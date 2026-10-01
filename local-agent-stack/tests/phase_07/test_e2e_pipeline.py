"""Phase 7 / Task 7.2: Synthetic end-to-end pipeline integration test.

Validates the full local-agent-stack lifecycle in an isolated synthetic
environment: repo setup → AST ingestion → MCP protocol → scaffolding &
verification → ephemeral worktree + harness dispatch → gatekeeper &
remediation loop.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from agent_forge.ast_extractor import extract_and_ingest_python_tree
from agent_forge.db.docs import init_docs_db
from agent_forge.db.registry import init_registry_db
from agent_forge.db.scratch import get_scratch_db
from agent_forge.scaffolder import scaffold_agent
from agent_forge.verifier import verify_agent_workspace
from orca_pack.hooks.setup_worktree_env import create_ephemeral_worktree
from orca_pack.workflows.tdd_workflow import TDDWorkflowRunner

PHASE_ID = "phase-99-synthetic"

GEOMETRY_SOURCE = '''
"""Geometry primitives with typed contracts."""


class GeometryError(Exception):
    """Raised when a geometric computation is invalid."""


class Rectangle:
    """A rectangle with typed dimensions."""

    def __init__(self, width: float, height: float) -> None:
        """Initialize the rectangle.

        Args:
            width: Horizontal extent in units.
            height: Vertical extent in units.
        """
        self.width = width
        self.height = height

    def scale(self, factor: float) -> "Rectangle":
        """Return a scaled copy of the rectangle.

        Args:
            factor: Positive scale factor.

        Returns:
            A new Rectangle instance.
        """
        return Rectangle(self.width * factor, self.height * factor)


def calculate_area(width: float, height: float) -> float:
    """Calculate the area of a rectangle.

    Args:
        width: Horizontal extent in units.
        height: Vertical extent in units.

    Returns:
        The computed area.

    Raises:
        GeometryError: If any dimension is negative.

    Example:
        >>> calculate_area(2.0, 3.0)
        6.0
    """
    if width < 0 or height < 0:
        raise GeometryError("dimensions must be non-negative")
    return width * height
'''

UNITS_SOURCE = '''
"""Unit conversion helpers."""


def convert_units(value: float, factor: float) -> float:
    """Convert a value between units using a fixed factor.

    Args:
        value: Input magnitude.
        factor: Conversion multiplier.

    Returns:
        The converted magnitude.

    Example:
        >>> convert_units(2.0, 100.0)
        200.0
    """
    return value * factor
'''


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command inside the synthetic repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


async def _fetch_scalar(db: aiosqlite.Connection, sql: str, params: tuple = ()) -> Any:
    cursor = await db.execute(sql, params)
    return (await cursor.fetchone())[0]


class TestSyntheticE2EPipeline:
    """One sequential lifecycle: ingest → MCP → scaffold → verify → worktree → gatekeeper."""

    @pytest.mark.asyncio
    async def test_full_synthetic_pipeline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        repo = tmp_path / "repo"
        repo.mkdir()

        # ------------------------------------------------------------------
        # Step 1: Synthetic codebase & repository setup
        # ------------------------------------------------------------------
        assert _git(repo, "init").returncode == 0
        _git(repo, "config", "user.email", "e2e@test.local")
        _git(repo, "config", "user.name", "E2E Synthetic")

        pkg = repo / "geometry_pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "shapes.py").write_text(GEOMETRY_SOURCE)
        (pkg / "units.py").write_text(UNITS_SOURCE)
        # Ephemeral worktree admin directory is setup noise, not agent output
        (repo / ".gitignore").write_text(".worktrees/\n")

        assert _git(repo, "add", "-A").returncode == 0
        assert _git(repo, "commit", "-m", "synthetic geometry package").returncode == 0

        # ------------------------------------------------------------------
        # Step 2: Codebase ingestion (forge ingest core)
        # ------------------------------------------------------------------
        docs_db = repo / ".agent" / "docs.db"
        await init_docs_db(docs_db)
        ingested = await extract_and_ingest_python_tree(repo, docs_db)
        assert ingested > 0

        async with aiosqlite.connect(docs_db) as db:
            # symbols table has extracted classes and functions
            calc_id = await _fetch_scalar(
                db, "SELECT symbol_id FROM symbols WHERE symbol_id LIKE '%calculate_area'"
            )
            assert calc_id, "calculate_area symbol missing"
            assert await _fetch_scalar(
                db, "SELECT COUNT(*) FROM symbols WHERE symbol_type = 'class' "
                    "AND symbol_id LIKE '%Rectangle'"
            ) >= 1
            assert await _fetch_scalar(
                db, "SELECT COUNT(*) FROM symbols WHERE symbol_type = 'class' "
                    "AND symbol_id LIKE '%GeometryError'"
            ) >= 1

            # parameters table has typed parameters
            param_rows = await (await db.execute(
                "SELECT name, param_type FROM parameters WHERE symbol_id = ?", (calc_id,)
            )).fetchall()
            param_types = {name: ptype for name, ptype in param_rows}
            assert param_types.get("width") == "float"
            assert param_types.get("height") == "float"

            # examples table has doctest code blocks
            example_rows = await (await db.execute(
                "SELECT code_snippet FROM examples WHERE symbol_id = ?", (calc_id,)
            )).fetchall()
            snippets = [row[0] for row in example_rows]
            assert any("calculate_area(2.0, 3.0)" in s for s in snippets)

            # symbols_fts returns matching results for BM25 queries
            fts_rows = await (await db.execute(
                "SELECT symbol_id FROM symbols_fts WHERE symbols_fts MATCH 'calculate area'"
            )).fetchall()
            assert any("calculate_area" in row[0] for row in fts_rows)

        # ------------------------------------------------------------------
        # Step 3: FastMCP protocol verification
        # ------------------------------------------------------------------
        import mcp_server.server as server_module
        from mcp_server.server import mcp, set_db_path

        old_db_path = server_module._current_db_path
        try:
            set_db_path(docs_db)

            search_result = await mcp.call_tool(
                "search_symbols", {"query": "calculate area", "limit": 10}
            )
            assert not search_result.isError
            search_text = search_result.content[0].text
            assert "calculate_area" in search_text

            schema_result = await mcp.call_tool("get_symbol_schema", {"symbol_id": calc_id})
            assert not schema_result.isError
            schema_text = schema_result.content[0].text
            assert "width" in schema_text
            assert "float" in schema_text
        finally:
            server_module._current_db_path = old_db_path

        # ------------------------------------------------------------------
        # Step 4: Sub-agent scaffolding & verification
        # ------------------------------------------------------------------
        agents_dir = repo / "agents"
        workspace = await scaffold_agent(
            agent_id="math_geometry_agent",
            name="Math Geometry Agent",
            description="Geometry computation agent",
            db_path=docs_db,
            output_dir=agents_dir,
            harness_type="generic_cli",
        )
        assert (workspace / "prompt.md").exists()
        assert (workspace / "tools.py").exists()
        assert (workspace / "agent.config.json").exists()

        # tools.py imports and instantiates cleanly
        tools_spec = importlib.util.spec_from_file_location(
            "e2e_math_geometry_tools", workspace / "tools.py"
        )
        tools_module = importlib.util.module_from_spec(tools_spec)
        tools_spec.loader.exec_module(tools_module)

        summary = await verify_agent_workspace(workspace)
        assert summary["status"] == "passed", summary["errors"]
        assert 0 < summary["prompt_tokens_est"] < 500
        assert summary["turns_recorded"] > 0
        assert len(summary["tools_tested"]) > 0

        # initial execution traces exist in scratch.db
        scratch_db = workspace / "scratch.db"
        assert scratch_db.exists()
        async with get_scratch_db(scratch_db) as db:
            turns = await _fetch_scalar(db, "SELECT COUNT(*) FROM execution_turns")
        assert turns > 0

        # ------------------------------------------------------------------
        # Step 5: Ephemeral Git worktree & harness execution
        # ------------------------------------------------------------------
        assert _git(repo, "add", "-A").returncode == 0
        assert _git(repo, "commit", "-m", "add docs.db and scaffolded workspace").returncode == 0

        worktree = create_ephemeral_worktree(repo, "task-math-feature")
        assert worktree.exists()
        assert (worktree / "geometry_pkg").exists()

        from adapters.base import AgentExecutionContext
        from adapters.generic_cli_adapter import GenericCLIAdapter

        adapter = GenericCLIAdapter(
            agent_config={"harness_type": "generic_cli", "agent_id": "math_geometry_agent"},
            workspace_dir=workspace,
        )
        context = AgentExecutionContext(
            session_id="e2e-math-feature",
            task_prompt="Implement the math feature",
            worktree_path=worktree,
            workspace_dir=workspace,
            max_turns=3,
            timeout_seconds=60,
        )

        feature_file = "geometry_feature.py"

        async def fake_agent_exec(*cmd_args: Any, **_: Any) -> Any:
            """Mock sub-agent runner: writes the feature into the worktree."""
            cmd = [a for a in cmd_args if isinstance(a, str)]
            if "--workdir" in cmd:
                workdir = Path(cmd[cmd.index("--workdir") + 1])
                (workdir / feature_file).write_text(
                    '"""Feature applied by synthetic agent."""\n'
                )
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"feature applied", b""))
            proc.returncode = 0
            return proc

        from unittest.mock import AsyncMock, patch

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = fake_agent_exec
            turn = await adapter.run_turn(context)

        assert turn.status == "success"
        assert turn.exit_code == 0
        assert (worktree / feature_file).exists()
        assert not (repo / feature_file).exists()
        parent_status = _git(repo, "status", "--porcelain")
        assert parent_status.returncode == 0
        assert parent_status.stdout.strip() == "", "parent repo root was dirtied"

        # ------------------------------------------------------------------
        # Step 6: Gatekeeper & remediation validation
        # ------------------------------------------------------------------
        plan_path = repo / "plan.json"
        plan_path.write_text(json.dumps({
            "phases": [{
                "phase_id": PHASE_ID,
                "title": "Synthetic math feature",
                "status": "pending",
                "tasks": [{"task_id": "99.1", "title": "Implement math feature"}],
            }]
        }))

        # Simulated builder output: feature test fails on cycle 1
        state_path = repo / "feature_state.json"
        state_path.write_text(json.dumps({"fixed": False}))

        tests_dir = repo / "tests" / PHASE_ID
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_feature.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            f"STATE = Path({str(state_path)!r})\n"
            "\n"
            "def test_feature_ready():\n"
            "    state = json.loads(STATE.read_text())\n"
            "    assert state['fixed'] is True\n"
        )

        registry_db = repo / ".agent" / "registry.db"
        await init_registry_db(registry_db)
        async with aiosqlite.connect(registry_db) as db:
            await db.execute(
                "INSERT INTO workflows (workflow_id, name, description, dag_definition) "
                "VALUES (?, ?, ?, ?)",
                (PHASE_ID, "Synthetic Workflow", "E2E synthetic workflow", "{}"),
            )
            await db.execute(
                "INSERT INTO workflow_runs (run_id, workflow_id, status) "
                "VALUES (?, ?, 'running')",
                ("run-e2e-99", PHASE_ID),
            )
            await db.commit()

        # Gatekeeper subprocess needs the venv's pytest (json-report plugin)
        monkeypatch.chdir(repo)
        monkeypatch.setenv(
            "PATH",
            f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}",
        )

        remediation_calls: list[dict] = []

        async def fake_remediation(self: TDDWorkflowRunner, payload: Any) -> dict:
            """Capture payload, write remediation_payload.json, fix on cycle 2."""
            remediation_calls.append({
                "cycle_number": payload.cycle_number,
                "failures": payload.failures,
                "exit_code": payload.exit_code,
            })
            (repo / "remediation_payload.json").write_text(json.dumps({
                "phase_id": payload.phase_id,
                "cycle_number": payload.cycle_number,
                "failures": payload.failures,
                "report_path": payload.report_path,
                "exit_code": payload.exit_code,
            }, indent=2))
            if payload.cycle_number >= 2:
                state_path.write_text(json.dumps({"fixed": True}))
            return {"patched_files": ["feature_state.json"]}

        with patch.object(TDDWorkflowRunner, "_dispatch_remediation", fake_remediation):
            runner = TDDWorkflowRunner(
                plan_path=plan_path,
                registry_db_path=registry_db,
                max_remediation_cycles=3,
            )
            completed = await runner.run_phase_tdd_cycle(PHASE_ID)

        # Cycle 1 failed, remediation payload generated, cycle 2 fix applied,
        # final gatekeeper passed
        assert completed is True
        assert len(remediation_calls) >= 1
        assert remediation_calls[0]["exit_code"] != 0
        assert len(remediation_calls[0]["failures"]) >= 1

        payload_path = repo / "remediation_payload.json"
        assert payload_path.exists()
        payload = json.loads(payload_path.read_text())
        assert payload["phase_id"] == PHASE_ID
        assert payload["failures"]
        assert payload["exit_code"] != 0

        assert json.loads(state_path.read_text())["fixed"] is True

        # Final gatekeeper report shows the passing run
        report = json.loads(Path(payload["report_path"]).read_text())
        assert report["summary"].get("passed") == 1

        # Workflow run status updated to completed in registry.db
        async with aiosqlite.connect(registry_db) as db:
            run_status, run_completed = await (
                await db.execute(
                    "SELECT status, completed_at FROM workflow_runs WHERE workflow_id = ?",
                    (PHASE_ID,),
                )
            ).fetchone()
        assert run_status == "completed"
        assert run_completed is not None
