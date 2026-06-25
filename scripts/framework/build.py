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

from framework.artifacts import calculate_file_sha256
from framework.manifest import update_manifest

ARTIFACT_MISSING_RETURN_CODE = 3


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
) -> None:
    """Write the build log for one experiment build run."""

    lines = [
        "Firmware build log",
        "==================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root: {repo_root}",
        f"Output ELF path: {elf_path}",
        f"Output ELF exists: {str(artifact_exists).lower()}",
        f"Output ELF SHA-256: {firmware_sha256 if firmware_sha256 is not None else 'unavailable'}",
        f"Final return code: {return_code}",
        f"Total duration seconds: {duration_seconds:.3f}",
        "",
        "Configure step",
        "--------------",
        _format_execution(configure, repo_root),
    ]

    if build is None:
        lines.extend(
            [
                "Build step",
                "----------",
                "Skipped because the configure step failed.",
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

    if return_code == ARTIFACT_MISSING_RETURN_CODE:
        lines.extend(
            [
                "Artifact check",
                "--------------",
                "CMake returned success, but the expected ELF artifact was not found.",
                "",
            ]
        )

    log_path.write_text("\n".join(lines), encoding="utf-8")


def execute_build(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
    result_dir: Path | str,
    configure_preset: str = "Debug",
    build_preset: str = "Debug",
    runner: Runner = default_runner,
) -> BuildResult:
    """Run the local CMake build process and update the result manifest.

    The configure and build commands are intentionally injectable so unit tests
    can verify command construction and result handling without invoking CMake.
    """

    repo_root_path = Path(repo_root)
    result_dir_path = Path(result_dir)
    log_path = result_dir_path / "build.log"
    artifact_relative_path = Path(str(bundle["experiment"]["firmware"]["artifact"]))
    elf_path = repo_root_path / artifact_relative_path

    start = perf_counter()
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
    )

    update_manifest(
        result_dir_path / "manifest.json",
        {
            "result": "build_passed" if return_code == 0 else "build_failed",
            "firmware": {
                "artifact": artifact_relative_path.as_posix(),
                "artifact_path": str(elf_path),
                "artifact_exists": artifact_exists,
                "sha256": firmware_sha256,
            },
            "build": {
                "configure_preset": configure_preset,
                "build_preset": build_preset,
                "return_code": return_code,
                "duration_seconds": round(duration_seconds, 3),
                "log": "build.log",
            },
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
    )
