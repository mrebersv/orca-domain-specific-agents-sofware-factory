"""
Phase 6 Integration Tests: Orca Workspace Manifest Generator.

Tests cover template rendering, schema validation, idempotency, and
generator edge cases for .orca/workspace.yaml creation.
"""

from __future__ import annotations

import tempfile
import yaml
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

# Import the generator module (will be implemented)
from orca_pack.generator import generate_orca_manifest, OrcaManifestGenerator
from orca_pack.templates import load_template


class TestOrcaTemplate:
    """Tests for the Orca workspace YAML template."""

    def test_template_loads(self):
        """Template file exists and loads as valid YAML."""
        template = load_template()
        assert isinstance(template, dict)

    def test_template_has_required_sections(self):
        """Template contains all required top-level sections."""
        template = load_template()

        # Required sections per spec
        assert "mcp_servers" in template
        assert "models" in template
        assert "nodes" in template
        assert "hooks" in template

    def test_mcp_server_docs_db_registration(self):
        """Template registers mcp-docs-db MCP server with stdio transport."""
        template = load_template()
        mcp_servers = template["mcp_servers"]

        assert "docs-db" in mcp_servers
        docs_db = mcp_servers["docs-db"]
        assert docs_db["command"] == "mcp-docs-db"
        assert "--db-path" in " ".join(docs_db.get("args", []))
        assert docs_db["transport"] == "stdio"

    def test_model_endpoints_defined(self):
        """Template defines local-slm and cloud-fallback model endpoints."""
        template = load_template()
        models = template["models"]

        assert "local-slm" in models
        assert models["local-slm"]["base_url"] == "http://127.0.0.1:8000/v1"
        assert models["local-slm"]["api_key"] == "not-needed"
        assert "model" in models["local-slm"]

        assert "cloud-fallback" in models
        assert models["cloud-fallback"]["base_url"] == "https://api.anthropic.com/v1"
        assert "ANTHROPIC_API_KEY" in models["cloud-fallback"]["api_key"]
        assert models["cloud-fallback"]["model"] == "claude-3-5-sonnet-latest"

    def test_agent_nodes_defined(self):
        """Template defines all four required agent nodes."""
        template = load_template()
        nodes = template["nodes"]

        required_nodes = ["test-author-node", "builder-node", "gatekeeper-node", "remediation-node"]
        for node in required_nodes:
            assert node in nodes, f"Missing required node: {node}"

    def test_lifecycle_hooks_bound(self):
        """Template binds pre_node_hook and post_node_hook to hook modules."""
        template = load_template()
        hooks = template["hooks"]

        assert "pre_node_hook" in hooks
        assert "post_node_hook" in hooks
        assert "pre_run" in hooks["pre_node_hook"]
        assert "post_run" in hooks["post_node_hook"]


class TestOrcaManifestGenerator:
    """Tests for the OrcaManifestGenerator class."""

    @pytest.fixture
    def temp_project_root(self):
        """Create a temporary project directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def generator(self):
        """Create a generator instance."""
        return OrcaManifestGenerator()

    def test_generate_creates_orca_directory(self, generator, temp_project_root):
        """Generator creates .orca/ directory if missing."""
        output_path = generator.generate(
            project_root=temp_project_root,
            local_model_name="test-model",
            force_overwrite=True,
        )

        assert output_path.exists()
        assert output_path.parent.name == ".orca"
        assert output_path.name == "workspace.yaml"

    def test_generate_renders_valid_yaml(self, generator, temp_project_root):
        """Generated manifest is valid YAML with expected structure."""
        output_path = generator.generate(
            project_root=temp_project_root,
            local_model_name="qwen2.5-coder-7b",
            force_overwrite=True,
        )

        with open(output_path) as f:
            manifest = yaml.safe_load(f)

        assert isinstance(manifest, dict)
        assert "mcp_servers" in manifest
        assert "models" in manifest
        assert "nodes" in manifest
        assert "hooks" in manifest

    def test_generate_substitutes_local_model_name(self, generator, temp_project_root):
        """Generator substitutes {{ local_model_name }} placeholder."""
        custom_model = "my-custom-model-v1"
        output_path = generator.generate(
            project_root=temp_project_root,
            local_model_name=custom_model,
            force_overwrite=True,
        )

        with open(output_path) as f:
            manifest = yaml.safe_load(f)

        assert manifest["models"]["local-slm"]["model"] == custom_model

    def test_generate_includes_cloud_fallback_when_enabled(self, generator, temp_project_root):
        """Cloud fallback model included when enable_cloud_fallback=True."""
        output_path = generator.generate(
            project_root=temp_project_root,
            enable_cloud_fallback=True,
            force_overwrite=True,
        )

        with open(output_path) as f:
            manifest = yaml.safe_load(f)

        assert "cloud-fallback" in manifest["models"]

    def test_generate_excludes_cloud_fallback_when_disabled(self, generator, temp_project_root):
        """Cloud fallback model excluded when enable_cloud_fallback=False."""
        output_path = generator.generate(
            project_root=temp_project_root,
            enable_cloud_fallback=False,
            force_overwrite=True,
        )

        with open(output_path) as f:
            manifest = yaml.safe_load(f)

        assert "cloud-fallback" not in manifest["models"]

    def test_generate_raises_on_existing_without_force(self, generator, temp_project_root):
        """Generator raises FileExistsError when manifest exists and force=False."""
        # Create first manifest
        generator.generate(
            project_root=temp_project_root,
            force_overwrite=True,
        )

        # Attempt second generation without force
        with pytest.raises(FileExistsError):
            generator.generate(
                project_root=temp_project_root,
                force_overwrite=False,
            )

    def test_generate_overwrites_with_force_true(self, generator, temp_project_root):
        """Generator overwrites existing manifest when force=True."""
        # Create first manifest
        generator.generate(
            project_root=temp_project_root,
            local_model_name="first-model",
            force_overwrite=True,
        )

        # Overwrite with second
        output_path = generator.generate(
            project_root=temp_project_root,
            local_model_name="second-model",
            force_overwrite=True,
        )

        with open(output_path) as f:
            manifest = yaml.safe_load(f)

        assert manifest["models"]["local-slm"]["model"] == "second-model"

    def test_generate_with_env_var_placeholders(self, generator, temp_project_root):
        """Generated manifest preserves environment variable placeholders."""
        output_path = generator.generate(
            project_root=temp_project_root,
            force_overwrite=True,
        )

        with open(output_path) as f:
            content = f.read()

        # Cloud fallback API key should have env var placeholder
        assert "${ANTHROPIC_API_KEY}" in content
        # Docs DB path should have WORKSPACE_ROOT placeholder
        assert "${WORKSPACE_ROOT}" in content


class TestGenerateOrcaManifestFunction:
    """Tests for the module-level generate_orca_manifest function."""

    @pytest.fixture
    def temp_project_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_function_signature_and_return(self, temp_project_root):
        """generate_orca_manifest returns Path to generated manifest."""
        result = generate_orca_manifest(
            project_root=temp_project_root,
            local_model_name="test-model",
            force_overwrite=True,
        )

        assert isinstance(result, Path)
        assert result.exists()
        assert result.name == "workspace.yaml"

    def test_function_uses_default_model_name(self, temp_project_root):
        """Function uses default model name when not specified."""
        result = generate_orca_manifest(
            project_root=temp_project_root,
            force_overwrite=True,
        )

        with open(result) as f:
            manifest = yaml.safe_load(f)

        # Default model name per spec
        assert manifest["models"]["local-slm"]["model"] == "qwen2.5-coder-7b"

    def test_function_creates_parent_directories(self, temp_project_root):
        """Function creates .orca/ directory if it doesn't exist."""
        nested_root = temp_project_root / "nested" / "project"
        nested_root.mkdir(parents=True)

        result = generate_orca_manifest(
            project_root=nested_root,
            force_overwrite=True,
        )

        assert result.exists()
        assert result.parent.name == ".orca"


class TestManifestSchemaValidation:
    """Tests validating generated manifest against expected schema."""

    @pytest.fixture
    def generated_manifest(self, temp_project_root):
        """Generate a manifest for validation tests."""
        gen = OrcaManifestGenerator()
        output_path = gen.generate(
            project_root=temp_project_root,
            force_overwrite=True,
        )
        with open(output_path) as f:
            return yaml.safe_load(f)

    def test_mcp_servers_docs_db_args_structure(self, generated_manifest):
        """mcp-docs-db server has correct args structure."""
        args = generated_manifest["mcp_servers"]["docs-db"]["args"]
        assert isinstance(args, list)
        assert len(args) >= 2
        assert "--db-path" in args
        # Path should contain placeholder
        db_path_idx = args.index("--db-path") + 1
        assert "${WORKSPACE_ROOT}" in args[db_path_idx]

    def test_nodes_have_required_fields(self, generated_manifest):
        """Each node has required fields per spec."""
        nodes = generated_manifest["nodes"]
        for node_name, node_config in nodes.items():
            assert "agent_id" in node_config
            assert "worktree" in node_config
            assert "model" in node_config

    def test_hooks_reference_correct_modules(self, generated_manifest):
        """Hooks reference the correct Python module paths."""
        hooks = generated_manifest["hooks"]
        assert "orca_pack.hooks.pre_run" in hooks["pre_node_hook"]
        assert "orca_pack.hooks.post_run" in hooks["post_node_hook"]


# Fixture for temp_project_root used in TestManifestSchemaValidation
@pytest.fixture
def temp_project_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
