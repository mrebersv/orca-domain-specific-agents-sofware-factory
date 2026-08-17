"""Read-only SQLite connection factory for docs.db MCP server."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional
import os
import aiosqlite

from mcp_server.config import get_db_path


DEFAULT_DOCS_DB_PATHS = [
    Path.cwd() / "docs.db",
    Path.cwd() / ".agent" / "docs.db",
]


def resolve_docs_db_path(db_path: Optional[Path] = None) -> Path:
    """
    Resolve docs.db path in order of precedence:
    1. Explicit db_path parameter
    2. Global path set via set_db_path() (for testing and CLI)
    3. DOCS_DB_PATH environment variable
    4. Default fallback paths
    """
    if db_path is not None:
        return db_path.resolve()

    # Check global path set by set_db_path()
    global_path = get_db_path()
    if global_path is not None:
        return global_path.resolve()

    env_path = os.environ.get("DOCS_DB_PATH")
    if env_path:
        return Path(env_path).resolve()

    for default_path in DEFAULT_DOCS_DB_PATHS:
        if default_path.exists():
            return default_path.resolve()

    # Return first default path as fallback (will raise FileNotFoundError on connect)
    return DEFAULT_DOCS_DB_PATHS[0].resolve()


@asynccontextmanager
async def get_readonly_docs_db(
    db_path: Optional[Path] = None,
) -> AsyncIterator[aiosqlite.Connection]:
    """
    Provides a read-only SQLite connection to docs.db.

    Args:
        db_path: Optional explicit path to docs.db

    Yields:
        aiosqlite.Connection: Read-only connection with row_factory

    Raises:
        FileNotFoundError: If docs.db does not exist at resolved path
    """
    resolved_path = resolve_docs_db_path(db_path)

    if not resolved_path.exists():
        raise FileNotFoundError(
            f"Documentation database not found at: {resolved_path}. "
            f"Run 'forge ingest' to create it, or set DOCS_DB_PATH environment variable."
        )

    uri = f"file:{resolved_path.absolute()}?mode=ro"
    db = await aiosqlite.connect(uri, uri=True)
    db.row_factory = aiosqlite.Row

    try:
        await db.execute("PRAGMA query_only = ON;")
        await db.execute("PRAGMA busy_timeout = 5000;")
        yield db
    finally:
        await db.close()
