# TASK BRIEF: Task 1.2 - Bootstrap Installation Script

---

## 1. Context References
- Read `specs/PRD.md` (Section 3.2: 3-Step Setup Journey).
- Read `specs/phases/phase-01-scaffolding-storage/tasks/task-1.1-packaging-pyproject.md`.

---

## 2. Objective
Author an idempotent, robust shell script (`install.sh`) that automates local virtual environment creation, package installation in editable mode, directory hierarchy setup in `~/.local-agent-stack/`, and database initialization.

---

## 3. Scope & Detailed Requirements

### 3.1 Script Behavior (`install.sh`)
1. **Safety Flags:** Enforce `set -euo pipefail`.
2. **Python Version Check:** Assert `python3` is installed and version is `>= 3.11`. Exit with a descriptive error if not met.
3. **Virtual Environment Setup:**
   - Create a local virtual environment in `.venv` if it does not already exist (`python3 -m venv .venv`).
   - Use `.venv/bin/python` and `.venv/bin/pip` for all operations.
4. **Editable Package Installation:**
   - Upgrade pip, setuptools, and wheel.
   - Run `pip install -e ".[dev]"` (or `pip install -e .` with test dependencies).
5. **Global Directory Hierarchy Provisioning:**
   - Create directories under `~/.local-agent-stack/`:
     - `~/.local-agent-stack/configs`
     - `~/.local-agent-stack/workspaces`
     - `~/.local-agent-stack/tools`
     - `~/.local-agent-stack/scripts`
     - `~/.local-agent-stack/proxy`
6. **Database Initialization:**
   - If `~/.local-agent-stack/registry.db` does not exist, run `python scripts/init_registry_db.py`.
7. **Confirmation Output:**
   - Print ASCII banner, installation summary, and instructions for activating the environment and running `forge --help`.

---

## 4. Deliverables
- `install.sh` (with executable permissions `chmod +x install.sh`).

---

## 5. Verification Command
```bash
bash -n install.sh
```
- **Exit Condition:** Shell syntax verification passes with exit code `0`.
