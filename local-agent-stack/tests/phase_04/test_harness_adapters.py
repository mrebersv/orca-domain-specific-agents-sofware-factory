"""Tests for Phase 4 - Harness Adapters & Execution Lifecycle."""

from __future__ import annotations

import asyncio
from abc import ABC
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError


class TestHarnessAdapterBase:
    """Tests for HarnessAdapter abstract base class and core data structures."""

    def test_harness_adapter_is_abstract_base_class(self):
        """HarnessAdapter must be an abstract base class that cannot be instantiated directly."""
        from adapters.base import HarnessAdapter

        assert issubclass(HarnessAdapter, ABC)

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            HarnessAdapter(agent_config={"agent_id": "test"}, workspace_dir=Path("."))

    def test_agent_execution_context_model(self):
        """AgentExecutionContext must validate required fields and types."""
        from adapters.base import AgentExecutionContext

        ctx = AgentExecutionContext(
            session_id="sess_123",
            workflow_run_id="run_abc",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
            secrets={"API_KEY": "secret"},
            max_turns=6,
            timeout_seconds=60,
        )
        assert ctx.session_id == "sess_123"
        assert ctx.max_turns == 6
        assert ctx.timeout_seconds == 60
        assert isinstance(ctx.worktree_path, Path)
        assert isinstance(ctx.workspace_dir, Path)

    def test_agent_execution_context_defaults(self):
        """AgentExecutionContext should apply defaults for optional fields."""
        from adapters.base import AgentExecutionContext

        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
        )
        assert ctx.workflow_run_id is None
        assert ctx.secrets == {}
        assert ctx.max_turns == 6
        assert ctx.timeout_seconds == 60

    def test_agent_execution_context_validation(self):
        """AgentExecutionContext must reject invalid types."""
        from adapters.base import AgentExecutionContext

        with pytest.raises(ValidationError):
            AgentExecutionContext(
                session_id=123,  # should be str
                task_prompt="Test",
                worktree_path=Path("/tmp"),
                workspace_dir=Path("/tmp"),
            )

    def test_execution_event_model(self):
        """ExecutionEvent must capture event type, timestamp, and payload."""
        from adapters.base import ExecutionEvent

        event = ExecutionEvent(
            event_type="tool_call",
            timestamp=1234567890.0,
            payload={"tool": "search", "args": {"query": "test"}},
        )
        assert event.event_type == "tool_call"
        assert event.timestamp == 1234567890.0
        assert event.payload["tool"] == "search"

    def test_execution_event_valid_types(self):
        """ExecutionEvent event_type must be one of the allowed values."""
        from adapters.base import ExecutionEvent

        valid_types = ["token", "tool_call", "tool_result", "error", "completed"]
        for etype in valid_types:
            event = ExecutionEvent(event_type=etype, timestamp=0.0, payload={})
            assert event.event_type == etype

    def test_turn_result_model(self):
        """TurnResult must capture execution outcome and metadata."""
        from adapters.base import TurnResult

        result = TurnResult(
            status="success",
            exit_code=0,
            output_text="Done",
            tool_calls=[{"tool": "search", "result": "ok"}],
            artifacts_created=[Path("/tmp/out.txt")],
            execution_time_ms=1500,
            error_message=None,
        )
        assert result.status == "success"
        assert result.exit_code == 0
        assert result.execution_time_ms == 1500
        assert len(result.tool_calls) == 1
        assert len(result.artifacts_created) == 1

    def test_turn_result_status_values(self):
        """TurnResult status must be one of allowed values."""
        from adapters.base import TurnResult

        valid_statuses = ["success", "error", "timeout", "retry"]
        for status in valid_statuses:
            result = TurnResult(
                status=status,
                exit_code=0,
                output_text="",
                tool_calls=[],
                artifacts_created=[],
                execution_time_ms=0,
            )
            assert result.status == status

    def test_abstract_methods_defined(self):
        """HarnessAdapter must define all required abstract methods."""
        from adapters.base import HarnessAdapter

        abstract_methods = {
            "build_execution_command",
            "run_turn",
            "stream_events",
            "record_turn_to_scratch_db",
        }
        for method in abstract_methods:
            assert hasattr(HarnessAdapter, method)
            attr = getattr(HarnessAdapter, method)
            assert getattr(attr, "__isabstractmethod__", False), f"{method} must be abstract"


class TestGenericCLIAdapter:
    """Tests for GenericCLIAdapter command building and execution."""

    def test_build_execution_command_basic(self):
        """GenericCLIAdapter must build command with prompt, tools, max-turns, workdir."""
        from adapters.generic_cli_adapter import GenericCLIAdapter

        adapter = GenericCLIAdapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "test"},
            workspace_dir=Path("/tmp/workspace"),
        )
        from adapters.base import AgentExecutionContext

        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test prompt",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
            max_turns=5,
            timeout_seconds=120,
        )
        cmd = adapter.build_execution_command(ctx)

        assert isinstance(cmd, list)
        assert "--prompt-file" in cmd
        assert "--tools" in cmd
        assert "--max-turns" in cmd
        assert "5" in cmd
        assert "--workdir" in cmd
        assert str(ctx.worktree_path) in cmd

    def test_build_execution_command_includes_secrets_env(self):
        """GenericCLIAdapter must inject secret environment variables."""
        from adapters.generic_cli_adapter import GenericCLIAdapter
        from adapters.base import AgentExecutionContext

        adapter = GenericCLIAdapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "test"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
            secrets={"API_KEY": "secret123", "TOKEN": "token456"},
        )
        cmd = adapter.build_execution_command(ctx)

        # Secrets should be passed via environment, not CLI args
        env = adapter._build_env(ctx)
        assert env["API_KEY"] == "secret123"
        assert env["TOKEN"] == "token456"

    def test_build_execution_command_sanitizes_env(self):
        """GenericCLIAdapter must not leak host environment variables."""
        from adapters.generic_cli_adapter import GenericCLIAdapter
        from adapters.base import AgentExecutionContext

        adapter = GenericCLIAdapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "test"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
        )
        env = adapter._build_env(ctx)

        # Should only have whitelisted vars + secrets
        allowed = {"PATH", "HOME", "USER", "LANG", "TMPDIR"}
        for key in env:
            assert key in allowed or key in {"API_KEY", "TOKEN"}  # secrets


class TestPiAdapter:
    """Tests for PiAdapter command building and event streaming."""

    def test_build_execution_command_pi_format(self):
        """PiAdapter must format CLI for Pi binary with --prompt, --system-prompt-file, --context-db."""
        from adapters.pi_adapter import PiAdapter
        from adapters.base import AgentExecutionContext

        adapter = PiAdapter(
            agent_config={"harness_type": "pi", "agent_id": "pi-test", "harness_binary": "pi"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
        )
        cmd = adapter.build_execution_command(ctx)

        assert cmd[0] == "pi"
        assert "--prompt" in cmd
        assert "--system-prompt-file" in cmd
        assert "--context-db" in cmd

    def test_parse_pi_json_events(self):
        """PiAdapter must parse Pi JSON event streams into ExecutionEvent objects."""
        from adapters.pi_adapter import PiAdapter
        from adapters.base import ExecutionEvent

        adapter = PiAdapter(
            agent_config={"harness_type": "pi", "agent_id": "pi-test"},
            workspace_dir=Path("/tmp/workspace"),
        )

        # Simulate Pi JSON output lines
        json_lines = [
            '{"type": "token", "data": "Hello"}',
            '{"type": "tool_call", "data": {"name": "search", "args": {"q": "test"}}}',
            '{"type": "tool_result", "data": {"result": "found"}}',
            '{"type": "completed", "data": {}}',
        ]

        events = list(adapter._parse_events(json_lines))

        assert len(events) == 4
        assert all(isinstance(e, ExecutionEvent) for e in events)
        assert events[0].event_type == "token"
        assert events[1].event_type == "tool_call"
        assert events[2].event_type == "tool_result"
        assert events[3].event_type == "completed"


class TestHermesAdapter:
    """Tests for HermesAdapter JSON-RPC handling."""

    def test_build_execution_command_hermes_format(self):
        """HermesAdapter must format CLI for Hermes with JSON-RPC protocol."""
        from adapters.hermes_adapter import HermesAdapter
        from adapters.base import AgentExecutionContext

        adapter = HermesAdapter(
            agent_config={"harness_type": "hermes", "agent_id": "hermes-test", "harness_binary": "hermes"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
        )
        cmd = adapter.build_execution_command(ctx)

        assert cmd[0] == "hermes"
        assert "--task" in cmd
        assert "--max-turns" in cmd

    def test_parse_hermes_turn_deltas(self):
        """HermesAdapter must parse structured function-calling format."""
        from adapters.hermes_adapter import HermesAdapter
        from adapters.base import ExecutionEvent

        adapter = HermesAdapter(
            agent_config={"harness_type": "hermes", "agent_id": "hermes-test"},
            workspace_dir=Path("/tmp/workspace"),
        )

        # Simulate Hermes JSON-RPC responses
        rpc_messages = [
            '{"jsonrpc": "2.0", "method": "tool_call", "params": {"name": "read", "args": {"path": "file.py"}}}',
            '{"jsonrpc": "2.0", "result": {"content": "file content"}}',
        ]

        events = list(adapter._parse_events(rpc_messages))

        assert len(events) >= 2
        assert any(e.event_type == "tool_call" for e in events)
        assert any(e.event_type == "tool_result" for e in events)


class TestOpenCodeAdapter:
    """Tests for OpenCodeAdapter workspace configuration."""

    def test_build_execution_command_opencode_format(self):
        """OpenCodeAdapter must translate task into OpenCode workspace config."""
        from adapters.opencode_adapter import OpenCodeAdapter
        from adapters.base import AgentExecutionContext

        adapter = OpenCodeAdapter(
            agent_config={"harness_type": "opencode", "agent_id": "oc-test", "harness_binary": "opencode"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
        )
        cmd = adapter.build_execution_command(ctx)

        assert cmd[0] == "opencode"
        assert "run" in cmd


class TestAdapterFactory:
    """Tests for adapter factory function."""

    def test_get_adapter_generic_cli(self):
        """Factory must return GenericCLIAdapter for generic_cli type."""
        from adapters import get_adapter

        adapter = get_adapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "test"},
            workspace_dir=Path("/tmp"),
        )
        from adapters.generic_cli_adapter import GenericCLIAdapter

        assert isinstance(adapter, GenericCLIAdapter)

    def test_get_adapter_pi(self):
        """Factory must return PiAdapter for pi type."""
        from adapters import get_adapter

        adapter = get_adapter(
            agent_config={"harness_type": "pi", "agent_id": "test"},
            workspace_dir=Path("/tmp"),
        )
        from adapters.pi_adapter import PiAdapter

        assert isinstance(adapter, PiAdapter)

    def test_get_adapter_hermes(self):
        """Factory must return HermesAdapter for hermes type."""
        from adapters import get_adapter

        adapter = get_adapter(
            agent_config={"harness_type": "hermes", "agent_id": "test"},
            workspace_dir=Path("/tmp"),
        )
        from adapters.hermes_adapter import HermesAdapter

        assert isinstance(adapter, HermesAdapter)

    def test_get_adapter_opencode(self):
        """Factory must return OpenCodeAdapter for opencode type."""
        from adapters import get_adapter

        adapter = get_adapter(
            agent_config={"harness_type": "opencode", "agent_id": "test"},
            workspace_dir=Path("/tmp"),
        )
        from adapters.opencode_adapter import OpenCodeAdapter

        assert isinstance(adapter, OpenCodeAdapter)

    def test_get_adapter_unknown_type_raises(self):
        """Factory must raise ValueError for unknown harness_type."""
        from adapters import get_adapter

        with pytest.raises(ValueError, match="Unknown harness_type"):
            get_adapter(
                agent_config={"harness_type": "unknown", "agent_id": "test"},
                workspace_dir=Path("/tmp"),
            )


class TestTurnExecutionAndScratchRecording:
    """Tests for run_turn execution and scratch.db persistence."""

    @pytest.mark.asyncio
    async def test_run_turn_returns_turn_result(self, ephemeral_scratch_db):
        """run_turn must return TurnResult with proper fields."""
        from adapters.generic_cli_adapter import GenericCLIAdapter
        from adapters.base import AgentExecutionContext, TurnResult

        adapter = GenericCLIAdapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "test"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
        )

        # Mock the subprocess execution
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"Success output", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc

            result = await adapter.run_turn(ctx)

            assert isinstance(result, TurnResult)
            assert result.status == "success"
            assert result.exit_code == 0
            assert "Success output" in result.output_text

    @pytest.mark.asyncio
    async def test_run_turn_timeout_returns_timeout_status(self, ephemeral_scratch_db):
        """run_turn must return timeout status when execution exceeds timeout."""
        from adapters.generic_cli_adapter import GenericCLIAdapter
        from adapters.base import AgentExecutionContext, TurnResult

        adapter = GenericCLIAdapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "test"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
            timeout_seconds=1,
        )

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_exec.return_value = mock_proc

            result = await adapter.run_turn(ctx)

            assert isinstance(result, TurnResult)
            assert result.status == "timeout"
            assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_record_turn_to_scratch_db_persists_turn(
        self, ephemeral_scratch_db, temp_dir
    ):
        """record_turn_to_scratch_db must persist turn metrics to scratch.db."""
        from adapters.generic_cli_adapter import GenericCLIAdapter
        from adapters.base import AgentExecutionContext, TurnResult
        from agent_forge.db.scratch import list_execution_turns, list_artifacts

        adapter = GenericCLIAdapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "test"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            workflow_run_id="run_abc",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
        )
        result = TurnResult(
            status="success",
            exit_code=0,
            output_text="Done",
            tool_calls=[{"tool": "search", "input": {"q": "test"}, "output": "results"}],
            artifacts_created=[temp_dir / "output.txt"],
            execution_time_ms=1500,
        )

        scratch_db_path = temp_dir / "scratch.db"
        await adapter.record_turn_to_scratch_db(ctx, result, scratch_db_path)

        async with ephemeral_scratch_db as db:
            turns = await list_execution_turns(db, "sess_123")
            assert len(turns) == 1
            assert turns[0]["tool_called"] == "search"
            assert turns[0]["status"] == "success"
            assert turns[0]["execution_time_ms"] == 1500
            assert turns[0]["workflow_run_id"] == "run_abc"

    @pytest.mark.asyncio
    async def test_record_turn_to_scratch_db_persists_artifacts(
        self, ephemeral_scratch_db, temp_dir
    ):
        """record_turn_to_scratch_db must persist artifacts with SHA-256 checksums."""
        from adapters.generic_cli_adapter import GenericCLIAdapter
        from adapters.base import AgentExecutionContext, TurnResult
        from agent_forge.db.scratch import list_artifacts

        adapter = GenericCLIAdapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "test"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
        )
        artifact_path = temp_dir / "generated.py"
        artifact_path.write_text("print('hello')")

        result = TurnResult(
            status="success",
            exit_code=0,
            output_text="Done",
            tool_calls=[],
            artifacts_created=[artifact_path],
            execution_time_ms=100,
        )

        scratch_db_path = temp_dir / "scratch.db"
        await adapter.record_turn_to_scratch_db(ctx, result, scratch_db_path)

        async with ephemeral_scratch_db as db:
            artifacts = await list_artifacts(db, "sess_123")
            assert len(artifacts) == 1
            assert artifacts[0]["artifact_type"] == "source_code"
            assert artifacts[0]["checksum_sha256"] is not None
            assert len(artifacts[0]["checksum_sha256"]) == 64


class TestStreamEvents:
    """Tests for stream_events async iterator."""

    @pytest.mark.asyncio
    async def test_stream_events_yields_execution_events(self):
        """stream_events must yield ExecutionEvent objects asynchronously."""
        from adapters.generic_cli_adapter import GenericCLIAdapter
        from adapters.base import AgentExecutionContext, ExecutionEvent

        adapter = GenericCLIAdapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "test"},
            workspace_dir=Path("/tmp/workspace"),
        )
        ctx = AgentExecutionContext(
            session_id="sess_123",
            task_prompt="Test task",
            worktree_path=Path("/tmp/worktree"),
            workspace_dir=Path("/tmp/workspace"),
        )

        with patch.object(adapter, "_run_process_stream", new_callable=AsyncMock) as mock_stream:
            # Mock async generator
            async def mock_gen():
                yield ExecutionEvent(event_type="token", timestamp=0.0, payload={"text": "Hello"})
                yield ExecutionEvent(event_type="tool_call", timestamp=0.0, payload={"tool": "search"})
                yield ExecutionEvent(event_type="completed", timestamp=0.0, payload={})

            mock_stream.return_value = mock_gen()

            events = []
            async for event in adapter.stream_events(ctx):
                events.append(event)

            assert len(events) == 3
            assert all(isinstance(e, ExecutionEvent) for e in events)
            assert events[0].event_type == "token"
            assert events[2].event_type == "completed"


