"""Agent Forge CLI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
import click

from agent_forge.ast_extractor import PythonASTExtractor, extract_and_ingest_python_tree
from agent_forge.spec_extractor import OpenAPIExtractor, CLIExtractor, extract_and_ingest_openapi, extract_and_ingest_cli_spec
from agent_forge.scaffolder import AgentScaffolder, scaffold_agent
from agent_forge.verifier import AgentVerifier, verify_agent_workspace
from agent_forge.db.docs import init_docs_db


@click.group()
def main() -> None:
    """Agent Forge: Automated agent workspace generation from source code and specs."""
    pass


@main.command()
@click.argument("source_path", type=click.Path(exists=True, path_type=Path))
@click.argument("db_path", type=click.Path(path_type=Path))
def extract_python(source_path: Path, db_path: Path) -> None:
    """Extract symbols from Python source tree into docs.db."""
    async def run() -> None:
        await init_docs_db(db_path)
        extractor = PythonASTExtractor()
        count = await extractor.extract_and_ingest_python_tree(source_path, db_path)
        click.echo(f"Extracted and ingested {count} symbols from {source_path}")

    asyncio.run(run())


@main.command()
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path))
@click.argument("db_path", type=click.Path(path_type=Path))
def extract_openapi(spec_path: Path, db_path: Path) -> None:
    """Extract symbols from OpenAPI spec into docs.db."""
    async def run() -> None:
        await init_docs_db(db_path)
        extractor = OpenAPIExtractor()
        count = await extractor.extract_and_ingest_openapi(spec_path, db_path)
        click.echo(f"Extracted and ingested {count} endpoints from {spec_path}")

    asyncio.run(run())


@main.command()
@click.argument("command_name")
@click.argument("help_text")
@click.argument("db_path", type=click.Path(path_type=Path))
def extract_cli(command_name: str, help_text: str, db_path: Path) -> None:
    """Extract symbols from CLI help text into docs.db."""
    async def run() -> None:
        await init_docs_db(db_path)
        extractor = CLIExtractor()
        count = await extractor.extract_and_ingest_cli_spec(command_name, help_text, db_path)
        click.echo(f"Extracted and ingested {count} CLI commands from {command_name}")

    asyncio.run(run())


@main.command()
@click.option("--agent-id", required=True, help="Unique agent identifier")
@click.option("--name", required=True, help="Agent display name")
@click.option("--description", required=True, help="Agent description")
@click.option("--db-path", required=True, type=click.Path(exists=True, path_type=Path), help="Path to docs.db")
@click.option("--output-dir", required=True, type=click.Path(path_type=Path), help="Output directory for workspace")
@click.option("--harness-type", default="generic_cli", help="Harness type")
@click.option("--model-name", default="local-slm", help="Model name")
@click.option("--model-endpoint", default="http://127.0.0.1:8000/v1", help="Model endpoint")
def scaffold(
    agent_id: str,
    name: str,
    description: str,
    db_path: Path,
    output_dir: Path,
    harness_type: str,
    model_name: str,
    model_endpoint: str,
) -> None:
    """Scaffold an agent workspace from docs.db."""
    async def run() -> None:
        scaffolder = AgentScaffolder()
        workspace = await scaffolder.scaffold_agent(
            agent_id=agent_id,
            name=name,
            description=description,
            db_path=db_path,
            output_dir=output_dir,
            harness_type=harness_type,
            model_name=model_name,
            model_endpoint=model_endpoint,
        )
        click.echo(f"Scaffolded agent workspace at {workspace}")

    asyncio.run(run())


@main.command()
@click.argument("workspace_dir", type=click.Path(exists=True, path_type=Path))
def verify(workspace_dir: Path) -> None:
    """Run synthetic verification on agent workspace."""
    async def run() -> None:
        verifier = AgentVerifier()
        result = await verifier.verify_agent_workspace(workspace_dir)
        click.echo(f"Agent: {result['agent_id']}")
        click.echo(f"Status: {result['status']}")
        click.echo(f"Prompt tokens: {result['prompt_tokens_est']}")
        click.echo(f"Tools tested: {', '.join(result['tools_tested'])}")
        click.echo(f"Turns recorded: {result['turns_recorded']}")
        if result["errors"]:
            click.echo("Errors:")
            for err in result["errors"]:
                click.echo(f"  - {err}")

    asyncio.run(run())


@main.command()
@click.argument("db_path", type=click.Path(path_type=Path))
def init_db(db_path: Path) -> None:
    """Initialize docs.db schema."""
    async def run() -> None:
        await init_docs_db(db_path)
        click.echo(f"Initialized docs.db at {db_path}")

    asyncio.run(run())


if __name__ == "__main__":
    main()
