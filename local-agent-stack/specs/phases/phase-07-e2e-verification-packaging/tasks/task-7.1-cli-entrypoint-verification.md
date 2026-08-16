# TASK BRIEF: Task 7.1 - Unified CLI Entrypoint (`forge` CLI Commands)

---

## 1. Context References
- Read `specs/PRD.md` (Section 3.2: 3-Step Setup Journey & Section 4: Core Functional Capabilities).
- Read `specs/ARCHITECTURE.md` (Section 1: Invariants & Section 6: Orca Integration).
- Read `pyproject.toml` entry points (`[project.scripts] forge = "agent_forge.cli:main"`).

---

## 2. Objective
Implement `agent_forge/cli.py` using Click and Rich to provide the unified command-line interface for the `local-agent-stack` toolchain. Author unit and CLI execution tests in `tests/phase_07/test_cli_commands.py`.

---

## 3. Scope & Detailed Requirements

### 3.1 CLI Command Group Architecture (`agent_forge/cli.py`)
1. **Root Command Group (`forge`):**
   - Context settings: `help_option_names=['-h', '--help']`.
   - Global flags: `--verbose` / `-v`, `--quiet` / `-q`.
   - Formatted Rich banner on `--help`.

2. **Subcommand Specifications:**

   - **`forge ingest`:**
     - Options:
       - `--source` / `-s` (Path, required): Target source directory or Python file to parse via AST.
       - `--openapi` / `-o` (Path, optional): Path to OpenAPI JSON/YAML file.
       - `--db-path` / `-d` (Path, default: `./.agent/docs.db`): Target SQLite database.
     - Action: Ingests AST and/or OpenAPI specs into `docs.db` and prints total indexed symbol count with a Rich table.

   - **`forge init-orca`:**
     - Options:
       - `--target-dir` / `-t` (Path, default: `.`): Directory to initialize.
       - `--model` / `-m` (str, default: `qwen2.5-coder-7b`): Default local SLM name.
       - `--force` / `-f` (bool, default: `false`): Overwrite existing `.orca/workspace.yaml`.
     - Action: Invokes `orca_pack.generator.generate_orca_manifest`.

   - **`forge scaffold`:**
     - Options:
       - `--agent-id` / `-a` (str, required): Unique identifier for sub-agent.
       - `--name` / `-n` (str, required): Display name.
       - `--description` / `-desc` (str, required): Sub-agent operational scope.
       - `--db-path` / `-d` (Path, default: `./.agent/docs.db`): Path to source `docs.db`.
       - `--output-dir` / `-o` (Path, default: `./agents`): Destination directory.
       - `--harness` (Choice: `generic_cli`, `pi`, `hermes`, `opencode`, `claude-code`, default: `generic_cli`).
     - Action: Renders `prompt.md`, `tools.py`, `agent.config.json` via `AgentScaffolder`.

   - **`forge verify`:**
     - Options:
       - `--workspace` / `-w` (Path, required): Path to agent workspace directory.
     - Action: Executes `AgentVerifier.verify_agent_workspace` and prints pass/fail summary.

   - **`forge run`:**
     - Options:
       - `--phase` / `-p` (str, optional): Run specific phase ID (e.g. `phase-01`).
       - `--plan` (Path, default: `specs/plan.json`): Path to plan DAG.
     - Action: Triggers autonomous orchestration loop via `orca_pack.workflows.tdd_workflow` or `scripts.run_autonomous_build`.

   - **`forge status`:**
     - Options:
       - `--registry-db` (Path, default: `~/.local-agent-stack/registry.db`).
     - Action: Displays active registered agents, tool permissions, and recent workflow execution runs in a formatted Rich table.

### 3.2 CLI Testing (`tests/phase_07/test_cli_commands.py`)
- Test Click `CliRunner` invocations for every subcommand:
  - `forge --help`
  - `forge ingest --help`
  - `forge init-orca --help`
  - `forge scaffold --help`
  - `forge verify --help`
  - `forge run --help`
  - `forge status --help`
- Assert exit codes are `0` and help output contains expected option flags.

---

## 4. Deliverables
- `agent_forge/cli.py`
- `tests/phase_07/test_cli_commands.py`

---

## 5. Verification Command
```bash
python3 -m agent_forge.cli --help
```
- **Exit Condition:** Displays formatted `forge` CLI documentation and exit code is `0`.
