from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SECURE_BOOT_EXPERIMENT_CONFIG = "configs/experiments/wolfboot_ecdsa_p256_uart.yaml"
SIGNING_PROFILE = "configs/signing/wolfboot_ecdsa_p256_app.yaml"
WOLFBOOT_ARTIFACT = "tools/wolfboot/wolfboot.elf"
SIGNED_APPLICATION_ARTIFACT = "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin"
EXPECTED_STLINK_SERIAL = "066EFF3932504E3043111818"
EXPECTED_BOOT_MODE = "wolfboot_ecdsa_p256"
EXPECTED_BOOT_CRYPTO = "ecdsa_p256"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_command(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_cli(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run_command(repo_root, [sys.executable, "scripts/experiment.py", *args])


def _skip_if_missing(path: Path, reason: str) -> None:
    if not path.exists():
        pytest.skip(f"{reason}: {path}")


def _secure_boot_result_dirs(results_dir: Path) -> list[Path]:
    """Return experiment run result directories, excluding helper evidence trees."""

    if not results_dir.exists():
        return []

    excluded_names = {"adhoc", "builds", "signing", "wolfboot-builds"}
    return sorted(
        path
        for path in results_dir.iterdir()
        if path.is_dir() and path.name not in excluded_names
    )


def _single_secure_boot_result_dir(results_dir: Path) -> Path:
    result_dirs = _secure_boot_result_dirs(results_dir)
    assert len(result_dirs) == 1
    return result_dirs[0]


def _prepare_signed_secure_boot_application(repo_root: Path, results_dir: Path) -> None:
    configure_completed = _run_command(repo_root, ["cmake", "--preset", "RelocatedDebug"])
    assert configure_completed.returncode == 0, (
        f"cmake configure stdout:\n{configure_completed.stdout}\n"
        f"cmake configure stderr:\n{configure_completed.stderr}"
    )

    build_completed = _run_command(repo_root, ["cmake", "--build", "--preset", "RelocatedDebug"])
    assert build_completed.returncode == 0, (
        f"cmake build stdout:\n{build_completed.stdout}\n"
        f"cmake build stderr:\n{build_completed.stderr}"
    )

    signing_completed = _run_cli(
        repo_root,
        [
            "sign-application",
            "--profile",
            SIGNING_PROFILE,
            "--results-dir",
            str(results_dir),
        ],
    )
    assert signing_completed.returncode == 0, (
        f"sign-application stdout:\n{signing_completed.stdout}\n"
        f"sign-application stderr:\n{signing_completed.stderr}"
    )
    assert (repo_root / SIGNED_APPLICATION_ARTIFACT).is_file()


def _assert_positive_secure_boot_manifest(manifest: dict) -> None:
    assert manifest["result"] == "secure_boot_positive_boot_evidence_passed"
    assert manifest["boot_mode"] == EXPECTED_BOOT_MODE
    assert manifest["boot_crypto"] == EXPECTED_BOOT_CRYPTO
    assert manifest["secure_boot_flash"]["return_code"] == 0
    assert manifest["secure_boot_flash"]["failure_stage"] == "none"
    assert manifest["secure_boot_flash"]["stlink_serial"] == EXPECTED_STLINK_SERIAL

    wolfboot = manifest["secure_boot_flash"]["wolfboot"]
    signed_application = manifest["secure_boot_flash"]["signed_application"]
    assert wolfboot["artifact_exists"] is True
    assert len(wolfboot["sha256"]) == 64
    assert wolfboot["offset"] == "0x08000000"
    assert wolfboot["scp_return_code"] == 0
    assert wolfboot["helper_return_code"] == 0
    assert signed_application["artifact_exists"] is True
    assert len(signed_application["sha256"]) == 64
    assert signed_application["offset"] == "0x08020000"
    assert signed_application["pass_offset_to_helper"] is True
    assert signed_application["scp_return_code"] == 0
    assert signed_application["helper_return_code"] == 0

    assert manifest["uart"]["return_code"] == 0
    assert manifest["uart"]["boot_marker_present"] is True
    assert manifest["uart"]["tick_present"] is True
    assert manifest["uart"]["secure_boot_marker_present"] is True
    assert manifest["uart"]["data_captured"] is True

    assert manifest["secure_boot_run"]["return_code"] == 0
    assert manifest["secure_boot_run"]["flash_return_code"] == 0
    assert manifest["secure_boot_run"]["uart_return_code"] == 0
    assert manifest["secure_boot_run"]["failure_stage"] == "none"
    assert manifest["secure_boot_run"]["boot_confirmed_from_uart_log"] is True
    assert manifest["secure_boot_run"]["boot_path_distinguished"] is True
    assert manifest["secure_boot_run"]["secure_boot_marker_present"] is True
    assert manifest["secure_boot_run"]["positive_boot_evidence_passed"] is True


def _restore_valid_secure_boot_application(repo_root: Path, results_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        repo_root,
        [
            "flash-secure-boot",
            "--experiment",
            SECURE_BOOT_EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
            "--uart-duration-seconds",
            "10",
        ],
    )


@pytest.mark.hardware
def test_secure_boot_build_sign_flash_uart_workflow(tmp_path, pqc_require_capabilities):
    """Build, sign, flash, and UART-check the Phase 10h secure-boot workflow.

    This hardware-dependent system workflow auto-skips unless the local build
    toolchain, SSH gateway, configured flash helper, and configured ST-LINK VCP
    UART device are available. It also requires an already-built wolfBoot ELF,
    because rebuilding wolfBoot belongs to the separate build-wolfboot workflow.

    The test validates positive secure-boot evidence by requiring the distinct
    secure-boot application UART marker, the normal boot marker, and the tick
    marker after the two-artifact flash workflow.
    """

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        "uart_device",
        strict_mode="hardware",
    )

    repo_root = _repo_root()
    results_dir = tmp_path / "results"

    _skip_if_missing(
        repo_root / SECURE_BOOT_EXPERIMENT_CONFIG,
        "secure-boot experiment config is missing",
    )
    _skip_if_missing(repo_root / SIGNING_PROFILE, "signing profile is missing")
    _skip_if_missing(
        repo_root / WOLFBOOT_ARTIFACT,
        "wolfBoot artifact is missing; run build-wolfboot first",
    )

    _prepare_signed_secure_boot_application(repo_root, results_dir)

    flash_completed = _run_cli(
        repo_root,
        [
            "flash-secure-boot",
            "--experiment",
            SECURE_BOOT_EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
            "--uart-duration-seconds",
            "10",
        ],
    )
    assert flash_completed.returncode == 0, (
        f"flash-secure-boot stdout:\n{flash_completed.stdout}\n"
        f"flash-secure-boot stderr:\n{flash_completed.stderr}"
    )

    result_dir = _single_secure_boot_result_dir(results_dir)
    manifest_path = result_dir / "manifest.json"
    flash_log_path = result_dir / "secure_boot_flash.log"
    uart_log_path = result_dir / "uart.log"

    assert manifest_path.is_file()
    assert flash_log_path.is_file()
    assert uart_log_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    _assert_positive_secure_boot_manifest(manifest)

    flash_log = flash_log_path.read_text(encoding="utf-8")
    assert "wolfBoot secure-boot flash log" in flash_log
    assert "signed_application artifact" in flash_log
    assert "0x08020000" in flash_log

    uart_log = uart_log_path.read_text(encoding="utf-8")
    assert "Boot marker present: true" in uart_log
    assert "Tick marker present: true" in uart_log
    assert "Secure-boot marker present: true" in uart_log
    assert "Data captured: true" in uart_log

@pytest.mark.hardware
def test_secure_boot_negative_corrupted_application_then_restore_workflow(
    tmp_path, pqc_require_capabilities
):
    """Flash a corrupted signed application and restore the valid image afterward.

    This hardware-dependent Phase 10j workflow auto-skips under the same
    capability rules as the positive secure-boot hardware test. It verifies that
    a result-local corrupted signed image does not produce the normal
    application markers, then flashes the valid signed application again so the
    board is left in the positive secure-boot state when restoration succeeds.
    """

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        "uart_device",
        strict_mode="hardware",
    )

    repo_root = _repo_root()
    results_dir = tmp_path / "results"

    _skip_if_missing(
        repo_root / SECURE_BOOT_EXPERIMENT_CONFIG,
        "secure-boot experiment config is missing",
    )
    _skip_if_missing(repo_root / SIGNING_PROFILE, "signing profile is missing")
    _skip_if_missing(
        repo_root / WOLFBOOT_ARTIFACT,
        "wolfBoot artifact is missing; run build-wolfboot first",
    )

    _prepare_signed_secure_boot_application(repo_root, results_dir)

    try:
        negative_completed = _run_cli(
            repo_root,
            [
                "flash-secure-boot",
                "--experiment",
                SECURE_BOOT_EXPERIMENT_CONFIG,
                "--results-dir",
                str(results_dir),
                "--uart-duration-seconds",
                "10",
                "--negative-corrupt-application",
            ],
        )
        assert negative_completed.returncode == 0, (
            f"negative flash-secure-boot stdout:\n{negative_completed.stdout}\n"
            f"negative flash-secure-boot stderr:\n{negative_completed.stderr}"
        )

        result_dirs = _secure_boot_result_dirs(results_dir)
        assert len(result_dirs) == 1
        result_dir = result_dirs[0]
        manifest_path = result_dir / "manifest.json"
        flash_log_path = result_dir / "secure_boot_flash.log"
        uart_log_path = result_dir / "uart.log"

        assert manifest_path.is_file()
        assert flash_log_path.is_file()
        assert uart_log_path.is_file()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert manifest["result"] == "secure_boot_negative_test_passed"
        assert manifest["boot_mode"] == EXPECTED_BOOT_MODE
        assert manifest["boot_crypto"] == EXPECTED_BOOT_CRYPTO
        assert manifest["secure_boot_flash"]["return_code"] == 0
        assert manifest["secure_boot_flash"]["failure_stage"] == "none"
        assert manifest["secure_boot_flash"]["negative_test"]["enabled"] is True
        assert manifest["secure_boot_flash"]["negative_test"]["source_image_modified"] is False
        assert (
            manifest["secure_boot_flash"]["negative_test"][
                "original_signed_application_sha256"
            ]
            != manifest["secure_boot_flash"]["negative_test"][
                "corrupted_signed_application_sha256"
            ]
        )
        assert manifest["secure_boot_negative_test"]["verdict"] == "passed"
        assert manifest["secure_boot_negative_test"]["normal_boot_marker_absent"] is True
        assert manifest["secure_boot_negative_test"]["tick_marker_absent"] is True
        assert manifest["secure_boot_negative_test"]["secure_boot_marker_absent"] is True
        assert manifest["secure_boot_negative_test"]["source_image_modified"] is False

        # In the negative workflow, UART marker evaluation is expected to fail
        # because the normal application markers must be absent. The enclosing
        # secure-boot command still returns success when the negative-test
        # verdict passes.
        assert manifest["uart"]["return_code"] == 9
        assert manifest["uart"]["boot_marker_present"] is False
        assert manifest["uart"]["tick_present"] is False
        assert manifest["uart"]["secure_boot_marker_present"] is False
        # A rejected/corrupted app may produce no UART payload at all. That is
        # valid negative evidence as long as the application markers are absent
        # and the enclosing negative-test verdict passed.
        assert manifest["uart"]["data_captured"] in {True, False}

        # Negative-test state is verified through manifest fields instead of
        # brittle flash-log text, because the flash log primarily captures
        # command output from external tools.

        uart_log = uart_log_path.read_text(encoding="utf-8")
        assert "Boot marker present: false" in uart_log
        assert "Tick marker present: false" in uart_log
        assert "Secure-boot marker present: false" in uart_log
    finally:
        restore_completed = _restore_valid_secure_boot_application(repo_root, results_dir)
        assert restore_completed.returncode == 0, (
            f"restore flash-secure-boot stdout:\n{restore_completed.stdout}\n"
            f"restore flash-secure-boot stderr:\n{restore_completed.stderr}"
        )

        restored_result_dir = _secure_boot_result_dirs(results_dir)[-1]
        restored_manifest = json.loads(
            (restored_result_dir / "manifest.json").read_text(encoding="utf-8")
        )
        _assert_positive_secure_boot_manifest(restored_manifest)

