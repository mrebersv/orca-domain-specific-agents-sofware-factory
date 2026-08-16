# PRODUCT REQUIREMENTS DOCUMENT (PRD)
## Local-First Multi-Agent Architecture, Knowledge Engine & Orca ADE Integration

---

## 1. Executive Summary
**local-agent-stack** is an open-source, local-first developer toolchain that enables software engineers to scaffold, govern, and orchestrate specialized sub-agents with minimal token footprints. The platform shifts multi-agent workflows away from monolithic, context-bloated agents toward single-responsibility sub-agents grounded in just-in-time relational SQLite documentation (`docs.db` with FTS5 search), isolated Git worktrees, tiered execution sandboxes, and hardware-aware local model inference.

The entire stack is designed to be cloned and integrated directly into **Orca ADE** (`onorca.dev`) using standard Model Context Protocol (MCP) servers, CLI harness adapters, and project-level lifecycle hooks.

---

## 2. Problem Statement
1. **Context Bloat & Token Inefficiency:** General-purpose coding agents consume tens of thousands of tokens per turn reading raw source trees, degrading reasoning quality and inflating inference latency.
2. **API Hallucinations on Local SLMs:** Local 7B–14B models frequently hallucinate SDK method signatures and parameters without exact, typed retrieval.
3. **Execution Interference:** Multi-agent workflows running concurrently on the same working tree cause race conditions, dirty file collisions, and branch corruption.
4. **Hardware OOM Collisions:** Multiple parallel agent workers dispatching concurrent requests to local inference engines (`llama.cpp`, Ollama, vLLM) crash host GPUs via Out-of-Memory (OOM) errors.
5. **Lack of Independent Verification:** Builder agents often author and evaluate their own tests, creating superficial passing conditions that fail in production.

---

## 3. User Personas & Developer Journeys

### 3.1 Primary Persona
- **Local AI Systems Engineer / Software Developer:** Runs local LLMs/SLMs or hybrid endpoints, utilizes modern agent environments (Orca ADE, Claude Code, Cursor), and requires deterministic, auditable code generation without vendor lock-in.

### 3.2 Target 3-Step Setup Journey
```bash
# 1. Clone the repository
git clone [https://github.com/org/local-agent-stack.git](https://github.com/org/local-agent-stack.git)
cd local-agent-stack

# 2. Run the idempotent installer
./install.sh

# 3. Ingest a codebase and configure Orca in any target project
forge ingest --source .
forge init-orca
```

---

## 4. Core Functional Capabilities

```
+------------------------------------------------------------------------+
|                        LOCAL AGENT STACK PRD                           |
+-------------------+-------------------+--------------------------------+
| 1. KNOWLEDGE      | 2. GOVERNANCE     | 3. ORCHESTRATION               |
| * AST-to-SQLite   | * Harness Adapter | * Orca ADE Native Hooks        |
| * FTS5 Full-Text  | * Git Worktrees   | * Local VRAM Arbiter Queue     |
| * FastMCP Server  | * Tiered Sandbox  | * Phase-Level TDD State Machine|
+-------------------+-------------------+--------------------------------+
```

### 4.1 JIT Relational Knowledge Store (`docs.db`)
- Ingests Python codebases via deterministic Abstract Syntax Tree (`ast` / `tree-sitter`) and docstring parsers.
- Ingests REST/CLI interfaces via OpenAPI specs and `--help` parsers.
- Indexes all signatures, parameter constraints, error codes, and verified call examples into SQLite tables.
- Provides sub-millisecond BM25 keyword retrieval via SQLite FTS5 virtual tables with automatic insert/update/delete triggers.

### 4.2 Universal Model Context Protocol (MCP) Server
- Exposes `docs.db` as a standardized FastMCP server (`mcp-server-docs-db`) over stdio and HTTP.
- Enables any MCP-compliant IDE or agent (Orca, Claude Code, Cursor, Zed) to query symbol schemas dynamically without polluting the prompt context.

### 4.3 Pluggable Harness Adapter Layer
- Wraps diverse agent inner loops (Pi Coding Agent, Hermes Agent, OpenCode, Claude Code, generic CLI runners) behind an asynchronous Python base class (`HarnessAdapter`).
- Enforces strict governance: injects single-purpose system prompts (`prompt.md`), tool definitions (`tools.py`), and iteration limits (`max_turns`).

### 4.4 Tiered Sandboxing & Git Worktree Isolation
- **Tier 1 (Subprocess):** Read-only filesystem mounts with restricted working directories.
- **Tier 2 (Containers):** Rootless Podman/Docker containers with strict RAM/CPU limits and host network isolation.
- **Worktree Lifecycle:** Enforces dedicated, ephemeral Git worktrees for every agent execution to eliminate working tree collisions.

### 4.5 Local Model Arbiter & Concurrency Proxy
- Acts as a local OpenAI-compatible reverse proxy (`http://127.0.0.1:8000/v1`).
- Enforces `asyncio.Semaphore(1)` per physical GPU to queue concurrent agent requests and prevent hardware VRAM exhaustion.

### 4.6 Autonomous Phase-Level TDD Engine
- Dispatches an independent **Test Author Agent** before any builder agent executes.
- Runs an automated **Gatekeeper Agent** to verify tests via `pytest --json-report`.
- Automatically routes test failures through a **Remediation Agent** (capped at 3 cycles) before triggering an Orca Human-in-the-Loop (HITL) breakpoint.

---

## 5. Non-Functional Requirements & Guardrails

| Requirement | Target Metric / Constraint |
|---|---|
| **Context Window Economy** | Sub-agent system prompts under 500 tokens; total turn input under 2,500 tokens. |
| **Search Latency** | FTS5 symbol queries resolve in under 5ms over local SQLite connections. |
| **Portability** | Zero binary compilation requirements outside standard Python 3.12+ and `uv`. |
| **Zero Secret Leakage** | API keys and tokens injected via in-memory enclaves; never written to SQLite or disk. |
| **Autonomous Reliability** | Multi-agent pipelines recover from transient test failures without human prompts. |

---

## 6. Out of Scope (Anti-Goals)
- Building a custom visual node-graph canvas from scratch (delegated entirely to Orca ADE).
- Implementing proprietary LLM inference engines (delegated to `llama.cpp`, Ollama, vLLM, or remote APIs).
- Persistent multi-turn conversation chats (sub-agents execute single-turn or bounded-turn tasks).
