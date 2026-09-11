"""Orca workspace template loading utilities."""

from __future__ import annotations

from pathlib import Path
import yaml


def load_template() -> dict:
    """Load the Orca workspace YAML template from the package templates directory.

    Returns:
        Parsed YAML template as a dictionary.
    """
    template_path = Path(__file__).parent / "templates" / "orca.template.yaml"
    with open(template_path, "r") as f:
        return yaml.safe_load(f)


def render_template(
    template: dict,
    local_model_name: str = "qwen2.5-coder-7b",
    enable_cloud_fallback: bool = True,
) -> dict:
    """Render the template with provided values.

    Args:
        template: The loaded template dictionary.
        local_model_name: Name of the local SLM model to use.
        enable_cloud_fallback: Whether to include the cloud fallback model.

    Returns:
        Rendered template dictionary with placeholders substituted.
    """
    import copy
    rendered = copy.deepcopy(template)

    # Substitute local model name
    rendered["models"]["local-slm"]["model"] = local_model_name

    # Handle cloud fallback
    if not enable_cloud_fallback:
        rendered["models"].pop("cloud-fallback", None)

    return rendered
