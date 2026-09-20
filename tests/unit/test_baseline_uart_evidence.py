"""Source-only regression checks for the baseline hardware UART evidence contract."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    name = "baseline_uart_hardware_contract"
    path = ROOT / "tests/hardware/test_baseline_uart_hw.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _boot(association: str = "ST67 Wi-Fi association: result=passed ssid=lab-ap",
          dhcp: str = "ST67 DHCP: result=passed ipv4=192.168.1.24") -> str:
    return "\n".join((
        "ST67 DHCP: result=passed ipv4=0.0.0.0",  # stale pre-reset output
        "stm32-basic_hal1 boot v0.1.0",
        association,
        dhcp,
    ))


def test_selects_only_latest_boot_and_validates_dhcp():
    module = _module()
    boot = module._latest_complete_boot(_boot())
    assert "ipv4=0.0.0.0" not in boot
    assert module._associated_ipv4(boot) == "192.168.1.24"


@pytest.mark.parametrize("association,dhcp", [
    ("ST67 Wi-Fi association: result=failed ssid=lab-ap", "ST67 DHCP: result=passed ipv4=192.168.1.24"),
    ("ST67 Wi-Fi association: result=passed ssid=lab-ap", "ST67 DHCP: result=failed ipv4=192.168.1.24"),
    ("ST67 Wi-Fi association: result=passed ssid=lab-ap", "ST67 DHCP: result=passed ipv4=0.0.0.0"),
    ("ST67 Wi-Fi association: result=passed ssid=lab-ap", "ST67 DHCP: result=passed ipv4=not-an-ip"),
])
def test_rejects_failed_or_invalid_network_evidence(association, dhcp):
    module = _module()
    with (pytest.raises((AssertionError, ValueError))):
        module._associated_ipv4(module._latest_complete_boot(_boot(association, dhcp)))


def test_rejects_absent_latest_boot():
    with pytest.raises(AssertionError, match="missing boot marker"):
        _module()._latest_complete_boot("old unrelated UART output")


def test_uses_only_indexed_retained_uart_and_finalized_manifest(tmp_path):
    module = _module()
    run = tmp_path / "run"
    run.mkdir()
    (run / "uart.log").write_text("retained UART evidence", encoding="utf-8")
    manifest = {
        "execution_outcome": {"status": "completed", "failure_stage": "none", "result": "baseline_run_passed"},
        "capture_acceptance": {"accepted": True},
        "final_index": {"status": "finalized"},
        "artifacts": [{"role": "diagnostic_uart", "path": "uart.log"}],
    }
    assert module._indexed_uart(run, manifest) == (run / "uart.log")
    manifest["artifacts"] = [{"role": "diagnostic_uart", "path": "../other.log"}]
    with pytest.raises(AssertionError):
        module._indexed_uart(run, manifest)
    manifest["artifacts"] = [{"role": "diagnostic_uart", "path": "uart.log"}]
    manifest["capture_acceptance"]["accepted"] = False
    with pytest.raises(AssertionError):
        module._indexed_uart(run, manifest)


def test_timestamped_uart_markers_validate_all_baseline_stages():
    """Real firmware prefixes diagnostics with TIM2 ticks; do not discard them."""
    module = _module()
    old = "[tick=0000000010] ST67 DHCP: result=passed ipv4=0.0.0.0"
    log = "\n".join((
        old,
        "stm32-basic_hal1 boot v0.1.0",
        "[tick=0000000026] lwIP runtime smoke: context=pre_scheduler "
        "scheduler=not_started version=2 ip4_format=192.0.2.1 "
        "checksum=0x1 network=unavailable tls_handshake=unavailable "
        "mqtt_connect=unavailable end_to_end=unavailable",
        "[tick=0000000030] ST67 SPI bring-up: begin "
        "evidence=stm32-st67-gpio-spi-bringup-only wifi_association=not-attempted",
        "[tick=0000000031] ST67 SPI bring-up: W6X_Init begin",
        "[tick=0000000032] ST67 SPI bring-up: W6X_Init result=passed",
        "[tick=0000000033] ST67 SPI bring-up: complete "
        "result=passed transport=spi-module-initialized",
        "[tick=0000000200] ST67 Wi-Fi association: result=passed ssid=lab-ap",
        "[tick=0000000300] ST67 DHCP: result=passed ipv4=192.168.1.24",
        "[tick=0000000310] lwIP runtime network: context=freertos_task "
        "scheduler=running network=available wifi=connected link=up "
        "tcp=available transport=st67-lwip st67w61m1=available",
    ))
    boot = module._latest_complete_boot(log)
    assert old not in boot
    assert boot.splitlines()[1].startswith("lwIP runtime smoke: context=pre_scheduler ")
    assert "[tick=" not in boot
    assert module._associated_ipv4(boot) == "192.168.1.24"
    assert "ST67 SPI bring-up: begin" in boot
    assert "ST67 SPI bring-up: complete" in boot
    assert "lwIP runtime network: context=freertos_task " in boot


def test_latest_boot_does_not_accept_diagnostics_from_earlier_boot():
    module = _module()
    log = "\n".join((
        "stm32-basic_hal1 boot v0.1.0",
        "[tick=0000000020] ST67 DHCP: result=passed ipv4=192.168.1.24",
        "stm32-basic_hal1 boot v0.1.0",
        "[tick=0000000015] ST67 Wi-Fi association: result=passed ssid=lab-ap",
        "[tick=0000000020] ST67 DHCP: result=failed ipv4=0.0.0.0",
    ))
    boot = module._latest_complete_boot(log)
    with pytest.raises(AssertionError, match="missing successful DHCP marker"):
        module._associated_ipv4(boot)
