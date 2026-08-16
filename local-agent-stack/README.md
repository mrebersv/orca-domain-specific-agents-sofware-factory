# local-agent-stack

A local-first multi-agent orchestration, JIT knowledge indexing, and TDD execution stack designed for native integration with Orca ADE (`onorca.dev`).

## Core Architecture
- **JIT Relational Documentation (`docs.db`):** AST-extracted symbol definitions, typed parameter schemas, and sub-5ms BM25 full-text indexing via SQLite FTS5.
- **FastMCP Knowledge Server:** Universal Model Context Protocol (MCP) server over `stdio` and HTTP.
- **Hardware-Aware VRAM Arbiter:** Reverse proxy with `asyncio.Semaphore(1)` per physical GPU to eliminate Out-Of-Memory collisions across concurrent agents.
- **Autonomous Phase TDD Engine:** Decoupled Test Author, Task Builder, Gatekeeper (`pytest --json-report`), and Remediation sub-agents with Orca HITL breakpoints.

## Quickstart

```bash
# 1. Run the idempotent installer
./install.sh

# 2. Activate the virtual environment
source .venv/bin/activate

# 3. Run the autonomous build orchestrator
python scripts/run_autonomous_build.py
