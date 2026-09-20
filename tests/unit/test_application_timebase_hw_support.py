"""No-hardware coverage for the standalone application-timebase test's evidence checks."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tests" / "hardware" / "test_application_timebase_hw.py"
spec = importlib.util.spec_from_file_location("application_timebase_hw_under_test", MODULE_PATH)
assert spec is not None and spec.loader is not None
hardware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hardware)


def _manifest(run_dir: Path, *, uart_path: str = "uart.log", accepted: bool = True) -> None:
    (run_dir / "manifest.json").write_text(json.dumps({
        "execution_outcome": {
            "status": "completed", "failure_stage": "none", "result": "baseline_run_passed"
        },
        "capture_acceptance": {"accepted": accepted},
        "final_index": {"status": "finalized"},
        "artifacts": [{"role": "diagnostic_uart", "path": uart_path}],
    }), encoding="utf-8")


def test_indexed_uart_requires_completed_accepted_retained_evidence(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    uart = run / "uart.log"
    uart.write_text("firmware marker\n", encoding="utf-8")
    _manifest(run)
    assert hardware._indexed_uart(run) == uart.resolve()
    _manifest(run, accepted=False)
    with pytest.raises(AssertionError, match="not accepted"):
        hardware._indexed_uart(run)
    _manifest(run, uart_path="../outside.log")
    with pytest.raises(AssertionError, match="unsafe"):
        hardware._indexed_uart(run)
    uart.unlink()
    _manifest(run)
    with pytest.raises(AssertionError, match="missing or unsafe"):
        hardware._indexed_uart(run)


def test_indexed_uart_rejects_missing_manifest_or_failed_outcome(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    with pytest.raises(AssertionError, match="missing experiment manifest"):
        hardware._indexed_uart(run)
    _manifest(run)
    manifest_path = run / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["execution_outcome"]["result"] = "baseline_run_failed"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError, match="did not pass"):
        hardware._indexed_uart(run)


def test_setup_failure_retains_logs_and_returncode(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], 7, "build output", "build error"))
    with pytest.raises(AssertionError, match="configure failed"):
        hardware._enable_timebase_self_test(tmp_path)
    setup = tmp_path / "setup"
    assert (setup / "stdout.log").read_text(encoding="utf-8") == "build output"
    assert (setup / "stderr.log").read_text(encoding="utf-8") == "build error"
    assert json.loads((setup / "returncode.json").read_text(encoding="utf-8")) == {"return_code": 7}
    assert "PQC_TIMEBASE_HARDWARE_SELF_TEST=ON" in (setup / "command.json").read_text(encoding="utf-8")


def test_setup_spawn_error_retains_diagnostic(tmp_path, monkeypatch):
    def cannot_start(*args, **kwargs):
        raise OSError("cmake missing")
    monkeypatch.setattr(hardware.subprocess, "run", cannot_start)
    with pytest.raises(AssertionError, match="could not start"):
        hardware._enable_timebase_self_test(tmp_path)
    assert "cmake missing" in (tmp_path / "setup" / "error.log").read_text(encoding="utf-8")


def test_self_test_marker_requires_firmware_derived_microsecond_rate():
    marker = (
        "PQC_TIMEBASE_SELF_TEST delay_ms=10 elapsed_us=10985 "
        "hal_tick_delta_ms=11 timer_input_clock_hz=120000000 "
        "prescaler=119 counter_hz=1000000"
    )
    hardware._assert_self_test_marker(marker)
    with pytest.raises(AssertionError):
        hardware._assert_self_test_marker(marker.replace("counter_hz=1000000", "counter_hz=1000"))


def test_integrity_profile_boot_evidence_requires_valid_integrity_result_and_app_start():
    uart = (
        "[tick=0000000031] wolfBoot integrity valid: 1\n"
        "[tick=0000000041] wolfBoot integrity result: 0\n"
        "[tick=0000000045] wolfBoot authenticity valid: 0\n"
        "[tick=0000000059] stm32-basic_hal1 secure-boot app v0.1.0\n"
    )
    hardware._assert_integrity_profile_boot_evidence(uart)
    with pytest.raises(AssertionError, match="integrity evidence"):
        hardware._assert_integrity_profile_boot_evidence(uart.replace("integrity valid: 1", "integrity valid: 0"))
    with pytest.raises(AssertionError, match="integrity success"):
        hardware._assert_integrity_profile_boot_evidence(uart.replace("integrity result: 0", "integrity result: 1"))
    with pytest.raises(AssertionError, match="application did not start"):
        hardware._assert_integrity_profile_boot_evidence(uart.replace("secure-boot app v0.1.0", "other app"))
    with pytest.raises(AssertionError, match="integrity evidence"):
        hardware._assert_integrity_profile_boot_evidence(
            "wolfBoot verification result: 0\n" + uart.replace("wolfBoot integrity valid: 1", "")
        )
