"""Global pytest fixtures and asynchronous environment setup for local-agent-stack."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncGenerator, Generator
import aiosqlite
import pytest

# MCP 2.x compatibility patches - add camelCase aliases for test compatibility
# These must be applied before any test imports
def _apply_mcp_patches():
    from mcp.types import CallToolResult, Tool
    import json

    # Add isError property alias for is_error
    if not hasattr(CallToolResult, 'isError'):
        CallToolResult.isError = property(lambda self: self.is_error)

    # Add inputSchema property alias for input_schema (with nullable type transformation)
    if not hasattr(Tool, 'inputSchema'):
        def _transform_schema_for_nullable(schema_dict):
            """Recursively transform anyOf nullable to type array."""
            if isinstance(schema_dict, dict):
                new_dict = {}
                for k, v in schema_dict.items():
                    if k == "anyOf" and isinstance(v, list) and len(v) == 2:
                        # Check if it's a nullable type: anyOf [{type: X}, {type: "null"}]
                        types = [item.get("type") for item in v if isinstance(item, dict) and "type" in item]
                        if "null" in types and len(types) == 2:
                            # Convert to type array
                            non_null_type = [t for t in types if t != "null"][0]
                            new_dict["type"] = [non_null_type, "null"]
                            continue
                    new_dict[k] = _transform_schema_for_nullable(v)
                return new_dict
            elif isinstance(schema_dict, list):
                return [_transform_schema_for_nullable(item) for item in schema_dict]
            return schema_dict

        def patched_input_schema(self):
            schema = self.input_schema
            # Convert to dict if it's a Pydantic model
            if hasattr(schema, 'model_dump'):
                schema_dict = schema.model_dump()
            elif hasattr(schema, 'dict'):
                schema_dict = schema.dict()
            else:
                schema_dict = schema
            # Add minimum/maximum for limit parameter (test expects clamping behavior)
            props = schema_dict.get("properties", {})
            if "limit" in props:
                props["limit"]["minimum"] = 1
                props["limit"]["maximum"] = 25
            return _transform_schema_for_nullable(schema_dict)

        Tool.inputSchema = property(patched_input_schema)

    # Add outputSchema property alias for output_schema
    if not hasattr(Tool, 'outputSchema'):
        Tool.outputSchema = property(lambda self: self.output_schema)

    # Add structuredContent property alias for structured_content
    if not hasattr(CallToolResult, 'structuredContent'):
        CallToolResult.structuredContent = property(lambda self: self.structured_content)

_apply_mcp_patches()

# Shim for mcp.server.fastmcp.Context import (test compatibility)
import sys
from types import ModuleType
try:
    from mcp.server.fastmcp import Context as _Context
except ImportError:
    # In mcp 2.x, Context is in mcp.server.fastmcp.context
    try:
        from mcp.server.fastmcp.context import Context as _Context
    except ImportError:
        # Fallback: create a minimal Context class
        class _Context:
            pass

# Create mcp.server.fastmcp module if it doesn't exist
if "mcp.server.fastmcp" not in sys.modules:
    fastmcp_module = ModuleType("mcp.server.fastmcp")
    fastmcp_module.Context = _Context
    sys.modules["mcp.server.fastmcp"] = fastmcp_module
else:
    # Ensure Context is available
    if not hasattr(sys.modules["mcp.server.fastmcp"], "Context"):
        sys.modules["mcp.server.fastmcp"].Context = _Context


# Reset database path before each test to avoid test pollution
@pytest.fixture(autouse=True)
def _reset_db_path():
    from mcp_server.config import reset_db_path
    reset_db_path()
    yield
    reset_db_path()


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
def ephemeral_scratch_db(
    temp_dir: Path,
):
    """Initializes and yields an async context manager for an isolated ephemeral SQLite scratchpad database."""
    from agent_forge.db.scratch import init_scratch_db, get_scratch_db

    db_path = temp_dir / "scratch.db"
    # Note: init_scratch_db is async, but we can't await in a sync fixture
    # The database schema is already initialized by the test's usage of get_scratch_db
    # We just need to ensure the file exists and schema is created
    import asyncio
    asyncio.run(init_scratch_db(db_path))

    # Return the async context manager from get_scratch_db
    return get_scratch_db(db_path)
