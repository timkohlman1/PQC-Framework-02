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
    python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
    python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ed25519_app.yaml
    python scripts/experiment.py sign-application --profile configs/signing/wolfboot_rsa2048_app.yaml
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ed25519_uart.yaml
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_rsa2048_uart.yaml
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --repeat-count 5
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --negative-corrupt-application
    python scripts/experiment.py aggregate-benchmarks

The status command loads an experiment config, resolves the referenced board, host, and boot configs, validates required fields, and prints a summary.

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
under results/adhoc/. The aggregate-benchmarks command reads existing secure-boot
benchmark manifests and writes JSON/CSV summaries without touching hardware.
"""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
MQTT_BROKER_SCRIPT_RELATIVE_PATH = Path("experiment/mqtt-broker/scripts/mqtt_broker_ctl.py")
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from framework.artifacts import copy_artifact_to_result
from framework.build_records import resolve_verified_build_record
from framework.build import execute_build
from framework.flash import execute_flash
from framework.manifest import (
    apply_repeated_run_samples_to_benchmark_model,
    build_secure_boot_benchmark_model,
    build_secure_boot_benchmark_sample,
    create_result_folder,
    format_manifest_timestamp,
    read_manifest,
    update_manifest,
)
from framework.uart import DEFAULT_CAPTURE_DURATION_SECONDS, DEFAULT_RESTART_COMMAND, execute_uart_capture, execute_uart_monitor
from framework.wolfboot_build import execute_wolfboot_build
from framework.signing import execute_application_signing
from framework.secure_boot_flash import (
    SecureBootFlashProfileError,
    _classical_profile_metadata,
    execute_secure_boot_flash,
)
from framework.benchmark_aggregation import (
    BenchmarkAggregationError,
    aggregate_benchmark_manifests,
    resolve_manifest_inputs,
    write_benchmark_summary_outputs,
)


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


MQTT_TLS_SCHEMA_VERSION = 1
MQTT_TLS_EVIDENCE_CLASSES = {
    "fake_no_network",
    "host_side",
    "stm32_build_only",
    "stm32_runtime",
    "st67w61m1_backed",
}
MQTT_TLS_TRANSPORT_BACKENDS = {
    "fake_no_network",
    "host_socket",
    "stm32_build_only",
    "stm32_runtime",
    "st67w61m1",
}
MQTT_TLS_TRANSPORT_EVIDENCE_MAP = {
    "fake_no_network": {"fake_no_network"},
    "host_socket": {"host_side"},
    "stm32_build_only": {"stm32_build_only"},
    "stm32_runtime": {"stm32_runtime"},
    "st67w61m1": {"st67w61m1_backed"},
}
MQTT_TLS_MODES = {
    "disabled",
    "classical_tls",
    "oqs_experimental_tls",
    "not_applicable",
    "unavailable",
}
MQTT_TLS_UNAVAILABLE_METRIC_FIELDS = {
    "wifi_association",
    "ip_address",
    "tcp_connect",
    "tls_handshake",
    "mqtt_connect",
    "mqtt_publish",
    "mqtt_reconnect",
    "latency_ms",
    "throughput_bytes_per_second",
}
MQTT_TLS_RUNTIME_EVIDENCE_CLASSES = {"stm32_runtime", "st67w61m1_backed"}
MQTT_TLS_NETWORK_EVIDENCE_CLASSES = {"host_side", "stm32_runtime", "st67w61m1_backed"}


def validate_mqtt_tls_config(config: dict[str, Any]) -> None:
    """Validate the Phase M2 MQTT/TLS experiment schema fragment.

    This validates representational support only. It does not open sockets,
    deploy brokers, access SSH, access UART, build firmware, or touch hardware.
    """

    mqtt_config = config.get("mqtt")
    if mqtt_config is None:
        return
    if not isinstance(mqtt_config, dict):
        raise ConfigError("experiment config mqtt field must be a mapping")

    required_fields = [
        "mqtt.schema_version",
        "mqtt.evidence_class",
        "mqtt.transport_backend",
        "mqtt.tls.mode",
        "mqtt.result_schema.unavailable_metrics",
    ]
    for field in required_fields:
        require_field(config, field, "experiment config")

    schema_version = require_field(config, "mqtt.schema_version", "experiment config")
    if schema_version != MQTT_TLS_SCHEMA_VERSION:
        raise ConfigError(f"mqtt.schema_version must be {MQTT_TLS_SCHEMA_VERSION}")

    evidence_class = require_field(config, "mqtt.evidence_class", "experiment config")
    if evidence_class not in MQTT_TLS_EVIDENCE_CLASSES:
        raise ConfigError(
            "mqtt.evidence_class must be one of: "
            + ", ".join(sorted(MQTT_TLS_EVIDENCE_CLASSES))
        )

    transport_backend = require_field(config, "mqtt.transport_backend", "experiment config")
    if transport_backend not in MQTT_TLS_TRANSPORT_BACKENDS:
        raise ConfigError(
            "mqtt.transport_backend must be one of: "
            + ", ".join(sorted(MQTT_TLS_TRANSPORT_BACKENDS))
        )

    allowed_evidence = MQTT_TLS_TRANSPORT_EVIDENCE_MAP[transport_backend]
    if evidence_class not in allowed_evidence:
        raise ConfigError(
            f"mqtt.transport_backend '{transport_backend}' is not compatible with "
            f"mqtt.evidence_class '{evidence_class}'"
        )

    tls_config = mqtt_config.get("tls")
    if not isinstance(tls_config, dict):
        raise ConfigError("experiment config mqtt.tls field must be a mapping")
    tls_mode = require_field(config, "mqtt.tls.mode", "experiment config")
    if tls_mode not in MQTT_TLS_MODES:
        raise ConfigError(
            "mqtt.tls.mode must be one of: " + ", ".join(sorted(MQTT_TLS_MODES))
        )

    certificate_refs = tls_config.get("certificate_refs", {})
    if certificate_refs and not isinstance(certificate_refs, dict):
        raise ConfigError("experiment config mqtt.tls.certificate_refs field must be a mapping")
    if certificate_refs and tls_mode in {"disabled", "not_applicable", "unavailable"}:
        raise ConfigError(
            "mqtt.tls.certificate_refs requires mqtt.tls.mode to be classical_tls or oqs_experimental_tls"
        )
    for ref_name, ref_value in certificate_refs.items():
        if not isinstance(ref_value, str) or not ref_value.strip():
            raise ConfigError(f"mqtt.tls.certificate_refs.{ref_name} must be a non-empty path reference")
        lowered_ref_name = str(ref_name).lower()
        lowered_ref_value = ref_value.lower()
        if "private" in lowered_ref_name or "key" in lowered_ref_name:
            raise ConfigError(
                "mqtt.tls.certificate_refs must not include private key references in Phase M2"
            )
        if lowered_ref_value.endswith((".key", ".pem.key")):
            raise ConfigError(
                "mqtt.tls.certificate_refs must not reference private key files in Phase M2"
            )

    broker = mqtt_config.get("broker", {})
    if broker and not isinstance(broker, dict):
        raise ConfigError("experiment config mqtt.broker field must be a mapping")
    if evidence_class == "host_side":
        require_field(config, "mqtt.broker.host", "experiment config")
        require_field(config, "mqtt.broker.port", "experiment config")
    if evidence_class == "fake_no_network" and broker:
        raise ConfigError("fake_no_network MQTT configs must not configure a real broker endpoint")

    result_schema = mqtt_config.get("result_schema")
    if not isinstance(result_schema, dict):
        raise ConfigError("experiment config mqtt.result_schema field must be a mapping")
    unavailable_metrics = result_schema.get("unavailable_metrics")
    if not isinstance(unavailable_metrics, dict):
        raise ConfigError("mqtt.result_schema.unavailable_metrics field must be a mapping")

    unknown_metrics = set(unavailable_metrics) - MQTT_TLS_UNAVAILABLE_METRIC_FIELDS
    if unknown_metrics:
        raise ConfigError(
            "mqtt.result_schema.unavailable_metrics contains unsupported metric names: "
            + ", ".join(sorted(unknown_metrics))
        )

    for metric_name, reason in unavailable_metrics.items():
        if not isinstance(reason, str) or not reason.strip():
            raise ConfigError(
                f"mqtt.result_schema.unavailable_metrics.{metric_name} must provide a non-empty reason"
            )

    requires_unavailable_runtime = evidence_class not in MQTT_TLS_RUNTIME_EVIDENCE_CLASSES
    runtime_metrics = {"tls_handshake", "mqtt_connect", "mqtt_publish", "mqtt_reconnect", "latency_ms"}
    if requires_unavailable_runtime and not runtime_metrics.issubset(unavailable_metrics):
        raise ConfigError(
            "non-runtime MQTT evidence classes must explicitly mark TLS/MQTT runtime metrics unavailable"
        )

    requires_unavailable_network = evidence_class not in MQTT_TLS_NETWORK_EVIDENCE_CLASSES
    network_metrics = {"wifi_association", "ip_address", "tcp_connect"}
    if requires_unavailable_network and not network_metrics.issubset(unavailable_metrics):
        raise ConfigError(
            "non-network MQTT evidence classes must explicitly mark Wi-Fi/IP/TCP metrics unavailable"
        )


def validate_experiment_config(config: dict[str, Any]) -> None:
    """Validate required fields for the initial experiment config schema."""

    required_fields = [
        "id",
        "description",
        "board",
        "host",
        "boot",
        "firmware.mode",
        "firmware.artifact",
        "uart.expected_boot_message",
        "uart.expected_tick_message",
    ]

    for field in required_fields:
        require_field(config, field, "experiment config")

    validate_mqtt_tls_config(config)


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




CLASSICAL_BENCHMARK_REQUIRED_ALGORITHMS = {"ED25519", "ECC256", "RSA2048"}


def validate_classical_benchmark_profile_model_config(config: dict[str, Any]) -> None:
    """Validate the Phase 11.5a classical signing benchmark profile model."""

    required_fields = [
        "id",
        "description",
        "schema_version",
        "model_phase",
        "benchmark_scope",
        "minimum_comparison_scope",
        "profiles.ecc256_reference.algorithm",
        "profiles.ecc256_reference.signature_algorithm",
        "profiles.ecc256_reference.signature_size_bytes",
        "profiles.ecc256_reference.signing_profile",
        "profiles.ecc256_reference.wolfboot_build_profile",
        "profiles.ecc256_reference.experiment_profile",
    ]

    for field in required_fields:
        require_field(config, field, "classical benchmark profile model")

    model_phase = require_field(config, "model_phase", "classical benchmark profile model")
    allowed_model_phases = {
        "phase_11_5a_classical_profile_model",
        "phase_11_5b_ed25519_profile",
        "phase_11_5c_rsa2048_profile",
        "phase_11_5d_expanded_classical_profiles",
    }
    if model_phase not in allowed_model_phases:
        raise ConfigError(
            "classical benchmark profile model must use a supported Phase 11.5 model_phase"
        )

    scope = config.get("minimum_comparison_scope")
    if not isinstance(scope, dict):
        raise ConfigError("classical benchmark profile model minimum_comparison_scope field must be a mapping")

    algorithms = {str(value.get("algorithm")) for value in scope.values() if isinstance(value, dict)}
    if algorithms != CLASSICAL_BENCHMARK_REQUIRED_ALGORITHMS:
        raise ConfigError(
            "classical benchmark profile model minimum comparison scope must contain exactly ED25519, ECC256, and RSA2048"
        )

    profiles = config.get("profiles")
    if not isinstance(profiles, dict):
        raise ConfigError("classical benchmark profile model profiles field must be a mapping")

    ecc256 = profiles.get("ecc256_reference")
    if not isinstance(ecc256, dict):
        raise ConfigError("classical benchmark profile model missing profiles.ecc256_reference")
    if ecc256.get("algorithm") != "ECC256":
        raise ConfigError("profiles.ecc256_reference.algorithm must be ECC256")
    if ecc256.get("runnable") is not True:
        raise ConfigError("profiles.ecc256_reference.runnable must remain true for the known-good reference path")

    if model_phase == "phase_11_5a_classical_profile_model":
        ed25519 = profiles.get("ed25519_reserved")
        if not isinstance(ed25519, dict):
            raise ConfigError("classical benchmark profile model missing profiles.ed25519_reserved")
        if ed25519.get("algorithm") != "ED25519":
            raise ConfigError("profiles.ed25519_reserved.algorithm must be ED25519")
        if ed25519.get("runnable") is not False:
            raise ConfigError("profiles.ed25519_reserved.runnable must remain false until its implementation sub-phase")
        require_field(ed25519, "unsupported_reason", "profiles.ed25519_reserved")
    else:
        ed25519 = profiles.get("ed25519_benchmark")
        if not isinstance(ed25519, dict):
            raise ConfigError("classical benchmark profile model missing profiles.ed25519_benchmark")
        if ed25519.get("algorithm") != "ED25519":
            raise ConfigError("profiles.ed25519_benchmark.algorithm must be ED25519")
        if ed25519.get("runnable") is not True:
            raise ConfigError("profiles.ed25519_benchmark.runnable must be true for Phase 11.5b or later")
        for field in ("signature_algorithm", "signature_size_bytes", "signing_profile", "wolfboot_build_profile", "experiment_profile", "boot_profile"):
            require_field(ed25519, field, "profiles.ed25519_benchmark")

    if model_phase in {"phase_11_5c_rsa2048_profile", "phase_11_5d_expanded_classical_profiles"}:
        rsa2048 = profiles.get("rsa2048_benchmark")
        if not isinstance(rsa2048, dict):
            raise ConfigError("classical benchmark profile model missing profiles.rsa2048_benchmark")
        if rsa2048.get("algorithm") != "RSA2048":
            raise ConfigError("profiles.rsa2048_benchmark.algorithm must be RSA2048")
        if rsa2048.get("runnable") is not True:
            raise ConfigError("profiles.rsa2048_benchmark.runnable must be true for Phase 11.5c")
        for field in ("signature_algorithm", "key_size_bits", "signature_size_bytes", "signing_profile", "wolfboot_build_profile", "experiment_profile", "boot_profile"):
            require_field(rsa2048, field, "profiles.rsa2048_benchmark")
    else:
        rsa2048 = profiles.get("rsa2048_reserved")
        if not isinstance(rsa2048, dict):
            raise ConfigError("classical benchmark profile model missing profiles.rsa2048_reserved")
        if rsa2048.get("algorithm") != "RSA2048":
            raise ConfigError("profiles.rsa2048_reserved.algorithm must be RSA2048")
        if rsa2048.get("runnable") is not False:
            raise ConfigError("profiles.rsa2048_reserved.runnable must remain false until Phase 11.5c")
        require_field(rsa2048, "unsupported_reason", "profiles.rsa2048_reserved")

    if model_phase == "phase_11_5d_expanded_classical_profiles":
        expanded_required = {
            "ecc384_benchmark": "ECC384",
            "ecc521_benchmark": "ECC521",
            "ed448_benchmark": "ED448",
            "rsa3072_benchmark": "RSA3072",
            "rsa4096_benchmark": "RSA4096",
        }
        for profile_name, algorithm_name in expanded_required.items():
            expanded_profile = profiles.get(profile_name)
            if not isinstance(expanded_profile, dict):
                raise ConfigError(f"classical benchmark profile model missing profiles.{profile_name}")
            if expanded_profile.get("algorithm") != algorithm_name:
                raise ConfigError(f"profiles.{profile_name}.algorithm must be {algorithm_name}")
            if expanded_profile.get("runnable") is not True:
                raise ConfigError(f"profiles.{profile_name}.runnable must be true for Phase 11.5d")
            for field in ("signature_algorithm", "key_size_bits", "signature_size_bytes", "signing_profile", "wolfboot_build_profile", "experiment_profile", "boot_profile"):
                require_field(expanded_profile, field, f"profiles.{profile_name}")


def validate_wolfboot_build_profile_config(config: dict[str, Any]) -> None:
    """Validate required fields for a wolfBoot build-profile config."""

    required_fields = [
        "id",
        "description",
        "source_dir",
        "output_dir",
        "artifact",
        "target",
        "signature_algorithm",
        "boot_profile",
        "build.command",
    ]

    for field in required_fields:
        require_field(config, field, "wolfBoot build profile")

    algorithm = require_field(config, "signature_algorithm", "wolfBoot build profile")
    if algorithm not in {"ecdsa_p256", "ed25519", "rsa2048", "ecc384", "ecc521", "ed448", "rsa3072", "rsa4096", "mldsa44", "mldsa65"}:
        raise ConfigError("wolfBoot build profile signature_algorithm must be ecdsa_p256, ed25519, rsa2048, ecc384, ecc521, ed448, rsa3072, rsa4096, mldsa44, or mldsa65")

    build_config = config.get("build")
    if not isinstance(build_config, dict):
        raise ConfigError("wolfBoot build profile build field must be a mapping")

    has_config_template = bool(build_config.get("config_template"))
    has_generated_config = bool(build_config.get("generated_config"))
    if has_config_template != has_generated_config:
        raise ConfigError(
            "wolfBoot build profile must set both build.config_template and "
            "build.generated_config, or neither"
        )


def validate_application_signing_profile_config(config: dict[str, Any]) -> None:
    """Validate required fields for an application-signing profile config."""

    required_fields = [
        "id",
        "description",
        "input_image",
        "signed_image",
        "signature_algorithm",
        "private_key",
        "image_version",
        "sign.command",
    ]

    for field in required_fields:
        require_field(config, field, "application signing profile")

    algorithm = require_field(config, "signature_algorithm", "application signing profile")
    if algorithm not in {"ecdsa_p256", "ed25519", "rsa2048", "ecc384", "ecc521", "ed448", "rsa3072", "rsa4096", "mldsa44", "mldsa65"}:
        raise ConfigError("application signing profile signature_algorithm must be ecdsa_p256, ed25519, rsa2048, ecc384, ecc521, ed448, rsa3072, rsa4096, mldsa44, or mldsa65")

    sign_config = config.get("sign")
    if not isinstance(sign_config, dict):
        raise ConfigError("application signing profile sign field must be a mapping")

    keygen_config = config.get("keygen", {})
    if keygen_config is None:
        keygen_config = {}
    if not isinstance(keygen_config, dict):
        raise ConfigError("application signing profile keygen field must be a mapping")

    binary_conversion_config = config.get("binary_conversion", {})
    if binary_conversion_config is None:
        binary_conversion_config = {}
    if not isinstance(binary_conversion_config, dict):
        raise ConfigError("application signing profile binary_conversion field must be a mapping")

    if keygen_config.get("enabled") is True:
        require_field(config, "keygen.command", "application signing profile")

    if binary_conversion_config.get("enabled") is True:
        require_field(config, "input_elf", "application signing profile")
        require_field(config, "binary_conversion.command", "application signing profile")


def repo_root_from_signing_profile_path(profile_path: Path | str) -> Path:
    """Resolve the repository root from configs/signing/<name>.yaml."""

    resolved_path = Path(profile_path).resolve()
    if resolved_path.parent.name != "signing":
        raise ConfigError(
            "application signing profile must live under configs/signing/ for automatic repository resolution"
        )

    configs_root = resolved_path.parent.parent
    return configs_root.parent


def repo_root_from_build_profile_path(profile_path: Path | str) -> Path:
    """Resolve the repository root from configs/builds/<name>.yaml."""

    resolved_path = Path(profile_path).resolve()
    if resolved_path.parent.name != "builds":
        raise ConfigError(
            "wolfBoot build profile must live under configs/builds/ for automatic repository resolution"
        )

    configs_root = resolved_path.parent.parent
    return configs_root.parent

def validate_boot_config_for_inspection(config: dict[str, Any]) -> None:
    """Validate fields required to inspect any boot config.

    Planned boot profiles use the same base schema as runnable profiles, but
    they are allowed to set ``runnable: false`` so they can exist in Git without
    being accepted by execution-oriented experiment workflows.
    """

    required_fields = [
        "id",
        "mode",
        "description",
        "runnable",
    ]

    for field in required_fields:
        require_field(config, field, "boot config")


def validate_boot_config(config: dict[str, Any]) -> None:
    """Validate a boot config for execution-oriented experiment workflows."""

    validate_boot_config_for_inspection(config)

    if require_field(config, "runnable", "boot config") is not True:
        raise ConfigError("boot config is planned and not runnable for execution: runnable")


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


def resolve_related_config_paths(experiment_path: Path | str) -> tuple[Path, Path, Path]:
    """Resolve board, host, and boot config paths referenced by an experiment config."""

    experiment_config_path = Path(experiment_path)
    experiment_config = load_config(experiment_config_path)
    validate_experiment_config(experiment_config)

    configs_root = _configs_root_from_experiment_path(experiment_config_path)
    board_id = require_field(experiment_config, "board", "experiment config")
    host_id = require_field(experiment_config, "host", "experiment config")
    boot_id = require_field(experiment_config, "boot", "experiment config")

    board_path = configs_root / "boards" / f"{board_id}.yaml"
    host_path = configs_root / "hosts" / f"{host_id}.yaml"
    boot_path = configs_root / "boot" / f"{boot_id}.yaml"

    return board_path, host_path, boot_path


def load_experiment_bundle(experiment_path: Path | str) -> dict[str, dict[str, Any]]:
    """Load and validate an experiment plus its referenced board and host configs."""

    experiment_config_path = Path(experiment_path)

    experiment_config = load_config(experiment_config_path)
    validate_experiment_config(experiment_config)

    board_path, host_path, boot_path = resolve_related_config_paths(experiment_config_path)

    board_config = load_config(board_path)
    host_config = load_config(host_path)
    boot_config = load_config(boot_path)

    validate_board_config(board_config)
    validate_host_config(host_config)
    validate_boot_config(boot_config)

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

    expected_boot_id = require_field(experiment_config, "boot", "experiment config")
    actual_boot_id = require_field(boot_config, "id", "boot config")

    if actual_boot_id != expected_boot_id:
        raise ConfigError(
            f"boot config id mismatch: experiment references '{expected_boot_id}' "
            f"but {boot_path} contains '{actual_boot_id}'"
        )

    boot_mode = require_field(boot_config, "mode", "boot config")
    firmware_mode = require_field(experiment_config, "firmware.mode", "experiment config")

    if firmware_mode != boot_mode:
        raise ConfigError(
            f"boot mode mismatch: experiment firmware.mode is '{firmware_mode}' "
            f"but boot config mode is '{boot_mode}'"
        )

    return {
        "experiment": experiment_config,
        "board": board_config,
        "host": host_config,
        "boot": boot_config,
    }


def load_secure_boot_experiment_bundle(experiment_path: Path | str) -> dict[str, dict[str, Any]]:
    """Load a wolfBoot secure-boot flash experiment without enabling generic execution.

    Phase 10h uses the planned wolfBoot boot config explicitly for the
    two-artifact flash workflow. The generic experiment loader still rejects
    non-runnable boot configs so normal direct-flash commands cannot
    accidentally treat the wolfBoot profile as a validated boot path.
    """

    experiment_config_path = Path(experiment_path)

    experiment_config = load_config(experiment_config_path)
    validate_experiment_config(experiment_config)

    board_path, host_path, boot_path = resolve_related_config_paths(experiment_config_path)

    board_config = load_config(board_path)
    host_config = load_config(host_path)
    boot_config = load_config(boot_path)

    validate_board_config(board_config)
    validate_host_config(host_config)
    validate_boot_config_for_inspection(boot_config)

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

    expected_boot_id = require_field(experiment_config, "boot", "experiment config")
    actual_boot_id = require_field(boot_config, "id", "boot config")
    if actual_boot_id != expected_boot_id:
        raise ConfigError(
            f"boot config id mismatch: experiment references '{expected_boot_id}' "
            f"but {boot_path} contains '{actual_boot_id}'"
        )

    boot_mode = require_field(boot_config, "mode", "boot config")
    firmware_mode = require_field(experiment_config, "firmware.mode", "experiment config")
    if firmware_mode != boot_mode:
        raise ConfigError(
            f"boot mode mismatch: experiment firmware.mode is '{firmware_mode}' "
            f"but boot config mode is '{boot_mode}'"
        )

    return {
        "experiment": experiment_config,
        "board": board_config,
        "host": host_config,
        "boot": boot_config,
    }


def format_status_summary(bundle: dict[str, dict[str, Any]]) -> str:
    """Format a human-readable status summary."""

    experiment = bundle["experiment"]
    board = bundle["board"]
    host = bundle["host"]
    boot = bundle["boot"]

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
            f"Boot config: {boot['id']}",
            f"Boot mode: {boot['mode']}",
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

    uart_result = None
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



def run_wolfboot_build_command(args: argparse.Namespace) -> int:
    """Run a configured wolfBoot build profile without flashing or UART access."""

    profile = load_config(args.profile)
    validate_wolfboot_build_profile_config(profile)
    repo_root = repo_root_from_build_profile_path(args.profile)

    result = execute_wolfboot_build(
        profile=profile,
        repo_root=repo_root,
        results_root=args.results_dir,
    )

    print("wolfBoot build completed" if result.return_code == 0 else "wolfBoot build failed")
    print("------------------------" if result.return_code == 0 else "---------------------")
    print(f"Profile: {result.profile_id}")
    print(f"Result directory: {result.result_dir}")
    print(f"Build log: {result.log_path}")
    print(f"Source directory: {result.source_dir}")
    print(f"Output directory: {result.output_dir}")
    print(f"Artifact path: {result.artifact_path}")
    print(f"Artifact exists: {result.artifact_exists}")
    if result.artifact_sha256 is not None:
        print(f"Artifact SHA-256: {result.artifact_sha256}")
    if result.failure_reason is not None:
        print(f"Failure reason: {result.failure_reason}")
    print(f"Return code: {result.return_code}")
    print("No signing key generation, application signing, flash, UART access, SSH, hardware access, or network access was performed.")

    return result.return_code


def run_sign_application_command(args: argparse.Namespace) -> int:
    """Run a configured local application-signing profile without flashing or UART access."""

    profile = load_config(args.profile)
    validate_application_signing_profile_config(profile)
    repo_root = repo_root_from_signing_profile_path(args.profile)

    result = execute_application_signing(
        profile=profile,
        repo_root=repo_root,
        results_root=args.results_dir,
    )

    print("Application signing completed" if result.return_code == 0 else "Application signing failed")
    print("-----------------------------" if result.return_code == 0 else "--------------------------")
    print(f"Profile: {result.profile_id}")
    print(f"Result directory: {result.result_dir}")
    print(f"Signing log: {result.log_path}")
    print(f"Input image: {result.input_image_path}")
    print(f"Signed image: {result.signed_image_path}")
    print(f"Signature algorithm: {result.signature_algorithm}")
    print(f"Image version: {result.image_version}")
    print(f"Private key path: {result.private_key_path}")
    print(f"Private key present after command: {result.private_key_present_after}")
    if result.signed_image_sha256 is not None:
        print(f"Signed image SHA-256: {result.signed_image_sha256}")
    if result.retained_signed_image_path is not None:
        print(f"Retained signed image: {result.retained_signed_image_path}")
    if result.failure_reason is not None:
        print(f"Failure reason: {result.failure_reason}")
    print(f"Return code: {result.return_code}")
    print("No private signing key was copied into results. No flash, UART access, SSH, hardware access, or network access was performed.")

    return result.return_code



def _secure_boot_sample_artifact_identity(
    *,
    flash_result: Any,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build artifact identity evidence referenced by one benchmark sample."""

    boot_signature = manifest.get("boot_signature", {})
    if not isinstance(boot_signature, dict):
        boot_signature = {}

    return {
        "run_id": manifest.get("run_id"),
        "experiment": manifest.get("experiment"),
        "boot_mode": manifest.get("boot_mode"),
        "boot_crypto": manifest.get("boot_crypto"),
        "signature_algorithm": boot_signature.get("algorithm"),
        "signature_size_bytes": boot_signature.get("signature_size_bytes", manifest.get("signature_size")),
        "image_version": boot_signature.get("image_version"),
        "wolfboot_artifact_path": str(flash_result.wolfboot.artifact_path),
        "wolfboot_sha256": flash_result.wolfboot.artifact_sha256,
        "signed_application_artifact_path": str(flash_result.signed_application.artifact_path),
        "signed_application_sha256": flash_result.signed_application.artifact_sha256,
    }


def _secure_boot_sample_from_uart_result(
    *,
    run_index: int,
    uart_result: Any,
    artifact_identity: dict[str, Any],
) -> dict[str, Any]:
    """Convert one UART capture result into a Phase 11.2 benchmark sample."""

    marker_detection = {
        "boot_marker_present": uart_result.boot_marker_present,
        "tick_present": uart_result.tick_present,
        "secure_boot_marker_present": uart_result.secure_boot_marker_present,
        "data_captured": uart_result.data_captured,
        "uart_return_code": uart_result.return_code,
        "capture_return_code": uart_result.capture.return_code,
        "log": uart_result.log_path.name,
    }
    sample_passed = (
        uart_result.return_code == 0
        and uart_result.verification_time_ms is not None
        and uart_result.verification_cycles is not None
    )
    return build_secure_boot_benchmark_sample(
        run_index=run_index,
        timestamp=format_manifest_timestamp(),
        verification_time_ms=uart_result.verification_time_ms,
        verification_cycles=uart_result.verification_cycles,
        verification_cpu_hz=uart_result.verification_cpu_hz,
        verification_result_code=uart_result.verification_result_code,
        verification_time_source=uart_result.verification_time_source,
        verification_cycles_source=(
            "uart_explicit_verification_cycles_marker"
            if uart_result.verification_cycles is not None
            else "unavailable"
        ),
        uart_marker_detection_result=marker_detection,
        sample_verdict="passed" if sample_passed else "failed",
        referenced_artifact_identity=artifact_identity,
        max_stack_used_bytes=getattr(uart_result, "max_stack_used_bytes", None),
        stack_metric_source=getattr(uart_result, "stack_metric_source", "unavailable"),
        heap_used_bytes=getattr(uart_result, "heap_used_bytes", None),
        heap_metric_source=getattr(uart_result, "heap_metric_source", "unavailable"),
        runtime_memory_limitations=getattr(uart_result, "runtime_memory_limitations", None),
    )

def run_secure_boot_flash_command(args: argparse.Namespace) -> int:
    """Run the wolfBoot secure-boot flash, evidence, repeated-run, and negative-test workflow."""

    repeat_count = int(getattr(args, "repeat_count", 1))
    if repeat_count < 1:
        print("Error: --repeat-count must be at least 1.", file=sys.stderr)
        return 45
    if args.negative_corrupt_application and args.skip_uart:
        print(
            "Error: --negative-corrupt-application requires UART capture evidence; do not combine it with --skip-uart.",
            file=sys.stderr,
        )
        return 44
    if args.skip_uart and repeat_count > 1:
        print(
            "Error: --repeat-count greater than 1 requires UART capture; do not combine it with --skip-uart.",
            file=sys.stderr,
        )
        return 45
    if args.negative_corrupt_application and repeat_count > 1:
        print(
            "Error: repeated-run benchmark samples are only supported for the positive secure-boot path; do not combine --repeat-count greater than 1 with --negative-corrupt-application.",
            file=sys.stderr,
        )
        return 45

    bundle = load_secure_boot_experiment_bundle(args.experiment)
    if args.negative_corrupt_application:
        bundle["experiment"].setdefault("secure_boot_flash", {})[
            "negative_test_corrupt_application"
        ] = True

    result_dir, manifest = create_result_folder(bundle, args.results_dir)
    repo_root = repo_root_from_experiment_path(args.experiment)

    try:
        flash_result = execute_secure_boot_flash(
            bundle=bundle,
            repo_root=repo_root,
            result_dir=result_dir,
        )
    except SecureBootFlashProfileError as exc:
        update_manifest(
            result_dir / "manifest.json",
            {
                "result": "secure_boot_flash_failed",
                "secure_boot_flash": {
                    "return_code": 43,
                    "failure_stage": "profile_validation",
                    "failure_reason": str(exc),
                    "log": None,
                },
            },
        )
        print(f"Error: {exc}", file=sys.stderr)
        return 43

    uart_results: list[Any] = []
    samples: list[dict[str, Any]] = []
    uart_return_code: int | None = None
    uart_duration_seconds = 0.0
    if flash_result.return_code == 0 and not args.skip_uart:
        manifest_after_flash = read_manifest(result_dir / "manifest.json")
        artifact_identity = _secure_boot_sample_artifact_identity(
            flash_result=flash_result,
            manifest=manifest_after_flash,
        )
        for run_index in range(1, repeat_count + 1):
            log_name = "uart.log" if repeat_count == 1 else f"uart_sample_{run_index:03d}.log"
            uart_result = execute_uart_capture(
                bundle=bundle,
                repo_root=repo_root,
                result_dir=result_dir,
                duration_seconds=args.uart_duration_seconds,
                restart_command=_monitor_restart_command(bundle, None),
                log_name=log_name,
            )
            uart_results.append(uart_result)
            uart_duration_seconds += uart_result.duration_seconds
            samples.append(
                _secure_boot_sample_from_uart_result(
                    run_index=run_index,
                    uart_result=uart_result,
                    artifact_identity=artifact_identity,
                )
            )
            if uart_result.return_code != 0:
                uart_return_code = uart_result.return_code
            elif uart_return_code is None:
                uart_return_code = 0
    elif flash_result.return_code != 0:
        update_manifest(
            result_dir / "manifest.json",
            {
                "uart": {
                    "log": None,
                    "skipped": True,
                    "skip_reason": "secure_boot_flash_failed",
                },
            },
        )
    elif args.skip_uart:
        update_manifest(
            result_dir / "manifest.json",
            {
                "uart": {
                    "log": None,
                    "skipped": True,
                    "skip_reason": "explicit_skip_uart",
                },
            },
        )

    uart_result = uart_results[-1] if uart_results else None
    secure_boot_marker_present = (
        None if uart_result is None else uart_result.secure_boot_marker_present
    )
    boot_marker_present = None if uart_result is None else uart_result.boot_marker_present
    tick_present = None if uart_result is None else uart_result.tick_present
    verification_time_ms = None if uart_result is None else uart_result.verification_time_ms
    verification_cycles = None if uart_result is None else uart_result.verification_cycles
    verification_cpu_hz = None if uart_result is None else uart_result.verification_cpu_hz
    verification_result_code = None if uart_result is None else uart_result.verification_result_code
    verification_time_source = (
        "unavailable" if uart_result is None else uart_result.verification_time_source
    )
    verification_time_measurement_method = (
        "UART capture did not run, so no verification timing source was available."
        if uart_result is None
        else uart_result.verification_time_measurement_method
    )
    verification_time_limitations = (
        "No UART timing evidence was captured because UART was skipped or secure-boot flashing failed."
        if uart_result is None
        else uart_result.verification_time_limitations
    )
    stack_sample_values = [
        sample.get("runtime_memory_metrics", {}).get("max_stack_used_bytes")
        for sample in samples
        if isinstance(sample.get("runtime_memory_metrics"), dict)
        and sample.get("runtime_memory_metrics", {}).get("max_stack_used_bytes") is not None
    ]
    max_stack_used_bytes = max(stack_sample_values) if stack_sample_values else (None if uart_result is None else getattr(uart_result, "max_stack_used_bytes", None))
    stack_metric_source = (
        "unavailable"
        if max_stack_used_bytes is None
        else ("uart_explicit_stack_high_water_marker" if stack_sample_values else getattr(uart_result, "stack_metric_source", "unavailable"))
    )
    heap_sample_values = [
        sample.get("runtime_memory_metrics", {}).get("heap_used_bytes")
        for sample in samples
        if isinstance(sample.get("runtime_memory_metrics"), dict)
        and sample.get("runtime_memory_metrics", {}).get("heap_used_bytes") is not None
    ]
    heap_used_bytes = max(heap_sample_values) if heap_sample_values else (None if uart_result is None else getattr(uart_result, "heap_used_bytes", None))
    heap_metric_source = (
        "unavailable"
        if heap_used_bytes is None
        else ("uart_explicit_heap_marker" if heap_sample_values else getattr(uart_result, "heap_metric_source", "unavailable"))
    )
    runtime_memory_limitations = (
        "No UART runtime memory evidence was captured because UART was skipped or secure-boot flashing failed."
        if uart_result is None
        else getattr(uart_result, "runtime_memory_limitations", "No explicit runtime memory evidence was available.")
    )
    capture_completed = (
        False
        if uart_result is None
        else uart_result.capture.return_code in {0, 124}
    )
    negative_test_requested = bool(args.negative_corrupt_application)
    negative_test_passed = (
        negative_test_requested
        and flash_result.return_code == 0
        and capture_completed
        and boot_marker_present is False
        and tick_present is False
        and secure_boot_marker_present is False
    )
    positive_boot_evidence_passed = (
        not negative_test_requested
        and flash_result.return_code == 0
        and bool(uart_results)
        and all(sample.get("sample_verdict") == "passed" for sample in samples)
        and secure_boot_marker_present is True
    )

    any_invalid_sample = bool(samples) and any(
        sample.get("sample_verdict") != "passed" for sample in samples
    )

    if flash_result.return_code != 0:
        final_return_code = flash_result.return_code
        failure_stage = flash_result.failure_stage
    elif negative_test_requested:
        final_return_code = 0 if negative_test_passed else (uart_return_code or 9)
        failure_stage = "none" if negative_test_passed else "negative_uart_evidence"
    elif uart_return_code is not None and uart_return_code != 0:
        final_return_code = uart_return_code
        failure_stage = "uart"
    elif any_invalid_sample:
        final_return_code = 9
        failure_stage = "benchmark_sample"
    else:
        final_return_code = 0
        failure_stage = "none"

    if negative_test_requested:
        result_status = (
            "secure_boot_negative_test_passed"
            if final_return_code == 0
            else "secure_boot_negative_test_failed"
        )
    elif positive_boot_evidence_passed:
        result_status = "secure_boot_benchmark_repeated_run_passed" if repeat_count > 1 else "secure_boot_positive_boot_evidence_passed"
    elif final_return_code == 0 and uart_return_code is None:
        result_status = "secure_boot_flash_passed"
    else:
        result_status = "secure_boot_flash_failed"

    manifest_before_final_update = read_manifest(result_dir / "manifest.json")
    secure_boot_evidence = manifest_before_final_update.get("secure_boot_evidence", {})
    if not isinstance(secure_boot_evidence, dict):
        secure_boot_evidence = {}
    secure_boot_evidence.update(
        {
            "result": result_status,
            "uart_evidence": {
                "log": None if uart_return_code is None else ("uart.log" if repeat_count == 1 else uart_results[-1].log_path.name),
                "logs": [result.log_path.name for result in uart_results],
                "skipped": args.skip_uart or flash_result.return_code != 0,
                "return_code": uart_return_code,
                "boot_marker_present": boot_marker_present,
                "tick_present": tick_present,
                "secure_boot_marker_present": secure_boot_marker_present,
                "positive_boot_evidence_passed": positive_boot_evidence_passed,
            },
            "boot_timing": {
                "verification_time_ms": verification_time_ms,
                "verification_cycles": verification_cycles,
                "verification_cpu_hz": verification_cpu_hz,
                "verification_result_code": verification_result_code,
                "verification_time_source": verification_time_source,
                "measurement_method": verification_time_measurement_method,
                "limitations": verification_time_limitations,
            },
            "runtime_memory": {
                "max_stack_used_bytes": max_stack_used_bytes,
                "stack_metric_source": stack_metric_source,
                "heap_used_bytes": heap_used_bytes,
                "heap_metric_source": heap_metric_source,
                "limitations": runtime_memory_limitations,
            },
            "negative_test": {
                "enabled": negative_test_requested,
                "verdict": (
                    "passed"
                    if negative_test_passed
                    else "failed"
                    if negative_test_requested
                    else "not_run"
                ),
                "normal_boot_marker_absent": boot_marker_present is False,
                "tick_marker_absent": tick_present is False,
                "secure_boot_marker_absent": secure_boot_marker_present is False,
                "capture_completed": capture_completed,
                "source_image_modified": False,
            },
        }
    )

    boot_signature = manifest_before_final_update.get("boot_signature", {})
    if not isinstance(boot_signature, dict):
        boot_signature = {}
    secure_boot_flash = manifest_before_final_update.get("secure_boot_flash", {})
    if not isinstance(secure_boot_flash, dict):
        secure_boot_flash = {}
    wolfboot_evidence = secure_boot_flash.get("wolfboot", {})
    if not isinstance(wolfboot_evidence, dict):
        wolfboot_evidence = {}
    signed_application_evidence = secure_boot_flash.get("signed_application", {})
    if not isinstance(signed_application_evidence, dict):
        signed_application_evidence = {}
    prior_benchmark_evidence = manifest_before_final_update.get("secure_boot_benchmark", {})
    if not isinstance(prior_benchmark_evidence, dict):
        prior_benchmark_evidence = {}
    prior_signed_artifact_metrics = prior_benchmark_evidence.get("signed_artifact_metrics", {})
    if not isinstance(prior_signed_artifact_metrics, dict):
        prior_signed_artifact_metrics = {}
    prior_build_time_metrics = prior_benchmark_evidence.get("build_time_metrics", {})
    if not isinstance(prior_build_time_metrics, dict):
        prior_build_time_metrics = {}
    benchmark_evidence = build_secure_boot_benchmark_model(
        experiment_id=str(bundle["experiment"]["id"]),
        boot_mode=str(bundle.get("boot", {}).get("mode", bundle["experiment"].get("firmware", {}).get("mode", "unknown"))),
        boot_crypto=str(manifest_before_final_update.get("boot_crypto", bundle["experiment"].get("boot_crypto", "ecdsa_p256"))),
        signature_algorithm=boot_signature.get("algorithm"),
        signature_size_bytes=boot_signature.get("signature_size_bytes", manifest_before_final_update.get("signature_size")),
        image_version=boot_signature.get("image_version"),
        wolfboot_artifact_path=wolfboot_evidence.get("artifact_path"),
        wolfboot_sha256=wolfboot_evidence.get("sha256"),
        wolfboot_elf_size_bytes=prior_signed_artifact_metrics.get("wolfboot_elf_size_bytes"),
        retained_wolfboot_artifact_path=prior_signed_artifact_metrics.get("retained_wolfboot_artifact_path"),
        retained_wolfboot_artifact_size_bytes=prior_signed_artifact_metrics.get("retained_wolfboot_artifact_size_bytes"),
        signed_application_artifact_path=signed_application_evidence.get("artifact_path"),
        signed_application_sha256=signed_application_evidence.get("sha256"),
        signed_application_size_bytes=prior_signed_artifact_metrics.get("signed_application_size_bytes"),
        unsigned_application_artifact_path=prior_signed_artifact_metrics.get("unsigned_application_artifact_path"),
        unsigned_application_sha256=prior_signed_artifact_metrics.get("unsigned_application_sha256"),
        unsigned_application_size_bytes=prior_signed_artifact_metrics.get("unsigned_application_size_bytes"),
        bootloader_text_bytes=prior_build_time_metrics.get("bootloader_text_bytes"),
        bootloader_data_bytes=prior_build_time_metrics.get("bootloader_data_bytes"),
        bootloader_bss_bytes=prior_build_time_metrics.get("bootloader_bss_bytes"),
        bootloader_flash_bytes=prior_build_time_metrics.get("bootloader_flash_bytes"),
        bootloader_static_ram_bytes=prior_build_time_metrics.get("bootloader_static_ram_bytes"),
        static_metrics_source=prior_build_time_metrics.get("source", "unavailable"),
        static_metrics_limitations=prior_build_time_metrics.get("limitations"),
        verification_time_ms=verification_time_ms,
        verification_cycles=verification_cycles,
        verification_cpu_hz=verification_cpu_hz,
        verification_result_code=verification_result_code,
        verification_time_source=verification_time_source,
        verification_cycles_source=(
            "uart_explicit_verification_cycles_marker"
            if verification_cycles is not None
            else "unavailable"
        ),
        runtime_measurement_method=verification_time_measurement_method,
        runtime_limitations=verification_time_limitations,
        max_stack_used_bytes=max_stack_used_bytes,
        stack_metric_source=stack_metric_source,
        heap_used_bytes=heap_used_bytes,
        heap_metric_source=heap_metric_source,
        runtime_memory_limitations=runtime_memory_limitations,
        classical_profile_metadata=_classical_profile_metadata(bundle["experiment"]),
    )
    if samples:
        benchmark_evidence = apply_repeated_run_samples_to_benchmark_model(
            benchmark_evidence,
            samples,
        )

    aggregate_statistics = benchmark_evidence.get("aggregate_statistics", {})
    headline_metrics = (
        aggregate_statistics.get("headline_metrics", {})
        if isinstance(aggregate_statistics, dict)
        else {}
    )

    update_manifest(
        result_dir / "manifest.json",
        {
            "result": result_status,
            "secure_boot_evidence": secure_boot_evidence,
            "secure_boot_benchmark": benchmark_evidence,
            "secure_boot_run": {
                "return_code": final_return_code,
                "flash_return_code": flash_result.return_code,
                "uart_return_code": uart_return_code,
                "flash_log": "secure_boot_flash.log",
                "uart_log": None if uart_return_code is None else ("uart.log" if repeat_count == 1 else uart_results[-1].log_path.name),
                "uart_logs": [result.log_path.name for result in uart_results],
                "uart_skipped": args.skip_uart or flash_result.return_code != 0,
                "failure_stage": failure_stage,
                "duration_seconds": round(
                    flash_result.duration_seconds + uart_duration_seconds,
                    3,
                ),
                "boot_confirmed_from_uart_log": positive_boot_evidence_passed,
                "boot_path_distinguished": secure_boot_marker_present is True,
                "expected_secure_boot_marker": bundle["experiment"].get("uart", {}).get(
                    "expected_secure_boot_message"
                ),
                "secure_boot_marker_present": secure_boot_marker_present,
                "boot_marker_present": boot_marker_present,
                "tick_present": tick_present,
                "positive_boot_evidence_passed": positive_boot_evidence_passed,
                "repeat_count_requested": repeat_count,
                "repeated_run_sample_count": len(samples),
                "primary_verification_time_ms": headline_metrics.get("primary_verification_time_ms"),
                "primary_verification_cycles": headline_metrics.get("primary_verification_cycles"),
                "primary_statistic": headline_metrics.get("primary_statistic") if headline_metrics else None,
                "verification_time_ms": verification_time_ms,
                "verification_cycles": verification_cycles,
                "verification_cpu_hz": verification_cpu_hz,
                "verification_result_code": verification_result_code,
                "verification_time_source": verification_time_source,
                "verification_time_measurement_method": verification_time_measurement_method,
                "verification_time_limitations": verification_time_limitations,
                "max_stack_used_bytes": max_stack_used_bytes,
                "stack_metric_source": stack_metric_source,
                "heap_used_bytes": heap_used_bytes,
                "heap_metric_source": heap_metric_source,
                "runtime_memory_limitations": runtime_memory_limitations,
            },
            "boot_timing": {
                "verification_time_ms": verification_time_ms,
                "verification_cycles": verification_cycles,
                "verification_cpu_hz": verification_cpu_hz,
                "verification_result_code": verification_result_code,
                "verification_time_source": verification_time_source,
                "measurement_method": verification_time_measurement_method,
                "limitations": verification_time_limitations,
            },
            "runtime_memory": {
                "max_stack_used_bytes": max_stack_used_bytes,
                "stack_metric_source": stack_metric_source,
                "heap_used_bytes": heap_used_bytes,
                "heap_metric_source": heap_metric_source,
                "limitations": runtime_memory_limitations,
            },
            "secure_boot_negative_test": {
                "enabled": negative_test_requested,
                "verdict": (
                    "passed"
                    if negative_test_passed
                    else "failed"
                    if negative_test_requested
                    else "not_run"
                ),
                "normal_boot_marker_absent": boot_marker_present is False,
                "tick_marker_absent": tick_present is False,
                "secure_boot_marker_absent": secure_boot_marker_present is False,
                "capture_completed": capture_completed,
                "source_image_modified": False,
            },
        },
    )

    print("Secure-boot flash workflow completed" if final_return_code == 0 else "Secure-boot flash workflow failed")
    print("------------------------------------" if final_return_code == 0 else "---------------------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Flash log: {flash_result.log_path}")
    print(f"wolfBoot artifact: {flash_result.wolfboot.artifact_path}")
    print(f"wolfBoot offset: {flash_result.wolfboot.offset}")
    if flash_result.wolfboot.artifact_sha256 is not None:
        print(f"wolfBoot SHA-256: {flash_result.wolfboot.artifact_sha256}")
    print(f"Signed application artifact: {flash_result.signed_application.artifact_path}")
    print(f"Signed application offset: {flash_result.signed_application.offset}")
    if flash_result.signed_application.artifact_sha256 is not None:
        print(f"Signed application SHA-256: {flash_result.signed_application.artifact_sha256}")
    print(f"Flash return code: {flash_result.return_code}")
    print(f"Failure stage: {failure_stage}")
    if flash_result.failure_reason is not None:
        print(f"Failure reason: {flash_result.failure_reason}")
    if args.skip_uart:
        print("UART capture skipped by explicit request. No boot confirmation was made.")
    elif uart_return_code is None:
        print("UART capture skipped because secure-boot flashing failed.")
    else:
        print(f"UART samples: {len(uart_results)}")
        for result in uart_results:
            print(f"UART log: {result.log_path}")
        print(f"UART return code: {uart_return_code}")
        print("Boot confirmation is based on the recorded UART marker evaluation.")
        if isinstance(aggregate_statistics, dict):
            print(f"Benchmark sample count: {aggregate_statistics.get('sample_count', len(uart_results))}")
            print(f"Benchmark valid samples: {aggregate_statistics.get('valid_sample_count', 0)}")
            print(f"Benchmark failed samples: {aggregate_statistics.get('failed_sample_count', 0)}")
        if headline_metrics.get("primary_verification_time_ms") is not None:
            print(f"Primary verification time (median): {headline_metrics['primary_verification_time_ms']} ms")
        elif verification_time_ms is None:
            print("Verification time: unavailable")
        else:
            print(f"Verification time: {verification_time_ms} ms")
        if headline_metrics.get("primary_verification_cycles") is not None:
            print(f"Primary verification cycles (median): {headline_metrics['primary_verification_cycles']}")
        elif verification_cycles is None:
            print("Verification cycles: unavailable")
        else:
            print(f"Verification cycles: {verification_cycles}")
        verification_time_stats = aggregate_statistics.get("verification_time_ms", {}) if isinstance(aggregate_statistics, dict) else {}
        verification_cycle_stats = aggregate_statistics.get("verification_cycles", {}) if isinstance(aggregate_statistics, dict) else {}
        if verification_time_stats.get("median") is not None:
            print(
                "Verification time stats (ms): "
                f"min={verification_time_stats.get('minimum')}, "
                f"mean={verification_time_stats.get('mean')}, "
                f"median={verification_time_stats.get('median')}, "
                f"max={verification_time_stats.get('maximum')}, "
                f"std={verification_time_stats.get('standard_deviation')}, "
                f"range={verification_time_stats.get('range')}, "
                f"cv_percent={verification_time_stats.get('coefficient_of_variation_percent')}"
            )
        if verification_cycle_stats.get("median") is not None:
            print(
                "Verification cycle stats: "
                f"min={verification_cycle_stats.get('minimum')}, "
                f"mean={verification_cycle_stats.get('mean')}, "
                f"median={verification_cycle_stats.get('median')}, "
                f"max={verification_cycle_stats.get('maximum')}, "
                f"std={verification_cycle_stats.get('standard_deviation')}, "
                f"range={verification_cycle_stats.get('range')}, "
                f"cv_percent={verification_cycle_stats.get('coefficient_of_variation_percent')}"
            )
        if verification_cpu_hz is None:
            print("Verification CPU Hz: unavailable")
        else:
            print(f"Verification CPU Hz: {verification_cpu_hz}")
        if verification_result_code is None:
            print("Verification result code: unavailable")
        else:
            print(f"Verification result code: {verification_result_code}")
        print(f"Verification timing source: {verification_time_source}")
        if args.negative_corrupt_application:
            print("Negative test passes only when the normal application and secure-boot markers are absent after flashing the corrupted result-local image.")
        else:
            print("Positive secure-boot evidence requires the distinct secure-boot UART marker, normal boot marker, tick marker, and explicit verification timing evidence for benchmark-valid samples.")
    print(f"Return code: {final_return_code}")

    return final_return_code


def _append_option(command: list[str], option: str, value: Any) -> None:
    if value is not None:
        command.extend([option, str(value)])


def _mqtt_broker_script_path(repo_root: Path) -> Path:
    return repo_root / MQTT_BROKER_SCRIPT_RELATIVE_PATH


def _mqtt_broker_base_command(args: argparse.Namespace, subcommand: str) -> list[str]:
    repo_root = Path.cwd()
    command = [sys.executable, str(_mqtt_broker_script_path(repo_root)), subcommand]
    _append_option(command, "--host-config", args.host_config)

    remote_subcommands = {
        "provision-oqs-certs",
        "deploy",
        "start",
        "stop",
        "status",
        "logs",
        "validate-oqs-tls",
        "validate-classical-mqtt",
        "validate-oqs-mqtt",
    }
    port_subcommands = {
        "start",
        "stop",
        "status",
        "logs",
        "validate-oqs-tls",
        "validate-classical-mqtt",
        "validate-oqs-mqtt",
    }

    if subcommand in remote_subcommands:
        _append_option(command, "--remote-dir", args.remote_dir)
        _append_option(command, "--project-name", args.project_name)
    if subcommand in port_subcommands:
        _append_option(command, "--classical-port", args.classical_port)
        _append_option(command, "--oqs-port", args.oqs_port)
    if args.dry_run:
        command.append("--dry-run")
    return command


def _write_mqtt_manifest(result_dir: Path, manifest: dict[str, Any]) -> None:
    (result_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _timeout_output_text(exc: subprocess.TimeoutExpired) -> str:
    """Return captured timeout output as text for result logs."""

    parts: list[str] = []
    for value in (exc.output, exc.stderr):
        if value is None:
            continue
        if isinstance(value, bytes):
            parts.append(value.decode(errors="replace"))
        else:
            parts.append(str(value))
    return "".join(parts)


def _run_logged_mqtt_step(
    *,
    step_name: str,
    command: list[str],
    result_dir: Path,
    manifest: dict[str, Any],
    attempts: int = 1,
    retry_delay_seconds: float = 0.0,
    timeout_seconds: float | None = None,
) -> int:
    log_path = result_dir / f"{step_name}.log"
    attempts = max(1, attempts)
    outputs: list[str] = []
    final_return_code = 1
    timed_out = False

    step_record: dict[str, Any] = {
        "name": step_name,
        "command": command,
        "return_code": None,
        "log": str(log_path),
        "status": "running",
    }
    if timeout_seconds is not None:
        step_record["timeout_seconds"] = timeout_seconds
    if attempts > 1:
        step_record["max_attempts"] = attempts
        step_record["retry_delay_seconds"] = retry_delay_seconds
    manifest.setdefault("steps", []).append(step_record)
    _write_mqtt_manifest(result_dir, manifest)
    log_path.write_text(
        f"# step: {step_name}\n# command: {' '.join(command)}\n# status: running\n",
        encoding="utf-8",
    )

    for attempt_index in range(1, attempts + 1):
        print(f"MQTT broker step {step_name}: attempt {attempt_index} of {attempts}", flush=True)
        if attempts > 1:
            outputs.append(f"# attempt {attempt_index} of {attempts}\n")
        try:
            run_kwargs: dict[str, Any] = {
                "text": True,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "check": False,
            }
            if timeout_seconds is not None:
                run_kwargs["timeout"] = timeout_seconds
            completed = subprocess.run(command, **run_kwargs)
            final_return_code = completed.returncode
            outputs.append(f"# return_code={completed.returncode}\n")
            outputs.append(completed.stdout or "")
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            final_return_code = 124
            outputs.append(f"# timed out after {timeout_seconds} seconds\n")
            outputs.append(_timeout_output_text(exc))
            break

        if final_return_code == 0:
            break
        if attempt_index < attempts and retry_delay_seconds > 0:
            time.sleep(retry_delay_seconds)

    log_path.write_text(
        f"# step: {step_name}\n# command: {' '.join(command)}\n" + "".join(outputs),
        encoding="utf-8",
    )
    step_record["return_code"] = final_return_code
    step_record["status"] = "failed" if final_return_code != 0 else "passed"
    if attempts > 1:
        step_record["attempts"] = attempt_index
    if timed_out:
        step_record["timed_out"] = True
    _write_mqtt_manifest(result_dir, manifest)
    return final_return_code


def _mqtt_step_command(args: argparse.Namespace, subcommand: str) -> list[str]:
    command = _mqtt_broker_base_command(args, subcommand)
    if subcommand == "start":
        command.extend(["--profile", args.profile])
    elif subcommand == "logs":
        command.extend(["--profile", args.profile, "--tail", str(args.log_tail)])
    elif subcommand == "validate-classical-mqtt":
        _append_option(command, "--topic", args.topic)
        _append_option(command, "--message", args.message)
    elif subcommand == "validate-oqs-mqtt":
        _append_option(command, "--topic", args.topic)
        _append_option(command, "--message", args.message)
    return command


def _filesystem_safe_timestamp(timestamp: str) -> str:
    """Return a timestamp fragment that is safe for Windows and POSIX paths."""

    return timestamp.replace(":", "").replace("+", "_").replace("T", "_")


def run_mqtt_broker_experiment_command(args: argparse.Namespace) -> int:
    """Run a gateway MQTT broker experiment through the framework CLI."""

    if args.message is None:
        args.message = "pqc-classical-mqtt-e2e" if args.profile == "classical" else "pqc-oqs-mqtt-e2e"

    timestamp = format_manifest_timestamp()
    run_id = f"{_filesystem_safe_timestamp(timestamp)}_mqtt_{args.profile}_broker"
    result_dir = args.results_dir / run_id
    result_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "command": "mqtt-broker-experiment",
        "created_at": timestamp,
        "status": "running",
        "profile": args.profile,
        "broker": {
            "host_config": str(args.host_config),
            "remote_dir": args.remote_dir,
            "project_name": args.project_name,
            "classical_port": args.classical_port,
            "oqs_port": args.oqs_port,
        },
        "mqtt_test": {
            "topic": args.topic,
            "message": args.message,
            "enabled": not args.skip_validation,
            "validation_retries": args.validation_retries,
            "validation_retry_delay_seconds": args.validation_retry_delay_seconds,
            "step_timeout_seconds": args.step_timeout_seconds,
        },
        "steps": [],
    }
    _write_mqtt_manifest(result_dir, manifest)

    planned_steps: list[tuple[str, str]] = []
    if not args.no_provision_certs:
        if args.profile == "classical":
            planned_steps.append(("provision_classical_certs", "provision-certs"))
        else:
            planned_steps.append(("provision_oqs_certs", "provision-oqs-certs"))
    if not args.no_deploy:
        planned_steps.append(("deploy_broker", "deploy"))
    planned_steps.extend([
        ("start_broker", "start"),
        ("status_after_start", "status"),
    ])
    if not args.skip_validation:
        if args.profile == "classical":
            planned_steps.append(("validate_classical_mqtt", "validate-classical-mqtt"))
        else:
            planned_steps.extend([
                ("validate_oqs_tls", "validate-oqs-tls"),
                ("validate_oqs_mqtt", "validate-oqs-mqtt"),
            ])
    planned_steps.append(("collect_broker_logs", "logs"))

    final_return_code = 0
    broker_started = False
    logs_collected = False
    failed_step: str | None = None
    for step_name, subcommand in planned_steps:
        step_attempts = 1
        step_retry_delay_seconds = 0.0
        if subcommand.startswith("validate-") and not args.dry_run:
            step_attempts = args.validation_retries
            step_retry_delay_seconds = args.validation_retry_delay_seconds

        return_code = _run_logged_mqtt_step(
            step_name=step_name,
            command=_mqtt_step_command(args, subcommand),
            result_dir=result_dir,
            manifest=manifest,
            attempts=step_attempts,
            retry_delay_seconds=step_retry_delay_seconds,
            timeout_seconds=args.step_timeout_seconds,
        )
        if step_name == "start_broker" and return_code == 0:
            broker_started = True
        if step_name == "collect_broker_logs":
            logs_collected = True
        if return_code != 0:
            final_return_code = return_code
            failed_step = step_name
            manifest["status"] = "failed"
            manifest["failed_step"] = step_name
            break

    if broker_started and not logs_collected:
        _run_logged_mqtt_step(
            step_name="collect_broker_logs",
            command=_mqtt_step_command(args, "logs"),
            result_dir=result_dir,
            manifest=manifest,
            timeout_seconds=args.step_timeout_seconds,
        )

    if args.stop_after:
        stop_return_code = _run_logged_mqtt_step(
            step_name="stop_broker",
            command=_mqtt_step_command(args, "stop"),
            result_dir=result_dir,
            manifest=manifest,
            timeout_seconds=args.step_timeout_seconds,
        )
        manifest["stop_after"] = True
        if final_return_code == 0 and stop_return_code != 0:
            final_return_code = stop_return_code
            manifest["status"] = "failed"
            manifest["failed_step"] = "stop_broker"
    else:
        manifest["stop_after"] = False

    if final_return_code == 0:
        manifest["status"] = "passed"
    _write_mqtt_manifest(result_dir, manifest)

    print("MQTT broker experiment completed" if final_return_code == 0 else "MQTT broker experiment failed")
    print("--------------------------------" if final_return_code == 0 else "-----------------------------")
    print(f"Run ID: {run_id}")
    print(f"Result directory: {result_dir}")
    print(f"Profile: {args.profile}")
    print(f"Manifest: {result_dir / 'manifest.json'}")
    print(f"Return code: {final_return_code}")
    return final_return_code

def run_aggregate_benchmarks_command(args: argparse.Namespace) -> int:
    """Aggregate secure-boot benchmark manifests into JSON and CSV summaries."""

    try:
        manifest_paths = resolve_manifest_inputs(
            results_dir=args.results_dir,
            manifest_paths=args.manifest,
            run_dirs=args.run_dir,
        )
        summary = aggregate_benchmark_manifests(manifest_paths)
        output_files = write_benchmark_summary_outputs(summary, args.output_dir)
    except BenchmarkAggregationError as exc:
        print(f"Benchmark aggregation failed: {exc}", file=sys.stderr)
        return 2

    print("Benchmark aggregation completed")
    print("-------------------------------")
    print(f"Input manifests: {summary['input_manifest_count']}")
    print(f"Aggregated profiles: {summary['aggregated_profile_count']}")
    print(f"Skipped manifests: {summary['skipped_manifest_count']}")
    print(f"JSON summary: {output_files['json']}")
    print(f"CSV summary: {output_files['csv']}")

    if summary["aggregated_profile_count"] == 0:
        return 1
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


    wolfboot_build_parser = subparsers.add_parser(
        "build-wolfboot",
        help="Build wolfBoot from a configured build profile without signing, flashing, or UART access.",
    )
    wolfboot_build_parser.add_argument(
        "--profile",
        required=True,
        type=Path,
        help="Path to a wolfBoot build-profile YAML config under configs/builds/.",
    )
    wolfboot_build_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where wolfBoot build evidence folders are created.",
    )
    wolfboot_build_parser.set_defaults(func=run_wolfboot_build_command)

    sign_application_parser = subparsers.add_parser(
        "sign-application",
        help="Sign the relocated application image from a configured signing profile without flashing or UART access.",
    )
    sign_application_parser.add_argument(
        "--profile",
        required=True,
        type=Path,
        help="Path to an application-signing YAML config under configs/signing/.",
    )
    sign_application_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where signing evidence folders are created.",
    )
    sign_application_parser.set_defaults(func=run_sign_application_command)

    secure_boot_flash_parser = subparsers.add_parser(
        "flash-secure-boot",
        help="Flash wolfBoot and a signed application image, then capture UART evidence.",
    )
    secure_boot_flash_parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to a wolfBoot secure-boot experiment YAML config.",
    )
    secure_boot_flash_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where result run folders are created.",
    )
    secure_boot_flash_parser.add_argument(
        "--uart-duration-seconds",
        default=DEFAULT_CAPTURE_DURATION_SECONDS,
        type=int,
        help="Bounded post-flash UART capture duration in seconds.",
    )
    secure_boot_flash_parser.add_argument(
        "--skip-uart",
        action="store_true",
        help="Diagnostic escape hatch: flash both artifacts without post-flash UART capture.",
    )
    secure_boot_flash_parser.add_argument(
        "--negative-corrupt-application",
        action="store_true",
        help="Create and flash a result-local corrupted copy of the signed application image, then require UART evidence that normal application markers are absent.",
    )
    secure_boot_flash_parser.add_argument(
        "--repeat-count",
        default=1,
        type=int,
        help="Run repeated post-flash secure-boot verification samples for the same benchmark profile. Each sample captures explicit UART timing evidence after reset.",
    )
    secure_boot_flash_parser.set_defaults(func=run_secure_boot_flash_command)


    mqtt_parser = subparsers.add_parser(
        "mqtt-broker-experiment",
        help="Provision, deploy, start, validate, log, and optionally stop a gateway MQTT broker profile.",
    )
    mqtt_parser.add_argument("--profile", choices=("classical", "oqs"), required=True, help="Broker profile to orchestrate.")
    mqtt_parser.add_argument("--results-dir", default=Path("results"), type=Path, help="Directory where MQTT broker experiment result folders are created.")
    mqtt_parser.add_argument("--host-config", default=Path("configs/hosts/gateway.yaml"), type=Path, help="Repository-relative gateway host config path.")
    mqtt_parser.add_argument("--remote-dir", default="~/pqc-framework-02/experiment/mqtt-broker", help="Remote gateway broker compose directory.")
    mqtt_parser.add_argument("--project-name", default="pqc-framework-mqtt-broker", help="Docker Compose project name.")
    mqtt_parser.add_argument("--classical-port", type=int, default=None, help="Host TLS port for the classical profile.")
    mqtt_parser.add_argument("--oqs-port", type=int, default=None, help="Host TLS port for the OQS profile.")
    mqtt_parser.add_argument("--topic", default="pqc/test/e2e", help="MQTT validation topic.")
    mqtt_parser.add_argument("--message", default=None, help="MQTT validation message. Defaults to a profile-specific message.")
    mqtt_parser.add_argument("--log-tail", type=int, default=200, help="Number of broker log lines to collect.")
    mqtt_parser.add_argument("--no-provision-certs", action="store_true", help="Skip certificate provisioning.")
    mqtt_parser.add_argument("--no-deploy", action="store_true", help="Skip compose-project deployment.")
    mqtt_parser.add_argument("--skip-validation", action="store_true", help="Skip TLS/MQTT validation steps.")
    mqtt_parser.add_argument("--validation-retries", type=int, default=8, help="Maximum broker validation attempts after broker start.")
    mqtt_parser.add_argument("--validation-retry-delay-seconds", type=float, default=5.0, help="Delay between broker validation attempts after broker start.")
    mqtt_parser.add_argument("--step-timeout-seconds", type=float, default=300.0, help="Maximum wall-clock seconds for each broker orchestration subprocess before it is marked failed.")
    mqtt_parser.add_argument("--stop-after", action="store_true", help="Stop the broker after logs are collected, or after a failed earlier step.")
    mqtt_parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run through to broker control commands while still writing framework result evidence.")
    mqtt_parser.set_defaults(func=run_mqtt_broker_experiment_command)

    aggregate_parser = subparsers.add_parser(
        "aggregate-benchmarks",
        help="Aggregate secure-boot benchmark manifests into benchmark_summary.json and benchmark_summary.csv.",
    )
    aggregate_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory to scan for result run manifests when --manifest or --run-dir is not supplied.",
    )
    aggregate_parser.add_argument(
        "--output-dir",
        default=Path("results/benchmark-aggregation"),
        type=Path,
        help="Directory where benchmark_summary.json and benchmark_summary.csv are written.",
    )
    aggregate_parser.add_argument(
        "--manifest",
        action="append",
        default=None,
        type=Path,
        help="Explicit secure-boot run manifest to include. May be supplied more than once.",
    )
    aggregate_parser.add_argument(
        "--run-dir",
        action="append",
        default=None,
        type=Path,
        help="Explicit result run directory containing manifest.json. May be supplied more than once.",
    )
    aggregate_parser.set_defaults(func=run_aggregate_benchmarks_command)

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
