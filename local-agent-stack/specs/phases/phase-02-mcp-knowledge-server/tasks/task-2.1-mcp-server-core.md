# TASK BRIEF: Task 2.1 - FastMCP Server Core & Read-Only SQLite Pool

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` (Section 4: Model Context Protocol Knowledge Server).
- Read `specs/phases/phase-01-scaffolding-storage/tasks/task-1.4-docs-db-fts5-schema.md`.

---

## 2. Objective
Implement the FastMCP application lifecycle and the read-only SQLite connection factory for `mcp_server`. The server must dynamically resolve the path to `docs.db` via environment variable or CLI parameter and establish safe, high-concurrency read connections using SQLite URI parameters.

---

## 3. Scope & Detailed Requirements

### 3.1 Read-Only Database Module (`mcp_server/db.py`)
1. **Path Resolution:**
   - Resolve `docs.db` path in order of precedence:
     1. Explicit `db_path` parameter passed to connection functions.
     2. `DOCS_DB_PATH` environment variable.
     3. Default fallback: `./docs.db` or `./.agent/docs.db`.
2. **Safe Read-Only Connection Factory:**
   - `async def get_readonly_docs_db(db_path: Optional[Path] = None) -> aiosqlite.Connection`
   - Must verify file existence before attempting to connect. Raise `FileNotFoundError` with a clear recovery message if missing.
   - Connect using SQLite URI: `f"file:{resolved_path.absolute()}?mode=ro"`.
   - Configure PRAGMAs:
     - `PRAGMA query_only = ON;`
     - `PRAGMA busy_timeout = 5000;`

### 3.2 FastMCP Server Lifecycle (`mcp_server/server.py`)
1. **Server Initialization:**
   - Initialize FastMCP server instance:
     ```python
     from mcp.server.fastmcp import FastMCP
     mcp = FastMCP("docs-db-knowledge-server")
     ```
2. **Context & State Management:**
   - Expose helper functions to configure active database targets dynamically.
   - Implement graceful lifecycle management ensuring open read connections close cleanly upon server shutdown.

---

## 4. Deliverables
- `mcp_server/db.py`
- `mcp_server/server.py`

---

## 5. Verification Command
```bash
python3 -c "import asyncio; from mcp_server.db import get_readonly_docs_db; from mcp_server.server import mcp; print('FastMCP initialized:', mcp.name)"
```
- **Exit Condition:** Server module imports without error and prints initialized instance name.
