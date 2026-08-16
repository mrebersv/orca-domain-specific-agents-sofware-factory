# TASK BRIEF: Task 6.2 - Pre/Post Worktree Lifecycle Hooks & Secret Enclave Injection

---

## 1. Context References
- Read `specs/PRD.md` (Section 4.4: Tiered Sandboxing & Git Worktree Isolation).
- Read `specs/ARCHITECTURE.md` (Section 6: Orca ADE Integration & Lifecycle Hooks).

---

## 2. Objective
Implement the lifecycle hook scripts in `orca_pack/hooks/` executed by Orca ADE before and after sub-agent runs:
1. `pre_worktree_check.py`: Validates Git repository status.
2. `setup_worktree_env.py`: Provisions isolated Git worktrees for tasks.
3. `pre_run.py`: Verifies VRAM proxy availability and injects in-memory secrets.
4. `post_run.py`: Records execution metrics into `scratch.db` and prepares Monaco diffs.

---

## 3. Scope & Detailed Requirements

### 3.1 Git Worktree Utilities (`orca_pack/hooks/pre_worktree_check.py` & `setup_worktree_env.py`)
1. **Pre-Worktree Check (`pre_worktree_check.py`):**
   - Asserts current directory is a valid Git repository.
   - Warns if uncommitted changes exist in root branch.
2. **Worktree Provisioning (`setup_worktree_env.py`):**
   - `def create_ephemeral_worktree(repo_root: Path, branch_name: str) -> Path`:
     - Runs `git worktree add -b {branch_name} .worktrees/{branch_name}`.
     - Copies or links local `.env` and `.agent/docs.db` into the worktree.
     - Returns path to active worktree directory.
   - `def cleanup_worktree(repo_root: Path, branch_name: str, delete_branch: bool = False) -> None`:
     - Runs `git worktree remove --force .worktrees/{branch_name}`.

### 3.2 Pre-Run Hook (`orca_pack/hooks/pre_run.py`)
1. **VRAM Proxy Health Check:**
   - Calls `proxy.check_vram.check_proxy_health(timeout=2.0)`.
   - If offline: print error instructions and abort with exit code `1`.
2. **Secret Enclave Injection:**
   - Reads target environment variable names from `agent.config.json`.
   - Injects key values strictly into subprocess memory environment without writing to disk or SQLite.

### 3.3 Post-Run Hook (`orca_pack/hooks/post_run.py`)
1. **Monaco Diff Preparation:**
   - Executes `git diff --stat` and `git diff` inside the task worktree.
   - Generates structured diff summary for Orca Monaco editor review.
2. **Telemetry & Scratchpad Persistence:**
   - Parses agent turn exit codes, tool invocation counts, and duration.
   - Records execution summary into `scratch.db`.
3. **HITL Breakpoint Escalation:**
   - If agent returned fatal failure or gatekeeper cycle exhausted:
     - Run `orca snapshot --message "Sub-agent failed: {reason}"` to trigger desktop/mobile alert.

---

## 4. Deliverables
- `orca_pack/hooks/pre_worktree_check.py`
- `orca_pack/hooks/setup_worktree_env.py`
- `orca_pack/hooks/pre_run.py`
- `orca_pack/hooks/post_run.py`

---

## 5. Verification Command
```bash
python3 -c "import orca_pack.hooks.pre_run; import orca_pack.hooks.post_run; print('Hooks imported successfully')"
```
- **Exit Condition:** All hook modules import cleanly and pass unit tests.
