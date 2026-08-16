Agent Operational Backlog & To-Do List
Phase 0: Host Bootstrapping & Secret Enclave (Grade C — Human One-Time Setup)

    [ ] Task 0.1: Install host prerequisites (orca, python 3.12+, podman or docker, git).

    [ ] Task 0.2: Create root directory: mkdir -p ~/.local-agent-stack/{configs,workspaces,tools,scripts,proxy}.

    [ ] Task 0.3: Populate host environment credentials (e.g., local model base URLs, git credentials) in ~/.local-agent-stack/.env.vault.

Phase 1: Storage Layer & Relational Topology (Grade A — 100% Autonomous)

    [ ] Task 1.1: Scaffold pyproject.toml and lock dependencies (fastapi, aiosqlite, pydantic, tree-sitter, docstring-parser, mcp, pytest, pytest-asyncio).

    [ ] Task 1.2: Write scripts/init_registry_db.py to create ~/.local-agent-stack/registry.db with schemas:

        agents (with harness types: hermes, pi, opencode, claude-code, generic_cli).

        agent_tool_permissions (with is_destructive and requires_approval flags).

        workflows, workflow_runs, and node_execution_checkpoints.

    [ ] Task 1.3: Write scripts/init_docs_db.py template implementing symbols, parameters, examples, error_codes, and the virtual FTS5 table symbols_fts with automated SQLite triggers (symbols_ai, symbols_ad, symbols_au).

    [ ] Task 1.4: Write integration tests (tests/test_database_topology.py) verifying CRUD operations, schema constraints, and FTS5 BM25 search ranking.

Phase 2: Meta-Agent Scaffolder / agent-forge (Grade B — Self-Healing Autonomous)

    [ ] Task 2.1: Implement Path A AST Extractor (agent_forge/ast_extractor.py):

        Parse target source files using Python ast and tree-sitter.

        Extract functions, classes, signatures, types, and decorators directly into SQLite symbols.

        Parse docstrings using docstring-parser into parameters, error_codes, and examples.

    [ ] Task 2.2: Implement Path B API Spec Extractor (agent_forge/spec_extractor.py):

        Parse OpenAPI v3 (JSON/YAML) and CLI --help text into symbols and parameters.

    [ ] Task 2.3: Implement Scaffolding Generators (agent_forge/scaffolder.py):

        Emit typed Python tool wrappers (workspaces/{agent_id}/tools.py) with input validation.

        Emit domain system prompts (workspaces/{agent_id}/prompt.md) under 500 tokens.

        Emit runtime manifests (workspaces/{agent_id}/agent.config.json).

    [ ] Task 2.4: Write synthetic dry-run verification harness (agent_forge/verifier.py) that boots the newly created agent in a sandboxed scratchpad and asserts zero-error execution.

Phase 3: JIT Knowledge MCP Server (Grade A — 100% Autonomous)

    [ ] Task 3.1: Implement mcp_server_docs_db/server.py using the official Python MCP SDK.

    [ ] Task 3.2: Register MCP Tools:

        search_symbols(query: str, domain_tag: str = None): Executes FTS5 BM25 query against docs.db in read-only mode (?mode=ro).

        get_symbol_schema(symbol_id: str): Returns exact signatures, parameter constraints, and working examples.

        list_error_codes(symbol_id: str): Returns recovery actions and error semantics.

    [ ] Task 3.3: Test MCP server over stdio using pytest tests/test_mcp_server.py.

Phase 4: Local Model Arbiter & VRAM Semaphore (Grade A — 100% Autonomous)

    [ ] Task 4.1: Build FastAPI Reverse Proxy (proxy/vram_arbiter.py):

        Listen on [http://127.0.0.1:8000/v1](http://127.0.0.1:8000/v1).

        Intercept /v1/chat/completions and /v1/completions.

        Wrap downstream inference calls in an asyncio.Semaphore(1) per physical GPU device to serialize requests and prevent OOM collisions during parallel agent fan-outs.

    [ ] Task 4.2: Implement health checks and fallback routes for remote API bypass.

Phase 5: Harness Adapter & Sandbox Runners (Grade B — Self-Healing Autonomous)

    [ ] Task 5.1: Define adapters/base.py (HarnessAdapter abstract base class).

    [ ] Task 5.2: Implement adapters:

        adapters/pi_adapter.py: Configures CLI flags for Pi Coding Agent (--system-prompt-file, --tools-file, --max-turns).

        adapters/hermes_adapter.py: Configures JSON-RPC / CLI flags for Hermes Agent.

        adapters/generic_cli_adapter.py: Fallback runner for arbitrary terminal-based agents.

    [ ] Task 5.3: Implement execution isolation runners (adapters/runners.py):

        SubprocessRunner: Sets restricted cwd and read-only environment variables.

        PodmanRunner / DockerRunner: Spawns rootless containers mounting only the specific workspace and Git worktree.

Phase 6: Orca ADE Configuration & Workflow Orchestration (Grade A — 100% Autonomous)

    [ ] Task 6.1: Generate orca.yaml in the project root configuring lifecycle hooks and MCP servers.

    [ ] Task 6.2: Implement pre-execution hook (scripts/orca_pre_hook.sh):

        Verify VRAM proxy availability.

        Inject secrets from enclave to runtime memory.

    [ ] Task 6.3: Implement post-execution hook (scripts/orca_post_hook.sh):

        Commit artifacts and turn logs to scratch.db.

        Format git status for Orca diff review.

    [ ] Task 6.4: Implement Python-driven Orca Workflow Script (orchestrator/run_tdd_workflow.py):

        Drive multi-agent loops programmatically via Orca CLI (orca worktree create, orca snapshot).

        Coordinate Planning Agent → Test Author → Builder → Linter → Test Gatekeeper.

        Trigger Orca breakpoints and mobile alerts on gatekeeper exhaustion (max_cycles: 3).

Phase 7: Autonomous End-to-End Self-Validation (Grade B — Self-Healing Autonomous)

    [ ] Task 7.1: Execute full end-to-end synthetic pipeline test:

        Ingest a target library (e.g., fastapi.routing) via agent-forge.

        Verify generated docs.db contains indexed symbols and FTS5 search works.

        Spin up an Orca worktree via orca worktree create.

        Run a TDD build-and-test cycle across two parallel sub-agents.

        Assert clean teardown and artifact registration in registry.db.

    [ ] Task 7.2: Emit an autonomous completion report summarizing all created files, verified tests, and active agent manifests.
