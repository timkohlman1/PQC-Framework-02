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



def test_default_runner_replaces_invalid_utf8_bytes(tmp_path: Path):
    uart = load_uart_module()

    result = uart.default_runner(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.stdout.buffer.write(bytes([98, 111, 111, 116, 10, 255, 116, 105, 99, 107, 10])); "
                "sys.stderr.buffer.write(bytes([119, 97, 114, 110, 105, 110, 103, 58, 255, 10]))"
            ),
        ],
        tmp_path,
    )

    assert result.return_code == 0
    assert result.stdout == "boot\n\ufffdtick\n"
    assert result.stderr == "warning:\ufffd\n"

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
    assert "timeout 0.2s cat /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02 >/dev/null 2>&1 || true" in command[2]
    assert "reset-stm32a 1>&2" in command[2]
    assert "timeout 10s cat /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02" in command[2]
    assert command[2].index("stty -F") < command[2].index("timeout 0.2s cat")
    assert command[2].index("timeout 0.2s cat") < command[2].index("timeout 10s cat")
    assert command[2].index("timeout 10s cat") < command[2].index("reset-stm32a 1>&2")



def test_parse_verification_timing_accepts_explicit_uart_markers():
    uart = load_uart_module()
    output = (
        "wolfBoot verification cycles: 1360000 cycles\n"
        "wolfBoot clock sysclk_hz: 64000000\n"
        "wolfBoot clock hclk_hz: 64000000\n"
        "wolfBoot clock pclk1_hz: 64000000\n"
        "wolfBoot clock pclk2_hz: 64000000\n"
        "wolfBoot verification result: 0\n"
        "application clock sysclk_hz: 120000000\n"
        "application clock hclk_hz: 120000000\n"
        "application clock pclk1_hz: 120000000\n"
        "application clock pclk2_hz: 120000000\n"
    )
    assert uart.parse_verification_cycles(output) == 1360000
    assert uart.parse_bootloader_clock_hz(output) == {
        "sysclk_hz": 64000000,
        "hclk_hz": 64000000,
        "pclk1_hz": 64000000,
        "pclk2_hz": 64000000,
    }
    assert uart.parse_application_clock_hz(output) == {
        "sysclk_hz": 120000000,
        "hclk_hz": 120000000,
        "pclk1_hz": 120000000,
        "pclk2_hz": 120000000,
    }
    evidence = uart._boot_timing_evidence(output)
    assert evidence["derived_verification_time_ms"] == 21.25
    assert evidence["derived_time_clock_source"] == "hclk_hz"
    assert evidence["verification_cycles_source"] == "uart_explicit_dwt_cycles_marker"
    assert uart.parse_verification_result_code(output) == 0


def test_parse_application_clock_hz_tolerates_capture_starting_mid_line():
    uart = load_uart_module()
    output = (
        "tapplication clock sysclk_hz: 120000000\n"
        "application clock hclk_hz: 120000000\n"
        "application clock pclk1_hz: 120000000\n"
        "application clock pclk2_hz: 120000000\n"
    )

    assert uart.parse_application_clock_hz(output) == {
        "sysclk_hz": 120000000,
        "hclk_hz": 120000000,
        "pclk1_hz": 120000000,
        "pclk2_hz": 120000000,
    }


def test_parse_application_memory_checkpoints_uses_explicit_exact_markers():
    uart = load_uart_module()
    output = (
        "FreeRTOS scheduler starting: heap_bytes=40000 default_task_stack_words=512\n"
        "application memory checkpoint: stage=pre_scheduler heap_total_bytes=40000 heap_free_bytes=37600 heap_min_ever_free_bytes=37600 heap_current_used_bytes=2400 heap_peak_used_bytes=2400\n"
        "application memory checkpoint: stage=default_task_runtime heap_total_bytes=40000 heap_free_bytes=37400 heap_min_ever_free_bytes=37200 heap_current_used_bytes=2600 heap_peak_used_bytes=2800\n"
        "application task stack: stage=default_task_runtime task=defaultTask total_bytes=2048 minimum_free_bytes=1500 peak_used_bytes=548\n"
        "application task stack: stage=default_task_runtime task=networkTask total_bytes=4096 minimum_free_bytes=3000 peak_used_bytes=1096\n"
    )

    checkpoints = uart.parse_application_memory_checkpoints(output)
    assert [checkpoint["stage"] for checkpoint in checkpoints] == [
        "pre_scheduler",
        "default_task_runtime",
    ]
    assert checkpoints[0]["task_stacks"] == []
    assert checkpoints[1]["heap_peak_used_bytes"] == 2800
    assert checkpoints[1]["task_stacks"] == [
        {
            "task": "defaultTask",
            "total_bytes": 2048,
            "minimum_free_bytes": 1500,
            "peak_used_bytes": 548,
        },
        {
            "task": "networkTask",
            "total_bytes": 4096,
            "minimum_free_bytes": 3000,
            "peak_used_bytes": 1096,
        },
    ]
    assert uart.parse_heap_used_bytes(output) == 2400
    evidence = uart._runtime_memory_evidence(output)
    assert evidence["heap_used_bytes"] == 2800
    assert evidence["heap_metric_source"] == "uart_explicit_application_memory_checkpoint"



def test_parse_application_memory_checkpoints_preserves_legacy_stack_fields():
    uart = load_uart_module()
    output = (
        "application memory checkpoint: stage=legacy heap_total_bytes=40000 "
        "heap_free_bytes=37000 heap_min_ever_free_bytes=36000 "
        "heap_current_used_bytes=3000 heap_peak_used_bytes=4000 "
        "task_stack_total_bytes=2048 task_stack_high_water_bytes=1500 "
        "task_stack_used_bytes=548\n"
    )

    checkpoints = uart.parse_application_memory_checkpoints(output)
    assert checkpoints[0]["task_stacks"] == [
        {
            "task": "current_task",
            "total_bytes": 2048,
            "minimum_free_bytes": 1500,
            "peak_used_bytes": 548,
        }
    ]

def test_heap_parser_does_not_infer_usage_from_scheduler_configuration():
    uart = load_uart_module()
    output = "FreeRTOS scheduler starting: heap_bytes=40000 default_task_stack_words=512\n"
    assert uart.parse_heap_used_bytes(output) is None
    assert uart.parse_application_memory_checkpoints(output) == []


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
    assert calls[0][0:2] == ["ssh", "timk@pqc-gateway1"]
    assert "timeout 0.2s cat " in calls[0][2]
    assert ">/dev/null 2>&1 || true" in calls[0][2]
    assert "reset-stm32a 1>&2" in calls[0][2]
    assert calls[0][2].index("timeout 10s cat") < calls[0][2].index("reset-stm32a 1>&2")
    assert "timeout 10s cat" in calls[0][2]
    assert manifest["uart"]["restart_command"] == "reset-stm32a"
    assert manifest["uart"]["restart_during_capture"] is True



def test_execute_uart_capture_does_not_accept_tick_as_substring(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    repo_root.mkdir()
    write_initial_manifest(result_dir)

    def fake_runner(command, cwd):
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout=(
                "stm32-basic_hal1 boot v0.1.0\n"
                "FreeRTOS scheduler starting: tick_hz=1000\n"
                "FreeRTOS defaultTask started: heartbeat active\n"
            ),
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

    assert result.return_code == uart.UART_MARKER_MISSING_RETURN_CODE
    assert result.boot_marker_present is True
    assert result.tick_present is False

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
            stdout=(
                "wolfBoot verification cycles: 1360000 cycles\n"
                "wolfBoot clock sysclk_hz: 64000000\n"
                "wolfBoot clock hclk_hz: 64000000\n"
                "wolfBoot clock pclk1_hz: 64000000\n"
                "wolfBoot clock pclk2_hz: 64000000\n"
                "wolfBoot verification cycles: 1360000 cycles\n"
                "wolfBoot clock hclk_hz: 64000000\n"
                "wolfBoot verification result: 0\n"
                "application clock sysclk_hz: 120000000\n"
                "application clock hclk_hz: 120000000\n"
                "application clock pclk1_hz: 120000000\n"
                "application clock pclk2_hz: 120000000\n"
                "application memory checkpoint: stage=pre_scheduler heap_total_bytes=40000 heap_free_bytes=37600 heap_min_ever_free_bytes=37600 heap_current_used_bytes=2400 heap_peak_used_bytes=2400\n"
                "application memory checkpoint: stage=default_task_start heap_total_bytes=40000 heap_free_bytes=37520 heap_min_ever_free_bytes=37440 heap_current_used_bytes=2480 heap_peak_used_bytes=2560\n"
                "application task stack: stage=default_task_start task=defaultTask total_bytes=2048 minimum_free_bytes=1600 peak_used_bytes=448\n"
                "application memory checkpoint: stage=default_task_runtime heap_total_bytes=40000 heap_free_bytes=37400 heap_min_ever_free_bytes=37200 heap_current_used_bytes=2600 heap_peak_used_bytes=2800\n"
                "application task stack: stage=default_task_runtime task=defaultTask total_bytes=2048 minimum_free_bytes=1500 peak_used_bytes=548\n"
                "application task stack: stage=default_task_runtime task=networkTask total_bytes=4096 minimum_free_bytes=3000 peak_used_bytes=1096\n"
                "stm32-basic_hal1 boot v0.1.0\n"
                "tick\n"
                "tick\n"
            ),
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
    assert result.derived_verification_time_ms == 21.25
    assert result.verification_cycles == 1360000
    assert result.bootloader_hclk_hz == 64000000
    assert result.application_clock_hz == {
        "sysclk_hz": 120000000,
        "hclk_hz": 120000000,
        "pclk1_hz": 120000000,
        "pclk2_hz": 120000000,
    }
    assert [checkpoint["stage"] for checkpoint in result.application_memory_checkpoints] == [
        "pre_scheduler",
        "default_task_start",
        "default_task_runtime",
    ]
    assert result.heap_used_bytes == 2800
    assert result.verification_result_code == 0
    assert result.verification_time_source == "framework_derived_from_uart_cycles_and_reported_hclk"
    assert len(calls) == 1
    assert manifest["result"] == "pass"
    assert manifest["uart"]["return_code"] == 0
    assert manifest["uart"]["capture_return_code"] == 124
    assert manifest["uart"]["boot_marker_present"] is True
    assert manifest["uart"]["tick_present"] is True
    assert manifest["uart"]["data_captured"] is True
    assert manifest["uart"]["derived_verification_time_ms"] == 21.25
    assert manifest["uart"]["verification_cycles"] == 1360000
    assert manifest["uart"]["bootloader_hclk_hz"] > 0
    assert manifest["uart"]["application_clock_hz"]["hclk_hz"] == 120000000
    assert manifest["application_clock"]["clock_hz"]["sysclk_hz"] == 120000000
    assert manifest["application_clock"]["source"] == "uart_reported_hal_rcc_from_running_default_task"
    assert manifest["runtime_memory"]["application_checkpoints"][-1]["heap_peak_used_bytes"] == 2800
    assert manifest["uart"]["application_memory_checkpoints"][-1]["task_stacks"][0]["peak_used_bytes"] == 548
    assert manifest["uart"]["verification_result_code"] == 0
    assert manifest["boot_timing"]["derived_verification_time_ms"] == 21.25
    assert manifest["boot_timing"]["verification_cycles"] == 1360000
    assert manifest["boot_timing"]["bootloader_hclk_hz"] > 0
    assert manifest["boot_timing"]["verification_result_code"] == 0
    assert manifest["boot_timing"]["verification_time_source"] == "framework_derived_from_uart_cycles_and_reported_hclk"
    assert "derived_verification_time_ms: 21.25" in log
    assert "verification_cycles: 1360000" in log
    assert "bootloader_hclk_hz: 64000000" in log
    assert "Application clock evidence" in log
    assert "application_hclk_hz: 120000000" in log
    assert "verification_result_code: 0" in log
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
    assert missing_result.derived_verification_time_ms is None
    assert missing_result.verification_cycles is None
    assert missing_result.bootloader_hclk_hz is None
    assert missing_result.application_clock_hz == {
        "sysclk_hz": None,
        "hclk_hz": None,
        "pclk1_hz": None,
        "pclk2_hz": None,
    }
    assert missing_result.application_memory_checkpoints == []
    assert missing_result.verification_result_code is None
    assert missing_result.verification_time_source == "unavailable"
    assert missing_manifest["uart"]["secure_boot_marker_present"] is False
    assert missing_manifest["boot_timing"]["derived_verification_time_ms"] is None
    assert missing_manifest["boot_timing"]["verification_cycles"] is None
    assert missing_manifest["boot_timing"]["bootloader_hclk_hz"] is None
    assert missing_manifest["boot_timing"]["verification_result_code"] is None
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
    assert calls[0][0:2] == ["ssh", "timk@pqc-gateway1"]
    assert "timeout 0.2s cat " in calls[0][2]
    assert ">/dev/null 2>&1 || true" in calls[0][2]
    assert "reset-stm32a 1>&2" in calls[0][2]
    assert calls[0][2].index("timeout 5s cat") < calls[0][2].index("reset-stm32a 1>&2")
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


def test_parse_wifi_dhcp_evidence_records_explicit_markers():
    from framework.uart import parse_wifi_dhcp_evidence
    evidence = parse_wifi_dhcp_evidence("ST67 Wi-Fi association: result=passed ssid=hiphopopotamus state=connected security=4 channel=6\nST67 DHCP: result=passed ipv4=192.168.1.42 gateway=192.168.1.1 netmask=255.255.255.0\n")
    assert evidence["association_success"] is True
    assert evidence["dhcp_success"] is True
    assert evidence["dhcp"]["ipv4"] == "192.168.1.42"


def test_execute_uart_capture_accepts_structured_tick_prefix(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    repo_root.mkdir()
    write_initial_manifest(result_dir)
    bundle = sample_bundle()
    bundle["experiment"]["uart"].pop("expected_tick_message", None)
    bundle["experiment"]["uart"]["expected_tick_prefix"] = "[tick="

    def fake_runner(command, cwd):
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout=(
                "[tick=0000000035] stm32-basic_hal1 boot v0.1.0\n"
                "[tick=0000006028] PQC_EXPERIMENT_COMPLETE experiment=plaintext status=done\n"
            ),
            stderr="",
            duration_seconds=10.0,
        )

    result = uart.execute_uart_capture(
        bundle,
        repo_root,
        result_dir,
        runner=fake_runner,
        duration_seconds=10,
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == 0
    assert result.tick_present is True
    assert manifest["uart"]["expected_tick_message"] is None
    assert manifest["uart"]["expected_tick_prefix"] == "[tick="


def test_execute_uart_capture_legacy_tick_marker_accepts_structured_prefix(tmp_path):
    uart = load_uart_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    repo_root.mkdir()
    write_initial_manifest(result_dir)

    def fake_runner(command, cwd):
        return uart.CommandExecution(
            command=command,
            return_code=124,
            stdout="[tick=0000000035] stm32-basic_hal1 boot v0.1.0\n",
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

    assert result.return_code == 0
    assert result.tick_present is True


def test_parse_final_ram_accounting_markers():
    uart = load_uart_module()
    output = (
        "[tick=10] PQC_RAM_LINKER_ACCOUNTING ram_total_bytes=196608 ram2_total_bytes=65536 "
        "ram3_total_bytes=393216 data_bytes=2048 bss_bytes=120000 ram_static_base_bytes=122048 "
        "linker_min_heap_bytes=512 linker_min_msp_bytes=1024 ram_linker_reserved_bytes=123584 "
        "ram_linker_unreserved_bytes=73024 ram3_workspace_reserved_bytes=98304 device_linker_ram_total_bytes=655360\n"
        "[tick=11] PQC_MEMORY_HIGH_WATERMARK freertos_heap_total_bytes=98304 "
        "freertos_heap_peak_used_bytes=86952 freertos_heap_min_free_bytes=11352 freertos_heap_final_free_bytes=44184 "
        "mldsa_workspace_total_bytes=98304 mldsa_workspace_peak_used_bytes=77824 "
        "mldsa_workspace_headroom_bytes=20480 mldsa_workspace_capacity_exceeded=0 mldsa_workspace_in_use=0 "
        "sbrk_capacity_bytes=73536 sbrk_peak_used_bytes=0 sbrk_final_used_bytes=0 sbrk_ever_called=0 "
        "msp_reserved_bytes=1024 msp_peak_used_bytes=1840 msp_headroom_bytes=0 msp_excess_bytes=816 "
        "msp_measurement_window_bytes=73536 msp_reservation_exceeded=1 msp_measurement_saturated=0 "
        "ram_observed_required_bytes=123888 ram_observed_headroom_bytes=72720 ram_observed_required_is_lower_bound=0 "
        "device_observed_workload_required_bytes=201712 device_observed_workload_required_is_lower_bound=0\n"
    )

    accounting = uart.parse_ram_accounting(output)
    assert accounting["linker"]["device_linker_ram_total_bytes"] == 655360
    assert accounting["linker"]["ram3_workspace_reserved_bytes"] == 98304
    assert accounting["runtime"]["sbrk_peak_used_bytes"] == 0
    assert accounting["runtime"]["msp_peak_used_bytes"] == 1840
    assert accounting["runtime"]["msp_excess_bytes"] == 816
    assert accounting["runtime"]["msp_measurement_saturated"] == 0
    assert accounting["runtime"]["ram_observed_required_bytes"] == 123888
    assert accounting["runtime"]["ram_observed_required_is_lower_bound"] == 0
    assert accounting["runtime"]["device_observed_workload_required_is_lower_bound"] == 0

    evidence = uart._runtime_memory_evidence(output)
    assert evidence["heap_used_bytes"] == 86952
    assert evidence["ram_accounting"] == accounting
    assert "does not reconstruct stack depth used before main()" in evidence["limitations"]
