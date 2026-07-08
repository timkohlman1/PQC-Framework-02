from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_wolfboot_build_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    return importlib.import_module("framework.wolfboot_build")


def sample_profile() -> dict[str, object]:
    return {
        "id": "wolfboot_stm32l4_ecdsa_p256",
        "description": "Test wolfBoot profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "ecdsa_p256",
        "boot_profile": "wolfboot_ecdsa_p256",
        "build": {
            "command": "make",
            "args": "WOLFBOOT_ROOT=. wolfboot.elf",
            "config_template": "configs/wolfboot/stm32l4r5_ecdsa_p256.config",
            "generated_config": "tools/wolfboot/.config",
            "mingw_keytools_ansi_stdio_patch": True,
            "stm32l4_hal_conf_pwr_patch": True,
            "boot_timing_instrumentation_patch": True,
            "signing_key": "secrets/wolfboot/ecdsa_p256_private_key.der",
            "wolfboot_private_key": "tools/wolfboot/wolfboot_signing_private_key.der",
            "generated_keystore": "tools/wolfboot/src/keystore.c",
        },
    }


def write_keytools_makefile(source_dir: Path) -> Path:
    makefile_path = source_dir / "tools" / "keytools" / "Makefile"
    makefile_path.parent.mkdir(parents=True)
    makefile_path.write_text(
        "CFLAGS = -Wall -Wextra -Werror\n"
        "all:\n"
        "\t@echo keytools\n",
        encoding="utf-8",
    )
    return makefile_path


def write_stm32l4_hal_conf(source_dir: Path) -> Path:
    hal_conf_path = source_dir / "hal" / "stm32l4xx_hal_conf.h"
    hal_conf_path.parent.mkdir(parents=True)
    hal_conf_path.write_text(
        "#ifndef __STM32L4xx_HAL_CONF_H\n"
        "#define __STM32L4xx_HAL_CONF_H\n"
        "#define HAL_MODULE_ENABLED\n"
        "#define HAL_CORTEX_MODULE_ENABLED\n"
        "#define HAL_FLASH_MODULE_ENABLED\n"
        "#define HAL_RCC_MODULE_ENABLED\n"
        "#include \"stm32l4xx_hal_def.h\"\n"
        "#if defined(HAL_RCC_MODULE_ENABLED)\n"
        "#include \"stm32l4xx_hal_rcc.h\"\n"
        "#endif\n"
        "#define assert_param(expr) ((void)0U)\n"
        "#endif\n",
        encoding="utf-8",
    )
    return hal_conf_path



def write_wolfboot_image_source(source_dir: Path) -> Path:
    image_path = source_dir / "src" / "image.c"
    image_path.parent.mkdir(parents=True)
    image_path.write_text(
        "#include <stdint.h>\n"
        "#include \"printf.h\"\n"
        "struct wolfBoot_image;\n"
        "#else\n"
        "int wolfBoot_verify_authenticity(struct wolfBoot_image *img)\n"
        "{\n"
        "    (void)img;\n"
        "    return 0;\n"
        "}\n"
        "#endif\n"
        "\n"
        "/**\n"
        " * @brief Peek at the content of the image at a specific offset.\n"
        " */\n",
        encoding="utf-8",
    )
    return image_path


def write_stm32l4_source(source_dir: Path) -> Path:
    hal_path = source_dir / "hal" / "stm32l4.c"
    hal_path.parent.mkdir(parents=True, exist_ok=True)
    hal_path.write_text(
        "#include <stdint.h>\n"
        "/* Assembly helpers */\n"
        "#define DMB() asm volatile (\"dmb\")\n"
        "static void clockconfig(int powersave) { (void)powersave; }\n"
        "void hal_init(void)\n"
        "{\n"
        "    clockconfig(0);\n"
        "}\n",
        encoding="utf-8",
    )
    return hal_path


def test_construct_wolfboot_build_command_uses_profile_scalars():
    wolfboot_build = load_wolfboot_build_module()

    profile = sample_profile()
    profile["build"]["args"] = "TARGET=stm32l4 SIGN=ECC256"

    assert wolfboot_build.construct_wolfboot_build_command(profile) == [
        "make",
        "TARGET=stm32l4",
        "SIGN=ECC256",
    ]


def test_execute_wolfboot_build_applies_project_local_config_and_records_artifact(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    artifact_path = source_dir / "wolfboot.elf"
    config_template_path = repo_root / "configs" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"
    source_dir.mkdir(parents=True)
    makefile_path = write_keytools_makefile(source_dir)
    hal_conf_path = write_stm32l4_hal_conf(source_dir)
    image_source_path = write_wolfboot_image_source(source_dir)
    hal_source_path = write_stm32l4_source(source_dir)
    original_makefile_text = makefile_path.read_text(encoding="utf-8")
    original_hal_conf_text = hal_conf_path.read_text(encoding="utf-8")
    original_image_source_text = image_source_path.read_text(encoding="utf-8")
    original_hal_source_text = hal_source_path.read_text(encoding="utf-8")
    config_template_path.parent.mkdir(parents=True)
    config_template_path.write_text("TARGET=stm32l4\nSIGN=ECC256\nSTM32CUBE=../..\n", encoding="utf-8")
    calls: list[tuple[list[str], Path]] = []

    def fake_runner(command: list[str], cwd: Path):
        calls.append((command, cwd))
        assert (source_dir / ".config").read_text(encoding="utf-8") == config_template_path.read_text(encoding="utf-8")
        patched_makefile = makefile_path.read_text(encoding="utf-8")
        assert "-D__USE_MINGW_ANSI_STDIO=1" in patched_makefile
        patched_hal_conf = hal_conf_path.read_text(encoding="utf-8")
        assert "#define HAL_PWR_MODULE_ENABLED" in patched_hal_conf
        assert "#include \"stm32l4xx_hal_pwr.h\"" in patched_hal_conf
        assert "#include \"stm32l4xx_hal_pwr_ex.h\"" in patched_hal_conf
        patched_image_source = image_source_path.read_text(encoding="utf-8")
        patched_hal_source = hal_source_path.read_text(encoding="utf-8")
        assert "PQC_BOOT_TIMING_MAILBOX_MAGIC" in patched_image_source
        assert "pqc_boot_timing_write_mailbox" in patched_image_source
        assert "elapsed_cycles" in patched_image_source
        assert "verification_result" in patched_image_source
        assert "max_stack_used_bytes" in patched_image_source
        assert "pqc_boot_stack_high_water" in patched_image_source
        assert "PQC_BOOT_STACK_SENTINEL" in patched_image_source
        assert "WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR" in patched_image_source
        assert "wolfBoot_printf" not in patched_image_source
        assert "pqc_boot_timing_uart_write" not in patched_hal_source
        assert "uart_printf" not in patched_hal_source
        artifact_path.write_text("fake wolfboot elf", encoding="utf-8")
        return wolfboot_build.WolfBootCommandExecution(
            command=command,
            return_code=0,
            stdout="wolfBoot build stdout",
            stderr="",
            duration_seconds=0.125,
        )

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
        timestamp=datetime(2026, 6, 29, 10, 30, 0, tzinfo=timezone.utc),
    )

    expected_sha256 = hashlib.sha256(b"fake wolfboot elf").hexdigest()
    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    build_log = result.log_path.read_text(encoding="utf-8")

    assert result.return_code == 0
    assert result.config_applied is True
    assert result.keytools_mingw_stdio_patch_enabled is True
    assert result.keytools_mingw_stdio_patch_applied is True
    assert result.keytools_makefile_path == makefile_path
    assert result.stm32l4_hal_conf_pwr_patch_enabled is True
    assert result.stm32l4_hal_conf_pwr_patch_applied is True
    assert result.stm32l4_hal_conf_path == hal_conf_path
    assert result.boot_timing_instrumentation_patch_enabled is True
    assert result.boot_timing_instrumentation_patch_applied is True
    assert result.boot_timing_image_path == image_source_path
    assert result.boot_timing_hal_path is None
    assert makefile_path.read_text(encoding="utf-8") == original_makefile_text
    assert hal_conf_path.read_text(encoding="utf-8") == original_hal_conf_text
    assert image_source_path.read_text(encoding="utf-8") == original_image_source_text
    assert hal_source_path.read_text(encoding="utf-8") == original_hal_source_text
    assert result.config_template_path == config_template_path
    assert result.generated_config_path == source_dir / ".config"
    assert result.artifact_sha256 == expected_sha256
    assert result.retained_artifact_path == result.result_dir / "wolfboot.elf"
    assert (result.result_dir / "wolfboot.elf").read_text(encoding="utf-8") == "fake wolfboot elf"
    assert calls == [(["make", "WOLFBOOT_ROOT=.", "wolfboot.elf"], source_dir)]
    assert manifest["result"] == "wolfboot_build_passed"
    assert manifest["wolfboot_build"]["config_applied"] is True
    assert manifest["wolfboot_build"]["config_template"] == str(config_template_path)
    assert manifest["wolfboot_build"]["generated_config"] == str(source_dir / ".config")
    assert manifest["wolfboot_build"]["keytools_mingw_stdio_patch_enabled"] is True
    assert manifest["wolfboot_build"]["keytools_mingw_stdio_patch_applied"] is True
    assert manifest["wolfboot_build"]["keytools_makefile"] == str(makefile_path)
    assert manifest["wolfboot_build"]["stm32l4_hal_conf_pwr_patch_enabled"] is True
    assert manifest["wolfboot_build"]["stm32l4_hal_conf_pwr_patch_applied"] is True
    assert manifest["wolfboot_build"]["stm32l4_hal_conf_path"] == str(hal_conf_path)
    assert manifest["wolfboot_build"]["boot_timing_instrumentation_patch_enabled"] is True
    assert manifest["wolfboot_build"]["boot_timing_instrumentation_patch_applied"] is True
    assert manifest["wolfboot_build"]["boot_timing_image_path"] == str(image_source_path)
    assert manifest["wolfboot_build"]["boot_timing_hal_path"] is None
    assert manifest["wolfboot_build"]["fingerprint_status"] == "available"
    assert len(manifest["wolfboot_build"]["fingerprint"]) == 64
    assert manifest["wolfboot_build"]["fingerprint_algorithm"] == "sha256-secure-boot-inputs-v1"
    assert "scripts/framework/wolfboot_build.py" in manifest["wolfboot_build"]["requested_fingerprint_inputs"]
    assert "tools/wolfboot/src/image.c" in manifest["wolfboot_build"]["fingerprint_inputs"]
    assert manifest["artifact"]["sha256"] == expected_sha256
    assert "Project-local config applied: true" in build_log
    assert "Keytools MinGW stdio patch applied: true" in build_log
    assert "STM32L4 HAL config PWR patch applied: true" in build_log
    assert "Boot timing instrumentation patch applied: true" in build_log
    assert "Input fingerprint status: available" in build_log
    assert f"Config template path: {config_template_path}" in build_log
    assert f"Generated config path: {source_dir / '.config'}" in build_log


def test_execute_wolfboot_build_synchronizes_generated_key_to_canonical_path(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    artifact_path = source_dir / "wolfboot.elf"
    config_template_path = repo_root / "configs" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"
    signing_key = repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"
    wolfboot_key = source_dir / "wolfboot_signing_private_key.der"
    source_dir.mkdir(parents=True)
    write_keytools_makefile(source_dir)
    write_stm32l4_hal_conf(source_dir)
    write_wolfboot_image_source(source_dir)
    write_stm32l4_source(source_dir)
    config_template_path.parent.mkdir(parents=True)
    config_template_path.write_text("TARGET=stm32l4\nSIGN=ECC256\nSTM32CUBE=../..\n", encoding="utf-8")

    def fake_runner(command: list[str], cwd: Path):
        wolfboot_key.write_bytes(b"wolfboot generated private key")
        artifact_path.write_text("fake wolfboot elf", encoding="utf-8")
        return wolfboot_build.WolfBootCommandExecution(command, 0, "ok", "", 0.1)

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    expected_key_sha = hashlib.sha256(b"wolfboot generated private key").hexdigest()
    assert result.return_code == 0
    assert signing_key.read_bytes() == b"wolfboot generated private key"
    assert manifest["wolfboot_build"]["signing_key_path"] == str(signing_key)
    assert manifest["wolfboot_build"]["wolfboot_private_key_path"] == str(wolfboot_key)
    assert manifest["wolfboot_build"]["signing_key_sha256"] == expected_key_sha
    assert manifest["wolfboot_build"]["wolfboot_private_key_sha256"] == expected_key_sha
    assert manifest["wolfboot_build"]["key_consistency_status"] == "matched"
    assert manifest["wolfboot_build"]["key_material_copied_to_results"] is False
    assert not (result.result_dir / "ecdsa_p256_private_key.der").exists()


def test_execute_wolfboot_build_rejects_generated_config_outside_source_dir(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "wolfboot").mkdir(parents=True)
    (repo_root / "configs" / "wolfboot").mkdir(parents=True)
    (repo_root / "configs" / "wolfboot" / "stm32l4r5_ecdsa_p256.config").write_text(
        "TARGET=stm32l4\n", encoding="utf-8"
    )
    profile = sample_profile()
    profile["build"]["generated_config"] = "outside.config"

    result = wolfboot_build.execute_wolfboot_build(
        profile=profile,
        repo_root=repo_root,
        results_root=tmp_path / "results",
    )

    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.return_code == wolfboot_build.PROFILE_ERROR_RETURN_CODE
    assert result.config_applied is False
    assert "must be inside the configured source_dir" in result.failure_reason
    assert manifest["result"] == "wolfboot_build_failed"
    assert manifest["wolfboot_build"]["config_applied"] is False


def test_execute_wolfboot_build_records_missing_project_local_config_template(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "wolfboot").mkdir(parents=True)

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
    )

    assert result.return_code == wolfboot_build.PROFILE_ERROR_RETURN_CODE
    assert result.config_applied is False
    assert "config template not found" in result.failure_reason


def test_project_local_wolfboot_config_selects_stm32l4r5_header():
    repo_root = Path(__file__).resolve().parents[2]
    config_path = repo_root / "configs" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"

    config_text = config_path.read_text(encoding="utf-8")

    assert "CFLAGS_EXTRA+=-USTM32L4A6xx" in config_text
    assert "CFLAGS_EXTRA+=-DSTM32L4R5xx" in config_text
    assert "IMAGE_HEADER_SIZE=8192" in config_text
    assert "IMAGE_HEADER_SIZE=0x2000" not in config_text
    assert "CFLAGS_EXTRA+=-DHAL_PWR_MODULE_ENABLED" not in config_text
    assert "CFLAGS_EXTRA+=-include" not in config_text
    assert "CFLAGS_EXTRA+=../../Core/Inc/stm32l4xx_hal_conf.h" not in config_text
    assert "OBJS+=$(STM32CUBE)/Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_pwr.o" in config_text
    assert "OBJS+=$(STM32CUBE)/Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_pwr_ex.o" in config_text
    assert "CFLAGS_EXTRA+=-DWOLFBOOT_PQC_BOOT_TIMING=1" in config_text
    assert "CFLAGS_EXTRA+=-DWOLFBOOT_PQC_BOOT_TIMING_CPU_HZ=80000000UL" in config_text
    assert "CFLAGS_EXTRA+=-DWOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR=0x10000000UL" in config_text
    assert "CFLAGS_EXTRA+=-DDEBUG_UART" not in config_text
    assert "CFLAGS_EXTRA+=-DPRINTF_ENABLED" not in config_text
    assert config_text.index("CFLAGS_EXTRA+=-USTM32L4A6xx") < config_text.index("CFLAGS_EXTRA+=-DSTM32L4R5xx")


def test_default_wolfboot_build_profile_sets_explicit_wolfboot_root():
    wolfboot_build = load_wolfboot_build_module()
    repo_root = Path(__file__).resolve().parents[2]
    profile_path = repo_root / "configs" / "builds" / "wolfboot_stm32l4_ecdsa_p256.yaml"
    profile_text = profile_path.read_text(encoding="utf-8")

    assert 'args: "WOLFBOOT_ROOT=. wolfboot.elf"' in profile_text
    assert "stm32l4_hal_conf_pwr_patch: true" in profile_text
    assert "boot_timing_instrumentation_patch: true" in profile_text
    assert wolfboot_build.construct_wolfboot_build_command({
        "id": "wolfboot_stm32l4_ecdsa_p256",
        "description": "Test wolfBoot profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "ecdsa_p256",
        "boot_profile": "wolfboot_ecdsa_p256",
        "build": {
            "command": "make",
            "args": "WOLFBOOT_ROOT=. wolfboot.elf",
        },
    }) == ["make", "WOLFBOOT_ROOT=.", "wolfboot.elf"]



def test_construct_ed25519_wolfboot_build_command_accepts_profile():
    wolfboot_build = load_wolfboot_build_module()
    profile = sample_profile()
    profile["id"] = "wolfboot_stm32l4_ed25519"
    profile["signature_algorithm"] = "ed25519"
    profile["boot_profile"] = "wolfboot_ed25519"
    profile["build"]["config_template"] = "configs/wolfboot/stm32l4r5_ed25519.config"
    profile["build"]["signing_key"] = "secrets/wolfboot/ed25519_private_key.der"

    command = wolfboot_build.construct_wolfboot_build_command(profile)

    assert command == ["make", "WOLFBOOT_ROOT=.", "wolfboot.elf"]


def test_validate_wolfboot_build_profile_accepts_rsa2048_algorithm():
    wolfboot_build = load_wolfboot_build_module()
    profile = sample_profile()
    profile["id"] = "wolfboot_stm32l4_rsa2048"
    profile["signature_algorithm"] = "rsa2048"
    profile["boot_profile"] = "wolfboot_rsa2048"
    profile["build"]["config_template"] = "configs/wolfboot/stm32l4r5_rsa2048.config"
    profile["build"]["signing_key"] = "secrets/wolfboot/rsa2048_private_key.der"

    wolfboot_build.validate_wolfboot_build_profile(profile)



def test_validate_wolfboot_build_profile_accepts_phase_11_5d_expanded_algorithm():
    wolfboot_build = load_wolfboot_build_module()
    profile = sample_profile()
    profile["id"] = "wolfboot_stm32l4_ecc384"
    profile["signature_algorithm"] = "ecc384"
    profile["boot_profile"] = "wolfboot_ecc384"
    profile["build"]["config_template"] = "configs/wolfboot/stm32l4r5_ecc384.config"
    profile["build"]["signing_key"] = "secrets/wolfboot/ecc384_private_key.der"

    wolfboot_build.validate_wolfboot_build_profile(profile)


def test_validate_wolfboot_build_profile_accepts_mldsa44():
    wolfboot_build = load_wolfboot_build_module()
    profile = sample_profile()
    profile["id"] = "wolfboot_stm32l4_mldsa44"
    profile["signature_algorithm"] = "mldsa44"
    profile["boot_profile"] = "wolfboot_mldsa44"
    profile["build"]["config_template"] = "configs/wolfboot/stm32l4r5_mldsa44.config"

    wolfboot_build.validate_wolfboot_build_profile(profile)


def test_execute_wolfboot_build_removes_stale_host_tool_outputs_before_make(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    artifact_path = source_dir / "wolfboot.elf"
    config_template_path = repo_root / "configs" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"
    source_dir.mkdir(parents=True)
    write_keytools_makefile(source_dir)
    write_stm32l4_hal_conf(source_dir)
    write_wolfboot_image_source(source_dir)
    write_stm32l4_source(source_dir)
    config_template_path.parent.mkdir(parents=True)
    config_template_path.write_text("TARGET=stm32l4\nSIGN=ECC256\nSTM32CUBE=../..\n", encoding="utf-8")

    stale_paths = [
        source_dir / "tools" / "bin-assemble" / "bin-assemble.o",
        source_dir / "tools" / "bin-assemble" / "bin-assemble.exe",
        source_dir / "tools" / "keytools" / "sign.o",
        source_dir / "tools" / "keytools" / "sign.exe",
    ]
    for stale_path in stale_paths:
        stale_path.parent.mkdir(parents=True, exist_ok=True)
        stale_path.write_bytes(b"stale host build output")

    def fake_runner(command: list[str], cwd: Path):
        assert command == ["make", "WOLFBOOT_ROOT=.", "wolfboot.elf"]
        assert cwd == source_dir
        for stale_path in stale_paths:
            assert not stale_path.exists()
        artifact_path.write_text("fake wolfboot elf", encoding="utf-8")
        return wolfboot_build.WolfBootCommandExecution(command, 0, "ok", "", 0.1)

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    assert result.return_code == 0
    for stale_path in stale_paths:
        assert not stale_path.exists()
