"""Remote firmware flash helpers for experiment runs.

This module copies the configured ELF artifact to the experiment gateway with
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
) -> None:
    lines = [
        "Remote firmware flash log",
        "=========================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root: {repo_root}",
        f"Local artifact path: {artifact_path}",
        f"Remote artifact path: {remote_artifact_path}",
        f"ST-LINK serial: {stlink_serial}",
        f"Final return code: {return_code}",
        f"Total duration seconds: {duration_seconds:.3f}",
        "",
    ]
    if scp_execution is None:
        lines += ["SCP step", "--------", "Skipped because the local artifact was not found.", ""]
    else:
        lines += ["SCP step", "--------", _format_execution(scp_execution, repo_root)]
    if flash_execution is None:
        reason = "Skipped because the SCP step failed." if scp_execution is not None else "Skipped because the local artifact was not found."
        lines += ["Flash step", "----------", reason, ""]
    else:
        lines += ["Flash step", "----------", _format_execution(flash_execution, repo_root)]
    log_path.write_text("\n".join(lines), encoding="utf-8")


def execute_flash(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
    result_dir: Path | str,
    runner: Runner = default_runner,
) -> FlashResult:
    """Stage and remotely flash the configured artifact, then update the manifest."""

    repo_root_path = Path(repo_root)
    result_dir_path = Path(result_dir)
    log_path = result_dir_path / "flash.log"
    artifact_relative_path = Path(str(bundle["experiment"]["firmware"]["artifact"]))
    artifact_path = repo_root_path / artifact_relative_path
    remote_artifact_path = str(PurePosixPath("/tmp") / artifact_path.name)
    gateway_alias = str(bundle["host"]["alias"])
    flash_helper = str(bundle["host"]["flash"]["helper"])
    stlink_serial = str(bundle["board"]["stlink"]["serial"])

    start = perf_counter()
    scp_execution: CommandExecution | None = None
    flash_execution: CommandExecution | None = None

    if not artifact_path.is_file():
        return_code = ARTIFACT_MISSING_RETURN_CODE
    else:
        scp_execution = runner(
            construct_scp_command(artifact_path, gateway_alias, remote_artifact_path),
            repo_root_path,
        )
        return_code = scp_execution.return_code
        if return_code == 0:
            flash_execution = runner(
                construct_ssh_flash_command(gateway_alias, flash_helper, remote_artifact_path),
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
    )
    update_manifest(
        result_dir_path / "manifest.json",
        {
            "result": "flash_passed" if return_code == 0 else "flash_failed",
            "firmware": {
                "artifact": artifact_relative_path.as_posix(),
                "artifact_path": str(artifact_path),
                "artifact_exists": artifact_path.is_file(),
            },
            "flash": {
                "return_code": return_code,
                "duration_seconds": round(duration_seconds, 3),
                "log": "flash.log",
                "remote_artifact_path": remote_artifact_path,
                "stlink_serial": stlink_serial,
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
    )
