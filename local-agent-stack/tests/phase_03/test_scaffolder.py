"""Tests for Phase 3 Task 3.3 - Workspace Scaffolder."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
import pytest

from agent_forge.scaffolder import AgentScaffolder, scaffold_agent
from agent_forge.ast_extractor import extract_and_ingest_python_tree
from agent_forge.db.docs import init_docs_db
from agent_forge.verifier import verify_agent_workspace

SAMPLE_PYTHON_CODE = """
\"\"\"Test module for scaffolding.\"\"\"

class Calculator:
    \"\"\"A simple calculator class.\"\"\"

    def add(self, a: int, b: int) -> int:
        \"\"\"Add two numbers.

        Args:
            a: First number.
            b: Second number.

        Returns:
            Sum of a and b.
        \"\"\"
        return a + b

    def multiply(self, x: float, y: float = 2.0) -> float:
        \"\"\"Multiply two numbers.

        Args:
            x: First number.
            y: Second number (default 2.0).

        Returns:
            Product of x and y.
        \"\"\"
        return x * y

def greet(name: str) -> str:
    \"\"\"Greet a person.

    Args:
        name: Person\'s name.

    Returns:
        Greeting message.
    \"\"\"
    return f"Hello, {name}!"
"""

class TestAgentScaffolder:
    """Tests for AgentScaffolder class."""

    @pytest.mark.asyncio
    async def test_scaffold_agent_basic(self):
        """Test basic agent scaffolding."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                scaffolder = AgentScaffolder()
                workspace = await scaffolder.scaffold_agent(
                    agent_id="test_calculator",
                    name="Calculator Agent",
                    description="An agent for mathematical operations",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                assert workspace.exists()
                assert workspace.name == "test_calculator"
                assert (workspace / "prompt.md").exists()
                assert (workspace / "tools.py").exists()
                assert (workspace / "agent.config.json").exists()
                assert (workspace / "docs.db").exists()

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_prompt_md_generation(self):
        """Test prompt.md generation and content."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                scaffolder = AgentScaffolder()
                workspace = await scaffolder.scaffold_agent(
                    agent_id="test_agent",
                    name="Test Agent",
                    description="A test agent",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                prompt_md = (workspace / "prompt.md").read_text()

                assert "# Agent: Test Agent" in prompt_md
                assert "Test Agent" in prompt_md
                assert "A test agent" in prompt_md
                assert "## Role" in prompt_md
                assert "## Available Tools" in prompt_md
                assert "## Tool Usage Instructions" in prompt_md
                assert "## Safety Guardrails" in prompt_md
                assert "## Context Window Economy" in prompt_md

                assert "search_symbols" in prompt_md
                assert "get_symbol_schema" in prompt_md
                assert "list_all_symbols" in prompt_md

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_prompt_token_budget(self):
        """Test that prompt.md is under 500 tokens."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                scaffolder = AgentScaffolder()
                workspace = await scaffolder.scaffold_agent(
                    agent_id="test_agent",
                    name="Test Agent",
                    description="A test agent",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                prompt_md = (workspace / "prompt.md").read_text()
                token_estimate = len(prompt_md) // 4

                assert token_estimate < 500, f"Prompt exceeds 500 tokens: {token_estimate}"

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_tools_py_generation(self):
        """Test tools.py generation and syntax validity."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                scaffolder = AgentScaffolder()
                workspace = await scaffolder.scaffold_agent(
                    agent_id="test_agent",
                    name="Test Agent",
                    description="A test agent",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                tools_py = (workspace / "tools.py").read_text()

                assert "search_symbols" in tools_py
                assert "get_symbol_schema" in tools_py
                assert "list_all_symbols" in tools_py
                assert "async def search_symbols" in tools_py
                assert "async def get_symbol_schema" in tools_py
                assert "async def list_all_symbols" in tools_py
                assert "DOCS_DB_PATH" in tools_py
                assert "aiosqlite" in tools_py

                import ast
                ast.parse(tools_py)

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_agent_config_json_generation(self):
        """Test agent.config.json generation and validity."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                scaffolder = AgentScaffolder()
                workspace = await scaffolder.scaffold_agent(
                    agent_id="test_agent",
                    name="Test Agent",
                    description="A test agent",
                    db_path=db_path,
                    output_dir=output_dir,
                    harness_type="generic_cli",
                    model_name="custom-model",
                    model_endpoint="http://localhost:8080/v1",
                    register_in_registry=False,
                )

                config_json = json.loads((workspace / "agent.config.json").read_text())

                assert config_json["agent_id"] == "test_agent"
                assert config_json["name"] == "Test Agent"
                assert config_json["description"] == "A test agent"
                assert config_json["harness_type"] == "generic_cli"
                assert config_json["model_name"] == "custom-model"
                assert config_json["model_endpoint"] == "http://localhost:8080/v1"
                assert config_json["isolation_tier"] == "subprocess"
                assert config_json["max_turns"] == 6
                assert config_json["timeout_seconds"] == 60

                assert "permissions" in config_json
                assert "allowed_tools" in config_json["permissions"]
                assert "require_approval_for_destructive" in config_json["permissions"]
                assert config_json["permissions"]["require_approval_for_destructive"] is True
                assert "search_symbols" in config_json["permissions"]["allowed_tools"]
                assert "get_symbol_schema" in config_json["permissions"]["allowed_tools"]

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_docs_db_copied(self):
        """Test that docs.db is copied to workspace."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                scaffolder = AgentScaffolder()
                workspace = await scaffolder.scaffold_agent(
                    agent_id="test_agent",
                    name="Test Agent",
                    description="A test agent",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                workspace_db = workspace / "docs.db"
                assert workspace_db.exists()
                assert workspace_db.stat().st_size > 0

                from agent_forge.db.docs import get_docs_db
                async with get_docs_db(workspace_db, read_only=True) as db:
                    async with db.execute("SELECT COUNT(*) FROM symbols") as cursor:
                        row = await cursor.fetchone()
                        assert row[0] > 0

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)


class TestScaffolderIntegration:
    """Integration tests for scaffolder with verifier."""

    @pytest.mark.asyncio
    async def test_scaffold_then_verify(self):
        """Test that scaffolded workspace passes verification."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                workspace = await scaffold_agent(
                    agent_id="verify_test",
                    name="Verify Test Agent",
                    description="Agent for verification testing",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                result = await verify_agent_workspace(workspace)

                assert result["status"] == "passed"
                assert result["agent_id"] == "verify_test"
                assert result["prompt_tokens_est"] < 500
                assert len(result["tools_tested"]) >= 3
                assert result["turns_recorded"] >= 3
                assert len(result["errors"]) == 0

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_multiple_agents_different_workspaces(self):
        """Test scaffolding multiple agents creates separate workspaces."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                workspace1 = await scaffold_agent(
                    agent_id="agent_one",
                    name="Agent One",
                    description="First agent",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                workspace2 = await scaffold_agent(
                    agent_id="agent_two",
                    name="Agent Two",
                    description="Second agent",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                assert workspace1 != workspace2
                assert workspace1.name == "agent_one"
                assert workspace2.name == "agent_two"
                assert workspace1.exists()
                assert workspace2.exists()

                assert (workspace1 / "prompt.md").read_text() != (workspace2 / "prompt.md").read_text()

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)


class TestTokenBudgetEdgeCases:
    """Tests for token budget edge cases."""

    @pytest.mark.asyncio
    async def test_long_description_truncation(self):
        """Test that very long descriptions don\'t exceed token budget."""
        long_description = "A " + "very " * 1000 + "long description"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                scaffolder = AgentScaffolder()
                workspace = await scaffolder.scaffold_agent(
                    agent_id="long_desc_agent",
                    name="Long Description Agent",
                    description=long_description,
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                prompt_md = (workspace / "prompt.md").read_text()
                token_estimate = len(prompt_md) // 4
                assert token_estimate < 500

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)


class TestTemplateRendering:
    """Tests for template rendering."""

    @pytest.mark.asyncio
    async def test_custom_harness_type(self):
        """Test custom harness type in config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                workspace = await scaffold_agent(
                    agent_id="custom_harness",
                    name="Custom Harness Agent",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    harness_type="custom_harness",
                    register_in_registry=False,
                )

                config = json.loads((workspace / "agent.config.json").read_text())
                assert config["harness_type"] == "custom_harness"

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_domain_scope_in_prompt(self):
        """Test domain scope appears in prompt."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write('"""Calculator module."""\nclass Calc: pass')
            source_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                await init_docs_db(db_path)
                await extract_and_ingest_python_tree(source_path, db_path)

                workspace = await scaffold_agent(
                    agent_id="domain_test",
                    name="Domain Test",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                prompt_md = (workspace / "prompt.md").read_text()
                assert "Domain Scope" in prompt_md

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
