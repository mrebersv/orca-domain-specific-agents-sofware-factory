"""Worktree environment setup hook.

Creates ephemeral git worktrees with copied .env and .agent/docs.db for isolated task execution.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)


class WorktreeError(Exception):
    """Raised when worktree operations fail."""
    pass


def _sanitize_branch_name(branch_name: str) -> str:
    """Sanitize branch name for use as directory name."""
    return branch_name.replace("/", "-").replace(" ", "-")


# Files/directories that are allowed to be untracked (managed by this hook)
_ALLOWED_UNTRACKED = {
    ".env",
    ".agent",
}


def _has_uncommitted_changes(repo_path: Path) -> bool:
    """Check if repository has uncommitted changes.

    Allows untracked .env and .agent/ files since they are managed by this hook.

    Args:
        repo_path: Path to the git repository.

    Returns:
        True if there are uncommitted changes that should block worktree creation.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        # Git status format: XY PATH
        # X = index status, Y = worktree status
        # '??' = untracked
        status = line[:2]
        path = line[3:] if len(line) > 3 else ""

        if status == "??":
            # Untracked file - check if it's allowed
            # Normalize: remove leading ./ and trailing /
            normalized_path = path
            if normalized_path.startswith("./"):
                normalized_path = normalized_path[2:]
            if normalized_path.endswith("/"):
                normalized_path = normalized_path[:-1]
            if normalized_path not in _ALLOWED_UNTRACKED:
                return True
        else:
            # Tracked file with changes
            return True
    return False


def create_ephemeral_worktree(
    repo_path: Path,
    branch_name: str,
    force: bool = False,
) -> Path:
    """Create an ephemeral git worktree for a task.

    Args:
        repo_path: Path to the main git repository.
        branch_name: Name of the branch/task (e.g., "task-6.1").
        force: If True, allow creating worktree even with uncommitted changes.

    Returns:
        Path to the created worktree directory.

    Raises:
        WorktreeError: If worktree creation fails.
    """
    # Check for uncommitted changes unless forced
    if not force:
        if _has_uncommitted_changes(repo_path):
            raise WorktreeError(
                "Repository has uncommitted changes. Use force=True to override."
            )

    # Sanitize branch name for directory name
    worktree_dir_name = _sanitize_branch_name(branch_name)
    worktree_path = repo_path / ".worktrees" / worktree_dir_name

    # Ensure .worktrees directory exists
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    # Determine the branch name to use in the worktree
    # For new branches, use sanitized name to match test expectation
    branch_exists_result = subprocess.run(
        ["git", "branch", "--list", branch_name],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    branch_exists = branch_name in branch_exists_result.stdout

    # Create worktree
    try:
        if branch_exists:
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), branch_name],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
        else:
            # Create new branch with sanitized name from current HEAD
            sanitized_branch = _sanitize_branch_name(branch_name)
            subprocess.run(
                ["git", "worktree", "add", "-b", sanitized_branch, str(worktree_path)],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        raise WorktreeError(f"Failed to create worktree: {stderr}")

    # Copy .env file if it exists
    env_src = repo_path / ".env"
    env_dst = worktree_path / ".env"
    if env_src.exists():
        shutil.copy2(env_src, env_dst)
        logger.debug(f"Copied .env to worktree: {env_dst}")

    # Copy .agent/docs.db if it exists
    agent_src = repo_path / ".agent" / "docs.db"
    agent_dst_dir = worktree_path / ".agent"
    agent_dst = agent_dst_dir / "docs.db"
    if agent_src.exists():
        agent_dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(agent_src, agent_dst)
        logger.debug(f"Copied docs.db to worktree: {agent_dst}")

    logger.info(f"Created worktree at {worktree_path} for branch {branch_name}")
    return worktree_path


def cleanup_worktree(
    repo_path: Path,
    branch_name: str,
    delete_branch: bool = False,
) -> None:
    """Clean up an ephemeral worktree.

    Args:
        repo_path: Path to the main git repository.
        branch_name: Name of the branch/task.
        delete_branch: If True, also delete the branch after removing worktree.
    """
    worktree_dir_name = _sanitize_branch_name(branch_name)
    worktree_path = repo_path / ".worktrees" / worktree_dir_name

    if worktree_path.exists():
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            logger.info(f"Removed worktree: {worktree_path}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to remove worktree {worktree_path}: {e}")

    # Optionally delete the branch (use sanitized name)
    if delete_branch:
        sanitized_branch = _sanitize_branch_name(branch_name)
        try:
            subprocess.run(
                ["git", "branch", "-D", sanitized_branch],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            logger.info(f"Deleted branch: {sanitized_branch}")
        except subprocess.CalledProcessError:
            logger.warning(f"Failed to delete branch {sanitized_branch} (may not exist)")
