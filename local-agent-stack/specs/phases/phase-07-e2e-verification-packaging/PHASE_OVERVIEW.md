# PHASE 7 OVERVIEW: End-to-End Verification & CLI Packaging

---

## 1. Phase Objective
Deliver the unified CLI application (`forge`) via `agent_forge/cli.py` and implement comprehensive end-to-end verification suites (`tests/phase_07/`). This final phase binds together all prior components—storage drivers, FastMCP knowledge servers, AST/OpenAPI ingestion extractors, harness adapters, VRAM concurrency proxies, and Orca ADE worktree/TDD workflows—into a cohesive developer experience and validates the full pipeline against synthetic mock repositories.

---

## 2. Task Breakdown & Execution Strategy

| Task ID | Task Title | Execution Mode | Dependencies | Primary Deliverables |
|---|---|---|---|---|
| **Task 7.1** | Unified CLI Entrypoint (`forge` Commands) | Sequential (First) | Phase 1–6 Complete | `agent_forge/cli.py`, `tests/phase_07/test_cli_commands.py` |
| **Task 7.2** | Synthetic End-to-End Pipeline Test | Sequential (Last) | Task 7.1 | `tests/phase_07/test_e2e_pipeline.py` |

### Dependency & Concurrency Graph
```
        ┌─────────────────────────────────────────────────────────┐
        │  Phase 1–6 Complete (Full Core Subsystems Operational)  │
        └────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │  [Task 7.1: Unified CLI Interface (agent_forge/cli.py)] │
        │  • forge ingest (AST/OpenAPI -> docs.db)                │
        │  • forge init-orca (Orca manifest & hook setup)         │
        │  • forge scaffold (prompt.md, tools.py, config.json)    │
        │  • forge verify (Synthetic dry-run verifier)            │
        │  • forge run (Autonomous TDD orchestration driver)      │
        └────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │  [Task 7.2: Synthetic End-to-End Pipeline Integration]  │
        │  • Ingest Mock Library -> Populate docs.db              │
        │  • Query FastMCP over stdio                             │
        │  • Scaffold Sub-Agent & Verify Token Budget (< 500 tok) │
        │  • Provision Worktree -> Execute Turn -> Check scratch  │
        │  • Gatekeeper Assertion & Remediation Loop Check        │
        └────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
                      [Phase 7 Gatekeeper Execution]
                       pytest tests/phase_07/ -v
```

---

## 3. Inter-Task Data Flow
1. **Task 7.1** implements the global Click/Rich command-line suite registered in `pyproject.toml` under `forge`. It connects user inputs to internal modules:
   - `forge ingest` -> `agent_forge.ast_extractor` & `agent_forge.spec_extractor`
   - `forge init-orca` -> `orca_pack.generator`
   - `forge scaffold` -> `agent_forge.scaffolder`
   - `forge verify` -> `agent_forge.verifier`
   - `forge run` -> `orca_pack.workflows.tdd_workflow` & `scripts.run_autonomous_build`
   - `forge status` -> `agent_forge.db.registry`
2. **Task 7.2** implements the full-stack synthetic integration test in `tests/phase_07/test_e2e_pipeline.py`. It provisions an ephemeral test git repository, ingests a multi-file Python package into `docs.db`, starts an in-process FastMCP server, scaffolds a sub-agent, runs an agent turn inside an ephemeral worktree via `HarnessAdapter`, evaluates the Gatekeeper pytest report, and asserts complete audit trails in `scratch.db` and `registry.db`.

---

## 4. Phase Exit Gate Criteria

Before certifying the repository as production-ready, the Test Runner / Gatekeeper executes:

```bash
pytest tests/phase_07/ -v
```

### Mandatory Pass Invariants:
1. `forge --help` and all subcommands execute cleanly with exit code `0` and formatted Rich terminal outputs.
2. `forge ingest` successfully processes mixed AST and OpenAPI inputs into a queryable `docs.db`.
3. `forge init-orca` produces a valid `.orca/workspace.yaml` with zero schema violations.
4. End-to-end synthetic pipeline executes without manual intervention from ingestion to verified TDD completion.
5. All 7 test phases pass in sequence with 100% test coverage across primary paths:
   ```bash
   pytest tests/ -v
   ```
6. `scripts/audit_placeholders.py --strict` exits with code `0`, confirming 0 remaining placeholder or stub files.
