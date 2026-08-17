"""
Harness Adapter Base Abstract Class & Lifecycle Events

Provides the foundational abstract base class for pluggable agent harness adapters,
event data structures, execution lifecycle hooks, and asynchronous database
persistence methods for recording execution steps to scratch.db.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentExecutionContext(BaseModel):
    """
    Context object carrying all parameters needed to execute a single agent task.

    Attributes:
        session_id: Unique identifier for this execution session.
        workflow_run_id: Optional workflow run ID if part of a workflow.
        task_prompt: The prompt/instruction for the agent to execute.
        worktree_path: Path to the isolated Git worktree for this execution.
        workspace_dir: Base workspace directory for the agent.
        secrets: Secret key-value pairs injected only into runtime memory.
        max_turns: Maximum number of execution turns allowed.
        timeout_seconds: Timeout in seconds for the execution.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    workflow_run_id: str | None = None
    task_prompt: str
    worktree_path: Path
    workspace_dir: Path
    secrets: dict[str, str] = Field(default_factory=dict)
    max_turns: int = 6
    timeout_seconds: int = 60


class ExecutionEvent(BaseModel):
    """
    Represents a real-time event emitted during agent execution.

    Attributes:
        event_type: Type of event ("token", "tool_call", "tool_result", "error", "completed").
        timestamp: Unix timestamp when the event occurred.
        payload: Event-specific data payload.
    """
    event_type: str
    timestamp: float
    payload: dict[str, Any]


class TurnResult(BaseModel):
    """
    Result of a single agent execution turn.

    Attributes:
        status: Execution status ("success", "error", "timeout", "retry").
        exit_code: Process exit code.
        output_text: Full text output from the execution.
        tool_calls: List of tool calls made during this turn.
        artifacts_created: List of file paths for artifacts generated.
        execution_time_ms: Execution time in milliseconds.
        error_message: Optional error message if status is error/timeout.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: str
    exit_code: int
    output_text: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    artifacts_created: list[Path] = Field(default_factory=list)
    execution_time_ms: int
    error_message: str | None = None


class HarnessAdapter(ABC):
    """
    Abstract base class for pluggable agent harness adapters.

    Each concrete adapter implementation translates the unified execution
    interface into the specific CLI commands, protocols, and behaviors
    required by a particular agent harness (Prime Intellect Hermes, OpenCode,
    opencode, claude-code, generic CLI, etc.).

    Attributes:
        config: Agent configuration dictionary from registry.db.
        workspace_dir: Base workspace directory for the agent.
        agent_id: Unique identifier for this agent.
    """

    def __init__(self, agent_config: dict[str, Any], workspace_dir: Path) -> None:
        """
        Initialize the harness adapter.

        Args:
            agent_config: Configuration dictionary containing agent_id, harness_type,
                         model_name, model_endpoint, max_turns, timeout_seconds, etc.
            workspace_dir: Base workspace directory for agent operations.
        """
        self.config = agent_config
        self.workspace_dir = workspace_dir
        self.agent_id = agent_config.get("agent_id", "unknown_agent")

    @abstractmethod
    def build_execution_command(self, context: AgentExecutionContext) -> list[str]:
        """
        Build the CLI command list to launch the underlying harness.

        Translates governance parameters, task prompt, worktree path, tools,
        and max_turns into the specific CLI arguments required by the harness.

        Args:
            context: Execution context containing all parameters for this run.

        Returns:
            List of command arguments ready for subprocess execution.
        """

    @abstractmethod
    async def run_turn(self, context: AgentExecutionContext) -> TurnResult:
        """
        Execute a single agent task and record step outputs to scratch.db.

        This is the primary execution entry point. Implementations should:
        1. Build the execution command via build_execution_command()
        2. Launch the harness process with proper environment/secrets
        3. Stream and collect events via stream_events()
        4. Persist results to scratch.db via record_turn_to_scratch_db()
        5. Return a TurnResult with status, output, tool calls, and artifacts.

        Args:
            context: Execution context containing all parameters for this run.

        Returns:
            TurnResult containing execution outcome, tool calls, and artifacts.
        """

    @abstractmethod
    async def stream_events(self, context: AgentExecutionContext) -> AsyncIterator[ExecutionEvent]:
        """
        Stream real-time events, tool calls, and output chunks.

        Implementations should yield ExecutionEvent objects as the agent executes,
        enabling real-time monitoring, logging, and SSE streaming to UIs.

        Args:
            context: Execution context containing all parameters for this run.

        Yields:
            ExecutionEvent objects for each token, tool call, tool result, error, or completion.
        """

    @abstractmethod
    async def record_turn_to_scratch_db(
        self,
        context: AgentExecutionContext,
        result: TurnResult,
        scratch_db_path: Path,
    ) -> None:
        """
        Persist turn telemetry and generated artifacts to scratch.db.

        Connects to the scratch.db SQLite database, inserts rows into
        execution_turns for each tool invocation and final turn status,
        and records artifact entries with SHA-256 checksums.

        Args:
            context: Execution context for this turn.
            result: TurnResult containing execution outcome and artifacts.
            scratch_db_path: Path to the scratch.db SQLite database file.
        """
        # Ensure parent directory exists
        scratch_db_path.parent.mkdir(parents=True, exist_ok=True)

        # Use a connection with WAL mode for better concurrency
        conn = sqlite3.connect(str(scratch_db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        try:
            cursor = conn.cursor()

            # Ensure tables exist (idempotent)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS execution_turns (
                    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    workflow_run_id TEXT,
                    step_number INTEGER NOT NULL,
                    tool_called TEXT NOT NULL,
                    tool_input JSON NOT NULL,
                    tool_output JSON NOT NULL,
                    status TEXT CHECK(status IN ('success', 'error', 'retry')),
                    execution_time_ms INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    workflow_run_id TEXT,
                    artifact_type TEXT NOT NULL,
                    file_path TEXT,
                    content_raw TEXT NOT NULL,
                    checksum_sha256 TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Insert execution turn records for each tool call
            step_number = 1
            for tool_call in result.tool_calls:
                tool_name = tool_call.get("tool", "unknown")
                tool_input = tool_call.get("input", {})
                tool_output = tool_call.get("output", {})
                tool_status = tool_call.get("status", "success")

                # Calculate execution time for this tool (distribute evenly if not specified)
                tool_time_ms = result.execution_time_ms // max(len(result.tool_calls), 1)

                cursor.execute("""
                    INSERT INTO execution_turns (
                        session_id, workflow_run_id, step_number,
                        tool_called, tool_input, tool_output,
                        status, execution_time_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    context.session_id,
                    context.workflow_run_id,
                    step_number,
                    tool_name,
                    json.dumps(tool_input),
                    json.dumps(tool_output),
                    tool_status,
                    tool_time_ms,
                ))
                step_number += 1

            # Insert final turn status record if no tool calls were made
            if not result.tool_calls:
                cursor.execute("""
                    INSERT INTO execution_turns (
                        session_id, workflow_run_id, step_number,
                        tool_called, tool_input, tool_output,
                        status, execution_time_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    context.session_id,
                    context.workflow_run_id,
                    1,
                    "agent_execution",
                    json.dumps({"prompt": context.task_prompt}),
                    json.dumps({"output": result.output_text}),
                    result.status,
                    result.execution_time_ms,
                ))

            # Process and record artifacts
            for artifact_path in result.artifacts_created:
                if artifact_path.exists() and artifact_path.is_file():
                    # Read content and calculate SHA-256
                    content = artifact_path.read_text(encoding="utf-8", errors="replace")
                    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()

                    # Determine artifact type from extension/path
                    artifact_type = self._infer_artifact_type(artifact_path)

                    # Generate unique artifact ID
                    artifact_id = f"{context.session_id}_{checksum[:16]}"

                    cursor.execute("""
                        INSERT OR REPLACE INTO artifacts (
                            artifact_id, session_id, workflow_run_id,
                            artifact_type, file_path, content_raw, checksum_sha256
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        artifact_id,
                        context.session_id,
                        context.workflow_run_id,
                        artifact_type,
                        str(artifact_path),
                        content,
                        checksum,
                    ))

            conn.commit()

        finally:
            conn.close()

    def _infer_artifact_type(self, path: Path) -> str:
        """
        Infer artifact type from file path and extension.

        Args:
            path: Path to the artifact file.

        Returns:
            Artifact type string.
        """
        suffix = path.suffix.lower()
        name = path.name.lower()

        if suffix in {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cpp", ".c", ".h"}:
            return "source_code"
        elif suffix in {".md", ".txt", ".rst"}:
            if "plan" in name:
                return "plan"
            return "documentation"
        elif suffix in {".json", ".yaml", ".yml", ".toml"}:
            return "config"
        elif suffix in {".test.py", ".spec.py", ".spec.ts", ".test.ts"} or "test" in name:
            return "test_suite"
        elif suffix in {".log", ".out", ".err"}:
            return "log"
        elif suffix in {".diff", ".patch"}:
            return "diff"
        elif suffix in {".html", ".xml", ".sarif"} and "lint" in name:
            return "lint_report"
        else:
            return "artifact"


# Re-export for convenient imports
__all__ = [
    "AgentExecutionContext",
    "ExecutionEvent",
    "HarnessAdapter",
    "TurnResult",
]
