"""OpenAPI & CLI Spec Extractor for Agent Forge (Path B)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Optional
import yaml

from agent_forge.db.docs import get_docs_db, insert_symbol_bundle


class OpenAPIExtractor:
    """Extract symbols from OpenAPI v3 specifications."""

    def __init__(self) -> None:
        self.symbols_extracted: list[dict[str, Any]] = []

    def _load_spec(self, spec_path: Path) -> dict[str, Any]:
        """Load OpenAPI spec from JSON or YAML file."""
        content = spec_path.read_text(encoding="utf-8")
        if spec_path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(content)
        return json.loads(content)

    def _resolve_ref(self, spec: dict[str, Any], ref: str) -> dict[str, Any]:
        """Resolve internal $ref references."""
        if not ref.startswith("#/"):
            return {}
        parts = ref[2:].split("/")
        current = spec
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return {}
        return current if isinstance(current, dict) else {}

    def _get_schema_type(self, schema: dict[str, Any]) -> str:
        """Extract type string from JSON schema."""
        if "type" in schema:
            t = schema["type"]
            if t == "array" and "items" in schema:
                return f"array[{self._get_schema_type(schema['items'])}]"
            return t
        if "anyOf" in schema:
            return " | ".join(self._get_schema_type(s) for s in schema["anyOf"])
        if "oneOf" in schema:
            return " | ".join(self._get_schema_type(s) for s in schema["oneOf"])
        if "$ref" in schema:
            return schema["$ref"].split("/")[-1]
        return "object"

    def _extract_parameters(
        self,
        parameters: list[dict[str, Any]],
        spec: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract OpenAPI parameters into our parameter format."""
        extracted = []
        for param in parameters:
            # Handle $ref in parameters
            if "$ref" in param:
                param = self._resolve_ref(spec, param["$ref"])

            schema = param.get("schema", {})
            param_type = self._get_schema_type(schema)
            default = schema.get("default")
            extracted.append({
                "name": param.get("name", ""),
                "param_type": param_type,
                "default_value": json.dumps(default) if default is not None else None,
                "is_required": param.get("required", False),
                "description": param.get("description"),
            })
        return extracted

    def _extract_request_body(
        self,
        request_body: dict[str, Any],
        spec: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract request body properties as parameters."""
        extracted = []
        content = request_body.get("content", {})
        for media_type, media_obj in content.items():
            schema = media_obj.get("schema", {})
            if "$ref" in schema:
                schema = self._resolve_ref(spec, schema["$ref"])

            if schema.get("type") == "object" and "properties" in schema:
                required = schema.get("required", [])
                for prop_name, prop_schema in schema["properties"].items():
                    if "$ref" in prop_schema:
                        prop_schema = self._resolve_ref(spec, prop_schema["$ref"])
                    extracted.append({
                        "name": f"body.{prop_name}",
                        "param_type": self._get_schema_type(prop_schema),
                        "default_value": json.dumps(prop_schema.get("default")) if "default" in prop_schema else None,
                        "is_required": prop_name in required,
                        "description": prop_schema.get("description"),
                    })
        return extracted

    def _extract_responses(
        self,
        responses: dict[str, Any],
        spec: dict[str, Any],
    ) -> tuple[Optional[str], list[dict[str, Any]]]:
        """Extract return type and error codes from responses."""
        return_type = None
        error_codes = []

        for status_code, response in responses.items():
            if status_code.startswith("2"):  # Success responses
                content = response.get("content", {})
                for media_type, media_obj in content.items():
                    schema = media_obj.get("schema", {})
                    if "$ref" in schema:
                        return_type = schema["$ref"].split("/")[-1]
                    elif "type" in schema:
                        return_type = self._get_schema_type(schema)
            elif status_code.startswith(("4", "5")):  # Error responses
                desc = response.get("description", "Error")
                error_codes.append({
                    "code": f"HTTP {status_code}",
                    "meaning": desc,
                    "recovery_action": "Verify request parameters and retry" if status_code.startswith("4") else "Check service availability and retry",
                })

        return return_type, error_codes

    def _is_destructive(self, method: str) -> bool:
        """Check if HTTP method is potentially destructive."""
        return method.upper() in {"DELETE", "PATCH", "POST", "PUT"}

    def extract_from_spec(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract all endpoint symbols from OpenAPI spec."""
        symbols = []
        paths = spec.get("paths", {})
        tags = spec.get("tags", [])

        for path, path_obj in paths.items():
            for method, op in path_obj.items():
                if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
                    continue

                # Determine parent scope from tags
                op_tags = op.get("tags", [])
                parent_scope = op_tags[0] if op_tags else "default"

                symbol_id = f"{method.upper()} {path}"
                summary = op.get("summary", "")
                description = op.get("description", "")
                docstring_raw = f"{summary}\n\n{description}".strip() if (summary or description) else ""

                # Extract parameters
                params = self._extract_parameters(op.get("parameters", []), spec)

                # Extract request body
                if "requestBody" in op:
                    params.extend(self._extract_request_body(op["requestBody"], spec))

                # Extract responses
                return_type, error_codes = self._extract_responses(op.get("responses", {}), spec)

                # Build signature
                signature = f"{method.upper()} {path} -> {return_type or 'Response'}"

                symbol = {
                    "symbol_id": symbol_id,
                    "symbol_type": "endpoint",
                    "parent_scope": parent_scope,
                    "signature": signature,
                    "return_type": return_type,
                    "docstring_raw": docstring_raw,
                    "source_file": "openapi_spec",
                    "is_destructive": self._is_destructive(method),
                    "parameters": params,
                    "examples": [],
                    "error_codes": error_codes,
                }
                symbols.append(symbol)

        return symbols

    async def extract_and_ingest_openapi(
        self,
        spec_path: Path,
        db_path: Path,
    ) -> int:
        """Extract symbols from OpenAPI spec and ingest into docs.db."""
        spec = self._load_spec(spec_path)
        symbols = self.extract_from_spec(spec)

        total_ingested = 0
        async with get_docs_db(db_path, read_only=False) as db:
            for symbol in symbols:
                symbol_data = {k: v for k, v in symbol.items() if k not in ("parameters", "examples", "error_codes")}
                params = symbol.get("parameters", [])
                examples = symbol.get("examples", [])
                errors = symbol.get("error_codes", [])

                await insert_symbol_bundle(db, symbol_data, params, examples, errors)
                total_ingested += 1

        return total_ingested


class CLIExtractor:
    """Extract symbols from CLI command structures."""

    def __init__(self) -> None:
        self.symbols_extracted: list[dict[str, Any]] = []

    def _parse_click_group(self, ctx, parent_scope: str, command_name: str) -> list[dict[str, Any]]:
        """Extract commands from a Click group."""
        symbols = []
        for name, cmd in ctx.command.commands.items():
            if hasattr(cmd, "commands"):  # It's a group
                symbols.extend(self._parse_click_group(cmd.make_context(name, []), parent_scope, name))
            else:
                symbols.append(self._parse_click_command(cmd, parent_scope, command_name))
        return symbols

    def _parse_click_command(self, cmd, parent_scope: str, root_command: str) -> dict[str, Any]:
        """Extract a single Click command."""
        params = []
        for param in cmd.params:
            param_type = "string"
            if hasattr(param, "type") and param.type:
                param_type = str(param.type).lower()

            default = param.default
            params.append({
                "name": param.name or "",
                "param_type": param_type,
                "default_value": str(default) if default is not None else None,
                "is_required": param.required,
                "description": param.help,
            })

        symbol_id = f"cli.{root_command}.{cmd.name}"
        signature = f"{root_command} {cmd.name}"

        return {
            "symbol_id": symbol_id,
            "symbol_type": "cli_command",
            "parent_scope": parent_scope,
            "signature": signature,
            "return_type": "int",  # Exit code
            "docstring_raw": cmd.help or "",
            "source_file": "cli_spec",
            "is_destructive": any(kw in cmd.name.lower() for kw in ["delete", "remove", "drop", "destroy", "purge"]),
            "parameters": params,
            "examples": [],
            "error_codes": [],
        }

    def _parse_help_text(self, help_text: str, root_command: str) -> list[dict[str, Any]]:
        """Parse CLI --help text output into symbols (fallback parser)."""
        symbols = []
        lines = help_text.split("\n")

        # Find the Commands section
        in_commands = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.lower().startswith("commands:"):
                in_commands = True
                continue

            if in_commands:
                # Parse command lines: "  create     Create a new resource"
                match = re.match(r"^(\w+)\s+(.+)$", stripped)
                if match:
                    cmd_name = match.group(1)
                    cmd_desc = match.group(2)
                    symbols.append(self._build_cli_symbol_from_name(cmd_name, cmd_desc, root_command))

        return symbols

    def _build_cli_symbol_from_name(self, cmd_name: str, description: str, root_command: str) -> dict[str, Any]:
        """Build a CLI symbol from command name and description."""
        params = []

        return {
            "symbol_id": f"cli.{root_command}.{cmd_name}",
            "symbol_type": "cli_command",
            "parent_scope": root_command,
            "signature": f"{root_command} {cmd_name}",
            "return_type": "int",
            "docstring_raw": description,
            "source_file": "cli_help",
            "is_destructive": any(kw in cmd_name.lower() for kw in ["delete", "remove", "drop", "destroy", "purge"]),
            "parameters": params,
            "examples": [],
            "error_codes": [],
        }

    async def extract_and_ingest_cli_spec(
        self,
        command_name: str,
        help_text: str,
        db_path: Path,
    ) -> int:
        """Extract CLI symbols from help text and ingest into docs.db."""
        symbols = self._parse_help_text(help_text, command_name)

        total_ingested = 0
        async with get_docs_db(db_path, read_only=False) as db:
            for symbol in symbols:
                symbol_data = {k: v for k, v in symbol.items() if k not in ("parameters", "examples", "error_codes")}
                params = symbol.get("parameters", [])
                examples = symbol.get("examples", [])
                errors = symbol.get("error_codes", [])

                await insert_symbol_bundle(db, symbol_data, params, examples, errors)
                total_ingested += 1

        return total_ingested


# Convenience functions
async def extract_and_ingest_openapi(
    spec_path: Path,
    db_path: Path,
) -> int:
    """Convenience function to extract and ingest OpenAPI spec."""
    extractor = OpenAPIExtractor()
    return await extractor.extract_and_ingest_openapi(spec_path, db_path)


async def extract_and_ingest_cli_spec(
    command_name: str,
    help_text: str,
    db_path: Path,
) -> int:
    """Convenience function to extract and ingest CLI spec."""
    extractor = CLIExtractor()
    return await extractor.extract_and_ingest_cli_spec(command_name, help_text, db_path)
