"""Source-only regression tests for file-owned T02 UART evidence."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    name = "lwip_t02_hardware_contract"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tests/hardware/test_lwip_runtime_smoke_uart_hw.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _boot(*, ipv4="192.168.1.24", live_ip=None, association="passed",
          dhcp="passed", contradictory="", scan=""):
    if live_ip is None:
        live_ip = ipv4
    return "\n".join((
        "stm32-basic_hal1 boot v0.1.0",
        "[tick=0000000026] ST67 SPI bring-up: complete result=passed",
        scan,
        f"[tick=0000000050] ST67 Wi-Fi association: result={association} ssid=test",
        f"[tick=0000000060] ST67 DHCP: result={dhcp} ipv4={ipv4}",
        "[tick=0000000070] lwIP runtime network: context=freertos_task "
        f"scheduler=running evidence=stm32-st67-t02-live-state network=available "
        f"wifi=connected link=up ip={live_ip}",
        contradictory,
    ))


def test_latest_timestamped_boot_passes_without_old_boot():
    module = _module()
    log = _boot() + "\n" + _boot(ipv4="192.168.1.25")
    boot = module._latest_complete_boot(log)
    assert "ipv4=192.168.1.24" not in boot
    module._assert_t02_network(boot)


def test_rejects_only_old_boot_success():
    module = _module()
    log = _boot() + "\n" + _boot(dhcp="failed")
    with pytest.raises(AssertionError):
        module._assert_t02_network(module._latest_complete_boot(log))


@pytest.mark.parametrize("override", [
    {"ipv4": "0.0.0.0"},
    {"ipv4": "not-an-ip"},
    {"live_ip": "192.168.1.99"},
    {"association": "failed"},
    {"dhcp": "failed"},
    {"contradictory": "network=unavailable"},
])
def test_rejects_invalid_or_contradictory_latest_boot(override):
    module = _module()
    with pytest.raises((AssertionError, ValueError)):
        module._assert_t02_network(module._latest_complete_boot(_boot(**override)))


def test_requires_final_manifest_and_indexed_uart(tmp_path):
    module = _module()
    run = tmp_path / "run"
    run.mkdir()
    (run / "uart.log").write_text(_boot(), encoding="utf-8")
    manifest = {
        "execution_outcome": {"status": "completed", "failure_stage": "none",
                              "result": "baseline_run_passed"},
        "capture_acceptance": {"accepted": True},
        "final_index": {"status": "finalized"},
        "artifacts": [{"role": "diagnostic_uart", "path": "uart.log"}],
    }
    target = run / "manifest.json"
    target.write_text(json.dumps(manifest), encoding="utf-8")
    assert "ST67 DHCP" in module._indexed_uart(run)
    manifest["artifacts"][0]["path"] = "../outside.log"
    target.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError):
        module._indexed_uart(run)
    manifest["artifacts"][0]["path"] = "uart.log"
    manifest["capture_acceptance"]["accepted"] = False
    target.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError):
        module._indexed_uart(run)


def test_network_succeeds_without_optional_scan_diagnostics():
    module = _module()
    module._assert_t02_network(module._latest_complete_boot(_boot(scan="")))


def test_network_succeeds_with_current_best_effort_scan_summary():
    module = _module()
    module._assert_t02_network(module._latest_complete_boot(
        _boot(scan="[tick=0000000040] ST67 Wi-Fi scan summary: result=timeout count=0 configured_ssid_found=0")
    ))


def test_rejects_association_before_spi_initialization():
    module = _module()
    log = _boot().replace(
        "[tick=0000000026] ST67 SPI bring-up: complete result=passed\n", ""
    ) + "\n[tick=0000000099] ST67 SPI bring-up: complete result=passed"
    with pytest.raises(AssertionError):
        module._assert_t02_network(module._latest_complete_boot(log))
