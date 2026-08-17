"""Symbol Schema, Examples, and Error Codes Tools for MCP server."""

from __future__ import annotations

from typing import Optional
from mcp_server.instance import mcp
from mcp_server.db import get_readonly_docs_db


@mcp.tool()
async def get_symbol_schema(symbol_id: str) -> str:
    """
    Get the complete schema for a symbol including parameters, return type, and signature.

    Args:
        symbol_id: Fully qualified symbol identifier (e.g., 'fastapi.routing.APIRoute').

    Returns:
        Formatted markdown with signature, parameters table, return type, and destructiveness flag.
    """
    try:
        async with get_readonly_docs_db() as db:
            # Get symbol details
            sql = """
            SELECT symbol_id, symbol_type, parent_scope, signature, return_type,
                   is_destructive, docstring_raw
            FROM symbols
            WHERE symbol_id = ?;
            """
            async with db.execute(sql, (symbol_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return f"Symbol not found: {symbol_id}"
            # Get parameters
            param_sql = """
            SELECT name, param_type, default_value, is_required, description
            FROM parameters
            WHERE symbol_id = ?
            ORDER BY id;
            """
            async with db.execute(param_sql, (symbol_id,)) as cursor:
                params = await cursor.fetchall()
            # Format output
            destructive = "⚠️ DESTRUCTIVE" if row["is_destructive"] else ""
            lines = [
                f"# {row['symbol_id']} {destructive}",
                f"**Type:** {row['symbol_type']}  |  **Scope:** {row['parent_scope'] or 'global'}",
                f"**Signature:** `{row['signature']}`",
                f"**Returns:** {row['return_type'] or 'None'}",
                "",
                "## Parameters"
            ]
            if params:
                lines.append("| Name | Type | Default | Required | Description |")
                lines.append("|------|------|---------|----------|-------------|")
                for p in params:
                    required = "✓" if p["is_required"] else ""
                    lines.append(
                        f"| `{p['name']}` | {p['param_type'] or '-'} | "
                        f"{p['default_value'] or '-'} | {required} | {p['description'] or '-'} |"
                    )
            else:
                lines.append("*No parameters*")
            if row["docstring_raw"]:
                lines.extend(["", "## Documentation", row["docstring_raw"]])
            return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving schema: {str(e)}"


@mcp.tool()
async def get_symbol_examples(symbol_id: str) -> str:
    """
    Get usage examples for a symbol.

    Args:
        symbol_id: Fully qualified symbol identifier (e.g., 'fastapi.routing.APIRoute').

    Returns:
        Formatted markdown list of examples with titles and code snippets.
    """
    try:
        async with get_readonly_docs_db() as db:
            # Check if symbol exists
            async with db.execute("SELECT 1 FROM symbols WHERE symbol_id = ?", (symbol_id,)) as cursor:
                if not await cursor.fetchone():
                    return f"Symbol not found: {symbol_id}"

            sql = """
            SELECT title, code_snippet, source_origin
            FROM examples
            WHERE symbol_id = ?
            ORDER BY example_id;
            """
            async with db.execute(sql, (symbol_id,)) as cursor:
                rows = await cursor.fetchall()
            if not rows:
                return f"No examples found for symbol: {symbol_id}"
            lines = [f"# Examples for {symbol_id}", ""]
            for i, row in enumerate(rows, 1):
                lines.append(f"## Example {i}: {row['title']}")
                lines.append(f"*Source: {row['source_origin']}*")
                lines.append("")
                lines.append("```python")
                lines.append(row["code_snippet"])
                lines.append("```")
                lines.append("")
            return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving examples: {str(e)}"


@mcp.tool()
async def list_error_codes(symbol_id: str) -> str:
    """
    List error codes and recovery actions for a symbol.

    Args:
        symbol_id: Fully qualified symbol identifier (e.g., 'fastapi.routing.APIRoute').

    Returns:
        Formatted markdown table of error codes, meanings, and recovery actions.
    """
    try:
        async with get_readonly_docs_db() as db:
            # Check if symbol exists
            async with db.execute("SELECT 1 FROM symbols WHERE symbol_id = ?", (symbol_id,)) as cursor:
                if not await cursor.fetchone():
                    return f"Symbol not found: {symbol_id}"

            sql = """
            SELECT code, meaning, recovery_action
            FROM error_codes
            WHERE symbol_id = ?
            ORDER BY code;
            """
            async with db.execute(sql, (symbol_id,)) as cursor:
                rows = await cursor.fetchall()
            if not rows:
                return f"No error codes documented for symbol: {symbol_id}"
            lines = [
                f"# Error Codes for {symbol_id}",
                "",
                "| Code | Meaning | Recovery Action |",
                "|------|---------|-----------------|"
            ]
            for row in rows:
                lines.append(
                    f"| {row['code']} | {row['meaning']} | {row['recovery_action']} |"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"Error retrieving error codes: {str(e)}"
