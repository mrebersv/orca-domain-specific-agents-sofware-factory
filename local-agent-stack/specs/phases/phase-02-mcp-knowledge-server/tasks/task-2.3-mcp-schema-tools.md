# TASK BRIEF: Task 2.3 - Symbol Schema, Examples & Error Code Retrieval Tools

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` (Section 2.2: `docs.db` Relational Topology).
- Read `specs/phases/phase-02-mcp-knowledge-server/tasks/task-2.1-mcp-server-core.md`.

---

## 2. Objective
Implement the detailed symbol inspection tools (`get_symbol_schema`, `get_symbol_examples`, and `list_error_codes`) in `mcp_server/tools/schema.py` and register them with the FastMCP application.

---

## 3. Scope & Detailed Requirements

### 3.1 Schema & Detail Tools (`mcp_server/tools/schema.py`)

1. **`get_symbol_schema` Tool:**
   ```python
   @mcp.tool()
   async def get_symbol_schema(symbol_id: str) -> str:
       """Retrieve full typed parameter signatures, parameter descriptions, return types, and docstrings for a specific symbol.
       
       Args:
           symbol_id: Exact symbol identifier returned from search_symbols (e.g. 'fastapi.routing.APIRoute').
       """
   ```
   - Query `symbols` table for base definition.
   - Query `parameters` table for all associated parameters (`name`, `param_type`, `default_value`, `is_required`, `description`) ordered by `id ASC`.
   - Format output as a complete, typed API reference block.

2. **`get_symbol_examples` Tool:**
   ```python
   @mcp.tool()
   async def get_symbol_examples(symbol_id: str) -> str:
       """Retrieve verified working code snippets and usage examples for a specific symbol.
       
       Args:
           symbol_id: Exact symbol identifier (e.g. 'fastapi.routing.APIRoute').
       """
   ```
   - Query `examples` table matching `symbol_id`.
   - Return all matched snippets with their `title` and `source_origin`.

3. **`list_error_codes` Tool:**
   ```python
   @mcp.tool()
   async def list_error_codes(symbol_id: Optional[str] = None) -> str:
       """Retrieve known error codes, failure meanings, and recovery actions for a symbol or the entire module.
       
       Args:
           symbol_id: Optional symbol identifier to filter specific error codes.
       """
   ```
   - Query `error_codes` table.
   - Return table of error codes, explanations, and exact remediation actions.

---

## 4. Deliverables
- `mcp_server/tools/schema.py`

---

## 5. Verification Command
```bash
python3 -c "from mcp_server.server import mcp; from mcp_server.tools.schema import get_symbol_schema, get_symbol_examples, list_error_codes; tools = [t.name for t in mcp._tool_manager.list_tools()]; print('Schema tools registered:', all(k in tools for k in ['get_symbol_schema', 'get_symbol_examples', 'list_error_codes']))"
```
- **Exit Condition:** Returns `Schema tools registered: True`.
