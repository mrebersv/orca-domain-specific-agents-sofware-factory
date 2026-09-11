"""Template loading utilities for Orca Pack."""

from __future__ import annotations

import yaml
from pathlib import Path


def load_template() -> dict:
    """Load and parse the Orca workspace template YAML.

    Returns:
        Parsed template as a dictionary.
    """
    template_path = Path(__file__).parent / "orca.template.yaml"
    with open(template_path) as f:
        return yaml.safe_load(f)


__all__ = ["load_template"]
