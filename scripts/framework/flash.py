"""Remote firmware flash helpers for experiment runs.

This module copies a verified ELF artifact to the experiment gateway with
``scp``, invokes the configured gateway flash helper with ``ssh``, and records
all command output under ``results/<run_id>/flash.log``.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any, Callable

from framework.artifacts import calculate_file_sha256
from framework.manifest import read_manifest, update_manifest
from framework.source import GitCommandExecution, GitRunner, capture_git_provenance
from framework.ssh_target import gateway_ssh_target

ARTIFACT_MISSING_RETURN_CODE = 3
PROVENANCE_REFUSED_RETURN_CODE = 5
BUILD_RECORD_MISSING_RETURN_CODE = 6
BUILD_RECORD_INVALID_RETURN_CODE = 7

PROVENANCE_VERIFIED_BUILD_MATCH = "verified_build_match"
PROVENANCE_UNTRACKED_ARTIFACT_ALLOWED = "untracked_artifact_allowed"
PROVENANCE_MISMATCH_REFUSED = "mismatch_refused"
PROVENANCE_MISSING_BUILD_RECORD = "missing_build_record"


@dataclass(frozen=True)
class CommandExecution:
    """Captured output from one command invocation."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class FlashProvenance:
    """Flash-time comparison against a recorded build manifest."""

    status: str
    return_code: int
    source_build_run_id: str | None
    source_build_number: int | None
    source_build_fingerprint: str | None
    source_build_firmware_sha256: str | None
    source_build_artifact_path: str | None
    current_build_fingerprint: str | None
    current_build_fingerprint_algorithm: str | None
    current_build_fingerprint_error: str | None
    message: str


@dataclass(frozen=True)
class FlashResult:
    """Captured output from one remote flash run."""

    return_code: int
    duration_seconds: float
    artifact_path: Path
    remote_artifact_path: str
    stlink_serial: str
    log_path: Path
    scp: CommandExecution | None
    flash: CommandExecution | None
    firmware_sha256: str | None
    provenance_status: str


Runner = Callable[[list[str], Path], CommandExecution]


def construct_scp_command(
    artifact_path: Path | str,
    gateway_alias: str,
    remote_artifact_path: str,
) -> list[str]:
    """Construct the SCP command used to stage an ELF on the gateway."""

    return ["scp", str(Path(artifact_path)), f"{gateway_alias}:{remote_artifact_path}"]


def construct_ssh_flash_command(
    gateway_alias: str,
    flash_helper: str,
    remote_artifact_path: str,
) -> list[str]:
    """Construct the SSH command used to invoke the gateway flash helper."""

    remote_command = f"{shlex.quote(flash_helper)} {shlex.quote(remote_artifact_path)}"
    return ["ssh", gateway_alias, remote_command]


def default_runner(command: list[str], cwd: Path) -> CommandExecution:
    """Run a command without a shell and capture output and duration."""

    start = perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=perf_counter() - start,
    )


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _format_execution(execution: CommandExecution, cwd: Path) -> str:
    return "\n".join(
        [
            f"Command: {_format_command(execution.command)}",
            f"Working directory: {cwd}",
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


def _read_required_manifest_string(
    manifest: dict[str, Any],
    dotted_path: str,
) -> tuple[str | None, str | None]:
    current: Any = manifest

    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None, f"Build manifest missing required field: {dotted_path}"
        current = current[part]

    if not isinstance(current, str) or current == "":
        return None, f"Build manifest has empty or invalid required field: {dotted_path}"

    return current, None



def _build_record_manifest_path(
    results_root: Path,
    build_run_id: str,
) -> Path:
    return results_root / build_run_id / "manifest.json"


def _check_flash_provenance(
    *,
    bundle: dict[str, dict[str, Any]],
    repo_root: Path,
    result_dir: Path,
    artifact_path: Path,
    firmware_sha256: str,
    source_build_run_id: str | None,
    source_build_number: int | None,
    source_build_manifest_path: Path | None,
    allow_untracked_artifact: bool,
) -> FlashProvenance:
    """Verify flash provenance using immutable manifest and ELF hashes only."""
    del bundle, repo_root, artifact_path
    if allow_untracked_artifact:
        return FlashProvenance(PROVENANCE_UNTRACKED_ARTIFACT_ALLOWED, 0, None, None, None, None, None, None, None, None, "Explicit escape hatch used: flashing an artifact without a verified build record.")
    if source_build_run_id is None and source_build_manifest_path is None:
        return FlashProvenance(PROVENANCE_MISSING_BUILD_RECORD, BUILD_RECORD_MISSING_RETURN_CODE, None, source_build_number, None, None, None, None, None, None, "No build record was provided and untracked artifact flashing was not allowed.")
    build_manifest_path = source_build_manifest_path if source_build_manifest_path is not None else _build_record_manifest_path(result_dir.parent, source_build_run_id)
    if not build_manifest_path.is_file():
        return FlashProvenance(PROVENANCE_MISSING_BUILD_RECORD, BUILD_RECORD_MISSING_RETURN_CODE, source_build_run_id, source_build_number, None, None, None, None, None, None, f"Build manifest not found: {build_manifest_path}")
    build_manifest = read_manifest(build_manifest_path)
    recorded_sha256, sha_error = _read_required_manifest_string(build_manifest, "firmware.sha256")
    recorded_artifact_path, artifact_error = _read_required_manifest_string(build_manifest, "firmware.artifact_path")
    errors = [e for e in (sha_error, artifact_error) if e is not None]
    if errors:
        return FlashProvenance(PROVENANCE_MISSING_BUILD_RECORD, BUILD_RECORD_INVALID_RETURN_CODE, source_build_run_id, source_build_number, None, recorded_sha256, recorded_artifact_path, None, None, None, "; ".join(errors))
    if recorded_sha256 != firmware_sha256:
        return FlashProvenance(PROVENANCE_MISMATCH_REFUSED, PROVENANCE_REFUSED_RETURN_CODE, source_build_run_id, source_build_number, None, recorded_sha256, recorded_artifact_path, None, None, None, "Flash-time ELF SHA-256 does not match the recorded build ELF SHA-256.")
    return FlashProvenance(PROVENANCE_VERIFIED_BUILD_MATCH, 0, source_build_run_id, source_build_number, None, recorded_sha256, recorded_artifact_path, None, None, None, "Flash artifact matches the immutable build record ELF SHA-256.")

def _write_flash_log(
    log_path: Path,
    repo_root: Path,
    artifact_path: Path,
    remote_artifact_path: str,
    stlink_serial: str,
    scp_execution: CommandExecution | None,
    flash_execution: CommandExecution | None,
    return_code: int,
    duration_seconds: float,
    firmware_sha256: str | None,
    provenance: FlashProvenance,
) -> None:
    lines = [
        "Remote firmware flash log",
        "=========================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root: {repo_root}",
        f"Local artifact path: {artifact_path}",
        f"Local artifact SHA-256: {firmware_sha256 if firmware_sha256 is not None else 'unavailable'}",
        f"Remote artifact path: {remote_artifact_path}",
        f"ST-LINK serial: {stlink_serial}",
        f"Final return code: {return_code}",
        f"Total duration seconds: {duration_seconds:.3f}",
        "",
        "Flash provenance check",
        "----------------------",
        f"Provenance status: {provenance.status}",
        f"Provenance message: {provenance.message}",
        f"Source build run ID: {provenance.source_build_run_id if provenance.source_build_run_id is not None else 'unavailable'}",
        f"Source build number: {provenance.source_build_number if provenance.source_build_number is not None else 'unavailable'}",
        f"Source build fingerprint: {provenance.source_build_fingerprint if provenance.source_build_fingerprint is not None else 'unavailable'}",
        f"Source build firmware SHA-256: {provenance.source_build_firmware_sha256 if provenance.source_build_firmware_sha256 is not None else 'unavailable'}",
        f"Current expected build fingerprint (disabled): {provenance.current_build_fingerprint if provenance.current_build_fingerprint is not None else 'unavailable'}",
        f"Current expected build fingerprint algorithm: {provenance.current_build_fingerprint_algorithm if provenance.current_build_fingerprint_algorithm is not None else 'unavailable'}",
        f"Current expected build fingerprint error: {provenance.current_build_fingerprint_error if provenance.current_build_fingerprint_error is not None else 'none'}",
        "",
    ]
    if scp_execution is None:
        if return_code == ARTIFACT_MISSING_RETURN_CODE:
            reason = "Skipped because the local artifact was not found."
        elif provenance.return_code != 0:
            reason = "Skipped because firmware artifact provenance was not verified."
        else:
            reason = "Skipped before SCP."
        lines += ["SCP step", "--------", reason, ""]
    else:
        lines += ["SCP step", "--------", _format_execution(scp_execution, repo_root)]
    if flash_execution is None:
        if scp_execution is not None:
            reason = "Skipped because the SCP step failed."
        elif return_code == ARTIFACT_MISSING_RETURN_CODE:
            reason = "Skipped because the local artifact was not found."
        elif provenance.return_code != 0:
            reason = "Skipped because firmware artifact provenance was not verified."
        else:
            reason = "Skipped before flash helper."
        lines += ["Flash step", "----------", reason, ""]
    else:
        lines += ["Flash step", "----------", _format_execution(flash_execution, repo_root)]
    log_path.write_text("\n".join(lines), encoding="utf-8")


def execute_flash(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
    result_dir: Path | str,
    runner: Runner = default_runner,
    git_runner: GitRunner | None = None,
    source_build_run_id: str | None = None,
    source_build_number: int | None = None,
    source_build_manifest_path: Path | str | None = None,
    artifact_path_override: Path | str | None = None,
    allow_untracked_artifact: bool = False,
) -> FlashResult:
    """Stage and remotely flash the configured artifact, then update the manifest."""

    repo_root_path = Path(repo_root)
    result_dir_path = Path(result_dir)
    source = (
        capture_git_provenance(repo_root_path)
        if git_runner is None
        else capture_git_provenance(repo_root_path, git_runner)
    )
    log_path = result_dir_path / "flash.log"
    artifact_relative_path = Path(str(bundle["experiment"]["firmware"]["artifact"]))
    artifact_path = (
        Path(artifact_path_override)
        if artifact_path_override is not None
        else repo_root_path / artifact_relative_path
    )
    remote_artifact_path = str(PurePosixPath("/tmp") / artifact_path.name)
    gateway_alias = str(bundle["host"]["alias"])
    gateway_target = gateway_ssh_target(bundle["host"])
    flash_helper = str(bundle["host"]["flash"]["helper"])
    stlink_serial = str(bundle["board"]["stlink"]["serial"])

    start = perf_counter()
    scp_execution: CommandExecution | None = None
    flash_execution: CommandExecution | None = None

    firmware_sha256 = calculate_file_sha256(artifact_path) if artifact_path.is_file() else None

    if not artifact_path.is_file():
        provenance = FlashProvenance(
            status=PROVENANCE_MISSING_BUILD_RECORD,
            return_code=ARTIFACT_MISSING_RETURN_CODE,
            source_build_run_id=source_build_run_id,
            source_build_number=source_build_number,
            source_build_fingerprint=None,
            source_build_firmware_sha256=None,
            source_build_artifact_path=None,
            current_build_fingerprint=None,
            current_build_fingerprint_algorithm=None,
            current_build_fingerprint_error=None,
            message="Configured local artifact was not found.",
        )
        return_code = ARTIFACT_MISSING_RETURN_CODE
    else:
        provenance = _check_flash_provenance(
            bundle=bundle,
            repo_root=repo_root_path,
            result_dir=result_dir_path,
            artifact_path=artifact_path,
            firmware_sha256=firmware_sha256,
            source_build_run_id=source_build_run_id,
            source_build_number=source_build_number,
            source_build_manifest_path=(
                None if source_build_manifest_path is None else Path(source_build_manifest_path)
            ),
            allow_untracked_artifact=allow_untracked_artifact,
        )
        return_code = provenance.return_code
        if return_code == 0:
            scp_execution = runner(
                construct_scp_command(artifact_path, gateway_target, remote_artifact_path),
                repo_root_path,
            )
            return_code = scp_execution.return_code
            if return_code == 0:
                flash_execution = runner(
                    construct_ssh_flash_command(gateway_target, flash_helper, remote_artifact_path),
                    repo_root_path,
                )
                return_code = flash_execution.return_code

    duration_seconds = perf_counter() - start
    _write_flash_log(
        log_path,
        repo_root_path,
        artifact_path,
        remote_artifact_path,
        stlink_serial,
        scp_execution,
        flash_execution,
        return_code,
        duration_seconds,
        firmware_sha256,
        provenance,
    )
    manifest_path = result_dir_path / "manifest.json"
    current_manifest = read_manifest(manifest_path)
    current_firmware = current_manifest.get("firmware", {})
    existing_build_sha256 = (
        current_firmware.get("sha256") if isinstance(current_firmware, dict) else None
    )

    updated_firmware = dict(current_firmware) if isinstance(current_firmware, dict) else {}
    updated_firmware.update(
        {
            "artifact": artifact_relative_path.as_posix(),
            "artifact_path": str(artifact_path),
            "artifact_exists": artifact_path.is_file(),
            "sha256": existing_build_sha256 if existing_build_sha256 is not None else firmware_sha256,
        }
    )

    update_manifest(
        manifest_path,
        {
            "result": "flash_passed" if return_code == 0 else "flash_failed",
            "firmware": updated_firmware,
            "source": source,
            "flash": {
                "return_code": return_code,
                "duration_seconds": round(duration_seconds, 3),
                "log": "flash.log",
                "remote_artifact_path": remote_artifact_path,
                "stlink_serial": stlink_serial,
                "source_build_run_id": provenance.source_build_run_id,
                "source_build_number": provenance.source_build_number,
                "source_build_fingerprint": provenance.source_build_fingerprint,
                "source_build_firmware_sha256": provenance.source_build_firmware_sha256,
                "source_build_artifact_path": provenance.source_build_artifact_path,
                "current_build_fingerprint": provenance.current_build_fingerprint,
                "current_build_fingerprint_algorithm": provenance.current_build_fingerprint_algorithm,
                "current_build_fingerprint_error": provenance.current_build_fingerprint_error,
                "firmware_sha256": firmware_sha256,
                "provenance_status": provenance.status,
                "provenance_message": provenance.message,
                "untracked_artifact_allowed": allow_untracked_artifact,
                "scp_return_code": None if scp_execution is None else scp_execution.return_code,
                "helper_return_code": None if flash_execution is None else flash_execution.return_code,
            },
        },
    )
    return FlashResult(
        return_code=return_code,
        duration_seconds=duration_seconds,
        artifact_path=artifact_path,
        remote_artifact_path=remote_artifact_path,
        stlink_serial=stlink_serial,
        log_path=log_path,
        scp=scp_execution,
        flash=flash_execution,
        firmware_sha256=firmware_sha256,
        provenance_status=provenance.status,
    )
