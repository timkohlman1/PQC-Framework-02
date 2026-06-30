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



# Phase 11.4 secure-boot artifact fingerprints are evidence fingerprints for
# generated wolfBoot/signing artifacts. They are intentionally separate from
# the baseline direct-flash rebuild-skip fingerprint because secure-boot uses
# a different build chain: wolfBoot make, direct RelocatedDebug CMake/Ninja,
# application signing, and two-artifact flashing.
SECURE_BOOT_FINGERPRINT_ALGORITHM = "sha256-secure-boot-inputs-v1"

DEFAULT_RELOCATED_APPLICATION_FINGERPRINT_INPUTS = [
    "Core",
    "Drivers",
    "CMakeLists.txt",
    "CMakePresets.json",
    "cmake",
    "STM32L4R5XX_FLASH_RELOCATED.ld",
    "startup_stm32l4r5xx.s",
    "stm32_basic_hal1.ioc",
]

DEFAULT_WOLFBOOT_SOURCE_FINGERPRINT_INPUTS = [
    "Makefile",
    "src",
    "hal",
    "include",
    "lib",
    "wolfcrypt",
    "tools/keytools/Makefile",
]

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


def calculate_existing_inputs_fingerprint(
    repo_root: Path | str,
    relative_inputs: Iterable[str],
    *,
    algorithm: str = SECURE_BOOT_FINGERPRINT_ALGORITHM,
) -> BuildFingerprint:
    """Calculate a fingerprint over the subset of inputs that currently exists.

    This helper is used for secure-boot evidence where some optional upstream
    wolfBoot directories may vary by submodule revision. Missing inputs are not
    silently claimed as covered; callers should record the requested input list
    separately when they need an audit trail. The returned ``inputs`` list is the
    exact repository-relative file list that was actually hashed.
    """

    repo_root_path = Path(repo_root)
    existing_inputs = [
        relative_input
        for relative_input in relative_inputs
        if (repo_root_path / relative_input).exists()
    ]
    if not existing_inputs:
        raise FingerprintInputError("No existing inputs were available for fingerprinting")

    files = _collect_files(repo_root_path, existing_inputs)
    file_entries = [
        {
            "path": _relative_path(path, repo_root_path),
            "sha256": _file_sha256(path),
        }
        for path in files
    ]
    payload = {
        "algorithm": algorithm,
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
        algorithm=algorithm,
    )


def default_relocated_application_fingerprint_inputs() -> list[str]:
    """Return the default input set for the relocated secure-boot application."""

    return list(DEFAULT_RELOCATED_APPLICATION_FINGERPRINT_INPUTS)


def default_wolfboot_fingerprint_inputs(
    *,
    profile_id: str,
    source_dir: str,
    config_template: str | None = None,
) -> list[str]:
    """Return secure-boot wolfBoot build fingerprint input candidates."""

    inputs = [
        f"configs/builds/{profile_id}.yaml",
        "scripts/framework/wolfboot_build.py",
    ]
    if config_template:
        inputs.append(config_template)
    source_prefix = source_dir.rstrip("/\\")
    inputs.extend(f"{source_prefix}/{relative}" for relative in DEFAULT_WOLFBOOT_SOURCE_FINGERPRINT_INPUTS)
    return inputs


def default_signing_fingerprint_inputs(*, profile_id: str) -> list[str]:
    """Return secure-boot application signing fingerprint input candidates."""

    return [
        f"configs/signing/{profile_id}.yaml",
        "scripts/framework/signing.py",
        *DEFAULT_RELOCATED_APPLICATION_FINGERPRINT_INPUTS,
    ]


def default_secure_boot_flash_fingerprint_inputs(*, experiment_id: str, boot_id: str | None = None) -> list[str]:
    """Return secure-boot flash workflow fingerprint input candidates.

    This evidence fingerprint intentionally covers more than the flash helper
    itself. The configured secure-boot artifacts are produced by the wolfBoot
    build helper, relocated application build, and signing helper before
    ``flash-secure-boot`` consumes them. Including those source/config inputs
    makes the recorded fingerprint useful for spotting stale artifacts when a
    source/config change occurred but the generated ELF/BIN files were not
    rebuilt.
    """

    inputs = [
        f"configs/experiments/{experiment_id}.yaml",
        "scripts/framework/secure_boot_flash.py",
        "scripts/framework/uart.py",
        "scripts/framework/manifest.py",
        "scripts/framework/wolfboot_build.py",
        "scripts/framework/signing.py",
        "configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml",
        "configs/signing/wolfboot_ecdsa_p256_app.yaml",
        "configs/wolfboot/stm32l4r5_ecdsa_p256.config",
        *DEFAULT_RELOCATED_APPLICATION_FINGERPRINT_INPUTS,
        "tools/wolfboot/Makefile",
        "tools/wolfboot/src/image.c",
        "tools/wolfboot/hal/stm32l4.c",
        "tools/wolfboot/hal/stm32l4xx_hal_conf.h",
        "tools/wolfboot/tools/keytools/Makefile",
    ]
    if boot_id:
        inputs.append(f"configs/boot/{boot_id}.yaml")
    return inputs
