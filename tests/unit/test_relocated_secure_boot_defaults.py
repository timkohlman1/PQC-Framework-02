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
    import yaml
    profile = yaml.safe_load(_read("configs/secure_boot/integrity_sha256.yaml"))
    target = yaml.safe_load(_read("configs/targets/stm32l4r5_st67.yaml"))
    assert profile["id"] == "integrity_sha256"
    assert profile["wolfboot"]["config"]["SIGN"] == "NONE"
    assert profile["wolfboot"]["packaging_option"] == "--no-sign --sha256"
    assert profile["signing"]["requires_private_key"] is False
    assert profile["signature_size_bytes"] == 0
    assert target["wolfboot"]["image_header_size_bytes"] == 12288


def test_mldsa87_profile_and_generated_wolfboot_config_are_present():
    import sys
    import yaml
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "scripts"))
    from framework.config_resolver import render_wolfboot_config
    profile = yaml.safe_load(_read("configs/secure_boot/mldsa87.yaml"))
    target = yaml.safe_load(_read("configs/targets/stm32l4r5_st67.yaml"))
    config = render_wolfboot_config(target, profile)
    assert profile["id"] == "mldsa87"
    assert profile["wolfboot"]["config"]["ML_DSA_LEVEL"] == 5
    assert profile["signature_size_bytes"] == 4627
    assert "ML_DSA_LEVEL=5" in config
    assert "IMAGE_SIGNATURE_SIZE=4627" in config
    assert "IMAGE_HEADER_SIZE=12288" in config


def test_wolfboot_stm32l4_linker_declares_complete_ram():
    repo_root = Path(__file__).resolve().parents[2]
    linker_text = (repo_root / "tools" / "wolfboot" / "hal" / "stm32l4.ld").read_text(encoding="utf-8")

    assert "RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 0x00018000" in linker_text
