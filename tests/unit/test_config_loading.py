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
    