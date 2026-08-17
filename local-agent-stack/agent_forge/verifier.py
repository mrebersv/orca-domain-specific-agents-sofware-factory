"""Synthetic Dry-Run Verification Harness for Agent Forge (Task 3.4)."""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path
from typing import Any, Optional
import aiosqlite

from agent_forge.db.scratch import get_scratch_db, init_scratch_db, log_execution_turn, record_artifact
from agent_forge.db.docs import get_docs_db


class AgentVerifier:
    """Runs synthetic dry-run validations on scaffolded agent workspaces."""

    def __init__(self) -> None:
        self.results: dict[str, Any] = {}

    def _validate_config(self, config_path: Path) -> tuple[bool, list[str]]:
        """Validate agent.config.json against required schema."""
        errors = []
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in agent.config.json: {e}")
            return False, errors

        required_fields = [
            "agent_id", "name", "description", "harness_type",
            "model_name", "model_endpoint", "isolation_tier",
            "max_turns", "timeout_seconds", "permissions"
        ]

        for field in required_fields:
            if field not in config:
                errors.append(f"Missing required field: {field}")

        if "permissions" in config:
            perms = config["permissions"]
            if "allowed_tools" not in perms:
                errors.append("permissions.allowed_tools is required")
            if "require_approval_for_destructive" not in perms:
                errors.append("permissions.require_approval_for_destructive is required")

        return len(errors) == 0, errors

    def _check_prompt_budget(self, prompt_path: Path) -> tuple[int, bool, list[str]]:
        """Check prompt.md token count."""
        errors = []
        prompt_text = prompt_path.read_text(encoding="utf-8")
        # Rough estimation: ~4 chars per token
        token_count = len(prompt_text) // 4

        if token_count >= 500:
            errors.append(f"Prompt token count ({token_count}) exceeds 500 token budget")

        return token_count, len(errors) == 0, errors

    def _import_tools_module(self, tools_path: Path) -> tuple[Optional[Any], list[str]]:
        """Dynamically import the tools.py module."""
        errors = []
        try:
            spec = importlib.util.spec_from_file_location("tools", tools_path)
            if spec is None or spec.loader is None:
                errors.append("Failed to create module spec for tools.py")
                return None, errors

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module, errors
        except Exception as e:
            errors.append(f"Failed to import tools.py: {e}")
            return None, errors

    def _get_tool_functions(self, module: Any) -> list[str]:
        """Get list of callable tool functions from module."""
        tools = []
        excluded = {
            "get_db_connection", "Any", "Optional", "Path", "Dict", "List",
            "Tuple", "Set", "Union", "Optional", "json", "aiosqlite",
            "AsyncIterator", "aiosqlite", "re", "hashlib",
        }
        for name in dir(module):
            obj = getattr(module, name)
            if (callable(obj) and 
                not name.startswith("_") and 
                name not in excluded and
                not isinstance(obj, type) and  # Exclude classes
                hasattr(obj, "__module__") and
                obj.__module__ == module.__name__):  # Only functions defined in this module
                tools.append(name)
        return tools

    async def _check_database_integrity(self, db_path: Path) -> tuple[bool, list[str]]:
        """Check docs.db integrity and required tables."""
        errors = []
        try:
            async with get_docs_db(db_path, read_only=True) as db:
                # Check integrity
                async with db.execute("PRAGMA integrity_check;") as cursor:
                    result = await cursor.fetchone()
                    if result and result[0] != "ok":
                        errors.append(f"Database integrity check failed: {result[0]}")

                # Check required tables
                required_tables = ["symbols", "parameters", "examples", "error_codes", "symbols_fts"]
                for table in required_tables:
                    async with db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ) as cursor:
                        if not await cursor.fetchone():
                            errors.append(f"Missing required table: {table}")

        except Exception as e:
            errors.append(f"Database check failed: {e}")
            return False, errors

        return len(errors) == 0, errors

    async def _run_synthetic_tool_calls(
        self,
        tools_module: Any,
        tool_names: list[str],
        scratch_db_path: Path,
        session_id: str,
    ) -> tuple[int, list[str]]:
        """Run synthetic tool calls and log to scratch.db."""
        errors = []
        turns_recorded = 0

        async with get_scratch_db(scratch_db_path) as db:
            for i, tool_name in enumerate(tool_names, 1):
                tool_func = getattr(tools_module, tool_name, None)
                if tool_func is None:
                    errors.append(f"Tool function {tool_name} not found in module")
                    continue

                # Generate synthetic inputs based on tool name
                tool_input = self._generate_synthetic_input(tool_name)

                start_time = time.perf_counter()
                try:
                    # Call the tool with synthetic input
                    if hasattr(tool_func, "__call__"):
                        import inspect
                        if inspect.iscoroutinefunction(tool_func):
                            tool_output = await tool_func(**tool_input)
                        else:
                            tool_output = tool_func(**tool_input)
                    else:
                        tool_output = {"error": "Not callable"}

                    execution_time_ms = int((time.perf_counter() - start_time) * 1000)
                    status = "success"
                except Exception as e:
                    execution_time_ms = int((time.perf_counter() - start_time) * 1000)
                    tool_output = {"error": str(e), "type": type(e).__name__}
                    status = "error"
                    errors.append(f"Tool {tool_name} failed: {e}")

                await log_execution_turn(
                    db=db,
                    session_id=session_id,
                    step_number=i,
                    tool_called=tool_name,
                    tool_input=tool_input,
                    tool_output=tool_output if isinstance(tool_output, dict) else {"result": str(tool_output)},
                    status=status,
                    execution_time_ms=execution_time_ms,
                )
                turns_recorded += 1

        return turns_recorded, errors

    def _generate_synthetic_input(self, tool_name: str) -> dict[str, Any]:
        """Generate synthetic input for a tool based on its name."""
        # Standard tools
        if tool_name == "search_symbols":
            return {"query": "test", "limit": 5}
        elif tool_name == "get_symbol_schema":
            return {"symbol_id": "test.module.function"}
        elif tool_name == "list_all_symbols":
            return {"limit": 10}

        # Generic fallback
        return {"param": "test"}

    async def verify_agent_workspace(self, workspace_dir: Path) -> dict[str, Any]:
        """
        Run complete verification pipeline on agent workspace.

        Args:
            workspace_dir: Path to agent workspace directory

        Returns:
            Verification summary dictionary.
        """
        summary = {
            "agent_id": workspace_dir.name,
            "status": "failed",
            "prompt_tokens_est": 0,
            "tools_tested": [],
            "turns_recorded": 0,
            "errors": [],
        }

        all_errors = []

        # 1. Manifest Validation
        config_path = workspace_dir / "agent.config.json"
        if not config_path.exists():
            all_errors.append("Missing agent.config.json")
        else:
            valid, errors = self._validate_config(config_path)
            all_errors.extend(errors)

        # 2. Prompt Budget Check
        prompt_path = workspace_dir / "prompt.md"
        if not prompt_path.exists():
            all_errors.append("Missing prompt.md")
        else:
            token_count, valid, errors = self._check_prompt_budget(prompt_path)
            summary["prompt_tokens_est"] = token_count
            all_errors.extend(errors)

        # 3. Tool Importability
        tools_path = workspace_dir / "tools.py"
        tools_module = None
        tool_names = []
        if not tools_path.exists():
            all_errors.append("Missing tools.py")
        else:
            tools_module, errors = self._import_tools_module(tools_path)
            all_errors.extend(errors)
            if tools_module is not None:
                tool_names = self._get_tool_functions(tools_module)
                summary["tools_tested"] = tool_names

        # 4. Database Integrity
        docs_db_path = workspace_dir / "docs.db"
        if not docs_db_path.exists():
            all_errors.append("Missing docs.db")
        else:
            valid, errors = await self._check_database_integrity(docs_db_path)
            all_errors.extend(errors)

        # 5. Synthetic Tool Execution
        if tools_module and tool_names:
            scratch_db_path = workspace_dir / "scratch.db"
            await init_scratch_db(scratch_db_path)

            session_id = f"verify_{workspace_dir.name}_{int(time.time())}"
            turns, errors = await self._run_synthetic_tool_calls(
                tools_module, tool_names, scratch_db_path, session_id
            )
            summary["turns_recorded"] = turns
            all_errors.extend(errors)

        # Final status
        summary["errors"] = all_errors
        summary["status"] = "passed" if len(all_errors) == 0 else "failed"

        return summary


async def verify_agent_workspace(workspace_dir: Path) -> dict[str, Any]:
    """Convenience function to verify an agent workspace."""
    verifier = AgentVerifier()
    return await verifier.verify_agent_workspace(workspace_dir)
