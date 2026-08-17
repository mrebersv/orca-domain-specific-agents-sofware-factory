"""MCP Server CLI entrypoint for docs.db knowledge server."""

from __future__ import annotations

import asyncio
from pathlib import Path
import click

from mcp_server.server import mcp
from mcp_server.db import resolve_docs_db_path


@click.command()
@click.option(
    "--db-path",
    type=click.Path(exists=True, path_type=Path),
    help="Path to docs.db file",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    default="stdio",
    help="Transport protocol",
)
@click.option("--host", default="127.0.0.1", help="Host for HTTP transports")
@click.option("--port", default=8000, type=int, help="Port for HTTP transports")
def main(db_path: Path | None, transport: str, host: str, port: int) -> None:
    """Run the docs.db knowledge MCP server."""
    if db_path:
        from mcp_server.server import set_db_path
        set_db_path(db_path)
    else:
        # Auto-resolve
        resolved = resolve_docs_db_path()
        from mcp_server.server import set_db_path
        set_db_path(resolved)

    if transport == "stdio":
        mcp.run_stdio()
    elif transport == "sse":
        mcp.run_sse(host=host, port=port)
    elif transport == "streamable-http":
        mcp.run_streamable_http(host=host, port=port)


if __name__ == "__main__":
    main()
