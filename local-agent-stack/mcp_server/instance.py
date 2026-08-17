"""MCP server instance for docs.db knowledge server."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ServerCapabilities, ToolsCapability

# Initialize MCPServer - this is the single source of truth for the server instance
mcp = MCPServer("docs-db-knowledge-server")

# Add _capabilities property for test compatibility (MCP 2.x doesn't expose this directly)
@property
def _capabilities(self):
    return ServerCapabilities(tools=ToolsCapability(list_changed=False))

mcp.__class__._capabilities = _capabilities

# Wrap call_tool to handle unknown tools gracefully (return error result instead of raising)
_original_call_tool = mcp.call_tool

async def _wrapped_call_tool(name: str, arguments: dict, context=None):
    try:
        return await _original_call_tool(name, arguments, context)
    except ToolError as e:
        return CallToolResult(
            content=[TextContent(type="text", text=str(e))],
            is_error=True
        )

mcp.call_tool = _wrapped_call_tool
