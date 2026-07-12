"""Local firmware build helpers for experiment runs.

This module wraps the local CMake/STM32 build process and records build output
under results/<run_id>/ without flashing hardware, opening UART devices, using
SSH, or touching network resources.
"""

import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from framework.artifacts import calculate_file_sha256, copy_firmware_artifacts_to_result
from framework.build_number import BuildNumberError, reserve_next_build_number
from framework.build_records import write_build_record
from framework.build_state import (
    BuildHashStateError,
    read_last_successful_build_state,
    record_last_successful_build_state,
)
from framework.fingerprint import (
    FingerprintInputError,
    calculate_default_build_fingerprint,
)
from framework.manifest import read_manifest, update_manifest
from framework.generated_state import (
    build_identity,
    detect_execution_identity,
    preflight_generated_state,
    record_generated_state_success,
)
from framework.source import GitCommandExecution, GitRunner, capture_git_provenance

ARTIFACT_MISSING_RETURN_CODE = 3
FINGERPRINT_INPUT_ERROR_RETURN_CODE = 4
BUILD_NUMBER_ERROR_RETURN_CODE = 9
BUILD_SKIP_REASON_CACHED = "cached_build_valid"


@dataclass(frozen=True)
class CommandExecution:
    """Captured output from one command invocation."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class BuildResult:
    """Captured output from a firmware build run."""

    return_code: int
    duration_seconds: float
    elf_path: Path
    log_path: Path
    configure: CommandExecution
    build: CommandExecution | None
    firmware_sha256: str | None
    build_fingerprint: str | None
    build_fingerprint_inputs: list[str]
    build_fingerprint_algorithm: str | None
    build_number: int | None
    result_artifacts: dict[str, dict[str, Any]]
    build_record_dir: Path | None = None
    build_record_manifest_path: Path | None = None
    build_skipped: bool = False
    build_skip_reason: str | None = None


Runner = Callable[[list[str], Path], CommandExecution]


def construct_configure_command(preset: str = "Debug") -> list[str]:
    """Construct the CMake configure command for a preset."""

    return ["cmake", "--preset", preset]


def construct_build_command(preset: str = "Debug") -> list[str]:
    """Construct the CMake build command for a preset."""

    return ["cmake", "--build", "--preset", preset]


def default_runner(command: list[str], cwd: Path) -> CommandExecution:
    """Run a command and capture stdout, stderr, return code, and duration."""

    start = perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    duration_seconds = perf_counter() - start

    return CommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=duration_seconds,
    )


def _format_command(command: list[str]) -> str:
    """Format a command for logs without using a shell."""

    return " ".join(shlex.quote(part) for part in command)


def _format_execution(execution: CommandExecution, cwd: Path) -> str:
    """Format one command execution for build.log."""

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


def _write_build_log(
    log_path: Path,
    repo_root: Path,
    configure: CommandExecution,
    build: CommandExecution | None,
    return_code: int,
    duration_seconds: float,
    elf_path: Path,
    artifact_exists: bool,
    firmware_sha256: str | None,
    build_fingerprint: str | None,
    build_fingerprint_inputs: list[str],
    build_fingerprint_algorithm: str | None,
    fingerprint_error: str | None = None,
    build_number_error: str | None = None,
    build_number: int | None = None,
    build_skipped: bool = False,
    build_skip_reason: str | None = None,
    build_skip_detail: str | None = None,
    force_rebuild: bool = False,
) -> None:
    """Write the build log for one experiment build run."""

    lines = [
        "Firmware build log",
        "==================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root: {repo_root}",
        f"Build number: {build_number if build_number is not None else 'unavailable'}",
        f"Build skipped: {str(build_skipped).lower()}",
        f"Build skip reason: {build_skip_reason if build_skip_reason is not None else 'none'}",
        f"Force rebuild requested: {str(force_rebuild).lower()}",
        f"Output ELF path: {elf_path}",
        f"Output ELF exists: {str(artifact_exists).lower()}",
        f"Output ELF SHA-256: {firmware_sha256 if firmware_sha256 is not None else 'unavailable'}",
        f"Build fingerprint algorithm: {build_fingerprint_algorithm if build_fingerprint_algorithm is not None else 'unavailable'}",
        f"Build fingerprint: {build_fingerprint if build_fingerprint is not None else 'unavailable'}",
        "Build fingerprint inputs:",
        *(f"- {input_path}" for input_path in build_fingerprint_inputs),
        f"Final return code: {return_code}",
        f"Total duration seconds: {duration_seconds:.3f}",
        "",
        "Configure step",
        "--------------",
        _format_execution(configure, repo_root),
    ]

    if build is None:
        skip_message = (
            "Skipped because a valid cached build artifact matched the current build fingerprint."
            if build_skipped
            else "Skipped because the configure step failed."
        )
        lines.extend(
            [
                "Build step",
                "----------",
                skip_message,
                "",
            ]
        )
    else:
        lines.extend(
            [
                "Build step",
                "----------",
                _format_execution(build, repo_root),
            ]
        )

    if build_skipped:
        lines.extend(
            [
                "Rebuild decision",
                "----------------",
                f"Decision: skipped",
                f"Reason: {build_skip_reason if build_skip_reason is not None else BUILD_SKIP_REASON_CACHED}",
                f"Detail: {build_skip_detail if build_skip_detail is not None else 'Current fingerprint matched local state and expected ELF exists.'}",
                "",
            ]
        )

    if not build_skipped and build_skip_reason is not None:
        lines.extend(
            [
                "Rebuild decision",
                "----------------",
                "Decision: run",
                f"Reason: {build_skip_reason}",
                f"Detail: {build_skip_detail if build_skip_detail is not None else 'CMake configure/build was required.'}",
                "",
            ]
        )

    if return_code == ARTIFACT_MISSING_RETURN_CODE:
        lines.extend(
            [
                "Artifact check",
                "--------------",
                "CMake returned success, but the expected ELF artifact was not found.",
                "",
            ]
        )

    if return_code == FINGERPRINT_INPUT_ERROR_RETURN_CODE:
        lines.extend(
            [
                "Build fingerprint check",
                "-----------------------",
                fingerprint_error if fingerprint_error is not None else "Build fingerprint calculation failed.",
                "",
            ]
        )

    if return_code == BUILD_NUMBER_ERROR_RETURN_CODE:
        lines.extend(
            [
                "Build number check",
                "------------------",
                build_number_error if build_number_error is not None else "Build number tracking failed.",
                "",
            ]
        )

    log_path.write_text("\n".join(lines), encoding="utf-8")




def _read_rebuild_state(repo_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read local rebuild-skip state without trusting malformed data."""

    try:
        return read_last_successful_build_state(repo_root), None
    except BuildHashStateError as exc:
        return None, str(exc)


def _successful_state_return_code(state: dict[str, Any]) -> bool:
    """Return whether a local state record says its source build succeeded."""

    build = state.get("build", {})
    if not isinstance(build, dict):
        return False

    return_code = build.get("return_code")
    return return_code is None or return_code == 0


def _rebuild_decision(
    *,
    current_fingerprint: str,
    current_algorithm: str,
    state: dict[str, Any] | None,
    state_error: str | None,
    elf_path: Path,
    force: bool,
) -> tuple[bool, str, str]:
    """Return whether CMake can be skipped, plus a reason and detail."""

    if force:
        return False, "force_requested", "--force was supplied."

    if state_error is not None:
        return False, "invalid_state", state_error

    if state is None:
        return False, "missing_state", "No local last-successful-build state was found."

    if not _successful_state_return_code(state):
        return False, "previous_build_failed", "Local build state did not record a successful prior build."

    if not elf_path.is_file():
        return False, "missing_elf", f"Expected ELF was not found: {elf_path}"

    build_state = state.get("build", {})
    state_fingerprint = build_state.get("fingerprint") if isinstance(build_state, dict) else None
    state_algorithm = build_state.get("fingerprint_algorithm") if isinstance(build_state, dict) else None

    if state_algorithm != current_algorithm:
        return False, "changed_hash", "Build fingerprint algorithm differs from local state."

    if state_fingerprint != current_fingerprint:
        return False, "changed_hash", "Current build fingerprint differs from local state."

    return True, BUILD_SKIP_REASON_CACHED, "Current fingerprint matched local state and expected ELF exists."



def _build_record_manifest_update(record_dir: Path | None) -> dict[str, Any]:
    """Return run-manifest fields that reference a first-class build record."""

    return {
        "record_path": None if record_dir is None else str(record_dir),
        "record_manifest": None if record_dir is None else str(record_dir / "manifest.json"),
    }


def _current_run_id(result_dir: Path) -> str | None:
    """Read the compatibility run ID for build-record back references."""

    try:
        run_id = read_manifest(result_dir / "manifest.json").get("run_id")
    except (FileNotFoundError, OSError, ValueError):
        return result_dir.name

    return run_id if isinstance(run_id, str) else result_dir.name

def execute_build(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
    result_dir: Path | str,
    configure_preset: str = "Debug",
    build_preset: str = "Debug",
    force: bool = False,
    runner: Runner = default_runner,
    git_runner: GitRunner | None = None,
) -> BuildResult:
    """Run or safely skip the local CMake build process and update the manifest.

    The configure and build commands are intentionally injectable so unit tests
    can verify command construction and result handling without invoking CMake.
    """

    repo_root_path = Path(repo_root)
    result_dir_path = Path(result_dir)
    source = (
        capture_git_provenance(repo_root_path)
        if git_runner is None
        else capture_git_provenance(repo_root_path, git_runner)
    )
    log_path = result_dir_path / "build.log"
    artifact_relative_path = Path(str(bundle["experiment"]["firmware"]["artifact"]))
    elf_path = repo_root_path / artifact_relative_path

    start = perf_counter()

    try:
        build_fingerprint = calculate_default_build_fingerprint(bundle, repo_root_path)
    except FingerprintInputError as exc:
        duration_seconds = perf_counter() - start
        fingerprint_error = str(exc)
        skipped_configure = CommandExecution(
            command=construct_configure_command(configure_preset),
            return_code=FINGERPRINT_INPUT_ERROR_RETURN_CODE,
            stdout="",
            stderr=fingerprint_error,
            duration_seconds=0.0,
        )
        _write_build_log(
            log_path=log_path,
            repo_root=repo_root_path,
            configure=skipped_configure,
            build=None,
            return_code=FINGERPRINT_INPUT_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            artifact_exists=elf_path.is_file(),
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_inputs=[],
            build_fingerprint_algorithm=None,
            fingerprint_error=fingerprint_error,
            build_number=None,
            build_skip_reason="fingerprint_error",
            build_skip_detail=fingerprint_error,
            force_rebuild=force,
        )
        update_manifest(
            result_dir_path / "manifest.json",
            {
                "result": "build_failed",
                "build_number": None,
                "firmware": {
                    "artifact": artifact_relative_path.as_posix(),
                    "artifact_path": str(elf_path),
                    "artifact_exists": elf_path.is_file(),
                    "sha256": None,
                },
                "source": source,
                "build": {
                    "configure_preset": configure_preset,
                    "build_preset": build_preset,
                    "return_code": FINGERPRINT_INPUT_ERROR_RETURN_CODE,
                    "duration_seconds": round(duration_seconds, 3),
                    "log": "build.log",
                    "fingerprint": None,
                    "fingerprint_inputs": [],
                    "fingerprint_algorithm": None,
                    "fingerprint_error": fingerprint_error,
                    "skipped": False,
                    "skip_reason": "fingerprint_error",
                    "skip_detail": fingerprint_error,
                    "force": force,
                },
            },
        )
        return BuildResult(
            return_code=FINGERPRINT_INPUT_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            log_path=log_path,
            configure=skipped_configure,
            build=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_inputs=[],
            build_fingerprint_algorithm=None,
            build_number=None,
            result_artifacts={},
            build_record_dir=None,
            build_record_manifest_path=None,
            build_skipped=False,
            build_skip_reason="fingerprint_error",
        )

    generated_state_scope = f"cmake-{configure_preset}"
    generated_state_identity = build_identity(
        workflow="stm32_cmake",
        profile=f"{configure_preset}:{build_preset}",
        input_fingerprint={
            "algorithm": build_fingerprint.algorithm,
            "fingerprint": build_fingerprint.fingerprint,
            "inputs": build_fingerprint.inputs,
        },
        toolchain={
            "configure_command": construct_configure_command(configure_preset),
            "build_command": construct_build_command(build_preset),
        },
        execution=detect_execution_identity(),
    )
    state, state_error = _read_rebuild_state(repo_root_path)
    build_skipped, skip_reason, skip_detail = _rebuild_decision(
        current_fingerprint=build_fingerprint.fingerprint,
        current_algorithm=build_fingerprint.algorithm,
        state=state,
        state_error=state_error,
        elf_path=elf_path,
        force=force,
    )

    if build_skipped:
        firmware_sha256 = calculate_file_sha256(elf_path)
        result_artifacts = copy_firmware_artifacts_to_result(elf_path, result_dir_path)
        duration_seconds = perf_counter() - start
        skipped_configure = CommandExecution(
            command=construct_configure_command(configure_preset),
            return_code=0,
            stdout="Skipped because current build fingerprint matched local state.",
            stderr="",
            duration_seconds=0.0,
        )
        state_build = state.get("build", {}) if isinstance(state, dict) else {}
        state_run_id = state.get("run_id") if isinstance(state, dict) else None
        state_build_number = state.get("build_number") if isinstance(state, dict) else None
        _write_build_log(
            log_path=log_path,
            repo_root=repo_root_path,
            configure=skipped_configure,
            build=None,
            return_code=0,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            artifact_exists=True,
            firmware_sha256=firmware_sha256,
            build_fingerprint=build_fingerprint.fingerprint,
            build_fingerprint_inputs=build_fingerprint.inputs,
            build_fingerprint_algorithm=build_fingerprint.algorithm,
            build_number=state_build_number if isinstance(state_build_number, int) else None,
            build_skipped=True,
            build_skip_reason=skip_reason,
            build_skip_detail=skip_detail,
            force_rebuild=force,
        )
        build_record_path = None
        build_record_manifest_path = None
        if isinstance(state_build_number, int):
            build_record_build = {
                "configure_preset": configure_preset,
                "build_preset": build_preset,
                "return_code": 0,
                "duration_seconds": round(duration_seconds, 3),
                "log": "build.log",
                "fingerprint": build_fingerprint.fingerprint,
                "fingerprint_inputs": build_fingerprint.inputs,
                "fingerprint_algorithm": build_fingerprint.algorithm,
                "skipped": True,
                "skip_reason": skip_reason,
                "skip_detail": skip_detail,
                "force": force,
                "source_state_run_id": state_run_id if isinstance(state_run_id, str) else None,
                "source_state_build_number": state_build_number,
                "source_state_fingerprint": state_build.get("fingerprint") if isinstance(state_build, dict) else None,
            }
            build_record_path, _ = write_build_record(
                bundle=bundle,
                result_dir=result_dir_path,
                build_number=state_build_number,
                firmware_elf_path=elf_path,
                firmware_artifact=artifact_relative_path.as_posix(),
                firmware_artifact_path=str(elf_path),
                firmware_sha256=firmware_sha256,
                source=source,
                build=build_record_build,
                source_run_id=_current_run_id(result_dir_path),
                build_log_path=log_path,
            )
            build_record_manifest_path = build_record_path / "manifest.json"
        record_generated_state_success(
            repo_root=repo_root_path,
            scope=generated_state_scope,
            identity=generated_state_identity,
            artifacts=[elf_path],
            record_refs={
                "build_number": state_build_number if isinstance(state_build_number, int) else None,
                "build_record_manifest": None if build_record_manifest_path is None else str(build_record_manifest_path),
                "run_manifest": str(result_dir_path / "manifest.json"),
                "source": "compatible_legacy_build_state",
            },
        )
        update_manifest(
            result_dir_path / "manifest.json",
            {
                "result": "build_skipped",
                "build_number": state_build_number if isinstance(state_build_number, int) else None,
                "firmware": {
                    "artifact": artifact_relative_path.as_posix(),
                    "artifact_path": str(elf_path),
                    "artifact_exists": True,
                    "sha256": firmware_sha256,
                    "result_artifacts": result_artifacts,
                },
                "source": source,
                "build": {
                    "configure_preset": configure_preset,
                    "build_preset": build_preset,
                    "return_code": 0,
                    "duration_seconds": round(duration_seconds, 3),
                    "log": "build.log",
                    "fingerprint": build_fingerprint.fingerprint,
                    "fingerprint_inputs": build_fingerprint.inputs,
                    "fingerprint_algorithm": build_fingerprint.algorithm,
                    "skipped": True,
                    "skip_reason": skip_reason,
                    "skip_detail": skip_detail,
                    "force": force,
                    "source_state_run_id": state_run_id if isinstance(state_run_id, str) else None,
                    "source_state_build_number": state_build_number if isinstance(state_build_number, int) else None,
                    "source_state_fingerprint": state_build.get("fingerprint") if isinstance(state_build, dict) else None,
                    **_build_record_manifest_update(build_record_path),
                },
            },
        )
        return BuildResult(
            return_code=0,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            log_path=log_path,
            configure=skipped_configure,
            build=None,
            firmware_sha256=firmware_sha256,
            build_fingerprint=build_fingerprint.fingerprint,
            build_fingerprint_inputs=build_fingerprint.inputs,
            build_fingerprint_algorithm=build_fingerprint.algorithm,
            build_number=state_build_number if isinstance(state_build_number, int) else None,
            result_artifacts=result_artifacts,
            build_record_dir=build_record_path,
            build_record_manifest_path=build_record_manifest_path,
            build_skipped=True,
            build_skip_reason=skip_reason,
        )

    preflight_generated_state(
        repo_root=repo_root_path,
        scope=generated_state_scope,
        expected_identity=generated_state_identity,
        cleanup_paths=[Path("build") / configure_preset],
        final_artifact_paths=[elf_path],
    )

    try:
        build_number = reserve_next_build_number(repo_root_path)
    except BuildNumberError as exc:
        duration_seconds = perf_counter() - start
        build_number_error = str(exc)
        skipped_configure = CommandExecution(
            command=construct_configure_command(configure_preset),
            return_code=BUILD_NUMBER_ERROR_RETURN_CODE,
            stdout="",
            stderr=build_number_error,
            duration_seconds=0.0,
        )
        _write_build_log(
            log_path=log_path,
            repo_root=repo_root_path,
            configure=skipped_configure,
            build=None,
            return_code=BUILD_NUMBER_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            artifact_exists=elf_path.is_file(),
            firmware_sha256=None,
            build_fingerprint=build_fingerprint.fingerprint,
            build_fingerprint_inputs=build_fingerprint.inputs,
            build_fingerprint_algorithm=build_fingerprint.algorithm,
            build_number_error=build_number_error,
            build_number=None,
            build_skip_reason=skip_reason,
            build_skip_detail=skip_detail,
            force_rebuild=force,
        )
        update_manifest(
            result_dir_path / "manifest.json",
            {
                "result": "build_failed",
                "build_number": None,
                "firmware": {
                    "artifact": artifact_relative_path.as_posix(),
                    "artifact_path": str(elf_path),
                    "artifact_exists": elf_path.is_file(),
                    "sha256": None,
                },
                "source": source,
                "build": {
                    "configure_preset": configure_preset,
                    "build_preset": build_preset,
                    "return_code": BUILD_NUMBER_ERROR_RETURN_CODE,
                    "duration_seconds": round(duration_seconds, 3),
                    "log": "build.log",
                    "fingerprint": build_fingerprint.fingerprint,
                    "fingerprint_inputs": build_fingerprint.inputs,
                    "fingerprint_algorithm": build_fingerprint.algorithm,
                    "build_number_error": build_number_error,
                    "skipped": False,
                    "skip_reason": skip_reason,
                    "skip_detail": skip_detail,
                    "force": force,
                },
            },
        )
        return BuildResult(
            return_code=BUILD_NUMBER_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            log_path=log_path,
            configure=skipped_configure,
            build=None,
            firmware_sha256=None,
            build_fingerprint=build_fingerprint.fingerprint,
            build_fingerprint_inputs=build_fingerprint.inputs,
            build_fingerprint_algorithm=build_fingerprint.algorithm,
            build_number=None,
            result_artifacts={},
            build_record_dir=None,
            build_record_manifest_path=None,
            build_skipped=False,
            build_skip_reason=skip_reason,
        )

    configure_execution = runner(construct_configure_command(configure_preset), repo_root_path)

    build_execution: CommandExecution | None = None
    return_code = configure_execution.return_code

    if configure_execution.return_code == 0:
        build_execution = runner(construct_build_command(build_preset), repo_root_path)
        return_code = build_execution.return_code

    artifact_exists = elf_path.is_file()

    if return_code == 0 and not artifact_exists:
        return_code = ARTIFACT_MISSING_RETURN_CODE

    firmware_sha256 = calculate_file_sha256(elf_path) if return_code == 0 else None
    result_artifacts = (
        copy_firmware_artifacts_to_result(elf_path, result_dir_path) if return_code == 0 else {}
    )

    duration_seconds = perf_counter() - start

    _write_build_log(
        log_path=log_path,
        repo_root=repo_root_path,
        configure=configure_execution,
        build=build_execution,
        return_code=return_code,
        duration_seconds=duration_seconds,
        elf_path=elf_path,
        artifact_exists=artifact_exists,
        firmware_sha256=firmware_sha256,
        build_fingerprint=build_fingerprint.fingerprint,
        build_fingerprint_inputs=build_fingerprint.inputs,
        build_fingerprint_algorithm=build_fingerprint.algorithm,
        build_number=build_number,
        build_skipped=False,
        build_skip_reason=skip_reason,
        build_skip_detail=skip_detail,
        force_rebuild=force,
    )

    build_record_path = None
    build_record_manifest_path = None
    if return_code == 0:
        build_record_build = {
            "configure_preset": configure_preset,
            "build_preset": build_preset,
            "return_code": return_code,
            "duration_seconds": round(duration_seconds, 3),
            "log": "build.log",
            "fingerprint": build_fingerprint.fingerprint,
            "fingerprint_inputs": build_fingerprint.inputs,
            "fingerprint_algorithm": build_fingerprint.algorithm,
            "skipped": False,
            "skip_reason": skip_reason,
            "skip_detail": skip_detail,
            "force": force,
        }
        build_record_path, _ = write_build_record(
            bundle=bundle,
            result_dir=result_dir_path,
            build_number=build_number,
            firmware_elf_path=elf_path,
            firmware_artifact=artifact_relative_path.as_posix(),
            firmware_artifact_path=str(elf_path),
            firmware_sha256=firmware_sha256,
            source=source,
            build=build_record_build,
            source_run_id=_current_run_id(result_dir_path),
            build_log_path=log_path,
        )
        build_record_manifest_path = build_record_path / "manifest.json"

    updated_manifest = update_manifest(
        result_dir_path / "manifest.json",
        {
            "result": "build_passed" if return_code == 0 else "build_failed",
            "build_number": build_number,
            "firmware": {
                "artifact": artifact_relative_path.as_posix(),
                "artifact_path": str(elf_path),
                "artifact_exists": artifact_exists,
                "sha256": firmware_sha256,
                "result_artifacts": result_artifacts,
            },
            "source": source,
            "build": {
                "configure_preset": configure_preset,
                "build_preset": build_preset,
                "return_code": return_code,
                "duration_seconds": round(duration_seconds, 3),
                "log": "build.log",
                "fingerprint": build_fingerprint.fingerprint,
                "fingerprint_inputs": build_fingerprint.inputs,
                "fingerprint_algorithm": build_fingerprint.algorithm,
                "skipped": False,
                "skip_reason": skip_reason,
                "skip_detail": skip_detail,
                "force": force,
                **_build_record_manifest_update(build_record_path),
            },
        },
    )

    if return_code == 0 and firmware_sha256 is not None:
        record_last_successful_build_state(
            repo_root=repo_root_path,
            run_id=str(updated_manifest.get("run_id")) if updated_manifest.get("run_id") is not None else result_dir_path.name,
            build_number=build_number,
            build_fingerprint=build_fingerprint.fingerprint,
            build_fingerprint_algorithm=build_fingerprint.algorithm,
            build_fingerprint_inputs=build_fingerprint.inputs,
            firmware_artifact=artifact_relative_path.as_posix(),
            firmware_artifact_path=str(elf_path),
            firmware_sha256=firmware_sha256,
            result_artifacts=result_artifacts,
        )
        record_generated_state_success(
            repo_root=repo_root_path,
            scope=generated_state_scope,
            identity=generated_state_identity,
            artifacts=[elf_path],
            record_refs={
                "build_number": build_number,
                "build_record_manifest": None if build_record_manifest_path is None else str(build_record_manifest_path),
                "run_manifest": str(result_dir_path / "manifest.json"),
            },
        )

    return BuildResult(
        return_code=return_code,
        duration_seconds=duration_seconds,
        elf_path=elf_path,
        log_path=log_path,
        configure=configure_execution,
        build=build_execution,
        firmware_sha256=firmware_sha256,
        build_fingerprint=build_fingerprint.fingerprint,
        build_fingerprint_inputs=build_fingerprint.inputs,
        build_fingerprint_algorithm=build_fingerprint.algorithm,
        build_number=build_number,
        result_artifacts=result_artifacts,
        build_record_dir=build_record_path,
        build_record_manifest_path=build_record_manifest_path,
        build_skipped=False,
        build_skip_reason=skip_reason,
    )
