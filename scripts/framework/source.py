"""Source-control provenance helpers for experiment manifests.

This module records a small, content-free Git state summary for build and
flash operations. It performs no network access and supports injected command
runners so unit tests can cover Git states without invoking Git.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable


@dataclass(frozen=True)
class GitCommandExecution:
    """Captured output from one Git command invocation."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


GitRunner = Callable[[list[str], Path], GitCommandExecution]


def default_git_runner(command: list[str], cwd: Path) -> GitCommandExecution:
    """Run a Git command locally and capture output without requiring a network."""

    start = perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return GitCommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=perf_counter() - start,
    )


def _unavailable_source() -> dict[str, object]:
    """Return the explicit manifest shape used when Git state is unavailable."""

    return {
        "git_commit": None,
        "git_dirty": None,
        "git_status_available": False,
    }


def capture_git_provenance(
    repo_root: Path | str,
    runner: GitRunner = default_git_runner,
) -> dict[str, object]:
    """Capture content-free Git provenance for the repository.

    The returned dictionary is intended for manifest ``source`` metadata. It
    includes the current commit hash, whether ``git status --short`` reports a
    dirty working tree, and whether status information was available.

    Git failures, missing Git executables, and non-Git directories are reported
    as an explicit unavailable state rather than raising during normal
    framework operation.
    """

    repo_root_path = Path(repo_root)

    try:
        commit_execution = runner(["git", "rev-parse", "HEAD"], repo_root_path)
    except (FileNotFoundError, OSError):
        return _unavailable_source()

    if commit_execution.return_code != 0:
        return _unavailable_source()

    git_commit = commit_execution.stdout.strip().splitlines()[0] if commit_execution.stdout.strip() else None

    try:
        status_execution = runner(["git", "status", "--short"], repo_root_path)
    except (FileNotFoundError, OSError):
        return {
            "git_commit": git_commit,
            "git_dirty": None,
            "git_status_available": False,
        }

    if status_execution.return_code != 0:
        return {
            "git_commit": git_commit,
            "git_dirty": None,
            "git_status_available": False,
        }

    return {
        "git_commit": git_commit,
        "git_dirty": bool(status_execution.stdout.strip()),
        "git_status_available": True,
    }
