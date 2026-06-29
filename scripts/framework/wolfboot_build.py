"""wolfBoot build-profile helpers.

This module runs a configured local wolfBoot build and records build evidence.
It does not flash hardware, open UART devices, use SSH, generate signing keys,
or sign application images.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from framework.artifacts import calculate_file_sha256, copy_artifact_to_result

MISSING_SOURCE_RETURN_CODE = 20
WOLFBOOT_BUILD_ARTIFACT_MISSING_RETURN_CODE = 21
PROFILE_ERROR_RETURN_CODE = 22
WOLFBOOT_BUILD_TOOL_MISSING_RETURN_CODE = 23
DEFAULT_WOLFBOOT_RESULTS_SUBDIR = "wolfboot-builds"
DEFAULT_WOLFBOOT_LOG_NAME = "wolfboot_build.log"


@dataclass(frozen=True)
class WolfBootCommandExecution:
    """Captured output from one wolfBoot build command invocation."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class WolfBootBuildResult:
    """Captured result from a configured wolfBoot build profile."""

    return_code: int
    duration_seconds: float
    profile_id: str
    result_dir: Path
    log_path: Path
    command: list[str]
    working_directory: Path
    source_dir: Path
    output_dir: Path
    artifact_path: Path
    artifact_exists: bool
    artifact_sha256: str | None
    retained_artifact_path: Path | None
    execution: WolfBootCommandExecution | None
    failure_reason: str | None = None


WolfBootRunner = Callable[[list[str], Path], WolfBootCommandExecution]


class WolfBootBuildProfileError(ValueError):
    """Raised when a wolfBoot build profile is incomplete or invalid."""


def _safe_id_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("_.-")
    if not safe:
        raise WolfBootBuildProfileError("wolfBoot build profile id must contain at least one safe character")
    return safe


def _required(profile: dict[str, Any], dotted_path: str) -> Any:
    current: Any = profile
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise WolfBootBuildProfileError(
                f"wolfBoot build profile missing required field: {dotted_path}"
            )
        current = current[part]
    if current is None or current == "":
        raise WolfBootBuildProfileError(
            f"wolfBoot build profile has empty required field: {dotted_path}"
        )
    return current


def validate_wolfboot_build_profile(profile: dict[str, Any]) -> None:
    """Validate the minimum schema for a wolfBoot build profile."""

    required_fields = [
        "id",
        "description",
        "source_dir",
        "output_dir",
        "artifact",
        "signature_algorithm",
        "target",
        "build.command",
    ]

    for field in required_fields:
        _required(profile, field)

    algorithm = str(_required(profile, "signature_algorithm"))
    if algorithm != "ecdsa_p256":
        raise WolfBootBuildProfileError(
            "Phase 10f supports only signature_algorithm: ecdsa_p256"
        )


def construct_wolfboot_build_command(profile: dict[str, Any]) -> list[str]:
    """Construct the configured wolfBoot build command.

    The profile stores the command and optional argument string as plain scalar
    values so the current small YAML parser can load it. The command is split
    with ``shlex.split``; no shell is used.
    """

    validate_wolfboot_build_profile(profile)
    build_config = profile.get("build", {})
    if not isinstance(build_config, dict):
        raise WolfBootBuildProfileError("wolfBoot build profile build field must be a mapping")

    command = shlex.split(str(build_config["command"]))
    args = shlex.split(str(build_config.get("args", "")))

    if not command:
        raise WolfBootBuildProfileError("wolfBoot build profile build.command produced an empty command")

    return command + args


def default_wolfboot_runner(command: list[str], cwd: Path) -> WolfBootCommandExecution:
    """Run a wolfBoot build command and capture stdout, stderr, and timing."""

    start = perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return WolfBootCommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=perf_counter() - start,
    )


def create_wolfboot_build_result_dir(
    profile_id: str,
    results_root: Path | str = "results",
    timestamp: datetime | None = None,
) -> Path:
    """Create a result directory for one wolfBoot build attempt."""

    current_timestamp = timestamp or datetime.now().astimezone()
    base = Path(results_root) / DEFAULT_WOLFBOOT_RESULTS_SUBDIR
    base.mkdir(parents=True, exist_ok=True)
    stem = f"{current_timestamp.strftime('%Y-%m-%d_%H%M%S')}_{_safe_id_component(profile_id)}"
    result_dir = base / stem
    suffix = 1
    while result_dir.exists():
        suffix += 1
        result_dir = base / f"{stem}_{suffix:02d}"
    result_dir.mkdir(parents=True, exist_ok=False)
    return result_dir


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _write_log(
    *,
    log_path: Path,
    profile: dict[str, Any],
    repo_root: Path,
    command: list[str],
    working_directory: Path,
    source_dir: Path,
    output_dir: Path,
    artifact_path: Path,
    artifact_exists: bool,
    artifact_sha256: str | None,
    return_code: int,
    duration_seconds: float,
    execution: WolfBootCommandExecution | None,
    failure_reason: str | None,
) -> None:
    lines = [
        "wolfBoot build log",
        "==================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Profile ID: {profile.get('id')}",
        f"Repository root: {repo_root}",
        f"Source directory: {source_dir}",
        f"Output directory: {output_dir}",
        f"Configured target: {profile.get('target')}",
        f"Signature algorithm: {profile.get('signature_algorithm')}",
        f"Command: {_format_command(command) if command else 'unavailable'}",
        f"Working directory: {working_directory}",
        f"Artifact path: {artifact_path}",
        f"Artifact exists: {str(artifact_exists).lower()}",
        f"Artifact SHA-256: {artifact_sha256 if artifact_sha256 is not None else 'unavailable'}",
        f"Final return code: {return_code}",
        f"Total duration seconds: {duration_seconds:.3f}",
    ]

    if failure_reason is not None:
        lines.extend(["", "Failure reason", "--------------", failure_reason])

    if execution is not None:
        lines.extend(
            [
                "",
                "Build command output",
                "--------------------",
                f"Return code: {execution.return_code}",
                f"Duration seconds: {execution.duration_seconds:.3f}",
                "",
                "stdout:",
                execution.stdout.rstrip(),
                "",
                "stderr:",
                execution.stderr.rstrip(),
                "",
            ]
        )

    log_path.write_text("\n".join(lines), encoding="utf-8")


def execute_wolfboot_build(
    *,
    profile: dict[str, Any],
    repo_root: Path | str,
    results_root: Path | str = "results",
    runner: WolfBootRunner = default_wolfboot_runner,
    timestamp: datetime | None = None,
) -> WolfBootBuildResult:
    """Execute a configured wolfBoot build profile and record evidence."""

    repo_root_path = Path(repo_root)
    start = perf_counter()

    try:
        validate_wolfboot_build_profile(profile)
        command = construct_wolfboot_build_command(profile)
        profile_id = str(profile["id"])
    except WolfBootBuildProfileError as exc:
        profile_id = str(profile.get("id", "invalid_wolfboot_profile"))
        result_dir = create_wolfboot_build_result_dir(profile_id, results_root, timestamp)
        log_path = result_dir / DEFAULT_WOLFBOOT_LOG_NAME
        duration_seconds = perf_counter() - start
        failure_reason = str(exc)
        manifest = {
            "record_type": "wolfboot_build",
            "schema_version": 1,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "profile": profile_id,
            "result": "wolfboot_build_failed",
            "wolfboot_build": {
                "return_code": PROFILE_ERROR_RETURN_CODE,
                "duration_seconds": round(duration_seconds, 3),
                "log": DEFAULT_WOLFBOOT_LOG_NAME,
                "failure_reason": failure_reason,
            },
        }
        _write_log(
            log_path=log_path,
            profile=profile,
            repo_root=repo_root_path,
            command=[],
            working_directory=repo_root_path,
            source_dir=repo_root_path,
            output_dir=repo_root_path,
            artifact_path=repo_root_path,
            artifact_exists=False,
            artifact_sha256=None,
            return_code=PROFILE_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            execution=None,
            failure_reason=failure_reason,
        )
        _write_json(result_dir / "manifest.json", manifest)
        return WolfBootBuildResult(
            return_code=PROFILE_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            profile_id=profile_id,
            result_dir=result_dir,
            log_path=log_path,
            command=[],
            working_directory=repo_root_path,
            source_dir=repo_root_path,
            output_dir=repo_root_path,
            artifact_path=repo_root_path,
            artifact_exists=False,
            artifact_sha256=None,
            retained_artifact_path=None,
            execution=None,
            failure_reason=failure_reason,
        )

    source_dir = repo_root_path / str(profile["source_dir"])
    output_dir = repo_root_path / str(profile["output_dir"])
    artifact_path = repo_root_path / str(profile["artifact"])
    working_directory = source_dir
    result_dir = create_wolfboot_build_result_dir(profile_id, results_root, timestamp)
    log_path = result_dir / DEFAULT_WOLFBOOT_LOG_NAME

    execution: WolfBootCommandExecution | None = None
    artifact_sha256: str | None = None
    retained_artifact_path: Path | None = None
    failure_reason: str | None = None

    if not source_dir.is_dir():
        return_code = MISSING_SOURCE_RETURN_CODE
        failure_reason = f"Configured wolfBoot source directory does not exist: {source_dir}"
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            execution = runner(command, working_directory)
            return_code = execution.return_code
        except FileNotFoundError as exc:
            missing_executable = command[0] if command else "configured build tool"
            return_code = WOLFBOOT_BUILD_TOOL_MISSING_RETURN_CODE
            failure_reason = (
                "wolfBoot build command could not be started because the executable was not found: "
                f"{missing_executable}"
            )
            execution = WolfBootCommandExecution(
                command=command,
                return_code=return_code,
                stdout="",
                stderr=f"{failure_reason}\n{exc}",
                duration_seconds=perf_counter() - start,
            )

        if return_code == 0:
            if artifact_path.is_file():
                artifact_sha256 = calculate_file_sha256(artifact_path)
                retained_artifact_path = copy_artifact_to_result(
                    artifact_path,
                    result_dir,
                    "wolfboot.elf",
                )
            else:
                return_code = WOLFBOOT_BUILD_ARTIFACT_MISSING_RETURN_CODE
                failure_reason = (
                    "wolfBoot build command returned success, but the configured artifact was not found: "
                    f"{artifact_path}"
                )
        elif failure_reason is None:
            failure_reason = f"wolfBoot build command failed with return code {return_code}."

    duration_seconds = perf_counter() - start
    artifact_exists = artifact_path.is_file()
    _write_log(
        log_path=log_path,
        profile=profile,
        repo_root=repo_root_path,
        command=command,
        working_directory=working_directory,
        source_dir=source_dir,
        output_dir=output_dir,
        artifact_path=artifact_path,
        artifact_exists=artifact_exists,
        artifact_sha256=artifact_sha256,
        return_code=return_code,
        duration_seconds=duration_seconds,
        execution=execution,
        failure_reason=failure_reason,
    )

    manifest = {
        "record_type": "wolfboot_build",
        "schema_version": 1,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "profile": profile_id,
        "result": "wolfboot_build_passed" if return_code == 0 else "wolfboot_build_failed",
        "wolfboot_build": {
            "profile_id": profile_id,
            "description": profile.get("description"),
            "target": profile.get("target"),
            "signature_algorithm": profile.get("signature_algorithm"),
            "source_dir": str(source_dir),
            "output_dir": str(output_dir),
            "command": command,
            "working_directory": str(working_directory),
            "return_code": return_code,
            "duration_seconds": round(duration_seconds, 3),
            "log": DEFAULT_WOLFBOOT_LOG_NAME,
            "failure_reason": failure_reason,
        },
        "artifact": {
            "path": str(artifact_path),
            "exists": artifact_exists,
            "sha256": artifact_sha256,
            "retained_path": None if retained_artifact_path is None else str(retained_artifact_path),
        },
    }
    _write_json(result_dir / "manifest.json", manifest)

    return WolfBootBuildResult(
        return_code=return_code,
        duration_seconds=duration_seconds,
        profile_id=profile_id,
        result_dir=result_dir,
        log_path=log_path,
        command=command,
        working_directory=working_directory,
        source_dir=source_dir,
        output_dir=output_dir,
        artifact_path=artifact_path,
        artifact_exists=artifact_exists,
        artifact_sha256=artifact_sha256,
        retained_artifact_path=retained_artifact_path,
        execution=execution,
        failure_reason=failure_reason,
    )
