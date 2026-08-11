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
        rtt_ms=50, loss_percent=1.0, mtu=1500, management_safe=True,
    )
    script = module._remote_script(config)
    assert "dev $iface root netem delay 25ms loss 1% rate 250kbit" in script
    assert "mirred egress redirect dev $ifb" in script
    assert "dev $ifb root netem delay 25ms loss 1% rate 250kbit" in script

def test_preparation_command_preserves_default_secure_boot_policy():
    grid_module = _load_module("scripts/network_degradation_grid.py", "network_degradation_grid_preparation_command")
    repo_root = Path(__file__).resolve().parents[2]
    command = grid_module._preparation_command(
        repo_root=repo_root,
        profile_path="configs/experiments/applications/ready_metrics/example.yaml",
        results_dir=Path("results"),
        force=False,
    )
    assert "--boot-mode" not in command
    assert "direct_flash" not in command
    assert "--runtime-only" not in command


def test_measurement_command_is_runtime_only_and_references_profile_preparation():
    grid_module = _load_module("scripts/network_degradation_grid.py", "network_degradation_grid_command")
    repo_root = Path(__file__).resolve().parents[2]
    command = grid_module._measurement_command(
        repo_root=repo_root,
        profile_path=repo_root / ".pqc-generated-state/network-degradation-grid/case.yaml",
        results_dir=Path("results"),
        preparation_manifest=repo_root / "results/preparation/manifest.json",
    )
    assert "--runtime-only" in command
    assert "--profile-preparation-manifest" in command
    assert "--build-number" not in command
    assert "--force" not in command
    assert "--boot-mode" not in command
    assert "direct_flash" not in command


def test_runtime_only_measurement_does_not_prepare_build_or_flash():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    start = source.index("def _run_runtime_only_measurement(")
    end = source.index("def run_full_baseline_command", start)
    runtime_only = source[start:end]
    assert "execute_build(" not in runtime_only
    assert "execute_flash(" not in runtime_only
    assert "_prepare_dependencies_for_result(" not in runtime_only
    assert "_execute_mqtt_e2e_uart_capture(" in runtime_only


def test_legacy_managed_broker_cleanup_structural_count_remains_three():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert source.count(
        "_collect_and_stop_managed_mqtt_broker(bundle=bundle, repo_root=repo_root, result_dir=result_dir)"
    ) == 3


def test_result_manifest_discovery_supports_progress_result_directory_format(tmp_path):
    grid_module = _load_module(
        "scripts/network_degradation_grid.py",
        "network_degradation_grid_progress_manifest_discovery",
    )
    repo_root = tmp_path
    result_dir = repo_root / "results" / "2026-08-07_006_example"
    result_dir.mkdir(parents=True)
    manifest = result_dir / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")

    lines = [
        "2026-08-07 13:38:35 AEST  [RESULT      ] Result evidence recorded",
        "                       Run ID: 2026-08-07_006_example; directory: results/2026-08-07_006_example",
    ]

    assert grid_module._result_manifest_from_output(
        lines, repo_root=repo_root
    ) == manifest.resolve()


def test_result_manifest_discovery_still_supports_legacy_result_directory_format(tmp_path):
    grid_module = _load_module(
        "scripts/network_degradation_grid.py",
        "network_degradation_grid_legacy_manifest_discovery",
    )
    repo_root = tmp_path
    result_dir = repo_root / "results" / "legacy-run"
    result_dir.mkdir(parents=True)
    manifest = result_dir / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")

    lines = ["Result directory: results/legacy-run"]

    assert grid_module._result_manifest_from_output(
        lines, repo_root=repo_root
    ) == manifest.resolve()


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
        rtt_ms=200, loss_percent=0.0, mtu=1280, management_safe=True,
    )
    script = module._remote_script(config)
    assert 'sudo -n "$TC" qdisc add dev $iface root netem' in script
    assert 'sudo -n "$IP" link set dev $iface mtu 1280' in script
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


def test_grid_has_preflight_command_before_preparation_command():
    grid_module = _load_module("scripts/network_degradation_grid.py", "network_degradation_grid_preflight_order")
    source = Path("scripts/network_degradation_grid.py").read_text(encoding="utf-8")
    preflight_run = source.index("preflight_rc, preflight_output = _run_streamed(preflight_command")
    preparation_run = source.index("preparation_rc, preparation_output = _run_streamed(")
    assert preflight_run < preparation_run
