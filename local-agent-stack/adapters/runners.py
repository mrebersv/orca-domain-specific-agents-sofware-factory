"""
Tiered Execution Sandboxes for Harness Adapters

Provides isolated execution environments across two tiers:
- Tier 1: Local subprocess isolation with environment sanitization
- Tier 2: Rootless Podman/Docker container isolation with resource bounds
"""

import asyncio
import logging
import os
import shutil
import signal
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Use the logger name that tests expect: "adapters.runners"
logger = logging.getLogger("adapters.runners")


class ExecutionRunner(ABC):
    """
    Abstract base class for execution runners.

    Defines the interface for executing commands in isolated environments
    with configurable timeouts, working directories, environment variables,
    and read-only path enforcement.
    """

    @abstractmethod
    async def execute(
        self,
        command: List[str],
        cwd: Path,
        env: Dict[str, str],
        timeout_seconds: int = 60,
        read_only_paths: Optional[List[Path]] = None,
    ) -> Tuple[int, str, str]:  # (exit_code, stdout, stderr)
        """
        Execute a command in the isolated environment.

        Args:
            command: List of command arguments to execute.
            cwd: Working directory for command execution.
            env: Environment variables to pass to the command.
            timeout_seconds: Maximum execution time in seconds.
            read_only_paths: Optional list of paths to mount as read-only.

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        pass


class SubprocessRunner(ExecutionRunner):
    """
    Tier 1: Local subprocess execution with process group isolation.

    Executes commands using asyncio subprocess with:
    - Process group creation for clean timeout killing
    - Environment variable whitelisting/sanitization
    - Working directory enforcement
    """

    # Whitelisted environment variables that are safe to pass through
    ALLOWED_ENV_VARS = {"PATH", "HOME", "USER", "LANG", "TMPDIR"}

    def __init__(self) -> None:
        """Initialize the subprocess runner."""
        super().__init__()

    def _sanitize_env(
        self, host_env: Dict[str, str], extra: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """
        Sanitize environment by keeping only whitelisted variables plus extras.

        Args:
            host_env: The host environment dictionary.
            extra: Additional environment variables to inject (e.g., secrets).

        Returns:
            Sanitized environment dictionary.
        """
        sanitized = {}
        for key in self.ALLOWED_ENV_VARS:
            if key in host_env:
                sanitized[key] = host_env[key]

        # Inject extra variables (secrets, etc.)
        if extra:
            sanitized.update(extra)

        return sanitized

    async def execute(
        self,
        command: List[str],
        cwd: Path,
        env: Dict[str, str],
        timeout_seconds: int = 60,
        read_only_paths: Optional[List[Path]] = None,
    ) -> Tuple[int, str, str]:
        """
        Execute command in a local subprocess with timeout and process group isolation.

        Args:
            command: Command and arguments to execute.
            cwd: Working directory.
            env: Environment variables (will be sanitized).
            timeout_seconds: Execution timeout.
            read_only_paths: Not enforced at subprocess level (best effort via filesystem perms).

        Returns:
            Tuple of (exit_code, stdout, stderr).

        Raises:
            asyncio.TimeoutError: If command exceeds timeout.
        """
        # Sanitize environment
        sanitized_env = self._sanitize_env(env)

        # Ensure working directory exists
        cwd.mkdir(parents=True, exist_ok=True)

        # Create subprocess with process group isolation
        # start_new_session=True creates a new process group
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            env=sanitized_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # Creates new process group for killpg
        )

        try:
            # Wait for completion with timeout
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            exit_code = proc.returncode if proc.returncode is not None else -1

        except asyncio.TimeoutError:
            # Kill the entire process group to eliminate dangling children
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
                logger.warning(
                    "Subprocess timeout: killed process group %d (PID %d)",
                    pgid,
                    proc.pid,
                )
            except ProcessLookupError:
                # Process already exited
                pass
            except Exception as e:
                logger.error("Failed to kill process group on timeout: %s", e)

            # Wait a bit for cleanup
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

            raise

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        return exit_code, stdout, stderr


class ContainerRunner(ExecutionRunner):
    """
    Tier 2: Rootless Podman/Docker container execution.

    Provides stronger isolation through containerization with:
    - Ephemeral containers (--rm)
    - Network isolation (--network none)
    - Resource limits (--memory, --cpus)
    - Read-only volume mounts
    - Automatic fallback to SubprocessRunner if container runtime unavailable
    """

    DEFAULT_MEMORY_LIMIT = "2g"
    DEFAULT_CPU_LIMIT = "2.0"
    DEFAULT_CONTAINER_IMAGE = "python:3.12-slim"

    def __init__(
        self,
        memory_limit: str = DEFAULT_MEMORY_LIMIT,
        cpu_limit: str = DEFAULT_CPU_LIMIT,
        container_image: str = DEFAULT_CONTAINER_IMAGE,
        prefer_podman: bool = True,
    ) -> None:
        """
        Initialize the container runner.

        Args:
            memory_limit: Memory limit for container (e.g., "2g", "512m").
            cpu_limit: CPU limit for container (e.g., "2.0", "1.5").
            container_image: Default container image to use.
            prefer_podman: If True, prefer Podman over Docker.
        """
        super().__init__()
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.container_image = container_image
        self.prefer_podman = prefer_podman
        self._container_binary: Optional[str] = None
        self._fallback_runner = SubprocessRunner()

    def _detect_container_binary(self) -> Optional[str]:
        """
        Detect available container runtime binary.

        Returns:
            Binary name ("podman" or "docker") or None if neither available.
        """
        if self.prefer_podman:
            if shutil.which("podman"):
                return "podman"
            if shutil.which("docker"):
                return "docker"
        else:
            if shutil.which("docker"):
                return "docker"
            if shutil.which("podman"):
                return "podman"
        return None

    def _build_container_command(
        self,
        command: List[str],
        cwd: Path,
        env: Dict[str, str],
        timeout_seconds: int = 60,
        read_only_paths: Optional[List[Path]] = None,
        memory_limit: Optional[str] = None,
        cpu_limit: Optional[str] = None,
        container_image: Optional[str] = None,
    ) -> List[str]:
        """
        Build the podman/docker command with isolation flags.

        Args:
            command: Command to run inside container.
            cwd: Host working directory to mount.
            env: Environment variables to pass.
            timeout_seconds: Not used directly (handled by runner).
            read_only_paths: Paths to mount as read-only.
            memory_limit: Override memory limit.
            cpu_limit: Override CPU limit.
            container_image: Override container image.

        Returns:
            List of command arguments for podman/docker.
        """
        binary = self._detect_container_binary()
        if not binary:
            raise RuntimeError("No container runtime available (podman or docker)")

        mem = memory_limit or self.memory_limit
        cpu = cpu_limit or self.cpu_limit
        image = container_image or self.container_image

        cmd = [
            binary,
            "run",
            "--rm",  # Ephemeral container
            "--network",
            "none",  # Network isolation
            "--memory",
            mem,
            "--cpus",
            cpu,
            "-v",
            f"{cwd}:/workspace:rw",  # Mount workdir as workspace
            "-w",
            "/workspace",  # Set working directory inside container
        ]

        # Add environment variables
        for key, value in env.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Add read-only volume mounts
        if read_only_paths:
            for ro_path in read_only_paths:
                ro_path_str = str(ro_path)
                cmd.extend(["-v", f"{ro_path_str}:{ro_path_str}:ro"])

        # Add container image and command
        cmd.append(image)
        cmd.extend(command)

        return cmd

    async def _execute_subprocess_fallback(
        self,
        command: List[str],
        cwd: Path,
        env: Dict[str, str],
        timeout_seconds: int,
        read_only_paths: Optional[List[Path]] = None,
    ) -> Tuple[int, str, str]:
        """
        Fallback to subprocess execution when container runtime unavailable.

        Args:
            command: Command to execute.
            cwd: Working directory.
            env: Environment variables.
            timeout_seconds: Execution timeout.
            read_only_paths: Read-only paths (not enforced in fallback).

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        return await self._fallback_runner.execute(
            command, cwd, env, timeout_seconds, read_only_paths
        )

    async def execute(
        self,
        command: List[str],
        cwd: Path,
        env: Dict[str, str],
        timeout_seconds: int = 60,
        read_only_paths: Optional[List[Path]] = None,
    ) -> Tuple[int, str, str]:
        """
        Execute command in a container with fallback to subprocess.

        Args:
            command: Command and arguments to execute.
            cwd: Working directory on host.
            env: Environment variables.
            timeout_seconds: Execution timeout.
            read_only_paths: Paths to mount read-only.

        Returns:
            Tuple of (exit_code, stdout, stderr).
        """
        binary = self._detect_container_binary()

        if not binary:
            # Log warning before fallback (test expects this)
            logger.warning(
                "Container runtime unavailable, falling back to SubprocessRunner. "
                "Security notice: Isolation level reduced."
            )
            return await self._execute_subprocess_fallback(
                command, cwd, env, timeout_seconds, read_only_paths
            )

        # Build container command
        try:
            container_cmd = self._build_container_command(
                command=command,
                cwd=cwd,
                env=env,
                timeout_seconds=timeout_seconds,
                read_only_paths=read_only_paths,
            )
        except RuntimeError as e:
            logger.error("Failed to build container command: %s", e)
            logger.warning(
                "Container runtime unavailable, falling back to SubprocessRunner. "
                "Security notice: Isolation level reduced."
            )
            return await self._execute_subprocess_fallback(
                command, cwd, env, timeout_seconds, read_only_paths
            )

        logger.debug("Executing container command: %s", " ".join(container_cmd))

        # Execute container command using subprocess runner logic
        # We reuse the subprocess execution but with the container command
        sanitized_env = self._fallback_runner._sanitize_env(env)

        cwd.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            *container_cmd,
            cwd=str(cwd),
            env=sanitized_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            exit_code = proc.returncode if proc.returncode is not None else -1

        except asyncio.TimeoutError:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
                logger.warning(
                    "Container execution timeout: killed process group %d (PID %d)",
                    pgid,
                    proc.pid,
                )
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.error("Failed to kill container process group on timeout: %s", e)

            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

            raise

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        return exit_code, stdout, stderr


def get_runner(isolation_tier: str = "subprocess") -> ExecutionRunner:
    """
    Factory function to get the appropriate runner for an isolation tier.

    Args:
        isolation_tier: One of "subprocess", "podman", or "docker".

    Returns:
        ExecutionRunner instance for the requested tier.

    Raises:
        ValueError: If isolation_tier is invalid.
    """
    tier = isolation_tier.lower()

    if tier == "subprocess":
        return SubprocessRunner()
    elif tier in ("podman", "docker"):
        prefer_podman = tier == "podman"
        return ContainerRunner(prefer_podman=prefer_podman)
    else:
        raise ValueError(
            f"Invalid isolation_tier: '{isolation_tier}'. "
            f"Must be one of: 'subprocess', 'podman', 'docker'"
        )


__all__ = [
    "ExecutionRunner",
    "SubprocessRunner",
    "ContainerRunner",
    "get_runner",
]
