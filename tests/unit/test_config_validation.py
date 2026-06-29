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

