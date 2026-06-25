#!/usr/bin/env python3
"""Minimal experiment framework CLI.

The initial supported commands are:

    python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml
    python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml

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
through the configured gateway in the same result run folder.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from framework.build import execute_build
from framework.flash import execute_flash
from framework.manifest import create_result_folder, update_manifest


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
    )

    print("Firmware build completed" if build_result.return_code == 0 else "Firmware build failed")
    print("------------------------" if build_result.return_code == 0 else "---------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Build log: {build_result.log_path}")
    print(f"ELF path: {build_result.elf_path}")
    print(f"Return code: {build_result.return_code}")
    print(f"Build duration seconds: {build_result.duration_seconds:.3f}")
    print("No flash, UART access, SSH, hardware access, or network access was performed.")

    return build_result.return_code



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

    print("Remote flash completed" if flash_result.return_code == 0 else "Remote flash failed")
    print("----------------------" if flash_result.return_code == 0 else "-------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Flash log: {flash_result.log_path}")
    print(f"Local artifact: {flash_result.artifact_path}")
    print(f"Remote artifact: {flash_result.remote_artifact_path}")
    print(f"ST-LINK serial: {flash_result.stlink_serial}")
    print(f"Return code: {flash_result.return_code}")
    print(f"Provenance status: {flash_result.provenance_status}")
    print("No UART access was performed.")

    return flash_result.return_code


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
                    "build_log": "build.log",
                    "flash_log": None,
                    "flash_skipped": True,
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

    final_return_code = flash_result.return_code
    update_manifest(
        result_dir / "manifest.json",
        {
            "result": "build_flash_passed" if final_return_code == 0 else "build_flash_failed",
            "build_flash": {
                "return_code": final_return_code,
                "build_return_code": build_result.return_code,
                "flash_return_code": flash_result.return_code,
                "build_log": "build.log",
                "flash_log": "flash.log",
                "flash_skipped": False,
                "failure_stage": "none" if final_return_code == 0 else "flash",
                "duration_seconds": round(
                    build_result.duration_seconds + flash_result.duration_seconds, 3
                ),
            },
        },
    )

    print("Build-flash completed" if final_return_code == 0 else "Build-flash failed during flash")
    print("---------------------" if final_return_code == 0 else "-------------------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Build log: {build_result.log_path}")
    print(f"Flash log: {flash_result.log_path}")
    print(f"ELF path: {build_result.elf_path}")
    print(f"Remote artifact: {flash_result.remote_artifact_path}")
    print(f"ST-LINK serial: {flash_result.stlink_serial}")
    print(f"Return code: {final_return_code}")
    print(f"Provenance status: {flash_result.provenance_status}")
    print("No UART access was performed.")

    return final_return_code


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
    build_flash_parser.set_defaults(func=run_build_flash_command)

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
