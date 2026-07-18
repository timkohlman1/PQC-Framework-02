from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HARDWARE_TEST_PATH = (
    REPO_ROOT / "tests/hardware/test_secure_boot_flash_workflow.py"
)


def _load_hardware_test_module():
    spec = importlib.util.spec_from_file_location(
        "secure_boot_flash_workflow_for_unit_test",
        HARDWARE_TEST_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secure_boot_result_selection_ignores_provenance_and_helper_results(tmp_path):
    module = _load_hardware_test_module()

    provenance = tmp_path / "2026-07-17_001_baseline_direct_uart"
    provenance.mkdir()
    (provenance / "manifest.json").write_text(
        json.dumps(
            {
                "result": "build_completed",
                "boot_mode": "direct",
            }
        ),
        encoding="utf-8",
    )

    signing = tmp_path / "signing"
    signing.mkdir()
    (signing / "manifest.json").write_text(
        json.dumps({"result": "application_signed"}),
        encoding="utf-8",
    )

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "manifest.json").write_text("{invalid", encoding="utf-8")

    secure_boot = tmp_path / "2026-07-17_002_wolfboot_ecdsa_p256_uart"
    secure_boot.mkdir()
    (secure_boot / "manifest.json").write_text(
        json.dumps(
            {
                "result": "secure_boot_positive_boot_evidence_passed",
                "boot_mode": module.EXPECTED_BOOT_MODE,
                "boot_crypto": module.EXPECTED_BOOT_CRYPTO,
                "secure_boot_flash": {"return_code": 0},
            }
        ),
        encoding="utf-8",
    )

    assert module._secure_boot_result_dirs(tmp_path) == [secure_boot]
    assert module._single_secure_boot_result_dir(tmp_path) == secure_boot


def test_secure_boot_timing_assertions_accept_fractional_milliseconds():
    source = HARDWARE_TEST_PATH.read_text(encoding="utf-8")

    assert (
        'isinstance(manifest["boot_timing"]["derived_verification_time_ms"], '
        '(int, float))'
    ) in source
    assert (
        'isinstance(manifest["uart"]["derived_verification_time_ms"], '
        '(int, float))'
    ) in source
    assert (
        'isinstance(manifest["secure_boot_run"]["derived_verification_time_ms"], '
        '(int, float))'
    ) in source
