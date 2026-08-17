"""
Adapters Package

Provides pluggable harness adapters for diverse agent execution engines
and a factory function for instantiating the appropriate adapter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adapters.base import HarnessAdapter


def get_adapter(
    agent_config: dict[str, Any],
    workspace_dir: Path,
) -> HarnessAdapter:
    """
    Factory function to instantiate the appropriate harness adapter.

    Inspects agent_config["harness_type"] and returns the corresponding
    adapter instance.

    Args:
        agent_config: Agent configuration dictionary containing at minimum:
            - harness_type: One of "pi", "hermes", "opencode", "generic_cli", "claude-code"
            - agent_id: Unique identifier for the agent
            - harness_binary: Optional path to the harness binary
            - Other harness-specific configuration
        workspace_dir: Base workspace directory for agent operations.

    Returns:
        Instance of the appropriate HarnessAdapter subclass.

    Raises:
        ValueError: If harness_type is unknown or not supported.
    """
    harness_type = agent_config.get("harness_type", "generic_cli")

    # Lazy imports to avoid circular dependencies
    if harness_type == "pi":
        from adapters.pi_adapter import PiAdapter
        return PiAdapter(agent_config, workspace_dir)

    elif harness_type == "hermes":
        from adapters.hermes_adapter import HermesAdapter
        return HermesAdapter(agent_config, workspace_dir)

    elif harness_type == "opencode":
        from adapters.opencode_adapter import OpenCodeAdapter
        return OpenCodeAdapter(agent_config, workspace_dir)

    elif harness_type == "generic_cli":
        from adapters.generic_cli_adapter import GenericCLIAdapter
        return GenericCLIAdapter(agent_config, workspace_dir)

    elif harness_type == "claude-code":
        # Claude Code uses the generic CLI adapter with specific binary
        from adapters.generic_cli_adapter import GenericCLIAdapter
        # Override binary to claude-code
        config = dict(agent_config)
        config["harness_binary"] = config.get("harness_binary", "claude-code")
        return GenericCLIAdapter(config, workspace_dir)

    else:
        raise ValueError(f"Unknown harness_type: {harness_type}. "
                         f"Supported types: pi, hermes, opencode, generic_cli, claude-code")


# Re-export base types for convenience
from adapters.base import (
    AgentExecutionContext,
    ExecutionEvent,
    HarnessAdapter,
    TurnResult,
)

__all__ = [
    "get_adapter",
    "AgentExecutionContext",
    "ExecutionEvent",
    "HarnessAdapter",
    "TurnResult",
]
