#!/usr/bin/env python3
"""Minimal experiment framework CLI.

The initial supported commands are:

    python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml

The status command loads an experiment config, resolves the referenced board and
host configs, validates required fields, and prints a summary.

The create-run command creates a local results/<run_id>/ folder containing
manifest.json and notes.md.

The build command creates a local results/<run_id>/ folder, runs the configured
CMake build presets, captures stdout, stderr, return codes, duration, the output
ELF path, and writes results/<run_id>/build.log.

The status and create-run commands do not build firmware, flash hardware, open
UART devices, use SSH, or touch network resources. The build command builds
firmware locally but does not flash hardware, open UART devices, use SSH, or
touch network resources. The flash command requires either an explicit
--build-run provenance record or an explicit escape hatch. The build-flash
command builds firmware and, only if the build succeeds, flashes that artifact
through the configured gateway in the same result run folder. The monitor
command performs ad hoc bounded UART monitoring and writes timestamped logs
under results/adhoc/.
"""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from framework.artifacts import copy_artifact_to_result
from framework.build_records import resolve_verified_build_record
from framework.build import execute_build
from framework.flash import execute_flash
from framework.manifest import create_result_folder, read_manifest, update_manifest
from framework.uart import DEFAULT_CAPTURE_DURATION_SECONDS, DEFAULT_RESTART_COMMAND, execute_uart_capture, execute_uart_monitor


class ConfigError(Exception):
    """Raised when a framework configuration file is invalid."""


def _parse_scalar(value: str) -> Any:
    """Parse a small YAML scalar value.

    This parser intentionally supports only the simple YAML subset currently used
    by the framework configuration files: nested mappings and scalar values.
    """

    value = value.strip()

    if value == "":
        return ""

    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    if value.lower() == "true":
        return True

    if value.lower() == "false":
        return False

    try:
        return int(value)
    except ValueError:
        return value


def load_config(path: Path | str) -> dict[str, Any]:
    """Load a simple YAML mapping from a config file."""

    config_path = Path(path)

    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for line_number, raw_line in enumerate(
        config_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))

        if indent % 2 != 0:
            raise ConfigError(
                f"{config_path}:{line_number}: indentation must use multiples of two spaces"
            )

        line = raw_line.strip()

        if ":" not in line:
            raise ConfigError(f"{config_path}:{line_number}: expected 'key: value'")

        key, value = line.split(":", 1)
        key = key.strip()

        if not key:
            raise ConfigError(f"{config_path}:{line_number}: empty key")

        while stack and indent <= stack[-1][0]:
            stack.pop()

        if not stack:
            raise ConfigError(f"{config_path}:{line_number}: invalid indentation")

        parent = stack[-1][1]

        if value.strip() == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value)

    return root


def require_field(config: dict[str, Any], dotted_path: str, config_name: str) -> Any:
    """Return a required dotted-path field from a nested mapping."""

    current: Any = config

    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ConfigError(f"{config_name} missing required field: {dotted_path}")
        current = current[part]

    if current is None or current == "":
        raise ConfigError(f"{config_name} has empty required field: {dotted_path}")

    return current


def validate_experiment_config(config: dict[str, Any]) -> None:
    """Validate required fields for the initial experiment config schema."""

    required_fields = [
        "id",
        "description",
        "board",
        "host",
        "firmware.mode",
        "firmware.artifact",
        "uart.expected_boot_message",
        "uart.expected_tick_message",
    ]

    for field in required_fields:
        require_field(config, field, "experiment config")


def validate_board_config(config: dict[str, Any]) -> None:
    """Validate required fields for the initial board config schema."""

    required_fields = [
        "id",
        "name",
        "mcu",
        "description",
        "stlink.serial",
        "uart.baud",
    ]

    for field in required_fields:
        require_field(config, field, "board config")


def validate_host_config(config: dict[str, Any]) -> None:
    """Validate required fields for the initial host config schema."""

    required_fields = [
        "id",
        "alias",
        "user",
        "description",
        "flash.helper",
        "uart.device",
        "uart.baud",
    ]

    for field in required_fields:
        require_field(config, field, "host config")


def _configs_root_from_experiment_path(experiment_path: Path) -> Path:
    """Resolve the configs root from configs/experiments/<name>.yaml."""

    resolved_path = experiment_path.resolve()

    if resolved_path.parent.name != "experiments":
        raise ConfigError(
            "Experiment config must live under configs/experiments/ for automatic "
            "board and host resolution"
        )

    return resolved_path.parent.parent


def repo_root_from_experiment_path(experiment_path: Path | str) -> Path:
    """Resolve the repository root from configs/experiments/<name>.yaml."""

    configs_root = _configs_root_from_experiment_path(Path(experiment_path))
    return configs_root.parent


def resolve_related_config_paths(experiment_path: Path | str) -> tuple[Path, Path]:
    """Resolve board and host config paths referenced by an experiment config."""

    experiment_config_path = Path(experiment_path)
    experiment_config = load_config(experiment_config_path)
    validate_experiment_config(experiment_config)

    configs_root = _configs_root_from_experiment_path(experiment_config_path)
    board_id = require_field(experiment_config, "board", "experiment config")
    host_id = require_field(experiment_config, "host", "experiment config")

    board_path = configs_root / "boards" / f"{board_id}.yaml"
    host_path = configs_root / "hosts" / f"{host_id}.yaml"

    return board_path, host_path


def load_experiment_bundle(experiment_path: Path | str) -> dict[str, dict[str, Any]]:
    """Load and validate an experiment plus its referenced board and host configs."""

    experiment_config_path = Path(experiment_path)

    experiment_config = load_config(experiment_config_path)
    validate_experiment_config(experiment_config)

    board_path, host_path = resolve_related_config_paths(experiment_config_path)

    board_config = load_config(board_path)
    host_config = load_config(host_path)

    validate_board_config(board_config)
    validate_host_config(host_config)

    expected_board_id = require_field(experiment_config, "board", "experiment config")
    actual_board_id = require_field(board_config, "id", "board config")

    if actual_board_id != expected_board_id:
        raise ConfigError(
            f"board config id mismatch: experiment references '{expected_board_id}' "
            f"but {board_path} contains '{actual_board_id}'"
        )

    expected_host_id = require_field(experiment_config, "host", "experiment config")
    actual_host_id = require_field(host_config, "id", "host config")

    if actual_host_id != expected_host_id:
        raise ConfigError(
            f"host config id mismatch: experiment references '{expected_host_id}' "
            f"but {host_path} contains '{actual_host_id}'"
        )

    return {
        "experiment": experiment_config,
        "board": board_config,
        "host": host_config,
    }


def format_status_summary(bundle: dict[str, dict[str, Any]]) -> str:
    """Format a human-readable status summary."""

    experiment = bundle["experiment"]
    board = bundle["board"]
    host = bundle["host"]

    return "\n".join(
        [
            "Experiment status",
            "-----------------",
            f"Experiment ID: {experiment['id']}",
            f"Description: {experiment['description']}",
            f"Board: {board['id']} ({board['name']}, {board['mcu']})",
            f"ST-LINK serial: {board['stlink']['serial']}",
            f"Host: {host['id']} ({host['alias']}, user {host['user']})",
            f"Flash helper: {host['flash']['helper']}",
            f"Firmware mode: {experiment['firmware']['mode']}",
            f"Firmware artifact: {experiment['firmware']['artifact']}",
            f"UART device: {host['uart']['device']}",
            f"UART baud: {host['uart']['baud']}",
            f"Expected boot message: {experiment['uart']['expected_boot_message']}",
            f"Expected tick message: {experiment['uart']['expected_tick_message']}",
            "",
            "Actions performed: status only.",
            "No build, flash, UART access, SSH, hardware access, or network access was performed.",
        ]
    )


def run_status_command(args: argparse.Namespace) -> int:
    """Run the status command."""

    bundle = load_experiment_bundle(args.experiment)
    print(format_status_summary(bundle))
    return 0


def run_create_run_command(args: argparse.Namespace) -> int:
    """Run the create-run command."""

    bundle = load_experiment_bundle(args.experiment)
    result_dir, manifest = create_result_folder(bundle, args.results_dir)

    print("Result manifest created")
    print("-----------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Manifest: {result_dir / 'manifest.json'}")
    print(f"Notes: {result_dir / 'notes.md'}")
    print(
        "No build, flash, UART access, SSH, hardware access, or network access was performed."
    )

    return 0


def run_build_command(args: argparse.Namespace) -> int:
    """Run the build command."""

    bundle = load_experiment_bundle(args.experiment)
    result_dir, manifest = create_result_folder(bundle, args.results_dir)
    repo_root = repo_root_from_experiment_path(args.experiment)
    configure_preset = args.configure_preset or args.build_preset

    build_result = execute_build(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        configure_preset=configure_preset,
        build_preset=args.build_preset,
        force=getattr(args, "force", False),
    )

    if getattr(build_result, "build_skipped", False):
        print("Firmware build skipped")
    else:
        print("Firmware build completed" if build_result.return_code == 0 else "Firmware build failed")
    print("----------------------" if getattr(build_result, "build_skipped", False) else ("------------------------" if build_result.return_code == 0 else "---------------------"))
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Build log: {build_result.log_path}")
    print(f"ELF path: {build_result.elf_path}")
    print(f"Return code: {build_result.return_code}")
    print(f"Build skipped: {getattr(build_result, 'build_skipped', False)}")
    if getattr(build_result, "build_skip_reason", None):
        print(f"Build skip reason: {build_result.build_skip_reason}")
    if getattr(build_result, "build_number", None) is not None:
        print(f"Build number: {build_result.build_number}")
    if getattr(build_result, "build_record_dir", None) is not None:
        print(f"Build record: {build_result.build_record_dir}")
    print(f"Build duration seconds: {build_result.duration_seconds:.3f}")
    print("No flash, UART access, SSH, hardware access, or network access was performed.")

    return build_result.return_code




def _maybe_capture_uart_after_flash(
    *,
    args: argparse.Namespace,
    bundle: dict[str, dict[str, Any]],
    repo_root: Path,
    result_dir: Path,
    stage_result_name: str,
) -> int:
    """Capture UART after a successful flash when requested by the CLI."""

    if not getattr(args, "capture_uart", False):
        return 0

    uart_result = execute_uart_capture(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        duration_seconds=args.uart_duration_seconds,
        restart_command=_monitor_restart_command(bundle, None),
    )

    if uart_result.return_code == 0:
        update_manifest(
            result_dir / "manifest.json",
            {
                "result": f"{stage_result_name}_uart_passed",
            },
        )
    else:
        update_manifest(
            result_dir / "manifest.json",
            {
                "result": f"{stage_result_name}_uart_failed",
            },
        )

    return uart_result.return_code


def run_flash_command(args: argparse.Namespace) -> int:
    """Run the remote flash command."""

    bundle = load_experiment_bundle(args.experiment)
    result_dir, manifest = create_result_folder(bundle, args.results_dir)
    repo_root = repo_root_from_experiment_path(args.experiment)
    flash_result = execute_flash(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        source_build_run_id=args.build_run,
        allow_untracked_artifact=args.allow_untracked_artifact,
    )

    final_return_code = flash_result.return_code
    uart_return_code: int | None = None
    if flash_result.return_code == 0 and args.capture_uart:
        uart_return_code = _maybe_capture_uart_after_flash(
            args=args,
            bundle=bundle,
            repo_root=repo_root,
            result_dir=result_dir,
            stage_result_name="flash",
        )
        final_return_code = uart_return_code
    elif flash_result.return_code != 0 and args.capture_uart:
        update_manifest(
            result_dir / "manifest.json",
            {
                "uart": {
                    "log": None,
                    "skipped": True,
                    "skip_reason": "flash_failed",
                },
            },
        )

    print("Remote flash completed" if final_return_code == 0 else "Remote flash failed")
    print("----------------------" if final_return_code == 0 else "-------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Flash log: {flash_result.log_path}")
    print(f"Local artifact: {flash_result.artifact_path}")
    print(f"Remote artifact: {flash_result.remote_artifact_path}")
    print(f"ST-LINK serial: {flash_result.stlink_serial}")
    print(f"Flash return code: {flash_result.return_code}")
    print(f"Provenance status: {flash_result.provenance_status}")
    if args.capture_uart:
        if uart_return_code is None:
            print("UART capture skipped because flash failed.")
        else:
            print(f"UART log: {result_dir / 'uart.log'}")
            print(f"UART return code: {uart_return_code}")
    else:
        print("No UART access was performed.")
    print(f"Return code: {final_return_code}")

    return final_return_code


def run_build_flash_command(args: argparse.Namespace) -> int:
    """Build firmware and flash the produced artifact in one result run."""

    bundle = load_experiment_bundle(args.experiment)
    result_dir, manifest = create_result_folder(bundle, args.results_dir)
    repo_root = repo_root_from_experiment_path(args.experiment)
    configure_preset = args.configure_preset or args.build_preset

    build_result = execute_build(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        configure_preset=configure_preset,
        build_preset=args.build_preset,
        force=getattr(args, "force", False),
    )

    if build_result.return_code != 0:
        update_manifest(
            result_dir / "manifest.json",
            {
                "result": "build_flash_failed",
                "build_flash": {
                    "return_code": build_result.return_code,
                    "build_return_code": build_result.return_code,
                    "flash_return_code": None,
                    "uart_return_code": None,
                    "build_log": "build.log",
                    "flash_log": None,
                    "uart_log": None,
                    "flash_skipped": True,
                    "uart_skipped": True,
                    "failure_stage": "build",
                    "duration_seconds": round(build_result.duration_seconds, 3),
                },
            },
        )

        print("Build-flash failed during build")
        print("------------------------------")
        print(f"Run ID: {manifest['run_id']}")
        print(f"Result directory: {result_dir}")
        print(f"Build log: {build_result.log_path}")
        print(f"ELF path: {build_result.elf_path}")
        print(f"Return code: {build_result.return_code}")
        print("Flash step skipped because the build failed.")
        print("No flash, UART access, SSH, hardware access, or network access was performed.")
        return build_result.return_code

    flash_result = execute_flash(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        source_build_run_id=manifest["run_id"],
    )

    uart_return_code: int | None = None
    uart_duration_seconds = 0.0
    if flash_result.return_code == 0 and args.capture_uart:
        uart_result = execute_uart_capture(
            bundle=bundle,
            repo_root=repo_root,
            result_dir=result_dir,
            duration_seconds=args.uart_duration_seconds,
            restart_command=_monitor_restart_command(bundle, None),
        )
        uart_return_code = uart_result.return_code
        uart_duration_seconds = uart_result.duration_seconds
    elif flash_result.return_code != 0 and args.capture_uart:
        update_manifest(
            result_dir / "manifest.json",
            {
                "uart": {
                    "log": None,
                    "skipped": True,
                    "skip_reason": "flash_failed",
                },
            },
        )

    if flash_result.return_code != 0:
        final_return_code = flash_result.return_code
        failure_stage = "flash"
    elif uart_return_code is not None and uart_return_code != 0:
        final_return_code = uart_return_code
        failure_stage = "uart"
    else:
        final_return_code = 0
        failure_stage = "none"

    update_manifest(
        result_dir / "manifest.json",
        {
            "result": "build_flash_passed" if final_return_code == 0 else "build_flash_failed",
            "build_flash": {
                "return_code": final_return_code,
                "build_return_code": build_result.return_code,
                "flash_return_code": flash_result.return_code,
                "uart_return_code": uart_return_code,
                "build_log": "build.log",
                "flash_log": "flash.log",
                "uart_log": "uart.log" if uart_return_code is not None else None,
                "flash_skipped": False,
                "uart_skipped": not args.capture_uart or flash_result.return_code != 0,
                "failure_stage": failure_stage,
                "duration_seconds": round(
                    build_result.duration_seconds
                    + flash_result.duration_seconds
                    + uart_duration_seconds,
                    3,
                ),
            },
        },
    )

    print("Build-flash completed" if final_return_code == 0 else f"Build-flash failed during {failure_stage}")
    print("---------------------" if final_return_code == 0 else "-------------------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Build log: {build_result.log_path}")
    print(f"Flash log: {flash_result.log_path}")
    if args.capture_uart and uart_return_code is not None:
        print(f"UART log: {result_dir / 'uart.log'}")
        print(f"UART return code: {uart_return_code}")
    elif args.capture_uart:
        print("UART capture skipped because flash failed.")
    else:
        print("No UART access was performed.")
    print(f"ELF path: {build_result.elf_path}")
    print(f"Remote artifact: {flash_result.remote_artifact_path}")
    print(f"ST-LINK serial: {flash_result.stlink_serial}")
    print(f"Flash return code: {flash_result.return_code}")
    print(f"Return code: {final_return_code}")
    print(f"Provenance status: {flash_result.provenance_status}")

    return final_return_code



def _copy_artifact_to_result_accepts_destination_name() -> bool:
    """Return whether the active artifact-copy helper accepts a destination name.

    Some unit tests monkeypatch ``copy_artifact_to_result`` with the earlier
    two-argument helper shape. The production helper accepts a third
    destination-name argument so the baseline run can retain the ELF as the
    canonical ``firmware.elf``. This check keeps the production behaviour while
    allowing existing mocked tests to remain focused on orchestration.
    """

    try:
        signature = inspect.signature(copy_artifact_to_result)
    except (TypeError, ValueError):
        return True

    parameters = list(signature.parameters.values())
    positional_parameters = [
        parameter
        for parameter in parameters
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        )
    ]

    if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
        return True

    return len(positional_parameters) >= 3


def _record_run_summary(
    *,
    result_dir: Path,
    final_return_code: int,
    failure_stage: str,
    build_return_code: int | None,
    flash_return_code: int | None,
    uart_return_code: int | None,
    artifact_copy_return_code: int | None,
    copied_artifact_path: Path | None,
    duration_seconds: float,
    referenced_build_number: int | None = None,
    referenced_build_artifact_sha256: str | None = None,
    referenced_build_manifest: Path | None = None,
) -> None:
    """Record the first-class automated baseline run summary."""

    manifest_path = result_dir / "manifest.json"
    manifest = read_manifest(manifest_path)
    firmware = manifest.get("firmware", {})
    if not isinstance(firmware, dict):
        firmware = {}
    firmware = dict(firmware)
    firmware["result_artifact"] = (
        copied_artifact_path.name if copied_artifact_path is not None else None
    )
    firmware["result_artifact_path"] = (
        str(copied_artifact_path) if copied_artifact_path is not None else None
    )
    if referenced_build_artifact_sha256 is not None:
        firmware["sha256"] = referenced_build_artifact_sha256

    build_reference = None
    if referenced_build_number is not None:
        existing_build_reference = manifest.get("build_reference")
        build_reference = (
            dict(existing_build_reference)
            if isinstance(existing_build_reference, dict)
            else {}
        )
        build_reference.update(
            {
                "build_number": referenced_build_number,
                "artifact_sha256": referenced_build_artifact_sha256,
                "record_manifest": None
                if referenced_build_manifest is None
                else str(referenced_build_manifest),
            }
        )

    update_manifest(
        manifest_path,
        {
            "result": "baseline_run_passed" if final_return_code == 0 else "baseline_run_failed",
            "firmware": firmware,
            "build_reference": build_reference,
            "run": {
                "return_code": final_return_code,
                "build_return_code": build_return_code,
                "referenced_build_number": referenced_build_number,
                "referenced_build_artifact_sha256": referenced_build_artifact_sha256,
                "artifact_copy_return_code": artifact_copy_return_code,
                "flash_return_code": flash_return_code,
                "uart_return_code": uart_return_code,
                "build_log": None if referenced_build_number is not None else "build.log",
                "flash_log": "flash.log" if flash_return_code is not None else None,
                "uart_log": "uart.log" if uart_return_code is not None else None,
                "copied_artifact": (
                    copied_artifact_path.name if copied_artifact_path is not None else None
                ),
                "failure_stage": failure_stage,
                "duration_seconds": round(duration_seconds, 3),
            },
        },
    )



def _record_build_reference_failure(
    *,
    result_dir: Path,
    verification_result: Any,
    duration_seconds: float,
) -> None:
    """Record a refused existing-build reference before hardware-facing stages."""

    update_manifest(
        result_dir / "manifest.json",
        {
            "result": "baseline_run_failed",
            "build_reference": {
                "build_number": verification_result.build_number,
                "status": verification_result.status,
                "return_code": verification_result.return_code,
                "message": verification_result.message,
                "record_manifest": None
                if verification_result.manifest_path is None
                else str(verification_result.manifest_path),
                "artifact_path": None
                if verification_result.artifact_path is None
                else str(verification_result.artifact_path),
                "artifact_sha256": verification_result.firmware_sha256,
                "build_fingerprint": verification_result.build_fingerprint,
                "current_build_fingerprint": verification_result.current_build_fingerprint,
                "current_build_fingerprint_error": verification_result.current_build_fingerprint_error,
            },
            "run": {
                "return_code": verification_result.return_code,
                "build_return_code": None,
                "referenced_build_number": verification_result.build_number,
                "referenced_build_artifact_sha256": verification_result.firmware_sha256,
                "artifact_copy_return_code": None,
                "flash_return_code": None,
                "uart_return_code": None,
                "build_log": None,
                "flash_log": None,
                "uart_log": None,
                "copied_artifact": None,
                "failure_stage": "build_reference",
                "duration_seconds": round(duration_seconds, 3),
            },
        },
    )


def _run_full_baseline_with_existing_build(
    *,
    args: argparse.Namespace,
    bundle: dict[str, dict[str, Any]],
    repo_root: Path,
    result_dir: Path,
    manifest: dict[str, Any],
    start: float,
) -> int:
    """Run flash and UART against a verified first-class build record."""

    from time import perf_counter

    build_number = args.build_number
    verification = resolve_verified_build_record(
        results_root=args.results_dir,
        build_number=build_number,
        bundle=bundle,
        repo_root=repo_root,
    )

    if verification.return_code != 0:
        _record_build_reference_failure(
            result_dir=result_dir,
            verification_result=verification,
            duration_seconds=perf_counter() - start,
        )
        print("Baseline run refused build reference")
        print("-----------------------------------")
        print(f"Run ID: {manifest['run_id']}")
        print(f"Result directory: {result_dir}")
        print(f"Build number: {build_number}")
        print(f"Reason: {verification.message}")
        print(f"Return code: {verification.return_code}")
        return verification.return_code

    assert verification.artifact_path is not None
    assert verification.manifest_path is not None

    copied_artifact_path: Path | None = None
    try:
        if _copy_artifact_to_result_accepts_destination_name():
            copied_artifact_path = copy_artifact_to_result(
                verification.artifact_path,
                result_dir,
                "firmware.elf",
            )
        else:
            copied_artifact_path = copy_artifact_to_result(
                verification.artifact_path,
                result_dir,
            )
        artifact_copy_return_code = 0
    except OSError as exc:
        artifact_copy_return_code = 11
        update_manifest(
            result_dir / "manifest.json",
            {"artifact_copy_error": str(exc)},
        )
        _record_run_summary(
            result_dir=result_dir,
            final_return_code=artifact_copy_return_code,
            failure_stage="artifact_copy",
            build_return_code=None,
            artifact_copy_return_code=artifact_copy_return_code,
            flash_return_code=None,
            uart_return_code=None,
            copied_artifact_path=None,
            duration_seconds=perf_counter() - start,
            referenced_build_number=build_number,
            referenced_build_artifact_sha256=verification.firmware_sha256,
            referenced_build_manifest=verification.manifest_path,
        )
        print("Baseline run failed while copying referenced build artifact")
        print("----------------------------------------------------------")
        print(f"Run ID: {manifest['run_id']}")
        print(f"Result directory: {result_dir}")
        print(f"Build number: {build_number}")
        print(f"Error: {exc}")
        print(f"Return code: {artifact_copy_return_code}")
        return artifact_copy_return_code

    update_manifest(
        result_dir / "manifest.json",
        {
            "build_number": build_number,
            "build_reference": {
                "build_number": build_number,
                "status": verification.status,
                "return_code": verification.return_code,
                "message": verification.message,
                "record_path": None if verification.record_dir is None else str(verification.record_dir),
                "record_manifest": str(verification.manifest_path),
                "artifact_path": str(verification.artifact_path),
                "artifact_sha256": verification.firmware_sha256,
                "build_fingerprint": verification.build_fingerprint,
                "build_fingerprint_algorithm": verification.build_fingerprint_algorithm,
                "current_build_fingerprint": verification.current_build_fingerprint,
                "current_build_fingerprint_algorithm": verification.current_build_fingerprint_algorithm,
            },
            "firmware": {
                "artifact": bundle["experiment"]["firmware"]["artifact"],
                "artifact_path": str(verification.artifact_path),
                "artifact_exists": True,
                "sha256": verification.firmware_sha256,
                "result_artifact": copied_artifact_path.name,
                "result_artifact_path": str(copied_artifact_path),
            },
        },
    )

    flash_result = execute_flash(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        source_build_run_id=None,
        source_build_number=build_number,
        source_build_manifest_path=verification.manifest_path,
        artifact_path_override=copied_artifact_path,
    )

    if flash_result.return_code != 0:
        update_manifest(
            result_dir / "manifest.json",
            {
                "uart": {
                    "log": None,
                    "skipped": True,
                    "skip_reason": "flash_failed",
                },
            },
        )
        _record_run_summary(
            result_dir=result_dir,
            final_return_code=flash_result.return_code,
            failure_stage="flash",
            build_return_code=None,
            artifact_copy_return_code=artifact_copy_return_code,
            flash_return_code=flash_result.return_code,
            uart_return_code=None,
            copied_artifact_path=copied_artifact_path,
            duration_seconds=perf_counter() - start,
            referenced_build_number=build_number,
            referenced_build_artifact_sha256=verification.firmware_sha256,
            referenced_build_manifest=verification.manifest_path,
        )
        print("Baseline run failed during flash")
        print("--------------------------------")
        print(f"Run ID: {manifest['run_id']}")
        print(f"Result directory: {result_dir}")
        print(f"Build number: {build_number}")
        print(f"Copied artifact: {copied_artifact_path}")
        print(f"Flash log: {flash_result.log_path}")
        print(f"Return code: {flash_result.return_code}")
        return flash_result.return_code

    uart_result = execute_uart_capture(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        duration_seconds=args.uart_duration_seconds,
        restart_command=_monitor_restart_command(bundle, None),
    )

    final_return_code = uart_result.return_code
    failure_stage = "none" if final_return_code == 0 else "uart"
    _record_run_summary(
        result_dir=result_dir,
        final_return_code=final_return_code,
        failure_stage=failure_stage,
        build_return_code=None,
        artifact_copy_return_code=artifact_copy_return_code,
        flash_return_code=flash_result.return_code,
        uart_return_code=uart_result.return_code,
        copied_artifact_path=copied_artifact_path,
        duration_seconds=perf_counter() - start,
        referenced_build_number=build_number,
        referenced_build_artifact_sha256=verification.firmware_sha256,
        referenced_build_manifest=verification.manifest_path,
    )

    print("Baseline run passed" if final_return_code == 0 else "Baseline run failed during uart")
    print("-------------------" if final_return_code == 0 else "-------------------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Build number: {build_number}")
    print(f"Copied artifact: {copied_artifact_path}")
    print(f"Flash log: {flash_result.log_path}")
    print(f"UART log: {uart_result.log_path}")
    print(f"Return code: {final_return_code}")
    return final_return_code


def run_full_baseline_command(args: argparse.Namespace) -> int:
    """Run the known-good automated baseline from build through UART verdict."""

    from time import perf_counter

    bundle = load_experiment_bundle(args.experiment)
    result_dir, manifest = create_result_folder(bundle, args.results_dir)
    repo_root = repo_root_from_experiment_path(args.experiment)
    configure_preset = args.configure_preset or args.build_preset
    start = perf_counter()

    if getattr(args, "build_number", None) is not None:
        return _run_full_baseline_with_existing_build(
            args=args,
            bundle=bundle,
            repo_root=repo_root,
            result_dir=result_dir,
            manifest=manifest,
            start=start,
        )

    build_result = execute_build(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        configure_preset=configure_preset,
        build_preset=args.build_preset,
        force=getattr(args, "force", False),
    )

    if build_result.return_code != 0:
        _record_run_summary(
            result_dir=result_dir,
            final_return_code=build_result.return_code,
            failure_stage="build",
            build_return_code=build_result.return_code,
            artifact_copy_return_code=None,
            flash_return_code=None,
            uart_return_code=None,
            copied_artifact_path=None,
            duration_seconds=perf_counter() - start,
        )
        print("Baseline run failed during build")
        print("--------------------------------")
        print(f"Run ID: {manifest['run_id']}")
        print(f"Result directory: {result_dir}")
        print(f"Build log: {build_result.log_path}")
        print(f"Return code: {build_result.return_code}")
        return build_result.return_code

    copied_artifact_path: Path | None = None
    try:
        if _copy_artifact_to_result_accepts_destination_name():
            copied_artifact_path = copy_artifact_to_result(
                build_result.elf_path,
                result_dir,
                "firmware.elf",
            )
        else:
            copied_artifact_path = copy_artifact_to_result(
                build_result.elf_path,
                result_dir,
            )
        artifact_copy_return_code = 0
    except OSError as exc:
        artifact_copy_return_code = 11
        update_manifest(
            result_dir / "manifest.json",
            {"artifact_copy_error": str(exc)},
        )
        _record_run_summary(
            result_dir=result_dir,
            final_return_code=artifact_copy_return_code,
            failure_stage="artifact_copy",
            build_return_code=build_result.return_code,
            artifact_copy_return_code=artifact_copy_return_code,
            flash_return_code=None,
            uart_return_code=None,
            copied_artifact_path=None,
            duration_seconds=perf_counter() - start,
        )
        print("Baseline run failed while copying artifact")
        print("------------------------------------------")
        print(f"Run ID: {manifest['run_id']}")
        print(f"Result directory: {result_dir}")
        print(f"Error: {exc}")
        print(f"Return code: {artifact_copy_return_code}")
        return artifact_copy_return_code

    flash_result = execute_flash(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        source_build_run_id=manifest["run_id"],
    )

    if flash_result.return_code != 0:
        update_manifest(
            result_dir / "manifest.json",
            {
                "uart": {
                    "log": None,
                    "skipped": True,
                    "skip_reason": "flash_failed",
                },
            },
        )
        _record_run_summary(
            result_dir=result_dir,
            final_return_code=flash_result.return_code,
            failure_stage="flash",
            build_return_code=build_result.return_code,
            artifact_copy_return_code=artifact_copy_return_code,
            flash_return_code=flash_result.return_code,
            uart_return_code=None,
            copied_artifact_path=copied_artifact_path,
            duration_seconds=perf_counter() - start,
        )
        print("Baseline run failed during flash")
        print("--------------------------------")
        print(f"Run ID: {manifest['run_id']}")
        print(f"Result directory: {result_dir}")
        print(f"Build log: {build_result.log_path}")
        print(f"Copied artifact: {copied_artifact_path}")
        print(f"Flash log: {flash_result.log_path}")
        print(f"Return code: {flash_result.return_code}")
        return flash_result.return_code

    uart_result = execute_uart_capture(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        duration_seconds=args.uart_duration_seconds,
        restart_command=_monitor_restart_command(bundle, None),
    )

    final_return_code = uart_result.return_code
    failure_stage = "none" if final_return_code == 0 else "uart"
    _record_run_summary(
        result_dir=result_dir,
        final_return_code=final_return_code,
        failure_stage=failure_stage,
        build_return_code=build_result.return_code,
        artifact_copy_return_code=artifact_copy_return_code,
        flash_return_code=flash_result.return_code,
        uart_return_code=uart_result.return_code,
        copied_artifact_path=copied_artifact_path,
        duration_seconds=perf_counter() - start,
    )

    print("Baseline run passed" if final_return_code == 0 else "Baseline run failed during uart")
    print("-------------------" if final_return_code == 0 else "-------------------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Build log: {build_result.log_path}")
    print(f"Copied artifact: {copied_artifact_path}")
    print(f"Flash log: {flash_result.log_path}")
    print(f"UART log: {uart_result.log_path}")
    print(f"Return code: {final_return_code}")
    return final_return_code

def _monitor_restart_command(bundle: dict[str, dict[str, Any]], override: str | None) -> str:
    """Resolve the gateway restart command for ad hoc UART monitoring."""

    if override:
        return override

    reset_config = bundle["host"].get("reset", {})
    if isinstance(reset_config, dict):
        helper = reset_config.get("helper")
        if helper:
            return str(helper)

    return DEFAULT_RESTART_COMMAND


def run_monitor_command(args: argparse.Namespace) -> int:
    """Run ad hoc bounded UART monitoring."""

    bundle = load_experiment_bundle(args.experiment)
    repo_root = repo_root_from_experiment_path(args.experiment)
    restart_command = _monitor_restart_command(bundle, args.restart_command)

    monitor_result = execute_uart_monitor(
        bundle=bundle,
        repo_root=repo_root,
        results_root=args.results_dir,
        duration_seconds=args.duration_seconds,
        restart=args.restart,
        restart_command=restart_command,
    )

    print("UART monitor passed" if monitor_result.return_code == 0 else "UART monitor failed")
    print("-------------------" if monitor_result.return_code == 0 else "-------------------")
    print(f"Ad hoc log: {monitor_result.log_path}")
    print(f"UART device: {monitor_result.device}")
    print(f"UART baud: {monitor_result.baud}")
    print(f"Monitor duration seconds: {monitor_result.requested_duration_seconds}")
    print(f"Restart requested: {monitor_result.restart_requested}")
    print(f"Data captured: {monitor_result.data_captured}")
    print(f"Capture return code: {monitor_result.capture.return_code}")
    print(f"Return code: {monitor_result.return_code}")
    print("No result manifest, build, or flash action was performed.")

    return monitor_result.return_code


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""

    parser = argparse.ArgumentParser(
        description="PQC experiment framework CLI",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser(
        "status",
        help="Load and validate an experiment config, then print a summary.",
    )
    status_parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to an experiment YAML config.",
    )
    status_parser.set_defaults(func=run_status_command)

    create_run_parser = subparsers.add_parser(
        "create-run",
        help="Create a local result run folder for an experiment config.",
    )
    create_run_parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to an experiment YAML config.",
    )
    create_run_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where result run folders are created.",
    )
    create_run_parser.set_defaults(func=run_create_run_command)

    build_parser = subparsers.add_parser(
        "build",
        help="Build firmware for an experiment config without flashing hardware.",
    )
    build_parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to an experiment YAML config.",
    )
    build_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where result run folders are created.",
    )
    build_parser.add_argument(
        "--build-preset",
        default="Debug",
        help="CMake build preset to invoke.",
    )
    build_parser.add_argument(
        "--configure-preset",
        default=None,
        help="CMake configure preset to invoke. Defaults to --build-preset.",
    )
    build_parser.add_argument(
        "--force",
        action="store_true",
        help="Run CMake configure/build even when the local build hash state allows a safe rebuild skip.",
    )
    build_parser.set_defaults(func=run_build_command)

    flash_parser = subparsers.add_parser(
        "flash",
        help="Copy the configured ELF to the gateway and invoke its flash helper.",
    )
    flash_parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to an experiment YAML config.",
    )
    flash_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where result run folders are created.",
    )
    flash_parser.add_argument(
        "--build-run",
        default=None,
        help="Existing build run ID whose manifest must match the ELF being flashed.",
    )
    flash_parser.add_argument(
        "--allow-untracked-artifact",
        action="store_true",
        help="Explicit escape hatch: allow flashing without a matching build record.",
    )
    flash_parser.add_argument(
        "--capture-uart",
        action="store_true",
        help="After successful flash, capture UART into this run directory and evaluate expected markers.",
    )
    flash_parser.add_argument(
        "--uart-duration-seconds",
        default=DEFAULT_CAPTURE_DURATION_SECONDS,
        type=int,
        help="Bounded post-flash UART capture duration in seconds.",
    )
    flash_parser.set_defaults(func=run_flash_command)

    build_flash_parser = subparsers.add_parser(
        "build-flash",
        help="Build firmware and flash the resulting ELF in one result run.",
    )
    build_flash_parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to an experiment YAML config.",
    )
    build_flash_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where result run folders are created.",
    )
    build_flash_parser.add_argument(
        "--build-preset",
        default="Debug",
        help="CMake build preset to invoke before flashing.",
    )
    build_flash_parser.add_argument(
        "--configure-preset",
        default=None,
        help="CMake configure preset to invoke. Defaults to --build-preset.",
    )
    build_flash_parser.add_argument(
        "--force",
        action="store_true",
        help="Run CMake configure/build even when the local build hash state allows a safe rebuild skip.",
    )
    build_flash_parser.add_argument(
        "--capture-uart",
        action="store_true",
        help="After successful flash, capture UART into this run directory and evaluate expected markers.",
    )
    build_flash_parser.add_argument(
        "--uart-duration-seconds",
        default=DEFAULT_CAPTURE_DURATION_SECONDS,
        type=int,
        help="Bounded post-flash UART capture duration in seconds.",
    )
    build_flash_parser.set_defaults(func=run_build_flash_command)


    run_parser = subparsers.add_parser(
        "run",
        help="Run the known-good automated baseline: build, retain artifact, flash, capture UART, and evaluate pass/fail.",
    )
    run_parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to an experiment YAML config.",
    )
    run_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where result run folders are created.",
    )
    run_parser.add_argument(
        "--build-number",
        default=None,
        type=int,
        help="Use an existing first-class build record from results/builds/<build-number> instead of creating a new build.",
    )
    run_parser.add_argument(
        "--build-preset",
        default="Debug",
        help="CMake build preset to invoke before flashing.",
    )
    run_parser.add_argument(
        "--configure-preset",
        default=None,
        help="CMake configure preset to invoke. Defaults to --build-preset.",
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        help="Run CMake configure/build even when the local build hash state allows a safe rebuild skip.",
    )
    run_parser.add_argument(
        "--uart-duration-seconds",
        default=DEFAULT_CAPTURE_DURATION_SECONDS,
        type=int,
        help="Bounded UART capture duration used for the baseline pass/fail verdict.",
    )
    run_parser.set_defaults(func=run_full_baseline_command)

    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Ad hoc bounded UART monitoring through the configured gateway.",
    )
    monitor_parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to an experiment YAML config.",
    )
    monitor_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where the adhoc UART log folder is created.",
    )
    monitor_parser.add_argument(
        "--duration-seconds",
        default=DEFAULT_CAPTURE_DURATION_SECONDS,
        type=int,
        help="Bounded UART monitor duration in seconds.",
    )
    monitor_parser.add_argument(
        "--restart",
        action="store_true",
        help="Run the configured gateway restart helper during monitoring after UART capture starts.",
    )
    monitor_parser.add_argument(
        "--restart-command",
        default=None,
        help="Override gateway command used by --restart. Defaults to host reset.helper when configured.",
    )
    monitor_parser.set_defaults(func=run_monitor_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
