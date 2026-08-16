#!/usr/bin/env bash
set -euo pipefail

# ANSI formatting
BOLD="\033[1m"
GREEN="\033[92m"
CYAN="\033[96m"
RED="\033[91m"
RESET="\033[0m"

echo -e "\n${BOLD}${CYAN}===================================================================${RESET}"
echo -e "${BOLD}  LOCAL AGENT STACK — IDEMPOTENT BOOTSTRAP INSTALLER${RESET}"
echo -e "${BOLD}${CYAN}===================================================================${RESET}\n"

# 1. Python 3.11+ Version Verification
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[ERROR] python3 is not installed on PATH.${RESET}" >&2
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo -e "${RED}[ERROR] Python >= 3.11 required. Detected: Python $PYTHON_VERSION${RESET}" >&2
    exit 1
fi
echo -e "  ${GREEN}[✓]${RESET} Python version supported: ${BOLD}Python $PYTHON_VERSION${RESET}"

# 2. Virtual Environment Creation
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "  ${CYAN}[i]${RESET} Creating virtual environment in .venv..."
    python3 -m venv "$VENV_DIR"
else
    echo -e "  ${GREEN}[✓]${RESET} Virtual environment exists at ${BOLD}.venv${RESET}"
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# 3. Pip & Tooling Upgrade
echo -e "  ${CYAN}[i]${RESET} Upgrading pip, setuptools, and wheel..."
"$VENV_PIP" install --quiet --upgrade pip setuptools wheel

# 4. Editable Package Installation
echo -e "  ${CYAN}[i]${RESET} Installing local-agent-stack in editable mode with development dependencies..."
"$VENV_PIP" install --quiet -e ".[dev]"

# 5. Provision Global Directory Hierarchy
GLOBAL_DIR="$HOME/.local-agent-stack"
echo -e "  ${CYAN}[i]${RESET} Initializing global runtime state in ${BOLD}$GLOBAL_DIR${RESET}..."
mkdir -p \
    "$GLOBAL_DIR/configs" \
    "$GLOBAL_DIR/workspaces" \
    "$GLOBAL_DIR/tools" \
    "$GLOBAL_DIR/scripts" \
    "$GLOBAL_DIR/proxy"

# 6. Initialize Global Database
if [ ! -f "$GLOBAL_DIR/registry.db" ]; then
    echo -e "  ${CYAN}[i]${RESET} Initializing global registry.db schema..."
    "$VENV_PY" scripts/init_registry_db.py 2>/dev/null || true
else
    echo -e "  ${GREEN}[✓]${RESET} Global registry database already exists."
fi

echo -e "\n${BOLD}${GREEN}===================================================================${RESET}"
echo -e "${BOLD}${GREEN}  INSTALLATION COMPLETE${RESET}"
echo -e "${BOLD}${GREEN}===================================================================${RESET}"
echo -e "  To activate the environment:"
echo -e "    ${BOLD}source .venv/bin/activate${RESET}"
echo -e "  To verify CLI entrypoint:"
echo -e "    ${BOLD}forge --help${RESET}\n"
