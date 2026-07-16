from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

EXPERIMENT_CONFIG = "configs/experiments/baseline_direct_uart.yaml"
EXPECTED_LWIP_SMOKE_PREFIX = "lwIP runtime smoke:"
EXPECTED_LWIP_NETWORK_BOUNDARY = "network=unavailable"
EXPECTED_ST67_INIT_MARKER = "ST67 SPI bring-up: W6X_Init result=0 status_ok=1"
EXPECTED_ST67_SCAN_MARKER = "ST67 Wi-Fi scan: complete result=passed"
EXPECTED_ST67_SCAN_BOUNDARY = "evidence=stm32-st67-wifi-rf-scan-only"


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


def _run_result_dirs(results_dir: Path) -> list[Path]:
    """Return experiment run result directories, excluding build-record storage."""

    return sorted(
        path
        for path in results_dir.iterdir()
        if path.is_dir() and path.name != "builds"
    )


def _single_result_dir(results_dir: Path) -> Path:
    result_dirs = _run_result_dirs(results_dir)
    assert len(result_dirs) == 1
    return result_dirs[0]


@pytest.mark.integration
def test_lwip_runtime_smoke_marker_appears_in_gateway_uart_log(
    tmp_path,
    pqc_require_capabilities,
):
    """Build, flash, and verify the Phase M5 lwIP UART smoke marker.

    This is a gateway/hardware-facing integration test. It proves only that the
    non-network lwIP helper-call smoke marker executes during the existing UART
    capture window. It does not validate a network interface, ST67W61M1 module
    detection, Wi-Fi association, IP acquisition, TCP, TLS, MQTT, publish, or
    reconnect behaviour.
    """

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        strict_mode="gateway",
    )

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
            "--force",
            "--uart-duration-seconds",
            "10",
        ],
    )

    assert completed.returncode == 0, (
        "Expected the baseline run command to build, flash, capture UART, and pass.\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )

    assert "Baseline run passed" in completed.stdout
    assert "UART log:" in completed.stdout

    result_dir = _single_result_dir(results_dir)
    manifest_path = result_dir / "manifest.json"
    uart_log_path = result_dir / "uart.log"

    assert manifest_path.is_file()
    assert uart_log_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["result"] == "baseline_run_passed"
    assert manifest["run"]["return_code"] == 0
    assert manifest["run"]["flash_return_code"] == 0
    assert manifest["run"]["uart_return_code"] == 0
    assert manifest["run"]["uart_log"] == "uart.log"

    uart_log = uart_log_path.read_text(encoding="utf-8", errors="replace")

    required_markers = (
        "stm32-basic_hal1 boot v0.1.0",
        EXPECTED_LWIP_SMOKE_PREFIX,
        "ip4_format=192.0.2.1",
        "checksum=0x",
        EXPECTED_LWIP_NETWORK_BOUNDARY,
        EXPECTED_ST67_INIT_MARKER,
        EXPECTED_ST67_SCAN_MARKER,
        EXPECTED_ST67_SCAN_BOUNDARY,
        "ssid_values=not-reported",
        "bssid_values=not-reported",
        "wifi_association=not-attempted",
        "FreeRTOS scheduler starting: cmsis_rtos=v2",
        "FreeRTOS defaultTask started: periodic tick task active",
        "tick",
    )

    for marker in required_markers:
        assert marker in uart_log

    assert "network=available" not in uart_log
    assert "wifi_association=passed" not in uart_log
    assert "tls_handshake=passed" not in uart_log
    assert "mqtt_connect=passed" not in uart_log
    assert "end_to_end=passed" not in uart_log
