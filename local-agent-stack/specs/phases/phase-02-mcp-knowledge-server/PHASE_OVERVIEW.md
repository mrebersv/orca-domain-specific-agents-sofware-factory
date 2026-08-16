# PHASE 2 OVERVIEW: JIT Knowledge MCP Server

---

## 1. Phase Objective
Implement the Model Context Protocol (MCP) server package (`mcp_server`) using the official Python MCP SDK (`FastMCP`). This server exposes the JIT relational documentation engine (`docs.db`) over standard `stdio` and HTTP/SSE transports, enabling any MCP-compliant environment (Orca ADE, Claude Code, Cursor, Zed) to dynamically search symbol signatures, inspect typed parameter schemas, retrieve working examples, and resolve error recovery actions without context window bloat.

---

## 2. Task Breakdown & Execution Strategy

| Task ID | Task Title | Execution Mode | Dependencies | Primary Deliverables |
|---|---|---|---|---|
| **Task 2.1** | FastMCP Server Core & Read-Only SQLite Pool | Sequential (First) | Phase 1 Complete | `mcp_server/server.py`, `mcp_server/db.py` |
| **Task 2.2** | FTS5 Symbol Search & Ranking Tool | Parallel (`p2_tools`) | Task 2.1 | `mcp_server/tools/search.py` |
| **Task 2.3** | Symbol Schema, Examples & Error Code Tools | Parallel (`p2_tools`) | Task 2.1 | `mcp_server/tools/schema.py` |
| **Task 2.4** | Stdio Protocol Runner & CLI Entrypoint | Sequential (Last) | Task 2.2, Task 2.3 | `mcp_server/__main__.py`, `tests/phase_02/` |

### Dependency & Concurrency Graph
```
               [Task 2.1: FastMCP Server Core & db.py]
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
       [Task 2.2: search_symbols]      [Task 2.3: schema/examples]
       (FTS5 BM25 Ranked Tool)         (Detail Extraction Tools)
                  │                               │
                  └───────────────┬───────────────┘
                                  ▼
               [Task 2.4: Stdio Runner & CLI __main__.py]
                                  │
                                  ▼
                    [Phase 2 Gatekeeper Execution]
                      pytest tests/phase_02/ -v
```

---

## 3. Inter-Task Data Flow
1. **Task 2.1** initializes the `FastMCP("docs-db-knowledge-server")` app instance and implements an asynchronous, read-only (`file:...?mode=ro`) connection manager pointing to the active agent or project `docs.db`.
2. **Task 2.2** implements the `search_symbols` tool, taking natural language queries or symbol prefixes, querying the `symbols_fts` table, and formatting ranked results with signatures and parent scopes.
3. **Task 2.3** implements three granular inspection tools (`get_symbol_schema`, `get_symbol_examples`, `list_error_codes`), fetching complete typed parameter lists, code snippets, and failure recovery instructions.
4. **Task 2.4** creates the executable module entrypoint (`python -m mcp_server`) and integration test harness validating MCP JSON-RPC protocol compliance over stdio.

---

## 4. Phase Exit Gate Criteria

Before unlocking Phase 3, the Test Runner / Gatekeeper executes:

```bash
pytest tests/phase_02/ -v
```

### Mandatory Pass Invariants:
1. FastMCP server boots over stdio and responds to standard MCP protocol handshakes (`initialize`, `tools/list`, `tools/call`).
2. SQLite connections open strictly in read-only URI mode (`?mode=ro`), preventing concurrent write locks.
3. `search_symbols` returns valid BM25 ranked matches for partial and full queries.
4. `get_symbol_schema` returns structured signatures, docstrings, and typed parameter constraints.
5. `get_symbol_examples` and `list_error_codes` return formatted snippets or empty lists without throwing unhandled exceptions.
6. Execution latency per tool call is $< 10\text{ ms}$ on local databases.
