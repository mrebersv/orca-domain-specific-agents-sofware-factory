# TASK BRIEF: Task 4.2 - Pi, Hermes, OpenCode & Generic CLI Harness Drivers

---

## 1. Context References
- Read `specs/PRD.md` (Section 4.3: Pluggable Harness Adapter Layer).
- Read `specs/phases/phase-04-harness-adapters-sandboxing/tasks/task-4.1-harness-adapter-base.md`.

---

## 2. Objective
Implement concrete harness adapters for diverse agent execution engines in `adapters/`:
1. `PiAdapter` (`adapters/pi_adapter.py`)
2. `HermesAdapter` (`adapters/hermes_adapter.py`)
3. `OpenCodeAdapter` (`adapters/opencode_adapter.py`)
4. `GenericCLIAdapter` (`adapters/generic_cli_adapter.py`)

---

## 3. Scope & Detailed Requirements

### 3.1 Generic CLI Harness Adapter (`adapters/generic_cli_adapter.py`)
- Standard fallback driver for executing arbitrary command-line agents.
- **Command Assembly:**
  - Injects `--prompt-file <path>`, `--tools <path>`, `--max-turns <int>`, and `--workdir <path>`.
  - Passes dynamic environment variables (sanitized, with secret enclave keys added).
- **Execution & Output Parsing:**
  - Captures stdout/stderr.
  - Returns `TurnResult` with captured exit code and raw output.

### 3.2 Pi Coding Agent Adapter (`adapters/pi_adapter.py`)
- Driver for Pi agent workflows.
- Formats CLI parameters for Pi binary (`--prompt`, `--system-prompt-file`, `--context-db`).
- Parses Pi JSON event streams over stdout to emit `ExecutionEvent` instances.

### 3.3 Hermes Agent Adapter (`adapters/hermes_adapter.py`)
- Driver for Nous Research Hermes / JSON-RPC agent loops.
- Supports structured function-calling formats and parses Hermes turn deltas.

### 3.4 OpenCode Adapter (`adapters/opencode_adapter.py`)
- Driver for OpenCode CLI toolchains.
- Translates task prompts and config manifests into OpenCode workspace configurations.

### 3.5 Adapter Factory (`adapters/__init__.py`)
- `def get_adapter(agent_config: Dict[str, Any], workspace_dir: Path) -> HarnessAdapter`:
  - Inspects `agent_config["harness_type"]`.
  - Instantiates and returns the corresponding driver (`pi`, `hermes`, `opencode`, `generic_cli`, or `claude-code`).

---

## 4. Deliverables
- `adapters/generic_cli_adapter.py`
- `adapters/pi_adapter.py`
- `adapters/hermes_adapter.py`
- `adapters/opencode_adapter.py`
- `adapters/__init__.py`

---

## 5. Verification Command
```bash
python3 -c "from adapters import get_adapter; adapter = get_adapter({'harness_type': 'generic_cli', 'agent_id': 'test'}, workspace_dir='.'); print(f'Loaded {type(adapter).__name__}')"
```
- **Exit Condition:** Returns `Loaded GenericCLIAdapter`.
