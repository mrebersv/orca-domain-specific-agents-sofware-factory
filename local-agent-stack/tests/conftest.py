"""Global pytest fixtures and asynchronous environment setup for local-agent-stack."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncGenerator, Generator
import aiosqlite
import pytest


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Provides a session-scoped asyncio event loop for all async test modules."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provides an isolated, clean temporary directory for individual test runs."""
    return tmp_path


@pytest.fixture
async def ephemeral_registry_db(
    temp_dir: Path,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Initializes and yields an isolated in-memory or ephemeral SQLite registry database."""
    from agent_forge.db.registry import get_registry_db, init_registry_db

    db_path = temp_dir / "registry.db"
    await init_registry_db(db_path)

    async with get_registry_db(db_path) as db:
        yield db


@pytest.fixture
async def ephemeral_docs_db(
    temp_dir: Path,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Initializes and yields an isolated ephemeral SQLite docs database with full FTS5 triggers."""
    from agent_forge.db.docs import get_docs_db, init_docs_db

    db_path = temp_dir / "docs.db"
    await init_docs_db(db_path)

    async with get_docs_db(db_path) as db:
        yield db


@pytest.fixture
async def ephemeral_scratch_db(
    temp_dir: Path,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Initializes and yields an isolated ephemeral SQLite scratchpad database."""
    from agent_forge.db.scratch import get_scratch_db, init_scratch_db

    db_path = temp_dir / "scratch.db"
    await init_scratch_db(db_path)

    async with get_scratch_db(db_path) as db:
        yield db
