from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HARDWARE_TEST_PATH = (
    REPO_ROOT / "tests/hardware/test_secure_boot_flash_workflow.py"
)


def _load_hardware_test_module():
    spec = importlib.util.spec_from_file_location(
        "secure_boot_flash_workflow_review",
        HARDWARE_TEST_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secure_boot_profile_and_hardware_test_use_derived_timing_contract():
    experiment_spec = importlib.util.spec_from_file_location(
        "experiment_cli_for_workflow_contract", REPO_ROOT / "scripts/experiment.py"
    )
    assert experiment_spec is not None and experiment_spec.loader is not None
    experiment_cli = importlib.util.module_from_spec(experiment_spec)
    experiment_spec.loader.exec_module(experiment_cli)
    bundle = experiment_cli.load_secure_boot_experiment_bundle(
        REPO_ROOT / "configs/experiments/secure_boot_uart.yaml",
        algorithm="ecdsa_p256",
    )
    profile = bundle["experiment"]
    hardware = HARDWARE_TEST_PATH.read_text(encoding="utf-8")
    expected = "framework_derived_from_uart_cycles_and_reported_hclk"

    assert profile["secure_boot_flash"]["boot_timing_source"] == expected
    assert expected in hardware
    assert "uart_explicit_verification_time_marker" not in hardware


def test_hardware_failure_context_reads_newest_matching_log(tmp_path):
    module = _load_hardware_test_module()
    older = tmp_path / "older" / "wolfboot_build.log"
    newer = tmp_path / "newer" / "wolfboot_build.log"
    older.parent.mkdir()
    newer.parent.mkdir()
    older.write_text("older failure", encoding="utf-8")
    newer.write_text("newer failure", encoding="utf-8")

    # Assign deliberately distinct mtimes so the test validates the
    # implementation's newest-by-mtime contract without depending on the
    # timestamp resolution or scheduling behaviour of the host filesystem.
    older_mtime_ns = 1_700_000_000_000_000_000
    newer_mtime_ns = older_mtime_ns + 1_000_000_000
    os.utime(older, ns=(older_mtime_ns, older_mtime_ns))
    os.utime(newer, ns=(newer_mtime_ns, newer_mtime_ns))

    context = module._result_log_context(
        tmp_path,
        "wolfboot_build.log",
    )

    assert str(newer) in context
    assert "newer failure" in context
    assert "older failure" not in context


def test_secure_boot_result_selection_uses_manifest_semantics(tmp_path):
    module = _load_hardware_test_module()

    build_result = tmp_path / "001_baseline"
    build_result.mkdir()
    (build_result / "manifest.json").write_text(
        json.dumps({"result": "build_passed"}),
        encoding="utf-8",
    )

    secure_boot = tmp_path / "002_secure_boot"
    secure_boot.mkdir()
    (secure_boot / "manifest.json").write_text(
        json.dumps(
            {
                "boot_mode": module.EXPECTED_BOOT_MODE,
                "boot_crypto": module.EXPECTED_BOOT_CRYPTO,
                "secure_boot_flash": {"return_code": 0},
            }
        ),
        encoding="utf-8",
    )

    assert module._secure_boot_result_dirs(tmp_path) == [secure_boot]
