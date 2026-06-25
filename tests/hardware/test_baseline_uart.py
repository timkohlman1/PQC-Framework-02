from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

RUN_BASELINE_UART_ENV = "PQC_RUN_BASELINE_UART_HARDWARE"
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
def test_baseline_uart_monitor(tmp_path):
    """Monitor real UART output from the currently running baseline firmware.

    This hardware-dependent test is opt-in. It verifies that the gateway can
    connect to the configured ST-LINK VCP path and capture non-empty UART data.
    It does not require the one-shot boot marker to be present.
    """

    if os.environ.get(RUN_BASELINE_UART_ENV) != "1":
        pytest.skip(f"Set {RUN_BASELINE_UART_ENV}=1 to run the baseline UART hardware test.")

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
