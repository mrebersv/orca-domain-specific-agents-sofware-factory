"""FastMCP server lifecycle and application entrypoint for docs.db knowledge server."""

from __future__ import annotations

from contextlib import asynccontextmanager
from mcp.server.mcpserver import MCPServer

# Import the mcp instance from instance module
from mcp_server.instance import mcp

# Import tools to register them with the MCPServer instance
from mcp_server.tools import search, schema  # noqa: F401

# Import config for shared database path state
from mcp_server.config import set_db_path, get_db_path, _current_db_path

# Re-export for backward compatibility
__all__ = ["mcp", "set_db_path", "get_db_path", "_current_db_path"]


@asynccontextmanager
async def server_lifespan(_: MCPServer):
    """Manage server lifecycle - ensure clean shutdown."""
    try:
        yield
    finally:
        # Any cleanup logic would go here
        pass


# Attach lifespan to the MCPServer instance
mcp.lifespan = server_lifespan
