"""Orca Pack - Local Agent Stack Orca ADE Integration.

Provides workspace manifest generation, worktree lifecycle hooks,
and TDD multi-agent workflow orchestration.
"""

from __future__ import annotations

from orca_pack.generator import generate_orca_manifest, OrcaManifestGenerator
from orca_pack.template_utils import load_template, render_template
from orca_pack.workflows import (
    TDDWorkflowRunner,
    TestAuthorResult,
    BuilderResult,
    GatekeeperResult,
    RemediationPayload,
)

__version__ = "0.1.0"

__all__ = [
    "generate_orca_manifest",
    "OrcaManifestGenerator",
    "load_template",
    "render_template",
    "TDDWorkflowRunner",
    "TestAuthorResult",
    "BuilderResult",
    "GatekeeperResult",
    "RemediationPayload",
]
