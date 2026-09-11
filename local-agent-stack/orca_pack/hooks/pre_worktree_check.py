"""Pre-worktree check hook.

Validates that the repository is a clean git repository before creating worktrees.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)


class NotGitRepositoryError(Exception):
    """Raised when the path is not a git repository."""
    pass


class DirtyRepositoryError(Exception):
    """Raised when the repository has uncommitted changes."""
    pass


def check_repo_status(repo_path: Path) -> None:
    """Check that the repository is a valid git repo and warn about uncommitted changes.

    Args:
        repo_path: Path to the git repository.

    Raises:
        NotGitRepositoryError: If the path is not a git repository.
        DirtyRepositoryError: If the repository has uncommitted changes on the root branch.
    """
    # Check if it's a git repo
    try:
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        raise NotGitRepositoryError(f"{repo_path} is not a git repository")

    # Check for uncommitted changes
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    if result.stdout.strip():
        logger.warning(
            "Repository has uncommitted changes. Consider committing or stashing before creating worktrees."
        )
        # List the changes for visibility
        for line in result.stdout.strip().split("\n"):
            logger.warning(f"  {line}")


__all__ = ["check_repo_status", "NotGitRepositoryError", "DirtyRepositoryError"]
