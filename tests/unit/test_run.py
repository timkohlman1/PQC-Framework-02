from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path


def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli_run", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_sample_configs(configs_root: Path) -> Path:
    (configs_root / "boards").mkdir(parents=True)
    (configs_root / "hosts").mkdir(parents=True)
    (configs_root / "boot").mkdir(parents=True)
    (configs_root / "experiments").mkdir(parents=True)

    (configs_root / "boards" / "board_a.yaml").write_text(
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
    (configs_root / "boot" / "direct_flash.yaml").write_text(
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

    (configs_root / "hosts" / "gateway.yaml").write_text(
        "\n".join(
            [
                "id: gateway",
                "alias: pqc-gateway1",
                "user: timk",
                "description: Test gateway.",
                "flash:",
                "  helper: flash-stm32a",
                "reset:",
                "  helper: reset-stm32a",
                "uart:",
                "  device: /dev/example",
                "  baud: 115200",
                "",
            ]
        ),
        encoding="utf-8",
    )
    experiment_path = configs_root / "experiments" / "baseline_direct_uart.yaml"
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


def args_for(experiment_path: Path, results_dir: Path) -> Namespace:
    return Namespace(
        experiment=experiment_path,
        results_dir=results_dir,
        configure_preset=None,
        build_preset="Debug",
        uart_duration_seconds=10,
        boot_mode="direct_flash",
        boot_algorithm=None,
        target_profile=Path("configs/targets/stm32l4r5_wolfboot.yaml"),
        build_number=None,
        force=False,
    )


def test_run_command_success_orchestrates_all_stages_in_one_result_directory(
    tmp_path, monkeypatch, capsys
):
    cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    results_dir = tmp_path / "results"
    seen_result_dirs = []

    class BuildResult:
        return_code = 0
        duration_seconds = 0.1
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FlashResult:
        return_code = 0
        duration_seconds = 0.2
        log_path = tmp_path / "results" / "run" / "flash.log"

    class UartResult:
        return_code = 0
        duration_seconds = 0.3
        log_path = tmp_path / "results" / "run" / "uart.log"

    def fake_build(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return BuildResult()

    def fake_copy(artifact_path, result_dir):
        assert artifact_path == BuildResult.elf_path
        seen_result_dirs.append(result_dir)
        copied = result_dir / BuildResult.elf_path.name
        copied.write_bytes(b"elf")
        return copied

    def fake_flash(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        assert kwargs["source_build_run_id"] == kwargs["result_dir"].name
        return FlashResult()

    def fake_uart(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        assert kwargs["restart_command"] == "reset-stm32a"
        return UartResult()

    monkeypatch.setattr(cli, "execute_build", fake_build)
    monkeypatch.setattr(cli, "copy_artifact_to_result", fake_copy)
    monkeypatch.setattr(cli, "execute_flash", fake_flash)
    monkeypatch.setattr(cli, "execute_uart_capture", fake_uart)

    exit_code = cli.run_full_baseline_command(args_for(experiment_path, results_dir))

    assert exit_code == 0
    assert len(seen_result_dirs) == 4
    assert all(path == seen_result_dirs[0] for path in seen_result_dirs)
    manifest = json.loads((seen_result_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result"] == "baseline_run_passed"
    assert manifest["run"]["failure_stage"] == "none"
    assert manifest["run"]["build_return_code"] == 0
    assert manifest["run"]["artifact_copy_return_code"] == 0
    assert manifest["run"]["flash_return_code"] == 0
    assert manifest["run"]["uart_return_code"] == 0
    assert manifest["run"]["copied_artifact"] == "stm32_basic_hal1.elf"
    assert manifest["firmware"]["result_artifact"] == "stm32_basic_hal1.elf"
    assert "Baseline run passed" in capsys.readouterr().out


def test_run_command_stops_after_build_failure(tmp_path, monkeypatch):
    cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    result_dirs = []

    class BuildResult:
        return_code = 4
        duration_seconds = 0.1
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    def fake_build(**kwargs):
        result_dirs.append(kwargs["result_dir"])
        return BuildResult()

    monkeypatch.setattr(cli, "execute_build", fake_build)
    monkeypatch.setattr(cli, "copy_artifact_to_result", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("copy must not run")))
    monkeypatch.setattr(cli, "execute_flash", lambda **kwargs: (_ for _ in ()).throw(AssertionError("flash must not run")))
    monkeypatch.setattr(cli, "execute_uart_capture", lambda **kwargs: (_ for _ in ()).throw(AssertionError("uart must not run")))

    exit_code = cli.run_full_baseline_command(args_for(experiment_path, tmp_path / "results"))
    manifest = json.loads((result_dirs[0] / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 4
    assert manifest["result"] == "baseline_run_failed"
    assert manifest["run"]["failure_stage"] == "build"
    assert manifest["run"]["flash_return_code"] is None
    assert manifest["run"]["uart_return_code"] is None


def test_run_command_stops_after_flash_failure_and_marks_uart_skipped(tmp_path, monkeypatch):
    cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    result_dirs = []

    class BuildResult:
        return_code = 0
        duration_seconds = 0.1
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FlashResult:
        return_code = 7
        duration_seconds = 0.2
        log_path = tmp_path / "results" / "run" / "flash.log"

    def fake_build(**kwargs):
        result_dirs.append(kwargs["result_dir"])
        return BuildResult()

    monkeypatch.setattr(cli, "execute_build", fake_build)
    monkeypatch.setattr(cli, "copy_artifact_to_result", lambda artifact_path, result_dir: result_dir / "stm32_basic_hal1.elf")
    monkeypatch.setattr(cli, "execute_flash", lambda **kwargs: FlashResult())
    monkeypatch.setattr(cli, "execute_uart_capture", lambda **kwargs: (_ for _ in ()).throw(AssertionError("uart must not run")))

    exit_code = cli.run_full_baseline_command(args_for(experiment_path, tmp_path / "results"))
    manifest = json.loads((result_dirs[0] / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 7
    assert manifest["result"] == "baseline_run_failed"
    assert manifest["run"]["failure_stage"] == "flash"
    assert manifest["run"]["uart_return_code"] is None
    assert manifest["uart"]["skipped"] is True
    assert manifest["uart"]["skip_reason"] == "flash_failed"


def test_run_command_returns_uart_marker_failure(tmp_path, monkeypatch):
    cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    result_dirs = []

    class BuildResult:
        return_code = 0
        duration_seconds = 0.1
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FlashResult:
        return_code = 0
        duration_seconds = 0.2
        log_path = tmp_path / "results" / "run" / "flash.log"

    class UartResult:
        return_code = 9
        duration_seconds = 0.3
        log_path = tmp_path / "results" / "run" / "uart.log"

    def fake_build(**kwargs):
        result_dirs.append(kwargs["result_dir"])
        return BuildResult()

    monkeypatch.setattr(cli, "execute_build", fake_build)
    monkeypatch.setattr(cli, "copy_artifact_to_result", lambda artifact_path, result_dir: result_dir / "stm32_basic_hal1.elf")
    monkeypatch.setattr(cli, "execute_flash", lambda **kwargs: FlashResult())
    monkeypatch.setattr(cli, "execute_uart_capture", lambda **kwargs: UartResult())

    exit_code = cli.run_full_baseline_command(args_for(experiment_path, tmp_path / "results"))
    manifest = json.loads((result_dirs[0] / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 9
    assert manifest["result"] == "baseline_run_failed"
    assert manifest["run"]["failure_stage"] == "uart"
    assert manifest["run"]["uart_return_code"] == 9


def test_run_subcommand_is_registered_with_mandatory_uart_capture():
    cli = load_experiment_module()
    parser = cli.build_arg_parser()
    args = parser.parse_args(
        [
            "run",
            "--experiment",
            "configs/experiments/baseline_direct_uart.yaml",
        ]
    )

    assert args.func is cli.run_full_baseline_command
    assert args.build_preset == "Debug"
    assert args.configure_preset is None
    assert args.uart_duration_seconds == cli.DEFAULT_CAPTURE_DURATION_SECONDS
    assert args.boot_mode == "direct_flash"
    assert args.boot_algorithm is None
    assert not hasattr(args, "capture_uart")


def test_run_subcommand_accepts_explicit_wolfboot_selection():
    cli = load_experiment_module()
    parser = cli.build_arg_parser()
    args = parser.parse_args(
        [
            "run",
            "--experiment",
            "configs/experiments/mqtt_tls_server_auth_st67_e2e.yaml",
            "--boot-mode",
            "wolfboot",
            "--boot-algorithm",
            "ecdsa_p256",
        ]
    )

    assert args.func is cli.run_full_baseline_command
    assert args.boot_mode == "wolfboot"
    assert args.boot_algorithm == "ecdsa_p256"
    assert args.target_profile == Path("configs/targets/stm32l4r5_wolfboot.yaml")


def test_run_rejects_boot_algorithm_for_direct_flash(tmp_path, capsys):
    cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    args = args_for(experiment_path, tmp_path / "results")
    args.boot_mode = "direct_flash"
    args.boot_algorithm = "ecdsa_p256"

    assert cli.run_full_baseline_command(args) == 2
    assert "--boot-algorithm is only valid" in capsys.readouterr().err


def test_wolfboot_application_build_uses_relocated_elf_before_signing():
    cli = load_experiment_module()
    bundle = {
        "experiment": {
            "firmware": {
                "mode": "wolfboot_ecdsa_p256",
                "artifact": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
            }
        },
        "board": {},
        "host": {},
        "boot": {},
    }
    signing_profile = {
        "input_image": "build/RelocatedDebug/stm32_basic_hal1.bin",
        "signed_image": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
    }

    build_bundle = cli._wolfboot_application_build_bundle(
        bundle=bundle,
        signing_profile=signing_profile,
    )

    assert build_bundle["experiment"]["firmware"]["artifact"] == (
        "build/RelocatedDebug/stm32_basic_hal1.elf"
    )
    assert bundle["experiment"]["firmware"]["artifact"] == (
        "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin"
    )


def test_wolfboot_signed_firmware_is_selected_only_after_signing():
    cli = load_experiment_module()
    bundle = {
        "experiment": {
            "firmware": {
                "mode": "wolfboot_ecdsa_p256",
                "artifact": "build/RelocatedDebug/stm32_basic_hal1.elf",
            }
        }
    }
    signing_profile = {
        "signed_image": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
    }

    cli._select_signed_firmware_artifact(
        bundle=bundle,
        signing_profile=signing_profile,
    )

    assert bundle["experiment"]["firmware"]["artifact"] == (
        "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin"
    )
