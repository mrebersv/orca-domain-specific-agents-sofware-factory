# TASK BRIEF: Task 3.3 - Workspace Scaffolder: tools.py, prompt.md, and agent.config.json Generator

---

## 1. Context References
- Read `specs/PRD.md` (Section 5: Context Window Economy < 500 tokens).
- Read `specs/ARCHITECTURE.md` (Section 1: Invariants & Section 3: Harness Adapters).
- Read `agent_forge/templates/` directory specifications.

---

## 2. Objective
Implement `agent_forge/scaffolder.py` and finalize the Jinja/format templates in `agent_forge/templates/`. The scaffolder provisions an isolated agent workspace by querying `docs.db` and outputting a lean system prompt (`prompt.md`), typed tool wrappers (`tools.py`), and runtime configuration (`agent.config.json`).

---

## 3. Scope & Detailed Requirements

### 3.1 Workspace Templates (`agent_forge/templates/`)
1. **`prompt.template.md`:**
   - Must generate a focused prompt under 500 tokens.
   - Injects agent role, targeted sub-domain scope, tool usage instructions, and safety guardrails.
   - Contains zero raw API documentation dumps (instructs agent to use MCP / `tools.py` for queries).
2. **`tools.template.py`:**
   - Python code template generating typed wrapper functions around the target library or MCP client calls.
   - Includes standard docstrings, parameter types, error handling, and destructive-action warnings.
3. **`agent.config.template.json`:**
   - Structured manifest containing:
     ```json
     {
       "agent_id": "{{ agent_id }}",
       "name": "{{ name }}",
       "description": "{{ description }}",
       "harness_type": "{{ harness_type }}",
       "model_name": "{{ model_name }}",
       "model_endpoint": "{{ model_endpoint }}",
       "isolation_tier": "subprocess",
       "max_turns": 6,
       "timeout_seconds": 60,
       "permissions": {
         "allowed_tools": ["search_symbols", "get_symbol_schema"],
         "require_approval_for_destructive": true
       }
     }
     ```

### 3.2 Scaffolding Engine (`agent_forge/scaffolder.py`)
1. **Agent Generator Class (`AgentScaffolder`):**
   - `def scaffold_agent(agent_id: str, name: str, description: str, db_path: Path, output_dir: Path, harness_type: str = "generic_cli", model_name: str = "local-slm") -> Path`:
     - Creates directory `{output_dir}/{agent_id}/`.
     - Connects to `{db_path}` to inspect available symbols and domain metadata.
     - Renders and writes `{output_dir}/{agent_id}/prompt.md`.
     - Renders and writes `{output_dir}/{agent_id}/tools.py`.
     - Renders and writes `{output_dir}/{agent_id}/agent.config.json`.
     - Copies or symlinks `{db_path}` to `{output_dir}/{agent_id}/docs.db`.
     - Registers the newly scaffolded agent in `registry.db`.
2. **Token Economy Guardrail:**
   - Assert that rendered `prompt.md` token count (estimated at ~4 chars/token) is strictly under 500 tokens. Raise `ValueError` if exceeded.

---

## 4. Deliverables
- `agent_forge/templates/prompt.template.md`
- `agent_forge/templates/tools.template.py`
- `agent_forge/templates/agent.config.template.json`
- `agent_forge/scaffolder.py`
- `tests/phase_03/test_scaffolder.py`

---

## 5. Verification Command
```bash
python3 -c "from agent_forge.scaffolder import AgentScaffolder; from pathlib import Path; s = AgentScaffolder(); print('Scaffolder ready')"
```
- **Exit Condition:** Scaffolder instantiates and template syntax parses without errors.
