from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from framework.config_resolver import ConfigResolver
_BASELINE_ROOT = ConfigResolver(ROOT).materialize_campaign("baseline")
EXPERIMENT_CONFIG = next(iter(sorted((_BASELINE_ROOT / "cases").glob("*.yaml")))).relative_to(ROOT).as_posix()
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


def _single_result_dir(results_dir: Path) -> Path:
    result_dirs = sorted(
        path for path in results_dir.iterdir()
        if path.is_dir() and path.name != "builds"
    )
    assert len(result_dirs) == 1
    return result_dirs[0]


def _latest_complete_boot(log_text: str) -> str:
    marker_index = log_text.rfind(EXPECTED_BOOT_MARKER)
    assert marker_index >= 0
    return log_text[marker_index:]


@pytest.mark.hardware
def test_st67_t02_wifi_link_and_dhcp_live_evidence(
    tmp_path,
    pqc_require_capabilities,
):
    """Build, flash, and validate the normal ST67 T02 startup path end to end."""

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        "uart_device",
        strict_mode="hardware",
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
            "30",
        ],
    )

    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )

    result_dir = _single_result_dir(results_dir)
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    uart_log = (result_dir / "uart.log").read_text(
        encoding="utf-8", errors="replace"
    )
    boot_text = _latest_complete_boot(uart_log)

    assert manifest["result"] == "baseline_run_passed"
    assert "ST67 SPI bring-up: complete result=passed" in boot_text
    assert (
        "ST67 Wi-Fi scan: result=skipped mode=normal "
        "diagnostic_scan=disabled"
    ) in boot_text
    assert "ST67 Wi-Fi association: result=passed" in boot_text
    assert "ST67 DHCP: result=passed" in boot_text
    assert "lwIP runtime network:" in boot_text
    assert "evidence=stm32-st67-t02-live-state" in boot_text
    assert "network=available" in boot_text
    assert "wifi=connected" in boot_text
    assert "link=up" in boot_text
    assert re.search(r"\bip=(?!0\.0\.0\.0\b)(?:\d{1,3}\.){3}\d{1,3}\b", boot_text)
    assert "tick" in boot_text

    live_index = boot_text.index("lwIP runtime network:")
    later_text = boot_text[live_index:]
    for stale_marker in (
        "network=unavailable",
        "wifi=unavailable",
        "link=unavailable",
        "ip=unavailable",
    ):
        assert stale_marker not in later_text

    timeout_lines = [
        line for line in later_text.splitlines()
        if "waiting for spi txn ready timeouted" in line
    ]
    for line in timeout_lines:
        for field in (
            "ready_level=",
            "ready_irq_count=",
            "ready_rising_count=",
            "ready_falling_count=",
            "last_rising_tick=",
            "last_falling_tick=",
            "current_tick=",
            "current_event_bits=",
            "last_task_wake_bits=",
            "last_selected_event=",
            "last_do_xfer_flags=",
            "txbuf_present=",
            "txq_waiting=",
            "tx_enqueue_count=",
            "last_tx_enqueue_tick=",
            "xfer_attempt_count=",
            "xfer_success_count=",
            "last_xfer_tick=",
            "last_xfer_result=",
            "last_pre_ready=",
            "last_post_ready=",
            "ready_before_cs=",
            "ready_after_cs_assert=",
            "last_cs_assert_tick=",
            "last_cs_deassert_tick=",
            "hw_xfer_start_tick=",
            "hw_xfer_done_tick=",
            "hw_xfer_done_count=",
            "hw_wait_result=",
        ):
            assert field in line
        assert re.search(r"ready_level=[01]\b", line)
        irq_count = int(re.search(r"ready_irq_count=(\d+)", line).group(1))
        rising_count = int(re.search(r"ready_rising_count=(\d+)", line).group(1))
        falling_count = int(re.search(r"ready_falling_count=(\d+)", line).group(1))
        assert irq_count == rising_count + falling_count
        assert re.search(r"current_event_bits=0x[0-9a-fA-F]+\b", line)
        assert re.search(r"last_task_wake_bits=0x[0-9a-fA-F]+\b", line)
        assert re.search(r"last_selected_event=0x[0-9a-fA-F]+\b", line)
        assert re.search(r"last_do_xfer_flags=0x[0-9a-fA-F]+\b", line)
        assert re.search(r"txbuf_present=[01]\b", line)
        assert re.search(r"last_pre_ready=[01]\b", line)
        assert re.search(r"last_post_ready=[01]\b", line)
        assert re.search(r"ready_before_cs=[01]\b", line)
        assert re.search(r"ready_after_cs_assert=[01]\b", line)
        assert re.search(r"last_cs_assert_tick=\d+\b", line)
        assert re.search(r"last_cs_deassert_tick=\d+\b", line)
        assert re.search(r"hw_xfer_start_tick=\d+\b", line)
        assert re.search(r"hw_xfer_done_tick=\d+\b", line)
        assert re.search(r"hw_xfer_done_count=\d+\b", line)
        assert re.search(r"hw_wait_result=-?\d+\b", line)
