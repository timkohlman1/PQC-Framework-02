"""Independent hardware validation of the application TIM2 timebase.

The framework owns building, signing, flashing, reset and UART collection. This
module owns its baseline case, opt-in CMake setup and persistent test evidence.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
import sys

SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.hardware_test_support import HardwareFileRun, session_result_dir


pytestmark = [pytest.mark.hardware, pytest.mark.long]
CMAKE_CACHE = ROOT / "build" / "Release" / "CMakeCache.txt"
MARKER_RE = re.compile(
    r"PQC_TIMEBASE_SELF_TEST delay_ms=(?P<delay>\d+) "
    r"elapsed_us=(?P<elapsed>\d+) hal_tick_delta_ms=(?P<hal_ms>\d+) "
    r"timer_input_clock_hz=(?P<input_hz>\d+) prescaler=(?P<prescaler>\d+) "
    r"counter_hz=(?P<counter_hz>\d+)"
)


def _clean_subprocess_env() -> dict[str, str]:
    """Prevent unrelated test-only selectors from influencing this run."""
    env = os.environ.copy()
    env.pop("PQC_TIMEBASE_UART_LOG", None)
    env.pop("PQC_TEST_RESULT_DIR", None)
    env["PQC_BUILD_PURPOSE"] = "experiment"
    return env


def _enable_timebase_self_test(evidence_root: Path) -> None:
    """Configure the opt-in firmware check and keep setup logs on failure."""
    setup = evidence_root / "setup"
    setup.mkdir(parents=True, exist_ok=False)
    command = ["cmake", "--preset", "Release", "-DPQC_TIMEBASE_HARDWARE_SELF_TEST=ON"]
    (setup / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
    try:
        completed = subprocess.run(
            command, cwd=ROOT, env=_clean_subprocess_env(), text=True,
            encoding="utf-8", errors="replace", capture_output=True, check=False,
        )
    except OSError as exc:
        (setup / "error.log").write_text(str(exc) + "\n", encoding="utf-8")
        raise AssertionError(f"timebase configure could not start; retained evidence: {setup}") from exc
    (setup / "stdout.log").write_text(completed.stdout, encoding="utf-8")
    (setup / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    (setup / "returncode.json").write_text(
        json.dumps({"return_code": completed.returncode}, indent=2) + "\n", encoding="utf-8"
    )
    assert completed.returncode == 0, f"timebase configure failed; retained evidence: {setup}"
    _assert_self_test_remained_enabled()


def _assert_self_test_remained_enabled() -> None:
    assert CMAKE_CACHE.is_file(), f"missing Release CMake cache: {CMAKE_CACHE}"
    cache = CMAKE_CACHE.read_text(encoding="utf-8", errors="replace")
    assert "PQC_TIMEBASE_HARDWARE_SELF_TEST:BOOL=ON" in cache


def _indexed_uart(run_dir: Path) -> Path:
    """Require a completed framework run and its indexed diagnostic UART file."""
    manifest_path = run_dir / "manifest.json"
    assert manifest_path.is_file(), f"missing experiment manifest: {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    outcome = manifest.get("execution_outcome", {})
    assert outcome.get("status") == "completed", f"experiment not completed: {run_dir}"
    assert outcome.get("failure_stage") == "none", f"experiment failure stage: {run_dir}"
    assert outcome.get("result") == "baseline_run_passed", f"experiment did not pass: {run_dir}"
    assert manifest.get("capture_acceptance", {}).get("accepted") is True, f"UART capture not accepted: {run_dir}"
    assert manifest.get("final_index", {}).get("status") == "finalized", f"evidence index not finalized: {run_dir}"
    artifacts = [entry for entry in manifest.get("artifacts", []) if entry.get("role") == "diagnostic_uart"]
    assert len(artifacts) == 1, f"expected one indexed UART artifact: {run_dir}"
    relative = artifacts[0].get("path")
    assert isinstance(relative, str) and relative and not Path(relative).is_absolute(), f"invalid UART artifact path: {relative!r}"
    uart = (run_dir / relative).resolve()
    assert uart.is_relative_to(run_dir.resolve()) and uart.is_file(), f"missing or unsafe indexed UART artifact: {uart}"
    return uart


def _assert_integrity_profile_boot_evidence(text: str) -> None:
    """Require the integrity profile's measured boot result and application startup."""
    assert "wolfBoot integrity valid: 1" in text, "wolfBoot integrity evidence not valid or not captured"
    assert "wolfBoot integrity result: 0" in text, "wolfBoot integrity success not captured"
    assert "stm32-basic_hal1 secure-boot app v0.1.0" in text, "secure-boot application did not start"


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
    # HAL_Delay is interrupt/scheduler-based; allow documented timing margin.
    assert 8_000 <= elapsed_us <= 12_000
    assert 9 <= hal_ms <= 12
    assert input_hz > 0
    assert input_hz % (prescaler + 1) == 0
    assert input_hz // (prescaler + 1) == 1_000_000
    assert counter_hz == 1_000_000


def test_application_timebase_known_delay_and_hal_tick_unchanged(
    pqc_require_capabilities, pytestconfig,
):
    """Build and run this module's own wolfBoot-enabled baseline firmware."""
    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware"
    )
    context = HardwareFileRun.create(
        repo_root=ROOT,
        session_result_dir=session_result_dir(pytestconfig),
        module_name="test_application_timebase_hw",
    )
    case = context.case(template="baseline", case_name="timebase")
    _enable_timebase_self_test(context.evidence_root)
    run_dir, _ = context.run_experiment(case=case, name="experiment")
    _assert_self_test_remained_enabled()
    uart = _indexed_uart(run_dir).read_text(encoding="utf-8", errors="replace")
    _assert_integrity_profile_boot_evidence(uart)
    _assert_self_test_marker(uart)
