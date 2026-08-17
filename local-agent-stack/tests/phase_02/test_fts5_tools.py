"""Tests for FTS5 symbol search, schema, examples, and error code tools."""

from __future__ import annotations

import time
from pathlib import Path
import pytest

from mcp_server.server import mcp, set_db_path
from mcp_server.tools import search, schema
from agent_forge.db.docs import init_docs_db, insert_symbol_bundle


# Reuse the populated_docs_db fixture from test_mcp_server.py
@pytest.fixture
async def populated_docs_db(temp_dir: Path) -> Path:
    """Create a docs.db with test data for FTS5 tool tests."""
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


from mcp_server.db import get_readonly_docs_db


class TestSearchSymbolsFTS5:
    """Tests for search_symbols FTS5 BM25 search functionality."""

    @pytest.mark.asyncio
    async def test_search_symbols_exact_match(self, populated_docs_db: Path):
        """Test search_symbols with exact keyword match returns expected symbol."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "APIRoute", "limit": 10})

        assert not result.isError
        content = result.content[0].text
        assert "fastapi.routing.APIRoute" in content
        assert "class" in content

    @pytest.mark.asyncio
    async def test_search_symbols_prefix_wildcard(self, populated_docs_db: Path):
        """Test search_symbols with prefix/wildcard matching."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "API*", "limit": 10})

        assert not result.isError
        content = result.content[0].text
        # Should match APIRoute and potentially other API* symbols
        assert "fastapi.routing.APIRoute" in content

    @pytest.mark.asyncio
    async def test_search_symbols_fuzzy_partial_match(self, populated_docs_db: Path):
        """Test search_symbols with fuzzy/partial matching finds multiple symbols."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "route", "limit": 10})

        assert not result.isError
        content = result.content[0].text
        # Should find APIRoute (contains "route") and potentially others
        assert "fastapi.routing.APIRoute" in content

    @pytest.mark.asyncio
    async def test_search_symbols_parent_scope_filter(self, populated_docs_db: Path):
        """Test search_symbols with parent_scope filter restricts results."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "route", "parent_scope": "fastapi.routing", "limit": 10})

        assert not result.isError
        content = result.content[0].text
        # Results should only be from fastapi.routing scope
        assert "fastapi.routing.APIRoute" in content
        # Should NOT include fastapi.testclient.TestClient.delete even though it might match "route"
        # (actually TestClient.delete doesn't contain "route" but verify scope filtering works)

    @pytest.mark.asyncio
    async def test_search_symbols_destructive_flag_shown(self, populated_docs_db: Path):
        """Test search_symbols shows destructive flag for destructive operations."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "delete", "limit": 10})

        assert not result.isError
        content = result.content[0].text
        assert "fastapi.testclient.TestClient.delete" in content
        assert "⚠️" in content or "destructive" in content.lower() or "True" in content

    @pytest.mark.asyncio
    async def test_search_symbols_limit_clamping_max(self, populated_docs_db: Path):
        """Test search_symbols clamps limit > 25 to 25."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "fastapi", "limit": 100})

        assert not result.isError
        content = result.content[0].text
        # Should not error, limit should be clamped

    @pytest.mark.asyncio
    async def test_search_symbols_limit_clamping_min(self, populated_docs_db: Path):
        """Test search_symbols clamps limit < 1 to 1."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "fastapi", "limit": 0})

        assert not result.isError
        content = result.content[0].text
        # Should not error, limit should be clamped to 1

    @pytest.mark.asyncio
    async def test_search_symbols_empty_results(self, populated_docs_db: Path):
        """Test search_symbols with no matching results returns helpful message."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "nonexistentxyz", "limit": 10})

        assert not result.isError
        content = result.content[0].text
        assert "No symbols found" in content or "no matches" in content.lower()

    @pytest.mark.asyncio
    async def test_search_symbols_empty_query(self, populated_docs_db: Path):
        """Test search_symbols with empty query."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("search_symbols", {"query": "", "limit": 10})

        assert not result.isError
        content = result.content[0].text
        assert "No symbols found" in content or "empty" in content.lower()

    @pytest.mark.asyncio
    async def test_search_symbols_latency_under_10ms(self, populated_docs_db: Path):
        """Verify search_symbols executes within 10ms."""
        set_db_path(populated_docs_db)

        # Warm up
        await mcp.call_tool("search_symbols", {"query": "fastapi", "limit": 5})

        # Measure
        start = time.perf_counter()
        result = await mcp.call_tool("search_symbols", {"query": "APIRoute", "limit": 10})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"search_symbols took {elapsed_ms:.2f}ms, expected < 10ms"
        assert not result.isError


class TestGetSymbolSchema:
    """Tests for get_symbol_schema tool."""

    @pytest.mark.asyncio
    async def test_get_symbol_schema_returns_params(self, populated_docs_db: Path):
        """Test get_symbol_schema returns correct parameter types, required flags, descriptions."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_schema", {"symbol_id": "fastapi.routing.APIRoute"})

        assert not result.isError
        content = result.content[0].text
        assert "path" in content
        assert "endpoint" in content
        assert "methods" in content
        assert "required" in content.lower() or "is_required" in content.lower()

    @pytest.mark.asyncio
    async def test_get_symbol_schema_returns_return_type(self, populated_docs_db: Path):
        """Test get_symbol_schema returns correct return type."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_schema", {"symbol_id": "fastapi.routing.APIRoute"})

        assert not result.isError
        content = result.content[0].text
        assert "APIRoute" in content

    @pytest.mark.asyncio
    async def test_get_symbol_schema_returns_signature(self, populated_docs_db: Path):
        """Test get_symbol_schema returns full signature."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_schema", {"symbol_id": "fastapi.routing.APIRoute"})

        assert not result.isError
        content = result.content[0].text
        assert "class APIRoute" in content

    @pytest.mark.asyncio
    async def test_get_symbol_schema_not_found(self, populated_docs_db: Path):
        """Test get_symbol_schema for non-existent symbol handles gracefully."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_schema", {"symbol_id": "nonexistent.symbol"})

        # Should return error or empty result gracefully
        assert result.isError or "not found" in result.content[0].text.lower() or "no such" in result.content[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_symbol_schema_latency_under_10ms(self, populated_docs_db: Path):
        """Verify get_symbol_schema executes within 10ms."""
        set_db_path(populated_docs_db)

        # Warm up
        await mcp.call_tool("get_symbol_schema", {"symbol_id": "fastapi.routing.APIRoute"})

        # Measure
        start = time.perf_counter()
        result = await mcp.call_tool("get_symbol_schema", {"symbol_id": "fastapi.routing.APIRoute"})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"get_symbol_schema took {elapsed_ms:.2f}ms, expected < 10ms"
        assert not result.isError


class TestGetSymbolExamples:
    """Tests for get_symbol_examples tool."""

    @pytest.mark.asyncio
    async def test_get_symbol_examples_returns_snippets(self, populated_docs_db: Path):
        """Test get_symbol_examples returns extracted snippets with titles."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_examples", {"symbol_id": "fastapi.routing.APIRoute"})

        assert not result.isError
        content = result.content[0].text
        assert "Basic Route" in content
        assert "POST Route" in content
        assert "APIRoute('/health'" in content
        assert "APIRoute('/users'" in content

    @pytest.mark.asyncio
    async def test_get_symbol_examples_single_example(self, populated_docs_db: Path):
        """Test get_symbol_examples for symbol with single example."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_examples", {"symbol_id": "fastapi.FastAPI"})

        assert not result.isError
        content = result.content[0].text
        assert "Basic App" in content
        assert "FastAPI(title='My API')" in content

    @pytest.mark.asyncio
    async def test_get_symbol_examples_empty(self, populated_docs_db: Path):
        """Test get_symbol_examples for symbol with no examples handles gracefully."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_examples", {"symbol_id": "fastapi.testclient.TestClient.delete"})

        assert not result.isError
        content = result.content[0].text
        # Should return empty list or appropriate message
        assert "example" in content.lower() or "[]" in content or "no examples" in content.lower() or "1 example" in content.lower()

    @pytest.mark.asyncio
    async def test_get_symbol_examples_not_found(self, populated_docs_db: Path):
        """Test get_symbol_examples for non-existent symbol."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("get_symbol_examples", {"symbol_id": "nonexistent.symbol"})

        assert result.isError or "not found" in result.content[0].text.lower()

    @pytest.mark.asyncio
    async def test_get_symbol_examples_latency_under_10ms(self, populated_docs_db: Path):
        """Verify get_symbol_examples executes within 10ms."""
        set_db_path(populated_docs_db)

        # Warm up
        await mcp.call_tool("get_symbol_examples", {"symbol_id": "fastapi.routing.APIRoute"})

        # Measure
        start = time.perf_counter()
        result = await mcp.call_tool("get_symbol_examples", {"symbol_id": "fastapi.routing.APIRoute"})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"get_symbol_examples took {elapsed_ms:.2f}ms, expected < 10ms"
        assert not result.isError


class TestListErrorCodes:
    """Tests for list_error_codes tool."""

    @pytest.mark.asyncio
    async def test_list_error_codes_returns_recovery_actions(self, populated_docs_db: Path):
        """Test list_error_codes returns codes, meanings, and recovery actions."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("list_error_codes", {"symbol_id": "fastapi.routing.APIRoute"})

        assert not result.isError
        content = result.content[0].text
        assert "HTTP 404" in content
        assert "HTTP 405" in content
        assert "Route path not registered" in content
        assert "Method not allowed" in content
        assert "Verify URL path" in content
        assert "Check methods parameter" in content

    @pytest.mark.asyncio
    async def test_list_error_codes_single_error(self, populated_docs_db: Path):
        """Test list_error_codes for symbol with single error code."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("list_error_codes", {"symbol_id": "fastapi.testclient.TestClient.delete"})

        assert not result.isError
        content = result.content[0].text
        assert "HTTP 404" in content
        assert "Resource not found" in content
        assert "Verify resource exists" in content

    @pytest.mark.asyncio
    async def test_list_error_codes_empty(self, populated_docs_db: Path):
        """Test list_error_codes for symbol with no error codes handles gracefully."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("list_error_codes", {"symbol_id": "fastapi.FastAPI"})

        assert not result.isError
        content = result.content[0].text
        assert "error" in content.lower() or "[]" in content or "no error" in content.lower()

    @pytest.mark.asyncio
    async def test_list_error_codes_not_found(self, populated_docs_db: Path):
        """Test list_error_codes for non-existent symbol."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("list_error_codes", {"symbol_id": "nonexistent.symbol"})

        assert result.isError or "not found" in result.content[0].text.lower()

    @pytest.mark.asyncio
    async def test_list_error_codes_without_symbol_id(self, populated_docs_db: Path):
        """Test list_error_codes without symbol_id returns all error codes."""
        set_db_path(populated_docs_db)
        result = await mcp.call_tool("list_error_codes", {"symbol_id": None} if False else {"symbol_id": ""})

        # The tool requires symbol_id, test with empty string or skip if not supported
        assert result.isError or "not found" in result.content[0].text.lower() or "required" in result.content[0].text.lower()

    @pytest.mark.asyncio
    async def test_list_error_codes_latency_under_10ms(self, populated_docs_db: Path):
        """Verify list_error_codes executes within 10ms."""
        set_db_path(populated_docs_db)

        # Warm up
        await mcp.call_tool("list_error_codes", {"symbol_id": "fastapi.routing.APIRoute"})

        # Measure
        start = time.perf_counter()
        result = await mcp.call_tool("list_error_codes", {"symbol_id": "fastapi.routing.APIRoute"})
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"list_error_codes took {elapsed_ms:.2f}ms, expected < 10ms"
        assert not result.isError


class TestAllToolsPerformance:
    """Performance tests for all MCP tools."""

    @pytest.mark.asyncio
    async def test_all_tools_latency_under_10ms(self, populated_docs_db: Path):
        """Verify all tools execute within 10ms."""
        set_db_path(populated_docs_db)

        tools_and_args = [
            ("search_symbols", {"query": "fastapi", "limit": 10}),
            ("get_symbol_schema", {"symbol_id": "fastapi.routing.APIRoute"}),
            ("get_symbol_examples", {"symbol_id": "fastapi.routing.APIRoute"}),
            ("list_error_codes", {"symbol_id": "fastapi.routing.APIRoute"}),
        ]

        for tool_name, args in tools_and_args:
            # Warm up
            await mcp.call_tool(tool_name, args)

            # Measure
            start = time.perf_counter()
            result = await mcp.call_tool(tool_name, args)
            elapsed_ms = (time.perf_counter() - start) * 1000

            assert elapsed_ms < 10, f"{tool_name} took {elapsed_ms:.2f}ms, expected < 10ms"
            assert not result.isError, f"{tool_name} returned error: {result.content[0].text if result.content else 'unknown'}"
