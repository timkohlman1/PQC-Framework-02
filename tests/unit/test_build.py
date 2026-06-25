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
        "CMakeLists.txt": "cmake minimum\n",
        "CMakePresets.json": "{\"version\": 3}\n",
        "STM32L4R5XX_FLASH.ld": "flash linker script\n",
        "startup_stm32l4r5xx.s": "startup assembly\n",
        "Core/Src/main.c": "int main(void) { return 0; }\n",
        "Core/Inc/main.h": "#pragma once\n",
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
    assert "Build fingerprint algorithm: sha256-build-inputs-v1" in build_log
    assert "- configs/experiments/baseline_direct_uart.yaml" in build_log
    assert "- Core/Inc/main.h" in build_log
    assert "- cmake/gcc-arm-none-eabi.cmake" in build_log

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result"] == "build_passed"
    assert manifest["build"]["return_code"] == 0
    assert manifest["build"]["log"] == "build.log"
    assert manifest["build"]["fingerprint_algorithm"] == "sha256-build-inputs-v1"
    assert isinstance(manifest["build"]["fingerprint"], str)
    assert len(manifest["build"]["fingerprint"]) == 64
    assert "configs/experiments/baseline_direct_uart.yaml" in manifest["build"]["fingerprint_inputs"]
    assert "Core/Inc/main.h" in manifest["build"]["fingerprint_inputs"]
    assert "cmake/gcc-arm-none-eabi.cmake" in manifest["build"]["fingerprint_inputs"]
    assert manifest["build"]["fingerprint_inputs"] == sorted(manifest["build"]["fingerprint_inputs"])
    assert manifest["firmware"]["artifact"] == "build/Debug/stm32_basic_hal1.elf"
    assert manifest["firmware"]["artifact_exists"] is True
    assert manifest["firmware"]["sha256"] == expected_sha256
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


def test_run_build_command_reports_no_flash_or_network_actions(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    experiment_path = tmp_path / "configs" / "experiments" / "baseline_direct_uart.yaml"
    board_path = tmp_path / "configs" / "boards" / "board_a.yaml"
    host_path = tmp_path / "configs" / "hosts" / "gateway.yaml"
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)

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
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)

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

    def fake_execute_build(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        assert kwargs["configure_preset"] == "Debug"
        assert kwargs["build_preset"] == "Debug"
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def fake_execute_flash(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeFlashResult()

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", fake_execute_flash)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
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
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)

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

    def fake_execute_build(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeBuildResult()

    def fake_execute_flash(**kwargs):
        seen_result_dirs.append(kwargs["result_dir"])
        return FakeFlashResult()

    monkeypatch.setattr(experiment_cli, "execute_build", fake_execute_build)
    monkeypatch.setattr(experiment_cli, "execute_flash", fake_execute_flash)

    exit_code = experiment_cli.run_build_flash_command(
        Namespace(
            experiment=experiment_path,
            results_dir=tmp_path / "results",
            configure_preset=None,
            build_preset="Debug",
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
    experiment_path.parent.mkdir(parents=True)
    board_path.parent.mkdir(parents=True)
    host_path.parent.mkdir(parents=True)

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