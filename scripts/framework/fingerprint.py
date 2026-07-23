"""Build input fingerprint helpers.

This module calculates a deterministic fingerprint for the small set of
configuration and firmware inputs that currently determine the local ELF build.
It performs no hardware, network, UART, SSH, or toolchain actions.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

BUILD_FINGERPRINT_ALGORITHM = "sha256-build-inputs-and-tools-v3"



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

# Optional roots are limited to source/configuration trees that can contribute
# to the selected STM32 targets. Directory collection applies the build-input
# file filter below, so generated objects, credentials, docs, examples, tests,
# repository metadata, and unrelated upstream project files are not hashed.
OPTIONAL_FIRMWARE_FINGERPRINT_INPUTS = [
    "ST67W6X/Target",
    "LWIP/App",
    "Middlewares/ST/ST67W6X_Network_Driver",
    "Middlewares/Third_Party/FreeRTOS/Source",
    "Middlewares/Third_Party/SICS_Network_LwIP/LwIP",
    "Middlewares/Third_Party/wolfMQTT/src",
    "Middlewares/Third_Party/wolfMQTT/wolfmqtt",
    "tools/wolfboot/lib/wolfssl/src",
    "tools/wolfboot/lib/wolfssl/wolfcrypt/src",
    "tools/wolfboot/lib/wolfssl/wolfssl",
    "scripts/framework/build.py",
    "scripts/framework/fingerprint.py",
]

BUILD_INPUT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
    ".s", ".S", ".asm", ".ld", ".cmake", ".json", ".yaml", ".yml",
    ".ioc", ".in",
}
BUILD_INPUT_FILENAMES = {"CMakeLists.txt", "CMakePresets.json", "Makefile"}
EXCLUDED_PATH_PARTS = {
    ".git", ".github", ".vscode", "__pycache__", "build", "results",
    "examples", "tests", "test", "docs", "doc", "certs", "IDE", "zephyr",
}


def _is_build_input_file(path: Path) -> bool:
    """Return whether a discovered file can affect the selected firmware build."""

    if any(part in EXCLUDED_PATH_PARTS for part in path.parts):
        return False
    return path.name in BUILD_INPUT_FILENAMES or path.suffix in BUILD_INPUT_SUFFIXES

DEFAULT_BUILD_TOOL_COMMANDS = {
    "cmake": ["cmake", "--version"],
    "arm_none_eabi_gcc": ["arm-none-eabi-gcc", "--version"],
    "ninja": ["ninja", "--version"],
    "python": [sys.executable, "--version"],
}


class FingerprintInputError(Exception):
    """Raised when a required build fingerprint input is unavailable."""


class BuildFingerprint(NamedTuple):
    """A deterministic build fingerprint and the evidence it covered."""

    fingerprint: str
    inputs: list[str]
    file_hashes: dict[str, str]
    algorithm: str = BUILD_FINGERPRINT_ALGORITHM
    tool_versions: dict[str, str] | None = None


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
                (path for path in input_path.rglob("*") if path.is_file() and _is_build_input_file(path)),
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


def capture_build_tool_versions(
    commands: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    """Capture stable version evidence for tools that can affect build output.

    Missing tools are recorded explicitly rather than ignored. In the normal
    container build environment the required build tools must be available; the
    explicit marker keeps fingerprint calculation deterministic in unit-test
    fixtures and makes incomplete provenance visible in manifests.
    """

    selected = DEFAULT_BUILD_TOOL_COMMANDS if commands is None else commands
    versions: dict[str, str] = {}
    for name, command in sorted(selected.items()):
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            versions[name] = f"unavailable:{type(exc).__name__}"
            continue
        output = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        versions[name] = f"return_code={completed.returncode};output={output}"
    return versions


def _existing_optional_inputs(repo_root: Path, relative_inputs: Iterable[str]) -> list[str]:
    return [item for item in relative_inputs if (repo_root / item).exists()]

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

    mqtt = experiment.get("mqtt", {})
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    certificate_refs = tls.get("certificate_refs", {}) if isinstance(tls, dict) else {}
    ca_certificate = (
        certificate_refs.get("ca_certificate")
        if isinstance(certificate_refs, dict)
        else None
    )
    if ca_certificate is not None:
        ca_certificate_path = str(ca_certificate).strip()
        if ca_certificate_path:
            inputs.append(ca_certificate_path)

    return [
        *inputs,
        *DEFAULT_FIRMWARE_FINGERPRINT_INPUTS,
    ]


def calculate_build_fingerprint(
    repo_root: Path | str,
    relative_inputs: Iterable[str],
    *,
    tool_versions: dict[str, str] | None = None,
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

    captured_tool_versions = (
        capture_build_tool_versions() if tool_versions is None else dict(tool_versions)
    )
    payload = {
        "algorithm": BUILD_FINGERPRINT_ALGORITHM,
        "files": file_entries,
        "tools": captured_tool_versions,
    }

    encoded_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return BuildFingerprint(
        fingerprint=hashlib.sha256(encoded_payload).hexdigest(),
        inputs=[entry["path"] for entry in file_entries],
        file_hashes={entry["path"]: entry["sha256"] for entry in file_entries},
        tool_versions=captured_tool_versions,
    )


def calculate_default_build_fingerprint(
    bundle: dict[str, dict[str, object]],
    repo_root: Path | str,
    *,
    tool_versions: dict[str, str] | None = None,
) -> BuildFingerprint:
    """Calculate the fingerprint for all discovered default build inputs."""

    repo_root_path = Path(repo_root)
    relative_inputs = [
        *default_build_fingerprint_inputs(bundle),
        *_existing_optional_inputs(repo_root_path, OPTIONAL_FIRMWARE_FINGERPRINT_INPUTS),
    ]
    return calculate_build_fingerprint(
        repo_root=repo_root_path,
        relative_inputs=relative_inputs,
        tool_versions=tool_versions,
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
    captured_tool_versions = capture_build_tool_versions()
    payload = {
        "algorithm": algorithm,
        "files": file_entries,
        "tools": captured_tool_versions,
    }
    encoded_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return BuildFingerprint(
        fingerprint=hashlib.sha256(encoded_payload).hexdigest(),
        inputs=[entry["path"] for entry in file_entries],
        file_hashes={entry["path"]: entry["sha256"] for entry in file_entries},
        algorithm=algorithm,
        tool_versions=captured_tool_versions,
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

    profile_by_experiment = {
        "wolfboot_ecdsa_p256_uart": (
            "configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml",
            "configs/signing/wolfboot_ecdsa_p256_app.yaml",
            "configs/wolfboot/stm32l4r5_ecdsa_p256.config",
        ),
        "wolfboot_ed25519_uart": (
            "configs/builds/wolfboot_stm32l4_ed25519.yaml",
            "configs/signing/wolfboot_ed25519_app.yaml",
            "configs/wolfboot/stm32l4r5_ed25519.config",
        ),
        "wolfboot_rsa2048_uart": (
            "configs/builds/wolfboot_stm32l4_rsa2048.yaml",
            "configs/signing/wolfboot_rsa2048_app.yaml",
            "configs/wolfboot/stm32l4r5_rsa2048.config",
        ),
        "wolfboot_ecc384_uart": (
            "configs/builds/wolfboot_stm32l4_ecc384.yaml",
            "configs/signing/wolfboot_ecc384_app.yaml",
            "configs/wolfboot/stm32l4r5_ecc384.config",
        ),
        "wolfboot_ecc521_uart": (
            "configs/builds/wolfboot_stm32l4_ecc521.yaml",
            "configs/signing/wolfboot_ecc521_app.yaml",
            "configs/wolfboot/stm32l4r5_ecc521.config",
        ),
        "wolfboot_ed448_uart": (
            "configs/builds/wolfboot_stm32l4_ed448.yaml",
            "configs/signing/wolfboot_ed448_app.yaml",
            "configs/wolfboot/stm32l4r5_ed448.config",
        ),
        "wolfboot_rsa3072_uart": (
            "configs/builds/wolfboot_stm32l4_rsa3072.yaml",
            "configs/signing/wolfboot_rsa3072_app.yaml",
            "configs/wolfboot/stm32l4r5_rsa3072.config",
        ),
        "wolfboot_rsa4096_uart": (
            "configs/builds/wolfboot_stm32l4_rsa4096.yaml",
            "configs/signing/wolfboot_rsa4096_app.yaml",
            "configs/wolfboot/stm32l4r5_rsa4096.config",
        ),
    }
    wolfboot_build_profile, signing_profile, wolfboot_config_template = profile_by_experiment.get(
        experiment_id,
        profile_by_experiment["wolfboot_ecdsa_p256_uart"],
    )

    inputs = [
        f"configs/experiments/{experiment_id}.yaml",
        "scripts/framework/secure_boot_flash.py",
        "scripts/framework/uart.py",
        "scripts/framework/manifest.py",
        "scripts/framework/wolfboot_build.py",
        "scripts/framework/signing.py",
        wolfboot_build_profile,
        signing_profile,
        wolfboot_config_template,
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
