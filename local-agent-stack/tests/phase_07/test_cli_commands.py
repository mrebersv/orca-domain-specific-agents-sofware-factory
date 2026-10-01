"""Phase 7 / Task 7.1: Unified CLI entrypoint (`forge`) verification tests."""

from __future__ import annotations

import subprocess
import sys

import pytest
from click.testing import CliRunner

from agent_forge.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestRootCommand:
    """forge --help: banner, global flags and subcommand registry."""

    def test_help_exit_code_zero(self, runner: CliRunner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0

    def test_help_option_names(self, runner: CliRunner):
        result = runner.invoke(main, ["-h"])
        assert result.exit_code == 0
        assert "--help" in result.output

    def test_banner_rendered(self, runner: CliRunner):
        result = runner.invoke(main, ["--help"])
        assert "Agent Forge" in result.output

    def test_global_flags_listed(self, runner: CliRunner):
        result = runner.invoke(main, ["--help"])
        for flag in ("--verbose", "-v", "--quiet", "-q"):
            assert flag in result.output

    def test_all_subcommands_registered(self, runner: CliRunner):
        result = runner.invoke(main, ["--help"])
        for command in ("ingest", "init-orca", "scaffold", "verify", "run", "status"):
            assert command in result.output


class TestIngestHelp:
    """forge ingest --help."""

    def test_help_exit_code_zero(self, runner: CliRunner):
        result = runner.invoke(main, ["ingest", "--help"])
        assert result.exit_code == 0

    def test_expected_flags(self, runner: CliRunner):
        result = runner.invoke(main, ["ingest", "--help"])
        for flag in ("--source", "-s", "--openapi", "-o", "--db-path", "-d"):
            assert flag in result.output


class TestInitOrcaHelp:
    """forge init-orca --help."""

    def test_help_exit_code_zero(self, runner: CliRunner):
        result = runner.invoke(main, ["init-orca", "--help"])
        assert result.exit_code == 0

    def test_expected_flags(self, runner: CliRunner):
        result = runner.invoke(main, ["init-orca", "--help"])
        for flag in ("--target-dir", "-t", "--model", "-m", "--force", "-f"):
            assert flag in result.output


class TestScaffoldHelp:
    """forge scaffold --help."""

    def test_help_exit_code_zero(self, runner: CliRunner):
        result = runner.invoke(main, ["scaffold", "--help"])
        assert result.exit_code == 0

    def test_expected_flags(self, runner: CliRunner):
        result = runner.invoke(main, ["scaffold", "--help"])
        for flag in (
            "--agent-id", "-a", "--name", "-n", "--description", "-desc",
            "--db-path", "-d", "--output-dir", "-o", "--harness",
        ):
            assert flag in result.output

    def test_harness_choices(self, runner: CliRunner):
        result = runner.invoke(main, ["scaffold", "--help"])
        for choice in ("generic_cli", "pi", "hermes", "opencode", "claude-code"):
            assert choice in result.output


class TestVerifyHelp:
    """forge verify --help."""

    def test_help_exit_code_zero(self, runner: CliRunner):
        result = runner.invoke(main, ["verify", "--help"])
        assert result.exit_code == 0

    def test_expected_flags(self, runner: CliRunner):
        result = runner.invoke(main, ["verify", "--help"])
        assert "--workspace" in result.output
        assert "-w" in result.output


class TestRunHelp:
    """forge run --help."""

    def test_help_exit_code_zero(self, runner: CliRunner):
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0

    def test_expected_flags(self, runner: CliRunner):
        result = runner.invoke(main, ["run", "--help"])
        for flag in ("--phase", "-p", "--plan"):
            assert flag in result.output


class TestStatusHelp:
    """forge status --help."""

    def test_help_exit_code_zero(self, runner: CliRunner):
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0

    def test_expected_flags(self, runner: CliRunner):
        result = runner.invoke(main, ["status", "--help"])
        assert "--registry-db" in result.output


class TestModuleEntrypoint:
    """Verification command from task spec: python3 -m agent_forge.cli --help."""

    def test_python_dash_m_help(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "agent_forge.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "Agent Forge" in result.stdout
        assert "ingest" in result.stdout
