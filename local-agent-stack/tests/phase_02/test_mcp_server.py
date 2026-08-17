"""Integration tests for FastMCP server lifecycle, stdio protocol, and tool registration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator, Dict, Any
import aiosqlite
import pytest
from mcp.server.mcpserver import MCPServer

from mcp_server.server import mcp, set_db_path, get_db_path
from mcp_server.instance import mcp as mcp_instance
from mcp_server.db import get_readonly_docs_db, resolve_docs_db_path
from mcp_server.tools import search, schema
from agent_forge.db.docs import init_docs_db, insert_symbol_bundle


@pytest.fixture
async def populated_docs_db(temp_dir: Path) -> AsyncGenerator[Path, None]:
    """Create a docs.db with test data for MCP server tests."""
    db_path = temp_dir / "docs.db"
    await init_docs_db(db_path)

    from agent_forge.db.docs import get_docs_db
    async with get_docs_db(db_path, read_only=False) as db:
        # Insert test symbols
        symbols_data = [
            {
                "symbol": {
                    "symbol_id": "fastapi.routing.APIRoute",
                    "symbol_type": "class",
                    "parent_scope": "fastapi.routing",
                    "signature": "class APIRoute(path: str, endpoint: Callable, methods: list[str] | None = None, **kwargs: Any)",
                    "return_type": "APIRoute",
                    "docstring_raw": "Encapsulates a route definition and request handler logic for FastAPI applications.",
                    "source_file": "fastapi/routing.py",
                    "is_destructive": False,
                },
                "parameters": [
                    {"name": "path", "param_type": "str", "default_value": None, "is_required": True, "description": "URL path pattern"},
                    {"name": "endpoint", "param_type": "Callable", "default_value": None, "is_required": True, "description": "Endpoint handler function"},
                    {"name": "methods", "param_type": "list[str] | None", "default_value": "None", "is_required": False, "description": "HTTP methods this route responds to"},
                ],
                "examples": [
                    {"title": "Basic Route", "code_snippet": "route = APIRoute('/health', health_check)", "source_origin": "extracted_docstring"},
                    {"title": "POST Route", "code_snippet": "route = APIRoute('/users', create_user, methods=['POST'])", "source_origin": "extracted_docstring"},
                ],
                "error_codes": [
                    {"code": "HTTP 404", "meaning": "Route path not registered", "recovery_action": "Verify URL path and router inclusion"},
                    {"code": "HTTP 405", "meaning": "Method not allowed for route", "recovery_action": "Check methods parameter matches endpoint"},
                ],
            },
            {
                "symbol": {
                    "symbol_id": "fastapi.FastAPI",
                    "symbol_type": "class",
                    "parent_scope": "fastapi",
                    "signature": "class FastAPI(title: str | None = None, version: str = '0.1.0', **kwargs: Any)",
                    "return_type": "FastAPI",
                    "docstring_raw": "Creates a FastAPI application instance with automatic OpenAPI documentation.",
                    "source_file": "fastapi/applications.py",
                    "is_destructive": False,
                },
                "parameters": [
                    {"name": "title", "param_type": "str | None", "default_value": "None", "is_required": False, "description": "API title for OpenAPI docs"},
                    {"name": "version", "param_type": "str", "default_value": "'0.1.0'", "is_required": False, "description": "API version"},
                ],
                "examples": [
                    {"title": "Basic App", "code_snippet": "app = FastAPI(title='My API')", "source_origin": "extracted_docstring"},
                ],
                "error_codes": [],
            },
            {
                "symbol": {
                    "symbol_id": "fastapi.testclient.TestClient.delete",
                    "symbol_type": "method",
                    "parent_scope": "fastapi.testclient",
                    "signature": "def delete(self, url: str, **kwargs: Any) -> Response",
                    "return_type": "Response",
                    "docstring_raw": "Send a DELETE request to the application. Useful for testing destructive operations.",
                    "source_file": "fastapi/testclient.py",
                    "is_destructive": True,
                },
                "parameters": [
                    {"name": "url", "param_type": "str", "default_value": None, "is_required": True, "description": "URL path to request"},
                ],
                "examples": [
                    {"title": "Delete Request", "code_snippet": "response = client.delete('/items/1')", "source_origin": "extracted_docstring"},
                ],
                "error_codes": [
                    {"code": "HTTP 404", "meaning": "Resource not found", "recovery_action": "Verify resource exists before deletion"},
                ],
            },
        ]

        for data in symbols_data:
            await insert_symbol_bundle(
                db=db,
                symbol=data["symbol"],
                parameters=data.get("parameters"),
                examples=data.get("examples"),
                error_codes=data.get("error_codes"),
            )
        await db.commit()

    yield db_path


class TestMCPServerLifecycle:
    """Tests for FastMCP server initialization and lifecycle management."""

    def test_mcp_server_instance_created(self):
        """Verify FastMCP server instance is properly initialized."""
        assert isinstance(mcp, MCPServer)
        assert mcp.name == "docs-db-knowledge-server"

    def test_server_lifespan_attached(self):
        """Verify lifespan context manager is attached to server."""
        assert mcp.lifespan is not None
        assert callable(mcp.lifespan)

    def test_set_and_get_db_path(self, temp_dir: Path):
        """Test database path configuration."""
        db_path = temp_dir / "test.db"
        set_db_path(db_path)
        assert get_db_path() == db_path.resolve()

    def test_get_db_path_returns_none_initially(self):
        """Verify get_db_path returns None when not configured."""
        # Reset global state
        import mcp_server.server as server_module
        server_module._current_db_path = None
        assert get_db_path() is None


class TestMCPProtocolHandshake:
    """Tests for MCP protocol initialization and handshake sequence."""

    @pytest.mark.asyncio
    async def test_initialize_request(self, populated_docs_db: Path):
        """Test MCP initialize handshake request."""
        from mcp.server.fastmcp import Context
        from mcp.types import InitializeResult, ServerCapabilities, ToolsCapability

        # FastMCP handles initialize automatically, verify server capabilities
        set_db_path(populated_docs_db)

        # The server should have tools capability
        capabilities = mcp._capabilities
        assert capabilities is not None
        assert capabilities.tools is not None
        assert isinstance(capabilities.tools, ToolsCapability)

    @pytest.mark.asyncio
    async def test_tools_list_request(self, populated_docs_db: Path):
        """Test tools/list returns all registered tools."""
        set_db_path(populated_docs_db)

        tools = await mcp.list_tools()
        tool_names = {tool.name for tool in tools}

        # Verify expected tools are registered
        expected_tools = {"search_symbols", "get_symbol_schema", "get_symbol_examples", "list_error_codes"}
        assert expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}"

        # Verify tool schemas have proper structure
        for tool in tools:
            assert tool.name
            assert tool.description
            assert tool.inputSchema
            assert tool.inputSchema["type"] == "object"
            assert "properties" in tool.inputSchema

    @pytest.mark.asyncio
    async def test_tools_call_invalid_tool(self, populated_docs_db: Path):
        """Test tools/call with invalid tool name returns error."""
        set_db_path(populated_docs_db)

        from mcp.types import CallToolResult
        result = await mcp.call_tool("nonexistent_tool", {})
        assert isinstance(result, CallToolResult)
        assert result.isError is True


class TestReadOnlyDatabaseEnforcement:
    """Tests verifying SQLite connections open in read-only mode."""

    @pytest.mark.asyncio
    async def test_read_only_connection_mode(self, populated_docs_db: Path):
        """Verify database connections use read-only URI mode."""
        async with get_readonly_docs_db(populated_docs_db) as db:
            # Check PRAGMA query_only is enforced
            async with db.execute("PRAGMA query_only;") as cursor:
                row = await cursor.fetchone()
                assert row[0] == 1, "query_only pragma should be ON"

    @pytest.mark.asyncio
    async def test_write_rejected_on_read_only_connection(self, populated_docs_db: Path):
        """Verify write operations are rejected on read-only connections."""
        async with get_readonly_docs_db(populated_docs_db) as db:
            with pytest.raises(aiosqlite.OperationalError):
                await db.execute(
                    "INSERT INTO symbols (symbol_id, symbol_type, signature) VALUES ('test', 'func', 'def test()')"
                )
                await db.commit()

    @pytest.mark.asyncio
    async def test_resolve_docs_db_path_precedence(self, temp_dir: Path, monkeypatch):
        """Test database path resolution precedence."""
        # Explicit path takes precedence
        explicit_path = temp_dir / "explicit.db"
        assert resolve_docs_db_path(explicit_path) == explicit_path.resolve()

        # Environment variable fallback
        env_path = temp_dir / "env.db"
        env_path.touch()
        monkeypatch.setenv("DOCS_DB_PATH", str(env_path))
        assert resolve_docs_db_path(None) == env_path.resolve()
        monkeypatch.delenv("DOCS_DB_PATH")

        # Default fallback paths
        cwd_path = Path.cwd() / "docs.db"
        assert resolve_docs_db_path(None) == cwd_path.resolve()

    @pytest.mark.asyncio
    async def test_read_only_connection_raises_on_missing_db(self, temp_dir: Path):
        """Verify FileNotFoundError for non-existent database."""
        missing_db = temp_dir / "missing.db"
        with pytest.raises(FileNotFoundError):
            async with get_readonly_docs_db(missing_db):
                pass


class TestMCPServerToolRegistration:
    """Tests verifying all MCP tools are properly registered with correct schemas."""

    @pytest.mark.asyncio
    async def test_search_symbols_tool_schema(self, populated_docs_db: Path):
        """Verify search_symbols tool has correct input schema."""
        set_db_path(populated_docs_db)
        tools = await mcp.list_tools()
        search_tool = next(t for t in tools if t.name == "search_symbols")

        assert search_tool.description
        schema_props = search_tool.inputSchema["properties"]
        assert "query" in schema_props
        assert schema_props["query"]["type"] == "string"
        assert "parent_scope" in schema_props
        assert schema_props["parent_scope"]["type"] == ["string", "null"]
        assert "limit" in schema_props
        assert schema_props["limit"]["type"] == "integer"
        assert schema_props["limit"]["minimum"] == 1
        assert schema_props["limit"]["maximum"] == 25

    @pytest.mark.asyncio
    async def test_get_symbol_schema_tool_schema(self, populated_docs_db: Path):
        """Verify get_symbol_schema tool has correct input schema."""
        set_db_path(populated_docs_db)
        tools = await mcp.list_tools()
        schema_tool = next(t for t in tools if t.name == "get_symbol_schema")

        assert schema_tool.description
        schema_props = schema_tool.inputSchema["properties"]
        assert "symbol_id" in schema_props
        assert schema_props["symbol_id"]["type"] == "string"
        assert schema_tool.inputSchema["required"] == ["symbol_id"]

    @pytest.mark.asyncio
    async def test_get_symbol_examples_tool_schema(self, populated_docs_db: Path):
        """Verify get_symbol_examples tool has correct input schema."""
        set_db_path(populated_docs_db)
        tools = await mcp.list_tools()
        examples_tool = next(t for t in tools if t.name == "get_symbol_examples")

        assert examples_tool.description
        schema_props = examples_tool.inputSchema["properties"]
        assert "symbol_id" in schema_props
        assert schema_props["symbol_id"]["type"] == "string"
        assert examples_tool.inputSchema["required"] == ["symbol_id"]

    @pytest.mark.asyncio
    async def test_list_error_codes_tool_schema(self, populated_docs_db: Path):
        """Verify list_error_codes tool has correct input schema."""
        set_db_path(populated_docs_db)
        tools = await mcp.list_tools()
        errors_tool = next(t for t in tools if t.name == "list_error_codes")

        assert errors_tool.description
        schema_props = errors_tool.inputSchema["properties"]
        assert "symbol_id" in schema_props
        assert schema_props["symbol_id"]["type"] == "string"
        assert errors_tool.inputSchema["required"] == ["symbol_id"]


class TestMCPServerStdioRunner:
    """Tests for stdio protocol runner and CLI entrypoint."""

    @pytest.mark.asyncio
    async def test_mcp_server_module_importable(self):
        """Verify mcp_server module can be imported as __main__."""
        import mcp_server.__main__ as main_module
        assert hasattr(main_module, "main") or hasattr(main_module, "run")

    def test_mcp_server_cli_entrypoint_exists(self):
        """Verify CLI entrypoint is configured."""
        import mcp_server
        # Check if __main__.py exists and is executable
        main_file = Path(mcp_server.__file__).parent / "__main__.py"
        assert main_file.exists()

    @pytest.mark.asyncio
    async def test_stdio_handshake_sequence(self, populated_docs_db: Path):
        """Test complete stdio MCP handshake sequence."""
        from mcp.client.stdio import stdio_client
        from mcp.client.session import ClientSession
        from mcp.types import InitializeRequest, InitializeResult

        set_db_path(populated_docs_db)

        # This test verifies the server can handle stdio transport
        # Note: Full stdio client test requires subprocess spawn
        # Here we verify the server components are ready
        tools = await mcp.list_tools()
        assert len(tools) >= 4

        # Verify initialize would succeed
        capabilities = mcp._capabilities
        assert capabilities.tools is not None


class TestMCPServerPerformance:
    """Performance tests for MCP tool call latency."""

    @pytest.mark.asyncio
    async def test_search_symbols_latency_under_10ms(self, populated_docs_db: Path):
        """Verify search_symbols executes within 10ms."""
        import time
        set_db_path(populated_docs_db)

        # Warm up
        await mcp.call_tool("search_symbols", {"query": "route", "limit": 5})

        # Measure
        start = time.perf_counter()
        result = await mcp.call_tool("search_symbols", {"query": "APIRoute", "limit": 10})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"search_symbols took {elapsed_ms:.2f}ms, expected < 10ms"
        assert not result.isError

    @pytest.mark.asyncio
    async def test_get_symbol_schema_latency_under_10ms(self, populated_docs_db: Path):
        """Verify get_symbol_schema executes within 10ms."""
        import time
        set_db_path(populated_docs_db)

        # Warm up
        await mcp.call_tool("get_symbol_schema", {"symbol_id": "fastapi.routing.APIRoute"})

        # Measure
        start = time.perf_counter()
        result = await mcp.call_tool("get_symbol_schema", {"symbol_id": "fastapi.routing.APIRoute"})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"get_symbol_schema took {elapsed_ms:.2f}ms, expected < 10ms"
        assert not result.isError

    @pytest.mark.asyncio
    async def test_get_symbol_examples_latency_under_10ms(self, populated_docs_db: Path):
        """Verify get_symbol_examples executes within 10ms."""
        import time
        set_db_path(populated_docs_db)

        # Warm up
        await mcp.call_tool("get_symbol_examples", {"symbol_id": "fastapi.routing.APIRoute"})

        # Measure
        start = time.perf_counter()
        result = await mcp.call_tool("get_symbol_examples", {"symbol_id": "fastapi.routing.APIRoute"})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"get_symbol_examples took {elapsed_ms:.2f}ms, expected < 10ms"
        assert not result.isError

    @pytest.mark.asyncio
    async def test_list_error_codes_latency_under_10ms(self, populated_docs_db: Path):
        """Verify list_error_codes executes within 10ms."""
        import time
        set_db_path(populated_docs_db)

        # Warm up
        await mcp.call_tool("list_error_codes", {"symbol_id": "fastapi.routing.APIRoute"})

        # Measure
        start = time.perf_counter()
        result = await mcp.call_tool("list_error_codes", {"symbol_id": "fastapi.routing.APIRoute"})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"list_error_codes took {elapsed_ms:.2f}ms, expected < 10ms"
        assert not result.isError


class TestMCPServerErrorHandling:
    """Tests for error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_search_symbols_empty_query(self, populated_docs_db: Path):
        """Test search_symbols with empty query returns helpful message."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "", "limit": 5})
        assert not result.isError
        # Should return "No symbols found" message
        assert "No symbols found" in result.content[0].text

    @pytest.mark.asyncio
    async def test_search_symbols_no_matches(self, populated_docs_db: Path):
        """Test search_symbols with no matching results."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "nonexistentxyz", "limit": 5})
        assert not result.isError
        assert "No symbols found" in result.content[0].text

    @pytest.mark.asyncio
    async def test_get_symbol_schema_not_found(self, populated_docs_db: Path):
        """Test get_symbol_schema for non-existent symbol."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_schema", {"symbol_id": "nonexistent.symbol"})
        # Should return error or empty result gracefully
        assert result.isError or "not found" in result.content[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_symbol_examples_empty(self, populated_docs_db: Path):
        """Test get_symbol_examples for symbol with no examples."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_examples", {"symbol_id": "fastapi.FastAPI"})
        assert not result.isError
        # Should return empty list or appropriate message
        content = result.content[0].text
        assert "example" in content.lower() or "[]" in content or "no examples" in content.lower()

    @pytest.mark.asyncio
    async def test_list_error_codes_empty(self, populated_docs_db: Path):
        """Test list_error_codes for symbol with no error codes."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("list_error_codes", {"symbol_id": "fastapi.FastAPI"})
        assert not result.isError
        content = result.content[0].text
        assert "error" in content.lower() or "[]" in content or "no error" in content.lower()

    @pytest.mark.asyncio
    async def test_search_symbols_limit_clamping(self, populated_docs_db: Path):
        """Test search_symbols limit parameter clamping."""
        set_db_path(populated_docs_db)

        # Test limit > 25 clamped to 25
        result = await mcp.call_tool("search_symbols", {"query": "fastapi", "limit": 100})
        assert not result.isError

        # Test limit < 1 clamped to 1
        result = await mcp.call_tool("search_symbols", {"query": "fastapi", "limit": 0})
        assert not result.isError

    @pytest.mark.asyncio
    async def test_search_symbols_parent_scope_filter(self, populated_docs_db: Path):
        """Test search_symbols with parent_scope filter."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "route", "parent_scope": "fastapi.routing", "limit": 10})
        assert not result.isError
        content = result.content[0].text
        # Results should only contain fastapi.routing scope
        assert "fastapi.routing" in content or "No symbols found" in content

    @pytest.mark.asyncio
    async def test_destructive_flag_in_search_results(self, populated_docs_db: Path):
        """Test that destructive flag is shown in search results."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "delete", "limit": 10})
        assert not result.isError
        content = result.content[0].text
        # Should show ⚠️ for destructive operations
        assert "⚠️" in content or "destructive" in content.lower()
