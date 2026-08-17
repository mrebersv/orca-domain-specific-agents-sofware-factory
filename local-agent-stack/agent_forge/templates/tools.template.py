"""Auto-generated tool wrappers for {{ name }} ({{ agent_id }})."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
import aiosqlite

# Database path - copied/symlinked to workspace
DOCS_DB_PATH = Path(__file__).parent / "docs.db"


async def get_db_connection():
    """Get a read-only connection to the docs database."""
    if not DOCS_DB_PATH.exists():
        raise FileNotFoundError(f"Documentation database not found at {DOCS_DB_PATH}")

    uri = f"file:{DOCS_DB_PATH.resolve()}?mode=ro"
    db = await aiosqlite.connect(uri, uri=True)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA query_only = ON;")
    return db


async def search_symbols(query: str, parent_scope: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]:
    """
    Search for symbols using FTS5 full-text search.

    Args:
        query: Search query string (supports wildcards and BM25 ranking)
        parent_scope: Optional parent scope filter (e.g., module or class name)
        limit: Maximum number of results (default: 10, max: 50)

    Returns:
        List of matching symbols with metadata and relevance scores.
    """
    db = await get_db_connection()
    try:
        # Sanitize query for FTS5
        import re
        cleaned = re.sub(r'[^\w\s\.\:\-\_]', " ", query).strip()
        if not cleaned:
            formatted_query = '""'
        else:
            tokens = [t for t in cleaned.split() if t]
            formatted_query = " ".join([f'"{t}"*' if not t.endswith("*") else f'"{t}"' for t in tokens])

        limit = max(1, min(limit, 50))

        if parent_scope:
            sql = """
            SELECT
                s.symbol_id,
                s.symbol_type,
                s.parent_scope,
                s.signature,
                s.return_type,
                s.is_destructive,
                snippet(symbols_fts, 3, '[', ']', '...', 16) AS matched_doc,
                bm25(symbols_fts) AS rank_score
            FROM symbols_fts f
            JOIN symbols s ON f.rowid = s.rowid
            WHERE symbols_fts MATCH ? AND s.parent_scope LIKE ?
            ORDER BY rank_score ASC
            LIMIT ?;
            """
            params = (formatted_query, f"{parent_scope}%", limit)
        else:
            sql = """
            SELECT
                s.symbol_id,
                s.symbol_type,
                s.parent_scope,
                s.signature,
                s.return_type,
                s.is_destructive,
                snippet(symbols_fts, 3, '[', ']', '...', 16) AS matched_doc,
                bm25(symbols_fts) AS rank_score
            FROM symbols_fts f
            JOIN symbols s ON f.rowid = s.rowid
            WHERE symbols_fts MATCH ?
            ORDER BY rank_score ASC
            LIMIT ?;
            """
            params = (formatted_query, limit)

        try:
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except aiosqlite.OperationalError:
            # Fallback to LIKE search
            fallback_sql = """
            SELECT symbol_id, symbol_type, parent_scope, signature, return_type, is_destructive, docstring_raw AS matched_doc, 1.0 AS rank_score
            FROM symbols
            WHERE symbol_id LIKE ? OR docstring_raw LIKE ?
            LIMIT ?;
            """
            like_term = f"%{query.strip()}%"
            async with db.execute(fallback_sql, (like_term, like_term, limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
    finally:
        await db.close()


async def get_symbol_schema(symbol_id: str) -> Optional[dict[str, Any]]:
    """
    Get complete schema for a symbol including parameters, examples, and error codes.

    Args:
        symbol_id: Full symbol identifier (e.g., 'module.Class.method')

    Returns:
        Complete symbol details or None if not found.
    """
    db = await get_db_connection()
    try:
        async with db.execute("SELECT * FROM symbols WHERE symbol_id = ?", (symbol_id,)) as cursor:
            symbol_row = await cursor.fetchone()
            if not symbol_row:
                return None
            details = dict(symbol_row)

        async with db.execute(
            "SELECT name, param_type, default_value, is_required, description FROM parameters WHERE symbol_id = ? ORDER BY id ASC",
            (symbol_id,),
        ) as cursor:
            details["parameters"] = [dict(p) for p in await cursor.fetchall()]

        async with db.execute(
            "SELECT title, code_snippet, source_origin FROM examples WHERE symbol_id = ?",
            (symbol_id,),
        ) as cursor:
            details["examples"] = [dict(e) for e in await cursor.fetchall()]

        async with db.execute(
            "SELECT code, meaning, recovery_action FROM error_codes WHERE symbol_id = ?",
            (symbol_id,),
        ) as cursor:
            details["error_codes"] = [dict(err) for err in await cursor.fetchall()]

        return details
    finally:
        await db.close()


async def list_all_symbols(
    symbol_type: Optional[str] = None,
    parent_scope: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    List symbols with optional filtering.

    Args:
        symbol_type: Filter by symbol type (function, method, class, endpoint, cli_command)
        parent_scope: Filter by parent scope
        limit: Maximum results (default: 100)

    Returns:
        List of symbols matching filters.
    """
    db = await get_db_connection()
    try:
        conditions = []
        params = []

        if symbol_type:
            conditions.append("symbol_type = ?")
            params.append(symbol_type)

        if parent_scope:
            conditions.append("parent_scope LIKE ?")
            params.append(f"{parent_scope}%")

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        sql = f"""
        SELECT symbol_id, symbol_type, parent_scope, signature, return_type, is_destructive, docstring_raw
        FROM symbols
        {where_clause}
        ORDER BY symbol_id
        LIMIT ?;
        """

        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
    finally:
        await db.close()


{% for tool in custom_tools %}
async def {{ tool.name }}({{ tool.signature }}) -> {{ tool.return_type }}:
    """
    {{ tool.description }}

    Args:
{% for param in tool.params %}
        {{ param.name }}: {{ param.description }}
{% endfor %}

    Returns:
        {{ tool.returns }}

    Raises:
        NotImplementedError: This is a generated stub. Implement the actual logic.
    """
    # TODO: Implement {{ tool.name }} logic
    raise NotImplementedError("{{ tool.name }} is a generated stub - implement actual logic")
{% endfor %}
