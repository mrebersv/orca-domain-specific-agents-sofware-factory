# TASK BRIEF: Task 1.1 - Python Packaging & Dependencies

---

## 1. Context References
- Read `specs/PRD.md` (Section 3: Target 3-Step Setup Journey).
- Read `specs/ARCHITECTURE.md` (Section 1: Invariants & Dependencies).

---

## 2. Objective
Configure standard Python packaging files (`pyproject.toml` and `requirements.txt`) supporting Python 3.11+ and 3.12+, registering all global CLI commands (`forge`, `vram-proxy`, `mcp-docs-db`), and locking all required runtime and testing libraries.

---

## 3. Scope & Detailed Requirements

### 3.1 `pyproject.toml` Specification
1. **Build Backend:** Use standard `setuptools` or `hatchling`.
2. **Project Metadata:**
   - Name: `local-agent-stack`
   - Version: `0.1.0`
   - Requires-Python: `>=3.11`
3. **Core Dependencies:**
   - `fastapi>=0.115.0`
   - `uvicorn>=0.30.0`
   - `mcp>=1.0.0`
   - `aiosqlite>=0.20.0`
   - `docstring-parser>=0.16`
   - `tree-sitter>=0.22.0`
   - `pydantic>=2.8.0`
   - `click>=8.1.0`
   - `rich>=13.7.0`
   - `httpx>=0.27.0`
   - `pyyaml>=6.0.1`
4. **Development / Test Dependencies:**
   - `pytest>=8.0.0`
   - `pytest-asyncio>=0.23.0`
   - `pytest-json-report>=1.5.0`
5. **CLI Entry Points:**
   ```toml
   [project.scripts]
   forge = "agent_forge.cli:main"
   vram-proxy = "proxy.vram_arbiter:main"
   mcp-docs-db = "mcp_server.__main__:main"
   ```

### 3.2 `requirements.txt` Specification
- Output pinned/compatible versions reflecting dependencies in `pyproject.toml` to support direct `pip install -r requirements.txt`.

---

## 4. Deliverables
- `pyproject.toml`
- `requirements.txt`

---

## 5. Verification Command
```bash
python3 -m pip install --dry-run -e .
```
- **Exit Condition:** Package metadata parses cleanly with zero dependency conflicts.
