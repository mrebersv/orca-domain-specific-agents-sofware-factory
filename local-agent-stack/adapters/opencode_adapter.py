"""
OpenCode Adapter

Driver for OpenCode CLI toolchains.
Translates task prompts and config manifests into OpenCode workspace configurations.
"""

from __future__ import annotations

import asyncio
import json
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


class OpenCodeAdapter(HarnessAdapter):
    """
    OpenCode adapter for OpenCode CLI toolchains.

    Translates execution context into OpenCode workspace configurations
    and parses OpenCode's output format for tool calls and results.
    """

    def __init__(
        self,
        agent_config: dict[str, Any],
        workspace_dir: Path,
        harness_binary: str | None = None,
    ) -> None:
        """
        Initialize the OpenCode adapter.

        Args:
            agent_config: Configuration containing harness_type, agent_id,
                         harness_binary (optional), and OpenCode-specific settings.
            workspace_dir: Base workspace directory for agent operations.
            harness_binary: Optional explicit binary name. Defaults to "opencode".
        """
        super().__init__(agent_config, workspace_dir)
        self.harness_binary = harness_binary or agent_config.get("harness_binary", "opencode")

    def build_execution_command(self, context: AgentExecutionContext) -> list[str]:
        """
        Build the CLI command for OpenCode agent execution.

        Creates OpenCode workspace configuration and runs:
        - opencode run --workspace <path> --prompt <text> --max-turns <int>

        Args:
            context: Execution context with task prompt, worktree, and limits.

        Returns:
            List of command arguments ready for subprocess execution.
        """
        # Ensure worktree directory exists
        context.worktree_path.mkdir(parents=True, exist_ok=True)

        # Create OpenCode workspace configuration
        workspace_config = {
            "version": "1.0",
            "workspace": str(context.worktree_path),
            "prompt": context.task_prompt,
            "max_turns": context.max_turns,
            "tools": self.config.get("allowed_tools", [
                "read", "write", "edit", "list", "glob", "grep",
                "bash", "python", "search", "replace"
            ]),
            "model": self.config.get("model_name", "default"),
            "model_endpoint": self.config.get("model_endpoint", ""),
        }

        # Write workspace config
        config_file = context.worktree_path / ".opencode_workspace.json"
        config_file.write_text(json.dumps(workspace_config, indent=2), encoding="utf-8")

        cmd = [
            self.harness_binary,
            "run",
            "--workspace",
            str(context.worktree_path),
            "--config",
            str(config_file),
        ]

        # Add max-turns if supported
        cmd.extend(["--max-turns", str(context.max_turns)])

        return cmd

    def _build_env(self, context: AgentExecutionContext) -> dict[str, str]:
        """Build sanitized environment with secrets for OpenCode execution."""
        env = {}

        # Pass through whitelisted host environment variables
        allowed_env = {"PATH", "HOME", "USER", "LANG", "TMPDIR", "TERM"}
        for key in allowed_env:
            if key in os.environ:
                env[key] = os.environ[key]

        # Inject secrets
        for key, value in context.secrets.items():
            env[key] = value

        # Agent configuration
        env["AGENT_ID"] = self.agent_id
        env["SESSION_ID"] = context.session_id
        if context.workflow_run_id:
            env["WORKFLOW_RUN_ID"] = context.workflow_run_id

        # OpenCode specific env vars
        if "model_name" in self.config:
            env["OPENCODE_MODEL"] = self.config["model_name"]
        if "model_endpoint" in self.config:
            env["OPENCODE_ENDPOINT"] = self.config["model_endpoint"]

        return env

    async def run_turn(self, context: AgentExecutionContext) -> TurnResult:
        """
        Execute a single OpenCode agent turn and return the result.

        Launches OpenCode process, captures output, parses tool calls,
        and records results.

        Args:
            context: Execution context for this turn.

        Returns:
            TurnResult with execution outcome, parsed tool calls, and artifacts.
        """
        start_time = time.monotonic()

        cmd = self.build_execution_command(context)
        env = self._build_env(context)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=context.worktree_path,
            )

            tool_calls = []
            output_lines = []

            try:
                # Stream stdout and stderr
                stdout_task = asyncio.create_task(self._read_stream(proc.stdout, output_lines, tool_calls))
                stderr_task = asyncio.create_task(self._read_stream(proc.stderr, output_lines, tool_calls))

                await asyncio.wait_for(asyncio.gather(stdout_task, stderr_task), timeout=context.timeout_seconds)
                await asyncio.wait_for(proc.wait(), timeout=1.0)  # Brief wait for process exit

            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

                execution_time_ms = int((time.monotonic() - start_time) * 1000)
                return TurnResult(
                    status="timeout",
                    exit_code=-1,
                    output_text="\n".join(output_lines),
                    tool_calls=tool_calls,
                    artifacts_created=self._discover_artifacts(context.worktree_path),
                    execution_time_ms=execution_time_ms,
                    error_message=f"Execution exceeded {context.timeout_seconds}s timeout",
                )

            execution_time_ms = int((time.monotonic() - start_time) * 1000)

            full_output = "\n".join(output_lines)

            status = "success" if proc.returncode == 0 else "error"

            return TurnResult(
                status=status,
                exit_code=proc.returncode,
                output_text=full_output,
                tool_calls=tool_calls,
                artifacts_created=self._discover_artifacts(context.worktree_path),
                execution_time_ms=execution_time_ms,
                error_message=None if status == "success" else "Non-zero exit code",
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

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        output_lines: list[str],
        tool_calls: list[dict[str, Any]]
    ) -> None:
        """Read from a stream and parse OpenCode output for tool calls."""
        if not stream:
            return

        async for line in stream:
            line_text = line.decode("utf-8", errors="replace").rstrip("\n")
            if line_text:
                output_lines.append(line_text)
                # Parse OpenCode tool call patterns
                parsed = self._parse_opencode_line(line_text)
                if parsed:
                    tool_calls.append(parsed)

    def _parse_opencode_line(self, line: str) -> dict[str, Any] | None:
        """
        Parse a single line of OpenCode output for tool calls.

        OpenCode typically outputs structured logs like:
        [TOOL] read_file: {"path": "file.py"}
        [TOOL_RESULT] read_file: {"content": "..."}
        [INFO] Agent: Some message

        Args:
            line: Single line of output from OpenCode.

        Returns:
            Tool call dict if line contains a tool call, None otherwise.
        """
        line = line.strip()

        # Pattern: [TOOL] tool_name: {json_args}
        if line.startswith("[TOOL]"):
            try:
                content = line[len("[TOOL]"):].strip()
                if ":" in content:
                    tool_name, args_str = content.split(":", 1)
                    tool_name = tool_name.strip()
                    args = json.loads(args_str.strip()) if args_str.strip() else {}
                    return {
                        "tool": tool_name,
                        "input": args,
                        "output": {},
                        "status": "pending",
                    }
            except Exception:
                pass

        # Pattern: [TOOL_RESULT] tool_name: {json_result}
        elif line.startswith("[TOOL_RESULT]"):
            try:
                content = line[len("[TOOL_RESULT]"):].strip()
                if ":" in content:
                    tool_name, result_str = content.split(":", 1)
                    tool_name = tool_name.strip()
                    result = json.loads(result_str.strip()) if result_str.strip() else {}
                    # Update last matching tool call
                    for tc in reversed(tool_calls):
                        if tc.get("tool") == tool_name and tc.get("status") == "pending":
                            tc["output"] = result
                            tc["status"] = "success"
                            break
            except Exception:
                pass

        return None

    def _discover_artifacts(self, worktree_path: Path) -> list[Path]:
        """Discover artifacts created during OpenCode execution."""
        artifacts = []
        exclude_patterns = {".opencode_workspace.json", ".git"}

        for file_path in worktree_path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(worktree_path)
                if rel_path.name not in exclude_patterns and not rel_path.name.startswith("."):
                    artifacts.append(file_path)

        return artifacts

    async def stream_events(self, context: AgentExecutionContext) -> AsyncIterator[ExecutionEvent]:
        """
        Stream real-time events from OpenCode agent execution.

        Launches OpenCode process and yields ExecutionEvent objects
        as output is produced.

        Args:
            context: Execution context for this turn.

        Yields:
            ExecutionEvent objects for tokens, tool calls, and completion.
        """
        import time

        cmd = self.build_execution_command(context)
        env = self._build_env(context)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=context.worktree_path,
        )

        # Stream stdout
        if proc.stdout:
            async for line in proc.stdout:
                line_text = line.decode("utf-8", errors="replace").rstrip("\n")
                if line_text:
                    # Check for tool calls
                    tool_call = self._parse_opencode_line(line_text)
                    if tool_call:
                        yield ExecutionEvent(
                            event_type="tool_call",
                            timestamp=time.time(),
                            payload=tool_call,
                        )
                    elif line_text.startswith("[TOOL_RESULT]"):
                        yield ExecutionEvent(
                            event_type="tool_result",
                            timestamp=time.time(),
                            payload={"raw": line_text},
                        )
                    else:
                        yield ExecutionEvent(
                            event_type="token",
                            timestamp=time.time(),
                            payload={"text": line_text},
                        )

        # Wait for completion
        await proc.wait()

        # Yield final completion event
        yield ExecutionEvent(
            event_type="completed",
            timestamp=time.time(),
            payload={
                "exit_code": proc.returncode,
                "status": "success" if proc.returncode == 0 else "error",
            },
        )



    async def record_turn_to_scratch_db(
        self,
        context: AgentExecutionContext,
        result: TurnResult,
        scratch_db_path: Path,
    ) -> None:
        """Persist turn telemetry and generated artifacts to scratch.db."""
        # Call the base class implementation
        await super().record_turn_to_scratch_db(context, result, scratch_db_path)


__all__ = ["OpenCodeAdapter"]
