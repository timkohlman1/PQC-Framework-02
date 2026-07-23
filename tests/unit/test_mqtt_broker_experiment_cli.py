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
        "provision-oqs-certs",
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

        if command[2] == "provision-oqs-certs":
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


def test_pqc_experiment_resolves_oqs_container_by_compose_labels():
    source = (REPO_ROOT / "scripts" / "experiment.py").read_text(encoding="utf-8")

    assert "label=com.docker.compose.project=pqc-framework-mqtt-broker" in source
    assert "label=com.docker.compose.service=mqtt-oqs" in source
    assert "--filter status=running" in source
    assert 'docker exec -i "$oqs_container_id" mosquitto_sub' in source
    assert 'docker exec -i "$oqs_container_id" mosquitto_pub' in source
    assert "docker compose --profile oqs exec -T mqtt-oqs" not in source


def test_pqc_readiness_requires_subscriber_and_publisher_success():
    source = (REPO_ROOT / "scripts" / "experiment.py").read_text(encoding="utf-8")

    assert 'pub_rc=$?' in source
    assert 'sub_rc=$?' in source
    assert '[ "$sub_rc" -eq 0 ] && [ "$pub_rc" -eq 0 ]' in source
    assert 'oqs_container_resolution_failed count=$oqs_container_count' in source
    assert "mosquitto_pub" in source
    assert ">/tmp/pqc-mqtt-ready-pub.$$ 2>&1; pub_rc=$?" in source


def test_pqc_uart_capture_uses_profile_hard_limit_and_final_marker_check():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'hard_limit_seconds = int(orchestration.get("hard_limit_seconds", duration_seconds))' in source
    assert 'timeout {hard_limit_seconds}s cat' in source
    assert 'if [ "$completion_seen" -eq 0 ] && grep -Fq "$completion_marker" "$uart_file"' in source
    assert 'hard_limit_seconds={hard_limit_seconds}' in source


def test_pqc_command_publisher_failures_are_retained():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'publish_failures=$((publish_failures + 1))' in source
    assert 'publish_failures=$publish_failures' in source
    assert 'last_publish_rc=$publish_rc' in source
    assert 'mosquitto_pub' in source
    assert 'publish_rc=$?' in source
