"""Domain knowledge documentation engine and FTS5 full-text indexing driver (docs.db)."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
import aiosqlite

DOCS_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS symbols (
    symbol_id TEXT PRIMARY KEY,
    symbol_type TEXT NOT NULL,
    parent_scope TEXT,
    signature TEXT NOT NULL,
    return_type TEXT,
    docstring_raw TEXT,
    source_file TEXT,
    is_destructive BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id TEXT REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    param_type TEXT,
    default_value TEXT,
    is_required BOOLEAN NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS examples (
    example_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id TEXT REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    code_snippet TEXT NOT NULL,
    source_origin TEXT
);

CREATE TABLE IF NOT EXISTS error_codes (
    code TEXT NOT NULL,
    symbol_id TEXT REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    meaning TEXT NOT NULL,
    recovery_action TEXT NOT NULL,
    PRIMARY KEY (code, symbol_id)
);

-- Native SQLite FTS5 Virtual Table for BM25 search
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    symbol_id,
    parent_scope,
    signature,
    docstring_raw,
    content='symbols',
    content_rowid='rowid'
);

-- FTS5 Auto-Sync Triggers
CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
  INSERT INTO symbols_fts(rowid, symbol_id, parent_scope, signature, docstring_raw)
  VALUES (new.rowid, new.symbol_id, new.parent_scope, new.signature, new.docstring_raw);
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
  INSERT INTO symbols_fts(symbols_fts, rowid, symbol_id, parent_scope, signature, docstring_raw)
  VALUES('delete', old.rowid, old.symbol_id, old.parent_scope, old.signature, old.docstring_raw);
END;

CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
  INSERT INTO symbols_fts(symbols_fts, rowid, symbol_id, parent_scope, signature, docstring_raw)
  VALUES('delete', old.rowid, old.symbol_id, old.parent_scope, old.signature, old.docstring_raw);
  INSERT INTO symbols_fts(rowid, symbol_id, parent_scope, signature, docstring_raw)
  VALUES (new.rowid, new.symbol_id, new.parent_scope, new.signature, new.docstring_raw);
END;
"""


@asynccontextmanager
async def get_docs_db(
    db_path: Path, read_only: bool = False
) -> AsyncIterator[aiosqlite.Connection]:
    """Provides an asynchronous connection context manager to docs.db."""
    resolved = Path(db_path).resolve()

    if read_only:
        if not resolved.exists():
            raise FileNotFoundError(
                f"Documentation database not found at: {resolved}"
            )
        uri = f"file:{resolved}?mode=ro"
        db = await aiosqlite.connect(uri, uri=True)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA query_only = ON;")
    else:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(str(resolved))
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute("PRAGMA journal_mode = WAL;")

    try:
        yield db
    finally:
        await db.close()


async def init_docs_db(db_path: Path) -> None:
    """Initializes tables, FTS5 virtual tables, and triggers for docs.db."""
    async with get_docs_db(db_path, read_only=False) as db:
        await db.executescript(DOCS_SCHEMA_SQL)
        await db.commit()


def sanitize_fts5_query(raw_query: str) -> str:
    """Sanitizes search query tokens and adds wildcard prefixes for partial symbol matching."""
    cleaned = re.sub(r'[^\w\s\.\:\-\_]', " ", raw_query).strip()
    if not cleaned:
        return '""'
    tokens = [t for t in cleaned.split() if t]
    return " ".join([f'"{t}"*' if not t.endswith("*") else f'"{t}"' for t in tokens])


async def query_symbols_fts(
    db: aiosqlite.Connection,
    query: str,
    parent_scope: Optional[str] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Executes a BM25 full-text query against symbols_fts and returns ranked symbol headers."""
    formatted_query = sanitize_fts5_query(query)
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
        # Fallback to direct LIKE search if FTS5 query syntax fails
        fallback_sql = """
        SELECT symbol_id, symbol_type, parent_scope, signature, return_type, is_destructive, docstring_raw AS matched_doc, 1.0 AS rank_score
        FROM symbols
        WHERE symbol_id LIKE ? OR docstring_raw LIKE ?
        LIMIT ?;
        """
        like_term = f"%{query.strip()}%"
        async with db.execute(
            fallback_sql, (like_term, like_term, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_symbol_details(
    db: aiosqlite.Connection, symbol_id: str
) -> Optional[Dict[str, Any]]:
    """Fetches comprehensive typed parameter list, examples, and error codes for a symbol."""
    async with db.execute(
        "SELECT * FROM symbols WHERE symbol_id = ?", (symbol_id,)
    ) as cursor:
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


async def insert_symbol_bundle(
    db: aiosqlite.Connection,
    symbol: Dict[str, Any],
    parameters: Optional[List[Dict[str, Any]]] = None,
    examples: Optional[List[Dict[str, Any]]] = None,
    error_codes: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Inserts a symbol and all related parameters, examples, and error codes in a single transaction."""
    symbol_id = symbol["symbol_id"]

    await db.execute(
        """
        INSERT INTO symbols (symbol_id, symbol_type, parent_scope, signature, return_type, docstring_raw, source_file, is_destructive)
        VALUES (:symbol_id, :symbol_type, :parent_scope, :signature, :return_type, :docstring_raw, :source_file, :is_destructive)
        ON CONFLICT(symbol_id) DO UPDATE SET
            symbol_type = excluded.symbol_type,
            parent_scope = excluded.parent_scope,
            signature = excluded.signature,
            return_type = excluded.return_type,
            docstring_raw = excluded.docstring_raw,
            source_file = excluded.source_file,
            is_destructive = excluded.is_destructive;
        """,
        {
            "symbol_id": symbol_id,
            "symbol_type": symbol["symbol_type"],
            "parent_scope": symbol.get("parent_scope"),
            "signature": symbol["signature"],
            "return_type": symbol.get("return_type"),
            "docstring_raw": symbol.get("docstring_raw"),
            "source_file": symbol.get("source_file"),
            "is_destructive": 1 if symbol.get("is_destructive") else 0,
        },
    )

    if parameters is not None:
        await db.execute(
            "DELETE FROM parameters WHERE symbol_id = ?", (symbol_id,)
        )
        for p in parameters:
            await db.execute(
                """
                INSERT INTO parameters (symbol_id, name, param_type, default_value, is_required, description)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol_id,
                    p["name"],
                    p.get("param_type"),
                    p.get("default_value"),
                    1 if p.get("is_required", True) else 0,
                    p.get("description"),
                ),
            )

    if examples is not None:
        await db.execute(
            "DELETE FROM examples WHERE symbol_id = ?", (symbol_id,)
        )
        for ex in examples:
            await db.execute(
                """
                INSERT INTO examples (symbol_id, title, code_snippet, source_origin)
                VALUES (?, ?, ?, ?)
                """,
                (
                    symbol_id,
                    ex["title"],
                    ex["code_snippet"],
                    ex.get("source_origin", "extracted_docstring"),
                ),
            )

    if error_codes is not None:
        await db.execute(
            "DELETE FROM error_codes WHERE symbol_id = ?", (symbol_id,)
        )
        for err in error_codes:
            await db.execute(
                """
                INSERT INTO error_codes (code, symbol_id, meaning, recovery_action)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(code, symbol_id) DO UPDATE SET
                    meaning = excluded.meaning,
                    recovery_action = excluded.recovery_action;
                """,
                (
                    err["code"],
                    symbol_id,
                    err["meaning"],
                    err["recovery_action"],
                ),
            )

    await db.commit()
