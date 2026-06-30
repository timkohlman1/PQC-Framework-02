from __future__ import annotations

import importlib.util
from pathlib import Path


def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_config_reads_nested_mapping(tmp_path):
    experiment_cli = load_experiment_module()

    config_path = tmp_path / "sample.yaml"
    config_path.write_text(
        "\n".join(
            [
                "id: sample",
                "uart:",
                "  baud: 115200",
                "  enabled: true",
                'message: "hello"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = experiment_cli.load_config(config_path)

    assert config["id"] == "sample"
    assert config["uart"]["baud"] == 115200
    assert config["uart"]["enabled"] is True
    assert config["message"] == "hello"


def test_load_experiment_bundle_resolves_board_host_and_boot_configs(tmp_path):
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

    bundle = experiment_cli.load_experiment_bundle(experiment_path)

    assert bundle["experiment"]["id"] == "baseline_direct_uart"
    assert bundle["board"]["id"] == "board_a"
    assert bundle["host"]["id"] == "gateway"
    assert bundle["boot"]["id"] == "direct_flash"
    assert bundle["boot"]["mode"] == "direct_flash"


def test_status_summary_states_no_hardware_actions(tmp_path):
    experiment_cli = load_experiment_module()

    bundle = {
        "experiment": {
            "id": "baseline_direct_uart",
            "description": "Test experiment.",
            "firmware": {
                "mode": "direct_flash",
                "artifact": "build/Debug/stm32_basic_hal1.elf",
            },
            "uart": {
                "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
                "expected_tick_message": "tick",
            },
        },
        "board": {
            "id": "board_a",
            "name": "NUCLEO-L4R5ZI-P",
            "mcu": "STM32L4R5",
            "stlink": {
                "serial": "123",
            },
        },
        "boot": {
            "id": "direct_flash",
            "mode": "direct_flash",
            "description": "Direct-flash test boot config.",
            "runnable": True,
        },
        "host": {
            "id": "gateway",
            "alias": "pqc-gateway1",
            "user": "timk",
            "flash": {
                "helper": "flash-stm32a",
            },
            "uart": {
                "device": "/dev/example",
                "baud": 115200,
            },
        },
    }

    summary = experiment_cli.format_status_summary(bundle)

    assert "Experiment status" in summary
    assert "baseline_direct_uart" in summary
    assert "Boot config: direct_flash" in summary
    assert "Boot mode: direct_flash" in summary
    assert "No build, flash, UART access, SSH, hardware access, or network access was performed." in summary

def test_planned_wolfboot_boot_config_is_loadable_for_inspection(tmp_path):
    experiment_cli = load_experiment_module()

    config_path = tmp_path / "wolfboot_ecdsa_p256.yaml"
    config_path.write_text(
        "\n".join(
            [
                "id: wolfboot_ecdsa_p256",
                "mode: wolfboot_ecdsa_p256",
                "description: Planned wolfBoot ECDSA-P256 placeholder.",
                "runnable: false",
                "status: planned",
                "implementation_state: placeholder_only",
                "intended_signature_algorithm: ecdsa_p256",
                "application_slot_concept: planned_signed_application_slot",
                "flash_layout_status: not_confirmed",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = experiment_cli.load_config(config_path)
    experiment_cli.validate_boot_config_for_inspection(config)

    assert config["id"] == "wolfboot_ecdsa_p256"
    assert config["runnable"] is False
    assert config["status"] == "planned"
    assert config["intended_signature_algorithm"] == "ecdsa_p256"
    assert config["application_slot_concept"] == "planned_signed_application_slot"
    assert config["flash_layout_status"] == "not_confirmed"



def test_planned_wolfboot_flash_layout_metadata_is_loadable_for_inspection(tmp_path):
    experiment_cli = load_experiment_module()

    config_path = tmp_path / "wolfboot_ecdsa_p256.yaml"
    config_path.write_text(
        "\n".join(
            [
                "id: wolfboot_ecdsa_p256",
                "mode: wolfboot_ecdsa_p256",
                "description: Planned wolfBoot ECDSA-P256 placeholder.",
                "runnable: false",
                "status: planned",
                "implementation_state: secure_boot_flash_layout_defined_placeholder_only",
                "intended_signature_algorithm: ecdsa_p256",
                "application_slot_concept: planned_signed_application_primary_slot",
                "flash_layout_status: defined_phase_10d_planned_not_implemented",
                "secure_boot_layout:",
                "  status: planned_not_runnable",
                "  decision_record: docs/decisions/0003_secure_boot_flash_layout.md",
                "  internal_flash_base: 0x08000000",
                "  internal_flash_size: 0x00200000",
                "  internal_flash_end: 0x081FFFFF",
                "  wolfboot_base: 0x08000000",
                "  wolfboot_size: 0x00020000",
                "  primary_slot_base: 0x08020000",
                "  primary_slot_size: 0x000E0000",
                "  primary_slot_entry: 0x08020100",
                "  image_header_size: 0x00000100",
                "  update_slot_base: 0x08100000",
                "  update_slot_size: 0x000E0000",
                "  swap_metadata_base: 0x081E0000",
                "  swap_metadata_size: 0x00020000",
                "  sector_size_assumption: 0x00001000",
                "  wolfboot_partition_boot_address: 0x08020000",
                "  wolfboot_partition_size: 0x000E0000",
                "  wolfboot_partition_update_address: 0x08100000",
                "  wolfboot_partition_swap_address: 0x081E0000",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = experiment_cli.load_config(config_path)
    experiment_cli.validate_boot_config_for_inspection(config)

    layout = config["secure_boot_layout"]
    assert config["runnable"] is False
    assert config["flash_layout_status"] == "defined_phase_10d_planned_not_implemented"
    assert layout["decision_record"] == "docs/decisions/0003_secure_boot_flash_layout.md"
    assert layout["internal_flash_base"] == "0x08000000"
    assert layout["internal_flash_size"] == "0x00200000"
    assert layout["wolfboot_base"] == "0x08000000"
    assert layout["wolfboot_size"] == "0x00020000"
    assert layout["primary_slot_base"] == "0x08020000"
    assert layout["primary_slot_entry"] == "0x08020100"
    assert layout["update_slot_base"] == "0x08100000"
    assert layout["swap_metadata_base"] == "0x081E0000"
    assert layout["wolfboot_partition_boot_address"] == "0x08020000"
    assert layout["wolfboot_partition_update_address"] == "0x08100000"
    assert layout["wolfboot_partition_swap_address"] == "0x081E0000"



def test_application_signing_profile_is_loadable(tmp_path):
    experiment_cli = load_experiment_module()

    config_path = tmp_path / "wolfboot_ecdsa_p256_app.yaml"
    config_path.write_text(
        "\n".join(
            [
                "id: wolfboot_ecdsa_p256_app",
                "description: Test signing profile.",
                "input_elf: build/RelocatedDebug/stm32_basic_hal1.elf",
                "input_image: build/RelocatedDebug/stm32_basic_hal1.bin",
                "signed_image: build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
                "signature_algorithm: ecdsa_p256",
                "signature_size_bytes: 64",
                "image_version: 1",
                "private_key: secrets/wolfboot/ecdsa_p256_private_key.der",
                "binary_conversion:",
                "  enabled: true",
                "  command: arm-none-eabi-objcopy",
                "  args: \"-O binary {input_elf} {input_image}\"",
                "keygen:",
                "  enabled: true",
                "  working_dir: tools/wolfboot",
                "  command: tools/keytools/keygen",
                "  args: \"--ecc256 -g {private_key}\"",
                "sign:",
                "  working_dir: tools/wolfboot",
                "  command: tools/keytools/sign",
                "  args: \"--ecc256 {input_image} {private_key} {image_version}\"",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = experiment_cli.load_config(config_path)
    experiment_cli.validate_application_signing_profile_config(config)

    assert config["id"] == "wolfboot_ecdsa_p256_app"
    assert config["signature_algorithm"] == "ecdsa_p256"
    assert config["binary_conversion"]["enabled"] is True
    assert config["keygen"]["enabled"] is True
    assert config["keygen"]["working_dir"] == "tools/wolfboot"
    assert config["sign"]["working_dir"] == "tools/wolfboot"
    assert config["sign"]["command"] == "tools/keytools/sign"


def test_classical_signing_profile_model_is_loadable(tmp_path):
    experiment_cli = load_experiment_module()

    config_path = tmp_path / "classical_signing_profiles.yaml"
    config_path.write_text(
        "\n".join(
            [
                "id: classical_signing_profiles",
                "description: Phase 11.5a model.",
                "schema_version: 1",
                "model_phase: phase_11_5a_classical_profile_model",
                "benchmark_scope: secure_boot_classical_signing_algorithm",
                "minimum_comparison_scope:",
                "  ed25519:",
                "    algorithm: ED25519",
                "    signature_size_bytes: 64",
                "    runnable: false",
                "  ecc256:",
                "    algorithm: ECC256",
                "    signature_size_bytes: 64",
                "    runnable: true",
                "  rsa2048:",
                "    algorithm: RSA2048",
                "    signature_size_bytes: 256",
                "    runnable: false",
                "profiles:",
                "  ecc256_reference:",
                "    algorithm: ECC256",
                "    signature_algorithm: ecdsa_p256",
                "    signature_size_bytes: 64",
                "    signing_profile: configs/signing/wolfboot_ecdsa_p256_app.yaml",
                "    wolfboot_build_profile: configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml",
                "    experiment_profile: configs/experiments/wolfboot_ecdsa_p256_uart.yaml",
                "    runnable: true",
                "  ed25519_reserved:",
                "    algorithm: ED25519",
                "    runnable: false",
                "    unsupported_reason: Not implemented in Phase 11.5a.",
                "  rsa2048_reserved:",
                "    algorithm: RSA2048",
                "    runnable: false",
                "    unsupported_reason: Not implemented in Phase 11.5a.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = experiment_cli.load_config(config_path)
    experiment_cli.validate_classical_benchmark_profile_model_config(config)

    assert config["minimum_comparison_scope"]["ed25519"]["algorithm"] == "ED25519"
    assert config["minimum_comparison_scope"]["ecc256"]["algorithm"] == "ECC256"
    assert config["minimum_comparison_scope"]["rsa2048"]["algorithm"] == "RSA2048"
    assert config["profiles"]["ecc256_reference"]["runnable"] is True
    assert config["profiles"]["ed25519_reserved"]["runnable"] is False
    assert config["profiles"]["rsa2048_reserved"]["runnable"] is False
