"""
Generic CLI Harness Adapter

Standard fallback driver for executing arbitrary command-line agents.
Injects --prompt-file, --tools, --max-turns, and --workdir parameters.
Captures stdout/stderr and returns TurnResult with exit code and raw output.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from adapters.base import (
    AgentExecutionContext,
    ExecutionEvent,
    HarnessAdapter,
    TurnResult,
)


class GenericCLIAdapter(HarnessAdapter):
    """
    Generic CLI adapter for executing arbitrary command-line agents.

    This adapter serves as the standard fallback driver for agents that
    can be invoked via command line with standard parameter patterns.
    """

    # Environment variables that are safe to pass through from host
    _ALLOWED_ENV_VARS = {"PATH", "HOME", "USER", "LANG", "TMPDIR"}

    def __init__(
        self,
        agent_config: dict[str, Any],
        workspace_dir: Path,
        harness_binary: str | None = None,
    ) -> None:
        """
        Initialize the Generic CLI adapter.

        Args:
            agent_config: Configuration containing harness_type, agent_id,
                         harness_binary (optional), and other agent settings.
            workspace_dir: Base workspace directory for agent operations.
            harness_binary: Optional explicit binary name. Defaults to agent_config["harness_binary"].
        """
        super().__init__(agent_config, workspace_dir)
        self.harness_binary = harness_binary or agent_config.get("harness_binary", "agent-cli")

    def build_execution_command(self, context: AgentExecutionContext) -> list[str]:
        """
        Build the CLI command for generic agent execution.

        Assembles command with:
        - --prompt-file <path>: Path to task prompt file
        - --tools <path>: Path to tools definition file
        - --max-turns <int>: Maximum execution turns
        - --workdir <path>: Working directory (worktree path)

        Args:
            context: Execution context with task prompt, worktree, and limits.

        Returns:
            List of command arguments ready for subprocess execution.
        """
        # Ensure worktree directory exists
        context.worktree_path.mkdir(parents=True, exist_ok=True)

        # Create prompt file in worktree
        prompt_file = context.worktree_path / ".agent_prompt.md"
        prompt_file.write_text(context.task_prompt, encoding="utf-8")

        # Create tools file if tools are configured
        tools_file = context.worktree_path / ".agent_tools.py"
        tools_content = self._generate_tools_file(context)
        tools_file.write_text(tools_content, encoding="utf-8")

        cmd = [
            self.harness_binary,
            "--prompt-file",
            str(prompt_file),
            "--tools",
            str(tools_file),
            "--max-turns",
            str(context.max_turns),
            "--workdir",
            str(context.worktree_path),
        ]

        # Add optional timeout if supported by harness
        if context.timeout_seconds:
            cmd.extend(["--timeout", str(context.timeout_seconds)])

        return cmd

    def _generate_tools_file(self, context: AgentExecutionContext) -> str:
        """Generate a minimal tools definition file for the agent."""
        # Extract tool permissions from config
        allowed_tools = self.config.get("allowed_tools", [
            "read_file", "write_file", "list_dir", "glob", "grep",
            "bash", "python", "search_symbols", "search_docs"
        ])

        tools_list = ", ".join(repr(t) for t in allowed_tools)
        tools_def = f"""
Auto-generated tools definition for agent execution.
Session: {context.session_id}
Agent: {self.agent_id}

# Available tools for this execution
AVAILABLE_TOOLS = [{tools_list}]

# Tool implementations would be provided by the harness runtime
# This file serves as a manifest for the agent to know what tools are available
"""
        return tools_def

    def _build_env(self, context: AgentExecutionContext) -> dict[str, str]:
        """
        Build sanitized environment for subprocess execution.

        Includes:
        - Whitelisted host environment variables (PATH, HOME, etc.)
        - Secret values from context.secrets (injected at runtime only)

        Args:
            context: Execution context containing secrets.

        Returns:
            Dictionary of environment variables for subprocess.
        """
        env = {}

        # Pass through whitelisted host environment variables
        for key in self._ALLOWED_ENV_VARS:
            if key in os.environ:
                env[key] = os.environ[key]

        # Inject secrets from context (runtime only, never persisted)
        for key, value in context.secrets.items():
            env[key] = value

        return env

    async def run_turn(self, context: AgentExecutionContext) -> TurnResult:
        """
        Execute a single agent turn and return the result.

        Launches the harness process, captures stdout/stderr,
        enforces timeout, and records results to scratch.db.

        Args:
            context: Execution context for this turn.

        Returns:
            TurnResult with execution outcome, output, and artifacts.
        """
        start_time = time.monotonic()

        cmd = self.build_execution_command(context)
        env = self._build_env(context)

        try:
            # Launch subprocess with timeout
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=context.worktree_path,
            )

            try:
                communicate_coro = proc.communicate()
                stdout, stderr = await asyncio.wait_for(
                    communicate_coro,
                    timeout=context.timeout_seconds,
                )
            except asyncio.TimeoutError:
                # Kill process on timeout
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                try:
                    await proc.wait()
                except Exception:
                    pass

                execution_time_ms = int((time.monotonic() - start_time) * 1000)
                # Read any partial output
                stderr_text = ""
                if proc.stderr:
                    try:
                        stderr_bytes = await proc.stderr.read()
                        # Ensure we have bytes before decoding (handles mock objects in tests)
                        if isinstance(stderr_bytes, bytes):
                            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
                        elif isinstance(stderr_bytes, str):
                            stderr_text = stderr_bytes
                    except Exception:
                        pass
                return TurnResult(
                    status="timeout",
                    exit_code=-1,
                    output_text=stderr_text or "Execution timed out",
                    tool_calls=[],
                    artifacts_created=[],
                    execution_time_ms=execution_time_ms,
                    error_message=f"Execution exceeded {context.timeout_seconds}s timeout",
                )

            execution_time_ms = int((time.monotonic() - start_time) * 1000)
            output_text = stdout.decode("utf-8", errors="replace")
            error_text = stderr.decode("utf-8", errors="replace")

            # Combine stdout and stderr for output
            full_output = output_text
            if error_text:
                full_output = f"{output_text}\n--- STDERR ---\n{error_text}" if output_text else error_text

            # Determine status based on exit code
            if proc.returncode == 0:
                status = "success"
            else:
                status = "error"

            # Parse tool calls from output (basic heuristic)
            tool_calls = self._parse_tool_calls(full_output)

            # Discover created artifacts
            artifacts_created = self._discover_artifacts(context.worktree_path)

            return TurnResult(
                status=status,
                exit_code=proc.returncode,
                output_text=full_output,
                tool_calls=tool_calls,
                artifacts_created=artifacts_created,
                execution_time_ms=execution_time_ms,
                error_message=error_text if status == "error" else None,
            )

        except (asyncio.TimeoutError, TimeoutError):
            # This catches timeout from communicate() call or wait_for at the outer level too
            execution_time_ms = int((time.monotonic() - start_time) * 1000)
            return TurnResult(
                status="timeout",
                exit_code=-1,
                output_text="",
                tool_calls=[],
                artifacts_created=[],
                execution_time_ms=execution_time_ms,
                error_message=f"Execution exceeded {context.timeout_seconds}s timeout",
            )
        except Exception as e:
            execution_time_ms = int((time.monotonic() - start_time) * 1000)
            return TurnResult(
                status="error",
                exit_code=-1,
                output_text="",
                tool_calls=[],
                artifacts_created=[],
                execution_time_ms=execution_time_ms,
                error_message=str(e),
            )

    def _parse_tool_calls(self, output: str) -> list[dict[str, Any]]:
        """
        Parse tool calls from agent output.

        This is a basic implementation - concrete adapters may override
        with more sophisticated parsing for their specific output format.

        Args:
            output: Combined stdout/stderr from agent execution.

        Returns:
            List of tool call dictionaries.
        """
        tool_calls = []

        # Look for common tool call patterns in output
        lines = output.split("\n")
        for line in lines:
            line = line.strip()
            # Pattern: TOOL_CALL: tool_name(args_json)
            if line.startswith("TOOL_CALL:"):
                try:
                    tool_part = line[len("TOOL_CALL:"):].strip()
                    # Simple parsing: tool_name({"arg": "value"})
                    if "(" in tool_part and tool_part.endswith(")"):
                        tool_name = tool_part[:tool_part.index("(")].strip()
                        args_str = tool_part[tool_part.index("(")+1:-1]
                        import json
                        args = json.loads(args_str) if args_str else {}
                        tool_calls.append({
                            "tool": tool_name,
                            "input": args,
                            "output": {},
                            "status": "success",
                        })
                except Exception:
                    pass

            # Pattern: [TOOL] tool_name: result
            elif line.startswith("[TOOL]") and ":" in line:
                try:
                    parts = line[len("[TOOL]"):].split(":", 1)
                    tool_name = parts[0].strip()
                    result = parts[1].strip() if len(parts) > 1 else ""
                    tool_calls.append({
                        "tool": tool_name,
                        "input": {},
                        "output": {"result": result},
                        "status": "success",
                    })
                except Exception:
                    pass

        return tool_calls

    def _discover_artifacts(self, worktree_path: Path) -> list[Path]:
        """
        Discover artifacts created during execution.

        Scans the worktree for newly created or modified files
        that look like artifacts (excluding hidden files and prompt/tools files).

        Args:
            worktree_path: Path to the agent worktree.

        Returns:
            List of artifact file paths.
        """
        artifacts = []
        exclude_patterns = {".agent_prompt.md", ".agent_tools.py", ".git"}

        for file_path in worktree_path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(worktree_path)
                if rel_path.name not in exclude_patterns and not rel_path.name.startswith("."):
                    artifacts.append(file_path)

        return artifacts

    def _run_process_stream(self, context: AgentExecutionContext) -> AsyncIterator[ExecutionEvent]:
        """
        Internal method to run process and stream events.

        This method can be mocked for testing.

        Args:
            context: Execution context for this turn.

        Yields:
            ExecutionEvent objects for tokens, tool calls, and completion.
        """
        import time

        async def _stream():
            cmd = self.build_execution_command(context)
            env = self._build_env(context)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=context.worktree_path,
            )

            # Stream stdout line by line
            if proc.stdout:
                async for line in proc.stdout:
                    line_text = line.decode("utf-8", errors="replace").rstrip("\n")
                    if line_text:
                        yield ExecutionEvent(
                            event_type="token",
                            timestamp=time.time(),
                            payload={"text": line_text},
                        )

            # Wait for completion
            await proc.wait()

            # Yield completion event
            yield ExecutionEvent(
                event_type="completed",
                timestamp=time.time(),
                payload={
                    "exit_code": proc.returncode,
                    "status": "success" if proc.returncode == 0 else "error",
                },
            )

        return _stream()

    async def stream_events(self, context: AgentExecutionContext) -> AsyncIterator[ExecutionEvent]:
        """
        Stream real-time events from agent execution.

        Launches the process and yields events as output is produced.
        This implementation yields token events for each line of output
        and a final completed event.

        Args:
            context: Execution context for this turn.

        Yields:
            ExecutionEvent objects for tokens, tool calls, and completion.
        """
        stream = self._run_process_stream(context)
        # Handle case where _run_process_stream returns a coroutine (when mocked)
        if asyncio.iscoroutine(stream):
            stream = await stream
        async for event in stream:
            yield event


# For backward compatibility and explicit export

    async def record_turn_to_scratch_db(
        self,
        context: AgentExecutionContext,
        result: TurnResult,
        scratch_db_path: Path,
    ) -> None:
        """Persist turn telemetry and generated artifacts to scratch.db."""
        # Call the base class implementation
        await super().record_turn_to_scratch_db(context, result, scratch_db_path)


__all__ = ["GenericCLIAdapter"]
