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
    python scripts/experiment.py sign-application --boot-algorithm ecdsa_p256
    python scripts/experiment.py sign-application --profile configs/algorithms/ed25519.yaml
    python scripts/experiment.py sign-application --profile configs/algorithms/rsa2048.yaml
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/secure_boot_uart.yaml
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/secure_boot_uart.yaml
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/secure_boot_uart.yaml
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/secure_boot_uart.yaml --repeat-count 5
    python scripts/experiment.py flash-secure-boot --experiment configs/experiments/secure_boot_uart.yaml --negative-corrupt-application
    python scripts/experiment.py mqtt-fake-transport --experiment configs/experiments/mqtt_tls_schema_fake.yaml
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
benchmark manifests and writes JSON/CSV summaries without touching hardware. The mqtt-fake-transport command records deterministic simulated fake/no-network MQTT control-flow evidence without broker, socket, TLS, gateway, UART, STM32 runtime, Wi-Fi, hardware, or network access.
"""

from __future__ import annotations

import argparse
import inspect
import ipaddress
import json
import shlex
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
    build_mqtt_fake_transport_manifest_evidence,
    create_result_folder,
    format_manifest_timestamp,
    read_manifest,
    update_manifest,
)
from framework.uart import (
    DEFAULT_CAPTURE_DURATION_SECONDS,
    DEFAULT_RESTART_COMMAND,
    CommandExecution,
    execute_uart_capture,
    execute_uart_monitor,
)
from framework.mqtt_fake_transport import (
    FAKE_MQTT_VALID_OUTCOMES,
    FakeMqttTransportConfigError,
    scenario_from_config,
    run_fake_mqtt_transport_scenario,
)
from framework.wolfboot_build import execute_wolfboot_build
from framework.progress import emit_progress
from framework.tls_algorithms import resolve_tls_algorithm_set
from framework.signing import execute_application_signing
from framework.secure_boot_flash import (
    SecureBootFlashProfileError,
    _classical_profile_metadata,
    execute_secure_boot_flash,
)
from framework.external_dependencies import (
    ExternalDependencyError,
    prepare_external_dependencies,
    resolve_signing_material,
)
from framework.benchmark_aggregation import (
    BenchmarkAggregationError,
    aggregate_benchmark_manifests,
    resolve_manifest_inputs,
    write_benchmark_summary_outputs,
)




MQTT_E2E_MARKER_PREFIX = "PQC_MQTT_E2E"
MQTT_UART_CAPTURE_MARKER_PREFIX = "PQC_UART_CAPTURE"
MQTT_COMPLETION_MARKER = "PQC_EXPERIMENT_COMPLETE experiment=mqtt_tls_server_auth status=done"
MQTT_E2E_FAILURE_RETURN_CODE = 12
MQTT_BROKER_LIFECYCLE_FAILURE_RETURN_CODE = 13
MQTT_STEP_PROGRESS_MESSAGES = {'provision_classical_certs': 'Provisioning classical broker certificates', 'provision_oqs_certs': 'Provisioning OQS broker certificates', 'deploy_broker': 'Deploying broker framework', 'start_broker': 'Starting broker', 'status_after_start': 'Checking broker readiness and status', 'validate_classical_mqtt': 'Publishing and subscribing with classical MQTT/TLS validation', 'validate_oqs_tls': 'Validating OQS TLS connectivity', 'validate_oqs_mqtt': 'Publishing and subscribing with OQS MQTT/TLS validation', 'collect_broker_logs': 'Collecting broker logs', 'stop_broker': 'Stopping broker'}


def _warning_count_from_build_result(build_result: Any) -> int | None:
    """Return the compiler warning count when captured build output is available."""
    build_execution = getattr(build_result, "build", None)
    if build_execution is None:
        return 0 if getattr(build_result, "build_skipped", False) else None
    text = "\n".join((str(getattr(build_execution, "stdout", "")), str(getattr(build_execution, "stderr", ""))))
    return sum(1 for line in text.splitlines() if "warning:" in line.lower())


def _build_decision_detail(build_result: Any) -> str:
    if getattr(build_result, "build_skipped", False):
        reason = getattr(build_result, "build_skip_reason", None) or "matching reusable build is valid"
        return f"Build skipped: {reason}."
    reason = getattr(build_result, "build_skip_reason", None)
    return f"Build executed: {reason}." if reason else "Build executed because no reusable result was selected."


def _crypto_progress_lines(bundle: dict[str, dict[str, Any]]) -> list[str]:
    """Describe configured crypto choices without inferring runtime success."""
    lines: list[str] = []
    experiment = bundle.get("experiment", {})
    mqtt = experiment.get("mqtt", {}) if isinstance(experiment, dict) else {}
    if isinstance(mqtt, dict):
        tls = mqtt.get("tls", {})
        mode = str(tls.get("mode", "plaintext")) if isinstance(tls, dict) else "plaintext"
        try:
            selected = resolve_tls_algorithm_set(bundle)
            groups = ", ".join(selected.get("key_exchange_groups", [])) or "none"
            signatures = ", ".join(selected.get("signature_schemes", [])) or "none"
            lines.append(f"MQTT TLS mode={mode}; key exchange={groups}; signatures={signatures}")
        except ValueError as exc:
            lines.append(f"MQTT TLS mode={mode}; algorithm resolution failed: {exc}")
    boot_crypto = experiment.get("boot_crypto") if isinstance(experiment, dict) else None
    if boot_crypto:
        lines.append(f"Secure boot signature={boot_crypto}")
    return lines


def _report_experiment_start(bundle: dict[str, dict[str, Any]], run_id: str) -> None:
    experiment = bundle["experiment"]
    emit_progress("experiment", f"Starting {experiment['id']}", detail=f"Run ID: {run_id}")
    for line in _crypto_progress_lines(bundle):
        emit_progress("crypto", line)




def _build_progress(stage: str, message: str, detail: str | None) -> None:
    emit_progress(stage, message, detail=detail)


def _report_run_result(*, passed_label: str, final_return_code: int, failure_stage: str, run_id: str, result_dir: Path, build_log: Path | None = None, copied_artifact: Path | None = None, flash_log: Path | None = None, uart_log: Path | None = None) -> None:
    message = passed_label if final_return_code == 0 else f"Run failed during {failure_stage}"
    emit_progress("result", message, detail=f"Return code: {final_return_code}.")
    emit_progress("result", "Result evidence recorded", detail=f"Run ID: {run_id}; directory: {result_dir}")
    if build_log is not None:
        emit_progress("result", "Build evidence", detail=f"Log: {build_log}")
    if copied_artifact is not None:
        emit_progress("result", "Firmware artifact copied", detail=str(copied_artifact))
    if flash_log is not None:
        emit_progress("result", "Flash evidence", detail=f"Log: {flash_log}")
    if uart_log is not None:
        emit_progress("result", "UART evidence", detail=f"Log: {uart_log}")

def _mqtt_certificate_profile(bundle: dict[str, dict[str, Any]]) -> str:
    """Return the configured deployed MQTT certificate profile identifier."""

    tls = bundle["experiment"]["mqtt"].get("tls", {})
    certificate_profile = str(tls.get("certificate_profile", "")).strip()
    if not certificate_profile:
        raise ConfigError("TLS experiments must declare mqtt.tls.certificate_profile")
    return certificate_profile


def _mqtt_remote_certificate_dir(bundle: dict[str, dict[str, Any]]) -> str:
    """Return the repository-level certificate profile path on the gateway."""

    return (
        "$HOME/pqc-framework-02/secrets/mqtt/"
        f"{_mqtt_certificate_profile(bundle)}"
    )


def _mqtt_remote_ca_file(bundle: dict[str, dict[str, Any]]) -> str:
    """Return the deployed CA path used by gateway-side MQTT clients."""

    return f"{_mqtt_remote_certificate_dir(bundle)}/ca.crt"


def _mqtt_mutual_tls_enabled(bundle: dict[str, dict[str, Any]]) -> bool:
    """Return whether host-side MQTT clients must present a client identity."""

    tls = bundle["experiment"]["mqtt"].get("tls", {})
    return str(tls.get("authentication", "server")).strip().lower() == "mutual"


def _mqtt_remote_client_certificate_file(bundle: dict[str, dict[str, Any]]) -> str:
    """Return the deployed client certificate used by mTLS orchestration."""

    return f"{_mqtt_remote_certificate_dir(bundle)}/client.crt"


def _mqtt_remote_client_private_key_file(bundle: dict[str, dict[str, Any]]) -> str:
    """Return the deployed client private key used by mTLS orchestration."""

    return f"{_mqtt_remote_certificate_dir(bundle)}/client.key"


def _mqtt_gateway_tls_args(
    bundle: dict[str, dict[str, Any]],
    *,
    container_paths: bool,
) -> str:
    """Return TLS arguments for gateway-side MQTT clients."""

    if container_paths:
        args = "--cafile /certs/ca.crt --tls-version tlsv1.3"
        if _mqtt_mutual_tls_enabled(bundle):
            args += " --cert /certs/client.crt --key /certs/client.key"
        return args

    args = f"--cafile {_mqtt_remote_ca_file(bundle)} --tls-version tlsv1.3"
    if _mqtt_mutual_tls_enabled(bundle):
        args += (
            f" --cert {_mqtt_remote_client_certificate_file(bundle)}"
            f" --key {_mqtt_remote_client_private_key_file(bundle)}"
        )
    return args

def _mqtt_orchestration_host(bundle: dict[str, dict[str, Any]]) -> str:
    """Return the host used by gateway-side broker control clients.

    Firmware uses mqtt.broker.host so DNS and TLS identity evidence reflect the
    experiment endpoint. Gateway-side readiness and command/response clients may
    use mqtt.orchestration.host to avoid coupling host orchestration to the
    firmware DNS path or certificate identity.
    """
    mqtt = bundle["experiment"]["mqtt"]
    broker = mqtt["broker"]
    orchestration = mqtt.get("orchestration", {})
    if isinstance(orchestration, dict):
        configured = str(orchestration.get("host", "")).strip()
        if configured:
            return configured
    return str(broker["host"])


def _mqtt_gateway_client_host(
    bundle: dict[str, dict[str, Any]],
    *,
    tls_enabled: bool,
) -> str:
    """Return the endpoint used by gateway-side MQTT clients.

    TLS clients must connect using mqtt.broker.host so certificate hostname
    verification authenticates the configured broker identity. Plaintext
    clients may use mqtt.orchestration.host as a transport-only override.
    """
    mqtt = bundle["experiment"]["mqtt"]
    if tls_enabled:
        return str(mqtt["broker"]["host"])
    return _mqtt_orchestration_host(bundle)


def _is_st67_mqtt_e2e(bundle: dict[str, dict[str, Any]]) -> bool:
    mqtt = bundle.get("experiment", {}).get("mqtt", {})
    return isinstance(mqtt, dict) and mqtt.get("evidence_class") in {"stm32_st67_plaintext_e2e", "stm32_st67_classical_tls_e2e", "stm32_st67_pqc_hybrid_tls_e2e"}




def _run_mqtt_broker_step(*, repo_root: Path, result_dir: Path, step_name: str, subcommand: str, extra_args: list[str] | None = None) -> CommandExecution:
    command = [sys.executable, str(repo_root / MQTT_BROKER_SCRIPT_RELATIVE_PATH), subcommand]
    if extra_args:
        command.extend(extra_args)
    start = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=repo_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    execution = CommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=time.perf_counter() - start,
    )
    log_path = result_dir / f"mqtt-broker-{step_name}.log"
    log_path.write_text(
        "Command: " + shlex.join(command) + "\n"
        + f"Return code: {execution.return_code}\n"
        + f"Duration seconds: {execution.duration_seconds:.3f}\n\nstdout:\n"
        + execution.stdout
        + "\n\nstderr:\n"
        + execution.stderr,
        encoding="utf-8",
    )
    return execution


def _wait_for_plaintext_mqtt_broker(
    *,
    bundle: dict[str, dict[str, Any]],
    result_dir: Path,
    retries: int = 15,
    delay_seconds: int = 1,
) -> CommandExecution:
    """Wait for the managed MQTT broker using the profile-appropriate client."""

    mqtt = bundle["experiment"]["mqtt"]
    broker = mqtt["broker"]
    gateway_alias = str(bundle["host"]["alias"])
    port = int(broker["port"])
    evidence_class = mqtt.get("evidence_class")
    tls_enabled = evidence_class in {
        "stm32_st67_classical_tls_e2e",
        "stm32_st67_pqc_hybrid_tls_e2e",
    }
    pqc_hybrid = evidence_class == "stm32_st67_pqc_hybrid_tls_e2e"
    host = shlex.quote(
        _mqtt_gateway_client_host(bundle, tls_enabled=tls_enabled)
    )

    topic = "pqc/framework/readiness"
    message = "ready"

    if pqc_hybrid:
        certificate_dir = _mqtt_remote_certificate_dir(bundle)
        oqs_config = (
            "$HOME/pqc-framework-02/experiment/mqtt-broker/"
            "config/oqs/openssl.cnf"
        )
        container_options = (
            "--network host "
            "-e OPENSSL_CONF=/mosquitto/config/openssl.cnf "
            "-e OPENSSL_MODULES=/opt/oqssa/lib64/ossl-modules "
            f"-v {oqs_config}:/mosquitto/config/openssl.cnf:ro "
            f"-v {certificate_dir}:/certs:ro "
        )
        tls_args = _mqtt_gateway_tls_args(bundle, container_paths=True)
        subscriber_name = "pqc-mqtt-readiness-sub"
        script = (
            f'attempt=0; subscriber={subscriber_name}; '
            'cleanup() { docker rm -f "$subscriber" >/dev/null 2>&1 || true; }; '
            'trap cleanup EXIT; '
            f'while [ "$attempt" -lt {retries} ]; do '
            'attempt=$((attempt + 1)); cleanup; '
            f'docker run -d {container_options}'
            '--name "$subscriber" --entrypoint mosquitto_sub '
            'openquantumsafe/mosquitto:latest '
            f'-h {host} -p {port} {tls_args} -t {topic} -C 1 >/dev/null; sub_start_rc=$?; '
            'if [ "$sub_start_rc" -ne 0 ]; then '
            'echo "subscriber_start_failed attempt=$attempt rc=$sub_start_rc"; '
            f'sleep {delay_seconds}; continue; fi; '
            'sleep 2; '
            'subscriber_state=$(docker inspect -f "{{.State.Status}}" "$subscriber" 2>/dev/null || true); '
            'if [ "$subscriber_state" != running ]; then '
            'echo "subscriber_not_running attempt=$attempt state=$subscriber_state"; '
            'docker logs "$subscriber" 2>&1 || true; '
            f'sleep {delay_seconds}; continue; fi; '
            f'docker run --rm {container_options}'
            '--entrypoint mosquitto_pub openquantumsafe/mosquitto:latest '
            f'-h {host} -p {port} {tls_args} -t {topic} -m {message} >/tmp/pqc-mqtt-ready-pub.$$ 2>&1; pub_rc=$?; '
            'found=0; poll=0; while [ "$poll" -lt 10 ]; do '
            'poll=$((poll + 1)); response=$(docker logs "$subscriber" 2>&1 || true); '
            f'if printf "%s\n" "$response" | grep -Fx -- {message} >/dev/null; then found=1; break; fi; '
            'subscriber_state=$(docker inspect -f "{{.State.Status}}" "$subscriber" 2>/dev/null || true); '
            'if [ "$subscriber_state" != running ]; then break; fi; sleep 1; done; '
            'if [ "$found" -eq 1 ] && [ "$pub_rc" -eq 0 ]; then '
            'echo "broker_ready attempt=$attempt"; exit 0; fi; '
            'echo "subscriber_output:"; printf "%s\n" "$response"; '
            'echo "publisher_output:"; cat /tmp/pqc-mqtt-ready-pub.$$ 2>/dev/null || true; '
            f'sleep {delay_seconds}; done; '
            'echo "broker_not_ready attempts=$attempt"; exit 1'
        )
    else:
        mqtt_sub = "mosquitto_sub"
        mqtt_pub = "mosquitto_pub"
        tls_args = (
            _mqtt_gateway_tls_args(bundle, container_paths=False)
            if tls_enabled
            else ""
        )
        script = (
            f'attempt=0; while [ "$attempt" -lt {retries} ]; do '
            'attempt=$((attempt + 1)); '
            'response_file=/tmp/pqc-mqtt-ready.$$; '
            'publisher_file=/tmp/pqc-mqtt-ready-pub.$$; '
            f'{mqtt_pub} -h {host} -p {port} {tls_args} -t {topic} -n -r >/dev/null 2>&1 || true; ' + 'rm -f "$response_file" "$publisher_file"; '
            f'{mqtt_sub} -h {host} -p {port} {tls_args} '
            f'-t {topic} -C 1 -W 4 >"$response_file" 2>&1 & sub_pid=$!; '
            'sleep 0.1; '
            f'{mqtt_pub} -h {host} -p {port} {tls_args} '
            f'-t {topic} -m {message} -r >"$publisher_file" 2>&1; pub_rc=$?; '
            'wait "$sub_pid"; sub_rc=$?; '
            'response=$(paste -sd, "$response_file"); '
        'echo "PQC_MQTT_SUBSCRIBER_OUTPUT_BEGIN" 1>&2; cat "$response_file" 1>&2; echo "PQC_MQTT_SUBSCRIBER_OUTPUT_END" 1>&2; '
            f'if [ "$sub_rc" -eq 0 ] && [ "$pub_rc" -eq 0 ] '
            f'&& [ "$response" = {message} ]; then '
            f'{mqtt_pub} -h {host} -p {port} {tls_args} -t {topic} -n -r >/dev/null 2>&1 || true; ' + 'rm -f "$response_file" "$publisher_file"; '
            'echo "broker_ready attempt=$attempt"; exit 0; fi; '
            f'sleep {delay_seconds}; done; '
            'echo "subscriber_output:"; '
            'cat /tmp/pqc-mqtt-ready.$$ 2>/dev/null || true; '
            'echo "publisher_output:"; '
            'cat /tmp/pqc-mqtt-ready-pub.$$ 2>/dev/null || true; '
            'echo "broker_not_ready attempts=$attempt"; exit 1'
        )
    command = ["ssh", gateway_alias, f"sh -c {shlex.quote(script)}"]
    start = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=result_dir.parent.parent,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    execution = CommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=time.perf_counter() - start,
    )
    (result_dir / "mqtt-broker-readiness.log").write_text(
        "Command: " + shlex.join(command) + "\n"
        + f"Return code: {execution.return_code}\n"
        + f"Duration seconds: {execution.duration_seconds:.3f}\n\nstdout:\n"
        + execution.stdout
        + "\n\nstderr:\n"
        + execution.stderr,
        encoding="utf-8",
    )
    return execution

def _start_managed_mqtt_broker(*, bundle: dict[str, dict[str, Any]], repo_root: Path, result_dir: Path) -> tuple[bool, str]:
    steps: dict[str, Any] = {}
    mqtt = bundle.get("experiment", {}).get("mqtt", {})
    profile = str(mqtt.get("broker_profile", "classical")) if isinstance(mqtt, dict) else "classical"
    tls = mqtt.get("tls", {}) if isinstance(mqtt, dict) else {}
    certificate_profile = str(tls.get("certificate_profile", "")).strip() if isinstance(tls, dict) else ""
    common = ["--host-config", "configs/hosts/gateway.yaml"]
    if certificate_profile:
        common.extend(["--certificate-profile", certificate_profile])
    broker_messages = {
        "stop-existing": "Stopping any existing managed broker",
        "deploy": "Deploying MQTT broker framework",
        "start": "Starting MQTT broker",
        "status": "Checking MQTT broker status",
    }
    for step_name, subcommand, extra in (
        ("stop-existing", "stop", common),
        ("deploy", "deploy", common),
        ("start", "start", [*common, "--profile", profile]),
        ("status", "status", common),
    ):
        emit_progress("broker", broker_messages[step_name], detail=f"Profile: {profile}.")
        result = _run_mqtt_broker_step(repo_root=repo_root, result_dir=result_dir, step_name=step_name, subcommand=subcommand, extra_args=extra)
        steps[step_name] = {"return_code": result.return_code, "log": f"mqtt-broker-{step_name}.log"}
        if result.return_code == 0:
            emit_progress("broker", f"{broker_messages[step_name]} complete", detail=f"Return code: 0; log: mqtt-broker-{step_name}.log")
        if result.return_code != 0:
            emit_progress("broker", f"{broker_messages[step_name]} failed", detail=f"Return code: {result.return_code}; log: mqtt-broker-{step_name}.log")
            update_manifest(result_dir / "manifest.json", {"mqtt_broker": {"managed_by_experiment": True, "profile": profile, "steps": steps, "readiness_passed": False, "failure_stage": f"broker_{step_name}"}})
            return False, f"broker_{step_name}"
    emit_progress("broker", "Waiting for MQTT broker readiness", detail="Gateway-side publish/subscribe readiness probe.")
    readiness = _wait_for_plaintext_mqtt_broker(bundle=bundle, result_dir=result_dir)
    emit_progress("broker", "MQTT broker readiness probe complete" if readiness.return_code == 0 else "MQTT broker readiness probe failed", detail=f"Return code: {readiness.return_code}; log: mqtt-broker-readiness.log")
    steps["readiness"] = {"return_code": readiness.return_code, "log": "mqtt-broker-readiness.log"}
    update_manifest(result_dir / "manifest.json", {"mqtt_broker": {"managed_by_experiment": True, "profile": profile, "steps": steps, "readiness_passed": readiness.return_code == 0, "failure_stage": "none" if readiness.return_code == 0 else "broker_readiness"}})
    return readiness.return_code == 0, ("none" if readiness.return_code == 0 else "broker_readiness")


def _collect_and_stop_managed_mqtt_broker(
    *,
    bundle: dict[str, dict[str, Any]],
    repo_root: Path,
    result_dir: Path,
) -> tuple[int, int]:
    mqtt = bundle.get("experiment", {}).get("mqtt", {})
    profile = str(mqtt.get("broker_profile", "classical")) if isinstance(mqtt, dict) else "classical"
    common = ["--host-config", "configs/hosts/gateway.yaml"]
    emit_progress("broker", "Collecting MQTT broker logs", detail=f"Profile: {profile}.")
    logs_result = _run_mqtt_broker_step(
        repo_root=repo_root, result_dir=result_dir, step_name="log", subcommand="logs",
        extra_args=[*common, "--profile", profile, "--tail", "100000"],
    )
    emit_progress("broker", "Stopping MQTT broker", detail=f"Profile: {profile}.")
    stop_result = _run_mqtt_broker_step(
        repo_root=repo_root, result_dir=result_dir, step_name="stop", subcommand="stop", extra_args=common,
    )
    emit_progress("broker", "MQTT broker log collection complete" if logs_result.return_code == 0 else "MQTT broker log collection failed", detail=f"Return code: {logs_result.return_code}; log: mqtt-broker-log.log")
    emit_progress("broker", "MQTT broker stopped" if stop_result.return_code == 0 else "MQTT broker stop failed", detail=f"Return code: {stop_result.return_code}; log: mqtt-broker-stop.log")
    update_manifest(result_dir / "manifest.json", {"mqtt_broker": {"log": "mqtt-broker-log.log", "log_return_code": logs_result.return_code, "stop_log": "mqtt-broker-stop.log", "stop_return_code": stop_result.return_code, "cleanup_completed": stop_result.return_code == 0}})
    return logs_result.return_code, stop_result.return_code


def _parse_mqtt_e2e_marker(stderr: str) -> dict[str, Any]:
    marker_line = ""
    marker_prefix = MQTT_E2E_MARKER_PREFIX + " "
    for line in stderr.splitlines():
        marker_index = line.find(marker_prefix)
        if marker_index >= 0:
            marker_line = line[marker_index:].strip()
            break
    values: dict[str, Any] = {"marker_present": bool(marker_line)}
    if not marker_line:
        return values
    for token in marker_line.split()[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key] = value
    for key in ("subscriber_rc", "publish_attempts", "response_count", "expected_response_count"):
        if key in values:
            try:
                values[key] = int(values[key])
            except ValueError:
                pass
    return values



def _extract_marked_text(text: str, begin_marker: str, end_marker: str) -> str:
    """Return text captured between exact marker lines."""

    collecting = False
    lines: list[str] = []
    for line in text.splitlines():
        if line.strip() == begin_marker:
            collecting = True
            continue
        if collecting and line.strip() == end_marker:
            break
        if collecting:
            lines.append(line)
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def _parse_mqtt_broker_message_evidence(
    log_text: str,
    *,
    stm32_client_id: str,
    publisher_client_id: str,
    subscriber_client_id: str,
    command_topic: str,
    response_topic: str,
) -> dict[str, Any]:
    """Parse independent Mosquitto packet-routing evidence for one E2E run."""

    lines = log_text.splitlines()

    def has_line(*fragments: str) -> bool:
        return any(all(fragment in line for fragment in fragments) for line in lines)

    checks = {
        "stm32_connected": has_line("New client connected", f" as {stm32_client_id} "),
        "stm32_subscribe_received": has_line(f"Received SUBSCRIBE from {stm32_client_id}"),
        "stm32_suback_sent": has_line(f"Sending SUBACK to {stm32_client_id}"),
        "command_publish_received": has_line(f"Received PUBLISH from {publisher_client_id}", command_topic),
        "command_publish_delivered": has_line(f"Sending PUBLISH to {stm32_client_id}", command_topic),
        "response_publish_received": has_line(f"Received PUBLISH from {stm32_client_id}", response_topic),
        "response_publish_delivered": has_line(f"Sending PUBLISH to {subscriber_client_id}", response_topic),
    }
    return {**checks, "passed": all(checks.values())}

def _parse_mqtt_uart_capture_marker(stderr: str) -> dict[str, Any]:
    for line in stderr.splitlines():
        if not line.startswith(MQTT_UART_CAPTURE_MARKER_PREFIX + " "):
            continue
        values: dict[str, Any] = {"marker_present": True}
        for token in line.split()[1:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            if key in {"boot_marker_present", "completion_marker_present", "grace_seconds", "hard_limit_seconds", "raw_capture_rc"}:
                try:
                    values[key] = int(value)
                    continue
                except ValueError:
                    pass
            values[key] = value
        return values
    return {"marker_present": False}


def _mqtt_e2e_required_uart_markers(bundle: dict[str, dict[str, Any]]) -> tuple[str, ...]:
    mqtt = bundle.get("experiment", {}).get("mqtt", {})
    markers = [
        "ST67 DHCP: result=passed", "mqtt_connect=passed",
        "mqtt_subscribe=passed", "mqtt_receive=passed",
        "mqtt_publish=passed", "end_to_end=passed", MQTT_COMPLETION_MARKER,
    ]
    if isinstance(mqtt, dict):
        broker = mqtt.get("broker", {})
        if isinstance(broker, dict) and bool(broker.get("dns_required", False)):
            markers.extend(("ST67 DNS: required=true", "ST67 DNS lookup: result=passed"))
        if mqtt.get("evidence_class") in {"stm32_st67_classical_tls_e2e", "stm32_st67_pqc_hybrid_tls_e2e"}:
            markers.extend(("tls_handshake=passed", "reconnect=passed",
                            "reconnect_tls_handshake=passed", "reconnect_publish=passed"))
        if mqtt.get("evidence_class") == "stm32_st67_pqc_hybrid_tls_e2e":
            markers.extend(("evidence=stm32-st67-pqc-hybrid-tls-e2e",
                            "pqc_group=passed", "reconnect_pqc_group=passed"))
    return tuple(markers)


def _execute_mqtt_e2e_uart_capture(*, bundle: dict[str, dict[str, Any]], repo_root: Path, result_dir: Path, duration_seconds: int, restart_command: str):
    broker_started, broker_failure_stage = _start_managed_mqtt_broker(bundle=bundle, repo_root=repo_root, result_dir=result_dir)
    if not broker_started:
        _collect_and_stop_managed_mqtt_broker(bundle=bundle, repo_root=repo_root, result_dir=result_dir)
        return None, MQTT_BROKER_LIFECYCLE_FAILURE_RETURN_CODE, broker_failure_stage

    experiment = bundle["experiment"]
    mqtt = experiment["mqtt"]
    broker = mqtt["broker"]
    topics = mqtt["topics"]
    orchestration = mqtt.get("orchestration", {})
    command_payload = str(mqtt.get("command_payload", "run"))
    expected_response = str(mqtt["correlation_payload"])
    reconnect_attempts = int(mqtt.get("reconnect_attempts", 0))
    expected_response_count = 2 if reconnect_attempts > 0 else 1
    publish_interval = int(orchestration.get("publish_interval_seconds", 1))
    hard_limit_seconds = int(orchestration.get("hard_limit_seconds", duration_seconds))
    max_attempts = int(orchestration.get("max_publish_attempts", max(1, hard_limit_seconds - 2)))
    completion_grace_seconds = int(orchestration.get("completion_grace_seconds", 3))
    boot_marker = str(experiment["uart"]["expected_boot_message"])

    gateway_alias = str(bundle["host"]["alias"])
    device = shlex.quote(str(bundle["host"]["uart"]["device"]))
    baud = int(bundle["host"]["uart"]["baud"])
    broker_port = int(broker["port"])
    evidence_class = mqtt.get("evidence_class")
    tls_enabled = evidence_class in {
        "stm32_st67_classical_tls_e2e",
        "stm32_st67_pqc_hybrid_tls_e2e",
    }
    pqc_hybrid = evidence_class == "stm32_st67_pqc_hybrid_tls_e2e"
    broker_host = shlex.quote(
        _mqtt_gateway_client_host(bundle, tls_enabled=tls_enabled)
    )

    oqs_subscriber_name = ""
    if pqc_hybrid:
        certificate_dir = _mqtt_remote_certificate_dir(bundle)
        oqs_config = (
            "$HOME/pqc-framework-02/experiment/mqtt-broker/"
            "config/oqs/openssl.cnf"
        )
        oqs_subscriber_name = "pqc-mqtt-e2e-sub-$$"
        common_container_options = (
            "--network host "
            "-e OPENSSL_CONF=/mosquitto/config/openssl.cnf "
            "-e OPENSSL_MODULES=/opt/oqssa/lib64/ossl-modules "
            f"-v {oqs_config}:/mosquitto/config/openssl.cnf:ro "
            f"-v {certificate_dir}:/certs:ro "
        )
        mqtt_sub = (
            f'docker run --rm --name "{oqs_subscriber_name}" '
            f"{common_container_options}"
            "--entrypoint mosquitto_sub openquantumsafe/mosquitto:latest"
        )
        mqtt_pub = (
            f"docker run --rm {common_container_options}"
            "--entrypoint mosquitto_pub openquantumsafe/mosquitto:latest"
        )
        tls_args = _mqtt_gateway_tls_args(bundle, container_paths=True)
    else:
        mqtt_sub = "mosquitto_sub"
        mqtt_pub = "mosquitto_pub"
        tls_args = (
            _mqtt_gateway_tls_args(bundle, container_paths=False)
            if tls_enabled
            else ""
        )

    client_host = broker_host
    client_port = broker_port
    command_topic = shlex.quote(str(topics["command"]))
    response_topic = shlex.quote(str(topics["response"]))
    command_value = shlex.quote(command_payload)
    stm32_client_id = str(mqtt["client_id"])
    publisher_client_id = "pqc-host-e2e-publisher"
    subscriber_client_id = "pqc-host-e2e-subscriber"
    response_file = "/tmp/pqc-mqtt-e2e-response.$$"
    uart_file = "/tmp/pqc-mqtt-e2e-uart.$$"

    script = (
        f"response_file={response_file}; uart_file={uart_file}; "
        'rm -f "$response_file" "$uart_file"; '
        f"stty -F {device} {baud} cs8 -cstopb -parenb raw -echo || exit $?; "
        f"timeout 0.2s cat {device} >/dev/null 2>&1 || true; "
        f'{mqtt_sub} -h {client_host} -p {client_port} {tls_args} -i {shlex.quote(subscriber_client_id)} -v -t {response_topic} -C {expected_response_count} -W {hard_limit_seconds} >"$response_file" & subscriber_pid=$!; '
        f'timeout {hard_limit_seconds}s cat {device} >"$uart_file" & capture_pid=$!; '
        f"{restart_command} 1>&2; reset_rc=$?; attempts=0; publish_failures=0; publish_rc=0; "
        f'boot_marker={shlex.quote(boot_marker)}; boot_seen=0; '
        f'completion_marker={shlex.quote(MQTT_COMPLETION_MARKER)}; completion_seen=0; '
        f'while kill -0 "$capture_pid" 2>/dev/null && [ "$attempts" -lt {max_attempts} ]; do '
        'if [ "$boot_seen" -eq 0 ] && grep -Fq "$boot_marker" "$uart_file"; then boot_seen=1; fi; '
        'if [ "$boot_seen" -eq 1 ] && [ "$attempts" -gt 0 ] && grep -Fq "$completion_marker" "$uart_file"; then completion_seen=1; break; fi; '
        f"sleep {publish_interval}; "
        'if [ "$boot_seen" -eq 0 ]; then continue; fi; '
        'attempts=$((attempts + 1)); '
        f"{mqtt_pub} -h {client_host} -p {client_port} {tls_args} -i {shlex.quote(publisher_client_id)} -t {command_topic} -m {command_value} >/tmp/pqc-mqtt-e2e-publisher.$$ 2>&1; publish_rc=$?; "
        'if [ "$publish_rc" -ne 0 ]; then publish_failures=$((publish_failures + 1)); fi; done; '
        f'if [ "$completion_seen" -eq 1 ]; then sleep {completion_grace_seconds}; kill "$capture_pid" 2>/dev/null || true; fi; '
        'if kill -0 "$subscriber_pid" 2>/dev/null; then kill "$subscriber_pid" 2>/dev/null || true; fi; '
        + (
            f'docker rm -f "{oqs_subscriber_name}" >/dev/null 2>&1 || true; '
            if pqc_hybrid
            else ''
        )
        + 'wait "$subscriber_pid"; subscriber_rc=$?; '
        'wait "$capture_pid"; capture_rc=$?; '
        'if [ "$boot_seen" -eq 1 ] && [ "$attempts" -gt 0 ] && [ "$completion_seen" -eq 0 ] && grep -Fq "$completion_marker" "$uart_file"; then completion_seen=1; fi; '
        'termination_reason=hard_timeout; [ "$completion_seen" -eq 1 ] && termination_reason=completion_marker; '
        'normalized_capture_rc=$capture_rc; [ "$completion_seen" -eq 1 ] && normalized_capture_rc=0; '
        'cat "$uart_file"; '
        f'expected={shlex.quote(expected_response)}; expected_line={shlex.quote(str(topics["response"]) + " " + expected_response)}; expected_count={expected_response_count}; '
        'response_count=$(grep -c . "$response_file" || true); ' 
        'matched_count=$(grep -Fxc "$expected_line" "$response_file" || true); ' 
        'matched=0; [ "$response_count" -eq "$expected_count" ] && [ "$matched_count" -eq "$expected_count" ] && matched=1; '
        'response=$(paste -sd, "$response_file"); '
        'echo "PQC_MQTT_SUBSCRIBER_OUTPUT_BEGIN" 1>&2; cat "$response_file" 1>&2; echo "PQC_MQTT_SUBSCRIBER_OUTPUT_END" 1>&2; '
        f'echo "{MQTT_E2E_MARKER_PREFIX} subscriber_rc=$subscriber_rc publish_attempts=$attempts publish_failures=$publish_failures last_publish_rc=$publish_rc response_count=$response_count expected_response_count=$expected_count response_matched=$matched response=$response" 1>&2; '
        'if [ "$publish_failures" -ne 0 ]; then echo "publisher_output:" 1>&2; cat /tmp/pqc-mqtt-e2e-publisher.$$ 1>&2 2>/dev/null || true; fi; '
        f'echo "{MQTT_UART_CAPTURE_MARKER_PREFIX} termination_reason=$termination_reason boot_marker_present=$boot_seen completion_marker_present=$completion_seen grace_seconds={completion_grace_seconds} hard_limit_seconds={hard_limit_seconds} raw_capture_rc=$capture_rc" 1>&2; '
        'rm -f "$response_file" "$uart_file" /tmp/pqc-mqtt-e2e-publisher.$$; '
        'if [ "$reset_rc" -ne 0 ]; then exit "$reset_rc"; fi; exit "$normalized_capture_rc"'
    )
    ssh_command = ["ssh", gateway_alias, f"sh -c {shlex.quote(script)}"]

    def runner(_ignored_command: list[str], cwd: Path) -> CommandExecution:
        start = time.perf_counter()
        completed = subprocess.run(ssh_command, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
        execution = CommandExecution(command=ssh_command, return_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr, duration_seconds=time.perf_counter() - start)
        (result_dir / "mqtt-publisher.log").write_text(f"Publisher client ID: {publisher_client_id}\nCommand topic: {topics['command']}\nCommand payload: {command_payload}\nPublish interval seconds: {publish_interval}\nMaximum attempts: {max_attempts}\nExpected response count: {expected_response_count}\n{completed.stderr}", encoding="utf-8")
        marker = _parse_mqtt_e2e_marker(completed.stderr)
        subscriber_output = _extract_marked_text(completed.stderr, "PQC_MQTT_SUBSCRIBER_OUTPUT_BEGIN", "PQC_MQTT_SUBSCRIBER_OUTPUT_END")
        (result_dir / "mqtt-subscriber-raw.log").write_text(subscriber_output, encoding="utf-8")
        (result_dir / "mqtt-subscriber.log").write_text(json.dumps({**marker, "subscriber_client_id": subscriber_client_id, "topic_qualified_output": "mqtt-subscriber-raw.log"}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return execution

    uart_result = None
    marker: dict[str, Any] = {"marker_present": False}
    capture_marker: dict[str, Any] = {"marker_present": False}
    missing_uart_markers = list(_mqtt_e2e_required_uart_markers(bundle))
    broker_response_passed = False
    passed = False
    failure_stage = "uart"
    broker_log_rc = 1
    broker_stop_rc = 1
    broker_message_evidence: dict[str, Any] = {"passed": False}
    try:
        emit_progress("mqtt", "Starting MQTT command/response validation", detail=f"Subscriber topic: {topics['response']}; publisher topic: {topics['command']}; expected responses: {expected_response_count}.")
        uart_result = execute_uart_capture(bundle=bundle, repo_root=repo_root, result_dir=result_dir, runner=runner, duration_seconds=hard_limit_seconds, restart_command=restart_command)
        marker = _parse_mqtt_e2e_marker(uart_result.capture.stderr)
        capture_marker = _parse_mqtt_uart_capture_marker(uart_result.capture.stderr)
        missing_uart_markers = [item for item in _mqtt_e2e_required_uart_markers(bundle) if item not in uart_result.capture.stdout]
        broker_response_passed = (
            marker.get("subscriber_rc") == 0
            and marker.get("response_matched") == "1"
            and marker.get("response_count") == expected_response_count
            and marker.get("expected_response_count") == expected_response_count
        )
        passed = uart_result.return_code == 0 and broker_response_passed and not missing_uart_markers
        emit_progress("mqtt", "MQTT command/response validation complete" if passed else "MQTT command/response validation incomplete", detail=f"Publish attempts: {marker.get('publish_attempts')}; responses: {marker.get('response_count')}/{expected_response_count}; missing UART markers: {len(missing_uart_markers)}.")
        failure_stage = "none"
        if uart_result.return_code != 0:
            failure_stage = "uart"
        elif not broker_response_passed:
            failure_stage = "broker_response"
        elif missing_uart_markers:
            failure_stage = "mqtt_uart_markers"
    finally:
        broker_log_rc, broker_stop_rc = _collect_and_stop_managed_mqtt_broker(bundle=bundle, repo_root=repo_root, result_dir=result_dir)
    broker_log_path = result_dir / "mqtt-broker-log.log"
    if broker_log_rc == 0 and broker_log_path.exists():
        broker_message_evidence = _parse_mqtt_broker_message_evidence(
            broker_log_path.read_text(encoding="utf-8", errors="replace"),
            stm32_client_id=stm32_client_id,
            publisher_client_id=publisher_client_id,
            subscriber_client_id=subscriber_client_id,
            command_topic=str(topics["command"]),
            response_topic=str(topics["response"]),
        )
        (result_dir / "mqtt-broker-message-evidence.json").write_text(
            json.dumps(broker_message_evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if passed and broker_log_rc != 0:
        passed = False
        failure_stage = "broker_log_collection"
    elif passed and not broker_message_evidence.get("passed", False):
        passed = False
        failure_stage = "broker_message_evidence"
    if passed and broker_stop_rc != 0:
        passed = False
        failure_stage = "broker_stop"
    update_manifest(result_dir / "manifest.json", {
        "mqtt_e2e": {
            "return_code": 0 if passed else MQTT_E2E_FAILURE_RETURN_CODE,
            "failure_stage": failure_stage,
            "command_topic": topics["command"],
            "response_topic": topics["response"],
            "command_payload": command_payload,
            "expected_response": expected_response,
            "stm32_client_id": stm32_client_id,
            "publisher_client_id": publisher_client_id,
            "subscriber_client_id": subscriber_client_id,
            "broker_response_passed": broker_response_passed,
            "publish_attempts": marker.get("publish_attempts"),
            "missing_uart_markers": missing_uart_markers,
            "publisher_log": "mqtt-publisher.log",
            "subscriber_log": "mqtt-subscriber.log",
            "subscriber_raw_log": "mqtt-subscriber-raw.log",
            "broker_message_evidence": broker_message_evidence,
            "broker_message_evidence_log": "mqtt-broker-message-evidence.json",
            "capture_termination_reason": capture_marker.get("termination_reason") if uart_result is not None else None,
            "completion_marker_present": capture_marker.get("completion_marker_present") if uart_result is not None else None,
            "completion_grace_seconds": completion_grace_seconds,
            "hard_limit_seconds": duration_seconds,
        }
    })
    return uart_result, (0 if passed else MQTT_E2E_FAILURE_RETURN_CODE), failure_stage


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


def _load_config_mapping(config_path: Path) -> dict[str, Any]:
    """Load one simple YAML mapping without resolving profile references."""

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


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge mappings without mutating either input."""

    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_config(existing, value)
        else:
            merged[key] = value
    return merged


def _repository_path_from_config(config_path: Path, configured_path: str) -> Path:
    """Resolve a repository-relative profile reference from any config location."""

    reference = Path(configured_path)
    if reference.is_absolute():
        return reference

    for parent in (config_path.parent, *config_path.parents):
        if parent.name == "configs":
            return parent.parent / reference

    return reference


def _resolve_composed_profile(config_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Compose a thin compatibility profile from target and algorithm sources."""

    profile_kind = config.get("profile_kind")
    if profile_kind is None:
        return config

    profile_sections = {
        "wolfboot_build": "build",
        "application_signing": "signing",
        "secure_boot_experiment": "experiment",
        "boot": "boot",
    }
    section = profile_sections.get(str(profile_kind))
    if section is None:
        raise ConfigError(
            f"{config_path}: unsupported profile_kind '{profile_kind}'"
        )

    target_ref = require_field(config, "target_profile", str(config_path))
    algorithm_ref = require_field(config, "algorithm_profile", str(config_path))
    target_path = _repository_path_from_config(config_path, str(target_ref))
    algorithm_path = _repository_path_from_config(config_path, str(algorithm_ref))
    target = _load_config_mapping(target_path)
    algorithm = _load_config_mapping(algorithm_path)

    target_profiles = target.get("profiles")
    algorithm_profiles = algorithm.get("profiles")
    if not isinstance(target_profiles, dict) or not isinstance(
        target_profiles.get(section), dict
    ):
        raise ConfigError(
            f"{target_path} missing profiles.{section} mapping"
        )
    if not isinstance(algorithm_profiles, dict) or not isinstance(
        algorithm_profiles.get(section), dict
    ):
        raise ConfigError(
            f"{algorithm_path} missing profiles.{section} mapping"
        )

    resolved = _merge_config(
        target_profiles[section], algorithm_profiles[section]
    )
    local_overrides = {
        key: value
        for key, value in config.items()
        if key not in {"profile_kind", "target_profile", "algorithm_profile"}
    }
    return _merge_config(resolved, local_overrides)




def load_secure_boot_profile_section(
    *, target_profile: Path | str, algorithm: str, section: str
) -> tuple[dict[str, Any], Path]:
    """Resolve one secure-boot section from the canonical target and algorithm profiles."""

    target_path = Path(target_profile)
    target = _load_config_mapping(target_path)
    repo_root = _repository_path_from_config(target_path, ".").resolve()
    algorithm_path = repo_root / "configs" / "algorithms" / f"{algorithm}.yaml"
    algorithm_config = _load_config_mapping(algorithm_path)
    if algorithm_config.get("target") != target.get("id"):
        raise ConfigError(
            f"{algorithm_path}: target must be {target.get('id')} for {target_path}"
        )
    target_profiles = target.get("profiles")
    algorithm_profiles = algorithm_config.get("profiles")
    if not isinstance(target_profiles, dict) or not isinstance(target_profiles.get(section), dict):
        raise ConfigError(f"{target_path} missing profiles.{section} mapping")
    if not isinstance(algorithm_profiles, dict) or not isinstance(algorithm_profiles.get(section), dict):
        raise ConfigError(f"{algorithm_path} missing profiles.{section} mapping")
    return _merge_config(target_profiles[section], algorithm_profiles[section]), repo_root


def load_config(path: Path | str) -> dict[str, Any]:
    """Load a simple YAML mapping and resolve thin composed profiles."""

    config_path = Path(path)
    return _resolve_composed_profile(
        config_path, _load_config_mapping(config_path)
    )


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
    "stm32_st67_plaintext_e2e",
    "stm32_st67_classical_tls_e2e",
    "stm32_st67_pqc_hybrid_tls_e2e",
}
MQTT_TLS_TRANSPORT_BACKENDS = {
    "fake_no_network",
    "host_socket",
    "stm32_build_only",
    "stm32_runtime",
    "st67w61m1",
    "st67w61m1_lwip_sockets",
    "st67w61m1_lwip_wolfssl",
}
MQTT_TLS_TRANSPORT_EVIDENCE_MAP = {
    "fake_no_network": {"fake_no_network"},
    "host_socket": {"host_side"},
    "stm32_build_only": {"stm32_build_only"},
    "stm32_runtime": {"stm32_runtime"},
    "st67w61m1": {"st67w61m1_backed"},
    "st67w61m1_lwip_sockets": {"stm32_st67_plaintext_e2e"},
    "st67w61m1_lwip_wolfssl": {"stm32_st67_classical_tls_e2e", "stm32_st67_pqc_hybrid_tls_e2e"},
}
MQTT_TLS_MODES = {
    "disabled",
    "classical_tls",
    "oqs_experimental_tls",
    "not_applicable",
    "unavailable",
    "plaintext",
    "classical_tls_server_auth",
    "classical_tls_mutual",
    "pqc_hybrid_tls_server_auth",
    "pqc_hybrid_tls_mutual",
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
MQTT_TLS_RUNTIME_EVIDENCE_CLASSES = {"stm32_runtime", "st67w61m1_backed", "stm32_st67_plaintext_e2e", "stm32_st67_classical_tls_e2e", "stm32_st67_pqc_hybrid_tls_e2e"}
MQTT_TLS_NETWORK_EVIDENCE_CLASSES = {"host_side", "stm32_runtime", "st67w61m1_backed", "stm32_st67_plaintext_e2e", "stm32_st67_classical_tls_e2e", "stm32_st67_pqc_hybrid_tls_e2e"}


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
    if certificate_refs:
        raise ConfigError(
            "mqtt.tls.certificate_refs is resolved by the experiment prerequisite phase and must not be declared in YAML"
        )
    authentication = str(tls_config.get("authentication", "server")).strip().lower()
    if authentication not in {"server", "mutual"}:
        raise ConfigError("mqtt.tls.authentication must be server or mutual")
    mode_mutual = tls_mode.endswith("_mutual")
    if mode_mutual != (authentication == "mutual"):
        raise ConfigError("mqtt.tls.mode and mqtt.tls.authentication must describe the same authentication mode")
    if tls_mode not in {"disabled", "plaintext", "not_applicable", "unavailable"}:
        certificate_profile = tls_config.get("certificate_profile")
        if not isinstance(certificate_profile, str) or not certificate_profile.strip():
            raise ConfigError("TLS experiments must declare mqtt.tls.certificate_profile")
        if "/" in certificate_profile or "\\" in certificate_profile or certificate_profile in {".", ".."}:
            raise ConfigError("mqtt.tls.certificate_profile must be an identifier, not a path")

    orchestration = mqtt_config.get("orchestration", {})
    if orchestration and not isinstance(orchestration, dict):
        raise ConfigError("experiment config mqtt.orchestration field must be a mapping")
    if isinstance(orchestration, dict) and "host" in orchestration:
        orchestration_host = orchestration.get("host")
        if not isinstance(orchestration_host, str) or not orchestration_host.strip():
            raise ConfigError("mqtt.orchestration.host must be a non-empty hostname or IP address")

    broker = mqtt_config.get("broker", {})
    if broker and not isinstance(broker, dict):
        raise ConfigError("experiment config mqtt.broker field must be a mapping")
    if evidence_class in {"host_side", "stm32_st67_plaintext_e2e", "stm32_st67_classical_tls_e2e", "stm32_st67_pqc_hybrid_tls_e2e"}:
        require_field(config, "mqtt.broker.host", "experiment config")
        require_field(config, "mqtt.broker.port", "experiment config")
        broker_host = str(broker.get("host", "")).strip()
        dns_required = broker.get("dns_required", False)
        if not isinstance(dns_required, bool):
            raise ConfigError("mqtt.broker.dns_required must be a boolean")
        try:
            ipaddress.ip_address(broker_host)
            broker_host_is_ip = True
        except ValueError:
            broker_host_is_ip = False
        if not broker_host_is_ip and not dns_required:
            raise ConfigError(
                "mqtt.broker.dns_required must be true when mqtt.broker.host is a hostname"
            )
    if evidence_class == "fake_no_network" and broker:
        raise ConfigError("fake_no_network MQTT configs must not configure a real broker endpoint")

    fake_transport = mqtt_config.get("fake_transport", {})
    if fake_transport and not isinstance(fake_transport, dict):
        raise ConfigError("experiment config mqtt.fake_transport field must be a mapping")
    if fake_transport and transport_backend != "fake_no_network":
        raise ConfigError("mqtt.fake_transport requires mqtt.transport_backend to be fake_no_network")
    if fake_transport:
        for outcome_field in (
            "connect_outcome",
            "publish_outcome",
            "disconnect_outcome",
            "reconnect_outcome",
        ):
            outcome_value = fake_transport.get(outcome_field)
            if outcome_value is not None and outcome_value not in FAKE_MQTT_VALID_OUTCOMES:
                raise ConfigError(
                    f"mqtt.fake_transport.{outcome_field} must be one of: "
                    + ", ".join(sorted(FAKE_MQTT_VALID_OUTCOMES))
                )
        reconnect_attempts = fake_transport.get("reconnect_attempts", 0)
        if not isinstance(reconnect_attempts, int) or reconnect_attempts < 0:
            raise ConfigError("mqtt.fake_transport.reconnect_attempts must be a non-negative integer")
        for text_field in ("scenario", "topic", "message"):
            text_value = fake_transport.get(text_field)
            if text_value is not None and not isinstance(text_value, str):
                raise ConfigError(f"mqtt.fake_transport.{text_field} must be a string")
        if fake_transport.get("scenario") == "":
            raise ConfigError("mqtt.fake_transport.scenario must be a non-empty string")
        if fake_transport.get("topic") == "":
            raise ConfigError("mqtt.fake_transport.topic must be a non-empty string")

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

    if "network" in config:
        ssid = str(require_field(config, "network.wifi.ssid", "experiment config"))
        psk = str(require_field(config, "network.wifi.psk", "experiment config"))
        ipv4_mode = str(require_field(config, "network.ipv4.mode", "experiment config"))
        if len(ssid.encode("utf-8")) > 32:
            raise ConfigError("network.wifi.ssid must be at most 32 bytes")
        if len(psk.encode("utf-8")) < 8 or len(psk.encode("utf-8")) > 63:
            raise ConfigError("network.wifi.psk must be between 8 and 63 bytes")
        if ipv4_mode != "dhcp":
            raise ConfigError("network.ipv4.mode must be dhcp")

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




SECURE_BOOT_BENCHMARK_MINIMUM_ALGORITHMS = {"ed25519", "ecdsa_p256", "rsa2048"}
SECURE_BOOT_BENCHMARK_EXPANDED_ALGORITHMS = {"ecc384", "ecc521", "ed448", "rsa3072", "rsa4096"}
SECURE_BOOT_BENCHMARK_POST_QUANTUM_ALGORITHMS = {"mldsa44", "mldsa65"}
SECURE_BOOT_BENCHMARK_SUPPORTED_ALGORITHMS = (
    SECURE_BOOT_BENCHMARK_MINIMUM_ALGORITHMS
    | SECURE_BOOT_BENCHMARK_EXPANDED_ALGORITHMS
    | SECURE_BOOT_BENCHMARK_POST_QUANTUM_ALGORITHMS
)


def _validate_algorithm_id_mapping(config: dict[str, Any], field: str, expected: set[str]) -> None:
    value = require_field(config, field, "secure-boot benchmark suite")
    if not isinstance(value, dict):
        raise ConfigError(f"secure-boot benchmark suite {field} must be a mapping of algorithm identifiers to true")
    if any(enabled is not True for enabled in value.values()):
        raise ConfigError(f"secure-boot benchmark suite {field} values must all be true")
    if set(value) != expected:
        expected_text = ", ".join(sorted(expected))
        raise ConfigError(f"secure-boot benchmark suite {field} must contain exactly: {expected_text}")


def validate_classical_benchmark_profile_model_config(config: dict[str, Any]) -> None:
    """Validate the consolidated secure-boot signing benchmark suite."""

    for field in (
        "id", "description", "schema_version", "benchmark_scope", "reference_algorithm",
        "minimum_algorithms", "expanded_algorithms", "post_quantum_algorithms",
        "common_evidence.board", "common_evidence.application_payload",
        "common_evidence.measurement_method", "common_evidence.repeated_run_model",
        "common_evidence.static_metrics_model", "common_evidence.runtime_memory_model",
    ):
        require_field(config, field, "secure-boot benchmark suite")

    if config.get("schema_version") != 2:
        raise ConfigError("secure-boot benchmark suite schema_version must be 2")
    if config.get("benchmark_scope") != "secure_boot_signing_algorithm":
        raise ConfigError("secure-boot benchmark suite benchmark_scope must be secure_boot_signing_algorithm")

    _validate_algorithm_id_mapping(config, "minimum_algorithms", SECURE_BOOT_BENCHMARK_MINIMUM_ALGORITHMS)
    _validate_algorithm_id_mapping(config, "expanded_algorithms", SECURE_BOOT_BENCHMARK_EXPANDED_ALGORITHMS)
    _validate_algorithm_id_mapping(config, "post_quantum_algorithms", SECURE_BOOT_BENCHMARK_POST_QUANTUM_ALGORITHMS)

    reference_algorithm = str(config.get("reference_algorithm"))
    if reference_algorithm not in SECURE_BOOT_BENCHMARK_SUPPORTED_ALGORITHMS:
        raise ConfigError("secure-boot benchmark suite reference_algorithm must name a supported algorithm")
    if reference_algorithm != "ecdsa_p256":
        raise ConfigError("secure-boot benchmark suite reference_algorithm must remain ecdsa_p256")

    unavailable = config.get("unavailable_algorithms", {})
    if not isinstance(unavailable, dict):
        raise ConfigError("secure-boot benchmark suite unavailable_algorithms must be a mapping")
    if set(unavailable) & SECURE_BOOT_BENCHMARK_SUPPORTED_ALGORITHMS:
        raise ConfigError("secure-boot benchmark suite unavailable algorithms must not also be runnable")
    for algorithm_id, metadata in unavailable.items():
        if not isinstance(algorithm_id, str) or not algorithm_id:
            raise ConfigError("secure-boot benchmark suite unavailable algorithm identifiers must be non-empty strings")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("reason"), str) or not metadata["reason"].strip():
            raise ConfigError(f"unavailable_algorithms.{algorithm_id}.reason must be a non-empty string")


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


def load_secure_boot_experiment_bundle(
    experiment_path: Path | str, *, algorithm: str, target_profile: Path | str = Path("configs/targets/stm32l4r5_wolfboot.yaml")
) -> dict[str, dict[str, Any]]:
    """Load a wolfBoot secure-boot flash experiment without enabling generic execution.

    Phase 10h uses the planned wolfBoot boot config explicitly for the
    two-artifact flash workflow. The generic experiment loader still rejects
    non-runnable boot configs so normal direct-flash commands cannot
    accidentally treat the wolfBoot profile as a validated boot path.
    """

    experiment_config_path = Path(experiment_path)
    local_experiment = _load_config_mapping(experiment_config_path)
    experiment_defaults, _ = load_secure_boot_profile_section(
        target_profile=target_profile, algorithm=algorithm, section="experiment"
    )
    boot_config, _ = load_secure_boot_profile_section(
        target_profile=target_profile, algorithm=algorithm, section="boot"
    )
    experiment_config = _merge_config(experiment_defaults, local_experiment)
    validate_experiment_config(experiment_config)

    configs_root = _configs_root_from_experiment_path(experiment_config_path)
    board_path = configs_root / "boards" / f"{require_field(experiment_config, 'board', 'experiment config')}.yaml"
    host_path = configs_root / "hosts" / f"{require_field(experiment_config, 'host', 'experiment config')}.yaml"
    board_config = load_config(board_path)
    host_config = load_config(host_path)

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


def _prepare_dependencies_for_result(*, bundle: dict[str, dict[str, Any]], repo_root: Path, result_dir: Path) -> dict[str, dict[str, Any]]:
    try:
        context = prepare_external_dependencies(bundle=bundle, repo_root=repo_root, result_dir=result_dir)
    except ExternalDependencyError as exc:
        update_manifest(result_dir / "manifest.json", {
            "status": "failed",
            "failure_stage": "external_dependencies",
            "external_dependencies": {"status": "failed", "reason": str(exc)},
        })
        raise
    public_context = context.public_manifest(repo_root)
    if public_context:
        update_manifest(result_dir / "manifest.json", {
            "external_dependencies": {"status": "prepared", **public_context},
        })
    return bundle


def run_build_command(args: argparse.Namespace) -> int:
    """Run the build command."""

    bundle = load_experiment_bundle(args.experiment)
    artifact_override = getattr(args, "artifact", None)
    if artifact_override is not None:
        bundle = {
            **bundle,
            "experiment": {
                **bundle["experiment"],
                "firmware": {
                    **bundle["experiment"]["firmware"],
                    "artifact": Path(artifact_override).as_posix(),
                },
            },
        }
    result_dir, manifest = create_result_folder(bundle, args.results_dir)
    _report_experiment_start(bundle, manifest["run_id"])
    repo_root = repo_root_from_experiment_path(args.experiment)
    emit_progress("prereq", "Preparing experiment prerequisites")
    try:
        bundle = _prepare_dependencies_for_result(bundle=bundle, repo_root=repo_root, result_dir=result_dir)
    except ExternalDependencyError as exc:
        print(f"Experiment prerequisite preparation failed: {exc}", file=sys.stderr)
        return MQTT_BROKER_LIFECYCLE_FAILURE_RETURN_CODE
    configure_preset = args.configure_preset or args.build_preset

    emit_progress("build", "Preparing application build")
    build_result = execute_build(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        configure_preset=configure_preset,
        build_preset=args.build_preset,
        force=getattr(args, "force", False),
        progress=_build_progress,
    )

    warning_count = _warning_count_from_build_result(build_result)
    warning_text = "warning count unavailable" if warning_count is None else f"{warning_count} compiler warnings"
    if getattr(build_result, "build_skipped", False):
        emit_progress("build", "Application build completed", detail=f"{warning_text}; no compilation performed.")
    else:
        outcome = "completed" if build_result.return_code == 0 else "failed"
        emit_progress("build", f"Application compilation {outcome}", detail=f"{warning_text}; return code: {build_result.return_code}.")
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
        progress=_build_progress,
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
    existing_firmware_sha256 = firmware.get("sha256")
    if (
        referenced_build_artifact_sha256 is not None
        and (
            not isinstance(existing_firmware_sha256, str)
            or not existing_firmware_sha256.strip()
        )
    ):
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
                "build_log": "build.log" if build_return_code is not None else None,
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

    if _is_st67_mqtt_e2e(bundle):
        uart_result, final_return_code, failure_stage = _execute_mqtt_e2e_uart_capture(
            bundle=bundle,
            repo_root=repo_root,
            result_dir=result_dir,
            duration_seconds=args.uart_duration_seconds,
            restart_command=_monitor_restart_command(bundle, None),
        )
    else:
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
        uart_return_code=None if uart_result is None else uart_result.return_code,
        copied_artifact_path=copied_artifact_path,
        duration_seconds=perf_counter() - start,
        referenced_build_number=build_number,
        referenced_build_artifact_sha256=verification.firmware_sha256,
        referenced_build_manifest=verification.manifest_path,
    )

    _report_run_result(
        passed_label="MQTT end-to-end run passed" if _is_st67_mqtt_e2e(bundle) else "Baseline run passed",
        final_return_code=final_return_code,
        failure_stage=failure_stage,
        run_id=manifest["run_id"],
        result_dir=result_dir,
        copied_artifact=copied_artifact_path,
        flash_log=flash_result.log_path,
        uart_log=None if uart_result is None else uart_result.log_path,
    )
    emit_progress("result", "Referenced reusable build", detail=f"Build number: {build_number}.")
    return final_return_code



def _compose_wolfboot_run_bundle(
    *,
    experiment_path: Path,
    boot_algorithm: str,
    target_profile: Path,
) -> dict[str, dict[str, Any]]:
    """Compose an existing experiment with canonical wolfBoot runtime settings."""

    direct_bundle = load_experiment_bundle(experiment_path)
    secure_bundle = load_secure_boot_experiment_bundle(
        Path("configs/experiments/secure_boot_uart.yaml"),
        algorithm=boot_algorithm,
        target_profile=target_profile,
    )

    original_experiment = direct_bundle["experiment"]
    secure_experiment = secure_bundle["experiment"]
    merged_uart = _merge_config(
        original_experiment.get("uart", {}),
        secure_experiment.get("uart", {}),
    )
    merged_experiment = {
        **original_experiment,
        "boot": secure_experiment["boot"],
        "boot_crypto": secure_experiment["boot_crypto"],
        "firmware": dict(secure_experiment["firmware"]),
        "secure_boot_benchmark_profile": dict(
            secure_experiment["secure_boot_benchmark_profile"]
        ),
        "secure_boot_flash": dict(secure_experiment["secure_boot_flash"]),
        "uart": merged_uart,
    }
    validate_experiment_config(merged_experiment)
    return {
        "experiment": merged_experiment,
        "board": direct_bundle["board"],
        "host": direct_bundle["host"],
        "boot": secure_bundle["boot"],
    }


def _wolfboot_application_build_bundle(
    *,
    bundle: dict[str, dict[str, Any]],
    signing_profile: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Return a build-stage bundle that validates the relocated ELF, not the future signed BIN."""

    input_elf = signing_profile.get("input_elf")
    if input_elf is not None and str(input_elf).strip():
        relocated_elf = Path(str(input_elf)).as_posix()
    else:
        input_image = Path(
            str(require_field(signing_profile, "input_image", "application signing profile"))
        )
        relocated_elf = input_image.with_suffix(".elf").as_posix()
    build_bundle = {
        **bundle,
        "experiment": {
            **bundle["experiment"],
            "firmware": {
                **bundle["experiment"]["firmware"],
                "artifact": relocated_elf,
            },
        },
    }
    return build_bundle


def _select_signed_firmware_artifact(
    *,
    bundle: dict[str, dict[str, Any]],
    signing_profile: dict[str, Any],
) -> None:
    """Select the signed application only after signing has completed."""

    bundle["experiment"]["firmware"]["artifact"] = str(
        require_field(signing_profile, "signed_image", "application signing profile")
    )


def _record_wolfboot_run_stage(
    *,
    result_dir: Path,
    stage: str,
    return_code: int,
    evidence_dir: Path | None = None,
    log_path: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    evidence: dict[str, Any] = {
        "return_code": return_code,
        "result_directory": None if evidence_dir is None else str(evidence_dir),
        "log": None if log_path is None else str(log_path),
    }
    if extra:
        evidence.update(extra)
    update_manifest(result_dir / "manifest.json", {stage: evidence})


def _run_full_wolfboot_command(args: argparse.Namespace) -> int:
    """Run an experiment end to end through wolfBoot without manual prerequisites."""

    from time import perf_counter

    if not args.boot_algorithm:
        print(
            "Error: --boot-algorithm is required when --boot-mode wolfboot.",
            file=sys.stderr,
        )
        return 2
    if getattr(args, "build_number", None) is not None:
        print(
            "Error: --build-number is not supported with --boot-mode wolfboot because the relocated application, bootloader, and signature must be prepared as one run.",
            file=sys.stderr,
        )
        return 2

    repo_root = repo_root_from_experiment_path(args.experiment)
    bundle = _compose_wolfboot_run_bundle(
        experiment_path=args.experiment,
        boot_algorithm=args.boot_algorithm,
        target_profile=args.target_profile,
    )
    result_dir, manifest = create_result_folder(bundle, args.results_dir)
    _report_experiment_start(bundle, manifest["run_id"])
    start = perf_counter()

    update_manifest(
        result_dir / "manifest.json",
        {
            "boot_selection": {
                "mode": "wolfboot",
                "algorithm": args.boot_algorithm,
                "target_profile": str(args.target_profile),
                "source_experiment": str(args.experiment),
            }
        },
    )

    emit_progress("prereq", "Preparing all experiment prerequisites")
    try:
        bundle = _prepare_dependencies_for_result(
            bundle=bundle,
            repo_root=repo_root,
            result_dir=result_dir,
        )
    except ExternalDependencyError as exc:
        print(f"Experiment prerequisite preparation failed: {exc}", file=sys.stderr)
        return MQTT_BROKER_LIFECYCLE_FAILURE_RETURN_CODE

    build_profile, _ = load_secure_boot_profile_section(
        target_profile=args.target_profile,
        algorithm=args.boot_algorithm,
        section="build",
    )
    validate_wolfboot_build_profile_config(build_profile)
    emit_progress("boot", "Building wolfBoot", detail=f"Algorithm: {args.boot_algorithm}.")
    wolfboot_result = execute_wolfboot_build(
        profile=build_profile,
        repo_root=repo_root,
        results_root=result_dir / "prerequisites",
    )
    _record_wolfboot_run_stage(
        result_dir=result_dir,
        stage="wolfboot_build",
        return_code=wolfboot_result.return_code,
        evidence_dir=wolfboot_result.result_dir,
        log_path=wolfboot_result.log_path,
        extra={
            "artifact": str(wolfboot_result.artifact_path),
            "artifact_sha256": wolfboot_result.artifact_sha256,
        },
    )
    if wolfboot_result.return_code != 0:
        _record_run_summary(
            result_dir=result_dir,
            final_return_code=wolfboot_result.return_code,
            failure_stage="wolfboot_build",
            build_return_code=None,
            artifact_copy_return_code=None,
            flash_return_code=None,
            uart_return_code=None,
            copied_artifact_path=None,
            duration_seconds=perf_counter() - start,
        )
        return wolfboot_result.return_code

    signing_profile, _ = load_secure_boot_profile_section(
        target_profile=args.target_profile,
        algorithm=args.boot_algorithm,
        section="signing",
    )
    validate_application_signing_profile_config(signing_profile)
    build_bundle = _wolfboot_application_build_bundle(
        bundle=bundle,
        signing_profile=signing_profile,
    )

    emit_progress("build", "Building relocated experiment firmware")
    build_result = execute_build(
        bundle=build_bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        configure_preset="RelocatedDebug",
        build_preset="RelocatedDebug",
        force=getattr(args, "force", False),
        progress=_build_progress,
    )
    if build_result.return_code != 0:
        _record_run_summary(
            result_dir=result_dir,
            final_return_code=build_result.return_code,
            failure_stage="application_build",
            build_return_code=build_result.return_code,
            artifact_copy_return_code=None,
            flash_return_code=None,
            uart_return_code=None,
            copied_artifact_path=None,
            duration_seconds=perf_counter() - start,
            referenced_build_number=getattr(build_result, "build_number", None),
            referenced_build_artifact_sha256=getattr(build_result, "firmware_sha256", None),
            referenced_build_manifest=getattr(build_result, "build_record_manifest_path", None),
        )
        return build_result.return_code

    try:
        signing_context = resolve_signing_material(
            profile=signing_profile,
            repo_root=repo_root,
        )
    except ExternalDependencyError as exc:
        print(f"Signing prerequisite preparation failed: {exc}", file=sys.stderr)
        return 14
    signing_profile = {
        **signing_profile,
        "private_key": signing_context.private_key.relative_to(repo_root).as_posix(),
        "resolved_signing_context": signing_context.public_manifest(repo_root),
    }
    emit_progress("sign", "Signing relocated experiment firmware")
    signing_result = execute_application_signing(
        profile=signing_profile,
        repo_root=repo_root,
        results_root=result_dir / "prerequisites",
    )
    _record_wolfboot_run_stage(
        result_dir=result_dir,
        stage="application_signing",
        return_code=signing_result.return_code,
        evidence_dir=signing_result.result_dir,
        log_path=signing_result.log_path,
        extra={
            "signed_image": str(signing_result.signed_image_path),
            "signed_image_sha256": signing_result.signed_image_sha256,
        },
    )
    if signing_result.return_code != 0:
        _record_run_summary(
            result_dir=result_dir,
            final_return_code=signing_result.return_code,
            failure_stage="application_signing",
            build_return_code=build_result.return_code,
            artifact_copy_return_code=None,
            flash_return_code=None,
            uart_return_code=None,
            copied_artifact_path=None,
            duration_seconds=perf_counter() - start,
            referenced_build_number=getattr(build_result, "build_number", None),
            referenced_build_artifact_sha256=getattr(build_result, "firmware_sha256", None),
            referenced_build_manifest=getattr(build_result, "build_record_manifest_path", None),
        )
        return signing_result.return_code

    _select_signed_firmware_artifact(
        bundle=bundle,
        signing_profile=signing_profile,
    )
    update_manifest(
        result_dir / "manifest.json",
        {
            "firmware": {
                "artifact": bundle["experiment"]["firmware"]["artifact"],
                "artifact_path": str(signing_result.signed_image_path),
                "artifact_exists": signing_result.signed_image_path.exists(),
                "sha256": signing_result.signed_image_sha256,
                "result_artifact": signing_result.retained_signed_image_path.name,
                "result_artifact_path": str(signing_result.retained_signed_image_path),
            }
        },
    )

    emit_progress("flash", "Flashing wolfBoot and signed experiment firmware")
    try:
        flash_result = execute_secure_boot_flash(
            bundle=bundle,
            repo_root=repo_root,
            result_dir=result_dir,
        )
    except SecureBootFlashProfileError as exc:
        print(f"Secure-boot flash profile failed: {exc}", file=sys.stderr)
        return 43
    if flash_result.return_code != 0:
        _record_run_summary(
            result_dir=result_dir,
            final_return_code=flash_result.return_code,
            failure_stage="secure_boot_flash",
            build_return_code=build_result.return_code,
            artifact_copy_return_code=0,
            flash_return_code=flash_result.return_code,
            uart_return_code=None,
            copied_artifact_path=signing_result.retained_signed_image_path,
            duration_seconds=perf_counter() - start,
            referenced_build_number=getattr(build_result, "build_number", None),
            referenced_build_artifact_sha256=getattr(build_result, "firmware_sha256", None),
            referenced_build_manifest=getattr(build_result, "build_record_manifest_path", None),
        )
        return flash_result.return_code

    emit_progress("uart", "Running experiment validation through wolfBoot")
    if _is_st67_mqtt_e2e(bundle):
        uart_result, final_return_code, failure_stage = _execute_mqtt_e2e_uart_capture(
            bundle=bundle,
            repo_root=repo_root,
            result_dir=result_dir,
            duration_seconds=args.uart_duration_seconds,
            restart_command=_monitor_restart_command(bundle, None),
        )
    else:
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
        artifact_copy_return_code=0,
        flash_return_code=flash_result.return_code,
        uart_return_code=None if uart_result is None else uart_result.return_code,
        copied_artifact_path=signing_result.retained_signed_image_path,
        duration_seconds=perf_counter() - start,
        referenced_build_number=getattr(build_result, "build_number", None),
        referenced_build_artifact_sha256=getattr(build_result, "firmware_sha256", None),
        referenced_build_manifest=getattr(build_result, "build_record_manifest_path", None),
    )
    _report_run_result(
        passed_label="MQTT secure-boot end-to-end run passed"
        if _is_st67_mqtt_e2e(bundle)
        else "Secure-boot run passed",
        final_return_code=final_return_code,
        failure_stage=failure_stage,
        run_id=manifest["run_id"],
        result_dir=result_dir,
        build_log=build_result.log_path,
        copied_artifact=signing_result.retained_signed_image_path,
        flash_log=flash_result.log_path,
        uart_log=None if uart_result is None else uart_result.log_path,
    )
    return final_return_code


def run_full_baseline_command(args: argparse.Namespace) -> int:
    """Run the selected experiment end to end through direct flash or wolfBoot."""

    from time import perf_counter

    if getattr(args, "boot_mode", "direct_flash") == "wolfboot":
        return _run_full_wolfboot_command(args)
    if getattr(args, "boot_algorithm", None):
        print(
            "Error: --boot-algorithm is only valid with --boot-mode wolfboot.",
            file=sys.stderr,
        )
        return 2

    bundle = load_experiment_bundle(args.experiment)
    result_dir, manifest = create_result_folder(bundle, args.results_dir)
    _report_experiment_start(bundle, manifest["run_id"])
    repo_root = repo_root_from_experiment_path(args.experiment)
    emit_progress("prereq", "Preparing experiment prerequisites")
    try:
        bundle = _prepare_dependencies_for_result(bundle=bundle, repo_root=repo_root, result_dir=result_dir)
    except ExternalDependencyError as exc:
        print(f"Experiment prerequisite preparation failed: {exc}", file=sys.stderr)
        return MQTT_BROKER_LIFECYCLE_FAILURE_RETURN_CODE
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

    emit_progress("build", "Preparing application build")
    build_result = execute_build(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        configure_preset=configure_preset,
        build_preset=args.build_preset,
        force=getattr(args, "force", False),
        progress=_build_progress,
    )

    warning_count = _warning_count_from_build_result(build_result)
    warning_text = "warning count unavailable" if warning_count is None else f"{warning_count} compiler warnings"
    if getattr(build_result, "build_skipped", False):
        emit_progress("build", "Application build completed", detail=f"{warning_text}; no compilation performed.")
    else:
        outcome = "completed" if build_result.return_code == 0 else "failed"
        emit_progress("build", f"Application compilation {outcome}", detail=f"{warning_text}; return code: {build_result.return_code}.")

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
            referenced_build_number=getattr(build_result, "build_number", None),
            referenced_build_artifact_sha256=getattr(build_result, "firmware_sha256", None),
            referenced_build_manifest=getattr(build_result, "build_record_manifest_path", None),
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
            referenced_build_number=getattr(build_result, "build_number", None),
            referenced_build_artifact_sha256=getattr(build_result, "firmware_sha256", None),
            referenced_build_manifest=getattr(build_result, "build_record_manifest_path", None),
        )
        print("Baseline run failed while copying artifact")
        print("------------------------------------------")
        print(f"Run ID: {manifest['run_id']}")
        print(f"Result directory: {result_dir}")
        print(f"Error: {exc}")
        print(f"Return code: {artifact_copy_return_code}")
        return artifact_copy_return_code

    emit_progress("gateway", "Using configured gateway for flash and UART stages", detail=f"Host alias: {bundle["host"]["alias"]}")
    emit_progress("flash", "Flashing application firmware")
    flash_result = execute_flash(
        bundle=bundle,
        repo_root=repo_root,
        result_dir=result_dir,
        source_build_run_id=manifest["run_id"],
        source_build_number=getattr(build_result, "build_number", None),
        source_build_manifest_path=getattr(build_result, "build_record_manifest_path", None),
        artifact_path_override=build_result.elf_path,
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
            referenced_build_number=getattr(build_result, "build_number", None),
            referenced_build_artifact_sha256=getattr(build_result, "firmware_sha256", None),
            referenced_build_manifest=getattr(build_result, "build_record_manifest_path", None),
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

    emit_progress("uart", "Starting bounded UART capture and marker evaluation")
    if _is_st67_mqtt_e2e(bundle):
        uart_result, final_return_code, failure_stage = _execute_mqtt_e2e_uart_capture(
            bundle=bundle,
            repo_root=repo_root,
            result_dir=result_dir,
            duration_seconds=args.uart_duration_seconds,
            restart_command=_monitor_restart_command(bundle, None),
        )
    else:
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
        uart_return_code=None if uart_result is None else uart_result.return_code,
        copied_artifact_path=copied_artifact_path,
        duration_seconds=perf_counter() - start,
        referenced_build_number=getattr(build_result, "build_number", None),
        referenced_build_artifact_sha256=getattr(build_result, "firmware_sha256", None),
        referenced_build_manifest=getattr(build_result, "build_record_manifest_path", None),
    )

    _report_run_result(
        passed_label="MQTT end-to-end run passed" if _is_st67_mqtt_e2e(bundle) else "Baseline run passed",
        final_return_code=final_return_code,
        failure_stage=failure_stage,
        run_id=manifest["run_id"],
        result_dir=result_dir,
        build_log=build_result.log_path,
        copied_artifact=copied_artifact_path,
        flash_log=flash_result.log_path,
        uart_log=None if uart_result is None else uart_result.log_path,
    )
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

    profile, repo_root = load_secure_boot_profile_section(
        target_profile=args.target_profile, algorithm=args.boot_algorithm, section="build"
    )
    validate_wolfboot_build_profile_config(profile)

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

    profile, repo_root = load_secure_boot_profile_section(
        target_profile=args.target_profile, algorithm=args.boot_algorithm, section="signing"
    )
    validate_application_signing_profile_config(profile)
    try:
        signing_context = resolve_signing_material(profile=profile, repo_root=repo_root)
    except ExternalDependencyError as exc:
        print(f"Signing prerequisite preparation failed: {exc}", file=sys.stderr)
        return 14
    profile = {
        **profile,
        "private_key": signing_context.private_key.relative_to(repo_root).as_posix(),
        "resolved_signing_context": signing_context.public_manifest(repo_root),
    }

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
        and uart_result.derived_verification_time_ms is not None
        and uart_result.verification_cycles is not None
    )
    return build_secure_boot_benchmark_sample(
        run_index=run_index,
        timestamp=format_manifest_timestamp(),
        derived_verification_time_ms=uart_result.derived_verification_time_ms,
        verification_cycles=uart_result.verification_cycles,
        bootloader_hclk_hz=uart_result.bootloader_hclk_hz,
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

    bundle = load_secure_boot_experiment_bundle(args.experiment, algorithm=args.boot_algorithm, target_profile=args.target_profile)
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
    derived_verification_time_ms = None if uart_result is None else uart_result.derived_verification_time_ms
    verification_cycles = None if uart_result is None else uart_result.verification_cycles
    bootloader_hclk_hz = None if uart_result is None else uart_result.bootloader_hclk_hz
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
                "derived_verification_time_ms": derived_verification_time_ms,
                "verification_cycles": verification_cycles,
                "bootloader_hclk_hz": bootloader_hclk_hz,
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
        derived_verification_time_ms=derived_verification_time_ms,
        verification_cycles=verification_cycles,
        bootloader_hclk_hz=bootloader_hclk_hz,
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
                "primary_derived_verification_time_ms": headline_metrics.get("primary_derived_verification_time_ms"),
                "primary_verification_cycles": headline_metrics.get("primary_verification_cycles"),
                "primary_statistic": headline_metrics.get("primary_statistic") if headline_metrics else None,
                "derived_verification_time_ms": derived_verification_time_ms,
                "verification_cycles": verification_cycles,
                "bootloader_hclk_hz": bootloader_hclk_hz,
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
                "derived_verification_time_ms": derived_verification_time_ms,
                "verification_cycles": verification_cycles,
                "bootloader_hclk_hz": bootloader_hclk_hz,
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
        if headline_metrics.get("primary_derived_verification_time_ms") is not None:
            print(f"Primary verification time (median): {headline_metrics['primary_derived_verification_time_ms']} ms")
        elif derived_verification_time_ms is None:
            print("Verification time: unavailable")
        else:
            print(f"Verification time: {derived_verification_time_ms} ms")
        if headline_metrics.get("primary_verification_cycles") is not None:
            print(f"Primary verification cycles (median): {headline_metrics['primary_verification_cycles']}")
        elif verification_cycles is None:
            print("Verification cycles: unavailable")
        else:
            print(f"Verification cycles: {verification_cycles}")
        verification_time_stats = aggregate_statistics.get("derived_verification_time_ms", {}) if isinstance(aggregate_statistics, dict) else {}
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
        if bootloader_hclk_hz is None:
            print("Verification CPU Hz: unavailable")
        else:
            print(f"Verification CPU Hz: {bootloader_hclk_hz}")
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

    emit_progress("broker", MQTT_STEP_PROGRESS_MESSAGES.get(step_name, step_name.replace("_", " ").capitalize()))
    for attempt_index in range(1, attempts + 1):
        emit_progress("broker", f"{step_name}: attempt {attempt_index} of {attempts}")
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
    outcome = "completed" if final_return_code == 0 else f"failed with return code {final_return_code}"
    emit_progress("broker", f"{step_name} {outcome}", detail=f"Log: {log_path}")
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
    emit_progress("experiment", f"Starting MQTT broker experiment ({args.profile})", detail=f"Run ID: {run_id}")
    emit_progress("crypto", "Classical TLS profile" if args.profile == "classical" else "OQS/PQC TLS profile")
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
        "evidence": {
            "evidence_class": "host_side",
            "evidence_label": "host-side/broker-side MQTT/TLS compatibility evidence",
            "evidence_sources": [
                "host-side MQTT/TLS client validation output",
                "broker-side Docker Compose status and broker logs",
            ],
            "evidence_boundaries": {
                "claims_host_side_broker_compatibility": not args.skip_validation,
                "claims_broker_side_container_status": True,
                "claims_stm32_success": False,
                "claims_wifi_module_success": False,
                "claims_lwip_on_stm32_success": False,
                "claims_wolfssl_on_stm32_success": False,
                "claims_wolfmqtt_on_stm32_success": False,
                "claims_end_to_end_wireless_success": False,
            },
            "limitations": [
                "Phase M4 broker validation is host-side and broker-side evidence only.",
                "It does not exercise STM32 firmware, the ST67W61M1 Wi-Fi module, lwIP on STM32, wolfSSL on STM32, wolfMQTT on STM32, or end-to-end wireless operation.",
            ],
        },
        "steps": [],
    }
    _write_mqtt_manifest(result_dir, manifest)

    planned_steps: list[tuple[str, str]] = []
    if not args.no_provision_certs:
        provision_step_name = (
            "provision_classical_certs"
            if args.profile == "classical"
            else "provision_oqs_certs"
        )
        planned_steps.append((provision_step_name, "provision-certs"))
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
    print("Evidence label: host-side/broker-side MQTT/TLS compatibility evidence")
    print("Evidence boundary: host-side client and broker-side Docker validation only; no STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless success is claimed")
    print(f"Manifest: {result_dir / 'manifest.json'}")
    print(f"Return code: {final_return_code}")
    return final_return_code


def _mqtt_fake_transport_config_from_args(
    *,
    mqtt_config: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Merge fake-transport config defaults with CLI overrides."""

    config = dict(mqtt_config.get("fake_transport", {}) or {})
    for attr, key in (
        ("scenario", "scenario"),
        ("connect_outcome", "connect_outcome"),
        ("publish_outcome", "publish_outcome"),
        ("disconnect_outcome", "disconnect_outcome"),
        ("reconnect_outcome", "reconnect_outcome"),
        ("reconnect_attempts", "reconnect_attempts"),
        ("topic", "topic"),
        ("message", "message"),
    ):
        value = getattr(args, attr, None)
        if value is not None:
            config[key] = value
    return config


def run_mqtt_fake_transport_command(args: argparse.Namespace) -> int:
    """Run deterministic fake/no-network MQTT transport control-flow evidence."""

    bundle = load_experiment_bundle(args.experiment)
    experiment = bundle["experiment"]
    mqtt_config = experiment.get("mqtt", {})
    if not isinstance(mqtt_config, dict):
        print("MQTT fake transport requires an experiment mqtt mapping.", file=sys.stderr)
        return 2
    if mqtt_config.get("evidence_class") != "fake_no_network" or mqtt_config.get("transport_backend") != "fake_no_network":
        print(
            "MQTT fake transport requires mqtt.evidence_class and mqtt.transport_backend to be fake_no_network.",
            file=sys.stderr,
        )
        return 2

    try:
        scenario_config = _mqtt_fake_transport_config_from_args(
            mqtt_config=mqtt_config,
            args=args,
        )
        scenario = scenario_from_config(scenario_config)
        fake_result = run_fake_mqtt_transport_scenario(scenario)
    except (FakeMqttTransportConfigError, ValueError) as exc:
        print(f"MQTT fake transport configuration failed: {exc}", file=sys.stderr)
        return 2

    result_dir, manifest = create_result_folder(bundle, args.results_dir)
    manifest_path = result_dir / "manifest.json"
    mqtt_tls = dict(manifest.get("mqtt_tls", {}))
    mqtt_tls["fake_transport"] = build_mqtt_fake_transport_manifest_evidence(fake_result)
    mqtt_tls["limitations"] = list(mqtt_tls.get("limitations", [])) + [
        "Phase M3 fake/no-network MQTT transport harness evidence is simulated control-flow evidence only; no broker, gateway, socket, TLS handshake, UART, STM32 runtime, Wi-Fi, or hardware access was performed."
    ]

    update_manifest(
        manifest_path,
        {
            "result": "fake_mqtt_transport_completed",
            "mqtt_tls": mqtt_tls,
        },
    )

    print("MQTT fake/no-network transport completed")
    print("----------------------------------------")
    print(f"Run ID: {manifest['run_id']}")
    print(f"Result directory: {result_dir}")
    print(f"Scenario: {fake_result['scenario_id']}")
    print(f"Evidence label: {fake_result['evidence_label']}")
    print(f"Events: {fake_result['summary']['event_count']}")
    print(f"Timeout operations: {', '.join(fake_result['summary']['timeout_operations']) or 'none'}")
    print(f"Failed operations: {', '.join(fake_result['summary']['failed_operations']) or 'none'}")
    print("No broker, socket, TLS, gateway, UART, STM32 runtime, Wi-Fi, hardware, or network access was performed.")
    return 0


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
        "--artifact",
        default=None,
        type=Path,
        help=(
            "Repository-relative expected ELF path for this build. "
            "Defaults to the experiment firmware artifact and is intended for "
            "provenance-recorded alternate presets such as RelocatedDebug."
        ),
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
    run_parser.add_argument(
        "--boot-mode",
        choices=("direct_flash", "wolfboot"),
        default="direct_flash",
        help="Firmware boot path. wolfboot performs prerequisite provisioning, relocated build, bootloader build, signing, two-artifact flash, and normal experiment validation.",
    )
    run_parser.add_argument(
        "--boot-algorithm",
        dest="boot_algorithm",
        default=None,
        help="Secure-boot signing algorithm ID from configs/algorithms/. Required when --boot-mode wolfboot.",
    )
    run_parser.add_argument(
        "--target-profile",
        default=Path("configs/targets/stm32l4r5_wolfboot.yaml"),
        type=Path,
        help="Canonical secure-boot target profile used when --boot-mode wolfboot.",
    )
    run_parser.set_defaults(func=run_full_baseline_command)


    wolfboot_build_parser = subparsers.add_parser(
        "build-wolfboot",
        help="Build wolfBoot from a configured build profile without signing, flashing, or UART access.",
    )
    wolfboot_build_parser.add_argument("--boot-algorithm", dest="boot_algorithm", required=True, help="Secure-boot signing algorithm ID from configs/algorithms/.")
    wolfboot_build_parser.add_argument(
        "--target-profile", default=Path("configs/targets/stm32l4r5_wolfboot.yaml"), type=Path,
        help="Canonical secure-boot target profile.",
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
    sign_application_parser.add_argument("--boot-algorithm", dest="boot_algorithm", required=True, help="Secure-boot signing algorithm ID from configs/algorithms/.")
    sign_application_parser.add_argument(
        "--target-profile", default=Path("configs/targets/stm32l4r5_wolfboot.yaml"), type=Path,
        help="Canonical secure-boot target profile.",
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
    secure_boot_flash_parser.add_argument("--boot-algorithm", dest="boot_algorithm", required=True, help="Secure-boot signing algorithm ID from configs/algorithms/.")
    secure_boot_flash_parser.add_argument(
        "--target-profile", default=Path("configs/targets/stm32l4r5_wolfboot.yaml"), type=Path,
        help="Canonical secure-boot target profile.",
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


    mqtt_fake_parser = subparsers.add_parser(
        "mqtt-fake-transport",
        help="Run deterministic fake/no-network MQTT client control-flow evidence without sockets or hardware.",
    )
    mqtt_fake_parser.add_argument(
        "--experiment",
        required=True,
        type=Path,
        help="Path to a fake/no-network MQTT experiment YAML config.",
    )
    mqtt_fake_parser.add_argument(
        "--results-dir",
        default=Path("results"),
        type=Path,
        help="Directory where result run folders are created.",
    )
    mqtt_fake_parser.add_argument("--scenario", default=None, help="Scenario identifier recorded in fake evidence.")
    mqtt_fake_parser.add_argument("--connect-outcome", choices=sorted(FAKE_MQTT_VALID_OUTCOMES), default=None, help="Simulated connect outcome.")
    mqtt_fake_parser.add_argument("--publish-outcome", choices=sorted(FAKE_MQTT_VALID_OUTCOMES), default=None, help="Simulated publish outcome.")
    mqtt_fake_parser.add_argument("--disconnect-outcome", choices=sorted(FAKE_MQTT_VALID_OUTCOMES), default=None, help="Simulated disconnect outcome.")
    mqtt_fake_parser.add_argument("--reconnect-outcome", choices=sorted(FAKE_MQTT_VALID_OUTCOMES), default=None, help="Simulated reconnect outcome.")
    mqtt_fake_parser.add_argument("--reconnect-attempts", type=int, default=None, help="Number of simulated reconnect attempts.")
    mqtt_fake_parser.add_argument("--topic", default=None, help="Simulated MQTT topic recorded in fake evidence.")
    mqtt_fake_parser.add_argument("--message", default=None, help="Simulated MQTT payload used only for message-size evidence.")
    mqtt_fake_parser.set_defaults(func=run_mqtt_fake_transport_command)


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
