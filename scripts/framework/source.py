"""Source-control provenance helpers for experiment manifests.

This module records a small, content-free Git state summary for build and
flash operations. It performs no network access and supports injected command
runners so unit tests can cover Git states without invoking Git.
"""

from __future__ import annotations

import subprocess
import sys
import hashlib
import os
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
        "git_branch": None,
        "git_dirty": None,
        "git_status_available": False,
        "source_state_sha256": None,
    }


def _source_state_fingerprint(repo_root: Path, runner: GitRunner) -> str | None:
    """Hash tracked diff plus untracked file content without retaining source text."""

    try:
        diff = runner(["git", "diff", "--binary", "HEAD"], repo_root)
        untracked = runner(["git", "ls-files", "--others", "--exclude-standard", "-z"], repo_root)
    except (FileNotFoundError, OSError):
        return None
    if diff.return_code != 0 or untracked.return_code != 0:
        return None
    digest = hashlib.sha256()
    digest.update(diff.stdout.encode("utf-8", errors="surrogateescape"))
    for name in sorted(value for value in untracked.stdout.split("\0") if value):
        digest.update(name.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        path = repo_root / name
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return None
    return digest.hexdigest()


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

    # Determine dirty state before doing the more expensive source-state hash.
    # A clean checkout is already identified exactly by its commit; the extra
    # fingerprint is only needed to distinguish dirty source states.
    try:
        status_execution = runner(["git", "status", "--short"], repo_root_path)
    except (FileNotFoundError, OSError):
        status_execution = None

    try:
        branch_execution = runner(["git", "branch", "--show-current"], repo_root_path)
        git_branch = (branch_execution.stdout.strip() or None) if branch_execution.return_code == 0 else None
    except (FileNotFoundError, OSError):
        git_branch = None

    if status_execution is None or status_execution.return_code != 0:
        return {
            "git_commit": git_commit,
            "git_branch": git_branch,
            "git_dirty": None,
            "git_status_available": False,
            "source_state_sha256": None,
        }

    git_dirty = bool(status_execution.stdout.strip())
    source_state_sha256 = _source_state_fingerprint(repo_root_path, runner) if git_dirty else None
    return {
        "git_commit": git_commit,
        "git_branch": git_branch,
        "git_dirty": git_dirty,
        "git_status_available": True,
        "source_state_sha256": source_state_sha256,
    }


_TOOL_COMMANDS: tuple[tuple[str, list[str]], ...] = (
    ("compiler", ["arm-none-eabi-gcc", "--version"]),
    ("cmake", ["cmake", "--version"]),
    ("ninja", ["ninja", "--version"]),
    ("python", [sys.executable, "--version"]),
    ("openssl", ["openssl", "version"]),
)


def _first_nonempty_line(stdout: str, stderr: str) -> str | None:
    for stream in (stdout, stderr):
        for line in stream.splitlines():
            value = line.strip()
            if value:
                return value
    return None


def capture_tool_versions(
    repo_root: Path | str,
    runner: GitRunner = default_git_runner,
) -> dict[str, dict[str, object]]:
    """Capture effective local build/runtime tool versions without network access."""

    root = Path(repo_root)
    versions: dict[str, dict[str, object]] = {}
    for name, command in _TOOL_COMMANDS:
        try:
            execution = runner(list(command), root)
        except (FileNotFoundError, OSError):
            versions[name] = {
                "available": False,
                "command": command,
                "version": None,
            }
            continue
        versions[name] = {
            "available": execution.return_code == 0,
            "command": command,
            "version": _first_nonempty_line(execution.stdout, execution.stderr),
        }
    return versions


def capture_submodule_provenance(
    repo_root: Path | str,
    runner: GitRunner = default_git_runner,
) -> dict[str, object]:
    """Capture checked-out submodule revisions plus content-free dirty state."""

    root = Path(repo_root)
    try:
        execution = runner(["git", "submodule", "status", "--recursive"], root)
    except (FileNotFoundError, OSError):
        return {"available": False, "entries": []}
    if execution.return_code != 0:
        return {"available": False, "entries": []}

    entries: list[dict[str, object]] = []
    for raw in execution.stdout.splitlines():
        if not raw.strip():
            continue
        state_prefix = raw[0]
        fields = raw[1:].strip().split()
        if len(fields) < 2:
            continue
        commit, path = fields[0], fields[1]
        state = {
            " ": "recorded",
            "+": "different_from_recorded",
            "-": "uninitialized",
            "U": "merge_conflict",
        }.get(state_prefix, "unknown")
        dirty: bool | None = None
        status_available = False
        if state != "uninitialized":
            try:
                status = runner(["git", "-C", path, "status", "--short"], root)
            except (FileNotFoundError, OSError):
                status = None
            if status is not None and status.return_code == 0:
                status_available = True
                dirty = bool(status.stdout.strip())
        entries.append({
            "path": path,
            "commit": commit,
            "checkout_state": state,
            "dirty": dirty,
            "status_available": status_available,
        })
    return {"available": True, "entries": entries}


def capture_container_runtime_identity(environment: dict[str, str] | None = None) -> dict[str, object]:
    """Record configured container image identity when the wrapper exposes it."""

    env = os.environ if environment is None else environment
    marker = str(env.get("PQC_CONTAINER", "")).strip().lower()
    image = (
        env.get("PQC_CONTAINER_IMAGE")
        or env.get("PQC_DEV_IMAGE")
        or env.get("PQC_RUNTIME_IMAGE")
    )
    digest = None
    if isinstance(image, str) and "@sha256:" in image:
        digest = "sha256:" + image.split("@sha256:", 1)[1]
    explicit_digest = env.get("PQC_CONTAINER_IMAGE_DIGEST")
    if explicit_digest:
        digest = explicit_digest
    return {
        "container": marker in {"1", "true", "yes", "on"},
        "image": image,
        "digest": digest,
        "immutable_identity_available": bool(digest),
    }


def capture_reproducibility_provenance(
    repo_root: Path | str,
    *,
    git_runner: GitRunner = default_git_runner,
    tool_runner: GitRunner = default_git_runner,
) -> dict[str, object]:
    """Capture source and effective local software-environment provenance."""

    source = capture_git_provenance(repo_root, git_runner)
    return {
        **source,
        "submodules": capture_submodule_provenance(repo_root, git_runner),
        "tools": capture_tool_versions(repo_root, tool_runner),
        "container_runtime": capture_container_runtime_identity(),
    }
