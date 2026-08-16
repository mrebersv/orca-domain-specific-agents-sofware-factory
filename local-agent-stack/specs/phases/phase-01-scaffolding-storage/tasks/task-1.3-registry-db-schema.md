# TASK BRIEF: Task 1.3 - registry.db & scratch.db Schemas and Async Drivers

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` -> Section 2.1 (`registry.db` DDL) & Section 2.3 (`scratch.db` DDL).

---

## 2. Objective
Implement the asynchronous SQLite database connection managers, migration/initialization logic, and data access objects for both the global stack registry (`registry.db`) and ephemeral execution scratchpads (`scratch.db`).

---

## 3. Scope & Detailed Requirements

### 3.1 Registry Database Module (`agent_forge/db/registry.py`)
1. **Connection Factory:**
   - `get_registry_db(db_path: Optional[Path] = None) -> aiosqlite.Connection`
   - Default path: `~/.local-agent-stack/registry.db`.
   - Enforce `PRAGMA foreign_keys = ON;` and `PRAGMA journal_mode = WAL;`.
2. **Schema DDL Initialization:**
   - `init_registry_db(db_path: Optional[Path] = None) -> None`
   - Creates tables:
     - `agents` (`agent_id`, `name`, `description`, `harness_type`, `harness_binary`, `model_name`, `model_endpoint`, `api_key_env_var`, `isolation_tier`, `container_image`, `max_turns`, `timeout_seconds`, `is_active`, `created_at`).
     - `agent_tool_permissions` (`agent_id`, `tool_name`, `is_destructive`, `requires_approval`).
     - `workflows` (`workflow_id`, `name`, `description`, `dag_definition`, `created_at`).
     - `workflow_runs` (`run_id`, `workflow_id`, `status`, `current_node_id`, `global_context`, `git_worktree_path`, `started_at`, `updated_at`, `completed_at`).
     - `node_execution_checkpoints` (`checkpoint_id`, `run_id`, `node_id`, `iteration`, `node_status`, `input_artifacts`, `output_artifacts`, `stderr_log`, `created_at`).

### 3.2 Scratchpad Database Module (`agent_forge/db/scratch.py`)
1. **Connection Factory & Initializer:**
   - `get_scratch_db(db_path: Path) -> aiosqlite.Connection`
   - `init_scratch_db(db_path: Path) -> None`
2. **Schema DDL:**
   - `execution_turns` (`turn_id`, `session_id`, `workflow_run_id`, `step_number`, `tool_called`, `tool_input`, `tool_output`, `status`, `execution_time_ms`, `created_at`).
   - `artifacts` (`artifact_id`, `session_id`, `workflow_run_id`, `artifact_type`, `file_path`, `content_raw`, `checksum_sha256`, `created_at`).

### 3.3 Standalone CLI Initialization Script (`scripts/init_registry_db.py`)
- Python script that can be executed directly from CLI or `install.sh` to provision `registry.db`.

---

## 4. Deliverables
- `agent_forge/db/registry.py`
- `agent_forge/db/scratch.py`
- `scripts/init_registry_db.py`

---

## 5. Verification Command
```bash
python3 -c "import asyncio; from agent_forge.db.registry import init_registry_db; from pathlib import Path; asyncio.run(init_registry_db(Path('/tmp/test_reg.db')))"
```
- **Exit Condition:** Database and all 5 tables initialize without error.
