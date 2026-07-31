from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_release_is_default_and_debug_is_cli_selectable():
    build_source = _read("scripts/framework/build.py")
    cli_source = _read("scripts/experiment.py")
    assert 'preset: str = "Release"' in build_source
    assert 'default="Release"' in cli_source
    assert '"--debug"' in cli_source
    assert 'const="Debug"' in cli_source


def test_integrity_profile_is_keyless_sha256_baseline():
    profile = _read("configs/algorithms/integrity_sha256.yaml")
    assert "target: stm32l4r5_wolfboot" in profile
    assert "signature_algorithm: integrity_sha256" in profile
    assert "description: Run the selected experiment through wolfBoot" in profile
    assert "description: Runnable wolfBoot integrity-only baseline" in profile
    assert "runnable: true" in profile
    assert "private_key:" not in profile
    assert "args: --no-sign --sha256 {input_image} {image_version}" in profile
    assert "image_header_size_bytes: 12288" in profile


def test_mldsa87_profile_and_wolfboot_config_are_present():
    profile = _read("configs/algorithms/mldsa87.yaml")
    config = _read("configs/wolfboot/stm32l4r5_mldsa87.config")
    assert "signature_algorithm: mldsa87" in profile
    assert "mldsa_level: 5" in profile
    assert "signature_size_bytes: 4627" in profile
    assert "ML_DSA_LEVEL=5" in config
    assert "IMAGE_SIGNATURE_SIZE=4627" in config
    assert "IMAGE_HEADER_SIZE=12288" in config


def test_wolfboot_stm32l4_mpu_covers_complete_linker_ram():
    repo_root = Path(__file__).resolve().parents[2]
    linker_text = (repo_root / "tools" / "wolfboot" / "hal" / "stm32l4.ld").read_text(encoding="utf-8")
    boot_text = (repo_root / "tools" / "wolfboot" / "src" / "boot_arm.c").read_text(encoding="utf-8")

    assert "RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 0x00018000" in linker_text
    assert "mpu_setattr(2, MPUSIZE_128K" in boot_text
    assert "mpu_setattr(2, MPUSIZE_64K" not in boot_text
