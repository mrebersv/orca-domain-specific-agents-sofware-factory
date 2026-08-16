# TASK BRIEF: Task 6.1 - Orca Workspace Manifest Generator (`forge init-orca`)

---

## 1. Context References
- Read `specs/PRD.md` (Section 1: Executive Summary & Section 4: Functional Capabilities).
- Read `specs/ARCHITECTURE.md` (Section 6: Orca ADE Integration & Lifecycle Hooks).

---

## 2. Objective
Implement `orca_pack/generator.py` and `orca_pack/templates/orca.template.yaml`. This module powers the `forge init-orca` CLI command, generating a production-ready `.orca/workspace.yaml` configuration in target repositories that registers the `mcp-docs-db` MCP server, VRAM arbiter endpoint, and Orca workflow nodes.

---

## 3. Scope & Detailed Requirements

### 3.1 Orca Workspace Template (`orca_pack/templates/orca.template.yaml`)
1. **MCP Server Registration:**
   ```yaml
   mcp_servers:
     docs-db:
       command: "mcp-docs-db"
       args: ["--db-path", "${WORKSPACE_ROOT}/.agent/docs.db"]
       transport: "stdio"
   ```
2. **Model Endpoints & Provider Configurations:**
   ```yaml
   models:
     local-slm:
       base_url: "[http://127.0.0.1:8000/v1](http://127.0.0.1:8000/v1)"
       api_key: "not-needed"
       model: "{{ local_model_name }}"
     cloud-fallback:
       base_url: "[https://api.anthropic.com/v1](https://api.anthropic.com/v1)"
       api_key: "${ANTHROPIC_API_KEY}"
       model: "claude-3-5-sonnet-latest"
   ```
3. **Agent Role & Node Definitions:**
   - `test-author-node`: Dispatches Phase Test Author Agent in read-only worktree.
   - `builder-node`: Dispatches Task Builder Agent in task-specific worktree.
   - `gatekeeper-node`: Executes pytest gate check with JSON report.
   - `remediation-node`: Dispatches remediation agent with failure payload.
4. **Lifecycle Hook Bindings:**
   - `pre_node_hook`: `python -m orca_pack.hooks.pre_run`
   - `post_node_hook`: `python -m orca_pack.hooks.post_run`

### 3.2 Manifest Generator Engine (`orca_pack/generator.py`)
1. **Generator Function:**
   ```python
   def generate_orca_manifest(
       project_root: Path,
       local_model_name: str = "qwen2.5-coder-7b",
       enable_cloud_fallback: bool = True,
       force_overwrite: bool = False
   ) -> Path:
       """Renders and writes .orca/workspace.yaml in project_root."""
   ```
2. **Validation & Idempotency:**
   - Create `.orca/` directory if missing.
   - If `.orca/workspace.yaml` exists and `force_overwrite=False`, prompt or raise `FileExistsError`.
   - Validate rendered YAML syntax with `pyyaml`.

---

## 4. Deliverables
- `orca_pack/templates/orca.template.yaml`
- `orca_pack/generator.py`

---

## 5. Verification Command
```bash
python3 -c "from orca_pack.generator import generate_orca_manifest; from pathlib import Path; p = generate_orca_manifest(Path('/tmp/test_orca_proj'), force_overwrite=True); print('Manifest generated at:', p)"
```
- **Exit Condition:** Generates valid `.orca/workspace.yaml` in target directory without errors.
