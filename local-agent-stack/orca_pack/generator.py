"""Orca Workspace Manifest Generator.

This module provides functionality to generate a production-ready
.orca/workspace.yaml configuration in target repositories.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from string import Template
from typing import Any

import yaml

from orca_pack.templates import load_template


class OrcaManifestGenerator:
    """Generates Orca workspace manifests from templates."""

    DEFAULT_MODEL_NAME = "qwen2.5-coder-7b"

    def __init__(self) -> None:
        """Initialize the generator with the default template."""
        self._template = load_template()

    def generate(
        self,
        project_root: Path,
        local_model_name: str = DEFAULT_MODEL_NAME,
        enable_cloud_fallback: bool = True,
        force_overwrite: bool = False,
    ) -> Path:
        """Render and write .orca/workspace.yaml in project_root.

        Args:
            project_root: Root directory of the target project.
            local_model_name: Name of the local SLM model to use.
            enable_cloud_fallback: Whether to include cloud fallback model.
            force_overwrite: Whether to overwrite existing manifest.

        Returns:
            Path to the generated workspace.yaml file.

        Raises:
            FileExistsError: If manifest exists and force_overwrite is False.
            yaml.YAMLError: If rendered YAML is invalid.
        """
        project_root = Path(project_root).resolve()
        orca_dir = project_root / ".orca"
        output_path = orca_dir / "workspace.yaml"

        # Check for existing manifest
        if output_path.exists() and not force_overwrite:
            raise FileExistsError(
                f"Manifest already exists at {output_path}. "
                "Use force_overwrite=True to overwrite."
            )

        # Create .orca directory if missing
        orca_dir.mkdir(parents=True, exist_ok=True)

        # Prepare template variables
        template_vars = {
            "local_model_name": local_model_name,
            "workspace_root": "${WORKSPACE_ROOT}",
            "anthropic_api_key": "${ANTHROPIC_API_KEY}",
        }

        # Deep copy template to avoid mutating the cached template
        import copy
        manifest = copy.deepcopy(self._template)

        # Substitute local model name
        manifest["models"]["local-slm"]["model"] = local_model_name

        # Handle cloud fallback
        if not enable_cloud_fallback:
            manifest["models"].pop("cloud-fallback", None)

        # Validate YAML syntax by dumping and loading
        yaml_str = yaml.dump(manifest, sort_keys=False, default_flow_style=False)
        try:
            # This validates the YAML structure
            yaml.safe_load(yaml_str)
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Generated manifest is invalid YAML: {e}") from e

        # Write the manifest
        output_path.write_text(yaml_str)

        return output_path


def generate_orca_manifest(
    project_root: Path,
    local_model_name: str = "qwen2.5-coder-7b",
    enable_cloud_fallback: bool = True,
    force_overwrite: bool = False,
) -> Path:
    """Render and write .orca/workspace.yaml in project_root.

    This is a convenience function that creates an OrcaManifestGenerator
    instance and calls its generate method.

    Args:
        project_root: Root directory of the target project.
        local_model_name: Name of the local SLM model to use.
        enable_cloud_fallback: Whether to include cloud fallback model.
        force_overwrite: Whether to overwrite existing manifest.

    Returns:
        Path to the generated workspace.yaml file.

    Raises:
        FileExistsError: If manifest exists and force_overwrite is False.
        yaml.YAMLError: If rendered YAML is invalid.
    """
    generator = OrcaManifestGenerator()
    return generator.generate(
        project_root=project_root,
        local_model_name=local_model_name,
        enable_cloud_fallback=enable_cloud_fallback,
        force_overwrite=force_overwrite,
    )


__all__ = ["OrcaManifestGenerator", "generate_orca_manifest"]
