"""Unit tests verifying packaging metadata, install script syntax, and CLI utilities."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import pytest


def test_install_script_syntax():
    install_script = Path("install.sh")
    assert install_script.exists(), "install.sh must exist in repository root"

    res = subprocess.run(["bash", "-n", str(install_script)], capture_output=True, text=True)
    assert res.returncode == 0, f"install.sh syntax error: {res.stderr}"


def test_package_modules_importable():
    # Verify core Phase 1 modules import cleanly in runtime environment
    import agent_forge.db.docs
    import agent_forge.db.registry
    import agent_forge.db.scratch

    assert hasattr(agent_forge.db.registry, "init_registry_db")
    assert hasattr(agent_forge.db.docs, "init_docs_db")
    assert hasattr(agent_forge.db.scratch, "init_scratch_db")


def test_init_scripts_cli_execution(tmp_path: Path):
    reg_db = tmp_path / "test_reg.db"
    docs_db = tmp_path / "test_docs.db"

    # Test scripts/init_registry_db.py
    res1 = subprocess.run(
        [sys.executable, "scripts/init_registry_db.py", "--db-path", str(reg_db)],
        capture_output=True,
        text=True,
    )
    assert res1.returncode == 0, f"init_registry_db.py failed: {res1.stderr}"
    assert reg_db.exists()

    # Test scripts/init_docs_db.py
    res2 = subprocess.run(
        [sys.executable, "scripts/init_docs_db.py", "--db-path", str(docs_db)],
        capture_output=True,
        text=True,
    )
    assert res2.returncode == 0, f"init_docs_db.py failed: {res2.stderr}"
    assert docs_db.exists()
