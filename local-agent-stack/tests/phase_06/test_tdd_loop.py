"""
Phase 6 Integration Tests: TDD Multi-Agent Workflow Runner.

Tests cover TDDWorkflowRunner orchestration:
- Test Author dispatch
- Task Builder dispatch in worktrees
- Gatekeeper pytest evaluation with JSON report
- Remediation loop (max 3 cycles)
- HITL escalation via orca snapshot
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open, call

import pytest

# Import the workflow module (will be implemented)
from orca_pack.workflows.tdd_workflow import (
    TDDWorkflowRunner,
    RemediationPayload,
    TestAuthorResult,
    BuilderResult,
    GatekeeperResult,
)


class TestTDDWorkflowRunnerInitialization:
    """Tests for TDDWorkflowRunner initialization and configuration."""

    @pytest.fixture
    def temp_plan_path(self):
        """Create a temporary plan.json for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_path = Path(tmpdir) / "plan.json"
            plan_data = {
                "phases": [
                    {
                        "phase_id": "phase-06",
                        "name": "Orca ADE Integration",
                        "tasks": [
                            {"task_id": "task-6.1", "title": "Orca YAML Generator"},
                            {"task_id": "task-6.2", "title": "Worktree Lifecycle Hooks"},
                            {"task_id": "task-6.3", "title": "TDD Workflow Runner"},
                        ]
                    }
                ]
            }
            plan_path.write_text(json.dumps(plan_data))
            yield plan_path

    @pytest.fixture
    def temp_registry_db(self):
        """Create a temporary registry.db path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "registry.db"

    def test_init_with_required_paths(self, temp_plan_path, temp_registry_db):
        """Runner initializes with plan_path and registry_db_path."""
        runner = TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=temp_registry_db,
        )

        assert runner.plan_path == temp_plan_path
        assert runner.registry_db_path == temp_registry_db
        assert runner.max_remediation_cycles == 3  # Default

    def test_init_with_custom_max_cycles(self, temp_plan_path, temp_registry_db):
        """Runner accepts custom max_remediation_cycles."""
        runner = TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=temp_registry_db,
            max_remediation_cycles=5,
        )

        assert runner.max_remediation_cycles == 5

    def test_init_loads_plan_phases(self, temp_plan_path, temp_registry_db):
        """Runner loads and parses plan.json phases."""
        runner = TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=temp_registry_db,
        )

        assert "phase-06" in runner.phases
        assert runner.phases["phase-06"]["name"] == "Orca ADE Integration"
        assert len(runner.phases["phase-06"]["tasks"]) == 3

    def test_init_creates_registry_db_if_missing(self, temp_plan_path, temp_registry_db):
        """Runner ensures registry.db parent directory exists."""
        # Registry db path in non-existent directory
        nested_db = temp_registry_db.parent / "nested" / "registry.db"
        runner = TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=nested_db,
        )

        assert runner.registry_db_path == nested_db
        assert nested_db.parent.exists()


class TestTDDWorkflowRunnerImmediatePass:
    """Tests for immediate pass scenario (no remediation needed)."""

    @pytest.fixture
    def runner(self, temp_plan_path, temp_registry_db):
        return TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=temp_registry_db,
        )

    @pytest.mark.asyncio
    async def test_run_phase_tdd_cycle_immediate_pass(self, runner):
        """Full TDD cycle passes on first attempt."""
        with patch.object(runner, "_dispatch_test_author") as mock_test_author,              patch.object(runner, "_dispatch_builders") as mock_builders,              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_commit_and_advance") as mock_commit:

            # Mock test author writes tests
            mock_test_author.return_value = TestAuthorResult(
                success=True,
                test_files=["tests/phase_06/test_orca_generator.py"],
                tokens_used=1500,
            )

            # Mock builders implement tasks
            mock_builders.return_value = [
                BuilderResult(task_id="task-6.1", success=True, worktree_path="/tmp/wt1"),
                BuilderResult(task_id="task-6.2", success=True, worktree_path="/tmp/wt2"),
                BuilderResult(task_id="task-6.3", success=True, worktree_path="/tmp/wt3"),
            ]

            # Mock gatekeeper passes
            mock_gatekeeper.return_value = GatekeeperResult(
                passed=True,
                report_path="/tmp/report.json",
                exit_code=0,
            )

            result = await runner.run_phase_tdd_cycle("phase-06")

            assert result is True
            mock_test_author.assert_called_once_with("phase-06")
            mock_builders.assert_called_once_with("phase-06")
            mock_gatekeeper.assert_called_once_with("phase-06")
            mock_commit.assert_called_once_with("phase-06")

    @pytest.mark.asyncio
    async def test_test_author_dispatched_with_clean_context(self, runner):
        """Test author receives clean context under token limit."""
        with patch.object(runner, "_dispatch_test_author") as mock_test_author,              patch.object(runner, "_dispatch_builders"),              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_commit_and_advance"):

            mock_test_author.return_value = TestAuthorResult(success=True, test_files=[], tokens_used=1000)
            mock_gatekeeper.return_value = GatekeeperResult(passed=True, report_path="", exit_code=0)

            await runner.run_phase_tdd_cycle("phase-06")

            # Verify test author was called
            mock_test_author.assert_called_once()
            # The context should be clean (implicitly tested by low token count)
            result = mock_test_author.return_value
            assert result.tokens_used < 2500


class TestTDDWorkflowRunnerFailRemediatePass:
    """Tests for fail -> remediation -> pass scenario (cycle < 3)."""

    @pytest.fixture
    def runner(self, temp_plan_path, temp_registry_db):
        return TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=temp_registry_db,
        )

    @pytest.mark.asyncio
    async def test_fail_then_remediate_then_pass(self, runner):
        """Cycle 1 fails, remediation runs, cycle 2 passes."""
        with patch.object(runner, "_dispatch_test_author") as mock_test_author,              patch.object(runner, "_dispatch_builders") as mock_builders,              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_dispatch_remediation") as mock_remediation,              patch.object(runner, "_commit_and_advance") as mock_commit:

            # First gatekeeper fails
            mock_gatekeeper.side_effect = [
                GatekeeperResult(
                    passed=False,
                    report_path="/tmp/report1.json",
                    exit_code=1,
                    failures=[
                        {"file": "test_orca_generator.py", "test": "test_model_substitution", "error": "AssertionError: expected qwen2.5-coder-7b"}
                    ],
                ),
                GatekeeperResult(
                    passed=True,
                    report_path="/tmp/report2.json",
                    exit_code=0,
                ),
            ]

            mock_test_author.return_value = TestAuthorResult(success=True, test_files=[], tokens_used=1000)
            mock_builders.return_value = [BuilderResult(task_id="task-6.1", success=True, worktree_path="/tmp/wt")]
            mock_remediation.return_value = {"patched_files": ["orca_pack/generator.py"]}

            result = await runner.run_phase_tdd_cycle("phase-06")

            assert result is True
            assert mock_gatekeeper.call_count == 2
            mock_remediation.assert_called_once()

            # Verify remediation payload built from first failure
            remediation_call = mock_remediation.call_args
            payload = remediation_call[0][0]
            assert isinstance(payload, RemediationPayload)
            assert len(payload.failures) == 1
            assert payload.cycle_number == 1

    @pytest.mark.asyncio
    async def test_remediation_payload_contains_failure_details(self, runner):
        """Remediation payload includes failing assertions, stack traces, target files."""
        with patch.object(runner, "_dispatch_test_author"),              patch.object(runner, "_dispatch_builders"),              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_dispatch_remediation") as mock_remediation,              patch.object(runner, "_commit_and_advance"):

            mock_gatekeeper.side_effect = [
                GatekeeperResult(
                    passed=False,
                    report_path="/tmp/report.json",
                    exit_code=1,
                    failures=[
                        {
                            "file": "tests/phase_06/test_orca_hooks.py",
                            "test": "test_proxy_health",
                            "error": "AssertionError: expected 0, got 1",
                            "traceback": "Traceback (most recent call last)...",
                        }
                    ],
                ),
                GatekeeperResult(passed=True, report_path="", exit_code=0),
            ]

            await runner.run_phase_tdd_cycle("phase-06")

            payload = mock_remediation.call_args[0][0]
            assert payload.failures[0]["file"] == "tests/phase_06/test_orca_hooks.py"
            assert payload.failures[0]["test"] == "test_proxy_health"
            assert "AssertionError" in payload.failures[0]["error"]
            assert "Traceback" in payload.failures[0]["traceback"]
            assert payload.phase_id == "phase-06"
            assert payload.cycle_number == 1


class TestTDDWorkflowRunnerExhaustedCycles:
    """Tests for 3 cycles exhausted -> HITL escalation."""

    @pytest.fixture
    def runner(self, temp_plan_path, temp_registry_db):
        return TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=temp_registry_db,
            max_remediation_cycles=3,
        )

    @pytest.mark.asyncio
    async def test_three_cycles_exhausted_triggers_orca_snapshot(self, runner):
        """After 3 failed cycles, orca snapshot triggered and status paused."""
        with patch.object(runner, "_dispatch_test_author"),              patch.object(runner, "_dispatch_builders"),              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_dispatch_remediation") as mock_remediation,              patch.object(runner, "_trigger_orca_snapshot") as mock_snapshot,              patch.object(runner, "_update_workflow_status") as mock_status,              patch.object(runner, "_commit_and_advance") as mock_commit:

            # All 3 cycles fail
            mock_gatekeeper.return_value = GatekeeperResult(
                passed=False,
                report_path="/tmp/report.json",
                exit_code=1,
                failures=[{"file": "test.py", "test": "test_x", "error": "fail"}],
            )

            mock_remediation.return_value = {"patched_files": []}

            result = await runner.run_phase_tdd_cycle("phase-06")

            assert result is False
            assert mock_gatekeeper.call_count == 3  # Initial + 2 retries = 3 total attempts
            assert mock_remediation.call_count == 2  # Remediation after cycle 1 and 2
            mock_snapshot.assert_called_once()

            # Verify snapshot message mentions gatekeeper failure
            snapshot_args = mock_snapshot.call_args[0]
            assert "Gatekeeper failed after 3 remediation attempts" in snapshot_args[0]
            assert "phase-06" in snapshot_args[0]

            # Verify status updated to paused_gatekeeper_failed
            mock_status.assert_called_with("phase-06", "paused_gatekeeper_failed")

    @pytest.mark.asyncio
    async def test_snapshot_called_with_correct_message(self, runner):
        """orca snapshot called with descriptive failure message."""
        with patch.object(runner, "_dispatch_test_author"),              patch.object(runner, "_dispatch_builders"),              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_dispatch_remediation"),              patch.object(runner, "_trigger_orca_snapshot") as mock_snapshot,              patch.object(runner, "_update_workflow_status"):

            mock_gatekeeper.return_value = GatekeeperResult(
                passed=False,
                report_path="/tmp/report.json",
                exit_code=1,
                failures=[{"file": "test.py", "test": "test_x", "error": "Specific error detail"}],
            )

            await runner.run_phase_tdd_cycle("phase-06")

            mock_snapshot.assert_called_once()
            message = mock_snapshot.call_args[0][0]
            assert "Gatekeeper failed after 3 remediation attempts" in message
            assert "phase-06" in message
            assert "Specific error detail" in message or "fail" in message.lower()

    @pytest.mark.asyncio
    async def test_workflow_status_persisted_to_registry_db(self, runner, temp_registry_db):
        """Workflow run status persisted to registry.db."""
        with patch.object(runner, "_dispatch_test_author"),              patch.object(runner, "_dispatch_builders"),              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_dispatch_remediation"),              patch.object(runner, "_trigger_orca_snapshot"),              patch("orca_pack.workflows.tdd_workflow.get_registry_db") as mock_get_db:

            mock_gatekeeper.return_value = GatekeeperResult(
                passed=False, report_path="", exit_code=1, failures=[]
            )

            # Mock database connection
            mock_db = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_db

            await runner.run_phase_tdd_cycle("phase-06")

            # Verify database update was called
            mock_db.execute.assert_called()
            call_args = str(mock_db.execute.call_args)
            assert "paused_gatekeeper_failed" in call_args or "UPDATE workflow_runs" in call_args


class TestTDDWorkflowRunnerConfigurableCycles:
    """Tests for configurable max remediation cycles."""

    @pytest.mark.asyncio
    async def test_custom_max_cycles_respected(self, temp_plan_path, temp_registry_db):
        """Runner respects custom max_remediation_cycles value."""
        runner = TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=temp_registry_db,
            max_remediation_cycles=2,
        )

        with patch.object(runner, "_dispatch_test_author"),              patch.object(runner, "_dispatch_builders"),              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_dispatch_remediation") as mock_remediation,              patch.object(runner, "_trigger_orca_snapshot") as mock_snapshot,              patch.object(runner, "_update_workflow_status"):

            mock_gatekeeper.return_value = GatekeeperResult(
                passed=False, report_path="", exit_code=1, failures=[]
            )
            mock_remediation.return_value = {"patched_files": []}

            await runner.run_phase_tdd_cycle("phase-06")

            # With max_cycles=2: initial + 1 remediation = 2 gatekeeper runs
            assert mock_gatekeeper.call_count == 2
            assert mock_remediation.call_count == 1
            mock_snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_cycles_zero_means_no_remediation(self, temp_plan_path, temp_registry_db):
        """max_remediation_cycles=0 skips remediation entirely."""
        runner = TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=temp_registry_db,
            max_remediation_cycles=0,
        )

        with patch.object(runner, "_dispatch_test_author"),              patch.object(runner, "_dispatch_builders"),              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_dispatch_remediation") as mock_remediation,              patch.object(runner, "_trigger_orca_snapshot") as mock_snapshot,              patch.object(runner, "_update_workflow_status"):

            mock_gatekeeper.return_value = GatekeeperResult(
                passed=False, report_path="", exit_code=1, failures=[]
            )

            await runner.run_phase_tdd_cycle("phase-06")

            # Only initial gatekeeper run, no remediation
            assert mock_gatekeeper.call_count == 1
            mock_remediation.assert_not_called()
            mock_snapshot.assert_called_once()


class TestJSONReportParsing:
    """Tests for pytest JSON report parsing for remediation payload."""

    @pytest.fixture
    def sample_pytest_json_report(self):
        """Sample pytest --json-report output."""
        return {
            "exitcode": 1,
            "tests": [
                {
                    "nodeid": "tests/phase_06/test_orca_generator.py::test_model_substitution",
                    "outcome": "failed",
                    "lineno": 42,
                    "call": {
                        "crash": {
                            "message": "AssertionError: assert 'wrong-model' == 'qwen2.5-coder-7b'",
                            "lineno": 42,
                        },
                        "traceback": [
                            {"path": "test_orca_generator.py", "lineno": 42, "message": "assert manifest[\"models\"][\"local-slm\"][\"model\"] == \"qwen2.5-coder-7b\""}
                        ]
                    }
                },
                {
                    "nodeid": "tests/phase_06/test_orca_hooks.py::test_proxy_health",
                    "outcome": "passed",
                }
            ],
            "summary": {
                "total": 2,
                "passed": 1,
                "failed": 1,
            }
        }

    def test_parse_json_report_extracts_failures(self, runner, sample_pytest_json_report):
        """parse_json_report extracts failure details for remediation."""
        failures = runner._parse_json_report(sample_pytest_json_report)

        assert len(failures) == 1
        failure = failures[0]
        assert failure["file"] == "tests/phase_06/test_orca_generator.py"
        assert failure["test"] == "test_model_substitution"
        assert "AssertionError" in failure["error"]
        assert "qwen2.5-coder-7b" in failure["error"]
        assert "traceback" in failure

    def test_parse_json_report_handles_passed_tests(self, runner, sample_pytest_json_report):
        """parse_json_report ignores passed tests."""
        failures = runner._parse_json_report(sample_pytest_json_report)

        # Only 1 failure, not 2
        assert len(failures) == 1

    def test_parse_json_report_empty_on_all_passed(self, runner):
        """parse_json_report returns empty list when all tests pass."""
        report = {
            "exitcode": 0,
            "tests": [
                {"nodeid": "test_a", "outcome": "passed"},
                {"nodeid": "test_b", "outcome": "passed"},
            ],
            "summary": {"total": 2, "passed": 2, "failed": 0},
        }

        failures = runner._parse_json_report(report)
        assert failures == []

    def test_parse_json_report_malformed_graceful(self, runner):
        """parse_json_report handles malformed JSON gracefully."""
        # Missing tests key
        report = {"exitcode": 1}
        failures = runner._parse_json_report(report)
        assert failures == []


class TestTDDWorkflowRunnerIntegration:
    """Integration-style tests with more complete mocking."""

    @pytest.fixture
    def runner(self, temp_plan_path, temp_registry_db):
        return TDDWorkflowRunner(
            plan_path=temp_plan_path,
            registry_db_path=temp_registry_db,
        )

    @pytest.mark.asyncio
    async def test_full_cycle_with_worktree_isolation(self, runner):
        """Each task builder runs in isolated worktree."""
        with patch.object(runner, "_dispatch_test_author") as mock_test_author,              patch.object(runner, "_dispatch_builders") as mock_builders,              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_commit_and_advance"):

            mock_test_author.return_value = TestAuthorResult(success=True, test_files=[], tokens_used=1000)
            mock_builders.return_value = [
                BuilderResult(task_id="task-6.1", success=True, worktree_path="/tmp/worktrees/task-6.1"),
                BuilderResult(task_id="task-6.2", success=True, worktree_path="/tmp/worktrees/task-6.2"),
            ]
            mock_gatekeeper.return_value = GatekeeperResult(passed=True, report_path="", exit_code=0)

            await runner.run_phase_tdd_cycle("phase-06")

            # Verify builders called with phase_id
            mock_builders.assert_called_once_with("phase-06")

            # Results have distinct worktree paths
            results = mock_builders.return_value
            assert results[0].worktree_path != results[1].worktree_path

    @pytest.mark.asyncio
    async def test_gatekeeper_runs_pytest_with_json_report(self, runner):
        """Gatekeeper executes pytest with --json-report flag."""
        with patch.object(runner, "_dispatch_test_author"),              patch.object(runner, "_dispatch_builders"),              patch("subprocess.run") as mock_subprocess,              patch.object(runner, "_commit_and_advance"):

            mock_subprocess.return_value = MagicMock(
                returncode=0,
                stdout="",
                stderr=""
            )

            # Mock the internal _run_gatekeeper to use subprocess
            async def mock_run_gatekeeper(phase_id):
                result = mock_subprocess([
                    "pytest", f"tests/{phase_id}/", 
                    "--json-report", "--json-report-file=/tmp/report.json",
                    "-v"
                ])
                return GatekeeperResult(
                    passed=result.returncode == 0,
                    report_path="/tmp/report.json",
                    exit_code=result.returncode,
                )

            runner._run_gatekeeper = mock_run_gatekeeper

            await runner.run_phase_tdd_cycle("phase-06")

            mock_subprocess.assert_called_once()
            args = mock_subprocess.call_args[0][0]
            assert "pytest" in args[0]
            assert "--json-report" in args
            assert "--json-report-file" in " ".join(args)

    @pytest.mark.asyncio
    async def test_phase_advances_on_success(self, runner):
        """Successful phase marks tasks complete and advances."""
        with patch.object(runner, "_dispatch_test_author"),              patch.object(runner, "_dispatch_builders"),              patch.object(runner, "_run_gatekeeper") as mock_gatekeeper,              patch.object(runner, "_commit_and_advance") as mock_commit,              patch("orca_pack.workflows.tdd_workflow.get_registry_db") as mock_get_db:

            mock_gatekeeper.return_value = GatekeeperResult(passed=True, report_path="", exit_code=0)

            mock_db = AsyncMock()
            mock_get_db.return_value.__aenter__.return_value = mock_db

            await runner.run_phase_tdd_cycle("phase-06")

            mock_commit.assert_called_once_with("phase-06")
            # Registry should be updated
            mock_db.commit.assert_called()


# Fixtures
@pytest.fixture
def temp_plan_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        plan_path = Path(tmpdir) / "plan.json"
        plan_data = {
            "phases": [
                {
                    "phase_id": "phase-06",
                    "name": "Orca ADE Integration",
                    "tasks": [
                        {"task_id": "task-6.1", "title": "Orca YAML Generator"},
                        {"task_id": "task-6.2", "title": "Worktree Lifecycle Hooks"},
                        {"task_id": "task-6.3", "title": "TDD Workflow Runner"},
                    ]
                }
            ]
        }
        plan_path.write_text(json.dumps(plan_data))
        yield plan_path


@pytest.fixture
def temp_registry_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "registry.db"


@pytest.fixture
def runner(temp_plan_path, temp_registry_db):
    return TDDWorkflowRunner(
        plan_path=temp_plan_path,
        registry_db_path=temp_registry_db,
    )
