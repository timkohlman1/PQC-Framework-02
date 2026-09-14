from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_result_dirs(results_dir: Path) -> list[Path]:
    """Return experiment run result directories, excluding build-record storage."""

    return sorted(
        path
        for path in results_dir.iterdir()
        if path.is_dir() and path.name != "builds"
    )


def _build_record_dir(results_dir: Path, build_number: int) -> Path:
    return results_dir / "builds" / str(build_number)


@pytest.mark.integration
def test_real_local_build_command_completes_without_flash_or_uart(
    tmp_path,
    pqc_require_capabilities,
):
    """Run the real local STM32/CMake build command when the toolchain is available.

    This test intentionally invokes the repository CLI through subprocess rather
    than mocking the build helper. It auto-skips when the local STM32/CMake/Ninja
    capability probes fail. Use --pqc-require-local-build to turn that skip into
    a failure.
    """

    pqc_require_capabilities("local_toolchain", strict_mode="local_build")

    repo_root = _repo_root()
    results_dir = tmp_path / "results"

    from framework.config_resolver import ConfigResolver
    generated = ConfigResolver(repo_root).materialize_campaign(
        "baseline", repo_root / ".pqc-generated-state" / "campaigns" / "baseline"
    )
    experiment_path = sorted((generated / "cases").glob("*.yaml"))[0]

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/experiment.py",
            "build",
            "--experiment",
            str(experiment_path),
            "--results-dir",
            str(results_dir),
            "--force",
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

    result_dirs = _run_result_dirs(results_dir)
    assert len(result_dirs) == 1

    result_dir = result_dirs[0]
    manifest_path = result_dir / "manifest.json"
    build_log_path = result_dir / "build.log"

    assert manifest_path.is_file()
    assert build_log_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["result"] == "build_passed"
    assert manifest["build_number"] is None
    assert manifest["build"]["purpose"] == "automated_test"
    assert isinstance(manifest["build"]["identity"], str)
    assert manifest["build"]["identity"]
    assert manifest["firmware"]["artifact"] == "build/Release/stm32_basic_hal1.elf"
    assert manifest["firmware"]["artifact_exists"] is True
    assert isinstance(manifest["firmware"]["sha256"], str)
    assert len(manifest["firmware"]["sha256"]) == 64
    assert manifest["build"]["configure_preset"] == "Release"
    assert manifest["build"]["build_preset"] == "Release"
    assert manifest["build"]["return_code"] == 0
    assert manifest["build"]["log"] == "build.log"

    build_record_dir = Path(manifest["build"]["record_path"])
    build_record_manifest_path = Path(manifest["build"]["record_manifest"])
    build_record_log_path = build_record_dir / "build.log"
    build_record_elf_path = build_record_dir / "firmware.elf"

    assert build_record_manifest_path == build_record_dir / "manifest.json"
    assert build_record_dir.is_dir()
    assert build_record_manifest_path.is_file()
    assert build_record_log_path.is_file()
    assert build_record_elf_path.is_file()

    build_log = build_log_path.read_text(encoding="utf-8")

    assert "Build purpose: automated_test" in build_log
    assert "Build number: unavailable" in build_log
    assert "Command: cmake --preset Release" in build_log
    assert "Command: cmake --build --preset Release" in build_log
    assert "Final return code: 0" in build_log
    assert "Output ELF exists: true" in build_log
    assert f"Output ELF SHA-256: {manifest['firmware']['sha256']}" in build_log

    build_record_manifest = json.loads(
        build_record_manifest_path.read_text(encoding="utf-8")
    )

    assert build_record_manifest["record_type"] == "automated_test_build"
    assert build_record_manifest["build_number"] is None
    assert build_record_manifest["purpose"] == "automated_test"
    assert build_record_manifest["reusable_by_normal_workflows"] is False
    assert build_record_manifest["build_identity"] == manifest["build"]["identity"]
    assert build_record_manifest["experiment"] == manifest["experiment"]
    assert build_record_manifest["board"] == manifest["board"]
    assert build_record_manifest["build"]["purpose"] == "automated_test"
    assert build_record_manifest["build"]["identity"] == manifest["build"]["identity"]
    assert build_record_manifest["build"]["return_code"] == 0
    assert build_record_manifest["build"]["log"] == "build.log"
    assert build_record_manifest["build"]["artifact_identity_algorithm"] == "sha256-elf"
    assert (
        build_record_manifest["build"]["artifact_identity"]
        == manifest["firmware"]["sha256"]
    )
    assert build_record_manifest["firmware"]["sha256"] == manifest["firmware"]["sha256"]
    assert build_record_manifest["firmware"]["result_artifacts"]["elf"]["path"] == "firmware.elf"
    assert (
        build_record_manifest["firmware"]["result_artifacts"]["elf"]["sha256"]
        == manifest["firmware"]["sha256"]
    )


@pytest.mark.integration
def test_debug_and_relocated_cmake_presets_build_with_freertos(
    pqc_require_capabilities,
):
    """Build both application presets after FreeRTOS generation.

    This test verifies that the generated FreeRTOS middleware and CMSIS-RTOS
    sources compile in both the direct-flash Debug build and the relocated
    post-secureboot application build. It does not flash hardware or access
    UART/gateway resources.
    """

    pqc_require_capabilities("local_toolchain", strict_mode="local_build")

    repo_root = _repo_root()

    for preset in ("Debug", "Release"):
        configure = subprocess.run(
            ["cmake", "--preset", preset],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )

        assert configure.returncode == 0, (
            f"Expected cmake configure preset {preset} to succeed.\n"
            f"stdout:\n{configure.stdout}\n"
            f"stderr:\n{configure.stderr}"
        )

        build = subprocess.run(
            ["cmake", "--build", "--preset", preset],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
        )

        assert build.returncode == 0, (
            f"Expected cmake build preset {preset} to succeed.\n"
            f"stdout:\n{build.stdout}\n"
            f"stderr:\n{build.stderr}"
        )
