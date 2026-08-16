# PHASE 6 OVERVIEW: Orca ADE Integration & Workflow Engine

---

## 1. Phase Objective
Implement the Orca ADE native integration package (`orca_pack/`). This phase delivers the workspace manifest generator (`forge init-orca`), the pre/post worktree lifecycle hooks (runtime secret enclave injection, proxy health verification, and Monaco diff preparation), and the programmatic phase-level TDD multi-agent orchestration engine (`tdd_workflow.py`) with automated gatekeeping, remediation loops, and Orca mobile/desktop HITL breakpoints.

---

## 2. Task Breakdown & Execution Strategy

| Task ID | Task Title | Execution Mode | Dependencies | Primary Deliverables |
|---|---|---|---|---|
| **Task 6.1** | Orca Workspace Manifest Generator (`forge init-orca`) | Sequential (First) | Phase 1–5 Complete | `orca_pack/generator.py`, `orca_pack/templates/orca.template.yaml` |
| **Task 6.2** | Pre/Post Worktree Lifecycle Hooks & Secret Enclave Injection | Parallel (`p6_hooks`) | Task 6.1 | `orca_pack/hooks/pre_run.py`, `orca_pack/hooks/post_run.py`, `orca_pack/hooks/pre_worktree_check.py`, `orca_pack/hooks/setup_worktree_env.py` |
| **Task 6.3** | Programmatic TDD Multi-Agent Workflow Runner | Parallel (`p6_hooks`) | Task 6.1 | `orca_pack/workflows/tdd_workflow.py`, `tests/phase_06/` |

### Dependency & Concurrency Graph
```
        ┌─────────────────────────────────────────────────────────┐
        │  Phase 1–5 Complete (Storage, MCP, Adapters, Proxy)     │
        └────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │  [Task 6.1: Orca Workspace Manifest Generator]          │
        │  (orca_pack/generator.py & orca.template.yaml)          │
        └────────────────────────────┬────────────────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
    [Task 6.2: Worktree Lifecycle Hooks]     [Task 6.3: TDD Workflow Engine]
    • pre_run.py (Proxy & Secrets)           • Test Author Dispatcher
    • post_run.py (Monaco Diff & scratch.db) • Gatekeeper (pytest --json-report)
    • pre_worktree_check.py                  • Remediation Loop (Max 3 Cycles)
    • setup_worktree_env.py                  • Orca HITL Snapshot Trigger
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     ▼
                      [Phase 6 Gatekeeper Execution]
                       pytest tests/phase_06/ -v
```

---

## 3. Inter-Task Data Flow
1. **Task 6.1** generates `.orca/workspace.yaml` inside target project repositories, registering the local FastMCP knowledge server (`mcp-docs-db`), the local VRAM arbiter endpoint (`http://127.0.0.1:8000/v1`), and custom BYOA (Bring-Your-Own-Agent) node definitions.
2. **Task 6.2** provides automated execution hooks for Orca ADE:
   - `pre_worktree_check.py` and `setup_worktree_env.py` verify Git cleanliness and initialize ephemeral branch worktrees.
   - `pre_run.py` validates VRAM proxy health and injects credentials into runtime memory enclaves.
   - `post_run.py` records step traces into `scratch.db`, stages modifications for Orca Monaco diff inspection, and invokes `orca snapshot` on critical failure.
3. **Task 6.3** executes the end-to-end TDD orchestration engine (`tdd_workflow.py`), dispatching the Test Author Agent, fan-out Task Builders, Gatekeeper test evaluation, and up to 3 automated remediation cycles before pausing for human review.

---

## 4. Phase Exit Gate Criteria

Before unlocking Phase 7, the Test Runner / Gatekeeper executes:

```bash
pytest tests/phase_06/ -v
```

### Mandatory Pass Invariants:
1. `orca_pack/generator.py` generates valid `.orca/workspace.yaml` conforming to Orca ADE specifications.
2. `pre_run.py` blocks execution with exit code `1` if the VRAM proxy is unreachable, and succeeds with `0` when healthy.
3. `post_run.py` successfully parses execution diffs and records artifacts in `scratch.db`.
4. `tdd_workflow.py` executes test authoring, task implementation, gatekeeping, and remediation in isolated sub-agent contexts.
5. On 3 consecutive test failures, the workflow triggers `orca snapshot` and marks run status as `paused_gatekeeper_failed`.
