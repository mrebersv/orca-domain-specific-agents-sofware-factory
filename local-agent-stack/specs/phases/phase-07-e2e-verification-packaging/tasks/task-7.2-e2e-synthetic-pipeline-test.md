# TASK BRIEF: Task 7.2 - Synthetic End-to-End Ingestion, Worktree & TDD Verification Test

---

## 1. Context References
- Read `specs/PRD.md` (Entire document).
- Read `specs/ARCHITECTURE.md` (Entire document).
- Read `specs/plan.json`.

---

## 2. Objective
Implement `tests/phase_07/test_e2e_pipeline.py` to perform a complete, automated end-to-end integration test validating the entire `local-agent-stack` lifecycle in a fully isolated, synthetic environment.

---

## 3. Scope & Detailed Requirements

### 3.1 Synthetic End-to-End Pipeline Test (`tests/phase_07/test_e2e_pipeline.py`)

1. **Step 1: Synthetic Codebase & Repository Setup:**
   - Create an ephemeral temporary directory initialized as a Git repository (`git init`).
   - Generate sample multi-module Python source code (e.g., a math/geometry package with typed functions, class methods, docstrings with parameter descriptions, doctests, and custom exceptions).

2. **Step 2: Codebase Ingestion (`forge ingest`):**
   - Execute AST ingestion against the synthetic repository.
   - Assert `docs.db` is populated:
     - `symbols` table has extracted classes and functions.
     - `parameters` table has typed parameters.
     - `examples` table has doctest code blocks.
     - `symbols_fts` virtual table returns matching results for BM25 queries.

3. **Step 3: FastMCP Protocol Verification:**
   - Connect to the generated `docs.db` using FastMCP test client.
   - Assert `search_symbols("calculate area")` returns the geometry function signature.
   - Assert `get_symbol_schema` returns typed parameter requirements.

4. **Step 4: Sub-Agent Scaffolding & Verification (`forge scaffold` & `forge verify`):**
   - Scaffold a new sub-agent workspace (`math_geometry_agent`).
   - Assert `prompt.md` token count is strictly < 500 tokens.
   - Assert `tools.py` imports and instantiates cleanly.
   - Run `AgentVerifier` to validate synthetic execution and assert initial execution traces exist in `scratch.db`.

5. **Step 5: Ephemeral Git Worktree & Harness Execution:**
   - Create an ephemeral branch worktree (`.worktrees/task-math-feature`).
   - Dispatch `HarnessAdapter` (using `GenericCLIAdapter` or mock sub-agent runner) inside the worktree.
   - Assert changes are confined to the worktree and do not dirty the parent repository root.

6. **Step 6: Gatekeeper & Remediation Validation:**
   - Author a test assertion verifying the generated feature.
   - Simulate a test failure on Cycle 1, verify `remediation_payload.json` generation, apply mock fix on Cycle 2, and assert Gatekeeper passes with exit code `0`.
   - Verify workflow run status updates to `completed` in `registry.db`.

---

## 4. Deliverables
- `tests/phase_07/test_e2e_pipeline.py`

---

## 5. Verification Command
```bash
pytest tests/phase_07/ -v
```
- **Exit Condition:** End-to-end integration test passes with exit code `0`.
