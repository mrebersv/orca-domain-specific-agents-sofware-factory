# PHASE 1 OVERVIEW: Scaffolding, Packaging & Storage Foundation

---

## 1. Phase Objective
Establish the foundational Python packaging, installation automation, and SQLite database topologies (`registry.db`, `scratch.db`, and `docs.db` with native FTS5 full-text indexing and synchronization triggers). This phase delivers the runtime storage engine and package contracts required by all downstream agents, MCP servers, and orchestrators.

---

## 2. Task Breakdown & Execution Strategy

| Task ID | Task Title | Execution Mode | Dependencies | Primary Deliverables |
|---|---|---|---|---|
| **Task 1.1** | Python Packaging & Dependencies | Sequential (First) | None | `pyproject.toml`, `requirements.txt` |
| **Task 1.2** | Bootstrap Installation Script | Parallel (`p1_db_group`) | Task 1.1 | `install.sh` |
| **Task 1.3** | `registry.db` & `scratch.db` Schemas | Parallel (`p1_db_group`) | Task 1.1 | `agent_forge/db/registry.py`, `agent_forge/db/scratch.py`, `scripts/init_registry_db.py` |
| **Task 1.4** | `docs.db` Schema & FTS5 Triggers | Parallel (`p1_db_group`) | Task 1.1 | `agent_forge/db/docs.py`, `scripts/init_docs_db.py` |

### Dependency & Concurrency Graph
```
               [Task 1.1: pyproject.toml & requirements.txt]
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
  [Task 1.2: install.sh]   [Task 1.3: registry/scratch]   [Task 1.4: docs.db FTS5]
  (Bootstrapper)           (aiosqlite Driver)             (Triggers & BM25 Search)
        │                            │                            │
        └────────────────────────────┼────────────────────────────┘
                                     ▼
                      [Phase 1 Gatekeeper Execution]
                      pytest tests/phase_01/ -v
```

---

## 3. Inter-Task Data Flow
1. **Task 1.1** defines the build system (`hatchling` or `setuptools`), CLI entrypoints (`forge`, `vram-proxy`, `mcp-docs-db`), and dependencies (`fastapi`, `aiosqlite`, `mcp`, `pydantic`, `tree-sitter`, `docstring-parser`, `click`, `rich`).
2. **Task 1.2** consumes `pyproject.toml` to build an idempotent virtual environment, install the package in editable mode (`pip install -e .`), and initialize `~/.local-agent-stack/`.
3. **Task 1.3** implements the async relational drivers and DDL schemas for agent registries, tool permissions, workflow states, and ephemeral execution turns.
4. **Task 1.4** implements the JIT domain documentation schema, connection factory (with read-only `?mode=ro` support), and FTS5 virtual tables with automated insert/delete/update triggers.

---

## 4. Phase Exit Gate Criteria

Before unlocking Phase 2, the Test Runner / Gatekeeper executes the following command:

```bash
pytest tests/phase_01/ -v
```

### Mandatory Pass Invariants:
1. `pyproject.toml` installs cleanly in editable mode via `pip install -e .`.
2. `install.sh` runs idempotently without overwriting existing data.
3. `registry.db` enforces foreign key constraints (`PRAGMA foreign_keys = ON;`) on `agent_tool_permissions` and `node_execution_checkpoints`.
4. `docs.db` inserts into `symbols` synchronize to `symbols_fts` via triggers.
5. FTS5 BM25 queries against `symbols_fts` return matching records with valid ranking.
6. Zero test failures or unhandled deprecation warnings.
