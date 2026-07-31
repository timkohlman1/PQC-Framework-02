"""Local firmware build helpers for experiment runs.

This module wraps the local CMake/STM32 build process and records build output
under results/<run_id>/ without flashing hardware, opening UART devices, using
SSH, or touching network resources.
"""

import json
import shlex
import shutil
import subprocess
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from framework.artifacts import calculate_file_sha256, copy_firmware_artifacts_to_result
from framework.build_number import BuildNumberError, reserve_next_build_number
from framework.build_records import build_record_dir_for_result_dir, write_build_record
from framework.manifest import read_manifest, update_manifest
from framework.generated_state import (
    build_identity as generated_build_identity,
    detect_execution_identity,
    record_generated_state_success,
)
from framework.test_provenance import (
    TEST_BUILD_PURPOSE,
    current_build_purpose,
    current_test_result_dir,
    reserve_test_build_identity,
    write_json_atomic,
)
from framework.source import GitCommandExecution, GitRunner, capture_git_provenance
from framework.tls_algorithms import cmake_boolean, resolve_tls_algorithm_set

ARTIFACT_MISSING_RETURN_CODE = 3
BUILD_NUMBER_ERROR_RETURN_CODE = 9


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
    build_purpose: str = "experiment"
    build_identity: str | None = None


Runner = Callable[[list[str], Path], CommandExecution]
BuildProgress = Callable[[str, str, str | None], None]


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
    build_purpose: str = "experiment",
    build_identity: str | None = None,
) -> None:
    """Write the build log for one experiment build run."""

    lines = [
        "Firmware build log",
        "==================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root: {repo_root}",
        f"Build purpose: {build_purpose}",
        f"Build identity: {build_identity if build_identity is not None else 'unavailable'}",
        f"Build number: {build_number if build_number is not None else 'unavailable'}",
        f"Build skipped: {str(build_skipped).lower()}",
        f"Build skip reason: {build_skip_reason if build_skip_reason is not None else 'none'}",
        f"Force rebuild requested: {str(force_rebuild).lower()}",
        f"Output ELF path: {elf_path}",
        f"Output ELF exists: {str(artifact_exists).lower()}",
        f"Output ELF SHA-256: {firmware_sha256 if firmware_sha256 is not None else 'unavailable'}",
        "Framework build reuse: disabled",
        "Artifact identity algorithm: sha256-elf",
        f"Artifact identity: {firmware_sha256 if firmware_sha256 is not None else 'unavailable'}",
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




def _write_tls_algorithm_selection(bundle: dict[str, dict[str, Any]], repo_root: Path, configure_preset: str = "Debug") -> tuple[Path, dict[str, Any]]:
    """Write the resolved profile-specific CMake algorithm selection."""
    selected = resolve_tls_algorithm_set(bundle)
    generated_dir = repo_root / "build" / configure_preset / "pqc_generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    path = generated_dir / "pqc_tls_algorithm_selection.cmake"
    path.write_text(
        f'set(PQC_TLS_ALGORITHM_MODE "{selected["mode"]}")\n'
        f'set(PQC_TLS_ENABLE_RSA {cmake_boolean(selected["rsa"])})\n'
        f'set(PQC_TLS_ENABLE_RSA_PSS {cmake_boolean(selected["rsa_pss"])})\n'
        f'set(PQC_TLS_ENABLE_MLKEM_768 {cmake_boolean(selected["mlkem_768"])})\n',
        encoding="utf-8",
    )
    return path, selected

def _write_wifi_config_header(bundle: dict[str, dict[str, Any]], repo_root: Path, configure_preset: str = "Debug") -> Path:
    """Write experiment Wi-Fi configuration without exposing the PSK in command logs."""
    experiment = bundle.get("experiment", {})
    network = experiment.get("network", {}) if isinstance(experiment, dict) else {}
    wifi = network.get("wifi", {}) if isinstance(network, dict) else {}
    ipv4 = network.get("ipv4", {}) if isinstance(network, dict) else {}
    mqtt = experiment.get("mqtt", {}) if isinstance(experiment, dict) else {}
    broker = mqtt.get("broker", {}) if isinstance(mqtt, dict) else {}
    topics = mqtt.get("topics", {}) if isinstance(mqtt, dict) else {}
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    certificate_refs = tls.get("certificate_refs", {}) if isinstance(tls, dict) else {}
    ca_pem = ""
    ca_sha256 = ""
    client_certificate_pem = ""
    client_private_key_pem = ""
    client_certificate_sha256 = ""
    client_private_key_sha256 = ""
    authentication = str(tls.get("authentication", "server")).strip().lower()
    mutual_tls = authentication == "mutual" or str(tls.get("mode", "")).endswith("_mutual")
    server_signature_algorithm = str(tls.get("server_signature_algorithm", "")).strip().lower()
    if tls.get("mode") in {"pqc_hybrid_tls_server_auth", "pqc_hybrid_tls_mutual"}:
        if not server_signature_algorithm:
            raise ValueError(
                "MQTT PQC hybrid TLS configuration is missing tls.server_signature_algorithm. "
                "The STM32 wolfSSL profile requires an explicit classical server-authentication algorithm."
            )
        supported_server_signature_algorithms = {"classical"}
        if server_signature_algorithm not in supported_server_signature_algorithms:
            raise ValueError(
                "MQTT TLS server signature algorithm " + server_signature_algorithm
                + " is incompatible with the STM32 wolfSSL profile; supported algorithms: "
                + ", ".join(sorted(supported_server_signature_algorithms))
            )
    ca_reference = certificate_refs.get("ca_certificate") if isinstance(certificate_refs, dict) else None
    if ca_reference:
        ca_path = repo_root / str(ca_reference)
        if not ca_path.is_file():
            raise ValueError(
                "MQTT TLS CA certificate is unavailable: " + str(ca_path)
                + ". Provision the classical broker certificates before building."
            )
        ca_pem = ca_path.read_text(encoding="utf-8")
        ca_sha256 = hashlib.sha256(ca_pem.encode("utf-8")).hexdigest()
        if "BEGIN CERTIFICATE" not in ca_pem:
            raise ValueError(f"MQTT TLS CA certificate is not PEM encoded: {ca_path}")
    if mutual_tls:
        for ref_name, label in (("client_certificate", "client certificate"), ("client_private_key", "client private key")):
            ref = certificate_refs.get(ref_name) if isinstance(certificate_refs, dict) else None
            if not ref:
                raise ValueError(f"MQTT mutual TLS requires a resolved {label}")
            path_ref = repo_root / str(ref)
            if not path_ref.is_file():
                raise ValueError(f"MQTT mutual TLS {label} is unavailable: {path_ref}")
            pem = path_ref.read_text(encoding="utf-8")
            if ref_name == "client_certificate":
                if "BEGIN CERTIFICATE" not in pem:
                    raise ValueError(f"MQTT client certificate is not PEM encoded: {path_ref}")
                client_certificate_pem = pem
                client_certificate_sha256 = hashlib.sha256(pem.encode("utf-8")).hexdigest()
            else:
                if "PRIVATE KEY" not in pem:
                    raise ValueError(f"MQTT client private key is not PEM encoded: {path_ref}")
                client_private_key_pem = pem
                client_private_key_sha256 = hashlib.sha256(pem.encode("utf-8")).hexdigest()
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "\\n")
    generated_dir = repo_root / "build" / configure_preset / "pqc_generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    path = generated_dir / "pqc_wifi_config_generated.h"
    path.write_text(
        "#ifndef PQC_WIFI_CONFIG_GENERATED_H\n#define PQC_WIFI_CONFIG_GENERATED_H\n"
        f'#define PQC_WIFI_SSID "{esc(str(wifi.get("ssid", "")))}"\n'
        f'#define PQC_WIFI_PSK "{esc(str(wifi.get("psk", "")))}"\n'
        f'#define PQC_WIFI_IPV4_MODE "{esc(str(ipv4.get("mode", "")))}"\n'
        f'#define PQC_MQTT_ENABLED {1 if bool(mqtt.get("enabled", False)) else 0}\n'
        f'#define PQC_MQTT_BROKER_HOST "{esc(str(broker.get("host", "")))}"\n'
        f'#define PQC_MQTT_BROKER_PORT {int(broker.get("port", 1883))}\n'
        f'#define PQC_MQTT_DNS_REQUIRED {1 if bool(broker.get("dns_required", False)) else 0}\n'
        f'#define PQC_MQTT_CLIENT_ID "{esc(str(mqtt.get("client_id", "pqc-stm32")))}"\n'
        f'#define PQC_MQTT_COMMAND_TOPIC "{esc(str(topics.get("command", "pqc/stm32/command")))}"\n'
        f'#define PQC_MQTT_RESPONSE_TOPIC "{esc(str(topics.get("response", "pqc/stm32/response")))}"\n'
        f'#define PQC_MQTT_CORRELATION_PAYLOAD "{esc(str(mqtt.get("correlation_payload", "pqc-e2e")))}"\n'
        f'#define PQC_MQTT_TLS_MODE "{esc(str(tls.get("mode", "plaintext")))}"\n'
        f'#define PQC_MQTT_TLS_SERVER_NAME "{esc(str(broker.get("server_name", broker.get("host", ""))))}"\n'
        f'#define PQC_MQTT_TLS_CA_PEM "{esc(ca_pem)}"\n'
        f'#define PQC_MQTT_TLS_CA_PEM_SHA256 "{ca_sha256}"\n'
        f'#define PQC_MQTT_TLS_AUTHENTICATION "{esc(authentication)}"\n'
        f'#define PQC_MQTT_TLS_CLIENT_CERT_PEM "{esc(client_certificate_pem)}"\n'
        f'#define PQC_MQTT_TLS_CLIENT_CERT_PEM_SHA256 "{client_certificate_sha256}"\n'
        f'#define PQC_MQTT_TLS_CLIENT_KEY_PEM "{esc(client_private_key_pem)}"\n'
        f'#define PQC_MQTT_TLS_CLIENT_KEY_PEM_SHA256 "{client_private_key_sha256}"\n'
        f'#define PQC_MQTT_TLS_SERVER_SIGNATURE_ALGORITHM "{esc(server_signature_algorithm)}"\n'
        f'#define PQC_MQTT_RECONNECT_ATTEMPTS {int(mqtt.get("reconnect_attempts", 0))}\n'
        "#endif\n", encoding="utf-8")
    return path

def execute_build(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
    result_dir: Path | str,
    configure_preset: str = "Debug",
    build_preset: str = "Debug",
    force: bool = False,
    runner: Runner = default_runner,
    git_runner: GitRunner | None = None,
    progress: BuildProgress | None = None,
) -> BuildResult:
    """Always invoke CMake configure/build and record the resulting ELF.

    Framework-level build reuse and source/dependency fingerprinting are
    intentionally disabled. CMake/Ninja remains responsible for incremental
    compilation inside the retained build directory.
    """

    repo_root_path = Path(repo_root)
    result_dir_path = Path(result_dir)
    requested_build_purpose = current_build_purpose()
    build_purpose = requested_build_purpose if runner is default_runner else "experiment"
    test_result_dir = current_test_result_dir()
    source = (
        capture_git_provenance(repo_root_path)
        if git_runner is None
        else capture_git_provenance(repo_root_path, git_runner)
    )
    log_path = result_dir_path / "build.log"
    artifact_relative_path = Path(str(bundle["experiment"]["firmware"]["artifact"]))
    elf_path = repo_root_path / artifact_relative_path
    start = perf_counter()

    build_identity_value: str | None = None
    test_build_record_dir: Path | None = None
    build_number: int | None = None
    try:
        if build_purpose == TEST_BUILD_PURPOSE:
            if test_result_dir is None:
                test_result_dir = result_dir_path
            build_identity_value, test_build_record_dir = reserve_test_build_identity(test_result_dir)
        else:
            build_number = reserve_next_build_number(repo_root_path)
    except BuildNumberError as exc:
        duration_seconds = perf_counter() - start
        error = str(exc)
        skipped = CommandExecution(
            command=construct_configure_command(configure_preset),
            return_code=BUILD_NUMBER_ERROR_RETURN_CODE,
            stdout="",
            stderr=error,
            duration_seconds=0.0,
        )
        _write_build_log(
            log_path, repo_root_path, skipped, None, BUILD_NUMBER_ERROR_RETURN_CODE,
            duration_seconds, elf_path, elf_path.is_file(), None, None, [], None,
            build_number_error=error, build_number=None, build_skipped=False,
            build_skip_reason="build_number_error", build_skip_detail=error,
            force_rebuild=force, build_purpose=build_purpose, build_identity=None,
        )
        update_manifest(result_dir_path / "manifest.json", {
            "result": "build_failed",
            "build_number": None,
            "source": source,
            "firmware": {"artifact": artifact_relative_path.as_posix(), "artifact_path": str(elf_path), "artifact_exists": elf_path.is_file(), "sha256": None},
            "build": {"configure_preset": configure_preset, "build_preset": build_preset, "purpose": build_purpose, "identity": None, "return_code": BUILD_NUMBER_ERROR_RETURN_CODE, "duration_seconds": round(duration_seconds, 3), "log": "build.log", "reuse_enabled": False, "incremental_build_system": "cmake-ninja", "build_number_error": error, "force": force},
        })
        return BuildResult(BUILD_NUMBER_ERROR_RETURN_CODE, duration_seconds, elf_path, log_path, skipped, None, None, None, [], None, None, {}, None, None, False, "build_number_error", build_purpose, None)

    _write_tls_algorithm_selection(bundle, repo_root_path, configure_preset)
    _write_wifi_config_header(bundle, repo_root_path, configure_preset)

    if progress is not None:
        progress("build", "Configuring application", f"CMake preset: {configure_preset}.")
    configure_execution = runner(construct_configure_command(configure_preset), repo_root_path)

    build_execution: CommandExecution | None = None
    return_code = configure_execution.return_code
    if configure_execution.return_code == 0:
        if progress is not None:
            progress("build", "Building application", f"CMake/Ninja preset: {build_preset}.")
        build_execution = runner(construct_build_command(build_preset), repo_root_path)
        return_code = build_execution.return_code

    artifact_exists = elf_path.is_file()
    if return_code == 0 and not artifact_exists:
        return_code = ARTIFACT_MISSING_RETURN_CODE

    firmware_sha256 = calculate_file_sha256(elf_path) if return_code == 0 else None
    result_artifacts = copy_firmware_artifacts_to_result(elf_path, result_dir_path) if return_code == 0 else {}
    if return_code == 0 and firmware_sha256 is not None:
        if build_purpose == TEST_BUILD_PURPOSE:
            assert build_identity_value is not None
        else:
            assert build_number is not None
            build_identity_value = f"build-{build_number}-{firmware_sha256[:12]}"

    duration_seconds = perf_counter() - start
    _write_build_log(
        log_path, repo_root_path, configure_execution, build_execution, return_code,
        duration_seconds, elf_path, artifact_exists, firmware_sha256, None, [], None,
        build_number=build_number, build_skipped=False, build_skip_reason=None,
        build_skip_detail="CMake configure/build is invoked for every framework build.",
        force_rebuild=force, build_purpose=build_purpose, build_identity=build_identity_value,
    )

    build_record_path: Path | None = None
    build_record_manifest_path: Path | None = None
    if return_code == 0:
        build_record_build = {
            "configure_preset": configure_preset,
            "build_preset": build_preset,
            "purpose": build_purpose,
            "identity": build_identity_value,
            "return_code": return_code,
            "duration_seconds": round(duration_seconds, 3),
            "log": "build.log",
            "reuse_enabled": False,
            "incremental_build_system": "cmake-ninja",
            "artifact_identity_algorithm": "sha256-elf",
            "artifact_identity": firmware_sha256,
            "skipped": False,
            "force": force,
        }
        if build_purpose == TEST_BUILD_PURPOSE:
            assert test_build_record_dir is not None
            build_record_path = test_build_record_dir
            shutil.copy2(log_path, build_record_path / "build.log")
            copied = copy_firmware_artifacts_to_result(elf_path, build_record_path)
            build_record_manifest_path = build_record_path / "manifest.json"
            write_json_atomic(build_record_manifest_path, {
                "schema_version": 1,
                "record_type": "automated_test_build",
                "build_identity": build_identity_value,
                "build_number": None,
                "purpose": TEST_BUILD_PURPOSE,
                "reusable_by_normal_workflows": False,
                "test_run_id": None if test_result_dir is None else test_result_dir.name,
                "experiment": str(bundle["experiment"]["id"]),
                "board": str(bundle["board"]["id"]),
                "source": source,
                "build": build_record_build,
                "firmware": {"sha256": firmware_sha256, "result_artifacts": copied},
            })
        else:
            assert build_number is not None
            build_record_path, _ = write_build_record(
                bundle=bundle, result_dir=result_dir_path, build_number=build_number,
                firmware_elf_path=elf_path, firmware_artifact=artifact_relative_path.as_posix(),
                firmware_artifact_path=str(elf_path), firmware_sha256=firmware_sha256,
                source=source, build=build_record_build, source_run_id=_current_run_id(result_dir_path),
                build_log_path=log_path,
            )
            build_record_manifest_path = build_record_path / "manifest.json"

        if build_purpose != TEST_BUILD_PURPOSE:
            generated_identity = generated_build_identity(
                workflow="stm32_cmake",
                profile=build_preset,
                input_fingerprint={
                    "status": "disabled",
                    "reason": "framework build-input fingerprinting removed",
                },
                toolchain={
                    "configure_command": construct_configure_command(configure_preset),
                    "build_command": construct_build_command(build_preset),
                },
                execution=detect_execution_identity(),
                extra={
                    "configure_preset": configure_preset,
                    "build_preset": build_preset,
                    "build_identity": build_identity_value,
                    "firmware_sha256": firmware_sha256,
                },
            )
            record_generated_state_success(
                repo_root=repo_root_path,
                scope=f"cmake-{build_preset}",
                identity=generated_identity,
                artifacts=[elf_path],
                record_refs={
                    "build_number": build_number,
                    "build_identity": build_identity_value,
                    "build_record_manifest": (
                        None
                        if build_record_manifest_path is None
                        else str(build_record_manifest_path)
                    ),
                },
            )

    update_manifest(result_dir_path / "manifest.json", {
        "result": "build_passed" if return_code == 0 else "build_failed",
        "build_number": build_number,
        "firmware": {"artifact": artifact_relative_path.as_posix(), "artifact_path": str(elf_path), "artifact_exists": artifact_exists, "sha256": firmware_sha256, "result_artifacts": result_artifacts},
        "source": source,
        "build": {
            "configure_preset": configure_preset,
            "build_preset": build_preset,
            "purpose": build_purpose,
            "identity": build_identity_value,
            "return_code": return_code,
            "duration_seconds": round(duration_seconds, 3),
            "log": "build.log",
            "reuse_enabled": False,
            "incremental_build_system": "cmake-ninja",
            "artifact_identity_algorithm": "sha256-elf",
            "artifact_identity": firmware_sha256,
            "skipped": False,
            "force": force,
            **_build_record_manifest_update(build_record_path),
        },
    })

    return BuildResult(
        return_code=return_code, duration_seconds=duration_seconds, elf_path=elf_path,
        log_path=log_path, configure=configure_execution, build=build_execution,
        firmware_sha256=firmware_sha256, build_fingerprint=None,
        build_fingerprint_inputs=[], build_fingerprint_algorithm=None,
        build_number=build_number, result_artifacts=result_artifacts,
        build_record_dir=build_record_path, build_record_manifest_path=build_record_manifest_path,
        build_skipped=False, build_skip_reason=None, build_purpose=build_purpose,
        build_identity=build_identity_value,
    )
