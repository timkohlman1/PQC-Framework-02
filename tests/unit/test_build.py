from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path


def load_build_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = repo_root / "scripts" / "framework" / "build.py"
    spec = importlib.util.spec_from_file_location("framework_build", module_path)
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


def write_initial_manifest(result_dir: Path) -> None:
    result_dir.mkdir(parents=True)
    (result_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "2026-06-25_001_baseline_direct_uart",
                "timestamp": "2026-06-25T10:30:00+00:00",
                "experiment": "baseline_direct_uart",
                "board": "board_a",
                "gateway": "gateway",
                "boot_mode": "direct_flash",
                "transport_mode": "direct_uart",
                "network_profile": "none",
                "result": "pending",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def write_build_fingerprint_inputs(repo_root: Path) -> None:
    """Create the required fingerprint input set without invoking toolchains."""

    files = {
        "configs/experiments/baseline_direct_uart.yaml": "id: baseline_direct_uart\nboard: board_a\nhost: gateway\n",
        "configs/boards/board_a.yaml": "id: board_a\n",
        "configs/hosts/gateway.yaml": "id: gateway\n",
        "configs/boot/direct_flash.yaml": "id: direct_flash\nmode: direct_flash\nrunnable: true\n",
        "CMakeLists.txt": "cmake minimum\n",
        "CMakePresets.json": "{\"version\": 3}\n",
        "STM32L4R5XX_FLASH.ld": "flash linker script\n",
        "startup_stm32l4r5xx.s": "startup assembly\n",
        "stm32_basic_hal1.ioc": "CubeMX project source\n",
        "Core/Src/main.c": "int main(void) { return 0; }\n",
        "Core/Inc/main.h": "#pragma once\n",
        "Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c": "HAL driver source\n",
        "Drivers/CMSIS/Device/ST/STM32L4xx/Include/stm32l4r5xx.h": "CMSIS device header\n",
        "cmake/gcc-arm-none-eabi.cmake": "toolchain config\n",
    }

    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_build_command_construction_uses_cmake_presets():
    build = load_build_module()

    assert build.construct_configure_command("Debug") == ["cmake", "--preset", "Debug"]
    assert build.construct_build_command("Debug") == ["cmake", "--build", "--preset", "Debug"]


def test_execute_build_captures_command_results_without_invoking_cmake(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    artifact_path = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    write_initial_manifest(result_dir)

    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path):
        calls.append(command)
        assert cwd == repo_root
        if command == ["cmake", "--build", "--preset", "Debug"]:
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_text("fake elf", encoding="utf-8")
        return build.CommandExecution(
            command=command,
            return_code=0,
            stdout="fake stdout",
            stderr="fake stderr",
            duration_seconds=0.125,
        )

    def fake_git_runner(command: list[str], cwd: Path):
        assert cwd == repo_root
        if command == ["git", "rev-parse", "HEAD"]:
            return build.GitCommandExecution(command, 0, "abc123\n", "", 0.01)
        if command == ["git", "status", "--short"]:
            return build.GitCommandExecution(command, 0, "", "", 0.01)
        raise AssertionError(f"unexpected git command: {command}")

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=fake_runner,
        git_runner=fake_git_runner,
    )

    expected_sha256 = hashlib.sha256(b"fake elf").hexdigest()

    assert result.return_code == 0
    assert result.elf_path == artifact_path
    assert result.firmware_sha256 == expected_sha256
    assert result.build_number == 1
    assert result.result_artifacts["elf"]["path"] == "firmware.elf"
    assert result.build_record_dir == result_dir.parent / "builds" / "1"
    assert result.build_record_manifest_path == result_dir.parent / "builds" / "1" / "manifest.json"
    assert calls == [
        ["cmake", "--preset", "Debug"],
        ["cmake", "--build", "--preset", "Debug"],
    ]

    build_log = (result_dir / "build.log").read_text(encoding="utf-8")
    assert "fake stdout" in build_log
    assert "fake stderr" in build_log
    assert "Final return code: 0" in build_log
    assert f"Output ELF path: {artifact_path}" in build_log
    assert f"Output ELF SHA-256: {expected_sha256}" in build_log
    assert "Build number: 1" in build_log
    assert "Build fingerprint algorithm: sha256-build-inputs-v1" in build_log
    assert "- configs/experiments/baseline_direct_uart.yaml" in build_log
    assert "- configs/boot/direct_flash.yaml" in build_log
    assert "- Core/Inc/main.h" in build_log
    assert "- Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c" in build_log
    assert "- cmake/gcc-arm-none-eabi.cmake" in build_log
    assert "- stm32_basic_hal1.ioc" in build_log

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert (repo_root / ".build_number").read_text(encoding="utf-8") == "1\n"
    build_state = json.loads((repo_root / ".last_successful_build.json").read_text(encoding="utf-8"))
    assert build_state["schema_version"] == 1
    assert build_state["run_id"] == "2026-06-25_001_baseline_direct_uart"
    assert build_state["build_number"] == 1
    assert build_state["build"]["fingerprint"] == manifest["build"]["fingerprint"]
    assert build_state["build"]["fingerprint_algorithm"] == "sha256-build-inputs-v1"
    assert build_state["build"]["fingerprint_inputs"] == manifest["build"]["fingerprint_inputs"]
    assert build_state["firmware"]["artifact"] == "build/Debug/stm32_basic_hal1.elf"
    assert build_state["firmware"]["artifact_path"] == str(artifact_path)
    assert build_state["firmware"]["sha256"] == expected_sha256
    assert build_state["firmware"]["result_artifacts"]["elf"]["path"] == "firmware.elf"
    assert (result_dir / "firmware.elf").read_text(encoding="utf-8") == "fake elf"
    build_record_dir = result_dir.parent / "builds" / "1"
    build_record_manifest = json.loads((build_record_dir / "manifest.json").read_text(encoding="utf-8"))
    assert (build_record_dir / "build.log").is_file()
    assert (build_record_dir / "firmware.elf").read_text(encoding="utf-8") == "fake elf"
    assert build_record_manifest["record_type"] == "build"
    assert build_record_manifest["schema_version"] == 1
    assert build_record_manifest["build_number"] == 1
    assert build_record_manifest["result"] == "build_passed"
    assert build_record_manifest["experiment"] == "baseline_direct_uart"
    assert build_record_manifest["firmware"]["sha256"] == expected_sha256
    assert build_record_manifest["firmware"]["result_artifacts"]["elf"]["path"] == "firmware.elf"
    assert build_record_manifest["build"]["fingerprint"] == manifest["build"]["fingerprint"]
    assert build_record_manifest["build"]["log"] == "build.log"
    assert build_record_manifest["compatibility"]["source_run_id"] == "2026-06-25_001_baseline_direct_uart"
    assert build_record_manifest["compatibility"]["source_run_dir"] == str(result_dir)
    assert manifest["result"] == "build_passed"
    assert manifest["build_number"] == 1
    assert manifest["build"]["return_code"] == 0
    assert manifest["build"]["log"] == "build.log"
    assert manifest["build"]["record_path"] == str(result_dir.parent / "builds" / "1")
    assert manifest["build"]["record_manifest"] == str(result_dir.parent / "builds" / "1" / "manifest.json")
    assert manifest["build"]["fingerprint_algorithm"] == "sha256-build-inputs-v1"
    assert isinstance(manifest["build"]["fingerprint"], str)
    assert len(manifest["build"]["fingerprint"]) == 64
    assert "configs/experiments/baseline_direct_uart.yaml" in manifest["build"]["fingerprint_inputs"]
    assert "configs/boot/direct_flash.yaml" in manifest["build"]["fingerprint_inputs"]
    assert "Core/Inc/main.h" in manifest["build"]["fingerprint_inputs"]
    assert "Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c" in manifest["build"]["fingerprint_inputs"]
    assert "cmake/gcc-arm-none-eabi.cmake" in manifest["build"]["fingerprint_inputs"]
    assert "stm32_basic_hal1.ioc" in manifest["build"]["fingerprint_inputs"]
    assert manifest["build"]["fingerprint_inputs"] == sorted(manifest["build"]["fingerprint_inputs"])
    assert manifest["firmware"]["artifact"] == "build/Debug/stm32_basic_hal1.elf"
    assert manifest["firmware"]["artifact_exists"] is True
    assert manifest["firmware"]["sha256"] == expected_sha256
    assert manifest["firmware"]["result_artifacts"]["elf"]["path"] == "firmware.elf"
    assert manifest["firmware"]["result_artifacts"]["elf"]["sha256"] == expected_sha256
    assert manifest["firmware"]["result_artifacts"]["hex"]["copied"] is False
    assert manifest["firmware"]["result_artifacts"]["bin"]["copied"] is False
    assert manifest["source"] == {
        "git_commit": "abc123",
        "git_dirty": False,
        "git_status_available": True,
    }


def test_execute_build_skips_build_step_when_configure_fails(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    write_initial_manifest(result_dir)

    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path):
        calls.append(command)
        return build.CommandExecution(
            command=command,
            return_code=9,
            stdout="configure stdout",
            stderr="configure stderr",
            duration_seconds=0.125,
        )

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=fake_runner,
    )

    assert result.return_code == 9
    assert result.build is None
    assert result.firmware_sha256 is None
    assert calls == [["cmake", "--preset", "Debug"]]
    assert "Skipped because the configure step failed." in (result_dir / "build.log").read_text(
        encoding="utf-8"
    )
    assert not (repo_root / ".last_successful_build.json").exists()



def test_execute_build_fails_clearly_when_fingerprint_input_is_missing(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    repo_root.mkdir()
    write_initial_manifest(result_dir)

    def forbidden_runner(command: list[str], cwd: Path):
        raise AssertionError("CMake must not run when fingerprint inputs are missing")

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=forbidden_runner,
    )

    build_log = (result_dir / "build.log").read_text(encoding="utf-8")
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == build.FINGERPRINT_INPUT_ERROR_RETURN_CODE
    assert result.build is None
    assert result.build_fingerprint is None
    assert "Required build fingerprint input is missing" in build_log
    assert manifest["result"] == "build_failed"
    assert manifest["build"]["return_code"] == build.FINGERPRINT_INPUT_ERROR_RETURN_CODE
    assert "Required build fingerprint input is missing" in manifest["build"]["fingerprint_error"]

def test_execute_build_fails_clearly_when_build_number_file_is_malformed(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    write_initial_manifest(result_dir)
    (repo_root / ".build_number").write_text("not an integer\n", encoding="utf-8")

    def forbidden_runner(command: list[str], cwd: Path):
        raise AssertionError("CMake must not run when build number tracking fails")

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=forbidden_runner,
    )

    build_log = (result_dir / "build.log").read_text(encoding="utf-8")
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == build.BUILD_NUMBER_ERROR_RETURN_CODE
    assert result.build_number is None
    assert "Build number file contains a non-integer value" in build_log
    assert manifest["result"] == "build_failed"
    assert manifest["build_number"] is None
    assert "non-integer" in manifest["build"]["build_number_error"]


def test_run_build_command_reports_no_flash_or_network_actions(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = tmp_path / "configs" / "experiments" / "baseline_direct_uart.yaml"
    board_path = tmp_path / "configs" / "boards" / "board_a.yaml"
    host_path = tmp_path / "configs" / "hosts" / "gateway.yaml"
    boot_path = tmp_path / "configs" / "boot" / "direct_flash.yaml"
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)
    boot_path.parent.mkdir(parents=True)

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
    board_path.write_text(
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
    boot_path.write_text(
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

    host_path.write_text(
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

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    def fake_execute_build(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        assert kwargs["configure_preset"] == "Debug"
        assert kwargs["build_preset"] == "Debug"
        return FakeBuildResult()

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)

    exit_code = experiment_cli.run_build_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            artifact=None,
            capture_uart=False,
            uart_duration_seconds=10,
        )
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Firmware build completed" in output
    assert "No flash, UART access, SSH, hardware access, or network access was performed." in output


def test_run_build_flash_command_uses_one_result_directory_for_build_and_flash(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = tmp_path / "configs" / "experiments" / "baseline_direct_uart.yaml"
    board_path = tmp_path / "configs" / "boards" / "board_a.yaml"
    host_path = tmp_path / "configs" / "hosts" / "gateway.yaml"
    boot_path = tmp_path / "configs" / "boot" / "direct_flash.yaml"
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)
    boot_path.parent.mkdir(parents=True)

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
    board_path.write_text(
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
    boot_path.write_text(
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

    host_path.write_text(
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

    seen_result_dirs = []

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FakeFlashResult:
        return_code = 0
        duration_seconds = 0.5
        artifact_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        remote_artifact_path = "/tmp/stm32_basic_hal1.elf"
        stlink_serial = "123"
        log_path = tmp_path / "results" / "run" / "flash.log"
        provenance_status = "verified_build_match"

    fake_flash_result = FakeFlashResult()

    def fake_execute_build(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        assert kwargs["configure_preset"] == "Debug"
        assert kwargs["build_preset"] == "Debug"
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def fake_execute_flash(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        seen_result_dirs.append(kwargs["result_dir"])
        return fake_flash_result

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", fake_execute_flash)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            capture_uart=False,
            uart_duration_seconds=10,
        )
    )

    output = capsys.readouterr().out
    result_dir = seen_result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert len(seen_result_dirs) == 2
    assert seen_result_dirs[0] == seen_result_dirs[1]
    assert "Build-flash completed" in output
    assert "Build log:" in output
    assert "Flash log:" in output
    assert manifest["result"] == "build_flash_passed"
    assert manifest["build_flash"]["build_return_code"] == 0
    assert manifest["build_flash"]["flash_return_code"] == 0
    assert manifest["build_flash"]["flash_skipped"] is False


def test_run_build_flash_command_returns_flash_failure_after_successful_build(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = tmp_path / "configs" / "experiments" / "baseline_direct_uart.yaml"
    board_path = tmp_path / "configs" / "boards" / "board_a.yaml"
    host_path = tmp_path / "configs" / "hosts" / "gateway.yaml"
    boot_path = tmp_path / "configs" / "boot" / "direct_flash.yaml"
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)
    boot_path.parent.mkdir(parents=True)

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
    board_path.write_text(
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
    boot_path.write_text(
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

    host_path.write_text(
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

    seen_result_dirs = []

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FakeFlashResult:
        return_code = 7
        duration_seconds = 0.5
        artifact_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        remote_artifact_path = "/tmp/stm32_basic_hal1.elf"
        stlink_serial = "123"
        log_path = tmp_path / "results" / "run" / "flash.log"
        provenance_status = "verified_build_match"

    fake_flash_result = FakeFlashResult()

    def fake_execute_build(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def fake_execute_flash(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return fake_flash_result

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", fake_execute_flash)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            capture_uart=False,
            uart_duration_seconds=10,
        )
    )

    output = capsys.readouterr().out
    result_dir = seen_result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 7
    assert len(seen_result_dirs) == 2
    assert seen_result_dirs[0] == seen_result_dirs[1]
    assert "Build-flash failed during flash" in output
    assert "Flash log:" in output
    assert manifest["result"] == "build_flash_failed"
    assert manifest["build_flash"]["build_return_code"] == 0
    assert manifest["build_flash"]["flash_return_code"] == 7
    assert manifest["build_flash"]["flash_skipped"] is False
    assert manifest["build_flash"]["failure_stage"] == "flash"


def test_run_build_flash_command_skips_flash_when_build_fails(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = tmp_path / "configs" / "experiments" / "baseline_direct_uart.yaml"
    board_path = tmp_path / "configs" / "boards" / "board_a.yaml"
    host_path = tmp_path / "configs" / "hosts" / "gateway.yaml"
    boot_path = tmp_path / "configs" / "boot" / "direct_flash.yaml"
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)
    boot_path.parent.mkdir(parents=True)

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
    board_path.write_text(
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
    boot_path.write_text(
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

    host_path.write_text(
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

    seen_result_dirs = []

    class FakeBuildResult:
        return_code = 9
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    def fake_execute_build(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def forbidden_execute_flash(**kwargs):
        raise AssertionError("flash must not run after a failed build")

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", forbidden_execute_flash)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            capture_uart=False,
            uart_duration_seconds=10,
        )
    )

    output = capsys.readouterr().out
    result_dir = seen_result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 9
    assert "Build-flash failed during build" in output
    assert "Flash step skipped because the build failed." in output
    assert manifest["result"] == "build_flash_failed"
    assert manifest["build_flash"]["build_return_code"] == 9
    assert manifest["build_flash"]["flash_return_code"] is None
    assert manifest["build_flash"]["flash_skipped"] is True
    assert manifest["build_flash"]["failure_stage"] == "build"

def test_run_build_flash_command_captures_uart_after_successful_flash(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = tmp_path / "configs" / "experiments" / "baseline_direct_uart.yaml"
    board_path = tmp_path / "configs" / "boards" / "board_a.yaml"
    host_path = tmp_path / "configs" / "hosts" / "gateway.yaml"
    boot_path = tmp_path / "configs" / "boot" / "direct_flash.yaml"
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)
    boot_path.parent.mkdir(parents=True)

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
    board_path.write_text(
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
    boot_path.write_text(
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

    host_path.write_text(
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

    seen_result_dirs = []

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.25
        elf_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        log_path = tmp_path / "results" / "run" / "build.log"

    class FakeFlashResult:
        return_code = 0
        duration_seconds = 0.5
        artifact_path = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
        remote_artifact_path = "/tmp/stm32_basic_hal1.elf"
        stlink_serial = "123"
        log_path = tmp_path / "results" / "run" / "flash.log"
        provenance_status = "verified_build_match"

    class FakeUartResult:
        return_code = 0
        duration_seconds = 1.25
        log_path = tmp_path / "results" / "run" / "uart.log"

    fake_flash_result = FakeFlashResult()
    fake_uart_result = FakeUartResult()

    def fake_execute_build(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def fake_execute_flash(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return fake_flash_result

    def fake_execute_uart_capture(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        assert kwargs["duration_seconds"] == 12
        seen_result_dirs.append(kwargs["result_dir"])
        return fake_uart_result

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", fake_execute_flash)
    monkeypatch.setattr(experiment_cli, "execute_uart_capture", fake_execute_uart_capture)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            capture_uart=True,
            uart_duration_seconds=12,
        )
    )

    output = capsys.readouterr().out
    result_dir = seen_result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert len(seen_result_dirs) == 3
    assert seen_result_dirs[0] == seen_result_dirs[1] == seen_result_dirs[2]
    assert "UART log:" in output
    assert manifest["result"] == "build_flash_passed"
    assert manifest["build_flash"]["uart_return_code"] == 0
    assert manifest["build_flash"]["uart_log"] == "uart.log"
    assert manifest["build_flash"]["uart_skipped"] is False
    assert manifest["build_flash"]["failure_stage"] == "none"


def _record_matching_last_successful_state(build, repo_root: Path, artifact_path: Path, build_number: int = 7) -> str:
    fingerprint = build.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    firmware_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest() if artifact_path.exists() else "c" * 64
    build.record_last_successful_build_state(
        repo_root=repo_root,
        run_id="2026-06-25_000_baseline_direct_uart",
        build_number=build_number,
        build_fingerprint=fingerprint.fingerprint,
        build_fingerprint_algorithm=fingerprint.algorithm,
        build_fingerprint_inputs=fingerprint.inputs,
        firmware_artifact="build/Debug/stm32_basic_hal1.elf",
        firmware_artifact_path=str(artifact_path),
        firmware_sha256=firmware_sha256,
        result_artifacts={
            "elf": {
                "source_path": str(artifact_path),
                "path": "firmware.elf",
                "artifact_path": str(repo_root / "results" / "old" / "firmware.elf"),
                "sha256": firmware_sha256,
                "copied": True,
                "missing_reason": None,
            }
        },
    )
    return fingerprint.fingerprint


def _successful_runner_that_writes_artifact(build, artifact_path: Path, calls: list[list[str]]):
    def fake_runner(command: list[str], cwd: Path):
        calls.append(command)
        if command == ["cmake", "--build", "--preset", "Debug"]:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text("fresh elf", encoding="utf-8")
        return build.CommandExecution(
            command=command,
            return_code=0,
            stdout="ran command",
            stderr="",
            duration_seconds=0.1,
        )

    return fake_runner


def test_execute_build_skips_cmake_when_hash_state_and_elf_match(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    artifact_path = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("cached elf", encoding="utf-8")
    write_initial_manifest(result_dir)
    expected_fingerprint = _record_matching_last_successful_state(build, repo_root, artifact_path)

    def forbidden_runner(command: list[str], cwd: Path):
        raise AssertionError("CMake must not run when rebuild skip criteria are satisfied")

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=forbidden_runner,
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    build_log = (result_dir / "build.log").read_text(encoding="utf-8")

    assert result.return_code == 0
    assert result.build_skipped is True
    assert result.build_skip_reason == "cached_build_valid"
    assert result.build is None
    assert result.build_number == 7
    assert result.build_record_dir == result_dir.parent / "builds" / "7"
    assert result.build_record_manifest_path == result_dir.parent / "builds" / "7" / "manifest.json"
    assert not (repo_root / ".build_number").exists()
    assert (result_dir / "firmware.elf").read_text(encoding="utf-8") == "cached elf"
    assert (result_dir.parent / "builds" / "7" / "firmware.elf").read_text(encoding="utf-8") == "cached elf"
    assert manifest["result"] == "build_skipped"
    assert manifest["build_number"] == 7
    assert manifest["build"]["skipped"] is True
    assert manifest["build"]["skip_reason"] == "cached_build_valid"
    assert manifest["build"]["source_state_run_id"] == "2026-06-25_000_baseline_direct_uart"
    assert manifest["build"]["record_path"] == str(result_dir.parent / "builds" / "7")
    assert manifest["build"]["record_manifest"] == str(result_dir.parent / "builds" / "7" / "manifest.json")
    skipped_build_record_manifest = json.loads((result_dir.parent / "builds" / "7" / "manifest.json").read_text(encoding="utf-8"))
    assert skipped_build_record_manifest["result"] == "build_skipped"
    assert skipped_build_record_manifest["build"]["skipped"] is True
    assert skipped_build_record_manifest["build"]["source_state_run_id"] == "2026-06-25_000_baseline_direct_uart"
    assert manifest["build"]["fingerprint"] == expected_fingerprint
    assert manifest["firmware"]["artifact_exists"] is True
    assert manifest["firmware"]["result_artifacts"]["elf"]["path"] == "firmware.elf"
    assert "Build skipped: true" in build_log
    assert "Decision: skipped" in build_log


def test_execute_build_runs_cmake_when_last_successful_state_is_missing(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    artifact_path = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    write_initial_manifest(result_dir)
    calls: list[list[str]] = []

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=_successful_runner_that_writes_artifact(build, artifact_path, calls),
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.return_code == 0
    assert result.build_skipped is False
    assert calls == [["cmake", "--preset", "Debug"], ["cmake", "--build", "--preset", "Debug"]]
    assert manifest["result"] == "build_passed"
    assert manifest["build"]["skipped"] is False
    assert manifest["build"]["skip_reason"] == "missing_state"


def test_execute_build_runs_cmake_when_expected_elf_is_missing(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    artifact_path = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    write_initial_manifest(result_dir)
    _record_matching_last_successful_state(build, repo_root, artifact_path)
    calls: list[list[str]] = []

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=_successful_runner_that_writes_artifact(build, artifact_path, calls),
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.return_code == 0
    assert result.build_skipped is False
    assert calls == [["cmake", "--preset", "Debug"], ["cmake", "--build", "--preset", "Debug"]]
    assert manifest["build"]["skip_reason"] == "missing_elf"


def test_execute_build_runs_cmake_when_hash_changed(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    artifact_path = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("old elf", encoding="utf-8")
    write_initial_manifest(result_dir)
    _record_matching_last_successful_state(build, repo_root, artifact_path, build_number=3)
    state_path = repo_root / ".last_successful_build.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["build"]["fingerprint"] = "d" * 64
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    calls: list[list[str]] = []

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=_successful_runner_that_writes_artifact(build, artifact_path, calls),
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.return_code == 0
    assert result.build_skipped is False
    assert calls == [["cmake", "--preset", "Debug"], ["cmake", "--build", "--preset", "Debug"]]
    assert manifest["build"]["skip_reason"] == "changed_hash"


def test_execute_build_runs_cmake_when_last_successful_state_is_invalid(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    artifact_path = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("old elf", encoding="utf-8")
    write_initial_manifest(result_dir)
    (repo_root / ".last_successful_build.json").write_text("not json\n", encoding="utf-8")
    calls: list[list[str]] = []

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=_successful_runner_that_writes_artifact(build, artifact_path, calls),
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.return_code == 0
    assert result.build_skipped is False
    assert calls == [["cmake", "--preset", "Debug"], ["cmake", "--build", "--preset", "Debug"]]
    assert manifest["build"]["skip_reason"] == "invalid_state"
    assert "not valid JSON" in manifest["build"]["skip_detail"]


def test_execute_build_runs_cmake_when_previous_build_state_records_failure(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    artifact_path = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("old elf", encoding="utf-8")
    write_initial_manifest(result_dir)
    _record_matching_last_successful_state(build, repo_root, artifact_path)
    state_path = repo_root / ".last_successful_build.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["build"]["return_code"] = 1
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    calls: list[list[str]] = []

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        runner=_successful_runner_that_writes_artifact(build, artifact_path, calls),
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.return_code == 0
    assert result.build_skipped is False
    assert calls == [["cmake", "--preset", "Debug"], ["cmake", "--build", "--preset", "Debug"]]
    assert manifest["build"]["skip_reason"] == "previous_build_failed"


def test_execute_build_force_runs_cmake_even_when_skip_criteria_match(tmp_path):
    build = load_build_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-25_001_baseline_direct_uart"
    artifact_path = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("old elf", encoding="utf-8")
    write_initial_manifest(result_dir)
    _record_matching_last_successful_state(build, repo_root, artifact_path)
    calls: list[list[str]] = []

    result = build.execute_build(
        bundle=sample_bundle(),
        repo_root=repo_root,
        result_dir=result_dir,
        force=True,
        runner=_successful_runner_that_writes_artifact(build, artifact_path, calls),
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    build_log = (result_dir / "build.log").read_text(encoding="utf-8")
    assert result.return_code == 0
    assert result.build_skipped is False
    assert calls == [["cmake", "--preset", "Debug"], ["cmake", "--build", "--preset", "Debug"]]
    assert manifest["build"]["skip_reason"] == "force_requested"
    assert manifest["build"]["force"] is True
    assert "Force rebuild requested: true" in build_log


def test_run_command_reuses_verified_build_number_without_building(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = tmp_path / "configs" / "experiments" / "baseline_direct_uart.yaml"
    board_path = tmp_path / "configs" / "boards" / "board_a.yaml"
    host_path = tmp_path / "configs" / "hosts" / "gateway.yaml"
    boot_path = tmp_path / "configs" / "boot" / "direct_flash.yaml"
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)
    boot_path.parent.mkdir(parents=True)

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
    board_path.write_text(
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
    boot_path.write_text(
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

    host_path.write_text(
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

    artifact_path = tmp_path / "results" / "builds" / "7" / "firmware.elf"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("reused elf", encoding="utf-8")
    manifest_path = artifact_path.parent / "manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    firmware_sha256 = hashlib.sha256(b"reused elf").hexdigest()
    seen_result_dirs = []

    fake_verification = Namespace(
        status="verified_build_record",
        return_code=0,
        message="ok",
        build_number=7,
        record_dir=artifact_path.parent,
        manifest_path=manifest_path,
        artifact_path=artifact_path,
        firmware_sha256=firmware_sha256,
        build_fingerprint="a" * 64,
        build_fingerprint_algorithm="sha256-build-inputs-v1",
        current_build_fingerprint="a" * 64,
        current_build_fingerprint_algorithm="sha256-build-inputs-v1",
        current_build_fingerprint_error=None,
        manifest={},
    )

    fake_flash_result = Namespace(
        return_code=0,
        duration_seconds=0.5,
        artifact_path=tmp_path / "results" / "run" / "firmware.elf",
        remote_artifact_path="/tmp/firmware.elf",
        stlink_serial="123",
        log_path=tmp_path / "results" / "run" / "flash.log",
        provenance_status="verified_build_match",
    )

    fake_uart_result = Namespace(
        return_code=0,
        duration_seconds=1.0,
        log_path=tmp_path / "results" / "run" / "uart.log",
    )

    def forbidden_execute_build(**kwargs):
        raise AssertionError("run --build-number must not invoke the build helper")

    def fake_resolve_verified_build_record(**kwargs):
        assert kwargs["results_root"] == tmp_path / "results"
        assert kwargs["build_number"] == 7
        assert kwargs["repo_root"] == tmp_path
        return fake_verification

    def fake_execute_flash(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        assert kwargs["source_build_number"] == 7
        assert kwargs["source_build_manifest_path"] == manifest_path
        assert Path(kwargs["artifact_path_override"]).name == "firmware.elf"
        return fake_flash_result

    def fake_execute_uart_capture(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return fake_uart_result

    monkeypatch.setattr(experiment_cli, "execute_build", forbidden_execute_build)
    monkeypatch.setattr(
        experiment_cli,
        "resolve_verified_build_record",
        fake_resolve_verified_build_record,
    )
    monkeypatch.setattr(experiment_cli, "execute_flash", fake_execute_flash)
    monkeypatch.setattr(experiment_cli, "execute_uart_capture", fake_execute_uart_capture)

    exit_code = experiment_cli.run_full_baseline_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
            build_number=7,
            force=False,
            uart_duration_seconds=10,
        )
    )

    output = capsys.readouterr().out
    result_dir = seen_result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Build number: 7" in output
    assert (result_dir / "firmware.elf").read_text(encoding="utf-8") == "reused elf"
    assert manifest["result"] == "baseline_run_passed"
    assert manifest["build_number"] == 7
    assert manifest["build_reference"]["build_number"] == 7
    assert manifest["build_reference"]["artifact_sha256"] == firmware_sha256
    assert manifest["run"]["build_return_code"] is None
    assert manifest["run"]["referenced_build_number"] == 7
    assert manifest["run"]["referenced_build_artifact_sha256"] == firmware_sha256


def test_run_build_command_applies_artifact_override_for_relocated_provenance(
    tmp_path, monkeypatch
):
    experiment_cli = load_experiment_module()
    original_bundle = {
        "experiment": {
            "id": "baseline_direct_uart",
            "firmware": {
                "mode": "direct_flash",
                "artifact": "build/Debug/stm32_basic_hal1.elf",
            },
        },
        "board": {},
        "host": {},
        "boot": {},
    }
    captured = {}

    monkeypatch.setattr(
        experiment_cli, "load_experiment_bundle", lambda _path: original_bundle
    )
    monkeypatch.setattr(
        experiment_cli,
        "create_result_folder",
        lambda bundle, _results_dir: (
            captured.setdefault("bundle", bundle) or tmp_path / "results" / "run",
            {"run_id": "run"},
        ),
    )
    # The lambda above cannot return both values after setdefault cleanly; replace it.
    def fake_create_result_folder(bundle, _results_dir):
        captured["bundle"] = bundle
        result_dir = tmp_path / "results" / "run"
        result_dir.mkdir(parents=True, exist_ok=True)
        return result_dir, {"run_id": "run"}

    monkeypatch.setattr(experiment_cli, "create_result_folder", fake_create_result_folder)
    monkeypatch.setattr(
        experiment_cli, "repo_root_from_experiment_path", lambda _path: tmp_path
    )

    class FakeBuildResult:
        return_code = 0
        duration_seconds = 0.1
        elf_path = tmp_path / "build/RelocatedDebug/stm32_basic_hal1.elf"
        log_path = tmp_path / "results/run/build.log"
        build_skipped = False
        build_skip_reason = None
        build_number = 1
        build_record_dir = tmp_path / "results/builds/1"

    def fake_execute_build(**kwargs):
        captured["execute_bundle"] = kwargs["bundle"]
        assert kwargs["configure_preset"] == "RelocatedDebug"
        assert kwargs["build_preset"] == "RelocatedDebug"
        return FakeBuildResult()

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)

    exit_code = experiment_cli.run_build_command(
        Namespace(
            experiment=Path("configs/experiments/baseline_direct_uart.yaml"),
            results_dir=tmp_path / "results",
            configure_preset="RelocatedDebug",
            build_preset="RelocatedDebug",
            artifact=Path("build/RelocatedDebug/stm32_basic_hal1.elf"),
            force=False,
        )
    )

    assert exit_code == 0
    expected = "build/RelocatedDebug/stm32_basic_hal1.elf"
    assert captured["bundle"]["experiment"]["firmware"]["artifact"] == expected
    assert captured["execute_bundle"]["experiment"]["firmware"]["artifact"] == expected
    assert original_bundle["experiment"]["firmware"]["artifact"] == (
        "build/Debug/stm32_basic_hal1.elf"
    )
