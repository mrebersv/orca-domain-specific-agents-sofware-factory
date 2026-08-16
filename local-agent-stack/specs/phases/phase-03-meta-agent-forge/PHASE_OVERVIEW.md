# PHASE 3 OVERVIEW: Meta-Agent Ingestion Engine (Agent Forge)

---

## 1. Phase Objective
Implement the automated extraction, scaffolding, and verification engine (`agent_forge`). Agent Forge automates the conversion of target source codebases (via deterministic Python AST analysis and docstring parsing) and external interfaces (via OpenAPI specs and CLI `--help` outputs) into relational SQLite schemas (`docs.db`). It also automatically generates isolated agent workspace assets (`prompt.md`, `tools.py`, `agent.config.json`) and runs synthetic dry-run verifications to validate generated tool signatures.

---

## 2. Task Breakdown & Execution Strategy

| Task ID | Task Title | Execution Mode | Dependencies | Primary Deliverables |
|---|---|---|---|---|
| **Task 3.1** | Path A Deterministic AST & Docstring Extractor | Parallel (`p3_parsers`) | Phase 1 & 2 Complete | `agent_forge/ast_extractor.py` |
| **Task 3.2** | Path B OpenAPI & CLI `--help` Spec Extractor | Parallel (`p3_parsers`) | Phase 1 & 2 Complete | `agent_forge/spec_extractor.py` |
| **Task 3.3** | Workspace Scaffolder: `tools.py`, `prompt.md`, `agent.config.json` | Sequential | Task 3.1, Task 3.2 | `agent_forge/scaffolder.py`, `agent_forge/templates/*` |
| **Task 3.4** | Synthetic Dry-Run Verification Harness | Sequential (Last) | Task 3.3 | `agent_forge/verifier.py`, `tests/phase_03/` |

### Dependency & Concurrency Graph
```
        ┌─────────────────────────────────────────────────────────┐
        │  Phase 1 & Phase 2 Complete (Storage & FastMCP Ready)   │
        └────────────────────────────┬────────────────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
    [Task 3.1: Python AST Extractor]       [Task 3.2: OpenAPI/CLI Extractor]
    (ast / docstring-parser -> docs.db)     (OpenAPI v3 / CLI help -> docs.db)
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     ▼
             [Task 3.3: Workspace Scaffolder & Templates]
             (Generates prompt.md, tools.py, config.json)
                                     │
                                     ▼
             [Task 3.4: Synthetic Dry-Run Verifier]
             (Mocks calls, logs traces to scratch.db)
                                     │
                                     ▼
                      [Phase 3 Gatekeeper Execution]
                       pytest tests/phase_03/ -v
```

---

## 3. Inter-Task Data Flow
1. **Task 3.1 (Path A)** traverses target Python project directories, parses module AST trees, extracts docstrings using `docstring-parser`, captures parameter types, return annotations, exceptions raised, and doctest examples, and populates `symbols`, `parameters`, `examples`, and `error_codes` in `docs.db`.
2. **Task 3.2 (Path B)** ingests REST OpenAPI specifications (JSON/YAML) and CLI command structures (parsing `--help` outputs), translating route definitions, query/body schemas, HTTP error codes, and CLI flags into corresponding `symbols` and `parameters` rows.
3. **Task 3.3** consumes the populated `docs.db` and agent configuration parameters to render minimal system prompts (`prompt.md` < 500 tokens), typed tool wrapper functions (`tools.py`), and runtime configuration manifests (`agent.config.json`) using templates.
4. **Task 3.4** provisions an ephemeral test workspace, loads generated `tools.py`, executes synthetic validation calls against mocked backends, records execution traces into `scratch.db`, and verifies that all scaffolded tools return valid responses without runtime exceptions.

---

## 4. Phase Exit Gate Criteria

Before unlocking Phase 4, the Test Runner / Gatekeeper executes:

```bash
pytest tests/phase_03/ -v
```

### Mandatory Pass Invariants:
1. Python AST parser processes valid Python 3.11/3.12 modules, correctly extracting classes, async/sync methods, typed parameters, default values, and docstrings.
2. OpenAPI parser correctly ingests REST endpoints, parameter schemas, request bodies, and error response models into `docs.db`.
3. Auto-sync FTS5 triggers in `docs.db` index all ingested symbols during extraction runs.
4. Scaffolder produces `prompt.md` files strictly under 500 tokens.
5. Scaffolder generates syntactically valid `tools.py` containing complete type annotations and docstrings.
6. Synthetic verifier executes generated tool modules and records verified turns and artifact records to `scratch.db`.
