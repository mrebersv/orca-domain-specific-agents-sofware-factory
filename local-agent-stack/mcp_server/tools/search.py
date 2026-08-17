"""FTS5 Symbol Search & Ranking Tool for MCP server."""

from __future__ import annotations

import re
from typing import Optional
from mcp_server.instance import mcp
from mcp_server.db import get_readonly_docs_db


def sanitize_fts5_query(raw_query: str) -> str:
    """
    Sanitize search query tokens and add wildcard prefixes for partial symbol matching.

    Args:
        raw_query: Raw search query string

    Returns:
        Sanitized FTS5 query with prefix wildcards
    """
    # Remove problematic FTS5 characters except word chars, dots, colons, hyphens, underscores, spaces
    cleaned = re.sub(r'[^\w\s\.\:\-\_]', ' ', raw_query).strip()
    if not cleaned:
        return '""'

    tokens = [t for t in cleaned.split() if t]
    # Add wildcard to each token for prefix matching
    return ' '.join([f'"{t}"*' if not t.endswith('*') else f'"{t}"' for t in tokens])


@mcp.tool()
async def search_symbols(query: str, parent_scope: Optional[str] = None, limit: int = 10) -> str:
    """
    Search the local domain knowledge base for functions, classes, methods, or endpoints 
    using BM25 full-text search.

    Args:
        query: Search terms, keywords, or partial symbol names (e.g. 'parse request', 'APIRoute', 'POST /users').
        parent_scope: Optional module, class, or route prefix filter.
        limit: Maximum number of results to return (default 10, max 25).

    Returns:
        Formatted markdown table of matching symbols with signatures and snippets.
    """
    # Clamp limit
    limit = max(1, min(limit, 25))

    # Sanitize query
    formatted_query = sanitize_fts5_query(query)

    try:
        async with get_readonly_docs_db() as db:
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

            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()

                if not rows:
                    return (
                        f"No symbols found matching '{query}'"
                        + (f" in scope '{parent_scope}'" if parent_scope else "")
                        + ". Try broader keywords or check spelling."
                    )

                # Format as markdown table
                lines = [
                    "| Symbol ID | Type | Scope | Signature | Return | Destructive | Match | Score |",
                    "|-----------|------|-------|-----------|--------|-------------|-------|-------|"
                ]

                for row in rows:
                    destructive = "⚠️" if row["is_destructive"] else ""
                    lines.append(
                        f"| `{row['symbol_id']}` | {row['symbol_type']} | "
                        f"{row['parent_scope'] or '-'} | {row['signature']} | "
                        f"{row['return_type'] or '-'} | {destructive} | "
                        f"{row['matched_doc']} | {row['rank_score']:.2f} |"
                    )

                return "\n".join(lines)

    except Exception as e:
        # Fallback to LIKE search if FTS5 query syntax fails
        try:
            async with get_readonly_docs_db() as db:
                fallback_sql = """
                SELECT symbol_id, symbol_type, parent_scope, signature, return_type, 
                       is_destructive, docstring_raw AS matched_doc, 1.0 AS rank_score
                FROM symbols
                WHERE symbol_id LIKE ? OR docstring_raw LIKE ?
                LIMIT ?;
                """
                like_term = f"%{query.strip()}%"
                async with db.execute(fallback_sql, (like_term, like_term, limit)) as cursor:
                    rows = await cursor.fetchall()

                    if not rows:
                        return (
                            f"No symbols found matching '{query}'"
                            + (f" in scope '{parent_scope}'" if parent_scope else "")
                            + ". Try broader keywords."
                        )

                    lines = [
                        "| Symbol ID | Type | Scope | Signature | Return | Destructive | Match | Score |",
                        "|-----------|------|-------|-----------|--------|-------------|-------|-------|"
                    ]

                    for row in rows:
                        destructive = "⚠️" if row["is_destructive"] else ""
                        lines.append(
                            f"| `{row['symbol_id']}` | {row['symbol_type']} | "
                            f"{row['parent_scope'] or '-'} | {row['signature']} | "
                            f"{row['return_type'] or '-'} | {destructive} | "
                            f"{row['matched_doc'][:50]}... | {row['rank_score']:.2f} |"
                        )

                    return "\n".join(lines) + "\n\n*(Fallback LIKE search used)*"
        except Exception as fallback_error:
            return f"Search failed: {str(e)} (fallback also failed: {str(fallback_error)})"
