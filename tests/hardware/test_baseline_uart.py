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
def test_baseline_known_image_reports_local_lwip_udp_loopback(tmp_path, pqc_require_capabilities):
    """Build, flash, and capture a known image before asserting M6.6 evidence."""

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
    scheduler_marker = "FreeRTOS defaultTask started: periodic tick task active"
    loopback_marker = "lwIP local loopback smoke:"

    assert scheduler_marker in boot_text
    assert loopback_marker in boot_text
    assert boot_text.index(scheduler_marker) < boot_text.index(loopback_marker)
    assert "evidence=stm32-local-lwip-loopback-only" in boot_text
    assert "protocol=udp" in boot_text
    assert "address=127.0.0.1" in boot_text
    assert "result=passed" in boot_text
    assert "sent=1" in boot_text
    assert "received=1" in boot_text
    assert "payload_match=1" in boot_text
    assert "wifi_module=unavailable" in boot_text
    assert "hardware_ip_acquisition=unavailable" in boot_text
    assert "external_ping=unavailable" in boot_text
    assert "external_tcp=unavailable" in boot_text
    assert "tls_handshake=unavailable" in boot_text
    assert "mqtt_connect=unavailable" in boot_text
    assert "mqtt_publish=unavailable" in boot_text
    assert "reconnect=unavailable" in boot_text
    assert "broker_access=unavailable" in boot_text
    assert "end_to_end=unavailable" in boot_text


@pytest.mark.hardware
def test_baseline_known_image_reports_wolfmqtt_fake_no_network_runtime(
    tmp_path, pqc_require_capabilities
):
    """Build, flash, and capture a known image before asserting M8 evidence."""

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
    scheduler_marker = "FreeRTOS defaultTask started: periodic tick task active"
    mqtt_marker = "wolfMQTT runtime smoke:"

    assert scheduler_marker in boot_text
    assert mqtt_marker in boot_text
    assert boot_text.index(scheduler_marker) < boot_text.index(mqtt_marker)
    assert "context=freertos_task" in boot_text
    assert "scheduler=running" in boot_text
    assert "evidence=stm32-fake-no-network-initialization-only" in boot_text
    assert "backend=fake_no_network" in boot_text
    assert "client_initialized=1" in boot_text
    assert "callbacks=present" in boot_text
    assert "transport=unavailable" in boot_text
    assert "wifi=unavailable" in boot_text
    assert "link=unavailable" in boot_text
    assert "ip=unavailable" in boot_text
    assert "tcp=unavailable" in boot_text
    assert "tls_handshake=unavailable" in boot_text
    assert "mqtt_connect=unavailable" in boot_text
    assert "mqtt_publish=unavailable" in boot_text
    assert "reconnect=unavailable" in boot_text
    assert "st67w61m1=unavailable" in boot_text
    assert "end_to_end=unavailable" in boot_text
