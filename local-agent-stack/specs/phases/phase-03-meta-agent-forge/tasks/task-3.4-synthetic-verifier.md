# TASK BRIEF: Task 3.4 - Synthetic Dry-Run Verification Harness

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` (Section 2.3: `scratch.db` Schema).
- Read `specs/phases/phase-03-meta-agent-forge/tasks/task-3.3-scaffolder-code-generator.md`.

---

## 2. Objective
Implement `agent_forge/verifier.py` to run synthetic dry-run validations on newly scaffolded agents. The verifier loads scaffolded `tools.py` and `agent.config.json`, executes test invocations with mock parameters, logs every execution turn and generated artifact into an ephemeral `scratch.db`, and validates operational integrity.

---

## 3. Scope & Detailed Requirements

### 3.1 Synthetic Verifier Engine (`agent_forge/verifier.py`)
1. **Verification Pipeline (`AgentVerifier`):**
   - `async def verify_agent_workspace(workspace_dir: Path) -> Dict[str, Any]`:
     1. **Manifest Validation:** Validate `agent.config.json` against required JSON schema.
     2. **Prompt Budget Check:** Measure `prompt.md` token length (< 500 tokens).
     3. **Tool Importability:** Dynamically import `{workspace_dir}/tools.py` using `importlib.util`.
     4. **Database Integrity:** Assert `{workspace_dir}/docs.db` exists, contains valid tables, and passes `PRAGMA integrity_check;`.
     5. **Synthetic Tool Execution:**
        - Initialize ephemeral `{workspace_dir}/scratch.db`.
        - Invoke each exposed tool in `tools.py` using synthetic/mock inputs.
        - Record execution turns (`step_number`, `tool_called`, `tool_input`, `tool_output`, `status`, `execution_time_ms`) into `execution_turns` table in `scratch.db`.
        - Record output files to `artifacts` table in `scratch.db` with SHA-256 checksums.
2. **Outcome Reporting:**
   - Return structured validation summary:
     ```python
     {
         "agent_id": "math_helper",
         "status": "passed",  # or "failed"
         "prompt_tokens_est": 320,
         "tools_tested": ["add_numbers", "search_symbols"],
         "turns_recorded": 2,
         "errors": []
     }
     ```

### 3.2 Phase 3 Test Suite Completion (`tests/phase_03/`)
- Author tests covering:
  - `test_ast_extractor.py`: Ingestion of sample Python modules, class hierarchies, and type hints.
  - `test_spec_extractor.py`: Ingestion of OpenAPI v3 JSON specs.
  - `test_scaffolder.py`: Workspace file generation and token economy assertions.
  - Verification that `scratch.db` contains expected execution traces post-verification.

---

## 4. Deliverables
- `agent_forge/verifier.py`
- `tests/phase_03/test_ast_extractor.py`
- `tests/phase_03/test_spec_extractor.py`
- `tests/phase_03/test_scaffolder.py`

---

## 5. Verification Command
```bash
pytest tests/phase_03/ -v
```
- **Exit Condition:** All Phase 3 extractor, scaffolder, and verifier tests pass with exit code `0`.
