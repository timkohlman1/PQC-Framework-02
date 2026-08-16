import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CMAKE_FILE = ROOT / "experiment/mqtt-broker/host-wolfmqtt/CMakeLists.txt"
UTILITY = ROOT / "experiment/mqtt-broker/scripts/host_wolfmqtt_validate.py"


def load_utility_module():
    spec = importlib.util.spec_from_file_location("host_wolfmqtt_validate", UTILITY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_host_wolfmqtt_build_uses_pinned_sources_and_wolfssl():
    text = CMAKE_FILE.read_text(encoding="utf-8")
    assert "Middlewares/Third_Party/wolfMQTT" in text
    assert "tools/wolfboot/lib/wolfssl" in text
    assert "Middlewares/Third_Party/wolfSSL" not in text
    assert "ENABLE_MQTT_TLS" in text
    assert "wolfssl::wolfssl" in text
    assert "pqc_host_wolfmqtt_client" in text


def test_host_wolfmqtt_evidence_boundary_is_explicit():
    text = UTILITY.read_text(encoding="utf-8")
    assert '"evidence_class": "host_side"' in text
    assert "broker_compatibility_confirmed" in text
    for claim in (
        "claims_stm32_success",
        "claims_wifi_module_success",
        "claims_lwip_on_stm32_success",
        "claims_wolfssl_on_stm32_success",
        "claims_wolfmqtt_on_stm32_success",
        "claims_end_to_end_wireless_success",
    ):
        assert f'"{claim}": False' in text


def test_help_is_local_only_and_does_not_invoke_subprocess(monkeypatch, capsys):
    module = load_utility_module()

    def fail_run(*args, **kwargs):
        raise AssertionError("help must not configure, build, execute, or access the network")

    monkeypatch.setattr(module, "run", fail_run)
    assert module.main(["help"]) == 0
    output = capsys.readouterr().out
    assert "evidence_scope=local_help_only" in output
    assert "No build or network access is performed" in output
    assert "test.mosquitto.org" not in output


def test_run_without_explicit_client_arguments_is_rejected(monkeypatch, capsys):
    module = load_utility_module()

    def fail_run(*args, **kwargs):
        raise AssertionError("empty run must be rejected before subprocess execution")

    monkeypatch.setattr(module, "run", fail_run)
    assert module.main(["run"]) == 2
    output = capsys.readouterr().out
    assert "evidence_scope=rejected_before_execution" in output
    assert "upstream example defaults are intentionally not permitted" in output


def run_boundary_case(module, monkeypatch, tmp_path, wrapper_tokens):
    commands = []

    def capture_run(command, *, cwd=None):
        commands.append(command)
        if command[0] == "cmake" and "--build" not in command:
            build_dir = Path(command[command.index("-B") + 1])
            build_dir.mkdir(parents=True, exist_ok=True)
            executable = build_dir / "pqc_host_wolfmqtt_client"
            executable.write_text("", encoding="utf-8")
        return 0

    def capture_run_captured(command, *, cwd=None):
        commands.append(command)
        return 0, ""

    monkeypatch.setattr(module, "run", capture_run)
    monkeypatch.setattr(module, "run_captured", capture_run_captured)
    monkeypatch.setattr(module, "repository_root", lambda: tmp_path)

    assert module.main(wrapper_tokens) == 0
    return commands


def test_run_separates_wrapper_options_after_action(monkeypatch, tmp_path):
    module = load_utility_module()
    result_path = "results/host-wolfmqtt/result.json"
    commands = run_boundary_case(
        module,
        monkeypatch,
        tmp_path,
        [
            "run",
            "--build-dir", "build/host-wolfmqtt",
            "--result-json", result_path,
            "--client-args",
            "-h", "10.1.1.18",
            "-p", "8883",
            "-t",
        ],
    )

    assert commands[-1] == [
        str(tmp_path / "build/host-wolfmqtt/pqc_host_wolfmqtt_client"),
        "-h", "10.1.1.18",
        "-p", "8883",
        "-t",
    ]
    assert "--result-json" not in commands[-1]
    assert result_path not in commands[-1]


def test_run_accepts_wrapper_options_before_action(monkeypatch, tmp_path):
    module = load_utility_module()
    commands = run_boundary_case(
        module,
        monkeypatch,
        tmp_path,
        [
            "--result-json", "results/host-wolfmqtt/result.json",
            "run",
            "--build-dir", "build/host-wolfmqtt",
            "--client-args",
            "-h", "10.1.1.18",
            "-p", "8883",
            "-t",
        ],
    )
    assert commands[-1][1:] == ["-h", "10.1.1.18", "-p", "8883", "-t"]


def test_split_preserves_all_client_tokens_verbatim():
    module = load_utility_module()
    for boundary in ("--client-args", "--"):
        wrapper, client = module.split_arguments(
            ["run", "--result-json", "result.json", boundary, "-h", "10.1.1.18", "-m", "--literal"]
        )
        assert wrapper == ["run", "--result-json", "result.json"]
        assert client == ["-h", "10.1.1.18", "-m", "--literal"]


def test_documented_powershell_boundary_is_present():
    text = UTILITY.read_text(encoding="utf-8")
    assert "--client-args" in text
    assert "quote each dash-prefixed" in text



def test_runtime_output_requires_complete_success_sequence():
    module = load_utility_module()
    output = "\n".join(
        (
            "MQTT Socket Connect: Success (0)",
            "MQTT Connect: Proto (v3.1.1), Success (0)",
            "MQTT Connect Ack: Return Code 0, Session Present 0",
            "MQTT Subscribe: Success (0)",
            "MQTT Publish: Topic pqc/test, ID 2, Success (0)",
            "MQTT Message: Done",
            "MQTT Disconnect: Success (0)",
            "MQTT Socket Disconnect: Success (0)",
        )
    )
    markers = module.evaluate_runtime_output(output)
    assert markers["tls_socket_connected"] is True
    assert markers["mqtt_connected"] is True
    assert markers["mqtt_connect_acknowledged"] is True
    assert markers["mqtt_subscribed"] is True
    assert markers["mqtt_publish_succeeded"] is True
    assert markers["mqtt_message_received"] is True
    assert markers["mqtt_disconnected"] is True
    assert markers["socket_disconnected"] is True


def test_runtime_output_does_not_confirm_partial_sequence(tmp_path):
    module = load_utility_module()
    destination = tmp_path / "result.json"
    module.repository_root = lambda: tmp_path
    module.write_result(
        str(destination.relative_to(tmp_path)),
        action="run",
        scope="host_runtime_command",
        return_code=0,
        runtime_markers={
            "tls_socket_connected": True,
            "mqtt_connected": True,
        },
    )
    data = __import__("json").loads(destination.read_text(encoding="utf-8"))
    assert data["command_succeeded"] is True
    assert data["broker_compatibility_confirmed"] is False


def test_runtime_output_confirms_complete_sequence(tmp_path):
    module = load_utility_module()
    destination = tmp_path / "result.json"
    module.repository_root = lambda: tmp_path
    markers = {
        "tls_socket_connected": True,
        "mqtt_connected": True,
        "mqtt_connect_acknowledged": True,
        "mqtt_subscribed": True,
        "mqtt_publish_succeeded": True,
        "mqtt_message_received": True,
        "mqtt_disconnected": True,
        "socket_disconnected": True,
    }
    module.write_result(
        str(destination.relative_to(tmp_path)),
        action="run",
        scope="host_runtime_command",
        return_code=0,
        runtime_markers=markers,
    )
    data = __import__("json").loads(destination.read_text(encoding="utf-8"))
    assert data["command_succeeded"] is True
    assert data["runtime_markers"] == markers
    assert data["broker_compatibility_confirmed"] is True


def test_compose_filename_is_canonical():
    for path in (
        ROOT / "README.md",
        ROOT / "AI_BUILD_GUIDE.md",
        ROOT / "docs/007_framework_architecture.md",
        ROOT / "docs/non_hardware_mqtt_tls_development_plan.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "docker-compose.yml" not in text
