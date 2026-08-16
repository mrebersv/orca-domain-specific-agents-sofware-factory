"""Global stack registry and workflow state database driver (registry.db)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
import aiosqlite

DEFAULT_REGISTRY_PATH = Path.home() / ".local-agent-stack" / "registry.db"

REGISTRY_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    harness_type TEXT NOT NULL,
    harness_binary TEXT,
    model_name TEXT NOT NULL,
    model_endpoint TEXT NOT NULL,
    api_key_env_var TEXT,
    isolation_tier TEXT CHECK(isolation_tier IN ('subprocess', 'podman', 'docker')) DEFAULT 'subprocess',
    container_image TEXT,
    max_turns INTEGER DEFAULT 6,
    timeout_seconds INTEGER DEFAULT 60,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_tool_permissions (
    agent_id TEXT REFERENCES agents(agent_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    is_destructive BOOLEAN DEFAULT 0,
    requires_approval BOOLEAN DEFAULT 0,
    PRIMARY KEY (agent_id, tool_name)
);

CREATE TABLE IF NOT EXISTS workflows (
    workflow_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    dag_definition JSON NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT REFERENCES workflows(workflow_id),
    status TEXT CHECK(status IN (
        'pending', 'running', 'paused_approval_required', 
        'paused_gatekeeper_failed', 'completed', 'failed', 'aborted'
    )) NOT NULL,
    current_node_id TEXT,
    global_context JSON DEFAULT '{}',
    git_worktree_path TEXT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

CREATE TABLE IF NOT EXISTS node_execution_checkpoints (
    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    iteration INTEGER DEFAULT 1,
    node_status TEXT CHECK(node_status IN ('pending', 'executing', 'passed', 'failed', 'paused')) NOT NULL,
    input_artifacts JSON,
    output_artifacts JSON,
    stderr_log TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def resolve_registry_path(db_path: Optional[Path] = None) -> Path:
    """Resolves registry path, defaulting to ~/.local-agent-stack/registry.db."""
    if db_path is not None:
        return Path(db_path).resolve()
    return DEFAULT_REGISTRY_PATH.resolve()


@asynccontextmanager
async def get_registry_db(
    db_path: Optional[Path] = None,
) -> AsyncIterator[aiosqlite.Connection]:
    """Provides an asynchronous connection context manager to registry.db with foreign keys enabled."""
    target_path = resolve_registry_path(db_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(str(target_path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON;")
    await db.execute("PRAGMA journal_mode = WAL;")
    try:
        yield db
    finally:
        await db.close()


async def init_registry_db(db_path: Optional[Path] = None) -> None:
    """Initializes tables and schemas in registry.db idempotently."""
    async with get_registry_db(db_path) as db:
        await db.executescript(REGISTRY_SCHEMA_SQL)
        await db.commit()


async def register_agent(
    db: aiosqlite.Connection, agent_data: Dict[str, Any]
) -> None:
    """Inserts or updates an agent specification and its associated tool permissions."""
    agent_id = agent_data["agent_id"]

    query = """
    INSERT INTO agents (
        agent_id, name, description, harness_type, harness_binary,
        model_name, model_endpoint, api_key_env_var, isolation_tier,
        container_image, max_turns, timeout_seconds, is_active
    ) VALUES (
        :agent_id, :name, :description, :harness_type, :harness_binary,
        :model_name, :model_endpoint, :api_key_env_var, :isolation_tier,
        :container_image, :max_turns, :timeout_seconds, :is_active
    )
    ON CONFLICT(agent_id) DO UPDATE SET
        name = excluded.name,
        description = excluded.description,
        harness_type = excluded.harness_type,
        harness_binary = excluded.harness_binary,
        model_name = excluded.model_name,
        model_endpoint = excluded.model_endpoint,
        api_key_env_var = excluded.api_key_env_var,
        isolation_tier = excluded.isolation_tier,
        container_image = excluded.container_image,
        max_turns = excluded.max_turns,
        timeout_seconds = excluded.timeout_seconds,
        is_active = excluded.is_active;
    """
    await db.execute(
        query,
        {
            "agent_id": agent_id,
            "name": agent_data["name"],
            "description": agent_data["description"],
            "harness_type": agent_data.get("harness_type", "generic_cli"),
            "harness_binary": agent_data.get("harness_binary"),
            "model_name": agent_data.get("model_name", "local-slm"),
            "model_endpoint": agent_data.get(
                "model_endpoint", "http://127.0.0.1:8000/v1"
            ),
            "api_key_env_var": agent_data.get("api_key_env_var"),
            "isolation_tier": agent_data.get("isolation_tier", "subprocess"),
            "container_image": agent_data.get("container_image"),
            "max_turns": agent_data.get("max_turns", 6),
            "timeout_seconds": agent_data.get("timeout_seconds", 60),
            "is_active": 1 if agent_data.get("is_active", True) else 0,
        },
    )

    permissions = agent_data.get("permissions", {})
    allowed_tools = permissions.get("allowed_tools", [])
    require_approval = permissions.get("require_approval_for_destructive", False)

    await db.execute(
        "DELETE FROM agent_tool_permissions WHERE agent_id = ?", (agent_id,)
    )

    for tool_name in allowed_tools:
        is_destructive = 1 if "delete" in tool_name or "drop" in tool_name else 0
        await db.execute(
            """
            INSERT INTO agent_tool_permissions (agent_id, tool_name, is_destructive, requires_approval)
            VALUES (?, ?, ?, ?)
            """,
            (
                agent_id,
                tool_name,
                is_destructive,
                1 if (is_destructive and require_approval) else 0,
            ),
        )

    await db.commit()


async def get_agent(
    db: aiosqlite.Connection, agent_id: str
) -> Optional[Dict[str, Any]]:
    """Retrieves full agent configuration and tool permissions by agent ID."""
    async with db.execute(
        "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        agent_dict = dict(row)

    async with db.execute(
        "SELECT * FROM agent_tool_permissions WHERE agent_id = ?", (agent_id,)
    ) as cursor:
        perms = await cursor.fetchall()
        agent_dict["permissions"] = [dict(p) for p in perms]

    return agent_dict


async def list_agents(
    db: aiosqlite.Connection, active_only: bool = False
) -> List[Dict[str, Any]]:
    """Lists all registered agents."""
    query = (
        "SELECT * FROM agents WHERE is_active = 1"
        if active_only
        else "SELECT * FROM agents"
    )
    async with db.execute(query) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
