from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_wolfboot_build_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    return importlib.import_module("framework.wolfboot_build")




def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    return importlib.import_module("experiment")


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
            "config_template": "testdata/wolfboot/stm32l4r5_ecdsa_p256.config",
            "generated_config": "tools/wolfboot/.config",
            "mingw_keytools_ansi_stdio_patch": True,
            "stm32l4_hal_conf_pwr_patch": True,
            "boot_timing_instrumentation_patch": True,
            "signing_key": "secrets/wolfboot/ecdsa_p256_private_key.der",
            "wolfboot_private_key": "tools/wolfboot/wolfboot_signing_private_key.der",
            "generated_keystore": "tools/wolfboot/src/keystore.c",
        },
    }


def install_fake_objcopy(monkeypatch, wolfboot_build) -> None:
    original_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if command[:3] == ["arm-none-eabi-objcopy", "-O", "binary"]:
            Path(command[-1]).write_bytes(b"fake wolfboot binary")
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="",
                stderr="",
            )
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(wolfboot_build.subprocess, "run", fake_run)


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
        "int wolfBoot_verify_integrity(struct wolfBoot_image *img)\n"
        "{\n"
        "    (void)img;\n"
        "    return 0;\n"
        "}\n"
        "#ifdef WOLFBOOT_ELF_FLASH_SCATTER\n"
        "#endif\n"
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
        "#if defined(DEBUG_UART) && defined(WOLFBOOT_PQC_UART_DIAGNOSTICS)\n"
        "    uart_init();\n"
        "    wolfBoot_printf(\"PQC_WOLFBOOT_DIAG event=bootloader_uart_ready\\n\");\n"
        "#endif\n"
        "}\n"
        "void hal_prepare_boot(void)\n"
        "{\n"
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




def test_default_wolfboot_runner_tolerates_non_utf8_build_output(monkeypatch, tmp_path):
    wolfboot_build = load_wolfboot_build_module()

    def fake_run(command, cwd, text, capture_output, check):
        assert command == ["make", "wolfboot.elf"]
        assert cwd == tmp_path
        assert text is False
        assert capture_output is True
        assert check is False
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=b"build output before invalid byte: \x86\n",
            stderr=b"warning before invalid byte: \x86\n",
        )

    monkeypatch.setattr(wolfboot_build.subprocess, "run", fake_run)

    execution = wolfboot_build.default_wolfboot_runner(["make", "wolfboot.elf"], tmp_path)

    assert execution.return_code == 0
    assert "build output before invalid byte" in execution.stdout
    assert "warning before invalid byte" in execution.stderr
    assert "�" in execution.stdout
    assert "�" in execution.stderr

def test_execute_wolfboot_build_applies_project_local_config_and_records_artifact(tmp_path, monkeypatch):
    wolfboot_build = load_wolfboot_build_module()
    install_fake_objcopy(monkeypatch, wolfboot_build)
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    artifact_path = source_dir / "wolfboot.elf"
    config_template_path = repo_root / "testdata" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"
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
        assert "PQC_BOOT_TIMING_WRAPPER_V3" in patched_image_source
        assert "PQC_BOOT_INTEGRITY_WRAPPER_V4" in patched_image_source
        assert "wolfBoot_verify_integrity_impl" in patched_image_source
        assert "pqc_boot_timing_verification_start" in patched_image_source
        assert "pqc_boot_timing_verification_finish" in patched_image_source
        assert "pqc_boot_timing_write_mailbox" not in patched_image_source
        assert "pqc_boot_timing_image_start(start_cycles, img);" in patched_image_source
        assert "pqc_boot_timing_image_finish(end_cycles, ret, img);" in patched_image_source
        assert "pqc_boot_timing_select_image(struct wolfBoot_image *img)" in patched_hal_source
        assert "mailbox->selected_image_valid = 1U;" in patched_hal_source
        assert "mailbox->image_verification_valid = 1U;" in patched_hal_source
        assert "PQC_BOOT_RESET_ORIGIN_V3" in patched_hal_source
        assert "PQC_BOOT_TIMING_MAILBOX_VERSION 8UL" in patched_hal_source
        assert "void pqc_boot_timing_verification_finish(uint32_t elapsed_cycles, int verification_result," in patched_hal_source
        assert "mailbox->authenticity_cycles = elapsed_cycles;" in patched_hal_source
        assert "#define PQC_BOOT_SIGNATURE_ALGORITHM_ID 2UL" in patched_hal_source
        assert "mailbox->signature_algorithm_id = PQC_BOOT_SIGNATURE_ALGORITHM_ID;" in patched_hal_source
        assert "pqc_boot_reset_origin_start" in patched_hal_source
        assert "pqc_boot_reset_origin_clock_ready" in patched_hal_source
        assert "pqc_boot_timing_prepare_handoff" in patched_hal_source
        assert "pqc_boot_reset_origin_valid" in patched_hal_source
        assert "LPTIM2" in patched_hal_source
        assert "RCC_LPTIM2CLKSOURCE_HSI" in patched_hal_source
        assert "PQC_BOOT_HANDOFF_BRIDGE_HZ 1000000UL" in patched_hal_source
        assert "pqc_boot_bridge_start(uint32_t *counter_start_cycle)" in patched_hal_source
        assert "*counter_start_cycle = PQC_BOOT_DWT_CYCCNT" in patched_hal_source
        assert "reset_origin_to_handoff_us_low" in patched_hal_source
        assert "handoff_bridge_status" in patched_hal_source
        assert "elapsed_cycles" in patched_hal_source
        assert "verification_result" in patched_hal_source
        assert "max_stack_used_bytes" in patched_hal_source
        assert "PQC_BOOT_STACK_UNAVAILABLE" in patched_hal_source
        assert "wolfBoot_printf" not in patched_image_source
        assert "pqc_boot_timing_uart_write" not in patched_hal_source
        assert "uart_printf" not in patched_hal_source
        hal_init_start = patched_hal_source.index("void hal_init(void)")
        origin_start = patched_hal_source.index("pqc_boot_reset_origin_start();", hal_init_start)
        clockconfig = patched_hal_source.index("clockconfig(0);", hal_init_start)
        clock_ready = patched_hal_source.index("pqc_boot_reset_origin_clock_ready();", hal_init_start)
        assert origin_start < clockconfig < clock_ready
        prepare_start = patched_hal_source.index("void hal_prepare_boot(void)")
        assert patched_hal_source.index("pqc_boot_timing_prepare_handoff();", prepare_start) > prepare_start
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
    assert result.boot_timing_hal_path == hal_source_path
    assert makefile_path.read_text(encoding="utf-8") == original_makefile_text
    assert hal_conf_path.read_text(encoding="utf-8") == original_hal_conf_text
    assert image_source_path.read_text(encoding="utf-8") == original_image_source_text
    assert hal_source_path.read_text(encoding="utf-8") == original_hal_source_text
    assert result.config_template_path == config_template_path
    assert result.generated_config_path == source_dir / ".config"
    assert result.artifact_sha256 == expected_sha256
    assert result.retained_artifact_path == result.result_dir / "wolfboot.elf"
    assert (result.result_dir / "wolfboot.elf").read_text(encoding="utf-8") == "fake wolfboot elf"
    assert (result.result_dir / "wolfboot.bin").read_bytes() == b"fake wolfboot binary"
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
    assert manifest["wolfboot_build"]["boot_timing_hal_path"] == str(hal_source_path)
    assert manifest["wolfboot_build"]["fingerprint_status"] == "available"
    assert len(manifest["wolfboot_build"]["fingerprint"]) == 64
    assert manifest["wolfboot_build"]["fingerprint_algorithm"] == "sha256-secure-boot-inputs-v1"
    assert "scripts/framework/wolfboot_build.py" in manifest["wolfboot_build"]["requested_fingerprint_inputs"]
    assert "tools/wolfboot/src/image.c" in manifest["wolfboot_build"]["fingerprint_inputs"]
    assert list(manifest["wolfboot_build"]["fingerprint_file_hashes"]) == manifest["wolfboot_build"]["fingerprint_inputs"]
    assert manifest["artifact"]["sha256"] == expected_sha256
    assert "Project-local config applied: true" in build_log
    assert "Keytools MinGW stdio patch applied: true" in build_log
    assert "STM32L4 HAL config PWR patch applied: true" in build_log
    assert "Boot timing instrumentation patch applied: true" in build_log
    assert "Input fingerprint status: available" in build_log
    assert f"Config template path: {config_template_path}" in build_log
    assert f"Generated config path: {source_dir / '.config'}" in build_log


def test_execute_wolfboot_build_synchronizes_generated_key_to_canonical_path(tmp_path, monkeypatch):
    wolfboot_build = load_wolfboot_build_module()
    install_fake_objcopy(monkeypatch, wolfboot_build)
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    artifact_path = source_dir / "wolfboot.elf"
    config_template_path = repo_root / "testdata" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"
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
    assert manifest["wolfboot_build"]["key_material_copied_to_results"] is True
    assert (result.result_dir / "cryptographic-material/bootloader-signing/private/canonical_private_key.der").read_bytes() == b"wolfboot generated private key"
    assert (result.result_dir / "artifacts/bootloader/wolfboot.elf").is_file()
    assert (result.result_dir / "material-inventory.json").is_file()


def test_execute_wolfboot_build_rejects_generated_config_outside_source_dir(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "wolfboot").mkdir(parents=True)
    (repo_root / "testdata" / "wolfboot").mkdir(parents=True)
    (repo_root / "testdata" / "wolfboot" / "stm32l4r5_ecdsa_p256.config").write_text(
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




def test_default_wolfboot_build_profile_sets_explicit_wolfboot_root():
    wolfboot_build = load_wolfboot_build_module()
    repo_root = Path(__file__).resolve().parents[2]
    target_profile = repo_root / "configs" / "targets" / "stm32l4r5_wolfboot.yaml"
    spec = importlib.util.spec_from_file_location(
        "experiment_cli_for_wolfboot_profile", repo_root / "scripts/experiment.py"
    )
    assert spec is not None and spec.loader is not None
    experiment_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(experiment_cli)
    profile, resolved_repo_root = experiment_cli.load_secure_boot_profile_section(
        target_profile=target_profile, algorithm="ecdsa_p256", section="build"
    )
    assert resolved_repo_root == repo_root

    assert profile["build"]["args"] == "WOLFBOOT_ROOT=. wolfboot.elf"
    assert profile["build"]["signing_tuple"]["tuple_id"] == "ecdsa_p256-development"
    assert profile["build"]["signing_tuple"]["directory"] == (
        "secrets/wolfboot/tuples/ecdsa_p256-development"
    )
    assert profile["build"]["stm32l4_hal_conf_pwr_patch"] is True
    assert profile["build"]["boot_timing_instrumentation_patch"] is True
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
    profile["build"]["config_template"] = "testdata/wolfboot/stm32l4r5_ed25519.config"
    profile["build"]["signing_key"] = "secrets/wolfboot/ed25519_private_key.der"

    command = wolfboot_build.construct_wolfboot_build_command(profile)

    assert command == ["make", "WOLFBOOT_ROOT=.", "wolfboot.elf"]


def test_validate_wolfboot_build_profile_accepts_rsa2048_algorithm():
    wolfboot_build = load_wolfboot_build_module()
    profile = sample_profile()
    profile["id"] = "wolfboot_stm32l4_rsa2048"
    profile["signature_algorithm"] = "rsa2048"
    profile["boot_profile"] = "wolfboot_rsa2048"
    profile["build"]["config_template"] = "testdata/wolfboot/stm32l4r5_rsa2048.config"
    profile["build"]["signing_key"] = "secrets/wolfboot/rsa2048_private_key.der"

    wolfboot_build.validate_wolfboot_build_profile(profile)



def test_validate_wolfboot_build_profile_accepts_phase_11_5d_expanded_algorithm():
    wolfboot_build = load_wolfboot_build_module()
    profile = sample_profile()
    profile["id"] = "wolfboot_stm32l4_ecc384"
    profile["signature_algorithm"] = "ecc384"
    profile["boot_profile"] = "wolfboot_ecc384"
    profile["build"]["config_template"] = "testdata/wolfboot/stm32l4r5_ecc384.config"
    profile["build"]["signing_key"] = "secrets/wolfboot/ecc384_private_key.der"

    wolfboot_build.validate_wolfboot_build_profile(profile)


def test_validate_wolfboot_build_profile_accepts_mldsa44():
    wolfboot_build = load_wolfboot_build_module()
    profile = sample_profile()
    profile["id"] = "wolfboot_stm32l4_mldsa44"
    profile["signature_algorithm"] = "mldsa44"
    profile["boot_profile"] = "wolfboot_mldsa44"
    profile["build"]["config_template"] = "testdata/wolfboot/stm32l4r5_mldsa44.config"

    wolfboot_build.validate_wolfboot_build_profile(profile)


def test_execute_wolfboot_build_removes_stale_host_tool_outputs_before_make(tmp_path, monkeypatch):
    wolfboot_build = load_wolfboot_build_module()
    install_fake_objcopy(monkeypatch, wolfboot_build)
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    artifact_path = source_dir / "wolfboot.elf"
    config_template_path = repo_root / "testdata" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"
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


def test_execute_wolfboot_build_preserves_matching_key_and_keystore_tuple(tmp_path, monkeypatch):
    wolfboot_build = load_wolfboot_build_module()
    install_fake_objcopy(monkeypatch, wolfboot_build)
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    artifact_path = source_dir / "wolfboot.elf"
    config_template_path = repo_root / "testdata" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"
    signing_key = repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"
    wolfboot_key = source_dir / "wolfboot_signing_private_key.der"
    generated_keystore = source_dir / "src" / "keystore.c"
    generated_public_key = source_dir / "wolfboot_signing_public_key.der"

    source_dir.mkdir(parents=True)
    write_keytools_makefile(source_dir)
    write_stm32l4_hal_conf(source_dir)
    write_wolfboot_image_source(source_dir)
    write_stm32l4_source(source_dir)
    config_template_path.parent.mkdir(parents=True)
    config_template_path.write_text("TARGET=stm32l4\nSIGN=ECC256\nSTM32CUBE=../..\n", encoding="utf-8")
    signing_key.parent.mkdir(parents=True)
    signing_key.write_bytes(b"canonical ecdsa p256 private key")
    wolfboot_key.write_bytes(b"canonical ecdsa p256 private key")
    generated_keystore.parent.mkdir(parents=True, exist_ok=True)
    generated_keystore.write_text("/* matching generated keystore */\n", encoding="utf-8")
    generated_public_key.write_bytes(b"matching generated public key")

    def fake_runner(command: list[str], cwd: Path):
        assert command == ["make", "WOLFBOOT_ROOT=.", "wolfboot.elf"]
        assert cwd == source_dir
        assert generated_keystore.is_file()
        assert generated_public_key.is_file()
        assert wolfboot_key.read_bytes() == signing_key.read_bytes()
        artifact_path.write_text("fake wolfboot elf", encoding="utf-8")
        return wolfboot_build.WolfBootCommandExecution(command, 0, "ok", "", 0.1)

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    cleanup = manifest["wolfboot_build"]["generated_signing_artifact_cleanup"]

    assert result.return_code == 0
    assert generated_keystore.is_file()
    assert generated_public_key.is_file()
    assert cleanup["removed_count"] == 0
    assert cleanup["removed_paths"] == []


def test_execute_wolfboot_build_rejects_existing_key_when_keystore_is_missing(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    config_template_path = repo_root / "testdata" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"
    signing_key = repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"
    wolfboot_key = source_dir / "wolfboot_signing_private_key.der"

    source_dir.mkdir(parents=True)
    write_keytools_makefile(source_dir)
    write_stm32l4_hal_conf(source_dir)
    write_wolfboot_image_source(source_dir)
    write_stm32l4_source(source_dir)
    config_template_path.parent.mkdir(parents=True)
    config_template_path.write_text("TARGET=stm32l4\nSIGN=ECC256\nSTM32CUBE=../..\n", encoding="utf-8")
    signing_key.parent.mkdir(parents=True)
    signing_key.write_bytes(b"canonical ecdsa p256 private key")
    wolfboot_key.write_bytes(b"canonical ecdsa p256 private key")

    runner_called = False

    def fake_runner(command: list[str], cwd: Path):
        nonlocal runner_called
        runner_called = True
        return wolfboot_build.WolfBootCommandExecution(command, 0, "ok", "", 0.1)

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    assert result.return_code == wolfboot_build.PROFILE_ERROR_RETURN_CODE
    assert runner_called is False
    assert result.failure_reason is not None
    assert "generated wolfBoot keystore is missing" in result.failure_reason
    assert "cannot regenerate keystore.c from an existing private key alone" in result.failure_reason



def test_execute_wolfboot_build_removes_cross_profile_wolfssl_objects_before_make(
    tmp_path, monkeypatch,
):
    wolfboot_build = load_wolfboot_build_module()
    install_fake_objcopy(monkeypatch, wolfboot_build)
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    artifact_path = source_dir / "wolfboot.elf"
    config_template_path = (
        repo_root / "testdata" / "wolfboot" / "stm32l4r5_ecdsa_p256.config"
    )
    source_dir.mkdir(parents=True)
    write_keytools_makefile(source_dir)
    write_stm32l4_hal_conf(source_dir)
    write_wolfboot_image_source(source_dir)
    write_stm32l4_source(source_dir)
    config_template_path.parent.mkdir(parents=True)
    config_template_path.write_text(
        "TARGET=stm32l4\nSIGN=ECC256\nSTM32CUBE=../..\n",
        encoding="utf-8",
    )

    stale_outputs = [
        source_dir / "lib/wolfssl/wolfcrypt/src/sha3.o",
        source_dir / "lib/wolfssl/wolfcrypt/src/sha3.d",
        source_dir
        / "lib/wolfssl/wolfcrypt/src/port/arm/thumb2-sha3-asm.o",
        source_dir
        / "lib/wolfssl/wolfcrypt/src/port/arm/thumb2-sha3-asm_c.o",
        source_dir / "lib/wolfssl/wolfcrypt/src/wc_mldsa.o",
        # Reproduces the single-bank to dual-bank link failure: a freshly
        # compiled update_flash_hwswap.o must not link an older libwolfboot.o.
        source_dir / "src/libwolfboot.o",
        source_dir / "src/update_flash_hwswap.o",
        source_dir / "hal/stm32l4.o",
    ]
    preserved_sources = [
        source_dir / "lib/wolfssl/wolfcrypt/src/sha3.c",
        source_dir
        / "lib/wolfssl/wolfcrypt/src/port/arm/thumb2-sha3-asm.S",
    ]
    for path in stale_outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stale profile-dependent output")
    for path in preserved_sources:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("/* source */\n", encoding="utf-8")

    def fake_runner(command: list[str], cwd: Path):
        assert command == ["make", "WOLFBOOT_ROOT=.", "wolfboot.elf"]
        assert cwd == source_dir
        for path in stale_outputs:
            assert not path.exists()
        for path in preserved_sources:
            assert path.is_file()
        artifact_path.write_text("fake wolfboot elf", encoding="utf-8")
        return wolfboot_build.WolfBootCommandExecution(
            command,
            0,
            "ok",
            "",
            0.1,
        )

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    assert result.return_code == 0
    for path in stale_outputs:
        assert not path.exists()
    for path in preserved_sources:
        assert path.is_file()


def test_execute_integrity_only_wolfboot_build_skips_all_signing_material(monkeypatch, tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    install_fake_objcopy(monkeypatch, wolfboot_build)
    repo_root = tmp_path / "repo"
    source_dir = repo_root / "tools" / "wolfboot"
    artifact_path = source_dir / "wolfboot.elf"
    config_template_path = repo_root / "testdata" / "wolfboot" / "stm32l4r5_integrity.config"
    source_dir.mkdir(parents=True)
    config_template_path.parent.mkdir(parents=True)
    config_template_path.write_text(
        "TARGET=stm32l4\nSIGN=NONE\nHASH=SHA256\nSTM32CUBE=../..\n",
        encoding="utf-8",
    )

    profile = sample_profile()
    profile["id"] = "wolfboot_stm32l4_integrity"
    profile["signature_algorithm"] = "integrity_sha256"
    profile["build"] = {
        "command": "make",
        "args": "WOLFBOOT_ROOT=. wolfboot.elf",
        "config_template": "testdata/wolfboot/stm32l4r5_integrity.config",
        "generated_config": "tools/wolfboot/.config",
        "signing_tuple": {},
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("integrity-only build entered a signing-material path")

    monkeypatch.setattr(wolfboot_build, "_prepare_persistent_signing_tuple", forbidden)
    monkeypatch.setattr(wolfboot_build, "_prepare_wolfboot_signing_artifacts", forbidden)
    monkeypatch.setattr(wolfboot_build, "_coordinate_wolfboot_signing_key_before_build", forbidden)
    monkeypatch.setattr(wolfboot_build, "_coordinate_wolfboot_signing_key_after_build", forbidden)

    def fake_runner(command, cwd):
        artifact_path.write_text("integrity wolfboot elf", encoding="utf-8")
        return wolfboot_build.WolfBootCommandExecution(
            command=command,
            return_code=0,
            stdout="ok",
            stderr="",
            duration_seconds=0.01,
        )

    result = wolfboot_build.execute_wolfboot_build(
        profile=profile,
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
        timestamp=datetime(2026, 7, 31, 4, 55, 0, tzinfo=timezone.utc),
    )

    assert result.return_code == 0
    assert result.signing_key_path is None
    assert result.wolfboot_private_key_path is None
    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["wolfboot_build"]["signature_algorithm"] == "integrity_sha256"
    assert manifest["signing_key_consistency"]["status"] == "not_configured"


def test_boot_measurements_reset_at_new_integrity_attempt_and_authenticate_same_image():
    """No previous candidate's authenticity/digest can survive the next attempt."""
    from pathlib import Path
    generator = Path("scripts/framework/wolfboot_build.py").read_text(encoding="utf-8")
    integrity_wrapper = generator[generator.index("/* PQC_BOOT_INTEGRITY_WRAPPER_V4:"):generator.index("pqc_boot_timing_integrity_finish(end_cycles - start_cycles, ret, img);") + len("pqc_boot_timing_integrity_finish(end_cycles - start_cycles, ret, img);")]
    assert integrity_wrapper.index("pqc_boot_timing_integrity_begin();") < integrity_wrapper.index("uint32_t start_cycles =")
    assert integrity_wrapper.index("uint32_t end_cycles =") < integrity_wrapper.index("pqc_boot_timing_integrity_finish(end_cycles")
    begin = generator[generator.index("void pqc_boot_timing_integrity_begin(void)\n{"):generator.index("void pqc_boot_timing_verification_start(uint32_t *start_cycles)\n{")]
    assert "mailbox->authenticity_valid = 0U;" in begin
    assert "mailbox->verified_image_digest_valid = 0U;" in begin
    assert "mailbox->integrity_valid = 0U;" in begin
    assert "pqc_boot_timing_verification_finish(end_cycles - start_cycles, ret, img);" in generator
    assert "img->part == mailbox->verified_image_part" in generator
    assert "img->fw_size == mailbox->verified_image_fw_size" in generator
    assert "img->sha_hash[i] != mailbox->verified_image_sha256[i]" in generator
    assert "#if !defined(WOLFBOOT_NO_SIGN)" in generator


def test_v7_generated_selected_image_helpers_compile_and_reject_mismatched_attempts(tmp_path):
    """Exercise the generated C implementation, not a Python reimplementation."""
    import shutil

    import pytest

    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("host C compiler not available")
    source = Path("scripts/framework/wolfboot_build.py").read_text(encoding="utf-8")

    def c_function(name: str) -> str:
        signature = f"void {name}("
        start = source.index(signature, source.index("/* PQC_BOOT_RESET_ORIGIN_V3 */"))
        brace = source.index("{", start)
        level = 0
        for end in range(brace, len(source)):
            if source[end] == "{":
                level += 1
            elif source[end] == "}":
                level -= 1
                if level == 0:
                    return source[start:end + 1]
        raise AssertionError(f"unterminated generated C helper: {name}")

    mailbox = source[
        source.index("struct pqc_boot_timing_mailbox {"):
        source.index("};", source.index("struct pqc_boot_timing_mailbox {")) + 2
    ]
    helper_names = (
        "pqc_boot_timing_image_start",
        "pqc_boot_timing_image_finish",
        "pqc_boot_timing_select_image",
    )
    generated = "\n\n".join(c_function(name) for name in helper_names)
    harness = (
        "#include <stdint.h>\n#include <stdio.h>\n"
        "#define WOLFBOOT_SHA_DIGEST_SIZE 32U\n"
        "#define PQC_BOOT_TIMING_MAILBOX_MAGIC 0x50514354UL\n"
        "#define PQC_BOOT_STACK_UNAVAILABLE 0xFFFFFFFFUL\n"
        "struct wolfBoot_image { uint32_t part; uint32_t fw_size; uint8_t *sha_hash; };\n"
        + mailbox
        + "\nstatic struct pqc_boot_timing_mailbox test_mailbox;\n"
        + "#define WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR ((uintptr_t)&test_mailbox)\n"
        + "static uint32_t pqc_boot_image_start_cycles, pqc_boot_image_start_part;\n"
        + "static uint32_t pqc_boot_image_start_size, pqc_boot_image_started;\n"
        + generated
        + '''
int main(void)
{
    uint8_t digest[32] = {0};
    struct wolfBoot_image image = {0U, 100U, digest};
    test_mailbox.integrity_valid = 1U;
    test_mailbox.integrity_result = 0;
    test_mailbox.verified_image_digest_valid = 1U;
    test_mailbox.verified_image_part = 0U;
    test_mailbox.verified_image_fw_size = 100U;
    test_mailbox.signature_algorithm_id = 12U;
    test_mailbox.authenticity_valid = 1U;
    test_mailbox.authenticity_result = 0;
    test_mailbox.hclk_hz = 80000000U;
    pqc_boot_timing_image_start(1000U, &image);
    pqc_boot_timing_image_finish(4000U, 0, &image);
    pqc_boot_timing_select_image(&image);
    if (test_mailbox.image_verification_valid != 1U ||
        test_mailbox.image_verification_cycles != 3000U ||
        test_mailbox.selected_image_valid != 1U)
        return 1;
    /* The final selected-image checkpoint must reject a different partition. */
    image.part = 1U;
    pqc_boot_timing_select_image(&image);
    if (test_mailbox.selected_image_valid != 0U) return 2;
    image.part = 0U;
    /* An invalid signature must not finalize an enclosing interval. */
    test_mailbox.image_verification_valid = 0U;
    pqc_boot_timing_image_start(5000U, &image);
    pqc_boot_timing_image_finish(6000U, -1, &image);
    if (test_mailbox.image_verification_valid != 0U) return 3;
    /* Integrity-only profiles do not require a signature measurement. */
    test_mailbox.signature_algorithm_id = 1U;
    test_mailbox.authenticity_valid = 0U;
    pqc_boot_timing_image_start(7000U, &image);
    pqc_boot_timing_image_finish(8000U, 0, &image);
    pqc_boot_timing_select_image(&image);
    if (test_mailbox.image_verification_valid != 1U ||
        test_mailbox.image_verification_cycles != 1000U ||
        test_mailbox.selected_image_valid != 1U)
        return 4;
    /* A digest mismatch cannot be reported as the selected image. */
    digest[0] = 1U;
    pqc_boot_timing_select_image(&image);
    if (test_mailbox.selected_image_valid != 0U) return 5;
    puts("generated image interval and final-selection checks passed");
    return 0;
}
'''
    )
    c_path = tmp_path / "mailbox_v7.c"
    c_path.write_text(harness, encoding="utf-8")
    executable = tmp_path / "mailbox_v7"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c_path), "-o", str(executable)],
        capture_output=True, text=True, check=True,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, check=True)
    assert "generated image interval and final-selection checks passed" in result.stdout


def test_optional_stack_watermark_reports_specific_unavailability():
    # This source is injected into the STM32L4 HAL at build time.
    helper = (Path(__file__).resolve().parents[2] / "scripts/framework/wolfboot_build.py").read_text(encoding="utf-8")
    assert "#define PQC_BOOT_STACK_GUARD_BYTES 128UL" in helper
    assert "mailbox->stack_measurement_status = 3U;" in helper
    assert "mailbox->stack_measurement_status = 4U;" in helper
    assert "mailbox->stack_measurement_status = 5U;" in helper
    assert "(uintptr_t)p + 32U >= scan_msp" in helper


def test_request17_diagnostic_config_is_default_off_and_explicitly_enabled():
    experiment = load_experiment_module()
    normal, _ = experiment.load_secure_boot_profile_section(
        target_profile=REPO_ROOT / "configs/targets/stm32l4r5_wolfboot.yaml",
        algorithm="integrity_sha256", section="build",
    )
    diagnostic, _ = experiment.load_secure_boot_profile_section(
        target_profile=REPO_ROOT / "configs/targets/stm32l4r5_wolfboot.yaml",
        algorithm="integrity_sha256", section="build", boot_uart_diagnostics=True,
    )
    normal_config = normal["build"]["config_content"]
    diagnostic_config = diagnostic["build"]["config_content"]
    assert "WOLFBOOT_PQC_UART_DIAGNOSTICS" not in normal_config
    assert "CFLAGS_EXTRA+=-DDEBUG_UART=1" in diagnostic_config
    assert "CFLAGS_EXTRA+=-DWOLFBOOT_PQC_UART_DIAGNOSTICS=1" in diagnostic_config
    assert "DEBUG?=1" in diagnostic_config
    assert diagnostic["build"]["boot_uart_diagnostics"] is True


def test_request17_stm32l4_uart_is_target_specific_and_markers_are_outside_timing_wrappers():
    hal = (REPO_ROOT / "tools/wolfboot/hal/stm32l4.c").read_text(encoding="utf-8")
    boot = (REPO_ROOT / "tools/wolfboot/src/update_flash.c").read_text(encoding="utf-8")
    hwswap = (REPO_ROOT / "tools/wolfboot/src/update_flash_hwswap.c").read_text(encoding="utf-8")
    assert "LPUART1" in hal and "PG7" in hal and "PG8" in hal
    assert "PQC_WB_UART_BAUD 115200UL" in hal
    assert "PQC_WOLFBOOT_DIAG event=bootloader_uart_ready" in hal
    assert "PQC_WOLFBOOT_DIAG event=verification_start" in boot
    assert "PQC_WOLFBOOT_DIAG event=verification_complete" in boot
    assert "cycles=%u timing_valid=%u" in boot
    assert "PQC_WOLFBOOT_DIAG event=bank_decision" in hwswap
    helper = (REPO_ROOT / "scripts/framework/wolfboot_build.py").read_text(encoding="utf-8")
    assert "pqc_boot_timing_diag_integrity_cycles" in helper
    assert "pqc_boot_timing_diag_authenticity_cycles" in helper
    assert "The DWT end snapshot was taken in image.c before this copy." in helper
    # The measured operation is the verify call itself. Diagnostics immediately
    # before/after it must not be inserted into image.c's DWT wrapper.
    image = (REPO_ROOT / "tools/wolfboot/src/image.c").read_text(encoding="utf-8")
    assert "PQC_WOLFBOOT_DIAG" not in image
