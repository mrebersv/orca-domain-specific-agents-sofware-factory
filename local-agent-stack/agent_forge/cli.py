"""Agent Forge unified CLI (`forge`).

Task 7.1: Unified command-line interface for the local-agent-stack toolchain.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_forge.ast_extractor import extract_and_ingest_python_tree
from agent_forge.spec_extractor import extract_and_ingest_openapi
from agent_forge.scaffolder import scaffold_agent
from agent_forge.verifier import verify_agent_workspace


BANNER = "Agent Forge"
TAGLINE = "local-agent-stack toolchain"


def _render_banner() -> str:
    """Render the Rich banner as plain text for help output."""
    console = Console(width=64, highlight=False)
    with console.capture() as capture:
        console.print(
            Panel.fit(
                f"[bold cyan]{BANNER}[/]\n[dim]{TAGLINE}[/]",
                border_style="cyan",
            )
        )
    return capture.get()


class ForgeGroup(click.Group):
    """Click group that prepends a Rich banner to help output."""

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write(_render_banner())
        formatter.write("\n")
        super().format_help(ctx, formatter)


@click.group(
    cls=ForgeGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Verbose output.")
@click.option("--quiet", "-q", is_flag=True, default=False, help="Suppress non-essential output.")
@click.pass_context
def main(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """Agent Forge: automated agent workspace generation from source code and specs."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet


@main.command()
@click.option("--source", "-s", "source", type=click.Path(exists=True, path_type=Path), required=True,
              help="Target source directory or Python file to parse via AST.")
@click.option("--openapi", "-o", "openapi", type=click.Path(exists=True, path_type=Path), default=None,
              help="Path to OpenAPI JSON/YAML file.")
@click.option("--db-path", "-d", "db_path", type=click.Path(path_type=Path),
              default=Path("./.agent/docs.db"), show_default=True,
              help="Target SQLite database.")
def ingest(source: Path, openapi: Optional[Path], db_path: Path) -> None:
    """Ingest AST and/or OpenAPI specs into docs.db."""
    from agent_forge.db.docs import init_docs_db

    async def run() -> tuple[int, int]:
        await init_docs_db(db_path)
        ast_count = await extract_and_ingest_python_tree(source, db_path)
        api_count = 0
        if openapi is not None:
            api_count = await extract_and_ingest_openapi(openapi, db_path)
        return ast_count, api_count

    ast_count, api_count = asyncio.run(run())

    table = Table(title="Ingestion Summary")
    table.add_column("Source", style="cyan")
    table.add_column("Symbols Indexed", justify="right", style="green")
    table.add_row(f"AST: {source}", str(ast_count))
    if openapi is not None:
        table.add_row(f"OpenAPI: {openapi}", str(api_count))
    table.add_row("Total", str(ast_count + api_count))

    console = Console()
    console.print(table)
    click.echo(f"Total indexed symbols: {ast_count + api_count}")


@main.command("init-orca")
@click.option("--target-dir", "-t", "target_dir", type=click.Path(path_type=Path), default=Path("."),
              show_default=True, help="Directory to initialize.")
@click.option("--model", "-m", "model", default="qwen2.5-coder-7b", show_default=True,
              help="Default local SLM name.")
@click.option("--force", "-f", "force", is_flag=True, default=False,
              help="Overwrite existing .orca/workspace.yaml.")
def init_orca(target_dir: Path, model: str, force: bool) -> None:
    """Initialize an Orca ADE workspace manifest."""
    from orca_pack.generator import generate_orca_manifest

    manifest_path = generate_orca_manifest(
        project_root=target_dir,
        local_model_name=model,
        force_overwrite=force,
    )
    click.echo(f"Orca manifest written: {manifest_path}")


@main.command()
@click.option("--agent-id", "-a", "agent_id", required=True, help="Unique identifier for sub-agent.")
@click.option("--name", "-n", required=True, help="Display name.")
@click.option("--description", "-desc", required=True, help="Sub-agent operational scope.")
@click.option("--db-path", "-d", "db_path", type=click.Path(path_type=Path),
              default=Path("./.agent/docs.db"), show_default=True, help="Path to source docs.db.")
@click.option("--output-dir", "-o", "output_dir", type=click.Path(path_type=Path),
              default=Path("./agents"), show_default=True, help="Destination directory.")
@click.option("--harness", type=click.Choice(["generic_cli", "pi", "hermes", "opencode", "claude-code"]),
              default="generic_cli", show_default=True, help="Target harness adapter.")
def scaffold(agent_id: str, name: str, description: str, db_path: Path,
             output_dir: Path, harness: str) -> None:
    """Render prompt.md, tools.py and agent.config.json for a sub-agent."""
    async def run() -> Path:
        return await scaffold_agent(
            agent_id=agent_id,
            name=name,
            description=description,
            db_path=db_path,
            output_dir=output_dir,
            harness_type=harness,
        )

    workspace = asyncio.run(run())
    click.echo(f"Scaffolded agent workspace at {workspace}")


@main.command()
@click.option("--workspace", "-w", "workspace", type=click.Path(exists=True, path_type=Path),
              required=True, help="Path to agent workspace directory.")
def verify(workspace: Path) -> None:
    """Run synthetic dry-run verification on an agent workspace."""
    result = asyncio.run(verify_agent_workspace(workspace))

    passed = result.get("status") == "passed"
    verdict = "[green]PASS[/]" if passed else "[red]FAIL[/]"
    console = Console()
    console.print(f"Agent: {result.get('agent_id', 'unknown')} — Verification: {verdict}")
    console.print(f"  Prompt tokens: {result.get('prompt_tokens_est', 'n/a')}")
    console.print(f"  Tools tested: {', '.join(result.get('tools_tested', []) or [])}")
    console.print(f"  Turns recorded: {result.get('turns_recorded', 0)}")
    for err in result.get("errors", []) or []:
        console.print(f"  [red]Error:[/] {err}")

    if not passed:
        raise SystemExit(1)


@main.command()
@click.option("--phase", "-p", "phase", default=None, help="Run specific phase ID (e.g. phase-01).")
@click.option("--plan", "plan", type=click.Path(exists=True, path_type=Path),
              default=Path("specs/plan.json"), show_default=True, help="Path to plan DAG.")
def run(phase: Optional[str], plan: Path) -> None:
    """Trigger the autonomous TDD orchestration loop."""
    from orca_pack.workflows.tdd_workflow import TDDWorkflowRunner

    registry_db = Path.home() / ".local-agent-stack" / "registry.db"
    registry_db.parent.mkdir(parents=True, exist_ok=True)
    runner = TDDWorkflowRunner(plan_path=plan, registry_db_path=registry_db)

    async def run_cycles() -> None:
        if phase is not None:
            ok = await runner.run_phase_tdd_cycle(phase)
            click.echo(f"Phase {phase}: {'completed' if ok else 'failed'}")
            if not ok:
                raise SystemExit(1)
        else:
            plan_data = json.loads(plan.read_text())
            for phase_entry in plan_data.get("phases", []):
                if phase_entry.get("status") == "pending":
                    pid = phase_entry["id"]
                    ok = await runner.run_phase_tdd_cycle(pid)
                    click.echo(f"Phase {pid}: {'completed' if ok else 'failed'}")
                    if not ok:
                        raise SystemExit(1)

    asyncio.run(run_cycles())


@main.command()
@click.option("--registry-db", "registry_db", type=click.Path(path_type=Path),
              default=Path.home() / ".local-agent-stack" / "registry.db", show_default=True,
              help="Path to registry.db.")
def status(registry_db: Path) -> None:
    """Display registered agents, tool permissions and recent workflow runs."""
    if not registry_db.exists():
        click.echo(f"[!] Registry DB not found at {registry_db}", err=True)
        raise SystemExit(1)

    conn = sqlite3.connect(f"file:{registry_db}?mode=ro", uri=True)
    try:
        console = Console()

        agents_table = Table(title="Registered Agents")
        for col in ("ID", "Name", "Harness"):
            agents_table.add_column(col)
        for row in conn.execute("SELECT agent_id, name, harness_type FROM agents"):
            agents_table.add_row(*[str(c) for c in row])
        console.print(agents_table)

        perms_table = Table(title="Tool Permissions")
        for col in ("Agent", "Tool", "Destructive", "Needs Approval"):
            perms_table.add_column(col)
        for row in conn.execute(
            "SELECT agent_id, tool_name, is_destructive, requires_approval "
            "FROM agent_tool_permissions"
        ):
            perms_table.add_row(*[str(c) for c in row])
        console.print(perms_table)

        runs_table = Table(title="Recent Workflow Runs")
        for col in ("Run ID", "Workflow", "Status", "Started"):
            runs_table.add_column(col)
        for row in conn.execute(
            "SELECT run_id, workflow_id, status, started_at FROM workflow_runs "
            "ORDER BY started_at DESC LIMIT 10"
        ):
            runs_table.add_row(*[str(c) for c in row])
        console.print(runs_table)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
