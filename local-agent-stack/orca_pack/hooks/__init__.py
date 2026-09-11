"""Orca Pack Hooks Package.

Contains lifecycle hooks for Orca ADE worktree management:
- pre_worktree_check: Validates git repository status
- setup_worktree_env: Creates and manages ephemeral git worktrees
- pre_run: Verifies VRAM proxy health and injects secrets
- post_run: Records metrics, generates diffs, triggers HITL
"""

from orca_pack.hooks.pre_worktree_check import (
    check_repo_status,
    NotGitRepositoryError,
    DirtyRepositoryError,
)

from orca_pack.hooks.setup_worktree_env import (
    create_ephemeral_worktree,
    cleanup_worktree,
    WorktreeError,
)

from orca_pack.hooks.pre_run import (
    check_proxy_health,
    inject_secrets,
)

from orca_pack.hooks.post_run import (
    generate_diff_summary,
    record_execution,
    record_artifact,
    trigger_hitl_snapshot,
    main as post_run_main,
)

__all__ = [
    # pre_worktree_check
    "check_repo_status",
    "NotGitRepositoryError",
    "DirtyRepositoryError",
    # setup_worktree_env
    "create_ephemeral_worktree",
    "cleanup_worktree",
    "WorktreeError",
    # pre_run
    "check_proxy_health",
    "inject_secrets",
    # post_run
    "generate_diff_summary",
    "record_execution",
    "record_artifact",
    "trigger_hitl_snapshot",
    "post_run_main",
]
