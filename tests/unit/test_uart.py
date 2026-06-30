from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path


def load_uart_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "uart.py"
    spec = importlib.util.spec_from_file_location("framework_uart", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
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
            "stlink": {"serial": "066EFF3932504E3043111818"},
            "uart": {"baud": 115200},
        },
        "boot": {
            "id": "direct_flash",
            "mode": "direct_flash",
            "description": "Direct flash baseline boot profile.",
            "runnable": True,
        },
        "host": {
            "id": "gateway",
            "alias": "pqc-gateway1",
            "user": "timk",
            "flash": {"helper": "flash-stm32a"},
            "reset": {"helper": "reset-stm32a"},
            "uart": {
                "device": "/dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02",
                "baud": 115200,
            },
        },
    }


def write_initial_manifest(result_dir: Path) -> None:
    result_dir.mkdir(parents=True)
    (result_dir / "manifest.json").write_text(
        json.dumps({"run_id": "run", "result": "pending"}) + "\n",
        encoding="utf-8",
    )


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
                '  serial: "066EFF3932504E3043111818"',
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

    (boot_dir / "direct_flash.yaml").write_text(
        "\n".join(
            [
                "id: direct_flash",
                "mode: direct_flash",
                "description: Direct flash baseline boot profile.",
                "runnable: true",
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


def test_constructs_bounded_uart_capture_command():
    uart = load_uart_module()

    command = uart.construct_ssh_uart_capture_command(
        "pqc-gateway1",
        "/dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02",
        115200,
        10,
    )

    assert command == [
        "ssh",
        "pqc-gateway1",
        "timeout 10s sh -c 'stty -F /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02 115200 cs8 -cstopb -parenb raw -echo && cat /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02'",
    ]


def test_constructs_monitor_with_delayed_restart_command():
    uart = load_uart_module()

    command = uart.construct_ssh_uart_monitor_with_restart_command(
        "pqc-gateway1",
        "/dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02",
        115200,
        10,
        "reset-stm32a",
    )

    assert command[0:2] == ["ssh", "pqc-gateway1"]
    assert "stty -F /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02 115200" in command[2]
    assert "sleep 0.2; reset-stm32a 1>&2" in command[2]
    assert "timeout 10s cat /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02" in command[2]
    assert command[2].index("stty -F") < command[2].index("sleep 0.2")
    assert command[2].index("sleep 0.2") < command[2].index("timeout 10s cat")



def test_parse_verification_time_ms_accepts_explicit_uart_markers():
    uart = load_uart_module()

    assert uart.parse_verification_time_ms("wolfBoot verification time: 17 ms\n") == 17
    assert uart.parse_verification_time_ms("verification_time_ms=23.5\n") == 23.5
    assert uart.parse_verification_time_ms("stm32-basic_hal1 boot v0.1.0\ntick\n") is None


def test_execute_uart_capture_can_restart_during_post_flash_capture(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    repo_root.mkdir()
    write_initial_manifest(result_dir)
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        assert cwd == repo_root
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout="stm32-basic_hal1 boot v0.1.0\ntick\n",
            stderr="reset ok",
            duration_seconds=10.0,
        )

    result = uart.execute_uart_capture(
        sample_bundle(),
        repo_root,
        result_dir,
        runner=fake_runner,
        duration_seconds=10,
        restart_command="reset-stm32a",
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == 0
    assert len(calls) == 1
    assert calls[0][0:2] == ["ssh", "pqc-gateway1"]
    assert "sleep 0.2; reset-stm32a 1>&2" in calls[0][2]
    assert "timeout 10s cat" in calls[0][2]
    assert manifest["uart"]["restart_command"] == "reset-stm32a"
    assert manifest["uart"]["restart_during_capture"] is True


def test_execute_uart_capture_passes_when_expected_markers_are_present(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    repo_root.mkdir()
    write_initial_manifest(result_dir)
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        assert cwd == repo_root
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout="wolfBoot verification time: 17 ms\nstm32-basic_hal1 boot v0.1.0\ntick\ntick\n",
            stderr="",
            duration_seconds=10.0,
        )

    result = uart.execute_uart_capture(
        sample_bundle(),
        repo_root,
        result_dir,
        runner=fake_runner,
        duration_seconds=10,
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    log = (result_dir / "uart.log").read_text(encoding="utf-8")

    assert result.return_code == 0
    assert result.boot_marker_present is True
    assert result.tick_present is True
    assert result.data_captured is True
    assert result.verification_time_ms == 17
    assert result.verification_time_source == "uart_explicit_verification_time_marker"
    assert len(calls) == 1
    assert manifest["result"] == "pass"
    assert manifest["uart"]["return_code"] == 0
    assert manifest["uart"]["capture_return_code"] == 124
    assert manifest["uart"]["boot_marker_present"] is True
    assert manifest["uart"]["tick_present"] is True
    assert manifest["uart"]["data_captured"] is True
    assert manifest["uart"]["verification_time_ms"] == 17
    assert manifest["boot_timing"]["verification_time_ms"] == 17
    assert manifest["boot_timing"]["verification_time_source"] == "uart_explicit_verification_time_marker"
    assert "verification_time_ms: 17" in log
    assert "Boot marker present: true" in log
    assert "Tick marker present: true" in log
    assert "stm32-basic_hal1 boot v0.1.0" in log




def test_execute_uart_capture_requires_secure_boot_marker_when_configured(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    repo_root.mkdir()
    write_initial_manifest(result_dir)
    bundle = sample_bundle()
    bundle["experiment"]["uart"]["expected_secure_boot_message"] = "stm32-basic_hal1 secure-boot app v0.1.0"

    def missing_secure_marker_runner(command, cwd):
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout="stm32-basic_hal1 boot v0.1.0\ntick\n",
            stderr="",
            duration_seconds=10.0,
        )

    missing_result = uart.execute_uart_capture(
        bundle,
        repo_root,
        result_dir,
        runner=missing_secure_marker_runner,
    )
    missing_manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert missing_result.return_code == uart.UART_MARKER_MISSING_RETURN_CODE
    assert missing_result.boot_marker_present is True
    assert missing_result.tick_present is True
    assert missing_result.secure_boot_marker_present is False
    assert missing_result.verification_time_ms is None
    assert missing_result.verification_time_source == "unavailable"
    assert missing_manifest["uart"]["secure_boot_marker_present"] is False
    assert missing_manifest["boot_timing"]["verification_time_ms"] is None
    assert missing_manifest["boot_timing"]["verification_time_source"] == "unavailable"

    def secure_marker_runner(command, cwd):
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout=(
                "stm32-basic_hal1 secure-boot app v0.1.0\n"
                "stm32-basic_hal1 boot v0.1.0\n"
                "tick\n"
            ),
            stderr="",
            duration_seconds=10.0,
        )

    passed_result = uart.execute_uart_capture(
        bundle,
        repo_root,
        result_dir,
        runner=secure_marker_runner,
    )
    passed_manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert passed_result.return_code == 0
    assert passed_result.secure_boot_marker_present is True
    assert passed_manifest["uart"]["secure_boot_marker_present"] is True
    assert "Secure-boot marker present: true" in (result_dir / "uart.log").read_text(encoding="utf-8")


def test_execute_uart_capture_fails_when_expected_marker_is_missing(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    repo_root.mkdir()
    write_initial_manifest(result_dir)

    def fake_runner(command, cwd):
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout="stm32-basic_hal1 boot v0.1.0\n",
            stderr="",
            duration_seconds=10.0,
        )

    result = uart.execute_uart_capture(
        sample_bundle(),
        repo_root,
        result_dir,
        runner=fake_runner,
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == uart.UART_MARKER_MISSING_RETURN_CODE
    assert result.boot_marker_present is True
    assert result.tick_present is False
    assert manifest["result"] == "fail"
    assert manifest["uart"]["boot_marker_present"] is True
    assert manifest["uart"]["tick_present"] is False


def test_execute_uart_capture_fails_when_ssh_command_fails(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    repo_root.mkdir()
    write_initial_manifest(result_dir)

    def fake_runner(command, cwd):
        return uart.CommandExecution(
            command=command,
            return_code=255,
            stdout="",
            stderr="ssh failed",
            duration_seconds=0.1,
        )

    result = uart.execute_uart_capture(
        sample_bundle(),
        repo_root,
        result_dir,
        runner=fake_runner,
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    log = (result_dir / "uart.log").read_text(encoding="utf-8")

    assert result.return_code == 255
    assert manifest["result"] == "fail"
    assert manifest["uart"]["capture_return_code"] == 255
    assert "ssh failed" in log


def test_execute_uart_monitor_writes_adhoc_log_and_passes_when_data_is_captured(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    repo_root.mkdir()
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout="tick\ntick\n",
            stderr="",
            duration_seconds=5.0,
        )

    result = uart.execute_uart_monitor(
        sample_bundle(),
        repo_root,
        results_root,
        runner=fake_runner,
        duration_seconds=5,
    )

    assert result.return_code == 0
    assert result.data_captured is True
    assert result.log_path.parent == results_root / "adhoc"
    assert result.log_path.name.startswith("uart_monitor_")
    assert result.log_path.suffix == ".log"
    assert len(calls) == 1
    assert "Ad hoc UART monitor log" in result.log_path.read_text(encoding="utf-8")
    assert not (results_root / "manifest.json").exists()


def test_execute_uart_monitor_fails_when_no_data_is_captured(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    repo_root.mkdir()

    def fake_runner(command, cwd):
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout="",
            stderr="",
            duration_seconds=5.0,
        )

    result = uart.execute_uart_monitor(
        sample_bundle(),
        repo_root,
        results_root,
        runner=fake_runner,
        duration_seconds=5,
    )

    assert result.return_code == uart.UART_NO_DATA_RETURN_CODE
    assert result.data_captured is False
    assert "Data captured: false" in result.log_path.read_text(encoding="utf-8")


def test_execute_uart_monitor_runs_delayed_restart_inside_monitor_command(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    repo_root.mkdir()
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        return uart.CommandExecution(command, 124, "stm32-basic_hal1 boot v0.1.0\ntick\n", "reset ok", 5.0)

    result = uart.execute_uart_monitor(
        sample_bundle(),
        repo_root,
        results_root,
        runner=fake_runner,
        duration_seconds=5,
        restart=True,
        restart_command="reset-stm32a",
    )

    assert result.return_code == 0
    assert result.restart is None
    assert len(calls) == 1
    assert calls[0][0:2] == ["ssh", "pqc-gateway1"]
    assert "sleep 0.2; reset-stm32a 1>&2" in calls[0][2]
    assert "timeout 5s cat" in calls[0][2]
    log = result.log_path.read_text(encoding="utf-8")
    assert "Restart requested: true" in log
    assert "Integrated into monitor command" in log
    assert "reset ok" in log


def test_execute_uart_monitor_fails_when_integrated_restart_command_fails(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    repo_root.mkdir()

    def fake_runner(command, cwd):
        return uart.CommandExecution(command, 127, "", "reset-stm32a: not found", 0.5)

    result = uart.execute_uart_monitor(
        sample_bundle(),
        repo_root,
        results_root,
        runner=fake_runner,
        duration_seconds=5,
        restart=True,
        restart_command="reset-stm32a",
    )

    assert result.return_code == 127
    assert result.data_captured is False
    log = result.log_path.read_text(encoding="utf-8")
    assert "reset-stm32a: not found" in log


def test_run_monitor_command_writes_adhoc_log_and_reports_status(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = write_sample_configs(tmp_path / "configs")
    results_root = tmp_path / "results"
    seen = []

    class FakeMonitorResult:
        return_code = 0
        duration_seconds = 0.25
        log_path = tmp_path / "results" / "adhoc" / "uart_monitor_20260625_120000.log"
        device = "/dev/example"
        baud = 115200
        requested_duration_seconds = 10
        restart_requested = False
        data_captured = True
        capture = type("Capture", (), {"return_code": 124})()

    def fake_execute_uart_monitor(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        assert kwargs["duration_seconds"] == 10
        assert kwargs["restart"] is False
        assert kwargs["restart_command"] == "reset-stm32a"
        seen.append(kwargs["results_root"])
        return FakeMonitorResult()

    monkeypatch.setattr(experiment_cli, "execute_uart_monitor", fake_execute_uart_monitor)

    exit_code = experiment_cli.run_monitor_command(
        Namespace(
            experiment=experiment_path,
            results_dir=results_root,
            duration_seconds=10,
            restart=False,
            restart_command=None,
        )
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert seen == [results_root]
    assert "UART monitor passed" in output
    assert "No result manifest, build, or flash action was performed." in output
