from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXPERIMENT_CONFIG = "configs/experiments/baseline_direct_uart.yaml"
EXPECTED_UART_DEVICE = "/dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02"


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
