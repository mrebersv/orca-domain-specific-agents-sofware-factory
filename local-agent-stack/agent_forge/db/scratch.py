"""Ephemeral execution scratchpad and step telemetry database driver (scratch.db)."""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
import aiosqlite

SCRATCH_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS execution_turns (
    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    workflow_run_id TEXT,
    step_number INTEGER NOT NULL,
    tool_called TEXT NOT NULL,
    tool_input JSON NOT NULL,
    tool_output JSON NOT NULL,
    status TEXT CHECK(status IN ('success', 'error', 'retry')),
    execution_time_ms INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    workflow_run_id TEXT,
    artifact_type TEXT NOT NULL,
    file_path TEXT,
    content_raw TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


@asynccontextmanager
async def get_scratch_db(
    db_path: Path,
) -> AsyncIterator[aiosqlite.Connection]:
    """Provides an asynchronous connection context manager to scratch.db."""
    resolved = Path(db_path).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(str(resolved))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode = WAL;")
    try:
        yield db
    finally:
        await db.close()


async def init_scratch_db(db_path: Path) -> None:
    """Initializes execution_turns and artifacts tables in scratch.db."""
    async with get_scratch_db(db_path) as db:
        await db.executescript(SCRATCH_SCHEMA_SQL)
        await db.commit()


async def log_execution_turn(
    db: aiosqlite.Connection,
    session_id: str,
    step_number: int,
    tool_called: str,
    tool_input: Dict[str, Any],
    tool_output: Dict[str, Any],
    status: str,
    execution_time_ms: int,
    workflow_run_id: Optional[str] = None,
) -> int:
    """Logs an individual tool call or agent turn step with serialized JSON payloads."""
    cursor = await db.execute(
        """
        INSERT INTO execution_turns (
            session_id, workflow_run_id, step_number, tool_called,
            tool_input, tool_output, status, execution_time_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            workflow_run_id,
            step_number,
            tool_called,
            json.dumps(tool_input),
            json.dumps(tool_output),
            status,
            execution_time_ms,
        ),
    )
    await db.commit()
    return cursor.lastrowid or 0


async def record_artifact(
    db: aiosqlite.Connection,
    artifact_id: str,
    session_id: str,
    artifact_type: str,
    content_raw: str,
    file_path: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
) -> str:
    """Persists a generated artifact with computed SHA-256 integrity hash."""
    sha256 = hashlib.sha256(content_raw.encode("utf-8")).hexdigest()
    await db.execute(
        """
        INSERT INTO artifacts (
            artifact_id, session_id, workflow_run_id, artifact_type,
            file_path, content_raw, checksum_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(artifact_id) DO UPDATE SET
            content_raw = excluded.content_raw,
            checksum_sha256 = excluded.checksum_sha256;
        """,
        (
            artifact_id,
            session_id,
            workflow_run_id,
            artifact_type,
            file_path,
            content_raw,
            sha256,
        ),
    )
    await db.commit()
    return sha256


async def list_execution_turns(
    db: aiosqlite.Connection, session_id: str
) -> List[Dict[str, Any]]:
    """Retrieves all execution turns for a session ordered chronologically."""
    async with db.execute(
        "SELECT * FROM execution_turns WHERE session_id = ? ORDER BY step_number ASC",
        (session_id,),
    ) as cursor:
        rows = await cursor.fetchall()
        turns = []
        for r in rows:
            t = dict(r)
            t["tool_input"] = json.loads(t["tool_input"])
            t["tool_output"] = json.loads(t["tool_output"])
            turns.append(t)
        return turns


async def list_artifacts(
    db: aiosqlite.Connection, session_id: str
) -> List[Dict[str, Any]]:
    """Retrieves all stored artifacts for a given execution session."""
    async with db.execute(
        "SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,),
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
