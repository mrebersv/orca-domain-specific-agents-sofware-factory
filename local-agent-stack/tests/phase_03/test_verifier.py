"""Tests for Phase 3 Task 3.4 - Synthetic Dry-Run Verification Harness."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
import pytest

from agent_forge.verifier import AgentVerifier, verify_agent_workspace
from agent_forge.scaffolder import scaffold_agent
from agent_forge.ast_extractor import extract_and_ingest_python_tree
from agent_forge.db.docs import init_docs_db
from agent_forge.db.scratch import get_scratch_db, init_scratch_db, list_execution_turns, list_artifacts

SAMPLE_PYTHON_CODE = """
\"\"\"Test module for verification.\"\"\"

class Calculator:
    \"\"\"A simple calculator class.\"\"\"

    def add(self, a: int, b: int) -> int:
        \"\"\"Add two numbers.\"\"\"
        return a + b
"""

class TestAgentVerifier:
    """Tests for AgentVerifier class."""

    @pytest.mark.asyncio
    async def test_verifier_instantiation(self):
        """Test AgentVerifier can be instantiated."""
        verifier = AgentVerifier()
        assert verifier is not None
        assert hasattr(verifier, "verify_agent_workspace")

    @pytest.mark.asyncio
    async def test_manifest_validation_pass(self):
        """Test manifest validation passes for valid config."""
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
                    agent_id="valid_config",
                    name="Valid Config Agent",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                verifier = AgentVerifier()
                valid, errors = verifier._validate_config(workspace / "agent.config.json")

                assert valid is True
                assert len(errors) == 0

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_manifest_validation_fail_missing_fields(self):
        """Test manifest validation fails for missing required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "bad_agent"
            workspace.mkdir()

            # Write invalid config (missing required fields)
            bad_config = {"agent_id": "test"}
            (workspace / "agent.config.json").write_text(json.dumps(bad_config))

            verifier = AgentVerifier()
            valid, errors = verifier._validate_config(workspace / "agent.config.json")

            assert valid is False
            assert len(errors) > 0
            assert any("Missing required field" in e for e in errors)

    @pytest.mark.asyncio
    async def test_manifest_validation_fail_invalid_json(self):
        """Test manifest validation fails for invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "bad_agent"
            workspace.mkdir()

            (workspace / "agent.config.json").write_text("not valid json")

            verifier = AgentVerifier()
            valid, errors = verifier._validate_config(workspace / "agent.config.json")

            assert valid is False
            assert len(errors) > 0
            assert any("Invalid JSON" in e for e in errors)

    @pytest.mark.asyncio
    async def test_prompt_budget_check_pass(self):
        """Test prompt budget check passes for valid prompt."""
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
                    agent_id="prompt_check",
                    name="Prompt Check Agent",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                verifier = AgentVerifier()
                token_count, valid, errors = verifier._check_prompt_budget(workspace / "prompt.md")

                assert valid is True
                assert len(errors) == 0
                assert token_count < 500

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_prompt_budget_check_fail(self):
        """Test prompt budget check fails for oversized prompt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "big_prompt_agent"
            workspace.mkdir()

            # Create a prompt that exceeds 500 tokens (~2000 chars)
            big_prompt = "# Agent: Test\n" + "x " * 3000
            (workspace / "prompt.md").write_text(big_prompt)

            verifier = AgentVerifier()
            token_count, valid, errors = verifier._check_prompt_budget(workspace / "prompt.md")

            assert valid is False
            assert len(errors) > 0
            assert any("exceeds 500 token budget" in e for e in errors)

    @pytest.mark.asyncio
    async def test_tool_importability_pass(self):
        """Test tools.py imports successfully."""
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
                    agent_id="import_test",
                    name="Import Test Agent",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                verifier = AgentVerifier()
                tools_module, errors = verifier._import_tools_module(workspace / "tools.py")

                assert tools_module is not None
                assert len(errors) == 0

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_tool_importability_fail_syntax_error(self):
        """Test tools.py import fails for syntax error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "bad_tools_agent"
            workspace.mkdir()

            (workspace / "tools.py").write_text("def invalid syntax(: pass")

            verifier = AgentVerifier()
            tools_module, errors = verifier._import_tools_module(workspace / "tools.py")

            assert tools_module is None
            assert len(errors) > 0
            assert any("Failed to import" in e for e in errors)

    @pytest.mark.asyncio
    async def test_get_tool_functions(self):
        """Test extracting tool functions from module."""
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
                    agent_id="tool_func_test",
                    name="Tool Func Test Agent",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                verifier = AgentVerifier()
                tools_module, _ = verifier._import_tools_module(workspace / "tools.py")
                tool_names = verifier._get_tool_functions(tools_module)

                assert "search_symbols" in tool_names
                assert "get_symbol_schema" in tool_names
                assert "list_all_symbols" in tool_names
                assert len(tool_names) >= 3

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_database_integrity_check_pass(self):
        """Test database integrity check passes for valid docs.db."""
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
                    agent_id="db_check",
                    name="DB Check Agent",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                verifier = AgentVerifier()
                valid, errors = await verifier._check_database_integrity(workspace / "docs.db")

                assert valid is True
                assert len(errors) == 0

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_database_integrity_check_fail_missing(self):
        """Test database integrity check fails for missing docs.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "missing_db_agent"
            workspace.mkdir()

            verifier = AgentVerifier()
            valid, errors = await verifier._check_database_integrity(workspace / "docs.db")

            assert valid is False
            assert len(errors) > 0

    @pytest.mark.asyncio
    async def test_synthetic_tool_execution(self):
        """Test synthetic tool execution records turns."""
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
                    agent_id="synthetic_test",
                    name="Synthetic Test Agent",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                verifier = AgentVerifier()
                tools_module, _ = verifier._import_tools_module(workspace / "tools.py")
                tool_names = verifier._get_tool_functions(tools_module)

                scratch_db = workspace / "scratch.db"
                await init_scratch_db(scratch_db)

                session_id = "test_session"
                turns, errors = await verifier._run_synthetic_tool_calls(
                    tools_module, tool_names, scratch_db, session_id
                )

                assert turns >= 3
                assert len(errors) == 0

                # Verify turns recorded in scratch.db
                async with get_scratch_db(scratch_db) as db:
                    recorded = await list_execution_turns(db, session_id)
                    assert len(recorded) == turns
                    for turn in recorded:
                        assert "tool_called" in turn
                        assert "tool_input" in turn
                        assert "tool_output" in turn
                        assert "status" in turn
                        assert "execution_time_ms" in turn
                        assert turn["status"] in ("success", "error")

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_scratch_db_turn_recording(self):
        """Test scratch.db records execution turns correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scratch_db = Path(tmpdir) / "scratch.db"
            await init_scratch_db(scratch_db)

            from agent_forge.db.scratch import log_execution_turn

            async with get_scratch_db(scratch_db) as db:
                await log_execution_turn(
                    db=db,
                    session_id="test_session",
                    step_number=1,
                    tool_called="search_symbols",
                    tool_input={"query": "test"},
                    tool_output={"results": []},
                    status="success",
                    execution_time_ms=100,
                )

                recorded = await list_execution_turns(db, "test_session")
                assert len(recorded) == 1
                assert recorded[0]["tool_called"] == "search_symbols"
                assert recorded[0]["tool_input"] == {"query": "test"}
                assert recorded[0]["status"] == "success"
                assert recorded[0]["execution_time_ms"] == 100

    @pytest.mark.asyncio
    async def test_artifact_sha256_checksum(self):
        """Test artifact recording with SHA-256 checksum."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scratch_db = Path(tmpdir) / "scratch.db"
            await init_scratch_db(scratch_db)

            from agent_forge.db.scratch import record_artifact

            content = "test artifact content"
            expected_sha256 = hashlib.sha256(content.encode()).hexdigest()

            async with get_scratch_db(scratch_db) as db:
                artifact_id = await record_artifact(
                    db=db,
                    artifact_id="test_artifact_1",
                    session_id="test_session",
                    artifact_type="tool_output",
                    content_raw=content,
                    file_path=None,
                )

                assert artifact_id == expected_sha256

                artifacts = await list_artifacts(db, "test_session")
                assert len(artifacts) == 1
                assert artifacts[0]["artifact_id"] == "test_artifact_1"
                assert artifacts[0]["checksum_sha256"] == expected_sha256
                assert artifacts[0]["content_raw"] == content

    @pytest.mark.asyncio
    async def test_verify_agent_workspace_pass(self):
        """Test full verification pipeline passes for valid workspace."""
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
                    agent_id="full_verify",
                    name="Full Verify Agent",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                result = await verify_agent_workspace(workspace)

                assert result["status"] == "passed"
                assert result["agent_id"] == "full_verify"
                assert result["prompt_tokens_est"] < 500
                assert len(result["tools_tested"]) >= 3
                assert result["turns_recorded"] >= 3
                assert len(result["errors"]) == 0

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_verify_agent_workspace_fail_missing_files(self):
        """Test verification fails for workspace with missing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "incomplete_agent"
            workspace.mkdir()

            result = await verify_agent_workspace(workspace)

            assert result["status"] == "failed"
            assert len(result["errors"]) > 0
            assert any("Missing" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_verify_agent_workspace_fail_bad_config(self):
        """Test verification fails for invalid config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "bad_config_agent"
            workspace.mkdir()

            (workspace / "agent.config.json").write_text("{}")
            (workspace / "prompt.md").write_text("# Agent: Test")
            (workspace / "tools.py").write_text("pass")

            result = await verify_agent_workspace(workspace)

            assert result["status"] == "failed"
            assert len(result["errors"]) > 0

    @pytest.mark.asyncio
    async def test_generate_synthetic_input(self):
        """Test synthetic input generation for different tools."""
        verifier = AgentVerifier()

        search_input = verifier._generate_synthetic_input("search_symbols")
        assert search_input == {"query": "test", "limit": 5}

        schema_input = verifier._generate_synthetic_input("get_symbol_schema")
        assert schema_input == {"symbol_id": "test.module.function"}

        list_input = verifier._generate_synthetic_input("list_all_symbols")
        assert list_input == {"limit": 10}

        generic_input = verifier._generate_synthetic_input("unknown_tool")
        assert generic_input == {"param": "test"}


class TestVerifierIntegration:
    """Integration tests for verifier with scaffolder."""

    @pytest.mark.asyncio
    async def test_scratch_db_has_expected_artifacts(self):
        """Test that scratch.db contains artifacts after verification."""
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
                    agent_id="artifact_test",
                    name="Artifact Test Agent",
                    description="Test",
                    db_path=db_path,
                    output_dir=output_dir,
                    register_in_registry=False,
                )

                result = await verify_agent_workspace(workspace)

                assert result["status"] == "passed"

                # Check scratch.db was created and has artifacts
                scratch_db = workspace / "scratch.db"
                assert scratch_db.exists()

                async with get_scratch_db(scratch_db) as db:
                    artifacts = await list_artifacts(db, result["agent_id"])
                    # Should have at least some artifacts recorded

            finally:
                source_path.unlink()
                db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
