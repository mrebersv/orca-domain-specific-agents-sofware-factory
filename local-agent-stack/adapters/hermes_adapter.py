"""
Hermes Agent Adapter

Driver for Nous Research Hermes / JSON-RPC agent loops.
Supports structured function-calling formats and parses Hermes turn deltas.
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


class HermesAdapter(HarnessAdapter):
    """
    Hermes agent adapter for JSON-RPC based agent loops.

    Translates execution context into Hermes CLI arguments and parses
    JSON-RPC messages for tool calls, results, and completion events.
    """

    def __init__(
        self,
        agent_config: dict[str, Any],
        workspace_dir: Path,
        harness_binary: str | None = None,
    ) -> None:
        """
        Initialize the Hermes adapter.

        Args:
            agent_config: Configuration containing harness_type, agent_id,
                         harness_binary (optional), and Hermes-specific settings.
            workspace_dir: Base workspace directory for agent operations.
            harness_binary: Optional explicit binary name. Defaults to "hermes".
        """
        super().__init__(agent_config, workspace_dir)
        self.harness_binary = harness_binary or agent_config.get("harness_binary", "hermes")

    def build_execution_command(self, context: AgentExecutionContext) -> list[str]:
        """
        Build the CLI command for Hermes agent execution.

        Formats parameters for Hermes binary with JSON-RPC protocol:
        - --task <text>: The task prompt
        - --max-turns <int>: Maximum execution turns
        - --workspace <path>: Working directory
        - --config <path>: Optional config file path

        Args:
            context: Execution context with task prompt, worktree, and limits.

        Returns:
            List of command arguments ready for subprocess execution.
        """
        # Ensure worktree directory exists
        context.worktree_path.mkdir(parents=True, exist_ok=True)

        # Create task file for complex prompts
        task_file = context.worktree_path / ".hermes_task.json"
        task_data = {
            "prompt": context.task_prompt,
            "max_turns": context.max_turns,
            "workspace": str(context.worktree_path),
            "tools": self.config.get("allowed_tools", [
                "read_file", "write_file", "list_dir", "glob", "grep",
                "bash", "python", "search_symbols", "search_docs"
            ]),
        }
        task_file.write_text(json.dumps(task_data, indent=2), encoding="utf-8")

        cmd = [
            self.harness_binary,
            "--task",
            str(task_file),
            "--max-turns",
            str(context.max_turns),
            "--workspace",
            str(context.worktree_path),
        ]

        # Add config file if specified
        if "config_file" in self.config:
            cmd.extend(["--config", self.config["config_file"]])

        # Add model configuration
        if "model_name" in self.config:
            cmd.extend(["--model", self.config["model_name"]])
        if "model_endpoint" in self.config:
            cmd.extend(["--endpoint", self.config["model_endpoint"]])

        return cmd

    def _build_env(self, context: AgentExecutionContext) -> dict[str, str]:
        """Build sanitized environment with secrets for Hermes execution."""
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
        Execute a single Hermes agent turn and return the result.

        Launches Hermes process, captures JSON-RPC messages, parses events,
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
            pending_tool_calls = {}  # Track tool calls by ID for matching results

            try:
                # Stream and parse JSON-RPC messages from stdout
                if proc.stdout:
                    async for line in proc.stdout:
                        line_text = line.decode("utf-8", errors="replace").strip()
                        if line_text:
                            output_lines.append(line_text)
                            # Parse Hermes JSON-RPC message
                            events = self._parse_hermes_message(line_text, pending_tool_calls)
                            for event in events:
                                if event.event_type == "tool_call":
                                    # Store pending tool call by ID
                                    call_id = event.payload.get("id")
                                    if call_id:
                                        pending_tool_calls[call_id] = event.payload
                                    tool_calls.append(event.payload)
                                elif event.event_type == "tool_result":
                                    # Match with pending tool call
                                    call_id = event.payload.get("id")
                                    if call_id and call_id in pending_tool_calls:
                                        pending_tool_calls[call_id]["output"] = event.payload.get("result")
                                        pending_tool_calls[call_id]["status"] = "success"

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

    def _parse_hermes_message(
        self,
        json_line: str,
        pending_tool_calls: dict[str, dict[str, Any]]
    ) -> list[ExecutionEvent]:
        """
        Parse a single Hermes JSON-RPC message into ExecutionEvent objects.

        Hermes uses JSON-RPC 2.0 format:
        - Request: {"jsonrpc": "2.0", "method": "tool_call", "params": {...}, "id": "123"}
        - Response: {"jsonrpc": "2.0", "result": {...}, "id": "123"}
        - Notification: {"jsonrpc": "2.0", "method": "token", "params": {"text": "..."}}

        Args:
            json_line: Single line of JSON-RPC from Hermes.
            pending_tool_calls: Dict tracking pending tool calls by ID.

        Returns:
            List of ExecutionEvent objects (may be multiple for batch responses).
        """
        import time

        events = []

        try:
            data = json.loads(json_line)

            # Validate JSON-RPC format
            if data.get("jsonrpc") != "2.0":
                return [ExecutionEvent(
                    event_type="token",
                    timestamp=time.time(),
                    payload={"text": json_line},
                )]

            # Handle request (method call)
            if "method" in data:
                method = data.get("method")
                params = data.get("params", {})
                msg_id = data.get("id")

                if method == "tool_call":
                    tool_name = params.get("name", "unknown")
                    tool_args = params.get("arguments", {})
                    events.append(ExecutionEvent(
                        event_type="tool_call",
                        timestamp=time.time(),
                        payload={
                            "id": msg_id,
                            "tool": tool_name,
                            "input": tool_args,
                            "status": "pending",
                        },
                    ))
                elif method == "token":
                    events.append(ExecutionEvent(
                        event_type="token",
                        timestamp=time.time(),
                        payload={"text": params.get("text", "")},
                    ))
                elif method == "completed":
                    events.append(ExecutionEvent(
                        event_type="completed",
                        timestamp=time.time(),
                        payload=params,
                    ))
                elif method == "error":
                    events.append(ExecutionEvent(
                        event_type="error",
                        timestamp=time.time(),
                        payload={"message": params.get("message", "Unknown error")},
                    ))
                else:
                    # Unknown method, treat as generic event
                    events.append(ExecutionEvent(
                        event_type=method,
                        timestamp=time.time(),
                        payload=params,
                    ))

            # Handle response (result or error)
            elif "result" in data or "error" in data:
                msg_id = data.get("id")

                if "result" in data:
                    result = data["result"]
                    events.append(ExecutionEvent(
                        event_type="tool_result",
                        timestamp=time.time(),
                        payload={
                            "id": msg_id,
                            "result": result,
                            "status": "success",
                        },
                    ))
                elif "error" in data:
                    error = data["error"]
                    events.append(ExecutionEvent(
                        event_type="error",
                        timestamp=time.time(),
                        payload={
                            "id": msg_id,
                            "code": error.get("code"),
                            "message": error.get("message", "Unknown error"),
                        },
                    ))

        except json.JSONDecodeError:
            # Not a JSON line, treat as token
            events.append(ExecutionEvent(
                event_type="token",
                timestamp=time.time(),
                payload={"text": json_line},
            ))
        except Exception:
            pass

        return events

    def _parse_events(self, rpc_messages: list[str]) -> list[ExecutionEvent]:
        """
        Parse multiple Hermes JSON-RPC messages.

        Used for testing and batch parsing.

        Args:
            rpc_messages: List of JSON-RPC lines from Hermes output.

        Returns:
            List of ExecutionEvent objects.
        """
        events = []
        pending = {}
        for msg in rpc_messages:
            events.extend(self._parse_hermes_message(msg, pending))
        return events

    def _discover_artifacts(self, worktree_path: Path) -> list[Path]:
        """Discover artifacts created during Hermes execution."""
        artifacts = []
        exclude_patterns = {".hermes_task.json", ".git"}

        for file_path in worktree_path.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(worktree_path)
                if rel_path.name not in exclude_patterns and not rel_path.name.startswith("."):
                    artifacts.append(file_path)

        return artifacts

    async def stream_events(self, context: AgentExecutionContext) -> AsyncIterator[ExecutionEvent]:
        """
        Stream real-time events from Hermes agent execution.

        Launches Hermes process and yields parsed ExecutionEvent objects
        as JSON-RPC messages are emitted.

        Args:
            context: Execution context for this turn.

        Yields:
            ExecutionEvent objects parsed from Hermes JSON-RPC stream.
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

        pending_tool_calls = {}

        # Stream and parse JSON-RPC messages from stdout
        if proc.stdout:
            async for line in proc.stdout:
                line_text = line.decode("utf-8", errors="replace").strip()
                if line_text:
                    events = self._parse_hermes_message(line_text, pending_tool_calls)
                    for event in events:
                        yield event

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


__all__ = ["HermesAdapter"]
