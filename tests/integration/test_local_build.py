from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


RUN_LOCAL_BUILD_ENV = "PQC_RUN_LOCAL_BUILD_INTEGRATION"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_real_local_build_command_completes_without_flash_or_uart(tmp_path):
    """Run the real local STM32/CMake build command when explicitly enabled.

    This test intentionally invokes the repository CLI through subprocess rather
    than mocking the build helper. It is skipped by default because it requires
    the local STM32/CMake/Ninja toolchain that unit tests must not require.
    """

    if os.environ.get(RUN_LOCAL_BUILD_ENV) != "1":
        pytest.skip(f"Set {RUN_LOCAL_BUILD_ENV}=1 to run the local build integration test.")

    repo_root = _repo_root()
    results_dir = tmp_path / "results"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/experiment.py",
            "build",
            "--experiment",
            "configs/experiments/baseline_direct_uart.yaml",
            "--results-dir",
            str(results_dir),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, (
        "Expected the real local build command to succeed.\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )

    assert "Firmware build completed" in completed.stdout
    assert "No flash, UART access, SSH, hardware access, or network access was performed." in completed.stdout

    result_dirs = [path for path in results_dir.iterdir() if path.is_dir()]
    assert len(result_dirs) == 1

    result_dir = result_dirs[0]
    manifest_path = result_dir / "manifest.json"
    build_log_path = result_dir / "build.log"

    assert manifest_path.is_file()
    assert build_log_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["result"] == "build_passed"
    assert manifest["firmware"]["artifact"] == "build/Debug/stm32_basic_hal1.elf"
    assert manifest["firmware"]["artifact_exists"] is True
    assert manifest["build"]["configure_preset"] == "Debug"
    assert manifest["build"]["build_preset"] == "Debug"
    assert manifest["build"]["return_code"] == 0
    assert manifest["build"]["log"] == "build.log"

    build_log = build_log_path.read_text(encoding="utf-8")

    assert "Command: cmake --preset Debug" in build_log
    assert "Command: cmake --build --preset Debug" in build_log
    assert "Final return code: 0" in build_log
    assert "Output ELF exists: true" in build_log
