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
from framework.fingerprint import (
    FingerprintInputError,
    calculate_default_build_fingerprint,
)
from framework.manifest import read_manifest, update_manifest
from framework.test_provenance import (
    TEST_BUILD_PURPOSE,
    current_build_purpose,
    current_test_result_dir,
    reserve_test_build_identity,
    write_json_atomic,
)
from framework.generated_state import (
    build_identity,
    detect_execution_identity,
    preflight_generated_state,
    record_generated_state_success,
)
from framework.source import GitCommandExecution, GitRunner, capture_git_provenance
from framework.tls_algorithms import cmake_boolean, resolve_tls_algorithm_set

ARTIFACT_MISSING_RETURN_CODE = 3
FINGERPRINT_INPUT_ERROR_RETURN_CODE = 4
BUILD_NUMBER_ERROR_RETURN_CODE = 9
BUILD_SKIP_REASON_CACHED = "cached_build_valid"


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
        f"Build fingerprint algorithm: {build_fingerprint_algorithm if build_fingerprint_algorithm is not None else 'unavailable'}",
        f"Build fingerprint: {build_fingerprint if build_fingerprint is not None else 'unavailable'}",
        "Build fingerprint inputs:",
        *(f"- {input_path}" for input_path in build_fingerprint_inputs),
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

    if return_code == FINGERPRINT_INPUT_ERROR_RETURN_CODE:
        lines.extend(
            [
                "Build fingerprint check",
                "-----------------------",
                fingerprint_error if fingerprint_error is not None else "Build fingerprint calculation failed.",
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




def _matching_build_record(
    *,
    results_root: Path,
    current_fingerprint: str,
    current_algorithm: str,
    experiment_id: str,
    board_id: str,
) -> tuple[dict[str, Any] | None, str]:
    """Find the newest verified immutable build record matching this build."""

    builds_root = results_root / "builds"
    if not builds_root.is_dir():
        return None, f"Build-record directory was not found: {builds_root}"

    candidates = sorted(
        (entry for entry in builds_root.iterdir() if entry.is_dir() and entry.name.isdigit()),
        key=lambda entry: int(entry.name),
        reverse=True,
    )
    matching_invalid: list[str] = []
    for record_dir in candidates:
        manifest_path = record_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict):
            continue
        build = manifest.get("build")
        firmware = manifest.get("firmware")
        if not isinstance(build, dict) or not isinstance(firmware, dict):
            continue
        if build.get("fingerprint") != current_fingerprint:
            continue
        if build.get("fingerprint_algorithm") != current_algorithm:
            continue
        if manifest.get("experiment") != experiment_id or manifest.get("board") != board_id:
            continue

        build_number = manifest.get("build_number")
        if build_number != int(record_dir.name):
            matching_invalid.append(f"{record_dir}: build number mismatch")
            continue
        recorded_sha256 = firmware.get("sha256")
        if not isinstance(recorded_sha256, str) or not recorded_sha256:
            matching_invalid.append(f"{record_dir}: missing firmware SHA-256")
            continue

        artifact_path = record_dir / "firmware.elf"
        result_artifacts = firmware.get("result_artifacts")
        if isinstance(result_artifacts, dict):
            elf = result_artifacts.get("elf")
            if isinstance(elf, dict) and isinstance(elf.get("path"), str) and elf["path"]:
                artifact_path = record_dir / elf["path"]
        if not artifact_path.is_file():
            matching_invalid.append(f"{record_dir}: retained firmware artifact is missing")
            continue
        actual_sha256 = calculate_file_sha256(artifact_path)
        if actual_sha256 != recorded_sha256:
            matching_invalid.append(f"{record_dir}: retained firmware SHA-256 mismatch")
            continue

        return {
            "build_number": build_number,
            "record_dir": record_dir,
            "manifest_path": manifest_path,
            "artifact_path": artifact_path,
            "firmware_sha256": recorded_sha256,
            "manifest": manifest,
        }, f"Verified matching immutable build record: {record_dir}"

    if matching_invalid:
        return None, "Matching build records were found but none passed verification: " + "; ".join(matching_invalid)
    return None, "No immutable build record matched the current fingerprint and algorithm."


def _rebuild_decision(
    *,
    matching_record: dict[str, Any] | None,
    search_detail: str,
    force: bool,
) -> tuple[bool, str, str]:
    """Return whether CMake can be skipped using an immutable build record."""

    if force:
        return False, "force_requested", "--force was supplied."
    if matching_record is None:
        return False, "missing_matching_build_record", search_detail
    return True, BUILD_SKIP_REASON_CACHED, search_detail



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
    server_signature_algorithm = str(tls.get("server_signature_algorithm", "")).strip().lower()
    if tls.get("mode") == "pqc_hybrid_tls_server_auth":
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
) -> BuildResult:
    """Run or safely skip the local CMake build process and update the manifest.

    The configure and build commands are intentionally injectable so unit tests
    can verify command construction and result handling without invoking CMake.
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

    try:
        build_fingerprint = calculate_default_build_fingerprint(bundle, repo_root_path)
    except FingerprintInputError as exc:
        duration_seconds = perf_counter() - start
        fingerprint_error = str(exc)
        skipped_configure = CommandExecution(
            command=construct_configure_command(configure_preset),
            return_code=FINGERPRINT_INPUT_ERROR_RETURN_CODE,
            stdout="",
            stderr=fingerprint_error,
            duration_seconds=0.0,
        )
        _write_build_log(
            log_path=log_path,
            repo_root=repo_root_path,
            configure=skipped_configure,
            build=None,
            return_code=FINGERPRINT_INPUT_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            artifact_exists=elf_path.is_file(),
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_inputs=[],
            build_fingerprint_algorithm=None,
            fingerprint_error=fingerprint_error,
            build_number=None,
            build_skip_reason="fingerprint_error",
            build_skip_detail=fingerprint_error,
            force_rebuild=force,
            build_purpose=build_purpose,
            build_identity=build_identity_value if "build_identity_value" in locals() else None,
        )
        update_manifest(
            result_dir_path / "manifest.json",
            {
                "result": "build_failed",
                "build_number": None,
                "firmware": {
                    "artifact": artifact_relative_path.as_posix(),
                    "artifact_path": str(elf_path),
                    "artifact_exists": elf_path.is_file(),
                    "sha256": None,
                },
                "network_configuration": {
                    "wifi": {
                        "ssid": str(bundle.get("experiment", {}).get("network", {}).get("wifi", {}).get("ssid", "")),
                        "psk": "redacted",
                        "psk_supplied": bool(bundle.get("experiment", {}).get("network", {}).get("wifi", {}).get("psk")),
                    },
                    "ipv4": {"mode": str(bundle.get("experiment", {}).get("network", {}).get("ipv4", {}).get("mode", ""))},
                },
                "source": source,
                "build": {
                    "configure_preset": configure_preset,
                    "build_preset": build_preset,
                    "purpose": build_purpose,
                    "identity": None,
                    "return_code": FINGERPRINT_INPUT_ERROR_RETURN_CODE,
                    "duration_seconds": round(duration_seconds, 3),
                    "log": "build.log",
                    "fingerprint": None,
                    "fingerprint_inputs": [],
                    "fingerprint_algorithm": None,
                    "fingerprint_error": fingerprint_error,
                    "skipped": False,
                    "skip_reason": "fingerprint_error",
                    "skip_detail": fingerprint_error,
                    "force": force,
                },
            },
        )
        return BuildResult(
            return_code=FINGERPRINT_INPUT_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            log_path=log_path,
            configure=skipped_configure,
            build=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_inputs=[],
            build_fingerprint_algorithm=None,
            build_number=None,
            result_artifacts={},
            build_record_dir=None,
            build_record_manifest_path=None,
            build_skipped=False,
            build_skip_reason="fingerprint_error",
            build_purpose=build_purpose,
            build_identity=None,
        )

    generated_state_scope = f"cmake-{configure_preset}"
    generated_state_identity = build_identity(
        workflow=f"stm32_cmake:{build_purpose}",
        profile=f"{configure_preset}:{build_preset}:{build_purpose}",
        input_fingerprint={
            "algorithm": build_fingerprint.algorithm,
            "fingerprint": build_fingerprint.fingerprint,
            "inputs": build_fingerprint.inputs,
            "file_hashes": build_fingerprint.file_hashes,
        },
        toolchain={
            "configure_command": construct_configure_command(configure_preset),
            "build_command": construct_build_command(build_preset),
        },
        execution=detect_execution_identity(),
    )
    if build_purpose == TEST_BUILD_PURPOSE:
        matching_record = None
        build_record_search_detail = "Automated-test builds never search or reuse the normal build pool."
    else:
        matching_record, build_record_search_detail = _matching_build_record(
            results_root=result_dir_path.parent,
            current_fingerprint=build_fingerprint.fingerprint,
            current_algorithm=build_fingerprint.algorithm,
            experiment_id=str(bundle["experiment"]["id"]),
            board_id=str(bundle["board"]["id"]),
        )
    build_skipped, skip_reason, skip_detail = _rebuild_decision(
        matching_record=matching_record,
        search_detail=build_record_search_detail,
        force=force,
    )

    if build_skipped:
        assert matching_record is not None
        reused_elf_path = Path(matching_record["artifact_path"])
        firmware_sha256 = str(matching_record["firmware_sha256"])
        build_number = int(matching_record["build_number"])
        build_record_path = Path(matching_record["record_dir"])
        build_record_manifest_path = Path(matching_record["manifest_path"])
        source_manifest = matching_record["manifest"]
        source_compatibility = source_manifest.get("compatibility", {}) if isinstance(source_manifest, dict) else {}
        source_run_id = source_compatibility.get("source_run_id") if isinstance(source_compatibility, dict) else None
        result_artifacts = copy_firmware_artifacts_to_result(reused_elf_path, result_dir_path)
        duration_seconds = perf_counter() - start
        skipped_configure = CommandExecution(
            command=construct_configure_command(configure_preset),
            return_code=0,
            stdout="Skipped because a verified immutable build record matched the current fingerprint.",
            stderr="",
            duration_seconds=0.0,
        )
        _write_build_log(
            log_path=log_path, repo_root=repo_root_path, configure=skipped_configure,
            build=None, return_code=0, duration_seconds=duration_seconds,
            elf_path=reused_elf_path, artifact_exists=True, firmware_sha256=firmware_sha256,
            build_fingerprint=build_fingerprint.fingerprint,
            build_fingerprint_inputs=build_fingerprint.inputs,
            build_fingerprint_algorithm=build_fingerprint.algorithm,
            build_number=build_number, build_skipped=True, build_skip_reason=skip_reason,
            build_skip_detail=skip_detail, force_rebuild=force,
            build_purpose=build_purpose, build_identity=None,
        )
        record_generated_state_success(
            repo_root=repo_root_path, scope=generated_state_scope, identity=generated_state_identity,
            artifacts=[reused_elf_path],
            record_refs={
                "build_number": build_number,
                "build_record_manifest": str(build_record_manifest_path),
                "run_manifest": str(result_dir_path / "manifest.json"),
                "source": "verified_immutable_build_record",
            },
        )
        update_manifest(
            result_dir_path / "manifest.json",
            {
                "result": "build_skipped",
                "build_number": build_number,
                "firmware": {
                    "artifact": artifact_relative_path.as_posix(),
                    "artifact_path": str(reused_elf_path),
                    "artifact_exists": True,
                    "sha256": firmware_sha256,
                    "result_artifacts": result_artifacts,
                },
                "network_configuration": {
                    "wifi": {
                        "ssid": str(bundle.get("experiment", {}).get("network", {}).get("wifi", {}).get("ssid", "")),
                        "psk": "redacted",
                        "psk_supplied": bool(bundle.get("experiment", {}).get("network", {}).get("wifi", {}).get("psk")),
                    },
                    "ipv4": {"mode": str(bundle.get("experiment", {}).get("network", {}).get("ipv4", {}).get("mode", ""))},
                },
                "source": source,
                "build": {
                    "configure_preset": configure_preset, "build_preset": build_preset,
                    "purpose": build_purpose, "identity": None,
                    "return_code": 0, "duration_seconds": round(duration_seconds, 3),
                    "log": "build.log", "fingerprint": build_fingerprint.fingerprint,
                    "fingerprint_inputs": build_fingerprint.inputs,
                    "fingerprint_file_hashes": build_fingerprint.file_hashes,
                    "fingerprint_algorithm": build_fingerprint.algorithm,
                    "fingerprint_tool_versions": build_fingerprint.tool_versions or {},
                    "skipped": True, "skip_reason": skip_reason, "skip_detail": skip_detail,
                    "force": force, "source_state_run_id": source_run_id,
                    "source_state_build_number": build_number,
                    "source_state_fingerprint": build_fingerprint.fingerprint,
                    "record_action": "reused_immutable_build_record", "record_mutated": False,
                    **_build_record_manifest_update(build_record_path),
                },
            },
        )
        return BuildResult(
            return_code=0, duration_seconds=duration_seconds, elf_path=reused_elf_path,
            log_path=log_path, configure=skipped_configure, build=None,
            firmware_sha256=firmware_sha256, build_fingerprint=build_fingerprint.fingerprint,
            build_fingerprint_inputs=build_fingerprint.inputs,
            build_fingerprint_algorithm=build_fingerprint.algorithm, build_number=build_number,
            result_artifacts=result_artifacts, build_record_dir=build_record_path,
            build_record_manifest_path=build_record_manifest_path, build_skipped=True,
            build_skip_reason=skip_reason,
            build_purpose=build_purpose,
            build_identity=build_identity_value if "build_identity_value" in locals() else None,
        )

    preflight_generated_state(
        repo_root=repo_root_path,
        scope=generated_state_scope,
        expected_identity=generated_state_identity,
        cleanup_paths=[Path("build") / configure_preset],
        final_artifact_paths=[elf_path],
    )

    build_identity_value = None
    test_build_record_dir = None
    if build_purpose == TEST_BUILD_PURPOSE:
        if test_result_dir is None:
            test_result_dir = result_dir_path
        build_identity_value, test_build_record_dir = reserve_test_build_identity(test_result_dir)
        build_number = None
    try:
        if build_purpose != TEST_BUILD_PURPOSE:
            build_number = reserve_next_build_number(repo_root_path)
    except BuildNumberError as exc:
        duration_seconds = perf_counter() - start
        build_number_error = str(exc)
        skipped_configure = CommandExecution(
            command=construct_configure_command(configure_preset),
            return_code=BUILD_NUMBER_ERROR_RETURN_CODE,
            stdout="",
            stderr=build_number_error,
            duration_seconds=0.0,
        )
        _write_build_log(
            log_path=log_path,
            repo_root=repo_root_path,
            configure=skipped_configure,
            build=None,
            return_code=BUILD_NUMBER_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            artifact_exists=elf_path.is_file(),
            firmware_sha256=None,
            build_fingerprint=build_fingerprint.fingerprint,
            build_fingerprint_inputs=build_fingerprint.inputs,
            build_fingerprint_algorithm=build_fingerprint.algorithm,
            build_number_error=build_number_error,
            build_number=None,
            build_skip_reason=skip_reason,
            build_skip_detail=skip_detail,
            force_rebuild=force,
            build_purpose=build_purpose,
            build_identity=build_identity_value if "build_identity_value" in locals() else None,
        )
        update_manifest(
            result_dir_path / "manifest.json",
            {
                "result": "build_failed",
                "build_number": None,
                "firmware": {
                    "artifact": artifact_relative_path.as_posix(),
                    "artifact_path": str(elf_path),
                    "artifact_exists": elf_path.is_file(),
                    "sha256": None,
                },
                "network_configuration": {
                    "wifi": {
                        "ssid": str(bundle.get("experiment", {}).get("network", {}).get("wifi", {}).get("ssid", "")),
                        "psk": "redacted",
                        "psk_supplied": bool(bundle.get("experiment", {}).get("network", {}).get("wifi", {}).get("psk")),
                    },
                    "ipv4": {"mode": str(bundle.get("experiment", {}).get("network", {}).get("ipv4", {}).get("mode", ""))},
                },
                "source": source,
                "build": {
                    "configure_preset": configure_preset,
                    "build_preset": build_preset,
                    "purpose": build_purpose,
                    "identity": None,
                    "return_code": BUILD_NUMBER_ERROR_RETURN_CODE,
                    "duration_seconds": round(duration_seconds, 3),
                    "log": "build.log",
                    "fingerprint": build_fingerprint.fingerprint,
                    "fingerprint_inputs": build_fingerprint.inputs,
                    "fingerprint_file_hashes": build_fingerprint.file_hashes,
                    "fingerprint_algorithm": build_fingerprint.algorithm,
                    "fingerprint_tool_versions": build_fingerprint.tool_versions or {},
                    "build_number_error": build_number_error,
                    "skipped": False,
                    "skip_reason": skip_reason,
                    "skip_detail": skip_detail,
                    "force": force,
                },
            },
        )
        return BuildResult(
            return_code=BUILD_NUMBER_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            elf_path=elf_path,
            log_path=log_path,
            configure=skipped_configure,
            build=None,
            firmware_sha256=None,
            build_fingerprint=build_fingerprint.fingerprint,
            build_fingerprint_inputs=build_fingerprint.inputs,
            build_fingerprint_algorithm=build_fingerprint.algorithm,
            build_number=None,
            result_artifacts={},
            build_record_dir=None,
            build_record_manifest_path=None,
            build_skipped=False,
            build_skip_reason=skip_reason,
            build_purpose=build_purpose,
            build_identity=build_identity_value if "build_identity_value" in locals() else None,
        )

    # Generated-state preflight may remove the configured build directory.
    # Write the Wi-Fi header only after that cleanup and before CMake configure,
    # so the compiler sees the experiment values during this build.
    _write_tls_algorithm_selection(bundle, repo_root_path, configure_preset)
    _write_wifi_config_header(bundle, repo_root_path, configure_preset)

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
    result_artifacts = (
        copy_firmware_artifacts_to_result(elf_path, result_dir_path) if return_code == 0 else {}
    )

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
        build_fingerprint=build_fingerprint.fingerprint,
        build_fingerprint_inputs=build_fingerprint.inputs,
        build_fingerprint_algorithm=build_fingerprint.algorithm,
        build_number=build_number,
        build_skipped=False,
        build_skip_reason=skip_reason,
        build_skip_detail=skip_detail,
        force_rebuild=force,
        build_purpose=build_purpose,
        build_identity=build_identity_value,
    )

    build_record_path = None
    build_record_manifest_path = None
    if return_code == 0:
        build_record_build = {
            "configure_preset": configure_preset,
            "build_preset": build_preset,
            "return_code": return_code,
            "duration_seconds": round(duration_seconds, 3),
            "log": "build.log",
            "fingerprint": build_fingerprint.fingerprint,
            "fingerprint_inputs": build_fingerprint.inputs,
            "fingerprint_file_hashes": build_fingerprint.file_hashes,
            "fingerprint_algorithm": build_fingerprint.algorithm,
            "skipped": False,
            "skip_reason": skip_reason,
            "skip_detail": skip_detail,
            "force": force,
        }
        build_record_build["purpose"] = build_purpose
        build_record_build["identity"] = build_identity_value
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
                bundle=bundle,
                result_dir=result_dir_path,
                build_number=build_number,
                firmware_elf_path=elf_path,
                firmware_artifact=artifact_relative_path.as_posix(),
                firmware_artifact_path=str(elf_path),
                firmware_sha256=firmware_sha256,
                source=source,
                build=build_record_build,
                source_run_id=_current_run_id(result_dir_path),
                build_log_path=log_path,
            )
            build_record_manifest_path = build_record_path / "manifest.json"

    updated_manifest = update_manifest(
        result_dir_path / "manifest.json",
        {
            "result": "build_passed" if return_code == 0 else "build_failed",
            "build_number": build_number,
            "firmware": {
                "artifact": artifact_relative_path.as_posix(),
                "artifact_path": str(elf_path),
                "artifact_exists": artifact_exists,
                "sha256": firmware_sha256,
                "result_artifacts": result_artifacts,
            },
            "source": source,
            "build": {
                "configure_preset": configure_preset,
                "build_preset": build_preset,
                "purpose": build_purpose,
                "identity": build_identity_value,
                "return_code": return_code,
                "duration_seconds": round(duration_seconds, 3),
                "log": "build.log",
                "fingerprint": build_fingerprint.fingerprint,
                "fingerprint_inputs": build_fingerprint.inputs,
                "fingerprint_file_hashes": build_fingerprint.file_hashes,
                "fingerprint_algorithm": build_fingerprint.algorithm,
                "fingerprint_tool_versions": build_fingerprint.tool_versions or {},
                "skipped": False,
                "skip_reason": skip_reason,
                "skip_detail": skip_detail,
                "force": force,
                **_build_record_manifest_update(build_record_path),
            },
        },
    )

    if return_code == 0 and firmware_sha256 is not None:
        record_generated_state_success(
            repo_root=repo_root_path,
            scope=generated_state_scope,
            identity=generated_state_identity,
            artifacts=[elf_path],
            record_refs={
                "build_number": build_number,
                "build_record_manifest": None if build_record_manifest_path is None else str(build_record_manifest_path),
                "run_manifest": str(result_dir_path / "manifest.json"),
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
        build_fingerprint=build_fingerprint.fingerprint,
        build_fingerprint_inputs=build_fingerprint.inputs,
        build_fingerprint_algorithm=build_fingerprint.algorithm,
        build_number=build_number,
        result_artifacts=result_artifacts,
        build_record_dir=build_record_path,
        build_record_manifest_path=build_record_manifest_path,
        build_skipped=False,
        build_skip_reason=skip_reason,
        build_purpose=build_purpose,
        build_identity=build_identity_value,
    )
