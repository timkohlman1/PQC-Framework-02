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
    experiments_dir = configs_root / "experiments"

    boards_dir.mkdir(parents=True)
    hosts_dir.mkdir(parents=True)
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
        