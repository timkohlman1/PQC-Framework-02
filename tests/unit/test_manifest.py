from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path


def load_manifest_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "framework" / "manifest.py"
    spec = importlib.util.spec_from_file_location("manifest", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_bundle() -> dict[str, dict[str, object]]:
    return {
        "experiment": {
            "id": "baseline_direct_uart",
            "description": "Test experiment.",
            "board": "board_a",
            "host": "gateway",
            "boot": "direct_flash",
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
            "uart": {
                "baud": 115200,
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


def write_sample_configs(configs_root: Path) -> Path:
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

    return experiment_path


def test_next_run_id_uses_date_and_next_sequence(tmp_path):
    manifest = load_manifest_module()
    results_root = tmp_path / "results"
    results_root.mkdir()
    (results_root / "2026-06-25_001_baseline_direct_uart").mkdir()
    (results_root / "2026-06-25_002_other_experiment").mkdir()
    (results_root / "not-a-run-id").mkdir()

    run_id = manifest.next_run_id(
        "baseline_direct_uart",
        results_root,
        datetime(2026, 6, 25, 10, 30, tzinfo=timezone.utc),
    )

    assert run_id == "2026-06-25_003_baseline_direct_uart"


def test_build_manifest_contains_initial_fields():
    manifest = load_manifest_module()
    timestamp = datetime(2026, 6, 25, 10, 30, tzinfo=timezone.utc)

    data = manifest.build_manifest(sample_bundle(), "2026-06-25_001_baseline_direct_uart", timestamp)

    assert data == {
        "run_id": "2026-06-25_001_baseline_direct_uart",
        "timestamp": "2026-06-25T10:30:00+00:00",
        "experiment": "baseline_direct_uart",
        "board": "board_a",
        "gateway": "gateway",
        "boot_mode": "direct_flash",
        "transport_mode": "direct_uart",
        "network_profile": "none",
        "result": "pending",
    }


def test_create_result_folder_writes_manifest_and_notes(tmp_path):
    manifest = load_manifest_module()
    results_root = tmp_path / "results"
    timestamp = datetime(2026, 6, 25, 10, 30, tzinfo=timezone.utc)

    result_dir, data = manifest.create_result_folder(sample_bundle(), results_root, timestamp)

    assert result_dir.name == "2026-06-25_001_baseline_direct_uart"
    assert (result_dir / "manifest.json").is_file()
    assert (result_dir / "notes.md").is_file()

    written_manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert written_manifest == data
    assert written_manifest["result"] == "pending"
    assert "Add manual observations" in (result_dir / "notes.md").read_text(encoding="utf-8")


def test_create_run_command_creates_result_folder_without_hardware_actions(tmp_path, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    results_root = tmp_path / "results"

    exit_code = experiment_cli.run_create_run_command(
        Namespace(experiment=experiment_path, results_dir=results_root)
    )

    output = capsys.readouterr().out
    result_dirs = list(results_root.iterdir())

    assert exit_code == 0
    assert len(result_dirs) == 1
    assert (result_dirs[0] / "manifest.json").is_file()
    assert (result_dirs[0] / "notes.md").is_file()
    assert "No build, flash, UART access, SSH, hardware access, or network access was performed." in output
