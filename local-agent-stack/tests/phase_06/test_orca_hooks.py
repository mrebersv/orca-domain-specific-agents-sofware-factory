"""
Phase 6 Integration Tests: Orca Worktree Lifecycle Hooks.

Tests cover pre_worktree_check, setup_worktree_env, pre_run (VRAM proxy
health check & secret injection), and post_run (diff generation, 
scratch.db recording, HITL snapshot escalation).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

# Import hook modules (will be implemented)
from orca_pack.hooks import (
    pre_worktree_check,
    setup_worktree_env,
    pre_run,
    post_run,
)


class TestPreWorktreeCheck:
    """Tests for pre_worktree_check.py hook."""

    @pytest.fixture
    def git_repo(self):
        """Create a temporary git repository."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
            # Create initial commit
            (repo_path / "README.md").write_text("# Test Repo")
            subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True)
            yield repo_path

    def test_valid_git_repo_passes(self, git_repo):
        """Valid git repository passes pre_worktree_check."""
        # Should not raise
        pre_worktree_check.check_repo_status(git_repo)

    def test_non_git_directory_fails(self):
        """Non-git directory raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(pre_worktree_check.NotGitRepositoryError):
                pre_worktree_check.check_repo_status(Path(tmpdir))

    def test_uncommitted_changes_warns(self, git_repo):
        """Uncommitted changes in root branch produces warning."""
        # Create uncommitted change
        (git_repo / "uncommitted.txt").write_text("uncommitted")

        with patch("orca_pack.hooks.pre_worktree_check.logger") as mock_logger:
            pre_worktree_check.check_repo_status(git_repo)
            mock_logger.warning.assert_called()
            # Warning should mention uncommitted changes
            call_args = str(mock_logger.warning.call_args)
            assert "uncommitted" in call_args.lower() or "dirty" in call_args.lower()

    def test_clean_repo_no_warning(self, git_repo):
        """Clean repo produces no warning."""
        with patch("orca_pack.hooks.pre_worktree_check.logger") as mock_logger:
            pre_worktree_check.check_repo_status(git_repo)
            mock_logger.warning.assert_not_called()


class TestSetupWorktreeEnv:
    """Tests for setup_worktree_env.py hook."""

    @pytest.fixture
    def git_repo_with_env(self):
        """Create a git repo with .env and .agent/docs.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
            (repo_path / "README.md").write_text("# Test")
            subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_path, check=True)

            # Create .env file
            (repo_path / ".env").write_text("TEST_VAR=value\nANTHROPIC_API_KEY=test-key\n")

            # Create .agent/docs.db
            agent_dir = repo_path / ".agent"
            agent_dir.mkdir()
            (agent_dir / "docs.db").write_text("sqlite-db-placeholder")

            yield repo_path

    def test_create_ephemeral_worktree(self, git_repo_with_env):
        """create_ephemeral_worktree creates worktree and copies env/db."""
        branch_name = "task/test-branch"
        worktree_path = setup_worktree_env.create_ephemeral_worktree(git_repo_with_env, branch_name)

        assert worktree_path.exists()
        assert worktree_path.name == branch_name.replace("/", "-")
        assert (worktree_path / ".env").exists()
        assert (worktree_path / ".agent" / "docs.db").exists()

        # Verify .env content copied
        assert (worktree_path / ".env").read_text() == (git_repo_with_env / ".env").read_text()

    def test_create_ephemeral_worktree_new_branch(self, git_repo_with_env):
        """Worktree creates new branch."""
        branch_name = "feature/new-feature"
        worktree_path = setup_worktree_env.create_ephemeral_worktree(git_repo_with_env, branch_name)

        # Check branch exists in worktree
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=worktree_path, capture_output=True, text=True, check=True
        )
        assert result.stdout.strip() == branch_name.replace("/", "-")

    def test_cleanup_worktree_removes_worktree(self, git_repo_with_env):
        """cleanup_worktree removes the worktree directory."""
        branch_name = "task/cleanup-test"
        worktree_path = setup_worktree_env.create_ephemeral_worktree(git_repo_with_env, branch_name)
        assert worktree_path.exists()

        setup_worktree_env.cleanup_worktree(git_repo_with_env, branch_name)

        assert not worktree_path.exists()

    def test_cleanup_worktree_with_delete_branch(self, git_repo_with_env):
        """cleanup_worktree with delete_branch=True removes branch."""
        branch_name = "task/delete-branch"
        setup_worktree_env.create_ephemeral_worktree(git_repo_with_env, branch_name)

        setup_worktree_env.cleanup_worktree(git_repo_with_env, branch_name, delete_branch=True)

        # Branch should be deleted
        result = subprocess.run(
            ["git", "branch", "-a"],
            cwd=git_repo_with_env, capture_output=True, text=True, check=True
        )
        assert branch_name not in result.stdout

    def test_create_ephemeral_worktree_fails_on_dirty_without_force(self, git_repo_with_env):
        """Creating worktree on dirty repo fails without force flag."""
        # Make repo dirty
        (git_repo_with_env / "dirty.txt").write_text("dirty")

        with pytest.raises(setup_worktree_env.WorktreeError):
            setup_worktree_env.create_ephemeral_worktree(git_repo_with_env, "task/dirty")


class TestPreRunHook:
    """Tests for pre_run.py hook - VRAM proxy health & secret injection."""

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent.config.json content."""
        return {
            "env_vars": [
                "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY",
                "CUSTOM_SECRET"
            ]
        }

    @pytest.mark.asyncio
    async def test_check_proxy_health_success(self):
        """check_proxy_health returns 0 when proxy is healthy."""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = AsyncMock(return_value={
                "status": "healthy",
                "upstream_reachable": True
            })
            mock_get.return_value = mock_response

            result = await pre_run.check_proxy_health()
            assert result == 0

    @pytest.mark.asyncio
    async def test_check_proxy_health_unhealthy_status(self):
        """check_proxy_health returns 1 when proxy status is not healthy."""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = AsyncMock(return_value={
                "status": "degraded",
                "upstream_reachable": True
            })
            mock_get.return_value = mock_response

            result = await pre_run.check_proxy_health()
            assert result == 1

    @pytest.mark.asyncio
    async def test_check_proxy_health_upstream_unreachable(self):
        """check_proxy_health returns 1 when upstream is unreachable."""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = AsyncMock(return_value={
                "status": "healthy",
                "upstream_reachable": False
            })
            mock_get.return_value = mock_response

            result = await pre_run.check_proxy_health()
            assert result == 1

    @pytest.mark.asyncio
    async def test_check_proxy_health_connection_error(self):
        """check_proxy_health returns 1 on connection error."""
        import httpx
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
            result = await pre_run.check_proxy_health()
            assert result == 1

    @pytest.mark.asyncio
    async def test_check_proxy_health_timeout(self):
        """check_proxy_health returns 1 on timeout."""
        import httpx
        with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout")):
            result = await pre_run.check_proxy_health()
            assert result == 1

    @pytest.mark.asyncio
    async def test_check_proxy_health_custom_url_and_timeout(self):
        """check_proxy_health respects custom URL and timeout."""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = AsyncMock(return_value={
                "status": "healthy",
                "upstream_reachable": True
            })
            mock_get.return_value = mock_response

            result = await pre_run.check_proxy_health(
                proxy_url="http://custom:9000",
                timeout=5.0
            )
            assert result == 0
            # Verify custom URL was used
            called_url = mock_get.call_args[0][0]
            assert "custom:9000" in called_url

    def test_inject_secrets_into_env(self, mock_agent_config):
        """inject_secrets loads env vars from agent.config.json into process env."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "agent.config.json"
            import json
            config_path.write_text(json.dumps(mock_agent_config))

            # Set some env vars
            os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
            os.environ["CUSTOM_SECRET"] = "test-custom"

            # OPENAI_API_KEY not set - should be skipped
            injected = pre_run.inject_secrets(config_path)

            assert "ANTHROPIC_API_KEY" in injected
            assert injected["ANTHROPIC_API_KEY"] == "test-anthropic-key"
            assert "CUSTOM_SECRET" in injected
            assert "OPENAI_API_KEY" not in injected  # Not set in env

    def test_inject_secrets_no_config_file(self):
        """inject_secrets returns empty dict when config file missing."""
        injected = pre_run.inject_secrets(Path("/nonexistent/agent.config.json"))
        assert injected == {}

    def test_inject_secrets_does_not_write_to_disk(self, mock_agent_config):
        """inject_secrets only modifies subprocess env, never writes to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "agent.config.json"
            import json
            config_path.write_text(json.dumps(mock_agent_config))

            os.environ["ANTHROPIC_API_KEY"] = "secret-value"

            injected = pre_run.inject_secrets(config_path)

            # Verify no file was written
            files = list(Path(tmpdir).rglob("*"))
            assert len(files) == 1  # Only agent.config.json
            assert files[0] == config_path


class TestPostRunHook:
    """Tests for post_run.py hook - diff generation, scratch.db, HITL."""

    @pytest.fixture
    def git_worktree_with_changes(self):
        """Create a git worktree with staged and unstaged changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
            (repo_path / "file1.py").write_text("original")
            subprocess.run(["git", "add", "file1.py"], cwd=repo_path, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_path, check=True)

            # Make changes
            (repo_path / "file1.py").write_text("modified")
            (repo_path / "file2.py").write_text("new file")
            subprocess.run(["git", "add", "file2.py"], cwd=repo_path, check=True)

            yield repo_path

    def test_generate_diff_summary(self, git_worktree_with_changes):
        """generate_diff_summary returns structured diff info."""
        diff = post_run.generate_diff_summary(git_worktree_with_changes)

        assert isinstance(diff, dict)
        assert "stat" in diff
        assert "diff" in diff
        assert "files_changed" in diff

        # Should show file1.py modified and file2.py added
        assert "file1.py" in diff["diff"]
        assert "file2.py" in diff["diff"]

    def test_generate_diff_summary_no_changes(self):
        """generate_diff_summary returns empty diff for clean worktree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_path, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
            (repo_path / "file.py").write_text("content")
            subprocess.run(["git", "add", "file.py"], cwd=repo_path, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_path, check=True)

            diff = post_run.generate_diff_summary(repo_path)

            assert diff["files_changed"] == 0
            assert diff["diff"] == ""

    @pytest.mark.asyncio
    async def test_record_execution_to_scratch_db(self):
        """record_execution writes turn data to scratch.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scratch_db = Path(tmpdir) / "scratch.db"

            await post_run.record_execution(
                scratch_db_path=scratch_db,
                session_id="test-session-123",
                workflow_run_id="run-456",
                step_number=1,
                tool_called="write_file",
                tool_input={"path": "test.py", "content": "print('hello')"},
                tool_output={"success": True, "bytes_written": 20},
                status="success",
                execution_time_ms=150,
            )

            # Verify data was written
            from agent_forge.db.scratch import get_scratch_db, list_execution_turns
            async with get_scratch_db(scratch_db) as db:
                turns = await list_execution_turns(db, "test-session-123")

            assert len(turns) == 1
            turn = turns[0]
            assert turn["tool_called"] == "write_file"
            assert turn["status"] == "success"
            assert turn["execution_time_ms"] == 150
            assert turn["workflow_run_id"] == "run-456"

    @pytest.mark.asyncio
    async def test_record_artifact_to_scratch_db(self):
        """record_artifact writes artifact with SHA256 to scratch.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scratch_db = Path(tmpdir) / "scratch.db"

            artifact_id = "artifact-001"
            content = "generated code content"

            await post_run.record_artifact(
                scratch_db_path=scratch_db,
                artifact_id=artifact_id,
                session_id="test-session",
                artifact_type="generated_code",
                content_raw=content,
                file_path="output/main.py",
                workflow_run_id="run-789",
            )

            from agent_forge.db.scratch import get_scratch_db, list_artifacts
            async with get_scratch_db(scratch_db) as db:
                artifacts = await list_artifacts(db, "test-session")

            assert len(artifacts) == 1
            artifact = artifacts[0]
            assert artifact["artifact_id"] == artifact_id
            assert artifact["artifact_type"] == "generated_code"
            assert artifact["file_path"] == "output/main.py"
            assert artifact["checksum_sha256"] == __import__("hashlib").sha256(content.encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_trigger_hitl_snapshot_on_gatekeeper_failure(self):
        """trigger_hitl_snapshot calls orca snapshot with failure message."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

            await post_run.trigger_hitl_snapshot(
                reason="Gatekeeper failed after 3 remediation attempts in phase-06",
                worktree_path="/tmp/worktree"
            )

            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "orca" in args[0]
            assert "snapshot" in args
            assert "Gatekeeper failed after 3 remediation attempts" in " ".join(args)

    @pytest.mark.asyncio
    async def test_trigger_hitl_snapshot_handles_orca_not_found(self):
        """trigger_hitl_snapshot handles missing orca command gracefully."""
        with patch("subprocess.run", side_effect=FileNotFoundError("orca not found")):
            # Should not raise
            await post_run.trigger_hitl_snapshot(
                reason="Test failure",
                worktree_path="/tmp/worktree"
            )

    @pytest.mark.asyncio
    async def test_post_run_main_flow(self, git_worktree_with_changes):
        """post_run main function orchestrates diff, recording, and HITL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scratch_db = Path(tmpdir) / "scratch.db"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                result = await post_run.main(
                    worktree_path=git_worktree_with_changes,
                    scratch_db_path=scratch_db,
                    session_id="session-123",
                    workflow_run_id="run-456",
                    step_number=2,
                    tool_called="edit_file",
                    tool_input={"path": "file1.py"},
                    tool_output={"success": True},
                    status="success",
                    execution_time_ms=200,
                    gatekeeper_exhausted=False,
                )

            assert result["diff_recorded"] is True
            assert result["turn_recorded"] is True
            assert result["hitl_triggered"] is False

    @pytest.mark.asyncio
    async def test_post_run_triggers_hitl_when_gatekeeper_exhausted(self, git_worktree_with_changes):
        """post_run triggers HITL when gatekeeper_exhausted=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            scratch_db = Path(tmpdir) / "scratch.db"

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)

                result = await post_run.main(
                    worktree_path=git_worktree_with_changes,
                    scratch_db_path=scratch_db,
                    session_id="session-123",
                    workflow_run_id="run-456",
                    step_number=5,
                    tool_called="pytest",
                    tool_input={},
                    tool_output={"passed": False},
                    status="error",
                    execution_time_ms=5000,
                    gatekeeper_exhausted=True,
                )

            assert result["hitl_triggered"] is True
            # Verify orca snapshot was called
            snapshot_calls = [c for c in mock_run.call_args_list if "snapshot" in str(c)]
            assert len(snapshot_calls) >= 1
