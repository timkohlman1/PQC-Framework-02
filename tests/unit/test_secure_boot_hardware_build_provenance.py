from pathlib import Path


def test_secure_boot_hardware_build_uses_own_baseline_case_for_provenance():
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "tests/hardware/test_secure_boot_flash_workflow_hw.py").read_text(encoding="utf-8")
    assert 'context.case(template="baseline", case_name="build_provenance")' in source
    helper = source.split("def _prepare_signed_secure_boot_application", 1)[1].split(
        "\ndef _assert_positive_secure_boot_manifest", 1
    )[0]
    assert 'str(build_case)' in helper
    assert '"--experiment"' in helper
    assert '_RESOLVER.materialize_campaign(' not in source
    assert '_clean_secure_boot_generated_outputs(' not in source
