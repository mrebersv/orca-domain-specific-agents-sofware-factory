"""Unit and integration tests for docs.db schemas, FTS5 BM25 search, and synchronization triggers."""

from __future__ import annotations

from pathlib import Path
import aiosqlite
import pytest
from agent_forge.db.docs import (
    get_docs_db,
    get_symbol_details,
    init_docs_db,
    insert_symbol_bundle,
    query_symbols_fts,
)


@pytest.mark.asyncio
async def test_docs_db_initialization_and_triggers(temp_dir: Path):
    db_path = temp_dir / "docs.db"
    await init_docs_db(db_path)

    async with get_docs_db(db_path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger');"
        ) as cursor:
            entities = {row["name"] for row in await cursor.fetchall()}
            expected_entities = {
                "symbols",
                "parameters",
                "examples",
                "error_codes",
                "symbols_fts",
                "symbols_ai",
                "symbols_ad",
                "symbols_au",
            }
            assert expected_entities.issubset(entities)


@pytest.mark.asyncio
async def test_fts5_insert_and_bm25_query(temp_dir: Path):
    db_path = temp_dir / "docs.db"
    await init_docs_db(db_path)

    async with get_docs_db(db_path) as db:
        symbol = {
            "symbol_id": "fastapi.routing.APIRoute",
            "symbol_type": "class",
            "parent_scope": "fastapi.routing",
            "signature": "class APIRoute(path: str, endpoint: Callable, ...)",
            "return_type": "APIRoute",
            "docstring_raw": "Encapsulates a route definition and request handler logic.",
            "source_file": "fastapi/routing.py",
            "is_destructive": False,
        }
        params = [
            {
                "name": "path",
                "param_type": "str",
                "default_value": None,
                "is_required": True,
                "description": "URL path pattern.",
            },
            {
                "name": "endpoint",
                "param_type": "Callable",
                "default_value": None,
                "is_required": True,
                "description": "Endpoint handler function.",
            },
        ]
        examples = [
            {
                "title": "Basic Route Creation",
                "code_snippet": "route = APIRoute('/health', health_check)",
                "source_origin": "extracted_docstring",
            }
        ]
        error_codes = [
            {
                "code": "HTTP 404",
                "meaning": "Route path not registered",
                "recovery_action": "Verify URL path and router inclusion",
            }
        ]

        await insert_symbol_bundle(
            db=db,
            symbol=symbol,
            parameters=params,
            examples=examples,
            error_codes=error_codes,
        )

        # Query 1: Exact keyword match
        results = await query_symbols_fts(db, query="handler logic")
        assert len(results) >= 1
        assert results[0]["symbol_id"] == "fastapi.routing.APIRoute"

        # Query 2: Partial prefix query
        prefix_results = await query_symbols_fts(db, query="APIRou")
        assert len(prefix_results) >= 1
        assert prefix_results[0]["symbol_id"] == "fastapi.routing.APIRoute"

        # Query 3: Scoped query filter
        scoped_results = await query_symbols_fts(
            db, query="route", parent_scope="fastapi.routing"
        )
        assert len(scoped_results) >= 1
        assert scoped_results[0]["parent_scope"] == "fastapi.routing"


@pytest.mark.asyncio
async def test_fts5_update_and_delete_triggers(temp_dir: Path):
    db_path = temp_dir / "docs.db"
    await init_docs_db(db_path)

    async with get_docs_db(db_path) as db:
        symbol = {
            "symbol_id": "test.unit.calculate_tax",
            "symbol_type": "function",
            "parent_scope": "test.unit",
            "signature": "def calculate_tax(amount: float) -> float:",
            "return_type": "float",
            "docstring_raw": "Calculates sales tax for given amount.",
            "source_file": "test/unit.py",
            "is_destructive": False,
        }
        await insert_symbol_bundle(db=db, symbol=symbol)

        # Verify initial index
        res = await query_symbols_fts(db, query="sales tax")
        assert len(res) == 1

        # Test Update Trigger (symbols_au)
        symbol["docstring_raw"] = "Computes value added tax and excise rates."
        await insert_symbol_bundle(db=db, symbol=symbol)

        old_res = await query_symbols_fts(db, query="sales tax")
        assert len(old_res) == 0

        new_res = await query_symbols_fts(db, query="excise rates")
        assert len(new_res) == 1

        # Test Delete Trigger (symbols_ad)
        await db.execute(
            "DELETE FROM symbols WHERE symbol_id = ?",
            ("test.unit.calculate_tax",),
        )
        await db.commit()

        deleted_res = await query_symbols_fts(db, query="excise rates")
        assert len(deleted_res) == 0


@pytest.mark.asyncio
async def test_get_symbol_details(temp_dir: Path):
    db_path = temp_dir / "docs.db"
    await init_docs_db(db_path)

    async with get_docs_db(db_path) as db:
        symbol = {
            "symbol_id": "test.math.divide",
            "symbol_type": "function",
            "parent_scope": "test.math",
            "signature": "def divide(a: float, b: float) -> float:",
            "return_type": "float",
            "docstring_raw": "Divides a by b.",
            "source_file": "test/math.py",
            "is_destructive": False,
        }
        params = [
            {
                "name": "a",
                "param_type": "float",
                "default_value": None,
                "is_required": True,
                "description": "Numerator",
            },
            {
                "name": "b",
                "param_type": "float",
                "default_value": "1.0",
                "is_required": False,
                "description": "Denominator",
            },
        ]
        errors = [
            {
                "code": "ZeroDivisionError",
                "meaning": "Denominator cannot be zero",
                "recovery_action": "Pass non-zero value for b",
            }
        ]

        await insert_symbol_bundle(
            db=db, symbol=symbol, parameters=params, error_codes=errors
        )

        details = await get_symbol_details(db, "test.math.divide")
        assert details is not None
        assert details["symbol_id"] == "test.math.divide"
        assert len(details["parameters"]) == 2
        assert details["parameters"][0]["name"] == "a"
        assert details["parameters"][1]["default_value"] == "1.0"
        assert len(details["error_codes"]) == 1
        assert details["error_codes"][0]["code"] == "ZeroDivisionError"


@pytest.mark.asyncio
async def test_read_only_docs_db_enforcement(temp_dir: Path):
    db_path = temp_dir / "docs.db"
    await init_docs_db(db_path)

    # Attempt write on read-only connection
    async with get_docs_db(db_path, read_only=True) as ro_db:
        with pytest.raises(aiosqlite.OperationalError):
            await ro_db.execute(
                "INSERT INTO symbols (symbol_id, symbol_type, signature) VALUES ('x', 'y', 'z')"
            )
            await ro_db.commit()
