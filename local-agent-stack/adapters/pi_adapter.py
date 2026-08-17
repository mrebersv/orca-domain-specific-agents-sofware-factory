"""
Pi Coding Agent Adapter

Driver for Pi agent workflows. Formats CLI parameters for Pi binary
(--prompt, --system-prompt-file, --context-db) and parses Pi JSON
event streams over stdout to emit ExecutionEvent instances.
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


class PiAdapter(HarnessAdapter):
    """
    Pi Coding Agent adapter.

    Translates execution context into Pi CLI arguments and parses
    Pi's JSON event stream output format.
    """

    def __init__(
        self,
        agent_config: dict[str, Any],
        workspace_dir: Path,
        harness_binary: str | None = None,
    ) -> None:
        """
        Initialize the Pi adapter.

        Args:
            agent_config: Configuration containing harness_type, agent_id,
                         harness_binary (optional), and Pi-specific settings.
            workspace_dir: Base workspace directory for agent operations.
            harness_binary: Optional explicit binary name. Defaults to "pi".
        """
        super().__init__(agent_config, workspace_dir)
        self.harness_binary = harness_binary or agent_config.get("harness_binary", "pi")

    def build_execution_command(self, context: AgentExecutionContext) -> list[str]:
        """
        Build the CLI command for Pi agent execution.

        Formats parameters for Pi binary:
        - --prompt <text>: The task prompt
        - --system-prompt-file <path>: Path to system prompt file
        - --context-db <path>: Path to context database
        - --max-turns <int>: Maximum execution turns

        Args:
            context: Execution context with task prompt, worktree, and limits.

        Returns:
            List of command arguments ready for subprocess execution.
        """
        # Ensure worktree directory exists
        context.worktree_path.mkdir(parents=True, exist_ok=True)

        # Create system prompt file
        system_prompt_file = context.worktree_path / ".system_prompt.md"
        system_prompt = self.config.get("system_prompt", "You are a helpful coding assistant.")
        system_prompt_file.write_text(system_prompt, encoding="utf-8")

        # Create prompt file
        prompt_file = context.worktree_path / ".agent_prompt.md"
        prompt_file.write_text(context.task_prompt, encoding="utf-8")

        # Context database path (can be in workspace)
        context_db = self.config.get("context_db", str(context.workspace_dir / "pi_context.db"))

        cmd = [
            self.harness_binary,
            "--prompt",
            str(prompt_file),
            "--system-prompt-file",
            str(system_prompt_file),
            "--context-db",
            context_db,
            "--max-turns",
            str(context.max_turns),
        ]

        # Add working directory
        cmd.extend(["--workdir", str(context.worktree_path)])

        # Add model configuration if available
        if "model_name" in self.config:
            cmd.extend(["--model", self.config["model_name"]])

        return cmd

    def _build_env(self, context: AgentExecutionContext) -> dict[str, str]:
        """Build sanitized environment with secrets for Pi execution."""
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

        return env

    async def run_turn(self, context: AgentExecutionContext) -> TurnResult:
        """
        Execute a single Pi agent turn and return the result.

        Launches Pi process, captures JSON event stream, parses events,
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
                # Stream and parse JSON events from stdout
                if proc.stdout:
                    async for line in proc.stdout:
                        line_text = line.decode("utf-8", errors="replace").strip()
                        if line_text:
                            output_lines.append(line_text)
                            # Parse Pi JSON event
                            event = self._parse_pi_event(line_text)
                            if event:
                                if event.event_type == "tool_call":
                                    tool_calls.append(event.payload)
                                elif event.event_type == "tool_result":
                                    # Update last tool call with result
                                    if tool_calls and "output" not in tool_calls[-1]:
                                        tool_calls[-1]["output"] = event.payload

                await asyncio.wait_for(proc.wait(), timeout=context.timeout_seconds)

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

            # Get stderr
            stderr_text = ""
            if proc.stderr:
                stderr_bytes = await proc.stderr.read()
                stderr_text = stderr_bytes.decode("utf-8", errors="replace")

            full_output = "\n".join(output_lines)
            if stderr_text:
                full_output += f"\n--- STDERR ---\n{stderr_text}"

            status = "success" if proc.returncode == 0 else "error"

            return TurnResult(
                status=status,
                exit_code=proc.returncode,
                output_text=full_output,
                tool_calls=tool_calls,
                artifacts_created=self._discover_artifacts(context.worktree_path),
                execution_time_ms=execution_time_ms,
                error_message=stderr_text if status == "error" else None,
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

    def _parse_pi_event(self, json_line: str) -> ExecutionEvent | None:
        """
        Parse a single Pi JSON event line into an ExecutionEvent.

        Pi emits JSON lines with structure:
        {"type": "token|tool_call|tool_result|completed|error", "data": {...}}

        Args:
            json_line: Single line of JSON output from Pi.

        Returns:
            ExecutionEvent if parsing succeeds, None otherwise.
        """
        import time

        try:
            data = json.loads(json_line)
            event_type = data.get("type", "unknown")
            raw_payload = data.get("data", {})

            # Map Pi event types to our standard event types
            type_mapping = {
                "token": "token",
                "tool_call": "tool_call",
                "tool_result": "tool_result",
                "completed": "completed",
                "error": "error",
            }

            standard_type = type_mapping.get(event_type, event_type)

            # Ensure payload is a dict (ExecutionEvent expects dict[str, Any])
            # For token events, data might be a string
            if isinstance(raw_payload, dict):
                payload = raw_payload
            else:
                payload = {"text": str(raw_payload)}

            return ExecutionEvent(
                event_type=standard_type,
                timestamp=time.time(),
                payload=payload,
            )
        except json.JSONDecodeError:
            # Not a JSON line, treat as token
            return ExecutionEvent(
                event_type="token",
                timestamp=time.time(),
                payload={"text": json_line},
            )
        except Exception:
            return None

    def _parse_events(self, json_lines: list[str]) -> list[ExecutionEvent]:
        """
        Parse multiple Pi JSON event lines.

        Used for testing and batch parsing.

        Args:
            json_lines: List of JSON lines from Pi output.

        Returns:
            List of ExecutionEvent objects.
        """
        events = []
        for line in json_lines:
            event = self._parse_pi_event(line)
            if event:
                events.append(event)
        return events

    def _discover_artifacts(self, worktree_path: Path) -> list[Path]:
        """Discover artifacts created during Pi execution."""
        artifacts = []
        exclude_patterns = {".agent_prompt.md", ".system_prompt.md", ".git"}

        for file_path in worktree_path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(worktree_path)
                if rel_path.name not in exclude_patterns and not rel_path.name.startswith("."):
                    artifacts.append(file_path)

        return artifacts

    async def stream_events(self, context: AgentExecutionContext) -> AsyncIterator[ExecutionEvent]:
        """
        Stream real-time events from Pi agent execution.

        Launches Pi process and yields parsed ExecutionEvent objects
        as JSON lines are emitted.

        Args:
            context: Execution context for this turn.

        Yields:
            ExecutionEvent objects parsed from Pi JSON stream.
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

        # Stream and parse JSON events from stdout
        if proc.stdout:
            async for line in proc.stdout:
                line_text = line.decode("utf-8", errors="replace").strip()
                if line_text:
                    event = self._parse_pi_event(line_text)
                    if event:
                        yield event
                    else:
                        # Fallback: yield as token
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


__all__ = ["PiAdapter"]
