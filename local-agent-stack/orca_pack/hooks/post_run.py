"""Post-run hook for diff generation, scratch.db recording, and HITL escalation.

Runs after each agent node execution to record execution telemetry and handle failures.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from agent_forge.db.scratch import get_scratch_db, init_scratch_db, log_execution_turn, record_artifact as db_record_artifact


logger = logging.getLogger(__name__)


def generate_diff_summary(worktree_path: Path) -> Dict[str, Any]:
    """Generate a structured diff summary of changes in the worktree.

    Includes both staged and unstaged changes.

    Args:
        worktree_path: Path to the git worktree.

    Returns:
        Dictionary with diff statistics and content.
    """
    # Get diff stat for all changes (staged + unstaged)
    stat_result = subprocess.run(
        ["git", "diff", "--stat", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    stat = stat_result.stdout.strip()

    # Get full diff for all changes (staged + unstaged)
    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    diff = diff_result.stdout.strip()

    # Count files changed
    files_changed = 0
    if stat:
        # Parse "X files changed, Y insertions(+), Z deletions(-)"
        for line in stat.split("\n"):
            if "file" in line and "changed" in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part.isdigit():
                        files_changed = int(part)
                        break

    return {
        "stat": stat,
        "diff": diff,
        "files_changed": files_changed,
    }


async def record_execution(
    scratch_db_path: Path,
    session_id: str,
    workflow_run_id: str,
    step_number: int,
    tool_called: str,
    tool_input: Dict[str, Any],
    tool_output: Dict[str, Any],
    status: str,
    execution_time_ms: int,
) -> int:
    """Record an execution turn to scratch.db.

    Args:
        scratch_db_path: Path to scratch.db.
        session_id: Unique session identifier.
        workflow_run_id: Workflow run identifier.
        step_number: Step number in the workflow.
        tool_called: Name of the tool called.
        tool_input: Tool input parameters.
        tool_output: Tool output/result.
        status: Execution status (success, error, retry).
        execution_time_ms: Execution time in milliseconds.

    Returns:
        The turn_id of the recorded execution.
    """
    # Initialize database if needed
    await init_scratch_db(scratch_db_path)

    async with get_scratch_db(scratch_db_path) as db:
        turn_id = await log_execution_turn(
            db=db,
            session_id=session_id,
            step_number=step_number,
            tool_called=tool_called,
            tool_input=tool_input,
            tool_output=tool_output,
            status=status,
            execution_time_ms=execution_time_ms,
            workflow_run_id=workflow_run_id,
        )
    logger.debug(f"Recorded execution turn {turn_id} for session {session_id}")
    return turn_id


async def record_artifact(
    scratch_db_path: Path,
    artifact_id: str,
    session_id: str,
    artifact_type: str,
    content_raw: str,
    file_path: Optional[str] = None,
    workflow_run_id: Optional[str] = None,
) -> str:
    """Record an artifact to scratch.db with SHA256 checksum.

    Args:
        scratch_db_path: Path to scratch.db.
        artifact_id: Unique artifact identifier.
        session_id: Session identifier.
        artifact_type: Type of artifact (e.g., generated_code, test_file).
        content_raw: Raw content of the artifact.
        file_path: Optional file path associated with artifact.
        workflow_run_id: Optional workflow run identifier.

    Returns:
        SHA256 checksum of the artifact content.
    """
    # Initialize database if needed
    await init_scratch_db(scratch_db_path)

    async with get_scratch_db(scratch_db_path) as db:
        sha256 = await db_record_artifact(
            db=db,
            artifact_id=artifact_id,
            session_id=session_id,
            artifact_type=artifact_type,
            content_raw=content_raw,
            file_path=file_path,
            workflow_run_id=workflow_run_id,
        )
    logger.debug(f"Recorded artifact {artifact_id} with checksum {sha256[:16]}...")
    return sha256


async def trigger_hitl_snapshot(reason: str, worktree_path: Path) -> bool:
    """Trigger an Orca HITL snapshot with the given reason.

    Args:
        reason: Reason for the HITL snapshot.
        worktree_path: Path to the worktree (for context).

    Returns:
        True if snapshot was triggered successfully, False otherwise.
    """
    try:
        cmd = ["orca", "snapshot", "--message", reason]
        result = subprocess.run(
            cmd,
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info(f"HITL snapshot triggered: {reason}")
            return True
        else:
            logger.error(f"Orca snapshot failed: {result.stderr}")
            return False
    except FileNotFoundError:
        logger.error("Orca CLI not found, cannot trigger HITL snapshot")
        return False
    except subprocess.TimeoutExpired:
        logger.error("Orca snapshot timed out")
        return False
    except Exception as e:
        logger.error(f"Failed to trigger HITL snapshot: {e}")
        return False


async def main(
    worktree_path: Path,
    scratch_db_path: Path,
    session_id: str,
    workflow_run_id: str,
    step_number: int,
    tool_called: str,
    tool_input: Dict[str, Any],
    tool_output: Dict[str, Any],
    status: str,
    execution_time_ms: int,
    gatekeeper_exhausted: bool = False,
    gatekeeper_failure_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Main entry point for post-run hook.

    Args:
        worktree_path: Path to the git worktree.
        scratch_db_path: Path to scratch.db.
        session_id: Session identifier.
        workflow_run_id: Workflow run identifier.
        step_number: Step number.
        tool_called: Tool that was called.
        tool_input: Tool input.
        tool_output: Tool output.
        status: Execution status.
        execution_time_ms: Execution time in milliseconds.
        gatekeeper_exhausted: Whether gatekeeper remediation cycles are exhausted.
        gatekeeper_failure_reason: Reason for gatekeeper failure (if exhausted).

    Returns:
        Dictionary with results of post-run operations.
    """
    result = {
        "diff_recorded": False,
        "turn_recorded": False,
        "artifact_recorded": False,
        "hitl_triggered": False,
    }

    # Generate and log diff summary
    diff_summary = generate_diff_summary(worktree_path)
    # Always record diff if there are any changes (including staged)
    if diff_summary["files_changed"] > 0 or diff_summary["diff"]:
        logger.info(f"Worktree diff: {diff_summary['stat'] or 'No stat output'}")
        result["diff_recorded"] = True

    # Record execution turn
    try:
        await record_execution(
            scratch_db_path=scratch_db_path,
            session_id=session_id,
            workflow_run_id=workflow_run_id,
            step_number=step_number,
            tool_called=tool_called,
            tool_input=tool_input,
            tool_output=tool_output,
            status=status,
            execution_time_ms=execution_time_ms,
        )
        result["turn_recorded"] = True
    except Exception as e:
        logger.error(f"Failed to record execution turn: {e}")

    # If gatekeeper exhausted, trigger HITL
    if gatekeeper_exhausted:
        reason = gatekeeper_failure_reason or "Gatekeeper failed after remediation attempts"
        hitl_result = await trigger_hitl_snapshot(reason, worktree_path)
        result["hitl_triggered"] = hitl_result

    return result
