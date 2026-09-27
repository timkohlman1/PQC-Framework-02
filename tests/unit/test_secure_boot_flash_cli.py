"""Flash-command verdicts using real UART acquisition/parsing and finalization.

Only external flashing and SSH are replaced; no laboratory capability is used.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.uart import CommandExecution, execute_uart_capture
from framework.manifest import build_manifest

ROOT = Path(__file__).resolve().parents[2]
BOOT = "stm32-basic_hal1 boot v0.1.0"
SECURE_BOOT = "stm32-basic_hal1 secure-boot app v0.1.0"
TYPED_UART = "\n".join([
    "wolfBoot timing mailbox version: 8",
    "wolfBoot integrity valid: 1",
    "wolfBoot integrity cycles: 24099087 cycles",
    "wolfBoot integrity result: 0",
    "wolfBoot authenticity valid: 1",
    "wolfBoot authenticity cycles: 3257288 cycles",
    "wolfBoot authenticity result: 0",
    "wolfBoot clock hclk_hz: 80000000",
    BOOT, SECURE_BOOT, "tick",
])


@pytest.fixture
def flash_cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("secure_boot_cli_test", ROOT / "scripts/experiment.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    bundle = {
        "experiment": {
            "id": "test_flash", "boot_crypto": "ecdsa_p256",
            "uart": {"expected_boot_message": BOOT, "expected_secure_boot_message": SECURE_BOOT,
                     "expected_tick_message": "tick"},
        },
        "host": {"id": "test-gateway", "alias": "test-gateway", "user": "test",
                 "uart": {"device": "/dev/test-uart", "baud": 115200}},
        "board": {"id": "test-board"},
        "boot": {"mode": "wolfboot_ecdsa_p256"},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest = build_manifest(bundle, "test_flash")
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(cli, "load_secure_boot_experiment_bundle", lambda *a, **kw: bundle)
    monkeypatch.setattr(cli, "create_result_folder", lambda *a: (tmp_path, manifest))
    monkeypatch.setattr(cli, "repo_root_from_experiment_path", lambda *a: tmp_path)
    monkeypatch.setattr(cli, "_monitor_restart_command", lambda *a: "reset-test-board")
    artifact = SimpleNamespace(artifact_path=tmp_path / "image.bin", artifact_sha256="a" * 64,
                               offset="0x08000000")
    flash = SimpleNamespace(return_code=0, failure_stage="none", failure_reason=None,
                            duration_seconds=1, wolfboot=artifact, signed_application=artifact,
                            log_path=tmp_path / "secure_boot_flash.log")
    monkeypatch.setattr(cli, "execute_secure_boot_flash", lambda **kw: flash)
    before_finalization = {}
    finalize = cli.finalize_run_evidence

    def retain_and_finalize(path):
        before_finalization.update(json.loads(path.read_text()))
        finalize(path)

    monkeypatch.setattr(cli, "finalize_run_evidence", retain_and_finalize)

    def run(outputs=(TYPED_UART,), *, capture_code=124, flash_code=0, options=()):
        flash.return_code = flash_code
        flash.failure_stage = "flash" if flash_code else "none"
        pending = iter(outputs)

        def capture(**kwargs):
            def runner(command, cwd):
                return CommandExecution(command, capture_code, next(pending), "", 1)
            return execute_uart_capture(**kwargs, runner=runner)

        monkeypatch.setattr(cli, "execute_uart_capture", capture)
        args = cli.build_arg_parser().parse_args([
            "flash-secure-boot", "--experiment", str(tmp_path / "case.yaml"),
            "--results-dir", str(tmp_path), *options,
        ])
        code = cli.run_secure_boot_flash_command(args)
        return (code, json.loads(manifest_path.read_text()), before_finalization,
                json.loads((tmp_path / "secure-boot-flash-capture.json").read_text()))

    return run


def test_single_flash_accepts_typed_boot_without_fabricating_benchmark(flash_cli):
    code, final, transient, capture = flash_cli()
    assert code == final["run"]["return_code"] == 0
    assert final["run"]["failure_stage"] == "none"
    assert final["execution_outcome"]["result"] == capture["result"] == "secure_boot_positive_boot_evidence_passed"
    sample = transient["secure_boot_benchmark"]["repeated_run_samples"]["samples"][0]
    assert sample["valid_for_statistics"] is False
    assert sample["verification_cycles"] is None
    assert sample["derived_verification_time_ms"] is None
    assert transient["secure_boot_benchmark"]["aggregate_statistics"]["valid_sample_count"] == 0


@pytest.mark.parametrize("missing", [BOOT, SECURE_BOOT, "tick"])
def test_single_flash_requires_every_boot_marker(flash_cli, missing):
    code, final, _, capture = flash_cli([TYPED_UART.replace(missing, "")])
    assert code == final["run"]["return_code"] == 9
    assert final["run"]["failure_stage"] == "positive_uart_evidence"
    assert capture["result"] == "secure_boot_flash_failed"


@pytest.mark.parametrize("flash_code,capture_code,output,stage,expected", [
    (7, 124, TYPED_UART, "flash", 7),
    (0, 255, TYPED_UART, "uart", 255),
    (0, 124, "", "uart", 10),
])
def test_acquisition_failures_are_not_masked(flash_cli, flash_code, capture_code, output, stage, expected):
    code, final, _, _ = flash_cli([output], flash_code=flash_code, capture_code=capture_code)
    assert code == final["run"]["return_code"] == expected
    assert final["run"]["failure_stage"] == stage


def test_repeated_benchmark_still_requires_timing(flash_cli):
    code, final, transient, capture = flash_cli([TYPED_UART] * 2, options=["--repeat-count", "2"])
    assert code == final["run"]["return_code"] == 9
    assert final["run"]["failure_stage"] == "benchmark_sample"
    assert transient["secure_boot_run"]["positive_boot_evidence_passed"] is True
    assert capture["result"] == final["execution_outcome"]["result"] == "secure_boot_flash_failed"


def test_repeated_benchmark_requires_boot_markers(flash_cli):
    code, final, _, _ = flash_cli([TYPED_UART.replace(BOOT, "")] * 2, options=["--repeat-count", "2"])
    assert code == 9
    assert final["run"]["failure_stage"] == "positive_uart_evidence"


def test_legacy_repeated_benchmark_with_valid_timing_passes(flash_cli):
    uart = "\n".join([BOOT, SECURE_BOOT, "tick", "wolfBoot verification cycles: 80000 cycles",
                      "wolfBoot clock hclk_hz: 80000000", "wolfBoot verification result: 0"])
    code, final, transient, _ = flash_cli([uart] * 2, options=["--repeat-count", "2"])
    assert code == 0
    assert final["execution_outcome"]["result"] == "secure_boot_benchmark_repeated_run_passed"
    assert transient["secure_boot_benchmark"]["aggregate_statistics"]["valid_sample_count"] == 2


def test_skip_uart_only_claims_flashing(flash_cli):
    code, final, _, capture = flash_cli([], options=["--skip-uart"])
    assert code == 0
    assert final["execution_outcome"]["result"] == "secure_boot_flash_passed"
    assert capture["capture_completed"] is False


def test_negative_empty_capture_is_still_accepted(flash_cli):
    code, final, _, capture = flash_cli([""], options=["--negative-corrupt-application"])
    assert code == 0
    assert final["execution_outcome"]["result"] == "secure_boot_negative_test_passed"
    assert capture["negative_passed"] is True
