# TASK BRIEF: Task 6.3 - Programmatic TDD Multi-Agent Workflow Runner

---

## 1. Context References
- Read `specs/PRD.md` (Section 4.6: Autonomous Phase-Level TDD Engine).
- Read `specs/ARCHITECTURE.md` (Section 7: Autonomous Phase-Level TDD Engine).

---

## 2. Objective
Implement `orca_pack/workflows/tdd_workflow.py` to drive the autonomous phase-based TDD orchestration engine, and author the complete Phase 6 test suite (`tests/phase_06/`).

---

## 3. Scope & Detailed Requirements

### 3.1 TDD Workflow Engine (`orca_pack/workflows/tdd_workflow.py`)
1. **Workflow Coordinator (`TDDWorkflowRunner`):**
   ```python
   class TDDWorkflowRunner:
       def __init__(self, plan_path: Path, registry_db_path: Path):
           self.plan_path = plan_path
           self.registry_db_path = registry_db_path
           self.max_remediation_cycles = 3

       async def run_phase_tdd_cycle(self, phase_id: str) -> bool:
           """Executes 4-step autonomous TDD lifecycle for the given phase."""
           pass
   ```
2. **Step 1: Test Author Dispatch:**
   - Read phase specification and all task briefs.
   - Dispatch `agent-test-author` with clean context (< 2,500 tokens).
   - Write test suite to `tests/{phase_id}/`.
3. **Step 2: Task Builders Dispatch:**
   - For each pending task, provision dedicated worktree.
   - Dispatch `agent-builder` with task brief and `docs.db` access.
   - Mark task complete upon successful exit code.
4. **Step 3: Gatekeeper Evaluation:**
   - Execute `pytest tests/{phase_id}/ --json-report --json-report-file={report_path}`.
   - If returncode == 0: Commit changes, advance phase, return `True`.
5. **Step 4: Remediation Loop & HITL Escalation:**
   - If returncode != 0 and `cycle < 3`:
     - Parse JSON test report and build `remediation_payload.json` (failing assertions, stack traces, target files).
     - Dispatch `agent-remediation` with failure payload.
     - Repeat Step 3.
   - If `cycle >= 3`:
     - Trigger `orca snapshot --message "Gatekeeper failed after 3 remediation attempts in {phase_id}"`.
     - Update workflow run state to `paused_gatekeeper_failed` in `registry.db`.
     - Return `False`.

### 3.2 Phase 6 Integration Test Suite (`tests/phase_06/`)
- `tests/phase_06/test_orca_generator.py`: Verifies `.orca/workspace.yaml` template rendering and schema validity.
- `tests/phase_06/test_orca_hooks.py`: Verifies pre-run VRAM check, secret enclave handling, and post-run diff generation.
- `tests/phase_06/test_tdd_loop.py`: Mocks a 4-step TDD cycle testing:
  - Immediate pass scenario.
  - Fail -> Remediation patch -> Pass scenario.
  - Fail -> 3 cycles exhausted -> Orca snapshot breakpoint trigger.

---

## 4. Deliverables
- `orca_pack/workflows/tdd_workflow.py`
- `tests/phase_06/test_orca_generator.py`
- `tests/phase_06/test_orca_hooks.py`
- `tests/phase_06/test_tdd_loop.py`

---

## 5. Verification Command
```bash
pytest tests/phase_06/ -v
```
- **Exit Condition:** All Phase 6 generator, hook, and TDD loop tests pass with exit code `0`.
