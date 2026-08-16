# TASK BRIEF: Task 2.4 - Stdio Protocol Runner & CLI Invocation Script

---

## 1. Context References
- Read `specs/PRD.md` (Section 4.2: Universal MCP Server).
- Read `specs/phases/phase-02-mcp-knowledge-server/tasks/task-2.1-mcp-server-core.md` through `task-2.3-mcp-schema-tools.md`.

---

## 2. Objective
Create the executable CLI runner (`mcp_server/__main__.py`) to launch the FastMCP server over standard input/output (`stdio`) or HTTP/SSE, and implement the comprehensive Phase 2 pytest suite (`tests/phase_02/test_mcp_server.py` and `tests/phase_02/test_fts5_tools.py`).

---

## 3. Scope & Detailed Requirements

### 3.1 Main Execution Entrypoint (`mcp_server/__main__.py`)
1. **CLI Parameter Parsing (Click / Argparse):**
   - Support flags:
     - `--db-path` / `-d`: Path to target `docs.db` (sets `DOCS_DB_PATH`).
     - `--transport` / `-t`: Transport protocol (`stdio` or `sse`, default: `stdio`).
     - `--port` / `-p`: Port for SSE transport (default: `8001`).
2. **Server Execution:**
   - Import all tools from `mcp_server.tools` to ensure registration.
   - Run `mcp.run(transport=args.transport)`.

### 3.2 Integration Test Suite (`tests/phase_02/`)
1. **`tests/phase_02/test_mcp_server.py`:**
   - Fixture: Create temporary populated `docs.db` with sample functions, classes, parameters, and error codes.
   - Verify FastMCP tool listing includes `search_symbols`, `get_symbol_schema`, `get_symbol_examples`, and `list_error_codes`.
2. **`tests/phase_02/test_fts5_tools.py`:**
   - Test `search_symbols` with exact keyword matches.
   - Test `search_symbols` with prefix/fuzzy wildcard matches.
   - Test `get_symbol_schema` returns correct parameter types and required flags.
   - Test `get_symbol_examples` returns extracted snippets.
   - Test `list_error_codes` returns appropriate recovery actions.

---

## 4. Deliverables
- `mcp_server/__main__.py`
- `tests/phase_02/test_mcp_server.py`
- `tests/phase_02/test_fts5_tools.py`

---

## 5. Verification Command
```bash
pytest tests/phase_02/ -v
```
- **Exit Condition:** All tests pass with exit code `0`.
