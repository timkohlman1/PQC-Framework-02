from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module(relative: str, name: str):
    repo_root = Path(__file__).resolve().parents[2]
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(name, repo_root / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def test_degradation_config_splits_rtt_and_records_independent_loss():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation")
    config = module.network_degradation_config({"experiment": {"network": {"degradation": {
        "enabled": True,
        "interface": "wlan-experiment",
        "ifb_interface": "ifb-pqc0",
        "rate_kbit": 40,
        "rtt_ms": 200,
        "loss_percent": 5,
        "mtu": 1280,
        "management_safe": True,
    }}}})
    assert config is not None
    assert config.one_way_delay_ms == 100
    evidence = module.degradation_manifest(config)
    assert evidence["loss_model"] == "independent_per_direction_netem"
    assert evidence["one_way_delay_ms"] == 100


def test_degradation_requires_management_safety_acknowledgement():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_validation")
    try:
        module.network_degradation_config({"experiment": {"network": {"degradation": {
            "enabled": True,
            "interface": "eth0",
            "rate_kbit": 5,
            "rtt_ms": 1000,
            "loss_percent": 10,
            "mtu": 1500,
        }}}})
    except ValueError as exc:
        assert "management_safe" in str(exc)
    else:
        raise AssertionError("unsafe impairment configuration was accepted")


def test_apply_command_uses_distinct_interface_and_ifb_netem():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_commands")
    config = module.NetworkDegradationConfig(
        interface="wlan-experiment", ifb_interface="ifb-pqc0", rate_kbit=250,
        rtt_ms=50, loss_percent=1.0, mtu=1500, management_safe=True, broker_service="mqtt-classical",
    )
    script = module._remote_script(config)
    assert 'dev "$iface" root netem delay 25ms loss 1% rate 250kbit' in script
    assert "docker" in script.lower() or "$DOCKER" in script
    assert "PQC_EXPERIMENT_VETH" in script
    assert "link set dev $physical_iface mtu" not in script
    assert 'mirred egress redirect dev "$ifb"' in script
    assert 'dev "$ifb" root netem delay 25ms loss 1% rate 250kbit' in script

def test_runtime_only_measurement_does_not_prepare_build_or_flash():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    start = source.index("def _run_runtime_only_measurement(")
    end = source.index("def run_full_baseline_command", start)
    runtime_only = source[start:end]
    assert "execute_build(" not in runtime_only
    assert "execute_flash(" not in runtime_only
    assert "_prepare_dependencies_for_result(" not in runtime_only
    assert "_execute_mqtt_e2e_uart_capture(" in runtime_only


def test_result_collector_is_finalised_before_impairment_cleanup():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    finally_start = source.index("    finally:", source.index("def _execute_mqtt_e2e_uart_capture"))
    collector = source.index("stop_and_collect_gateway_result_collector", finally_start)
    cleanup = source.index("remove_gateway_network_degradation", finally_start)
    assert collector < cleanup


def test_gateway_command_resolution_falls_back_to_standard_system_paths():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_path_resolution")
    script = module._remote_command_resolution_script()
    assert "/usr/sbin/$name" in script
    assert "/usr/bin/$name" in script
    assert "TC=$(resolve_cmd tc)" in script
    assert "IP=$(resolve_cmd ip)" in script
    assert "MODPROBE=$(resolve_cmd modprobe)" in script


def test_apply_uses_resolved_absolute_commands_instead_of_bare_tc_ip():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_resolved_apply")
    config = module.NetworkDegradationConfig(
        interface="enp0s31f6", ifb_interface="ifb-pqc0", rate_kbit=40,
        rtt_ms=200, loss_percent=0.0, mtu=1280, management_safe=True, broker_service="mqtt-classical",
    )
    script = module._remote_script(config)
    assert 'sudo -n "$TC" qdisc add dev "$iface" root netem' in script
    assert 'sudo -n "$IP" link set dev "$iface" mtu 1280' in script
    assert 'NSENTER' in script
    assert 'link set dev eth0 mtu 1280' in script
    assert 'sudo -n "$MODPROBE" ifb numifbs=1' in script
    assert "sudo -n tc " not in script
    assert "sudo -n ip " not in script


def test_preflight_checks_noninteractive_sudo_before_profile_build():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_preflight")
    script = module.gateway_network_degradation_preflight_script("enp0s31f6")
    assert "PQC_NETDEG_ERROR=sudo_tc_required" in script
    assert "PQC_NETDEG_ERROR=sudo_ip_required" in script
    assert "PQC_NETDEG_ERROR=sudo_modprobe_required" in script
    assert "PQC_NETDEG_PREFLIGHT=passed" in script




def test_veth_resolution_queries_container_link_via_ip_in_network_namespace():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_namespace_link")
    config = module.NetworkDegradationConfig(
        interface="enp0s31f6", ifb_interface="ifb-pqc0", rate_kbit=256,
        rtt_ms=0, loss_percent=0.0, mtu=1500, management_safe=True, broker_service="mqtt-oqs",
    )
    script = module._remote_script(config)
    assert 'container_link=$(sudo -n "$NSENTER" -t "$pid" -n "$IP" -o link show dev "$container_iface")' in script
    assert 'container_iface=eth0' in script
    assert r'@if\([0-9][0-9]*\)' in script
    assert 'container_mtu=$(printf' in script
    assert 'PQC_NETDEG_ERROR=container_peer_index_not_found' in script
    assert 'PQC_NETDEG_ERROR=container_mtu_not_found' in script
    assert '/sys/class/net/eth0/iflink' not in script
    assert '/sys/class/net/eth0/mtu' not in script


def test_container_mtu_reuses_namespace_aware_ip_result():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_namespace_mtu")
    config = module.NetworkDegradationConfig(
        interface="enp0s31f6", ifb_interface="ifb-pqc0", rate_kbit=256,
        rtt_ms=0, loss_percent=0.0, mtu=1200, management_safe=True, broker_service="mqtt-oqs",
    )
    script = module._remote_script(config)
    assert 'container_original_mtu=$container_mtu' in script
    assert 'sudo -n "$NSENTER" -t "$pid" -n "$IP" link set dev eth0 mtu 1200' in script


def test_remote_application_rolls_back_partial_failure_and_rejects_occupied_resources():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_rollback")
    config = module.NetworkDegradationConfig("eth0", "ifb-pqc0", 256, 200, 1.0, 1280, True, "mqtt-classical")
    script = module._remote_script(config)
    assert "PQC_NETDEG_ERROR=occupied_veth_qdisc" in script
    assert "PQC_NETDEG_ERROR=occupied_ifb" in script
    assert "trap rollback EXIT" in script
    assert "PQC_ROLLBACK_RESULT=" in script
    assert script.index("trap rollback EXIT") < script.index('link set dev "$iface" mtu 1280')


def test_gateway_state_rejects_missing_ifb_redirect_or_wrong_mtu():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_state")
    config = module.NetworkDegradationConfig("eth0", "ifb-pqc0", 256, 200, 1.0, 1280, True, "mqtt-classical")
    qdisc = "qdisc netem 8001: root refcnt 2 limit 1000 delay 100ms loss 1% rate 256Kbit\n Sent 500 bytes 4 pkt\n"
    output = ("PQC_EXPERIMENT_VETH=veth0\nPQC_EXPERIMENT_PEER_INDEX=10\nPQC_REPORTING_PEER_INDEX=11\n"
              "PQC_APPLIED_STATE_BEGIN\n1: veth0 mtu 1280\n"
              "PQC_VETH_QDISC_BEGIN\n" + qdisc + "qdisc ingress ffff: parent ffff:fff1\nPQC_VETH_QDISC_END\n"
              "PQC_IFB_QDISC_BEGIN\n" + qdisc + "PQC_IFB_QDISC_END\n"
              "PQC_INGRESS_FILTER_BEGIN\naction order 1: mirred redirect dev ifb-pqc0\nPQC_INGRESS_FILTER_END\n"
              "2: eth0 mtu 1280\nPQC_APPLIED_STATE_END\n")
    assert module._verified_state(output, config) == (True, "verified")
    assert module._verified_state(output.replace("redirect dev ifb-pqc0", "redirect dev ifb-other"), config)[0] is False
    assert module._verified_state(output.replace("eth0 mtu 1280", "eth0 mtu 1500"), config)[0] is False
    assert module._verified_state(output.replace("rate 256Kbit", "rate 500Kbit"), config)[0] is False


def test_gateway_packet_counts_require_both_directional_counters():
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_packets")
    output = ("PQC_VETH_QDISC_BEGIN\nqdisc netem 8001: root\n Sent 80 bytes 2 pkt\nPQC_VETH_QDISC_END\n"
              "PQC_IFB_QDISC_BEGIN\nqdisc netem 8002: root\n Sent 120 bytes 3 pkt\nPQC_IFB_QDISC_END\n")
    assert module.gateway_impairment_packet_counts(output) == (2, 3)
    assert module.gateway_impairment_packet_counts(output.replace(" Sent 120 bytes 3 pkt", " No packet counters")) is None


def test_remote_script_has_valid_posix_shell_syntax():
    import subprocess
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_shell")
    config = module.NetworkDegradationConfig("eth0", "ifb-pqc0", 256, 200, 1.0, 1280, True, "mqtt-classical")
    compiled = subprocess.run(["sh", "-n"], input=module._remote_script(config), text=True, capture_output=True)
    assert compiled.returncode == 0, compiled.stderr


def test_failed_gateway_apply_preserves_rollback_evidence(tmp_path):
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_failed_apply")
    bundle = {
        "host": {"user": "test-user", "alias": "test-gateway"},
        "experiment": {
            "mqtt": {"broker_profile": "classical"},
            "network": {"degradation": {
                "enabled": True, "interface": "eth-test0", "ifb_interface": "ifb-pqc0",
                "rate_kbit": 256, "rtt_ms": 200, "loss_percent": 1.0,
                "mtu": 1280, "management_safe": True,
            }},
        },
    }
    def failure(command, *, cwd):
        return module.CommandExecution(command, 1,
            "PQC_ORIGINAL_MTU=1500\nPQC_ROLLBACK_BEGIN\nPQC_ROLLBACK_RESULT=1\nPQC_ROLLBACK_END\n",
            "partial qdisc installation failed\n", 0.01)
    active, result = module.apply_gateway_network_degradation(
        bundle=bundle, repo_root=tmp_path, result_dir=tmp_path, runner=failure,
    )
    assert active is None and result.return_code != 0
    text = (tmp_path / module.NETWORK_DEGRADATION_LOG_NAME).read_text()
    assert "PQC_ROLLBACK_RESULT=1" in text and "partial qdisc installation failed" in text


def test_state_mismatch_triggers_cleanup_before_apply_can_be_accepted(tmp_path):
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_failed_state")
    bundle = {
        "host": {"user": "test-user", "alias": "test-gateway"},
        "experiment": {
            "mqtt": {"broker_profile": "classical"},
            "network": {"degradation": {
                "enabled": True, "interface": "eth-test0", "ifb_interface": "ifb-pqc0",
                "rate_kbit": 256, "rtt_ms": 200, "loss_percent": 1.0,
                "mtu": 1280, "management_safe": True,
            }},
        },
    }
    calls = []
    def runner(command, *, cwd):
        calls.append(command)
        if len(calls) == 1:
            return module.CommandExecution(command, 0,
                "PQC_ORIGINAL_MTU=1500\nPQC_CONTAINER_ORIGINAL_MTU=1500\n"
                "PQC_EXPERIMENT_VETH=veth1\nPQC_EXPERIMENT_CONTAINER_PID=123\n",
                "", 0.01)
        return module.CommandExecution(command, 1, "PQC_RESTORED_STATE_BEGIN\n",
                                       "restoration failed\n", 0.01)
    active, result = module.apply_gateway_network_degradation(
        bundle=bundle, repo_root=tmp_path, result_dir=tmp_path, runner=runner,
    )
    assert active is None and result.return_code != 0 and len(calls) == 2
    assert "cleanup_return_code=1" in result.stderr
    assert "Cleanup return code: 1" in (tmp_path / module.NETWORK_DEGRADATION_LOG_NAME).read_text()


def test_retained_state_rejects_changed_container_and_records_error(tmp_path):
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_retained")
    config = module.NetworkDegradationConfig("eth-test0", "ifb-pqc0", 256, 200, 1, 1280, True, "mqtt-classical")
    command = module.CommandExecution(["ssh", "test"], 0, "", "", 0)
    log = tmp_path / module.NETWORK_DEGRADATION_LOG_NAME
    log.write_text("initial evidence\n")
    active = module.GatewayNetworkDegradation("test", "test-user@test", config, 1500, 1500,
                                              "veth1", 123, command, log)
    def mismatch(command, *, cwd):
        return module.CommandExecution(command, 3, "PQC_NETDEG_ERROR=experiment_container_changed\n", "", 0.01)
    observed = module.verify_gateway_network_degradation(
        degradation=active, repo_root=tmp_path, runner=mismatch,
    )
    assert observed.return_code != 0
    assert "experiment_container_changed" in log.read_text()


def test_remote_retained_state_and_cleanup_scripts_have_valid_shell_syntax(tmp_path):
    import shlex
    import subprocess
    module = _load_module("scripts/framework/network_degradation.py", "network_degradation_shell_cleanup")
    config = module.NetworkDegradationConfig("eth0", "ifb-pqc0", 256, 200, 1.0, 1280, True, "mqtt-classical")
    command = module.CommandExecution(["ssh", "test"], 0, "", "", 0)
    log = tmp_path / module.NETWORK_DEGRADATION_LOG_NAME
    log.write_text("application evidence\n")
    active = module.GatewayNetworkDegradation("test", "user@test", config, 1500, 1500, "veth1", 123, command, log)
    scripts = []

    def collect(command, *, cwd):
        shell = shlex.split(command[-1])
        assert shell[:2] == ["sh", "-c"]
        scripts.append(shell[2])
        return module.CommandExecution(command, 1, "", "test-only runner\n", 0)

    module.verify_gateway_network_degradation(degradation=active, repo_root=tmp_path, runner=collect)
    module.remove_gateway_network_degradation(degradation=active, repo_root=tmp_path, runner=collect)
    assert len(scripts) == 2
    for script in scripts:
        parsed = subprocess.run(["sh", "-n"], input=script, text=True, capture_output=True)
        assert parsed.returncode == 0, parsed.stderr


def test_ipv4_small_mtu_stress_config_is_bounded_and_isolated():
    import pytest
    module = _load_module("scripts/framework/network_degradation.py", "small_mtu_validation")
    for mtu in (400, 576, 768):
        config = module.network_degradation_config({"experiment": {"network": {"degradation": dict(
            enabled=True, interface="enp0s31f6", rate_kbit=100000, rtt_ms=0,
            loss_percent=0, mtu=mtu, management_safe=True)}}})
        assert config.mtu == mtu
    with pytest.raises(ValueError, match="400"):
        module.network_degradation_config({"experiment": {"network": {"degradation": dict(
            enabled=True, interface="enp0s31f6", rate_kbit=100000, rtt_ms=0,
            loss_percent=0, mtu=399, management_safe=True)}}})
