"""Unit and integration tests for registry.db and scratch.db drivers."""

from __future__ import annotations

from pathlib import Path
import aiosqlite
import pytest
from agent_forge.db.registry import (
    get_agent,
    get_registry_db,
    init_registry_db,
    list_agents,
    register_agent,
)
from agent_forge.db.scratch import (
    get_scratch_db,
    init_scratch_db,
    list_artifacts,
    list_execution_turns,
    log_execution_turn,
    record_artifact,
)


@pytest.mark.asyncio
async def test_registry_db_schema_initialization(temp_dir: Path):
    db_path = temp_dir / "registry.db"
    await init_registry_db(db_path)

    async with get_registry_db(db_path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ) as cursor:
            tables = {row["name"] for row in await cursor.fetchall()}
            expected_tables = {
                "agents",
                "agent_tool_permissions",
                "workflows",
                "workflow_runs",
                "node_execution_checkpoints",
            }
            assert expected_tables.issubset(tables)


@pytest.mark.asyncio
async def test_register_and_get_agent(temp_dir: Path):
    db_path = temp_dir / "registry.db"
    await init_registry_db(db_path)

    agent_payload = {
        "agent_id": "test-builder-agent",
        "name": "Test Builder Agent",
        "description": "Specialized sub-agent for autonomous testing.",
        "harness_type": "claude-code",
        "model_name": "local-slm",
        "model_endpoint": "http://127.0.0.1:8000/v1",
        "isolation_tier": "subprocess",
        "max_turns": 6,
        "timeout_seconds": 90,
        "is_active": True,
        "permissions": {
            "allowed_tools": ["search_symbols", "delete_file", "write_file"],
            "require_approval_for_destructive": True,
        },
    }

    async with get_registry_db(db_path) as db:
        await register_agent(db, agent_payload)
        agent = await get_agent(db, "test-builder-agent")

        assert agent is not None
        assert agent["agent_id"] == "test-builder-agent"
        assert agent["name"] == "Test Builder Agent"
        assert agent["max_turns"] == 6
        assert agent["timeout_seconds"] == 90

        # Verify permissions and destructive action classification
        permissions = {p["tool_name"]: p for p in agent["permissions"]}
        assert "search_symbols" in permissions
        assert permissions["search_symbols"]["is_destructive"] == 0
        assert permissions["search_symbols"]["requires_approval"] == 0

        assert "delete_file" in permissions
        assert permissions["delete_file"]["is_destructive"] == 1
        assert permissions["delete_file"]["requires_approval"] == 1

        all_agents = await list_agents(db, active_only=True)
        assert len(all_agents) == 1
        assert all_agents[0]["agent_id"] == "test-builder-agent"


@pytest.mark.asyncio
async def test_registry_foreign_key_enforcement(temp_dir: Path):
    db_path = temp_dir / "registry.db"
    await init_registry_db(db_path)

    async with get_registry_db(db_path) as db:
        # Attempt inserting a permission for a non-existent agent_id
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO agent_tool_permissions (agent_id, tool_name) VALUES (?, ?)",
                ("non-existent-agent", "some_tool"),
            )
            await db.commit()


@pytest.mark.asyncio
async def test_scratch_db_logging_and_artifacts(temp_dir: Path):
    db_path = temp_dir / "scratch.db"
    await init_scratch_db(db_path)

    async with get_scratch_db(db_path) as db:
        turn_id = await log_execution_turn(
            db=db,
            session_id="sess_123",
            step_number=1,
            tool_called="search_symbols",
            tool_input={"query": "test query"},
            tool_output={"count": 2, "results": ["sym_a", "sym_b"]},
            status="success",
            execution_time_ms=14,
            workflow_run_id="run_abc",
        )
        assert turn_id > 0

        checksum = await record_artifact(
            db=db,
            artifact_id="art_001",
            session_id="sess_123",
            artifact_type="source_code",
            content_raw="print('hello world')",
            file_path="src/main.py",
            workflow_run_id="run_abc",
        )
        assert len(checksum) == 64  # SHA-256 hex string

        turns = await list_execution_turns(db, session_id="sess_123")
        assert len(turns) == 1
        assert turns[0]["tool_called"] == "search_symbols"
        assert turns[0]["tool_input"] == {"query": "test query"}
        assert turns[0]["tool_output"]["count"] == 2

        artifacts = await list_artifacts(db, session_id="sess_123")
        assert len(artifacts) == 1
        assert artifacts[0]["artifact_id"] == "art_001"
        assert artifacts[0]["checksum_sha256"] == checksum
