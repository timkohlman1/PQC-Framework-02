from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_experiment_module():
    module_path = REPO_ROOT / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mqtt_broker_experiment_parser_defaults_to_framework_orchestration_command():
    experiment_cli = load_experiment_module()
    parser = experiment_cli.build_arg_parser()

    args = parser.parse_args(["mqtt-broker-experiment", "--profile", "classical"])

    assert args.command == "mqtt-broker-experiment"
    assert args.profile == "classical"
    assert args.host_config == Path("configs/hosts/gateway.yaml")
    assert args.remote_dir == "~/pqc-framework-02/experiment/mqtt-broker"
    assert args.project_name == "pqc-framework-mqtt-broker"
    assert args.topic == "pqc/test/e2e"
    assert args.stop_after is False
    assert args.validation_retries == 8
    assert args.validation_retry_delay_seconds == 5.0
    assert args.step_timeout_seconds == 300.0
    assert callable(args.func)


def test_mqtt_broker_experiment_run_id_is_windows_safe(tmp_path, monkeypatch):
    experiment_cli = load_experiment_module()

    def fake_run(command, *, text, stdin, stdout, stderr, check, timeout=None):
        return SimpleNamespace(returncode=0, stdout="step output\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(experiment_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(experiment_cli, "format_manifest_timestamp", lambda: "2026-07-04T22:28:10+10:00")

    args = experiment_cli.build_arg_parser().parse_args([
        "mqtt-broker-experiment",
        "--profile",
        "classical",
        "--results-dir",
        str(tmp_path / "results"),
        "--dry-run",
    ])

    result = experiment_cli.run_mqtt_broker_experiment_command(args)

    assert result == 0
    manifest_path = tmp_path / "results" / "2026-07-04_222810_1000_mqtt_classical_broker" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "2026-07-04_222810_1000_mqtt_classical_broker"
    assert manifest["created_at"] == "2026-07-04T22:28:10+10:00"


def test_mqtt_broker_experiment_orchestrates_oqs_profile_and_writes_manifest(tmp_path, monkeypatch):
    experiment_cli = load_experiment_module()
    commands: list[list[str]] = []

    def fake_run(command, *, text, stdin, stdout, stderr, check, timeout=None):
        commands.append(command)
        assert stdin == experiment_cli.subprocess.DEVNULL
        return SimpleNamespace(returncode=0, stdout=f"ran {' '.join(command)}\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(experiment_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(experiment_cli, "format_manifest_timestamp", lambda: "2026-07-04_001")

    args = experiment_cli.build_arg_parser().parse_args([
        "mqtt-broker-experiment",
        "--profile",
        "oqs",
        "--results-dir",
        str(tmp_path / "results"),
        "--host-config",
        "configs/hosts/gateway.yaml",
        "--remote-dir",
        "~/pqc-framework-02/tmp/mqtt-test",
        "--project-name",
        "pytest-mqtt",
        "--oqs-port",
        "38884",
        "--topic",
        "pqc/test/e2e",
        "--stop-after",
    ])

    result = experiment_cli.run_mqtt_broker_experiment_command(args)

    assert result == 0
    subcommands = [command[2] for command in commands]
    assert subcommands == [
        "provision-certs",
        "deploy",
        "start",
        "status",
        "validate-oqs-tls",
        "validate-oqs-mqtt",
        "logs",
        "stop",
    ]
    command_text = "\n".join(" ".join(command) for command in commands)
    assert "--profile oqs" in command_text
    assert "--oqs-port 38884" in command_text
    assert "--project-name pytest-mqtt" in command_text
    assert "--message pqc-oqs-mqtt-e2e" in command_text

    manifest_path = tmp_path / "results" / "2026-07-04_001_mqtt_oqs_broker" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"] == "mqtt-broker-experiment"
    assert manifest["profile"] == "oqs"
    assert manifest["status"] == "passed"
    assert manifest["stop_after"] is True
    assert manifest["mqtt_test"]["step_timeout_seconds"] == 300.0
    assert len(manifest["steps"]) == 8
    assert all(step["status"] == "passed" for step in manifest["steps"])


def test_mqtt_broker_experiment_stops_after_failed_validation_when_requested(tmp_path, monkeypatch):
    experiment_cli = load_experiment_module()
    commands: list[list[str]] = []
    sleeps: list[float] = []

    def fake_run(command, *, text, stdin, stdout, stderr, check, timeout=None):
        commands.append(command)
        assert stdin == experiment_cli.subprocess.DEVNULL
        return_code = 7 if command[2] == "validate-classical-mqtt" else 0
        return SimpleNamespace(returncode=return_code, stdout="step output\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(experiment_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(experiment_cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(experiment_cli, "format_manifest_timestamp", lambda: "2026-07-04_002")

    args = experiment_cli.build_arg_parser().parse_args([
        "mqtt-broker-experiment",
        "--profile",
        "classical",
        "--results-dir",
        str(tmp_path / "results"),
        "--validation-retries",
        "3",
        "--validation-retry-delay-seconds",
        "0.25",
        "--stop-after",
    ])

    result = experiment_cli.run_mqtt_broker_experiment_command(args)

    assert result == 7
    assert sleeps == [0.25, 0.25]
    subcommands = [command[2] for command in commands]
    assert subcommands == [
        "provision-certs",
        "deploy",
        "start",
        "status",
        "validate-classical-mqtt",
        "validate-classical-mqtt",
        "validate-classical-mqtt",
        "logs",
        "stop",
    ]
    manifest_path = tmp_path / "results" / "2026-07-04_002_mqtt_classical_broker" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["failed_step"] == "validate_classical_mqtt"
    failed_step = next(step for step in manifest["steps"] if step["name"] == "validate_classical_mqtt")
    assert failed_step["return_code"] == 7
    assert failed_step["attempts"] == 3
    assert failed_step["max_attempts"] == 3
    assert manifest["stop_after"] is True


def test_mqtt_broker_experiment_retries_oqs_tls_validation_before_mqtt_validation(tmp_path, monkeypatch):
    experiment_cli = load_experiment_module()
    commands: list[list[str]] = []
    oqs_tls_attempts = 0
    sleeps: list[float] = []

    def fake_run(command, *, text, stdin, stdout, stderr, check, timeout=None):
        nonlocal oqs_tls_attempts
        commands.append(command)
        assert stdin == experiment_cli.subprocess.DEVNULL
        if command[2] == "validate-oqs-tls":
            oqs_tls_attempts += 1
            if oqs_tls_attempts < 3:
                return SimpleNamespace(returncode=1, stdout="connection refused\n")
        return SimpleNamespace(returncode=0, stdout="step output\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(experiment_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(experiment_cli.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(experiment_cli, "format_manifest_timestamp", lambda: "2026-07-04_003")

    args = experiment_cli.build_arg_parser().parse_args([
        "mqtt-broker-experiment",
        "--profile",
        "oqs",
        "--results-dir",
        str(tmp_path / "results"),
        "--validation-retries",
        "4",
        "--validation-retry-delay-seconds",
        "0.25",
    ])

    result = experiment_cli.run_mqtt_broker_experiment_command(args)

    assert result == 0
    assert oqs_tls_attempts == 3
    assert sleeps == [0.25, 0.25]
    subcommands = [command[2] for command in commands]
    assert subcommands.count("validate-oqs-tls") == 3
    assert "validate-oqs-mqtt" in subcommands
    manifest_path = tmp_path / "results" / "2026-07-04_003_mqtt_oqs_broker" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tls_step = next(step for step in manifest["steps"] if step["name"] == "validate_oqs_tls")
    assert tls_step["return_code"] == 0
    assert tls_step["attempts"] == 3
    assert tls_step["max_attempts"] == 4
    assert manifest["status"] == "passed"


def test_mqtt_broker_experiment_records_running_step_before_subprocess_returns(tmp_path, monkeypatch):
    experiment_cli = load_experiment_module()
    inspected_running_step = False

    def fake_run(command, *, text, stdin, stdout, stderr, check, timeout=None):
        nonlocal inspected_running_step
        assert stdin == experiment_cli.subprocess.DEVNULL
        manifest_path = tmp_path / "results" / "2026-07-04_004_mqtt_oqs_broker" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        if command[2] == "provision-certs":
            inspected_running_step = True
            assert manifest["steps"][0]["name"] == "provision_oqs_certs"
            assert manifest["steps"][0]["status"] == "running"
            assert manifest["steps"][0]["return_code"] is None
            assert manifest["steps"][0]["timeout_seconds"] == 12.5
            log_path = tmp_path / "results" / "2026-07-04_004_mqtt_oqs_broker" / "provision_oqs_certs.log"
            assert "# status: running" in log_path.read_text(encoding="utf-8")
        elif command[2] == "start":
            assert manifest["steps"][0]["name"] == "provision_oqs_certs"
            assert manifest["steps"][0]["status"] == "passed"
            assert manifest["steps"][1]["name"] == "start_broker"
            assert manifest["steps"][1]["status"] == "running"

        return SimpleNamespace(returncode=0, stdout="step output\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(experiment_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(experiment_cli, "format_manifest_timestamp", lambda: "2026-07-04_004")

    args = experiment_cli.build_arg_parser().parse_args([
        "mqtt-broker-experiment",
        "--profile",
        "oqs",
        "--results-dir",
        str(tmp_path / "results"),
        "--step-timeout-seconds",
        "12.5",
        "--no-deploy",
        "--skip-validation",
    ])

    assert experiment_cli.run_mqtt_broker_experiment_command(args) == 0
    assert inspected_running_step


def test_mqtt_broker_experiment_marks_step_timeout_failed(tmp_path, monkeypatch):
    experiment_cli = load_experiment_module()

    def fake_run(command, *, text, stdin, stdout, stderr, check, timeout=None):
        assert stdin == experiment_cli.subprocess.DEVNULL
        assert timeout == 0.5
        raise experiment_cli.subprocess.TimeoutExpired(command, timeout, output="partial output\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(experiment_cli.subprocess, "run", fake_run)
    monkeypatch.setattr(experiment_cli, "format_manifest_timestamp", lambda: "2026-07-04_005")

    args = experiment_cli.build_arg_parser().parse_args([
        "mqtt-broker-experiment",
        "--profile",
        "classical",
        "--results-dir",
        str(tmp_path / "results"),
        "--step-timeout-seconds",
        "0.5",
    ])

    result = experiment_cli.run_mqtt_broker_experiment_command(args)

    assert result == 124
    manifest_path = tmp_path / "results" / "2026-07-04_005_mqtt_classical_broker" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["failed_step"] == "provision_classical_certs"
    step = manifest["steps"][0]
    assert step["return_code"] == 124
    assert step["timed_out"] is True
    assert step["status"] == "failed"
    assert "partial output" in (tmp_path / "results" / "2026-07-04_005_mqtt_classical_broker" / "provision_classical_certs.log").read_text(encoding="utf-8")


def test_pqc_experiment_uses_separate_oqs_client_containers():
    source = (REPO_ROOT / "scripts" / "experiment.py").read_text(encoding="utf-8")

    assert "eclipse-mosquitto:2.1.2-alpine" in source
    assert "docker run -d " in source
    assert '--name "$subscriber" --entrypoint mosquitto_sub' in source
    assert 'docker rm -f "$subscriber"' in source
    assert "docker run --rm " in source
    assert "OPENSSL_CONF=/mosquitto/config/openssl.cnf" in source
    assert "OPENSSL_MODULES" not in source
    assert "--entrypoint mosquitto_sub" in source
    assert "--entrypoint mosquitto_pub" in source
    assert 'docker exec -i "$oqs_container_id"' not in source
    assert "label=com.docker.compose.service=mqtt-oqs" not in source

def test_pqc_readiness_requires_subscriber_and_publisher_success():
    source = (REPO_ROOT / "scripts" / "experiment.py").read_text(encoding="utf-8")
    readiness = source[source.index("def _wait_for_plaintext_mqtt_broker"):source.index("def _start_managed_mqtt_broker")]

    subscriber = readiness.index("mqtt_sub =")
    publisher = readiness.index("mqtt_pub =", subscriber)
    subscriber_command = readiness.index("f'{mqtt_sub} -h {host}", publisher)
    publisher_command = readiness.index("f'{mqtt_pub} -h {host}", subscriber_command)
    wait = readiness.index('wait "$sub_pid"; sub_rc=$?;', publisher_command)
    response = readiness.index('response=$(paste -sd, "$response_file")', wait)
    readiness_check = readiness.index('if [ "$sub_rc" -eq 0 ] && [ "$pub_rc" -eq 0 ]', response)

    assert subscriber < publisher < subscriber_command < publisher_command < wait < response < readiness_check
    assert 'pub_rc=$?' in readiness
    assert 'sub_rc=$?' in readiness
    assert '"$publisher_file" 2>&1; pub_rc=$?' in readiness

def test_pqc_uart_capture_uses_profile_hard_limit_and_current_boot_epoch():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'hard_limit_seconds = int(orchestration.get("hard_limit_seconds", duration_seconds))' in source
    assert 'boot_marker = str(experiment["uart"]["expected_boot_message"])' in source
    assert 'timeout 0.2s cat {device} >/dev/null 2>&1 || true' in source
    assert 'timeout {hard_limit_seconds}s cat' in source
    assert 'boot_marker={shlex.quote(boot_marker)}; boot_seen=0' in source
    assert 'if [ "$boot_seen" -eq 0 ] && grep -Fq "$boot_marker" "$uart_file"; then boot_seen=1; fi' in source
    assert 'if [ "$boot_seen" -eq 0 ]; then continue; fi' in source
    assert '[ "$attempts" -gt 0 ] && grep -Fq "$completion_marker" "$uart_file"' in source
    assert 'boot_marker_present=$boot_seen' in source
    assert 'hard_limit_seconds={hard_limit_seconds}' in source


def test_pqc_command_publisher_failures_are_retained():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'publish_failures=$((publish_failures + 1))' in source
    assert 'publish_failures=$publish_failures' in source
    assert 'last_publish_rc=$publish_rc' in source
    assert 'mosquitto_pub' in source
    assert 'publish_rc=$?' in source


def test_mqtt_uart_completion_is_observed_only_after_boot_and_publish():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    capture_block = source[source.index("def _execute_mqtt_e2e_uart_capture"):]
    legacy_branch = capture_block[capture_block.index("    else:\n        script = ("):]

    boot_check = legacy_branch.index('grep -Fq "$boot_marker" "$uart_file"')
    completion_check = legacy_branch.index('grep -Fq "$completion_marker" "$uart_file"')
    publish = legacy_branch.index('attempts=$((attempts + 1))')
    common_suffix = legacy_branch.index("+ common_suffix")

    assert boot_check < completion_check < publish < common_suffix
    assert '[ "$attempts" -gt 0 ]' in legacy_branch[completion_check - 120:completion_check]
    assert "duration_seconds=hard_limit_seconds" in capture_block


def test_classical_gateway_mqtt_clients_use_resolved_certificate_profile():
    experiment_cli = load_experiment_module()
    bundle = {
        "experiment": {
            "mqtt": {
                "tls": {"certificate_profile": "stepca-classical"}
            }
        }
    }

    assert experiment_cli._mqtt_remote_ca_file(bundle) == (
        "$HOME/pqc-framework-02/secrets/mqtt/stepca-classical/ca.crt"
    )

def test_oqs_gateway_clients_mount_profile_at_container_certificate_path():
    source = (REPO_ROOT / "scripts" / "experiment.py").read_text(encoding="utf-8")

    assert 'f"-v {certificate_dir}:/certs:ro "' in source
    assert "--cafile /certs/ca.crt --tls-version tlsv1.3" in source
    assert 'return "/mosquitto/config/certs/ca.crt"' not in source


def test_gateway_mqtt_client_host_uses_broker_identity_for_tls():
    experiment_cli = load_experiment_module()
    bundle = {
        "experiment": {
            "mqtt": {
                "broker": {"host": "pqc-gateway1.pqcnet"},
                "orchestration": {"host": "10.1.1.18"},
            }
        }
    }

    assert experiment_cli._mqtt_gateway_client_host(
        bundle, tls_enabled=True
    ) == "pqc-gateway1.pqcnet"


def test_gateway_mqtt_client_host_allows_transport_override_for_plaintext():
    experiment_cli = load_experiment_module()
    bundle = {
        "experiment": {
            "mqtt": {
                "broker": {"host": "pqc-gateway1.pqcnet"},
                "orchestration": {"host": "10.1.1.18"},
            }
        }
    }

    assert experiment_cli._mqtt_gateway_client_host(
        bundle, tls_enabled=False
    ) == "10.1.1.18"


def test_e2e_clients_emit_topic_qualified_independent_broker_evidence():
    source = (REPO_ROOT / "scripts" / "experiment.py").read_text(encoding="utf-8")

    assert 'publisher_client_id = "pqc-host-e2e-publisher"' in source
    assert 'subscriber_client_id = "pqc-host-e2e-subscriber"' in source
    assert '-i {shlex.quote(subscriber_client_id)} -v -t {response_topic}' in source
    assert '-i {shlex.quote(publisher_client_id)} -t {command_topic}' in source
    assert 'mqtt-subscriber-raw.log' in source
    assert 'mqtt-broker-message-evidence.json' in source
    assert 'failure_stage = "broker_message_evidence"' in source


def test_broker_message_evidence_parser_requires_both_directions():
    experiment_cli = load_experiment_module()
    log = """
mqtt | New client connected from 10.1.1.119:50000 as pqc-stm32-tls-e2e (p2, c1, k30).
mqtt | Received SUBSCRIBE from pqc-stm32-tls-e2e
mqtt | Sending SUBACK to pqc-stm32-tls-e2e
mqtt | Received PUBLISH from pqc-host-e2e-publisher (d0, q0, r0, m0, 'pqc/experiments/stm32/tls/command', ... (3 bytes))
mqtt | Sending PUBLISH to pqc-stm32-tls-e2e (d0, q0, r0, m0, 'pqc/experiments/stm32/tls/command', ... (3 bytes))
mqtt | Received PUBLISH from pqc-stm32-tls-e2e (d0, q0, r0, m0, 'pqc/experiments/stm32/tls/response', ... (22 bytes))
mqtt | Sending PUBLISH to pqc-host-e2e-subscriber (d0, q0, r0, m0, 'pqc/experiments/stm32/tls/response', ... (22 bytes))
"""
    evidence = experiment_cli._parse_mqtt_broker_message_evidence(
        log,
        stm32_client_id="pqc-stm32-tls-e2e",
        publisher_client_id="pqc-host-e2e-publisher",
        subscriber_client_id="pqc-host-e2e-subscriber",
        command_topic="pqc/experiments/stm32/tls/command",
        response_topic="pqc/experiments/stm32/tls/response",
    )
    assert evidence["passed"] is True
    assert all(value is True for key, value in evidence.items() if key != "passed")

    incomplete = experiment_cli._parse_mqtt_broker_message_evidence(
        log.replace("Sending PUBLISH to pqc-host-e2e-subscriber", "not delivered"),
        stm32_client_id="pqc-stm32-tls-e2e",
        publisher_client_id="pqc-host-e2e-publisher",
        subscriber_client_id="pqc-host-e2e-subscriber",
        command_topic="pqc/experiments/stm32/tls/command",
        response_topic="pqc/experiments/stm32/tls/response",
    )
    assert incomplete["passed"] is False
    assert incomplete["response_publish_delivered"] is False


def test_managed_tls_experiments_collect_broker_keylog_into_result_directory():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'MQTT_BROKER_IMAGE = "eclipse-mosquitto:2.1.2-alpine"' in source
    assert 'MQTT_TLS_KEYLOG_FILENAME = "mqtt-broker-tls-keylog.log"' in source
    assert 'subcommand="collect-tls-keylog"' in source
    assert '"sha256": hashlib.sha256(data).hexdigest()' in source
    assert '"tls_keylog": keylog_evidence' in source


def test_broker_evidence_is_mandatory_and_fatal_errors_fail_the_run():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'BROKER_FATAL_LOG_PATTERNS' in source
    assert '"broker_log_write_failure", "unable to open log file"' in source
    assert '"unexpected_broker_tls_error", "ssl/tls alert bad certificate"' in source
    assert '"required_for_pass": True' in source
    assert 'failure_stage = "broker_log_unavailable"' in source
    assert 'failure_stage = "broker_message_evidence"' in source
    assert '"broker_log_integrity": broker_log_integrity' in source


def test_subscriber_artifact_is_rebuilt_from_completed_capture_and_verified():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'authoritative_subscriber_output = _extract_marked_text(' in source
    assert 'uart_result.capture.stderr' in source
    assert 'subscriber_raw_path.write_text(authoritative_subscriber_output' in source
    assert '"artifact_matches_capture": persisted_subscriber_output == authoritative_subscriber_output' in source
    assert 'failure_stage = "subscriber_evidence_integrity"' in source


def test_subscriber_marker_extraction_accepts_ansi_prefixed_begin_marker():
    experiment_cli = load_experiment_module()
    stderr = (
        "\x1b[39;49m\x1b[0mSoftware reset is performed"
        "PQC_MQTT_SUBSCRIBER_OUTPUT_BEGIN\n"
        "topic/response ready\n"
        "topic/response {\"type\":\"connect_timing\",\"milliseconds\":123}\n"
        "PQC_MQTT_SUBSCRIBER_OUTPUT_END\n"
    )

    extracted = experiment_cli._extract_marked_text(
        stderr,
        "PQC_MQTT_SUBSCRIBER_OUTPUT_BEGIN",
        "PQC_MQTT_SUBSCRIBER_OUTPUT_END",
    )

    assert extracted == (
        "topic/response ready\n"
        "topic/response {\"type\":\"connect_timing\",\"milliseconds\":123}\n"
    )


def test_subscriber_marker_extraction_fails_when_marker_pair_is_incomplete():
    experiment_cli = load_experiment_module()

    assert experiment_cli._extract_marked_text(
        "PQC_MQTT_SUBSCRIBER_OUTPUT_BEGIN\ntopic/response ready\n",
        "PQC_MQTT_SUBSCRIBER_OUTPUT_BEGIN",
        "PQC_MQTT_SUBSCRIBER_OUTPUT_END",
    ) == ""


def test_uart_capture_forces_marker_onto_a_new_line():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")

    assert "printf '\\\\nPQC_MQTT_SUBSCRIBER_OUTPUT_BEGIN\\\\n'" in source
    assert "printf 'PQC_MQTT_SUBSCRIBER_OUTPUT_END\\\\n'" in source
