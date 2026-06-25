#!/usr/bin/env python3
"""Minimal experiment framework CLI.

The first supported command is:

    python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml

The status command loads an experiment config, resolves the referenced board and
host configs, validates required fields, and prints a summary.

It does not build firmware, flash hardware, open UART devices, use SSH, or touch
network resources.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


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
    