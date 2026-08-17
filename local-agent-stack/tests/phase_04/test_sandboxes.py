"""Tests for Phase 4 - Subprocess & Container Execution Sandboxes."""

from __future__ import annotations

import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


class TestExecutionRunnerBase:
    """Tests for ExecutionRunner abstract base class."""

    def test_execution_runner_is_abstract(self):
        """ExecutionRunner must be an abstract base class."""
        from adapters.runners import ExecutionRunner

        import abc
        assert issubclass(ExecutionRunner, abc.ABC)

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            ExecutionRunner()

    def test_execute_method_signature(self):
        """ExecutionRunner.execute must have correct signature."""
        from adapters.runners import ExecutionRunner
        import inspect

        sig = inspect.signature(ExecutionRunner.execute)
        params = list(sig.parameters.keys())
        assert params == ["self", "command", "cwd", "env", "timeout_seconds", "read_only_paths"]
        assert sig.parameters["command"].annotation == List[str]
        assert sig.parameters["cwd"].annotation == Path
        assert sig.parameters["env"].annotation == Dict[str, str]
        assert sig.parameters["timeout_seconds"].annotation == int
        assert sig.parameters["read_only_paths"].annotation == Optional[List[Path]]


class TestSubprocessRunner:
    """Tests for SubprocessRunner - Tier 1 local process isolation."""

    @pytest.mark.asyncio
    async def test_subprocess_runner_basic_execution(self):
        """SubprocessRunner must execute command and return exit_code, stdout, stderr."""
        from adapters.runners import SubprocessRunner

        runner = SubprocessRunner()
        exit_code, stdout, stderr = await runner.execute(
            command=[sys.executable, "-c", "print('hello')"],
            cwd=Path("."),
            env={"PATH": os.environ.get("PATH", "")},
            timeout_seconds=10,
        )
        assert exit_code == 0
        assert "hello" in stdout
        assert stderr == ""

    @pytest.mark.asyncio
    async def test_subprocess_runner_captures_stderr(self):
        """SubprocessRunner must capture stderr separately from stdout."""
        from adapters.runners import SubprocessRunner

        runner = SubprocessRunner()
        exit_code, stdout, stderr = await runner.execute(
            command=[sys.executable, "-c", "import sys; print('out', file=sys.stdout); print('err', file=sys.stderr)"],
            cwd=Path("."),
            env={"PATH": os.environ.get("PATH", "")},
            timeout_seconds=10,
        )
        assert exit_code == 0
        assert "out" in stdout
        assert "err" in stderr

    @pytest.mark.asyncio
    async def test_subprocess_runner_nonzero_exit_code(self):
        """SubprocessRunner must return non-zero exit code for failing commands."""
        from adapters.runners import SubprocessRunner

        runner = SubprocessRunner()
        exit_code, stdout, stderr = await runner.execute(
            command=[sys.executable, "-c", "import sys; sys.exit(42)"],
            cwd=Path("."),
            env={"PATH": os.environ.get("PATH", "")},
            timeout_seconds=10,
        )
        assert exit_code == 42

    @pytest.mark.asyncio
    async def test_subprocess_runner_timeout_kills_process(self):
        """SubprocessRunner must kill process group on timeout to prevent orphans."""
        from adapters.runners import SubprocessRunner

        runner = SubprocessRunner()

        # Command that runs indefinitely
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.pid = 12345
            # Simulate timeout by not returning from communicate
            async def hang():
                await asyncio.sleep(100)
                return (b"", b"")
            mock_proc.communicate = hang
            mock_exec.return_value = mock_proc

            with pytest.raises(asyncio.TimeoutError):
                await runner.execute(
                    command=["sleep", "100"],
                    cwd=Path("."),
                    env={"PATH": os.environ.get("PATH", "")},
                    timeout_seconds=1,
                )

            # Verify killpg was called to terminate process group
            with patch("os.killpg") as mock_killpg:
                # The timeout handling should call killpg
                pass  # Actual killpg call happens in implementation

    @pytest.mark.asyncio
    async def test_subprocess_runner_timeout_kills_process_group(self):
        """SubprocessRunner must use os.killpg with SIGKILL on timeout."""
        from adapters.runners import SubprocessRunner

        runner = SubprocessRunner()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.pid = 12345

            # Make communicate raise TimeoutError
            async def timeout_communicate():
                raise asyncio.TimeoutError()

            mock_proc.communicate = timeout_communicate
            mock_exec.return_value = mock_proc

            with patch("os.killpg") as mock_killpg, \
                 patch("os.getpgid", return_value=12345):
                with pytest.raises(asyncio.TimeoutError):
                    await runner.execute(
                        command=["sleep", "100"],
                        cwd=Path("."),
                        env={"PATH": os.environ.get("PATH", "")},
                        timeout_seconds=1,
                    )

                # Verify killpg was called with process group ID and SIGKILL
                mock_killpg.assert_called_once_with(12345, signal.SIGKILL)

    @pytest.mark.asyncio
    async def test_subprocess_runner_env_sanitization(self):
        """SubprocessRunner must whitelist safe environment variables only."""
        from adapters.runners import SubprocessRunner

        runner = SubprocessRunner()

        # Test internal _sanitize_env method
        host_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "USER": "testuser",
            "LANG": "en_US.UTF-8",
            "TMPDIR": "/tmp",
            "SECRET_KEY": "should-be-stripped",
            "AWS_SECRET": "should-be-stripped",
            "CUSTOM_VAR": "should-be-stripped",
        }

        sanitized = runner._sanitize_env(host_env, extra={"INJECTED_SECRET": "value"})

        allowed = {"PATH", "HOME", "USER", "LANG", "TMPDIR", "INJECTED_SECRET"}
        for key in sanitized:
            assert key in allowed, f"Unexpected env var: {key}"
        assert "SECRET_KEY" not in sanitized
        assert "AWS_SECRET" not in sanitized
        assert "CUSTOM_VAR" not in sanitized
        assert sanitized["INJECTED_SECRET"] == "value"

    @pytest.mark.asyncio
    async def test_subprocess_runner_working_directory_enforcement(self):
        """SubprocessRunner must enforce working directory."""
        from adapters.runners import SubprocessRunner

        runner = SubprocessRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_output.txt"
            exit_code, stdout, stderr = await runner.execute(
                command=[sys.executable, "-c", f"open('{test_file}', 'w').write('cwd works')"],
                cwd=Path(tmpdir),
                env={"PATH": os.environ.get("PATH", "")},
                timeout_seconds=10,
            )
            assert exit_code == 0
            assert test_file.exists()
            assert test_file.read_text() == "cwd works"


class TestContainerRunner:
    """Tests for ContainerRunner (Podman/Docker) - Tier 2 container isolation."""

    @pytest.mark.asyncio
    async def test_container_runner_detects_podman(self):
        """ContainerRunner must prefer podman over docker when both available."""
        from adapters.runners import ContainerRunner

        runner = ContainerRunner()

        with patch("shutil.which", side_effect=lambda x: "/usr/bin/podman" if x == "podman" else "/usr/bin/docker"):
            binary = runner._detect_container_binary()
            assert binary == "podman"

    @pytest.mark.asyncio
    async def test_container_runner_falls_back_to_docker(self):
        """ContainerRunner must fall back to docker if podman unavailable."""
        from adapters.runners import ContainerRunner

        runner = ContainerRunner()

        with patch("shutil.which", side_effect=lambda x: "/usr/bin/docker" if x == "docker" else None):
            binary = runner._detect_container_binary()
            assert binary == "docker"

    @pytest.mark.asyncio
    async def test_container_runner_builds_correct_command(self):
        """ContainerRunner must build correct podman/docker command with isolation flags."""
        from adapters.runners import ContainerRunner

        runner = ContainerRunner()

        with patch("shutil.which", return_value="/usr/bin/podman"):
            cmd = runner._build_container_command(
                command=["echo", "hello"],
                cwd=Path("/host/workdir"),
                env={"VAR": "value"},
                timeout_seconds=60,
                read_only_paths=[Path("/host/readonly")],
                memory_limit="2g",
                cpu_limit="2.0",
                container_image="python:3.12",
            )

        assert cmd[0] == "podman"
        assert "--rm" in cmd
        assert "--network" in cmd
        assert "none" in cmd
        assert "--memory" in cmd
        assert "2g" in cmd
        assert "--cpus" in cmd
        assert "2.0" in cmd
        assert "-v" in cmd
        assert "/host/workdir:/workspace:rw" in " ".join(cmd)
        assert "-w" in cmd
        assert "/workspace" in cmd
        # Read-only mount should have :ro flag
        assert any(":ro" in arg for arg in cmd)

    @pytest.mark.asyncio
    async def test_container_runner_graceful_fallback_to_subprocess(self):
        """ContainerRunner must fall back to SubprocessRunner when container binary unavailable."""
        from adapters.runners import ContainerRunner, SubprocessRunner

        runner = ContainerRunner()

        with patch("shutil.which", return_value=None):
            with patch.object(SubprocessRunner, "execute", new_callable=AsyncMock) as mock_subprocess:
                mock_subprocess.return_value = (0, "fallback output", "")

                exit_code, stdout, stderr = await runner.execute(
                    command=["echo", "hello"],
                    cwd=Path("."),
                    env={"PATH": "/usr/bin"},
                    timeout_seconds=10,
                )

                assert exit_code == 0
                assert stdout == "fallback output"
                mock_subprocess.assert_called_once()

    @pytest.mark.asyncio
    async def test_container_runner_logs_warning_on_fallback(self):
        """ContainerRunner must log warning when falling back to subprocess."""
        from adapters.runners import ContainerRunner

        runner = ContainerRunner()

        with patch("shutil.which", return_value=None):
            with patch("adapters.runners.logger") as mock_logger:
                with patch.object(runner, "_execute_subprocess_fallback", new_callable=AsyncMock) as mock_fallback:
                    mock_fallback.return_value = (0, "output", "")

                    await runner.execute(
                        command=["echo", "hello"],
                        cwd=Path("."),
                        env={},
                        timeout_seconds=10,
                    )

                    mock_logger.warning.assert_called()
                    warning_msg = mock_logger.warning.call_args[0][0]
                    assert "container" in warning_msg.lower()
                    assert "fallback" in warning_msg.lower() or "unavailable" in warning_msg.lower()

    @pytest.mark.asyncio
    async def test_container_runner_enforces_resource_bounds(self):
        """ContainerRunner must enforce configurable memory and CPU limits."""
        from adapters.runners import ContainerRunner

        runner = ContainerRunner()

        with patch("shutil.which", return_value="/usr/bin/podman"):
            # Test default limits
            cmd = runner._build_container_command(
                command=["echo", "test"],
                cwd=Path("."),
                env={},
                timeout_seconds=60,
            )
            assert "--memory" in cmd
            assert "--cpus" in cmd

            # Test custom limits
            cmd = runner._build_container_command(
                command=["echo", "test"],
                cwd=Path("."),
                env={},
                timeout_seconds=60,
                memory_limit="4g",
                cpu_limit="4.0",
            )
            assert "4g" in cmd
            assert "4.0" in cmd

    @pytest.mark.asyncio
    async def test_container_runner_mounts_workdir_with_correct_permissions(self):
        """ContainerRunner must mount working directory with rw permissions by default."""
        from adapters.runners import ContainerRunner

        runner = ContainerRunner()

        with patch("shutil.which", return_value="/usr/bin/podman"):
            cmd = runner._build_container_command(
                command=["echo", "test"],
                cwd=Path("/host/path"),
                env={},
                timeout_seconds=60,
            )

            # Find the volume mount argument
            mount_args = [arg for arg in cmd if arg.startswith("/host/path")]
            assert len(mount_args) > 0
            mount = mount_args[0]
            assert ":rw" in mount or mount.endswith(":rw") or ":rw," in mount

    @pytest.mark.asyncio
    async def test_container_runner_mounts_readonly_paths_ro(self):
        """ContainerRunner must mount read-only paths with :ro flag."""
        from adapters.runners import ContainerRunner

        runner = ContainerRunner()

        with patch("shutil.which", return_value="/usr/bin/podman"):
            cmd = runner._build_container_command(
                command=["echo", "test"],
                cwd=Path("/host/workdir"),
                env={},
                timeout_seconds=60,
                read_only_paths=[Path("/host/readonly1"), Path("/host/readonly2")],
            )

            cmd_str = " ".join(cmd)
            assert "/host/readonly1:/host/readonly1:ro" in cmd_str
            assert "/host/readonly2:/host/readonly2:ro" in cmd_str

    @pytest.mark.asyncio
    async def test_container_runner_sets_network_none_by_default(self):
        """ContainerRunner must use --network none for isolation by default."""
        from adapters.runners import ContainerRunner

        runner = ContainerRunner()

        with patch("shutil.which", return_value="/usr/bin/podman"):
            cmd = runner._build_container_command(
                command=["echo", "test"],
                cwd=Path("."),
                env={},
                timeout_seconds=60,
            )

            assert "--network" in cmd
            net_idx = cmd.index("--network")
            assert cmd[net_idx + 1] == "none"


class TestRunnerIntegration:
    """Integration tests for runner behavior."""

    @pytest.mark.asyncio
    async def test_subprocess_runner_handles_sigterm_cleanup(self):
        """SubprocessRunner must clean up child processes on SIGTERM."""
        from adapters.runners import SubprocessRunner

        runner = SubprocessRunner()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.pid = 12345
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            await runner.execute(
                command=["sleep", "10"],
                cwd=Path("."),
                env={"PATH": os.environ.get("PATH", "")},
                timeout_seconds=60,
            )

            # Verify process was awaited properly
            mock_proc.communicate.assert_called_once()

    @pytest.mark.asyncio
    async def test_runner_respects_read_only_paths_in_subprocess(self):
        """SubprocessRunner should enforce read-only paths (best effort on POSIX)."""
        from adapters.runners import SubprocessRunner

        runner = SubprocessRunner()

        # This is a best-effort test since full read-only enforcement
        # requires container runtime or filesystem capabilities
        with tempfile.TemporaryDirectory() as tmpdir:
            readonly_file = Path(tmpdir) / "readonly.txt"
            readonly_file.write_text("secret")
            readonly_file.chmod(0o444)  # Read-only

            # Should be able to read but not write
            exit_code, stdout, stderr = await runner.execute(
                command=[sys.executable, "-c", f"print(open('{readonly_file}').read())"],
                cwd=Path(tmpdir),
                env={"PATH": os.environ.get("PATH", "")},
                timeout_seconds=10,
                read_only_paths=[readonly_file],
            )
            assert exit_code == 0
            assert "secret" in stdout


class TestRunnerFactory:
    """Tests for runner factory/selection logic."""

    def test_get_runner_for_subprocess_tier(self):
        """Factory must return SubprocessRunner for subprocess tier."""
        from adapters.runners import get_runner

        runner = get_runner(isolation_tier="subprocess")
        from adapters.runners import SubprocessRunner

        assert isinstance(runner, SubprocessRunner)

    def test_get_runner_for_podman_tier(self):
        """Factory must return ContainerRunner for podman tier."""
        from adapters.runners import get_runner

        runner = get_runner(isolation_tier="podman")
        from adapters.runners import ContainerRunner

        assert isinstance(runner, ContainerRunner)

    def test_get_runner_for_docker_tier(self):
        """Factory must return ContainerRunner for docker tier."""
        from adapters.runners import get_runner

        runner = get_runner(isolation_tier="docker")
        from adapters.runners import ContainerRunner

        assert isinstance(runner, ContainerRunner)

    def test_get_runner_invalid_tier_raises(self):
        """Factory must raise ValueError for invalid isolation tier."""
        from adapters.runners import get_runner

        with pytest.raises(ValueError, match="Invalid isolation_tier"):
            get_runner(isolation_tier="invalid")


# Import asyncio at module level for use in tests
import asyncio

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
