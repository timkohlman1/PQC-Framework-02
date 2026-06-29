"""Two-artifact wolfBoot flash helpers for secure-boot experiment runs.

This module flashes a wolfBoot bootloader artifact and a signed application
image through the configured experiment gateway. It records command output,
artifact hashes, configured flash offsets, and final status under one run result
directory. Command runners are injectable so unit tests do not require SSH,
UART, gateway access, or STM32 hardware.
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

SECURE_BOOT_ARTIFACT_MISSING_RETURN_CODE = 40
SECURE_BOOT_SCP_FAILED_RETURN_CODE = 41
SECURE_BOOT_FLASH_FAILED_RETURN_CODE = 42
SECURE_BOOT_PROFILE_ERROR_RETURN_CODE = 43

DEFAULT_SECURE_BOOT_FLASH_LOG_NAME = "secure_boot_flash.log"


@dataclass(frozen=True)
class CommandExecution:
    """Captured output from one command invocation."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class SecureBootFlashArtifactResult:
    """Flash evidence for one secure-boot artifact."""

    name: str
    artifact_path: Path
    artifact_exists: bool
    artifact_sha256: str | None
    offset: str
    remote_artifact_path: str
    pass_offset_to_helper: bool
    scp: CommandExecution | None
    flash: CommandExecution | None


@dataclass(frozen=True)
class SecureBootFlashResult:
    """Captured output from one wolfBoot + signed-application flash run."""

    return_code: int
    duration_seconds: float
    result_dir: Path
    log_path: Path
    stlink_serial: str
    gateway_alias: str
    flash_helper: str
    wolfboot: SecureBootFlashArtifactResult
    signed_application: SecureBootFlashArtifactResult
    failure_stage: str
    failure_reason: str | None


Runner = Callable[[list[str], Path], CommandExecution]


class SecureBootFlashProfileError(ValueError):
    """Raised when an experiment lacks required secure-boot flash fields."""


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


def _required(mapping: dict[str, Any], dotted_path: str) -> Any:
    current: Any = mapping
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise SecureBootFlashProfileError(
                f"secure-boot flash experiment missing required field: {dotted_path}"
            )
        current = current[part]
    if current is None or current == "":
        raise SecureBootFlashProfileError(
            f"secure-boot flash experiment has empty required field: {dotted_path}"
        )
    return current


def _optional_bool(mapping: dict[str, Any], dotted_path: str, default: bool) -> bool:
    current: Any = mapping
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    if isinstance(current, bool):
        return current
    return str(current).strip().lower() in {"true", "yes", "1", "on"}


def validate_secure_boot_flash_experiment(bundle: dict[str, dict[str, Any]]) -> None:
    """Validate fields required by the Phase 10h two-artifact flash workflow."""

    experiment = bundle.get("experiment", {})
    boot = bundle.get("boot", {})
    host = bundle.get("host", {})
    board = bundle.get("board", {})

    _required(experiment, "id")
    _required(experiment, "secure_boot_flash.wolfboot_artifact")
    _required(experiment, "secure_boot_flash.wolfboot_offset")
    _required(experiment, "secure_boot_flash.signed_application_artifact")
    _required(experiment, "secure_boot_flash.signed_application_offset")
    _required(host, "alias")
    _required(host, "flash.helper")
    _required(board, "stlink.serial")

    boot_mode = _required(boot, "mode")
    firmware_mode = _required(experiment, "firmware.mode")
    if firmware_mode != boot_mode:
        raise SecureBootFlashProfileError(
            f"secure-boot flash experiment firmware.mode '{firmware_mode}' does not match boot mode '{boot_mode}'"
        )


def construct_scp_command(
    artifact_path: Path | str,
    gateway_alias: str,
    remote_artifact_path: str,
) -> list[str]:
    """Construct the SCP command used to stage one artifact on the gateway."""

    return ["scp", str(Path(artifact_path)), f"{gateway_alias}:{remote_artifact_path}"]


def construct_ssh_flash_command(
    gateway_alias: str,
    flash_helper: str,
    remote_artifact_path: str,
    offset: str,
    *,
    pass_offset_to_helper: bool,
) -> list[str]:
    """Construct the SSH command used to invoke the gateway flash helper."""

    remote_command = f"{shlex.quote(flash_helper)} {shlex.quote(remote_artifact_path)}"
    if pass_offset_to_helper:
        remote_command += f" {shlex.quote(str(offset))}"
    return ["ssh", gateway_alias, remote_command]


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _format_execution(execution: CommandExecution | None, cwd: Path) -> list[str]:
    if execution is None:
        return ["not run", ""]
    return [
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


def _remote_artifact_path(result_dir: Path, label: str, artifact_path: Path) -> str:
    safe_name = f"{result_dir.name}_{label}_{artifact_path.name}"
    return str(PurePosixPath("/tmp") / safe_name)


def _artifact_result_to_manifest(result: SecureBootFlashArtifactResult) -> dict[str, Any]:
    return {
        "artifact_path": str(result.artifact_path),
        "artifact_exists": result.artifact_exists,
        "sha256": result.artifact_sha256,
        "offset": result.offset,
        "remote_artifact_path": result.remote_artifact_path,
        "pass_offset_to_helper": result.pass_offset_to_helper,
        "scp_return_code": None if result.scp is None else result.scp.return_code,
        "helper_return_code": None if result.flash is None else result.flash.return_code,
    }


def _write_secure_boot_flash_log(
    *,
    log_path: Path,
    repo_root: Path,
    result: SecureBootFlashResult,
) -> None:
    lines = [
        "wolfBoot secure-boot flash log",
        "===============================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root: {repo_root}",
        f"Gateway alias: {result.gateway_alias}",
        f"Flash helper: {result.flash_helper}",
        f"ST-LINK serial: {result.stlink_serial}",
        f"Final return code: {result.return_code}",
        f"Failure stage: {result.failure_stage}",
        f"Failure reason: {result.failure_reason if result.failure_reason is not None else 'none'}",
        f"Total duration seconds: {result.duration_seconds:.3f}",
        "",
    ]

    for artifact in [result.wolfboot, result.signed_application]:
        lines += [
            f"{artifact.name} artifact",
            "-" * (len(artifact.name) + 9),
            f"Local artifact path: {artifact.artifact_path}",
            f"Local artifact exists: {str(artifact.artifact_exists).lower()}",
            f"Local artifact SHA-256: {artifact.artifact_sha256 if artifact.artifact_sha256 is not None else 'unavailable'}",
            f"Configured flash offset: {artifact.offset}",
            f"Pass offset to helper: {str(artifact.pass_offset_to_helper).lower()}",
            f"Remote artifact path: {artifact.remote_artifact_path}",
            "",
            "SCP step",
            "--------",
        ]
        lines += _format_execution(artifact.scp, repo_root)
        lines += ["Flash helper step", "-----------------"]
        lines += _format_execution(artifact.flash, repo_root)

    log_path.write_text("\n".join(lines), encoding="utf-8")


def _prepare_artifact_result(
    *,
    name: str,
    repo_root: Path,
    result_dir: Path,
    relative_path: str,
    offset: str,
    pass_offset_to_helper: bool,
) -> SecureBootFlashArtifactResult:
    artifact_path = repo_root / relative_path
    artifact_exists = artifact_path.is_file()
    return SecureBootFlashArtifactResult(
        name=name,
        artifact_path=artifact_path,
        artifact_exists=artifact_exists,
        artifact_sha256=calculate_file_sha256(artifact_path) if artifact_exists else None,
        offset=str(offset),
        remote_artifact_path=_remote_artifact_path(result_dir, name, artifact_path),
        pass_offset_to_helper=pass_offset_to_helper,
        scp=None,
        flash=None,
    )


def _with_executions(
    artifact: SecureBootFlashArtifactResult,
    *,
    scp: CommandExecution | None,
    flash: CommandExecution | None,
) -> SecureBootFlashArtifactResult:
    return SecureBootFlashArtifactResult(
        name=artifact.name,
        artifact_path=artifact.artifact_path,
        artifact_exists=artifact.artifact_exists,
        artifact_sha256=artifact.artifact_sha256,
        offset=artifact.offset,
        remote_artifact_path=artifact.remote_artifact_path,
        pass_offset_to_helper=artifact.pass_offset_to_helper,
        scp=scp,
        flash=flash,
    )


def execute_secure_boot_flash(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
    result_dir: Path | str,
    runner: Runner = default_runner,
    git_runner: GitRunner | None = None,
) -> SecureBootFlashResult:
    """Flash wolfBoot and the signed application, then update the run manifest."""

    validate_secure_boot_flash_experiment(bundle)

    repo_root_path = Path(repo_root)
    result_dir_path = Path(result_dir)
    experiment = bundle["experiment"]
    secure_boot_config = experiment["secure_boot_flash"]
    host = bundle["host"]
    board = bundle["board"]

    gateway_alias = str(host["alias"])
    flash_helper = str(host["flash"]["helper"])
    stlink_serial = str(board["stlink"]["serial"])
    log_path = result_dir_path / DEFAULT_SECURE_BOOT_FLASH_LOG_NAME

    wolfboot = _prepare_artifact_result(
        name="wolfboot",
        repo_root=repo_root_path,
        result_dir=result_dir_path,
        relative_path=str(secure_boot_config["wolfboot_artifact"]),
        offset=str(secure_boot_config["wolfboot_offset"]),
        pass_offset_to_helper=_optional_bool(
            experiment,
            "secure_boot_flash.wolfboot_pass_offset_to_helper",
            False,
        ),
    )
    signed_application = _prepare_artifact_result(
        name="signed_application",
        repo_root=repo_root_path,
        result_dir=result_dir_path,
        relative_path=str(secure_boot_config["signed_application_artifact"]),
        offset=str(secure_boot_config["signed_application_offset"]),
        pass_offset_to_helper=_optional_bool(
            experiment,
            "secure_boot_flash.signed_application_pass_offset_to_helper",
            True,
        ),
    )

    start = perf_counter()
    return_code = 0
    failure_stage = "none"
    failure_reason: str | None = None

    for artifact in [wolfboot, signed_application]:
        if not artifact.artifact_exists:
            return_code = SECURE_BOOT_ARTIFACT_MISSING_RETURN_CODE
            failure_stage = f"{artifact.name}_artifact"
            failure_reason = f"Required artifact not found: {artifact.artifact_path}"
            break

        scp_execution = runner(
            construct_scp_command(
                artifact.artifact_path,
                gateway_alias,
                artifact.remote_artifact_path,
            ),
            repo_root_path,
        )
        artifact = _with_executions(artifact, scp=scp_execution, flash=None)
        if artifact.name == "wolfboot":
            wolfboot = artifact
        else:
            signed_application = artifact

        if scp_execution.return_code != 0:
            return_code = scp_execution.return_code or SECURE_BOOT_SCP_FAILED_RETURN_CODE
            failure_stage = f"{artifact.name}_scp"
            failure_reason = f"SCP failed for {artifact.name}."
            break

        flash_execution = runner(
            construct_ssh_flash_command(
                gateway_alias,
                flash_helper,
                artifact.remote_artifact_path,
                artifact.offset,
                pass_offset_to_helper=artifact.pass_offset_to_helper,
            ),
            repo_root_path,
        )
        artifact = _with_executions(artifact, scp=scp_execution, flash=flash_execution)
        if artifact.name == "wolfboot":
            wolfboot = artifact
        else:
            signed_application = artifact

        if flash_execution.return_code != 0:
            return_code = flash_execution.return_code or SECURE_BOOT_FLASH_FAILED_RETURN_CODE
            failure_stage = f"{artifact.name}_flash"
            failure_reason = f"Flash helper failed for {artifact.name}."
            break

    duration_seconds = perf_counter() - start
    source = (
        capture_git_provenance(repo_root_path)
        if git_runner is None
        else capture_git_provenance(repo_root_path, git_runner)
    )

    result = SecureBootFlashResult(
        return_code=return_code,
        duration_seconds=duration_seconds,
        result_dir=result_dir_path,
        log_path=log_path,
        stlink_serial=stlink_serial,
        gateway_alias=gateway_alias,
        flash_helper=flash_helper,
        wolfboot=wolfboot,
        signed_application=signed_application,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
    )

    _write_secure_boot_flash_log(log_path=log_path, repo_root=repo_root_path, result=result)

    manifest_path = result_dir_path / "manifest.json"
    current_manifest = read_manifest(manifest_path)
    current_firmware = current_manifest.get("firmware", {})
    if not isinstance(current_firmware, dict):
        current_firmware = {}
    current_firmware.update(
        {
            "artifact": str(secure_boot_config["signed_application_artifact"]),
            "artifact_path": str(signed_application.artifact_path),
            "artifact_exists": signed_application.artifact_exists,
            "sha256": signed_application.artifact_sha256,
        }
    )

    update_manifest(
        manifest_path,
        {
            "result": "secure_boot_flash_passed" if return_code == 0 else "secure_boot_flash_failed",
            "source": source,
            "firmware": current_firmware,
            "boot_crypto": str(experiment.get("boot_crypto", "ecdsa_p256")),
            "secure_boot_flash": {
                "return_code": return_code,
                "duration_seconds": round(duration_seconds, 3),
                "log": DEFAULT_SECURE_BOOT_FLASH_LOG_NAME,
                "failure_stage": failure_stage,
                "failure_reason": failure_reason,
                "gateway_alias": gateway_alias,
                "flash_helper": flash_helper,
                "stlink_serial": stlink_serial,
                "wolfboot": _artifact_result_to_manifest(wolfboot),
                "signed_application": _artifact_result_to_manifest(signed_application),
            },
        },
    )

    return result
