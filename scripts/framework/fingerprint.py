"""Build input fingerprint helpers.

This module calculates a deterministic fingerprint for the small set of
configuration and firmware inputs that currently determine the local ELF build.
It performs no hardware, network, UART, SSH, or toolchain actions.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, NamedTuple

BUILD_FINGERPRINT_ALGORITHM = "sha256-build-inputs-v1"

DEFAULT_FIRMWARE_FINGERPRINT_INPUTS = [
    "Core",
    "Drivers",
    "CMakeLists.txt",
    "CMakePresets.json",
    "cmake",
    "STM32L4R5XX_FLASH.ld",
    "startup_stm32l4r5xx.s",
    "stm32_basic_hal1.ioc",
]


class FingerprintInputError(Exception):
    """Raised when a required build fingerprint input is unavailable."""


class BuildFingerprint(NamedTuple):
    """A deterministic build input fingerprint and the paths it covered."""

    fingerprint: str
    inputs: list[str]
    algorithm: str = BUILD_FINGERPRINT_ALGORITHM


def _relative_path(path: Path, repo_root: Path) -> str:
    """Return a stable POSIX-style repository-relative path."""

    return path.relative_to(repo_root).as_posix()


def _file_sha256(path: Path) -> str:
    """Return a SHA-256 hex digest for one input file."""

    digest = hashlib.sha256()

    with path.open("rb") as file_object:
        for chunk in iter(lambda: file_object.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _collect_files(repo_root: Path, relative_inputs: Iterable[str]) -> list[Path]:
    """Resolve required input files from files and directories."""

    collected: list[Path] = []

    for relative_input in relative_inputs:
        input_path = repo_root / relative_input

        if not input_path.exists():
            raise FingerprintInputError(
                f"Required build fingerprint input is missing: {relative_input}"
            )

        if input_path.is_file():
            collected.append(input_path)
            continue

        if input_path.is_dir():
            files = sorted(
                (path for path in input_path.rglob("*") if path.is_file()),
                key=lambda path: _relative_path(path, repo_root),
            )

            if not files:
                raise FingerprintInputError(
                    f"Required build fingerprint input directory has no files: {relative_input}"
                )

            collected.extend(files)
            continue

        raise FingerprintInputError(
            f"Required build fingerprint input is not a regular file or directory: {relative_input}"
        )

    return sorted(collected, key=lambda path: _relative_path(path, repo_root))


def default_build_fingerprint_inputs(bundle: dict[str, dict[str, object]]) -> list[str]:
    """Return the current conservative build fingerprint input set.

    The configuration paths are resolved from the currently implemented config
    model: configs/experiments/<experiment>.yaml references board, host, and boot IDs,
    which resolve to configs/boards/<board>.yaml, configs/hosts/<host>.yaml, and configs/boot/<boot>.yaml.
    """

    experiment = bundle["experiment"]
    board = bundle["board"]
    host = bundle["host"]
    boot = bundle.get("boot", {})

    experiment_id = str(experiment["id"])
    board_id = str(board["id"])
    host_id = str(host["id"])
    boot_id = str(boot.get("id", experiment.get("boot", "")))

    inputs = [
        f"configs/experiments/{experiment_id}.yaml",
        f"configs/boards/{board_id}.yaml",
        f"configs/hosts/{host_id}.yaml",
    ]

    if boot_id:
        inputs.append(f"configs/boot/{boot_id}.yaml")

    return [
        *inputs,
        *DEFAULT_FIRMWARE_FINGERPRINT_INPUTS,
    ]


def calculate_build_fingerprint(
    repo_root: Path | str,
    relative_inputs: Iterable[str],
) -> BuildFingerprint:
    """Calculate the deterministic build input fingerprint.

    The aggregate hash is calculated from a stable JSON payload containing each
    input file's repository-relative path and its individual content SHA-256.
    Including both path and content avoids collisions where different files have
    identical bytes or where path changes are meaningful to the build.
    """

    repo_root_path = Path(repo_root)
    files = _collect_files(repo_root_path, relative_inputs)

    file_entries = [
        {
            "path": _relative_path(path, repo_root_path),
            "sha256": _file_sha256(path),
        }
        for path in files
    ]

    payload = {
        "algorithm": BUILD_FINGERPRINT_ALGORITHM,
        "files": file_entries,
    }

    encoded_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return BuildFingerprint(
        fingerprint=hashlib.sha256(encoded_payload).hexdigest(),
        inputs=[entry["path"] for entry in file_entries],
    )


def calculate_default_build_fingerprint(
    bundle: dict[str, dict[str, object]],
    repo_root: Path | str,
) -> BuildFingerprint:
    """Calculate the fingerprint for the current default build input set."""

    return calculate_build_fingerprint(
        repo_root=repo_root,
        relative_inputs=default_build_fingerprint_inputs(bundle),
    )
