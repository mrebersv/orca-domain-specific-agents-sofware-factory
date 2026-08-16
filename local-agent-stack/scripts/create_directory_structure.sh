#!/usr/bin/env bash
set -euo pipefail

# Helper function to create file only if it doesn't already exist
safe_touch() {
    local target="$1"
    if [ ! -e "$target" ]; then
        touch "$target"
        echo "Created: $target"
    else
        echo "Skipped (already exists): $target"
    fi
}

echo "Scaffolding directory structure..."

# 1. Directories
mkdir -p \
    specs/phases/phase-01-scaffolding-storage/tasks \
    specs/phases/phase-02-mcp-knowledge-server/tasks \
    specs/phases/phase-03-meta-agent-forge/tasks \
    specs/phases/phase-04-harness-adapters-sandboxing/tasks \
    specs/phases/phase-05-local-infrastructure-proxy/tasks \
    specs/phases/phase-06-orca-ade-integration/tasks \
    specs/phases/phase-07-e2e-verification-packaging/tasks \
    agent_forge/db \
    agent_forge/templates \
    mcp_server/tools \
    adapters \
    proxy \
    orca_pack/templates \
    orca_pack/hooks \
    orca_pack/workflows \
    scripts \
    tests/phase_01 \
    tests/phase_02 \
    tests/phase_03 \
    tests/phase_04 \
    tests/phase_05 \
    tests/phase_06 \
    tests/phase_07

echo "Provisioning placeholder files without overwriting existing content..."

# 2. Root Project Files
safe_touch "pyproject.toml"
safe_touch "requirements.txt"
safe_touch "install.sh"
safe_touch "README.md"
safe_touch ".env.example"

# 3. Specs & Plan Files
safe_touch "specs/PRD.md"
safe_touch "specs/ARCHITECTURE.md"
safe_touch "specs/plan.json"

# Phase 1 Specs
safe_touch "specs/phases/phase-01-scaffolding-storage/PHASE_OVERVIEW.md"
safe_touch "specs/phases/phase-01-scaffolding-storage/tasks/task-1.1-packaging-pyproject.md"
safe_touch "specs/phases/phase-01-scaffolding-storage/tasks/task-1.2-install-script.md"
safe_touch "specs/phases/phase-01-scaffolding-storage/tasks/task-1.3-registry-db-schema.md"
safe_touch "specs/phases/phase-01-scaffolding-storage/tasks/task-1.4-docs-db-fts5-schema.md"

# Phase 2 Specs
safe_touch "specs/phases/phase-02-mcp-knowledge-server/PHASE_OVERVIEW.md"
safe_touch "specs/phases/phase-02-mcp-knowledge-server/tasks/task-2.1-mcp-server-core.md"
safe_touch "specs/phases/phase-02-mcp-knowledge-server/tasks/task-2.2-mcp-search-symbols-tool.md"
safe_touch "specs/phases/phase-02-mcp-knowledge-server/tasks/task-2.3-mcp-schema-tools.md"
safe_touch "specs/phases/phase-02-mcp-knowledge-server/tasks/task-2.4-mcp-stdio-tests.md"

# Phase 3 Specs
safe_touch "specs/phases/phase-03-meta-agent-forge/PHASE_OVERVIEW.md"
safe_touch "specs/phases/phase-03-meta-agent-forge/tasks/task-3.1-ast-python-parser.md"
safe_touch "specs/phases/phase-03-meta-agent-forge/tasks/task-3.2-spec-openapi-parser.md"
safe_touch "specs/phases/phase-03-meta-agent-forge/tasks/task-3.3-scaffolder-code-generator.md"
safe_touch "specs/phases/phase-03-meta-agent-forge/tasks/task-3.4-synthetic-verifier.md"

# Phase 4 Specs
safe_touch "specs/phases/phase-04-harness-adapters-sandboxing/PHASE_OVERVIEW.md"
safe_touch "specs/phases/phase-04-harness-adapters-sandboxing/tasks/task-4.1-harness-adapter-base.md"
safe_touch "specs/phases/phase-04-harness-adapters-sandboxing/tasks/task-4.2-pi-hermes-opencode-adapters.md"
safe_touch "specs/phases/phase-04-harness-adapters-sandboxing/tasks/task-4.3-subprocess-podman-runners.md"

# Phase 5 Specs
safe_touch "specs/phases/phase-05-local-infrastructure-proxy/PHASE_OVERVIEW.md"
safe_touch "specs/phases/phase-05-local-infrastructure-proxy/tasks/task-5.1-fastapi-reverse-proxy.md"
safe_touch "specs/phases/phase-05-local-infrastructure-proxy/tasks/task-5.2-asyncio-gpu-semaphore-arbiter.md"

# Phase 6 Specs
safe_touch "specs/phases/phase-06-orca-ade-integration/PHASE_OVERVIEW.md"
safe_touch "specs/phases/phase-06-orca-ade-integration/tasks/task-6.1-orca-yaml-generator.md"
safe_touch "specs/phases/phase-06-orca-ade-integration/tasks/task-6.2-worktree-lifecycle-hooks.md"
safe_touch "specs/phases/phase-06-orca-ade-integration/tasks/task-6.3-tdd-remediation-loop-script.md"

# Phase 7 Specs
safe_touch "specs/phases/phase-07-e2e-verification-packaging/PHASE_OVERVIEW.md"
safe_touch "specs/phases/phase-07-e2e-verification-packaging/tasks/task-7.1-cli-entrypoint-verification.md"
safe_touch "specs/phases/phase-07-e2e-verification-packaging/tasks/task-7.2-e2e-synthetic-pipeline-test.md"

# 4. agent_forge/ Package
safe_touch "agent_forge/__init__.py"
safe_touch "agent_forge/cli.py"
safe_touch "agent_forge/ast_extractor.py"
safe_touch "agent_forge/spec_extractor.py"
safe_touch "agent_forge/scaffolder.py"
safe_touch "agent_forge/verifier.py"
safe_touch "agent_forge/db/__init__.py"
safe_touch "agent_forge/db/registry.py"
safe_touch "agent_forge/db/docs.py"
safe_touch "agent_forge/db/scratch.py"
safe_touch "agent_forge/templates/prompt.template.md"
safe_touch "agent_forge/templates/tools.template.py"
safe_touch "agent_forge/templates/agent.config.template.json"

# 5. mcp_server/ Package
safe_touch "mcp_server/__init__.py"
safe_touch "mcp_server/__main__.py"
safe_touch "mcp_server/server.py"
safe_touch "mcp_server/db.py"
safe_touch "mcp_server/tools/__init__.py"
safe_touch "mcp_server/tools/search.py"
safe_touch "mcp_server/tools/schema.py"

# 6. adapters/ Package
safe_touch "adapters/__init__.py"
safe_touch "adapters/base.py"
safe_touch "adapters/pi_adapter.py"
safe_touch "adapters/hermes_adapter.py"
safe_touch "adapters/opencode_adapter.py"
safe_touch "adapters/generic_cli_adapter.py"
safe_touch "adapters/runners.py"

# 7. proxy/ Package
safe_touch "proxy/__init__.py"
safe_touch "proxy/server.py"
safe_touch "proxy/vram_arbiter.py"
safe_touch "proxy/check_vram.py"

# 8. orca_pack/ Package
safe_touch "orca_pack/__init__.py"
safe_touch "orca_pack/generator.py"
safe_touch "orca_pack/templates/orca.template.yaml"
safe_touch "orca_pack/hooks/__init__.py"
safe_touch "orca_pack/hooks/pre_run.py"
safe_touch "orca_pack/hooks/post_run.py"
safe_touch "orca_pack/hooks/pre_worktree_check.py"
safe_touch "orca_pack/hooks/setup_worktree_env.py"
safe_touch "orca_pack/workflows/__init__.py"
safe_touch "orca_pack/workflows/tdd_workflow.py"

# 9. scripts/ Directory
safe_touch "scripts/run_autonomous_build.py"
safe_touch "scripts/init_registry_db.py"
safe_touch "scripts/init_docs_db.py"

# 10. tests/ Directory
safe_touch "tests/conftest.py"
safe_touch "tests/phase_01/test_registry_db.py"
safe_touch "tests/phase_01/test_docs_fts5.py"
safe_touch "tests/phase_01/test_installer.py"
safe_touch "tests/phase_02/test_mcp_server.py"
safe_touch "tests/phase_02/test_fts5_tools.py"
safe_touch "tests/phase_03/test_ast_extractor.py"
safe_touch "tests/phase_03/test_spec_extractor.py"
safe_touch "tests/phase_03/test_scaffolder.py"
safe_touch "tests/phase_04/test_harness_adapters.py"
safe_touch "tests/phase_04/test_sandboxes.py"
safe_touch "tests/phase_05/test_vram_proxy.py"
safe_touch "tests/phase_05/test_semaphore_queue.py"
safe_touch "tests/phase_06/test_orca_generator.py"
safe_touch "tests/phase_06/test_orca_hooks.py"
safe_touch "tests/phase_06/test_tdd_loop.py"
safe_touch "tests/phase_07/test_cli_commands.py"
safe_touch "tests/phase_07/test_e2e_pipeline.py"

# Ensure execution bits on scripts
chmod +x install.sh 2>/dev/null || true
chmod +x scripts/*.py 2>/dev/null || true

echo "Architecture tree successfully initialized."
