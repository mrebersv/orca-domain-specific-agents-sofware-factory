# TASK BRIEF: Task 1.4 - docs.db Schema, Connection Manager & FTS5 Auto-Sync Triggers

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` -> Section 2.2 (`docs.db` DDL & FTS5 Virtual Table).

---

## 2. Objective
Implement the domain documentation SQLite engine (`docs.db`) featuring typed symbol indexing, parameter schemas, code examples, error recovery mappings, and native SQLite FTS5 full-text indexing with automated synchronization triggers.

---

## 3. Scope & Detailed Requirements

### 3.1 Docs Database Module (`agent_forge/db/docs.py`)
1. **Connection Management:**
   - `get_docs_db(db_path: Path, read_only: bool = False) -> aiosqlite.Connection`
   - When `read_only=True`, open using SQLite URI mode: `file:{db_path}?mode=ro`.
   - Enforce `PRAGMA foreign_keys = ON;`.
2. **DDL Creation (`init_docs_db(db_path: Path) -> None`):**
   - Tables:
     - `symbols` (`symbol_id`, `symbol_type`, `parent_scope`, `signature`, `return_type`, `docstring_raw`, `source_file`, `is_destructive`).
     - `parameters` (`id`, `symbol_id`, `name`, `param_type`, `default_value`, `is_required`, `description`).
     - `examples` (`example_id`, `symbol_id`, `title`, `code_snippet`, `source_origin`).
     - `error_codes` (`code`, `symbol_id`, `meaning`, `recovery_action`).
3. **FTS5 Virtual Table & Triggers:**
   - Create virtual table `symbols_fts USING fts5(symbol_id, parent_scope, signature, docstring_raw, content='symbols', content_rowid='rowid');`.
   - Create trigger `symbols_ai AFTER INSERT ON symbols`: inserts new row into `symbols_fts`.
   - Create trigger `symbols_ad AFTER DELETE ON symbols`: deletes row from `symbols_fts`.
   - Create trigger `symbols_au AFTER UPDATE ON symbols`: updates row in `symbols_fts`.
4. **Helper Query Methods:**
   - `query_symbols_fts(db: aiosqlite.Connection, query: str, limit: int = 10) -> List[Dict[str, Any]]`: Executes BM25 ranked search (`SELECT ... FROM symbols_fts WHERE symbols_fts MATCH :query ORDER BY rank LIMIT :limit`).
   - `get_symbol_details(db: aiosqlite.Connection, symbol_id: str) -> Optional[Dict[str, Any]]`: Returns joined symbol, parameter list, examples, and error codes.

### 3.2 Standalone CLI Initialization Script (`scripts/init_docs_db.py`)
- Python script that creates an empty, valid `docs.db` at a given target file path.

---

## 4. Deliverables
- `agent_forge/db/docs.py`
- `scripts/init_docs_db.py`

---

## 5. Verification Command
```bash
python3 -c "import asyncio; from agent_forge.db.docs import init_docs_db; from pathlib import Path; asyncio.run(init_docs_db(Path('/tmp/test_docs.db')))"
```
- **Exit Condition:** SQLite database initializes with `symbols`, `parameters`, `examples`, `error_codes`, and `symbols_fts` tables and triggers.
