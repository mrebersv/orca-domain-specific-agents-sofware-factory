# SYSTEM ARCHITECTURE & TECHNICAL SPECIFICATION
## Local-First Multi-Agent Platform & Relational Knowledge Engine

---

## 1. Architectural Principles & Invariants

```
                      +----------------------------+
                      |      Composition Over      |
                      |        Inheritance         |
                      +-------------+--------------+
                                    |
        +---------------------------+---------------------------+
        |                           |                           |
        v                           v                           v
+--------------+            +--------------+            +--------------+
| Single Duty  |            |  Relational  |            |  Worktree    |
| Sub-Agents   |            |  Grounding   |            |  Isolation   |
| (< 500 tok)  |            | (docs.db FTS)|            | (Git Worktree|
+--------------+            +--------------+            +--------------+
```

1. **Composition Over Inheritance:** Monolithic agents are forbidden. Tasks are executed by single-responsibility sub-agents coordinated via deterministic state machines.
2. **Relational Grounding:** Sub-agents never grep raw repositories for API interfaces. They query local SQLite `docs.db` via SQL/FTS5 tools.
3. **Strict Ephemeral Isolation:** Code modifications occur inside ephemeral Git worktrees (`git worktree add -b ...`). Worktrees are cleaned up post-verification.
4. **Hardware-Safe Serialization:** Concurrent agent inferences against local GPU backends route through a semaphore-gated local proxy to eliminate OOMs.
5. **Independent Gatekeeping:** The agent authoring tests is strictly decoupled from the agent implementing the code.

---

## 2. Relational Database Topology (SQLite)

The architecture uses three separate SQLite databases to decouple stack configuration, domain knowledge, and ephemeral runtime logs.

```
                              ~/.local-agent-stack/
                                       |
        +------------------------------+------------------------------+
        |                              |                              |
        v                              v                              v
  [registry.db]                [{agent}/docs.db]              [{agent}/scratch.db]
  * Global Agents              * AST Symbols Table            * Execution Turns
  * Harness Manifests          * FTS5 BM25 Virtual Table      * Generated Artifacts
  * Workflow Run Checkpoints   * Parameter Schemas            * Gatekeeper Logs
```

### 2.1 Stack Registry & Workflow Store (`registry.db`)
```sql
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    harness_type TEXT NOT NULL,            -- 'hermes', 'pi', 'opencode', 'claude-code', 'generic_cli'
    harness_binary TEXT,                   -- Path or command binary
    model_name TEXT NOT NULL,
    model_endpoint TEXT NOT NULL,          -- Local proxy or remote URL
    api_key_env_var TEXT,                  -- Reference name in secret enclave
    isolation_tier TEXT CHECK(isolation_tier IN ('subprocess', 'podman', 'docker')) DEFAULT 'subprocess',
    container_image TEXT,                  -- Optional container image for Tier 2
    max_turns INTEGER DEFAULT 6,
    timeout_seconds INTEGER DEFAULT 60,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_tool_permissions (
    agent_id TEXT REFERENCES agents(agent_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    is_destructive BOOLEAN DEFAULT 0,
    requires_approval BOOLEAN DEFAULT 0,   -- Triggers Orca HITL breakpoint if 1
    PRIMARY KEY (agent_id, tool_name)
);

CREATE TABLE IF NOT EXISTS workflows (
    workflow_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    dag_definition JSON NOT NULL,          -- Nodes, edges, conditions, gatekeeper policies
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id TEXT PRIMARY KEY,
    workflow_id TEXT REFERENCES workflows(workflow_id),
    status TEXT CHECK(status IN ('pending', 'running', 'paused_approval_required', 'paused_gatekeeper_failed', 'completed', 'failed', 'aborted')) NOT NULL,
    current_node_id TEXT,
    global_context JSON DEFAULT '{}',
    git_worktree_path TEXT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME
);

CREATE TABLE IF NOT EXISTS node_execution_checkpoints (
    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    iteration INTEGER DEFAULT 1,
    node_status TEXT CHECK(node_status IN ('pending', 'executing', 'passed', 'failed', 'paused')) NOT NULL,
    input_artifacts JSON,
    output_artifacts JSON,
    stderr_log TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 Domain Knowledge Base (`{agent}/docs.db`)
```sql
CREATE TABLE IF NOT EXISTS symbols (
    symbol_id TEXT PRIMARY KEY,            -- e.g., 'fastapi.routing.APIRoute' or 'POST /api/v1/units'
    symbol_type TEXT NOT NULL,            -- 'function', 'class', 'method', 'endpoint', 'cli_command'
    parent_scope TEXT,                    -- Module name, class name, or route base
    signature TEXT NOT NULL,              -- Full typed signature or route definition
    return_type TEXT,                     -- Return type annotation or response model
    docstring_raw TEXT,
    source_file TEXT,
    is_destructive BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id TEXT REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    param_type TEXT,
    default_value TEXT,
    is_required BOOLEAN NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS examples (
    example_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_id TEXT REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    code_snippet TEXT NOT NULL,
    source_origin TEXT                    -- 'extracted_docstring', 'source_repo', 'meta_agent'
);

CREATE TABLE IF NOT EXISTS error_codes (
    code TEXT PRIMARY KEY,
    symbol_id TEXT REFERENCES symbols(symbol_id) ON DELETE CASCADE,
    meaning TEXT NOT NULL,
    recovery_action TEXT NOT NULL
);

-- Native SQLite FTS5 Virtual Table for high-speed BM25 full-text indexing
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    symbol_id,
    parent_scope,
    signature,
    docstring_raw,
    content='symbols',
    content_rowid='rowid'
);

-- FTS5 Auto-Sync Triggers
CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
  INSERT INTO symbols_fts(rowid, symbol_id, parent_scope, signature, docstring_raw)
  VALUES (new.rowid, new.symbol_id, new.parent_scope, new.signature, new.docstring_raw);
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
  INSERT INTO symbols_fts(symbols_fts, rowid, symbol_id, parent_scope, signature, docstring_raw)
  VALUES('delete', old.rowid, old.symbol_id, old.parent_scope, old.signature, old.docstring_raw);
END;

CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
  INSERT INTO symbols_fts(symbols_fts, rowid, symbol_id, parent_scope, signature, docstring_raw)
  VALUES('delete', old.rowid, old.symbol_id, old.parent_scope, old.signature, old.docstring_raw);
  INSERT INTO symbols_fts(rowid, symbol_id, parent_scope, signature, docstring_raw)
  VALUES (new.rowid, new.symbol_id, new.parent_scope, new.signature, new.docstring_raw);
END;
```

### 2.3 Ephemeral Execution Scratchpad (`{agent}/scratch.db`)
```sql
CREATE TABLE IF NOT EXISTS execution_turns (
    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    workflow_run_id TEXT,
    step_number INTEGER NOT NULL,
    tool_called TEXT NOT NULL,
    tool_input JSON NOT NULL,
    tool_output JSON NOT NULL,
    status TEXT CHECK(status IN ('success', 'error', 'retry')),
    execution_time_ms INTEGER NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    workflow_run_id TEXT,
    artifact_type TEXT NOT NULL,           -- 'plan', 'test_suite', 'source_code', 'lint_report', 'diff'
    file_path TEXT,
    content_raw TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. Pluggable Harness Adapter Interface

Third-party agent harnesses are driven through an extensible Python abstract base class:

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List


class HarnessAdapter(ABC):

    def __init__(self, agent_config: Dict[str, Any], workspace_dir: Path):
        self.config = agent_config
        self.workspace_dir = workspace_dir

    @abstractmethod
    def build_execution_command(
        self, task_prompt: str, worktree_path: Path
    ) -> List[str]:
        """Translates governance parameters, prompt.md, tools.py, and max_turns into CLI args."""
        pass

    @abstractmethod
    async def run_turn(
        self, task_prompt: str, worktree_path: Path, secrets: Dict[str, str]
    ) -> Dict[str, Any]:
        """Executes a single agent task and records step outputs and generated artifacts into scratch.db."""
        pass

    @abstractmethod
    async def stream_events(
        self, task_prompt: str, worktree_path: Path, secrets: Dict[str, str]
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streams real-time token outputs, tool calls, and logs to standard logging/SSE channels."""
        pass
```

---

## 4. Model Context Protocol (MCP) Knowledge Server

The JIT knowledge engine exposes `docs.db` via a standard FastMCP server (`mcp_server_docs_db`):

```
+-------------------------------------------------------------+
|                 MCP Client (Orca / Claude Code)             |
+------------------------------+------------------------------+
                               | JSON-RPC (stdio / HTTP)
                               v
+-------------------------------------------------------------+
|                   FastMCP Knowledge Server                  |
+-------------------------------------------------------------+
|  * search_symbols(query, parent_scope) -> FTS5 BM25 matches |
|  * get_symbol_schema(symbol_id)        -> Full typed params |
|  * get_symbol_examples(symbol_id)      -> Extracted snippets|
|  * list_error_codes(symbol_id)         -> Recovery actions  |
+------------------------------+------------------------------+
                               | SQLite Read-Only (?mode=ro)
                               v
+-------------------------------------------------------------+
|                       {agent}/docs.db                       |
+-------------------------------------------------------------+
```

---

## 5. Local Model Arbiter & Concurrency Proxy

To eliminate GPU Out-Of-Memory collisions when multiple sub-agents execute simultaneously, all inference requests route through a local reverse proxy (`proxy/vram_arbiter.py`):
- **Base Endpoint:** `http://127.0.0.1:8000/v1`
- **Locking Mechanism:** An `asyncio.Semaphore(1)` per physical GPU serializes incoming `/v1/chat/completions` and `/v1/completions` requests while streaming responses back immediately.
- **Pass-through Routing:** Remote API endpoints (e.g., Anthropic, OpenAI) bypass GPU locks.

---

## 6. Orca ADE Integration & Lifecycle Hooks

```
+------------------------------------------------------------------------+
|                        ORCA ADE WORKSPACE HOOKS                        |
|                                                                        |
|  [Pre-Worktree Hook]                                                   |
|   * Verify VRAM proxy health ([http://127.0.0.1:8000/health](http://127.0.0.1:8000/health))            |
|   * Inject Secret Enclave credentials into runtime memory              |
|                                                                        |
|  [Agent Node Execution]                                                |
|   * Runs isolated inside ${ORCA_WORKTREE_PATH}                         |
|   * Queries JIT knowledge via MCP Server                               |
|                                                                        |
|  [Post-Run Hook]                                                       |
|   * Record turn logs and generated artifacts to scratch.db             |
|   * Stage Git diffs for Orca Monaco review                             |
|   * On Gatekeeper exhaustion (>= 3 cycles), call `orca snapshot`       |
+------------------------------------------------------------------------+
```

---

## 7. Autonomous Phase-Level TDD Engine

```
[Phase Start] ---> [Phase Test Author Agent] ---> Writes tests/phase_XX/
                            |
                            v
                  [Task Builder Agents]    ---> Executes in Worktrees
                            |
                            v
                  [Gatekeeper Agent]       ---> Runs `pytest --json-report`
                            |
              +-------------+-------------+
              |                           |
              v                           v
        [Tests Pass]                [Tests Fail]
              |                           |
              v                     (Cycle < 3) ---> [Remediation Agent] ---+
    [Commit & Advance]                    |                                 |
                                    (Cycle >= 3)                            |
                                          |                                 |
                                          v                                 |
                                [Orca HITL Breakpoint] <--------------------+
```
