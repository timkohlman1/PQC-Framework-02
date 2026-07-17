from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXPERIMENT_CONFIG = "configs/experiments/baseline_direct_uart.yaml"
EXPECTED_UART_DEVICE = "/dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02"
EXPECTED_BOOT_MARKER = "stm32-basic_hal1 boot v0.1.0"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_cli(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/experiment.py", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _latest_complete_boot(log_text: str) -> str:
    """Return UART evidence from the most recent captured application boot.

    Gateway capture starts before the reset command so the log can contain a
    tail from the image that was already running. Ordering assertions must be
    scoped to the final boot marker rather than the first marker in the file.
    """

    marker_index = log_text.rfind(EXPECTED_BOOT_MARKER)
    assert marker_index >= 0, f"missing boot marker: {EXPECTED_BOOT_MARKER}"
    return log_text[marker_index:]


def _single_adhoc_log(results_dir: Path) -> Path:
    logs = sorted((results_dir / "adhoc").glob("uart_monitor_*.log"))
    assert len(logs) == 1
    return logs[0]


@pytest.mark.hardware
@pytest.mark.short
def test_baseline_uart_monitor(tmp_path, pqc_require_capabilities):
    """Monitor real UART output from the currently running firmware.

    This hardware-dependent smoke test auto-skips unless the SSH gateway and
    configured ST-LINK VCP UART device are available. It verifies that the
    gateway can connect to the configured ST-LINK VCP path and capture non-empty
    UART data. It intentionally does not require the one-shot boot marker or
    FreeRTOS scheduler markers, because it does not flash a known image before
    capture. Use --pqc-require-hardware to turn missing capability skips into
    failures.
    """

    pqc_require_capabilities("gateway", "uart_device", strict_mode="hardware")

    repo_root = _repo_root()
    results_dir = tmp_path / "results"

    completed = _run_cli(
        repo_root,
        [
            "monitor",
            "--experiment",
            EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
            "--duration-seconds",
            "10",
        ],
    )
    assert completed.returncode == 0, (
        f"monitor stdout:\n{completed.stdout}\nmonitor stderr:\n{completed.stderr}"
    )

    uart_log = _single_adhoc_log(results_dir)
    log_text = uart_log.read_text(encoding="utf-8")

    assert EXPECTED_UART_DEVICE in log_text
    assert "Data captured: true" in log_text
    assert "stdout:" in log_text


def _single_run_uart_log(results_dir: Path) -> Path:
    logs = sorted(results_dir.glob("*/uart.log"))
    assert len(logs) == 1, f"expected one run UART log, found: {logs}"
    return logs[0]


@pytest.mark.hardware
def test_baseline_known_image_reports_pre_scheduler_lwip_smoke(
    tmp_path, pqc_require_capabilities
):
    """Build, flash, and validate the bounded pre-scheduler lwIP smoke line."""

    pqc_require_capabilities("gateway", "uart_device", strict_mode="hardware")
    repo_root = _repo_root()
    results_dir = tmp_path / "results"
    completed = _run_cli(
        repo_root,
        ["run", "--experiment", EXPERIMENT_CONFIG, "--results-dir", str(results_dir)],
    )
    assert completed.returncode == 0, (
        f"run stdout:\n{completed.stdout}\nrun stderr:\n{completed.stderr}"
    )

    boot_text = _latest_complete_boot(
        _single_run_uart_log(results_dir).read_text(encoding="utf-8")
    )
    marker = next(
        line for line in boot_text.splitlines()
        if line.startswith("lwIP runtime smoke: context=pre_scheduler ")
    )
    assert "scheduler=not_started" in marker
    assert "version=" in marker
    assert "ip4_format=192.0.2.1" in marker
    assert "checksum=0x" in marker
    assert "network=unavailable" in marker
    assert "tls_handshake=unavailable" in marker
    assert "mqtt_connect=unavailable" in marker
    assert "end_to_end=unavailable" in marker


@pytest.mark.hardware
def test_baseline_known_image_reports_live_st67_network(
    tmp_path, pqc_require_capabilities
):
    """Build, flash, and validate live ST67 association and DHCP evidence."""

    import ipaddress
    import json

    pqc_require_capabilities("gateway", "uart_device", strict_mode="hardware")
    repo_root = _repo_root()
    results_dir = tmp_path / "results"
    completed = _run_cli(
        repo_root,
        [
            "run",
            "--experiment",
            EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
            "--uart-duration-seconds",
            "30",
        ],
    )
    assert completed.returncode == 0, (
        f"run stdout:\n{completed.stdout}\nrun stderr:\n{completed.stderr}"
    )

    boot_text = _latest_complete_boot(
        _single_run_uart_log(results_dir).read_text(encoding="utf-8")
    )
    live_line = next(
        line for line in boot_text.splitlines()
        if line.startswith("lwIP runtime network: context=freertos_task ")
    )
    assert "scheduler=running" in live_line
    assert "network=available" in live_line
    assert "wifi=connected" in live_line
    assert "link=up" in live_line
    assert "tcp=available" in live_line
    assert "transport=st67-lwip" in live_line
    assert "st67w61m1=available" in live_line

    manifest_path = next(results_dir.glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    network = manifest["network"]
    assert network["association_success"] is True
    assert network["dhcp_success"] is True
    assert network["wifi_association"]["result"] == "passed"
    assert network["wifi_association"]["state"] == "connected"
    assert network["dhcp"]["result"] == "passed"
    assert ipaddress.IPv4Address(network["dhcp"]["ipv4"]) != ipaddress.IPv4Address("0.0.0.0")


@pytest.mark.hardware
def test_baseline_known_image_reports_st67_spi_bringup(
    tmp_path, pqc_require_capabilities
):
    """Build, flash, and capture bounded ST67 GPIO/SPI initialization evidence."""

    pqc_require_capabilities("gateway", "uart_device", strict_mode="hardware")

    repo_root = _repo_root()
    results_dir = tmp_path / "results"
    completed = _run_cli(
        repo_root,
        [
            "run",
            "--experiment",
            EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
        ],
    )
    assert completed.returncode == 0, (
        f"run stdout:\n{completed.stdout}\nrun stderr:\n{completed.stderr}"
    )

    log_text = _single_run_uart_log(results_dir).read_text(encoding="utf-8")
    boot_text = _latest_complete_boot(log_text)

    begin_marker = "ST67 SPI bring-up: begin"
    init_marker = "ST67 SPI bring-up: W6X_Init begin"
    result_marker = "ST67 SPI bring-up: W6X_Init result="
    complete_marker = "ST67 SPI bring-up: complete"

    assert begin_marker in boot_text
    assert init_marker in boot_text
    assert result_marker in boot_text
    assert complete_marker in boot_text
    assert boot_text.index(begin_marker) < boot_text.index(init_marker)
    assert boot_text.index(init_marker) < boot_text.index(result_marker)
    assert boot_text.index(result_marker) < boot_text.index(complete_marker)
    begin_line = next(
        line for line in boot_text.splitlines() if line.startswith(begin_marker)
    )
    complete_line = next(
        line for line in boot_text.splitlines() if line.startswith(complete_marker)
    )
    assert "evidence=stm32-st67-gpio-spi-bringup-only" in begin_line
    assert "wifi_association=not-attempted" in begin_line
    assert "result=passed" in complete_line
    assert "transport=spi-module-initialized" in complete_line


@pytest.mark.hardware
def test_baseline_known_image_joins_ap_and_gets_dhcp(tmp_path, pqc_require_capabilities):
    import ipaddress, json
    pqc_require_capabilities("gateway", "uart_device", strict_mode="hardware")
    repo_root=_repo_root(); results_dir=tmp_path/"results"
    completed=_run_cli(repo_root,["run","--experiment",EXPERIMENT_CONFIG,"--results-dir",str(results_dir),"--uart-duration-seconds","30"])
    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    boot_text=_latest_complete_boot(_single_run_uart_log(results_dir).read_text(encoding="utf-8"))
    manifest_path = next(results_dir.glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    association = manifest["network"]["wifi_association"]
    association_line = next(
        line for line in boot_text.splitlines()
        if line.startswith("ST67 Wi-Fi association: result=passed ssid=")
    )
    assert f"ssid={association['ssid']}" in association_line
    line = next(
        line for line in boot_text.splitlines()
        if line.startswith("ST67 DHCP: result=passed ipv4=")
    )
    ipv4 = line.split("ipv4=", 1)[1].split(" ", 1)[0]
    assert ipaddress.IPv4Address(ipv4) != ipaddress.IPv4Address("0.0.0.0")
    assert manifest["network"]["association_success"] is True
    assert manifest["network"]["dhcp_success"] is True
    assert manifest["network"]["dhcp"]["ipv4"] == ipv4
    assert "psk" not in manifest["network"]
