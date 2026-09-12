from pathlib import Path


def test_secure_boot_hardware_uses_runnable_experiment_for_build_provenance():
    repo_root = Path(__file__).resolve().parents[2]
    source = (
        repo_root / "tests/hardware/test_secure_boot_flash_workflow_hw.py"
    ).read_text(encoding="utf-8")

    assert (
        'BUILD_PROVENANCE_EXPERIMENT_CONFIG = '
        '"configs/experiments/baseline_direct_uart.yaml"'
    ) in source
    helper_start = source.index(
        "def _prepare_signed_secure_boot_application"
    )
    helper_end = source.index(
        "\ndef _assert_positive_secure_boot_manifest",
        helper_start,
    )
    helper = source[helper_start:helper_end]
    assert "BUILD_PROVENANCE_EXPERIMENT_CONFIG" in helper
    assert "SECURE_BOOT_EXPERIMENT_CONFIG" not in helper

