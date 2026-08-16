# PHASE 4 OVERVIEW: Harness Adapters & Execution Sandboxing

---

## 1. Phase Objective
Implement the pluggable harness adapter layer and execution sandboxing subsystems (`adapters/`). This phase decouples agent governance, system prompts, tool permissions, and iteration limits from specific underlying agent engines (such as Pi Coding Agent, Hermes Agent, OpenCode, Claude Code, or generic CLI runners). It provides a unified asynchronous runtime (`HarnessAdapter`) and tiered execution sandboxes (Tier 1 Subprocess and Tier 2 Rootless Podman/Docker) that execute sub-agents in ephemeral environments, enforcing strict resource quotas, timeout guards, and automated trace recording into `scratch.db`.

---

## 2. Task Breakdown & Execution Strategy

| Task ID | Task Title | Execution Mode | Dependencies | Primary Deliverables |
|---|---|---|---|---|
| **Task 4.1** | HarnessAdapter Base Abstract Class & Lifecycle Events | Sequential (First) | Phase 1 & 3 Complete | `adapters/base.py` |
| **Task 4.2** | Pi, Hermes, OpenCode & Generic CLI Harness Drivers | Parallel (`p4_adapters`) | Task 4.1 | `adapters/pi_adapter.py`, `adapters/hermes_adapter.py`, `adapters/opencode_adapter.py`, `adapters/generic_cli_adapter.py` |
| **Task 4.3** | Subprocess & Podman Tiered Execution Sandboxes | Parallel (`p4_adapters`) | Task 4.1 | `adapters/runners.py`, `tests/phase_04/` |

### Dependency & Concurrency Graph
```
        ┌─────────────────────────────────────────────────────────┐
        │  Phase 1 & Phase 3 Complete (Storage & Workspace Ready) │
        └────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │  [Task 4.1: HarnessAdapter Base Class & Lifecycle]      │
        │  (adapters/base.py: ABC, Event Streams, scratch.db hook)│
        └────────────────────────────┬────────────────────────────┘
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
    [Task 4.2: Concrete Harness Drivers]     [Task 4.3: Tiered Sandboxes]
    • pi_adapter.py                          • Tier 1: Local Subprocess
    • hermes_adapter.py                      • Tier 2: Rootless Podman
    • opencode_adapter.py                    • Cgroups & Timeout Guards
    • generic_cli_adapter.py                 • adapters/runners.py
                 │                                       │
                 └───────────────────┬───────────────────┘
                                     ▼
                      [Phase 4 Gatekeeper Execution]
                       pytest tests/phase_04/ -v
```

---

## 3. Inter-Task Data Flow
1. **Task 4.1** defines the `HarnessAdapter` abstract base class, execution event models (`TokenEvent`, `ToolCallEvent`, `TurnCompleteEvent`), lifecycle management hooks, and automated execution logging to `scratch.db`.
2. **Task 4.2** implements driver classes for specific inner loops (Pi, Hermes, OpenCode, and Generic CLI), translating unified task parameters, `prompt.md`, `tools.py`, and `max_turns` into engine-specific CLI arguments and stdio/JSON-RPC protocols.
3. **Task 4.3** implements execution runners:
   - **Tier 1 (`SubprocessRunner`):** Local process execution with environment sanitization, working directory enforcement, and strict timeout enforcement.
   - **Tier 2 (`PodmanRunner` / `DockerRunner`):** Containerized execution with volume mounts, memory/CPU bounds, and network isolation.
   It also authors the complete integration test suite in `tests/phase_04/`.

---

## 4. Phase Exit Gate Criteria

Before unlocking Phase 5, the Test Runner / Gatekeeper executes:

```bash
pytest tests/phase_04/ -v
```

### Mandatory Pass Invariants:
1. `HarnessAdapter` abstract methods cannot be instantiated directly and enforce typing contracts across all subclasses.
2. All concrete adapters (`PiAdapter`, `HermesAdapter`, `GenericCLIAdapter`) correctly parse CLI exit codes and map stdout/stderr into structured `TurnResult` objects.
3. Every executed turn automatically persists step metrics, inputs, outputs, and runtime milliseconds to `scratch.db`.
4. Sandboxes terminate child processes cleanly upon timeout expiration without orphan processes.
5. Container runner mounts target working directories with proper permissions and enforces read-only mounts when specified.
