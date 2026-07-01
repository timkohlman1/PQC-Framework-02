from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_experiment_config_rejects_missing_board():
    experiment_cli = load_experiment_module()

    config = {
        "id": "baseline_direct_uart",
        "description": "Missing board field.",
        "host": "gateway",
        "firmware": {
            "mode": "direct_flash",
            "artifact": "build/Debug/stm32_basic_hal1.elf",
        },
        "uart": {
            "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
            "expected_tick_message": "tick",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="board"):
        experiment_cli.validate_experiment_config(config)



def test_validate_experiment_config_rejects_missing_boot():
    experiment_cli = load_experiment_module()

    config = {
        "id": "baseline_direct_uart",
        "description": "Missing boot field.",
        "board": "board_a",
        "host": "gateway",
        "firmware": {
            "mode": "direct_flash",
            "artifact": "build/Debug/stm32_basic_hal1.elf",
        },
        "uart": {
            "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
            "expected_tick_message": "tick",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="boot"):
        experiment_cli.validate_experiment_config(config)


def test_validate_boot_config_rejects_non_runnable_boot_profile():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_ecdsa_p256",
        "mode": "wolfboot_ecdsa_p256",
        "description": "Planned wolfBoot test boot config.",
        "runnable": False,
    }

    with pytest.raises(experiment_cli.ConfigError, match="planned and not runnable"):
        experiment_cli.validate_boot_config(config)


def test_validate_boot_config_for_inspection_accepts_planned_boot_profile():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_ecdsa_p256",
        "mode": "wolfboot_ecdsa_p256",
        "description": "Planned wolfBoot test boot config.",
        "runnable": False,
        "status": "planned",
        "intended_signature_algorithm": "ecdsa_p256",
        "application_slot_concept": "planned_signed_application_slot",
    }

    experiment_cli.validate_boot_config_for_inspection(config)

def test_validate_board_config_rejects_missing_stlink_serial():
    experiment_cli = load_experiment_module()

    config = {
        "id": "board_a",
        "name": "NUCLEO-L4R5ZI-P",
        "mcu": "STM32L4R5",
        "description": "Missing ST-LINK serial.",
        "stlink": {},
        "uart": {
            "baud": 115200,
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="stlink.serial"):
        experiment_cli.validate_board_config(config)


def test_validate_host_config_rejects_missing_uart_device():
    experiment_cli = load_experiment_module()

    config = {
        "id": "gateway",
        "alias": "pqc-gateway1",
        "user": "timk",
        "description": "Missing UART device.",
        "flash": {
            "helper": "flash-stm32a",
        },
        "uart": {
            "baud": 115200,
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="uart.device"):
        experiment_cli.validate_host_config(config)


def test_load_experiment_bundle_rejects_board_id_mismatch(tmp_path):
    experiment_cli = load_experiment_module()

    configs_root = tmp_path / "configs"
    boards_dir = configs_root / "boards"
    hosts_dir = configs_root / "hosts"
    boot_dir = configs_root / "boot"
    experiments_dir = configs_root / "experiments"

    boards_dir.mkdir(parents=True)
    hosts_dir.mkdir(parents=True)
    boot_dir.mkdir(parents=True)
    experiments_dir.mkdir(parents=True)

    (boards_dir / "board_a.yaml").write_text(
        "\n".join(
            [
                "id: wrong_board",
                "name: NUCLEO-L4R5ZI-P",
                "mcu: STM32L4R5",
                "description: Test board.",
                "stlink:",
                '  serial: "123"',
                "uart:",
                "  baud: 115200",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (boot_dir / "direct_flash.yaml").write_text(
        "\n".join(
            [
                "id: direct_flash",
                "mode: direct_flash",
                "description: Direct-flash test boot config.",
                "runnable: true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (hosts_dir / "gateway.yaml").write_text(
        "\n".join(
            [
                "id: gateway",
                "alias: pqc-gateway1",
                "user: timk",
                "description: Test gateway.",
                "flash:",
                "  helper: flash-stm32a",
                "uart:",
                "  device: /dev/example",
                "  baud: 115200",
                "",
            ]
        ),
        encoding="utf-8",
    )

    experiment_path = experiments_dir / "baseline_direct_uart.yaml"
    experiment_path.write_text(
        "\n".join(
            [
                "id: baseline_direct_uart",
                "description: Test experiment.",
                "board: board_a",
                "host: gateway",
                "boot: direct_flash",
                "firmware:",
                "  mode: direct_flash",
                "  artifact: build/Debug/stm32_basic_hal1.elf",
                "uart:",
                "  expected_boot_message: stm32-basic_hal1 boot v0.1.0",
                "  expected_tick_message: tick",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(experiment_cli.ConfigError, match="board config id mismatch"):
        experiment_cli.load_experiment_bundle(experiment_path)

def test_load_experiment_bundle_rejects_planned_wolfboot_boot_profile_for_execution(tmp_path):
    experiment_cli = load_experiment_module()

    configs_root = tmp_path / "configs"
    boards_dir = configs_root / "boards"
    hosts_dir = configs_root / "hosts"
    boot_dir = configs_root / "boot"
    experiments_dir = configs_root / "experiments"

    boards_dir.mkdir(parents=True)
    hosts_dir.mkdir(parents=True)
    boot_dir.mkdir(parents=True)
    experiments_dir.mkdir(parents=True)

    (boards_dir / "board_a.yaml").write_text(
        "\n".join(
            [
                "id: board_a",
                "name: NUCLEO-L4R5ZI-P",
                "mcu: STM32L4R5",
                "description: Test board.",
                "stlink:",
                '  serial: "123"',
                "uart:",
                "  baud: 115200",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (boot_dir / "wolfboot_ecdsa_p256.yaml").write_text(
        "\n".join(
            [
                "id: wolfboot_ecdsa_p256",
                "mode: wolfboot_ecdsa_p256",
                "description: Planned wolfBoot test boot config.",
                "runnable: false",
                "status: planned",
                "intended_signature_algorithm: ecdsa_p256",
                "application_slot_concept: planned_signed_application_slot",
                "flash_layout_status: not_confirmed",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (hosts_dir / "gateway.yaml").write_text(
        "\n".join(
            [
                "id: gateway",
                "alias: pqc-gateway1",
                "user: timk",
                "description: Test gateway.",
                "flash:",
                "  helper: flash-stm32a",
                "uart:",
                "  device: /dev/example",
                "  baud: 115200",
                "",
            ]
        ),
        encoding="utf-8",
    )

    experiment_path = experiments_dir / "wolfboot_placeholder_uart.yaml"
    experiment_path.write_text(
        "\n".join(
            [
                "id: wolfboot_placeholder_uart",
                "description: Placeholder wolfBoot experiment that must not execute.",
                "board: board_a",
                "host: gateway",
                "boot: wolfboot_ecdsa_p256",
                "firmware:",
                "  mode: wolfboot_ecdsa_p256",
                "  artifact: build/Debug/stm32_basic_hal1.elf",
                "uart:",
                "  expected_boot_message: stm32-basic_hal1 boot v0.1.0",
                "  expected_tick_message: tick",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(experiment_cli.ConfigError, match="planned and not runnable"):
        experiment_cli.load_experiment_bundle(experiment_path)



def test_validate_boot_config_for_inspection_accepts_planned_flash_layout_metadata():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_ecdsa_p256",
        "mode": "wolfboot_ecdsa_p256",
        "description": "Planned wolfBoot test boot config.",
        "runnable": False,
        "status": "planned",
        "implementation_state": "secure_boot_flash_layout_defined_placeholder_only",
        "intended_signature_algorithm": "ecdsa_p256",
        "application_slot_concept": "planned_signed_application_primary_slot",
        "flash_layout_status": "defined_phase_10d_planned_not_implemented",
        "secure_boot_layout": {
            "status": "planned_not_runnable",
            "decision_record": "docs/decisions/0003_secure_boot_flash_layout.md",
            "internal_flash_base": "0x08000000",
            "internal_flash_size": "0x00200000",
            "internal_flash_end": "0x081FFFFF",
            "wolfboot_base": "0x08000000",
            "wolfboot_size": "0x00020000",
            "primary_slot_base": "0x08020000",
            "primary_slot_size": "0x000E0000",
            "primary_slot_entry": "0x08022000",
            "image_header_size": "0x00002000",
            "update_slot_base": "0x08100000",
            "update_slot_size": "0x000E0000",
            "swap_metadata_base": "0x081E0000",
            "swap_metadata_size": "0x00020000",
            "sector_size_assumption": "0x00004000",
            "physical_flash_page_assumption": "0x00001000",
            "wolfboot_partition_boot_address": "0x08020000",
            "wolfboot_partition_size": "0x000E0000",
            "wolfboot_partition_update_address": "0x08100000",
            "wolfboot_partition_swap_address": "0x081E0000",
        },
    }

    experiment_cli.validate_boot_config_for_inspection(config)



def test_validate_boot_config_still_rejects_planned_flash_layout_for_execution():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_ecdsa_p256",
        "mode": "wolfboot_ecdsa_p256",
        "description": "Planned wolfBoot test boot config.",
        "runnable": False,
        "status": "planned",
        "flash_layout_status": "defined_phase_10d_planned_not_implemented",
        "secure_boot_layout": {
            "primary_slot_base": "0x08020000",
            "primary_slot_entry": "0x08022000",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="planned and not runnable"):
        experiment_cli.validate_boot_config(config)



def test_validate_application_signing_profile_accepts_ed25519_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_test_signing",
        "description": "Invalid signing profile.",
        "input_image": "build/RelocatedDebug/stm32_basic_hal1.bin",
        "signed_image": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
        "signature_algorithm": "ed25519",
        "image_version": 1,
        "private_key": "secrets/wolfboot/ecdsa_p256_private_key.der",
        "sign": {
            "command": "tools/wolfboot/tools/keytools/sign",
        },
    }

    experiment_cli.validate_application_signing_profile_config(config)


def test_validate_application_signing_profile_requires_keygen_command_when_enabled():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_test_signing",
        "description": "Invalid signing profile.",
        "input_image": "build/RelocatedDebug/stm32_basic_hal1.bin",
        "signed_image": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
        "signature_algorithm": "ecdsa_p256",
        "image_version": 1,
        "private_key": "secrets/wolfboot/ecdsa_p256_private_key.der",
        "keygen": {
            "enabled": True,
        },
        "sign": {
            "command": "tools/wolfboot/tools/keytools/sign",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="keygen.command"):
        experiment_cli.validate_application_signing_profile_config(config)


def test_validate_application_signing_profile_requires_binary_conversion_command_when_enabled():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_test_signing",
        "description": "Invalid signing profile.",
        "input_elf": "build/RelocatedDebug/stm32_basic_hal1.elf",
        "input_image": "build/RelocatedDebug/stm32_basic_hal1.bin",
        "signed_image": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
        "signature_algorithm": "ecdsa_p256",
        "image_version": 1,
        "private_key": "secrets/wolfboot/ecdsa_p256_private_key.der",
        "binary_conversion": {
            "enabled": True,
        },
        "sign": {
            "command": "tools/wolfboot/tools/keytools/sign",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="binary_conversion.command"):
        experiment_cli.validate_application_signing_profile_config(config)


def _valid_classical_profile_model():
    return {
        "id": "classical_signing_profiles",
        "description": "Phase 11.5a model.",
        "schema_version": 1,
        "model_phase": "phase_11_5a_classical_profile_model",
        "benchmark_scope": "secure_boot_classical_signing_algorithm",
        "minimum_comparison_scope": {
            "ed25519": {"algorithm": "ED25519", "runnable": False},
            "ecc256": {"algorithm": "ECC256", "runnable": True},
            "rsa2048": {"algorithm": "RSA2048", "runnable": False},
        },
        "profiles": {
            "ecc256_reference": {
                "algorithm": "ECC256",
                "signature_algorithm": "ecdsa_p256",
                "signature_size_bytes": 64,
                "signing_profile": "configs/signing/wolfboot_ecdsa_p256_app.yaml",
                "wolfboot_build_profile": "configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml",
                "experiment_profile": "configs/experiments/wolfboot_ecdsa_p256_uart.yaml",
                "runnable": True,
            },
            "ed25519_reserved": {
                "algorithm": "ED25519",
                "runnable": False,
                "unsupported_reason": "Not implemented in Phase 11.5a.",
            },
            "rsa2048_reserved": {
                "algorithm": "RSA2048",
                "runnable": False,
                "unsupported_reason": "Not implemented in Phase 11.5a.",
            },
        },
    }


def test_validate_classical_profile_model_accepts_minimum_scope():
    experiment_cli = load_experiment_module()

    experiment_cli.validate_classical_benchmark_profile_model_config(_valid_classical_profile_model())


def test_validate_classical_profile_model_rejects_missing_rsa2048_scope():
    experiment_cli = load_experiment_module()
    config = _valid_classical_profile_model()
    del config["minimum_comparison_scope"]["rsa2048"]

    with pytest.raises(experiment_cli.ConfigError, match="exactly ED25519, ECC256, and RSA2048"):
        experiment_cli.validate_classical_benchmark_profile_model_config(config)


def test_validate_classical_profile_model_rejects_runnable_reserved_profile():
    experiment_cli = load_experiment_module()
    config = _valid_classical_profile_model()
    config["profiles"]["ed25519_reserved"]["runnable"] = True

    with pytest.raises(experiment_cli.ConfigError, match="ed25519_reserved.*runnable must remain false"):
        experiment_cli.validate_classical_benchmark_profile_model_config(config)



def test_validate_application_signing_profile_rejects_unsupported_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_test_signing",
        "description": "Invalid signing profile.",
        "input_image": "build/RelocatedDebug/stm32_basic_hal1.bin",
        "signed_image": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
        "signature_algorithm": "mldsa44",
        "image_version": 1,
        "private_key": "secrets/wolfboot/mldsa44_private_key.der",
        "sign": {"command": "tools/wolfboot/tools/keytools/sign"},
    }

    with pytest.raises(experiment_cli.ConfigError, match="ecdsa_p256, ed25519, rsa2048, ecc384, ecc521, ed448, rsa3072, or rsa4096"):
        experiment_cli.validate_application_signing_profile_config(config)


def test_validate_wolfboot_build_profile_accepts_ed25519_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_stm32l4_ed25519",
        "description": "ED25519 build profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "ed25519",
        "boot_profile": "wolfboot_ed25519",
        "build": {
            "command": "make",
            "config_template": "configs/wolfboot/stm32l4r5_ed25519.config",
            "generated_config": "tools/wolfboot/.config",
        },
    }

    experiment_cli.validate_wolfboot_build_profile_config(config)


def test_validate_classical_profile_model_accepts_phase_11_5b_ed25519_profile():
    experiment_cli = load_experiment_module()
    config = _valid_classical_profile_model()
    config["model_phase"] = "phase_11_5b_ed25519_profile"
    config["minimum_comparison_scope"]["ed25519"]["runnable"] = True
    config["minimum_comparison_scope"]["ed25519"]["signature_algorithm"] = "ed25519"
    del config["profiles"]["ed25519_reserved"]
    config["profiles"]["ed25519_benchmark"] = {
        "algorithm": "ED25519",
        "signature_algorithm": "ed25519",
        "signature_size_bytes": 64,
        "signing_profile": "configs/signing/wolfboot_ed25519_app.yaml",
        "wolfboot_build_profile": "configs/builds/wolfboot_stm32l4_ed25519.yaml",
        "experiment_profile": "configs/experiments/wolfboot_ed25519_uart.yaml",
        "boot_profile": "configs/boot/wolfboot_ed25519.yaml",
        "runnable": True,
    }

    experiment_cli.validate_classical_benchmark_profile_model_config(config)



def test_validate_classical_profile_model_accepts_phase_11_5d_expanded_profiles():
    experiment_cli = load_experiment_module()
    config = _valid_classical_profile_model()
    config["model_phase"] = "phase_11_5d_expanded_classical_profiles"
    config["minimum_comparison_scope"]["ed25519"]["runnable"] = True
    config["minimum_comparison_scope"]["ed25519"]["signature_algorithm"] = "ed25519"
    config["minimum_comparison_scope"]["rsa2048"]["runnable"] = True
    config["minimum_comparison_scope"]["rsa2048"]["signature_algorithm"] = "rsa2048"
    del config["profiles"]["ed25519_reserved"]
    del config["profiles"]["rsa2048_reserved"]
    config["profiles"]["ed25519_benchmark"] = {
        "algorithm": "ED25519",
        "signature_algorithm": "ed25519",
        "signature_size_bytes": 64,
        "signing_profile": "configs/signing/wolfboot_ed25519_app.yaml",
        "wolfboot_build_profile": "configs/builds/wolfboot_stm32l4_ed25519.yaml",
        "experiment_profile": "configs/experiments/wolfboot_ed25519_uart.yaml",
        "boot_profile": "configs/boot/wolfboot_ed25519.yaml",
        "runnable": True,
    }
    config["profiles"]["rsa2048_benchmark"] = {
        "algorithm": "RSA2048",
        "signature_algorithm": "rsa2048",
        "key_size_bits": 2048,
        "signature_size_bytes": 256,
        "signing_profile": "configs/signing/wolfboot_rsa2048_app.yaml",
        "wolfboot_build_profile": "configs/builds/wolfboot_stm32l4_rsa2048.yaml",
        "experiment_profile": "configs/experiments/wolfboot_rsa2048_uart.yaml",
        "boot_profile": "configs/boot/wolfboot_rsa2048.yaml",
        "runnable": True,
    }
    for name, algorithm, sig_alg, key_bits, sig_size in (
        ("ecc384_benchmark", "ECC384", "ecc384", 384, 96),
        ("ecc521_benchmark", "ECC521", "ecc521", 521, 132),
        ("ed448_benchmark", "ED448", "ed448", 448, 114),
        ("rsa3072_benchmark", "RSA3072", "rsa3072", 3072, 384),
        ("rsa4096_benchmark", "RSA4096", "rsa4096", 4096, 512),
    ):
        suffix = sig_alg
        config["profiles"][name] = {
            "algorithm": algorithm,
            "signature_algorithm": sig_alg,
            "key_size_bits": key_bits,
            "signature_size_bytes": sig_size,
            "signing_profile": f"configs/signing/wolfboot_{suffix}_app.yaml",
            "wolfboot_build_profile": f"configs/builds/wolfboot_stm32l4_{suffix}.yaml",
            "experiment_profile": f"configs/experiments/wolfboot_{suffix}_uart.yaml",
            "boot_profile": f"configs/boot/wolfboot_{suffix}.yaml",
            "runnable": True,
        }

    experiment_cli.validate_classical_benchmark_profile_model_config(config)


def test_validate_wolfboot_build_profile_accepts_phase_11_5d_expanded_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_stm32l4_rsa4096",
        "description": "RSA4096 build profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "rsa4096",
        "boot_profile": "wolfboot_rsa4096",
        "build": {
            "command": "make",
            "config_template": "configs/wolfboot/stm32l4r5_rsa4096.config",
            "generated_config": "tools/wolfboot/.config",
        },
    }

    experiment_cli.validate_wolfboot_build_profile_config(config)
