# TASK BRIEF: Task 2.2 - FTS5 Symbol Search & Ranking Tool

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` (Section 2.2: `docs.db` Relational Topology & FTS5 Indexing).
- Read `specs/phases/phase-02-mcp-knowledge-server/tasks/task-2.1-mcp-server-core.md`.

---

## 2. Objective
Implement the `search_symbols` MCP tool inside `mcp_server/tools/search.py` and register it with the FastMCP application. This tool executes BM25-ranked full-text search queries against `symbols_fts` and returns lightweight symbol signatures to minimize sub-agent context consumption.

---

## 3. Scope & Detailed Requirements

### 3.1 Search Tool Implementation (`mcp_server/tools/search.py`)
1. **Tool Signature & Description:**
   ```python
   @mcp.tool()
   async def search_symbols(query: str, parent_scope: Optional[str] = None, limit: int = 10) -> str:
       """Search the local domain knowledge base for functions, classes, methods, or endpoints using BM25 full-text search.
       
       Args:
           query: Search terms, keywords, or partial symbol names (e.g. 'parse request', 'APIRoute', 'POST /users').
           parent_scope: Optional module, class, or route prefix filter.
           limit: Maximum number of results to return (default 10, max 25).
       """
   ```
2. **Query Sanitization & Execution:**
   - Sanitize raw query string to prevent FTS5 syntax errors (escape double quotes and unbalanced operators).
   - Format search tokens with prefix wildcarding (e.g., `term*`) to support partial symbol completion.
   - SQL Query Structure:
     ```sql
     SELECT 
         s.symbol_id, 
         s.symbol_type, 
         s.parent_scope, 
         s.signature, 
         s.return_type,
         s.is_destructive,
         snippet(symbols_fts, 3, '[', ']', '...', 16) AS matched_doc
     FROM symbols_fts f
     JOIN symbols s ON f.rowid = s.rowid
     WHERE symbols_fts MATCH :query
     ORDER BY rank
     LIMIT :limit;
     ```
   - If `parent_scope` is provided, append `AND s.parent_scope LIKE :scope`.
3. **Output Formatting:**
   - Return clean, structured markdown or JSON formatted string detailing:
     - `symbol_id`
     - `symbol_type` (`function`, `class`, `method`, `endpoint`)
     - `signature`
     - `return_type`
     - `matched_doc` snippet
   - If no matches found, return a clear guidance message suggesting broader keywords.

---

## 4. Deliverables
- `mcp_server/tools/search.py`
- `mcp_server/tools/__init__.py` (exposing search tools)

---

## 5. Verification Command
```bash
python3 -c "from mcp_server.server import mcp; from mcp_server.tools.search import search_symbols; print('Tool registered:', 'search_symbols' in [t.name for t in mcp._tool_manager.list_tools()])"
```
- **Exit Condition:** Returns `Tool registered: True`.
