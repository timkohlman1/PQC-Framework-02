"""Build input fingerprint helpers.

This module calculates a deterministic fingerprint for the small set of
configuration and firmware inputs that currently determine the local ELF build.
It performs no hardware, network, UART, SSH, or toolchain actions.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import shlex
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable, NamedTuple

from framework.tls_algorithms import resolve_tls_algorithm_set

BUILD_FINGERPRINT_ALGORITHM = "sha256-build-relevant-inputs-and-tools-v4"
CONFIGURED_BUILD_FINGERPRINT_ALGORITHM = "sha256-prebuild-compiler-dependencies-v3"



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

DEFAULT_FIRMWARE_BUILD_DEFINITION_INPUTS = [
    "CMakeLists.txt",
    "CMakePresets.json",
    "cmake/stm32cubemx/CMakeLists.txt",
    "cmake/gcc-arm-none-eabi.cmake",
]

# These modules directly resolve build inputs, generate build configuration, or
# invoke CMake. They are explicit rather than discovered recursively so an
# unrelated framework helper cannot invalidate a firmware build.
DEFAULT_BUILD_ORCHESTRATION_INPUTS = [
    "scripts/framework/build.py",
    "scripts/framework/fingerprint.py",
    "scripts/framework/external_dependencies.py",
    "scripts/framework/tls_algorithms.py",
]

_SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".s", ".S", ".asm"}
_HEADER_SUFFIXES = {".h", ".hh", ".hpp", ".hxx", ".inc"}
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.MULTILINE)
_CMAKE_SOURCE_RE = re.compile(
    r"(?P<token>(?:\$\{[A-Za-z0-9_]+\}|[A-Za-z0-9_./+\-])+\.(?:cc|cpp|cxx|asm|c|s|S))(?=$|[\s\)\"'])"
)

# Source entries declared by CubeMX but explicitly filtered out before target
# creation. These files are not compiled or linked into the firmware image.
_CMAKE_EXCLUDED_SOURCE_PATTERNS = (
    re.compile(r"^LWIP/App/(?:altls_mbedtls|sntp|dhcp_server_raw|http_client)\.c$"),
    re.compile(r"^Middlewares/ST/ST67W6X_Network_Driver/Utils/Performance/"),
    re.compile(r"^Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_(?:ble|http|mqtt)\.c$"),
)


def _normalise_cmake_source_token(token: str) -> str | None:
    replacements = {
        "${CMAKE_CURRENT_SOURCE_DIR}/../../": "",
        "${CMAKE_SOURCE_DIR}/": "",
        "${PQC_WOLFSSL_SOURCE_DIR}/": "tools/wolfboot/lib/wolfssl/",
        "${PQC_WOLFMQTT_SOURCE_DIR}/": "Middlewares/Third_Party/wolfMQTT/",
    }
    value = token
    for prefix, replacement in replacements.items():
        if value.startswith(prefix):
            value = replacement + value[len(prefix):]
            break
    if "${" in value or value.startswith("/"):
        return None
    return Path(value).as_posix()


def _source_is_enabled(relative_path: str, tls_algorithms: dict[str, Any]) -> bool:
    if any(pattern.search(relative_path) for pattern in _CMAKE_EXCLUDED_SOURCE_PATTERNS):
        return False
    if relative_path.endswith("/rsa.c") and not bool(tls_algorithms.get("enable_rsa")):
        return False
    if relative_path.endswith(("/sha3.c", "/wc_mlkem.c", "/wc_mlkem_poly.c")) and not bool(
        tls_algorithms.get("enable_mlkem_768")
    ):
        return False
    return True


def _declared_firmware_sources(repo_root: Path, tls_algorithms: dict[str, Any]) -> list[str]:
    """Return source files explicitly declared by the configured CMake target."""

    sources: set[str] = set()
    for cmake_path in (repo_root / "CMakeLists.txt", repo_root / "cmake/stm32cubemx/CMakeLists.txt"):
        if not cmake_path.is_file():
            raise FingerprintInputError(
                f"Required build fingerprint input is missing: {cmake_path.relative_to(repo_root).as_posix()}"
            )
        for match in _CMAKE_SOURCE_RE.finditer(cmake_path.read_text(encoding="utf-8")):
            relative = _normalise_cmake_source_token(match.group("token"))
            if relative and Path(relative).suffix in _SOURCE_SUFFIXES and _source_is_enabled(relative, tls_algorithms):
                sources.add(relative)
    return sorted(sources)


def _repository_header_index(repo_root: Path) -> dict[str, list[str]]:
    """Index repository headers by include spelling without hashing whole trees."""

    index: dict[str, list[str]] = {}
    excluded_roots = {".git", "build", "results", "tests", "docs", "examples", "certs"}
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix not in _HEADER_SUFFIXES:
            continue
        relative = path.relative_to(repo_root)
        if any(part in excluded_roots for part in relative.parts):
            continue
        rel = relative.as_posix()
        index.setdefault(path.name, []).append(rel)
        index.setdefault(rel, []).append(rel)
    return index


def _resolve_compiled_headers(repo_root: Path, sources: Iterable[str]) -> list[str]:
    """Resolve repository headers reached from compiled sources and headers."""

    index = _repository_header_index(repo_root)
    resolved: set[str] = set()
    queue = list(sources)
    visited: set[str] = set()
    while queue:
        relative = queue.pop()
        if relative in visited:
            continue
        visited.add(relative)
        path = repo_root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for include in _INCLUDE_RE.findall(text):
            local = (path.parent / include).resolve()
            try:
                local_relative = local.relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                local_relative = ""
            candidate = None
            if local_relative and (repo_root / local_relative).is_file():
                candidate = local_relative
            else:
                matches = index.get(include, []) or index.get(Path(include).name, [])
                unique = sorted(set(matches))
                if len(unique) == 1:
                    candidate = unique[0]
                elif unique:
                    suffix_matches = [item for item in unique if item.endswith("/" + include) or item == include]
                    if len(suffix_matches) == 1:
                        candidate = suffix_matches[0]
            if candidate and candidate not in resolved:
                resolved.add(candidate)
                queue.append(candidate)
    return sorted(resolved)

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
    """Return whether a generic directory fingerprint input is build-relevant."""

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


def _hash_paths(paths: Iterable[Path], *, workers: int = 12) -> dict[Path, str]:
    """Hash independent files concurrently to reduce bind-mount latency."""

    selected = list(paths)
    if not selected:
        return {}
    with ThreadPoolExecutor(max_workers=min(workers, len(selected))) as executor:
        digests = executor.map(_file_sha256, selected)
    return dict(zip(selected, digests, strict=True))


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


def _experiment_profile_input(repo_root: Path, experiment_id: str) -> str:
    """Return the repository-relative path for a flat or nested experiment profile."""

    flat = Path("configs/experiments") / f"{experiment_id}.yaml"
    if (repo_root / flat).exists():
        return flat.as_posix()
    matches = sorted((repo_root / "configs/experiments").rglob(f"{experiment_id}.yaml"))
    if len(matches) == 1:
        return matches[0].relative_to(repo_root).as_posix()
    return flat.as_posix()

def default_build_fingerprint_inputs(
    bundle: dict[str, dict[str, object]],
    repo_root: Path | str | None = None,
    *,
    configure_preset: str = "Debug",
) -> list[str]:
    """Return only files that can affect the selected firmware build."""

    experiment = bundle["experiment"]
    board = bundle["board"]
    host = bundle["host"]
    boot = bundle.get("boot", {})
    experiment_id = str(experiment["id"])
    board_id = str(board["id"])
    host_id = str(host["id"])
    boot_id = str(boot.get("id", experiment.get("boot", "")))
    inputs = [
        _experiment_profile_input(Path(repo_root or "."), experiment_id),
        f"configs/boards/{board_id}.yaml",
        f"configs/hosts/{host_id}.yaml",
        *DEFAULT_FIRMWARE_BUILD_DEFINITION_INPUTS,
    ]
    if boot_id:
        inputs.append(f"configs/boot/{boot_id}.yaml")

    linker_script = (
        "STM32L4R5XX_FLASH_RELOCATED.ld"
        if configure_preset.lower().startswith("relocated")
        else "STM32L4R5XX_FLASH.ld"
    )
    inputs.extend([linker_script, "startup_stm32l4r5xx.s"])

    mqtt = experiment.get("mqtt", {})
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    certificate_refs = tls.get("certificate_refs", {}) if isinstance(tls, dict) else {}
    if isinstance(certificate_refs, dict):
        for reference_name in ("ca_certificate", "client_certificate"):
            reference = certificate_refs.get(reference_name)
            if reference is not None and str(reference).strip():
                inputs.append(str(reference).strip())

    if repo_root is not None:
        root = Path(repo_root)
        tls_algorithms = resolve_tls_algorithm_set(bundle)
        sources = _declared_firmware_sources(root, tls_algorithms)
        inputs.extend(sources)
        inputs.extend(
            item for item in DEFAULT_BUILD_ORCHESTRATION_INPUTS if (root / item).is_file()
        )
    return sorted(set(inputs))


def calculate_build_fingerprint(
    repo_root: Path | str,
    relative_inputs: Iterable[str],
    *,
    tool_versions: dict[str, str] | None = None,
    semantic_inputs: dict[str, Any] | None = None,
) -> BuildFingerprint:
    """Calculate the deterministic build input fingerprint.

    The aggregate hash is calculated from a stable JSON payload containing each
    input file's repository-relative path and its individual content SHA-256.
    Including both path and content avoids collisions where different files have
    identical bytes or where path changes are meaningful to the build.
    """

    repo_root_path = Path(repo_root)
    files = _collect_files(repo_root_path, relative_inputs)

    hashed = _hash_paths(files)
    file_entries = [
        {"path": _relative_path(path, repo_root_path), "sha256": hashed[path]}
        for path in files
    ]

    captured_tool_versions = (
        capture_build_tool_versions() if tool_versions is None else dict(tool_versions)
    )
    payload = {
        "algorithm": BUILD_FINGERPRINT_ALGORITHM,
        "files": file_entries,
        "tools": captured_tool_versions,
        "semantic_inputs": semantic_inputs or {},
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
    configure_preset: str = "Debug",
    tool_versions: dict[str, str] | None = None,
) -> BuildFingerprint:
    """Calculate the fast pre-configure candidate fingerprint.

    This public wrapper is retained for build, flash, build-record, and test
    callers.  The exact configured dependency fingerprint is calculated
    separately after CMake configuration.
    """

    root = Path(repo_root)
    semantic_inputs: dict[str, Any] = {
        "configure_preset": configure_preset,
        "tls_algorithms": resolve_tls_algorithm_set(bundle),
    }
    private_inputs = _opaque_private_input_digests(bundle, root)
    if private_inputs:
        semantic_inputs["opaque_private_inputs"] = private_inputs

    return calculate_build_fingerprint(
        root,
        default_build_fingerprint_inputs(
            bundle,
            root,
            configure_preset=configure_preset,
        ),
        tool_versions=tool_versions,
        semantic_inputs=semantic_inputs,
    )


def _opaque_private_input_digests(bundle: dict[str, dict[str, object]], repo_root: Path) -> dict[str, str]:
    """Return secret-sensitive digests without exposing private paths or hashes."""

    experiment = bundle.get("experiment", {})
    mqtt = experiment.get("mqtt", {}) if isinstance(experiment, dict) else {}
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    refs = tls.get("certificate_refs", {}) if isinstance(tls, dict) else {}
    result: dict[str, str] = {}
    if isinstance(refs, dict):
        reference = refs.get("client_private_key")
        if reference is not None and str(reference).strip():
            path = repo_root / str(reference).strip()
            if not path.is_file():
                raise FingerprintInputError("Required MQTT client private key is missing")
            result["mqtt_client_private_key"] = _file_sha256(path)
    return result


def _dependency_command_from_compile_command(command_line: str) -> tuple[list[str], str] | None:
    """Convert one Ninja compile command into a dependency-only compiler command."""

    try:
        tokens = shlex.split(command_line, posix=True)
    except ValueError as exc:
        raise FingerprintInputError(f"Unable to parse Ninja compile command: {exc}") from exc
    if "-c" not in tokens:
        return None
    source_index = tokens.index("-c") + 1
    if source_index >= len(tokens):
        return None
    source = tokens[source_index]
    if Path(source).suffix not in _SOURCE_SUFFIXES:
        return None

    filtered: list[str] = []
    skip_next = False
    dependency_prefixes = ("-MF", "-MT", "-MQ", "-MD", "-MMD", "-MP")
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "-c":
            index += 2
            continue
        if token == "-o":
            index += 2
            continue
        if token in {"-MF", "-MT", "-MQ"}:
            index += 2
            continue
        if token in {"-MD", "-MMD", "-MP", "-M", "-MM"}:
            index += 1
            continue
        if token.startswith(dependency_prefixes):
            index += 1
            continue
        filtered.append(token)
        index += 1
    filtered.extend(["-MM", source])
    return filtered, source


def parse_make_dependency_output(output: str) -> list[str]:
    """Parse GCC make-style dependency output into path spellings."""

    logical = output.replace("\\\n", " ")
    if ":" not in logical:
        raise FingerprintInputError("Dependency-only compiler output did not contain a make target")
    _, dependencies = logical.split(":", 1)
    try:
        return [token for token in shlex.split(dependencies, posix=True) if token]
    except ValueError as exc:
        raise FingerprintInputError(f"Unable to parse compiler dependency output: {exc}") from exc


def _run_dependency_command(command: list[str], *, build_dir: Path) -> list[str]:
    completed = subprocess.run(
        command,
        cwd=build_dir,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise FingerprintInputError(
            f"Dependency-only compiler command failed with return code {completed.returncode}: {detail}"
        )
    return parse_make_dependency_output(completed.stdout)


def _normalise_dependency_paths(
    dependencies: Iterable[str], *, repo_root: Path, build_dir: Path
) -> tuple[set[str], set[str]]:
    repository_inputs: set[str] = set()
    generated_inputs: set[str] = set()
    for value in dependencies:
        path = Path(value)
        if not path.is_absolute():
            path = build_dir / path
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if not resolved.is_file():
            raise FingerprintInputError(f"Compiler dependency is missing after configure: {relative}")
        try:
            resolved.relative_to(build_dir)
        except ValueError:
            repository_inputs.add(relative)
        else:
            generated_inputs.add(relative)
    return repository_inputs, generated_inputs


def calculate_configured_build_fingerprint(
    repo_root: Path | str,
    *,
    configure_preset: str,
    candidate_fingerprint: BuildFingerprint,
    commands_output: str | None = None,
    dependency_outputs: list[str] | None = None,
) -> BuildFingerprint:
    """Calculate an exact fingerprint before compilation using compiler dependency mode."""

    root = Path(repo_root).resolve()
    build_dir = root / "build" / configure_preset
    if commands_output is None:
        try:
            completed = subprocess.run(
                ["ninja", "-C", str(build_dir), "-t", "commands", "stm32_basic_hal1.elf"],
                text=True,
                capture_output=True,
                check=False,
                timeout=120,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise FingerprintInputError(f"Active compiler command capture failed: {type(exc).__name__}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise FingerprintInputError(
                f"Active compiler command capture failed with return code {completed.returncode}: {detail}"
            )
        commands_output = completed.stdout

    dependency_commands: list[tuple[list[str], str]] = []
    seen: set[tuple[str, ...]] = set()
    for line in commands_output.splitlines():
        converted = _dependency_command_from_compile_command(line.strip())
        if converted is None:
            continue
        command, source = converted
        key = tuple(command)
        if key not in seen:
            seen.add(key)
            dependency_commands.append((command, source))
    if not dependency_commands:
        raise FingerprintInputError("Ninja active command output did not contain compiler translation units")

    if dependency_outputs is None:
        with ThreadPoolExecutor(max_workers=min(12, len(dependency_commands))) as executor:
            dependency_outputs = list(
                executor.map(lambda item: " ".join(_run_dependency_command(item[0], build_dir=build_dir)), dependency_commands)
            )

    repository_inputs: set[str] = set()
    generated_inputs: set[str] = set()
    for output in dependency_outputs:
        repo_items, generated_items = _normalise_dependency_paths(
            parse_make_dependency_output(output) if ":" in output else shlex.split(output),
            repo_root=root,
            build_dir=build_dir,
        )
        repository_inputs.update(repo_items)
        generated_inputs.update(generated_items)

    exposed_inputs = sorted(set(candidate_fingerprint.inputs) | repository_inputs)
    file_hashes = {
        relative: candidate_fingerprint.file_hashes[relative]
        for relative in exposed_inputs
        if relative in candidate_fingerprint.file_hashes
    }
    missing_paths = [root / relative for relative in exposed_inputs if relative not in file_hashes]
    for path, digest in _hash_paths(missing_paths).items():
        file_hashes[path.relative_to(root).as_posix()] = digest

    opaque_generated: dict[str, str] = {}
    for relative in sorted(generated_inputs):
        path = root / relative
        label = (
            "generated:mqtt-credential-and-network-config"
            if "pqc_wifi_config_generated.h" in relative
            else f"generated:{Path(relative).name}"
        )
        opaque_generated[label] = _file_sha256(path)

    payload = {
        "algorithm": CONFIGURED_BUILD_FINGERPRINT_ALGORITHM,
        "candidate_algorithm": candidate_fingerprint.algorithm,
        "candidate_fingerprint": candidate_fingerprint.fingerprint,
        "files": [{"path": path, "sha256": file_hashes[path]} for path in sorted(file_hashes)],
        "opaque_generated_inputs": opaque_generated,
        "translation_unit_count": len(dependency_commands),
        "tools": candidate_fingerprint.tool_versions or {},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return BuildFingerprint(
        fingerprint=hashlib.sha256(encoded).hexdigest(),
        inputs=sorted(file_hashes) + sorted(opaque_generated),
        file_hashes=file_hashes,
        algorithm=CONFIGURED_BUILD_FINGERPRINT_ALGORITHM,
        tool_versions=candidate_fingerprint.tool_versions or {},
    )

def verify_recorded_dependency_hashes(
    repo_root: Path | str,
    file_hashes: dict[str, str],
) -> tuple[bool, str]:
    """Rehash immutable repository dependencies recorded by a configured build."""

    root = Path(repo_root)
    for relative, expected in sorted(file_hashes.items()):
        if relative == "build" or relative.startswith("build/"):
            continue
        path = root / relative
        if not path.is_file():
            return False, f"Recorded compiler dependency is missing: {relative}"
        actual = _file_sha256(path)
        if actual != expected:
            return False, f"Recorded compiler dependency changed: {relative}"
    return True, "Recorded compiler dependency hashes match."

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

    algorithm = profile_id.removeprefix("wolfboot_stm32l4_")
    inputs = [
        "configs/targets/stm32l4r5_wolfboot.yaml",
        f"configs/algorithms/{algorithm}.yaml",
        "scripts/framework/wolfboot_build.py",
    ]
    if config_template:
        inputs.append(config_template)
    source_prefix = source_dir.rstrip("/\\")
    inputs.extend(f"{source_prefix}/{relative}" for relative in DEFAULT_WOLFBOOT_SOURCE_FINGERPRINT_INPUTS)
    return inputs


def default_signing_fingerprint_inputs(*, profile_id: str) -> list[str]:
    """Return secure-boot application signing fingerprint input candidates."""

    algorithm = profile_id.removeprefix("wolfboot_").removesuffix("_app")
    return [
        "configs/targets/stm32l4r5_wolfboot.yaml",
        f"configs/algorithms/{algorithm}.yaml",
        "scripts/framework/signing.py",
        *DEFAULT_RELOCATED_APPLICATION_FINGERPRINT_INPUTS,
    ]


def default_secure_boot_flash_fingerprint_inputs(
    *,
    experiment_id: str,
    algorithm_id: str | None = None,
    boot_id: str | None = None,
) -> list[str]:
    """Return secure-boot flash workflow fingerprint input candidates.

    The generic secure-boot experiment is composed with one canonical target
    profile and one selected algorithm profile. Record those canonical inputs
    directly so provenance does not depend on removed compatibility wrappers.
    """

    normalized_algorithm = str(algorithm_id or "").strip().lower()
    if not normalized_algorithm and boot_id:
        normalized_algorithm = str(boot_id).removeprefix("wolfboot_").strip().lower()
    if not normalized_algorithm:
        normalized_algorithm = "ecdsa_p256"

    return [
        f"configs/experiments/{experiment_id}.yaml",
        "configs/targets/stm32l4r5_wolfboot.yaml",
        f"configs/algorithms/{normalized_algorithm}.yaml",
        f"configs/wolfboot/stm32l4r5_{normalized_algorithm}.config",
        "scripts/framework/secure_boot_flash.py",
        "scripts/framework/uart.py",
        "scripts/framework/manifest.py",
        "scripts/framework/wolfboot_build.py",
        "scripts/framework/signing.py",
        *DEFAULT_RELOCATED_APPLICATION_FINGERPRINT_INPUTS,
        "tools/wolfboot/Makefile",
        "tools/wolfboot/src/image.c",
        "tools/wolfboot/hal/stm32l4.c",
        "tools/wolfboot/hal/stm32l4xx_hal_conf.h",
        "tools/wolfboot/tools/keytools/Makefile",
    ]
