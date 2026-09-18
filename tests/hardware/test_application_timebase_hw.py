from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.config_resolver import ConfigResolver


pytestmark = [pytest.mark.hardware, pytest.mark.long]

TEST_GENERATED_ROOT = ROOT / ".pqc-generated-state" / "hardware-tests" / "request13-timebase"
CMAKE_CACHE = ROOT / "build" / "Release" / "CMakeCache.txt"
MARKER_RE = re.compile(
    r"PQC_TIMEBASE_SELF_TEST delay_ms=(?P<delay>\d+) "
    r"elapsed_us=(?P<elapsed>\d+) hal_tick_delta_ms=(?P<hal_ms>\d+) "
    r"timer_input_clock_hz=(?P<input_hz>\d+) prescaler=(?P<prescaler>\d+) "
    r"counter_hz=(?P<counter_hz>\d+)"
)


def _clean_subprocess_env() -> dict[str, str]:
    """Return a deterministic environment for the self-contained hardware run."""

    env = os.environ.copy()
    # The test owns its complete lifecycle. Retained-log replay and unrelated
    # hardware-test selectors must not alter its behaviour.
    env.pop("PQC_TIMEBASE_UART_LOG", None)
    env.pop("PQC_TEST_RESULT_DIR", None)
    env["PQC_BUILD_PURPOSE"] = "experiment"
    return env


def _run_setup_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_clean_subprocess_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    return completed


def _materialize_timebase_case() -> Path:
    """Resolve a fresh wolfBoot-enabled baseline case for Request 13 validation."""

    resolver = ConfigResolver(ROOT)
    _, campaign = resolver.load_campaign("baseline")
    choices = dict(campaign["fixed"])
    # Keep the self-test on the maintained baseline path used by the Request 13
    # implementation: wolfBoot integrity verification plus Ready Metrics.
    choices["secure_boot"] = "integrity_sha256"

    selections = {
        "target": campaign["target"],
        "gateway": campaign["gateway"],
        "services": dict(campaign["services"]),
        "workload": campaign["workload"],
    }
    if campaign.get("instruments"):
        selections["instruments"] = campaign["instruments"]

    case = resolver.resolve_case(
        campaign_id="request13_timebase_hardware",
        case_index=1,
        selections=selections,
        choices=choices,
        workload_overrides={},
        execution=dict(campaign["execution"]),
    )

    cases_dir = TEST_GENERATED_ROOT / "cases"
    shutil.rmtree(TEST_GENERATED_ROOT, ignore_errors=True)
    cases_dir.mkdir(parents=True, exist_ok=True)
    case_path = cases_dir / "0001_request13_timebase_hardware.yaml"
    case_path.write_text(yaml.safe_dump(case, sort_keys=False), encoding="utf-8")
    return case_path


def _enable_timebase_self_test() -> None:
    """Prime the isolated Release cache with the opt-in firmware self-test."""

    _run_setup_command(
        [
            "cmake",
            "--preset",
            "Release",
            "-DPQC_TIMEBASE_HARDWARE_SELF_TEST=ON",
        ]
    )


def _run_hardware_case(case: Path, results_dir: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    command = [
        sys.executable,
        "scripts/experiment.py",
        "run",
        "--experiment",
        str(case),
        "--results-dir",
        str(results_dir),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_clean_subprocess_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    manifests = sorted(results_dir.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime_ns)
    assert manifests, completed.stdout + "\n" + completed.stderr
    return completed, manifests[-1]


def _uart_text(manifest_path: Path) -> str:
    uart_path = manifest_path.parent / "uart.log"
    assert uart_path.is_file(), f"missing UART evidence: {uart_path}"
    return uart_path.read_text(encoding="utf-8", errors="replace")


def _assert_self_test_marker(text: str) -> None:
    match = MARKER_RE.search(text)
    assert match is not None, "PQC_TIMEBASE_SELF_TEST marker was not captured"

    delay_ms = int(match.group("delay"))
    elapsed_us = int(match.group("elapsed"))
    hal_ms = int(match.group("hal_ms"))
    input_hz = int(match.group("input_hz"))
    prescaler = int(match.group("prescaler"))
    counter_hz = int(match.group("counter_hz"))

    assert delay_ms == 10
    # HAL_Delay(10) is scheduler/interrupt based. A +/-20% window is wider than
    # timer quantisation and normal interrupt latency while still proving that
    # the dedicated microsecond source is not just the 1 ms HAL tick.
    assert 8_000 <= elapsed_us <= 12_000
    assert 9 <= hal_ms <= 12
    assert input_hz > 0
    assert input_hz % (prescaler + 1) == 0
    assert input_hz // (prescaler + 1) == 1_000_000
    assert counter_hz == 1_000_000


def _assert_self_test_remained_enabled() -> None:
    assert CMAKE_CACHE.is_file(), f"missing Release CMake cache: {CMAKE_CACHE}"
    cache = CMAKE_CACHE.read_text(encoding="utf-8", errors="replace")
    assert "PQC_TIMEBASE_HARDWARE_SELF_TEST:BOOL=ON" in cache


@pytest.fixture(scope="module")
def timebase_test_workspace(tmp_path_factory):
    # scripts/dev.sh pytest-hardware overlays /workspace/build and
    # /workspace/.pqc-generated-state with anonymous Docker volumes. This test
    # therefore owns fresh build/generated state without modifying host state.
    root = tmp_path_factory.mktemp("request13-timebase-self-contained")
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(TEST_GENERATED_ROOT, ignore_errors=True)


@pytest.mark.hardware
@pytest.mark.long
def test_application_timebase_known_delay_and_hal_tick_unchanged(
    pqc_require_capabilities,
    timebase_test_workspace: Path,
):
    """Build, flash, execute and validate the Request 13 1 MHz self-test."""

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        "uart_device",
        strict_mode="hardware",
    )

    case = _materialize_timebase_case()
    _enable_timebase_self_test()
    completed, manifest_path = _run_hardware_case(case, timebase_test_workspace / "results")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_self_test_remained_enabled()

    uart = _uart_text(manifest_path)
    assert "wolfBoot verification result: 0" in uart, "wolfBoot verification success not captured"
    assert "stm32-basic_hal1 secure-boot app v0.1.0" in uart, "secure-boot application did not start"
    _assert_self_test_marker(uart)
