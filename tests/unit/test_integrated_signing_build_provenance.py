from pathlib import Path


def test_integrated_secure_boot_signing_uses_immediately_preceding_build_hash():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")

    assert (
        'expected_input_elf_sha256=getattr(build_result, "firmware_sha256", None)'
        in source
    )


def test_signing_prefers_invocation_local_elf_hash_over_global_generated_state():
    source = Path("scripts/framework/signing.py").read_text(encoding="utf-8")

    assert "expected_input_elf_sha256: str | None = None" in source
    assert "actual_input_elf_sha256 = calculate_file_sha256(input_elf_path)" in source
    assert "actual_input_elf_sha256 != expected_input_elf_sha256" in source
    assert "else:\n            input_scope =" in source


def test_standalone_signing_retains_recorded_artifact_validation_fallback():
    source = Path("scripts/framework/signing.py").read_text(encoding="utf-8")

    assert "require_recorded_artifact(" in source
    assert 'scope=input_scope' in source
    assert 'artifact_path=input_elf_path' in source
