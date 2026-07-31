from __future__ import annotations

from pathlib import Path

from framework.packet_capture import (
    PACKET_CAPTURE_ARTIFACT_NAME,
    GatewayPacketCapture,
    packet_capture_config,
    start_gateway_packet_capture,
    stop_and_collect_gateway_packet_capture,
)
from framework.uart import CommandExecution


def _execution(command: list[str], return_code: int = 0, stdout: str = "", stderr: str = "") -> CommandExecution:
    return CommandExecution(command=command, return_code=return_code, stdout=stdout, stderr=stderr, duration_seconds=0.01)


def _bundle(packet_capture: dict | None = None) -> dict:
    network = {"wifi": {"ssid": "pqc", "psk": "lukeisadog"}, "ipv4": {"mode": "dhcp"}}
    if packet_capture is not None:
        network["packet_capture"] = packet_capture
    return {
        "experiment": {"network": network},
        "host": {"alias": "pqc-gateway1"},
    }


def test_packet_capture_prefers_explicit_stm32_mac_filter():
    resolved = packet_capture_config(
        _bundle({"interface": "wlan0", "stm32_mac_address": "02:11:22:33:44:55"})
    )
    assert resolved == {
        "interface": "wlan0",
        "stm32_mac_address": "02:11:22:33:44:55",
        "capture_filter": "ether host 02:11:22:33:44:55",
    }


def test_packet_capture_defaults_to_any_interface_without_narrow_filter():
    resolved = packet_capture_config(_bundle())
    assert resolved == {
        "interface": "any",
        "stm32_mac_address": None,
        "capture_filter": None,
    }


def test_non_network_experiment_does_not_enable_packet_capture():
    assert packet_capture_config({"experiment": {}, "host": {"alias": "gateway"}}) is None


def test_start_command_uses_tcpdump_and_returns_owned_pid(tmp_path: Path):
    commands: list[list[str]] = []

    def runner(command: list[str], cwd: Path) -> CommandExecution:
        commands.append(command)
        return _execution(command, stdout="4321\n")

    capture, execution = start_gateway_packet_capture(
        bundle=_bundle({"stm32_mac_address": "02:11:22:33:44:55"}),
        repo_root=tmp_path,
        run_id="2026-07-31_001_test",
        runner=runner,
    )

    assert execution is not None and execution.return_code == 0
    assert capture is not None and capture.pid == 4321
    rendered = " ".join(commands[0])
    assert "tcpdump" in rendered
    assert "-i any" in rendered
    assert "ether host 02:11:22:33:44:55" in rendered
    assert "nohup" in rendered



def test_start_runner_receives_keyword_only_cwd(tmp_path: Path):
    observed: dict[str, object] = {}

    def runner(command: list[str], *, cwd: Path) -> CommandExecution:
        observed["command"] = command
        observed["cwd"] = cwd
        return _execution(command, stdout="4321\n")

    capture, execution = start_gateway_packet_capture(
        bundle=_bundle(),
        repo_root=tmp_path,
        run_id="keyword-only-runner",
        runner=runner,
    )

    assert execution is not None and execution.return_code == 0
    assert capture is not None and capture.pid == 4321
    assert observed["cwd"] == tmp_path

def test_stop_collects_non_empty_capture_and_hashes_artifact(tmp_path: Path):
    capture = GatewayPacketCapture(
        gateway_alias="pqc-gateway1",
        remote_capture_path="/tmp/test.pcap",
        remote_log_path="/tmp/test.log",
        pid=4321,
        interface="any",
        capture_filter=None,
        stm32_mac_address=None,
        started_at_epoch_seconds=0.0,
    )

    def runner(command: list[str], cwd: Path) -> CommandExecution:
        if command[0] == "scp":
            Path(command[-1]).write_bytes(b"pcap-data")
        if command[0] == "ssh" and command[2].startswith("cat "):
            return _execution(command, stdout="10 packets captured\n")
        return _execution(command)

    result = stop_and_collect_gateway_packet_capture(
        capture=capture,
        repo_root=tmp_path,
        result_dir=tmp_path,
        runner=runner,
    )

    assert result.return_code == 0
    assert result.artifact_path == tmp_path / PACKET_CAPTURE_ARTIFACT_NAME
    assert result.size_bytes == len(b"pcap-data")
    assert result.sha256 is not None and len(result.sha256) == 64
    assert "10 packets captured" in result.log_path.read_text(encoding="utf-8")


def test_mqtt_orchestration_collects_packet_capture_in_guaranteed_cleanup():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    start_index = source.index("packet_capture, packet_capture_start = start_gateway_packet_capture(")
    reset_index = source.index("uart_result = execute_uart_capture(", start_index)
    finally_index = source.index("finally:", reset_index)
    collect_index = source.index("stop_and_collect_gateway_packet_capture(", finally_index)
    broker_cleanup_index = source.index("_collect_and_stop_managed_mqtt_broker(", collect_index)

    assert start_index < reset_index < finally_index < collect_index < broker_cleanup_index
    for marker in (
        '"gateway_packet_capture"',
        '"sha256": packet_capture_result.sha256',
        '"size_bytes": packet_capture_result.size_bytes',
        'failure_stage = "gateway_packet_capture"',
    ):
        assert marker in source


def test_non_mqtt_network_runs_use_generic_packet_capture_wrapper():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert "def _execute_uart_capture_with_optional_gateway_packet_capture(" in source
    assert source.count("uart_result, final_return_code, failure_stage = _execute_uart_capture_with_optional_gateway_packet_capture(") == 3
