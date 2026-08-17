"""Workspace Scaffolder for Agent Forge (Task 3.3)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape

from agent_forge.db.docs import get_docs_db, query_symbols_fts
from agent_forge.db.registry import get_registry_db, register_agent


class AgentScaffolder:
    """Generates isolated agent workspaces from docs.db."""

    def __init__(self, templates_dir: Optional[Path] = None) -> None:
        if templates_dir is None:
            templates_dir = Path(__file__).parent / "templates"
        self.templates_dir = templates_dir
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (~4 chars per token)."""
        return len(text) // 4

    def _get_available_tools(self, db_path: Path) -> list[dict[str, Any]]:
        """Get list of available tool symbols from docs.db."""
        # For now, return the standard tools
        return [
            {"name": "search_symbols", "description": "Search symbols using FTS5 full-text search"},
            {"name": "get_symbol_schema", "description": "Get complete schema for a symbol including parameters, examples, and error codes"},
            {"name": "list_all_symbols", "description": "List symbols with optional filtering by type and scope"},
        ]

    def _get_custom_tools(self, db_path: Path) -> list[dict[str, Any]]:
        """Get custom domain-specific tools from docs.db."""
        # This would extract domain-specific functions from the database
        # For now, return empty list - can be extended
        return []

    async def _get_domain_info(self, db_path: Path) -> dict[str, Any]:
        """Extract domain information from docs.db."""
        async with get_docs_db(db_path, read_only=True) as db:
            # Get unique parent scopes
            async with db.execute("SELECT DISTINCT parent_scope FROM symbols WHERE parent_scope IS NOT NULL") as cursor:
                scopes = [row[0] for row in await cursor.fetchall()]

            # Get symbol types
            async with db.execute("SELECT DISTINCT symbol_type FROM symbols") as cursor:
                types = [row[0] for row in await cursor.fetchall()]

            # Determine domain scope from most common parent scope
            domain_scope = scopes[0] if scopes else "general"

            return {
                "domain_scope": domain_scope,
                "available_scopes": scopes,
                "symbol_types": types,
            }

    def _render_prompt(
        self,
        agent_id: str,
        name: str,
        description: str,
        domain_scope: str,
        tools: list[dict[str, Any]],
    ) -> str:
        """Render the prompt.md template."""
        template = self.env.get_template("prompt.template.md")
        # Use a short description for the prompt to stay under token budget
        short_desc = description[:200] if len(description) > 200 else description
        return template.render(
            agent_id=agent_id,
            name=name,
            description=short_desc,
            domain_scope=domain_scope,
            tools=tools,
        )

    def _render_tools(
        self,
        agent_id: str,
        name: str,
        custom_tools: list[dict[str, Any]],
    ) -> str:
        """Render the tools.py template."""
        template = self.env.get_template("tools.template.py")
        return template.render(
            agent_id=agent_id,
            name=name,
            custom_tools=custom_tools,
        )

    def _render_config(
        self,
        agent_id: str,
        name: str,
        description: str,
        harness_type: str,
        model_name: str,
        model_endpoint: str,
    ) -> str:
        """Render the agent.config.json template."""
        template = self.env.get_template("agent.config.template.json")
        return template.render(
            agent_id=agent_id,
            name=name,
            description=description,
            harness_type=harness_type,
            model_name=model_name,
            model_endpoint=model_endpoint,
        )

    def _validate_prompt_budget(self, prompt_md: str) -> None:
        """Validate that prompt is under 500 tokens."""
        token_count = self._estimate_tokens(prompt_md)
        if token_count >= 500:
            raise ValueError(
                f"Prompt token count ({token_count}) exceeds 500 token budget. "
                f"Prompt must be under 500 tokens."
            )

    async def scaffold_agent(
        self,
        agent_id: str,
        name: str,
        description: str,
        db_path: Path,
        output_dir: Path,
        harness_type: str = "generic_cli",
        model_name: str = "local-slm",
        model_endpoint: str = "http://127.0.0.1:8000/v1",
        register_in_registry: bool = True,
        registry_db_path: Optional[Path] = None,
    ) -> Path:
        """
        Scaffold a complete agent workspace.

        Args:
            agent_id: Unique identifier for the agent
            name: Human-readable agent name
            description: Agent description
            db_path: Path to docs.db with extracted symbols
            output_dir: Base directory for agent workspace
            harness_type: Type of harness (generic_cli, etc.)
            model_name: Model name for the agent
            model_endpoint: Model endpoint URL
            register_in_registry: Whether to register in registry.db
            registry_db_path: Optional custom registry.db path

        Returns:
            Path to the created agent workspace directory.
        """
        # Create agent workspace directory
        agent_dir = output_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Get domain info from docs.db
        domain_info = await self._get_domain_info(db_path)

        # Get available tools
        standard_tools = self._get_available_tools(db_path)
        custom_tools = self._get_custom_tools(db_path)
        all_tools = standard_tools + custom_tools

        # Render prompt.md
        prompt_md = self._render_prompt(
            agent_id=agent_id,
            name=name,
            description=description,
            domain_scope=domain_info["domain_scope"],
            tools=all_tools,
        )

        # Validate token budget
        self._validate_prompt_budget(prompt_md)

        # Write prompt.md
        (agent_dir / "prompt.md").write_text(prompt_md, encoding="utf-8")

        # Render and write tools.py
        tools_py = self._render_tools(
            agent_id=agent_id,
            name=name,
            custom_tools=custom_tools,
        )
        (agent_dir / "tools.py").write_text(tools_py, encoding="utf-8")

        # Render and write agent.config.json
        config_json = self._render_config(
            agent_id=agent_id,
            name=name,
            description=description,
            harness_type=harness_type,
            model_name=model_name,
            model_endpoint=model_endpoint,
        )
        (agent_dir / "agent.config.json").write_text(config_json, encoding="utf-8")

        # Copy/symlink docs.db to workspace
        target_db = agent_dir / "docs.db"
        if target_db.exists() or target_db.is_symlink():
            target_db.unlink()
        shutil.copy2(db_path, target_db)

        # Register in registry.db if requested
        if register_in_registry:
            async with get_registry_db(registry_db_path) as db:
                await register_agent(db, {
                    "agent_id": agent_id,
                    "name": name,
                    "description": description,
                    "harness_type": harness_type,
                    "model_name": model_name,
                    "model_endpoint": model_endpoint,
                    "isolation_tier": "subprocess",
                    "max_turns": 6,
                    "timeout_seconds": 60,
                    "is_active": True,
                    "permissions": {
                        "allowed_tools": ["search_symbols", "get_symbol_schema", "list_all_symbols"],
                        "require_approval_for_destructive": True,
                    },
                })

        return agent_dir


# Convenience function
async def scaffold_agent(
    agent_id: str,
    name: str,
    description: str,
    db_path: Path,
    output_dir: Path,
    harness_type: str = "generic_cli",
    model_name: str = "local-slm",
    model_endpoint: str = "http://127.0.0.1:8000/v1",
    register_in_registry: bool = False,
    registry_db_path: Optional[Path] = None,
) -> Path:
    """Convenience function to scaffold an agent."""
    scaffolder = AgentScaffolder()
    return await scaffolder.scaffold_agent(
        agent_id=agent_id,
        name=name,
        description=description,
        db_path=db_path,
        output_dir=output_dir,
        harness_type=harness_type,
        model_name=model_name,
        model_endpoint=model_endpoint,
        register_in_registry=register_in_registry,
        registry_db_path=registry_db_path,
    )
