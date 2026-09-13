from __future__ import annotations

import ipaddress
import json
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
    """Build, flash, and verify bounded pre-scheduler and live ST67 evidence."""

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
            "30",
        ],
    )

    assert completed.returncode == 0, (
        "Expected the baseline run command to build, flash, capture UART, and pass.\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )

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

    network = manifest["network"]
    assert network["association_success"] is True
    assert network["dhcp_success"] is True
    assert network["wifi_association"]["result"] == "passed"
    assert network["wifi_association"]["state"] == "connected"
    assert network["dhcp"]["result"] == "passed"
    assert ipaddress.IPv4Address(network["dhcp"]["ipv4"]) != ipaddress.IPv4Address("0.0.0.0")

    uart_log = uart_log_path.read_text(encoding="utf-8", errors="replace")
    pre_scheduler_line = next(
        line for line in uart_log.splitlines()
        if line.startswith("lwIP runtime smoke: context=pre_scheduler ")
    )
    assert "scheduler=not_started" in pre_scheduler_line
    assert "network=unavailable" in pre_scheduler_line
    assert "ip4_format=192.0.2.1" in pre_scheduler_line
    assert "checksum=0x" in pre_scheduler_line

    assert "ST67 SPI bring-up: W6X_Init result=0 status_ok=1" in uart_log
    assert "ST67 SPI bring-up: complete result=passed" in uart_log
    assert "ST67 Wi-Fi scan: result=skipped mode=normal diagnostic_scan=disabled" in uart_log
    assert "ST67 Wi-Fi association: result=passed" in uart_log
    assert "ST67 DHCP: result=passed" in uart_log

    live_line = next(
        line for line in uart_log.splitlines()
        if line.startswith("lwIP runtime network: context=freertos_task ")
    )
    assert "scheduler=running" in live_line
    assert "network=available" in live_line
    assert "wifi=connected" in live_line
    assert "link=up" in live_line
    assert f"ip={network['dhcp']['ipv4']}" in live_line
    assert "tcp=available" in live_line
    assert "transport=st67-lwip" in live_line
    assert "st67w61m1=available" in live_line

    assert "tls_handshake=passed" not in live_line
    assert "mqtt_connect=passed" not in live_line
    assert "end_to_end=passed" not in live_line
