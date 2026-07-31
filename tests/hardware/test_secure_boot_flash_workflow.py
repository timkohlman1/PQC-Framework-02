from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SECURE_BOOT_EXPERIMENT_CONFIG = "configs/experiments/secure_boot_uart.yaml"
BUILD_PROVENANCE_EXPERIMENT_CONFIG = "configs/experiments/baseline_direct_uart.yaml"
SIGNING_PROFILE = "configs/algorithms/ecdsa_p256.yaml"
WOLFBOOT_BUILD_PROFILE = "configs/algorithms/ecdsa_p256.yaml"
WOLFBOOT_ARTIFACT = "tools/wolfboot/wolfboot.elf"
RELOCATED_APPLICATION_ELF = "build/Release/stm32_basic_hal1.elf"
SIGNED_APPLICATION_ARTIFACT = "build/Release/stm32_basic_hal1_v1_signed.bin"
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




def _result_log_context(results_dir: Path, filename: str) -> str:
    """Return the newest matching result log for assertion diagnostics."""

    if not results_dir.exists():
        return f"No {filename} was created under {results_dir}."

    candidates = sorted(
        results_dir.rglob(filename),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not candidates:
        return f"No {filename} was created under {results_dir}."

    log_path = candidates[0]
    try:
        content = log_path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Unable to read {log_path}: {exc}"
    return f"{log_path}:\n{content}"


def _clean_secure_boot_generated_outputs(repo_root: Path) -> None:
    """Remove non-signing build outputs before hardware workflow builds.

    Reusable wolfBoot private-key, public-key, and generated-keystore tuple
    members are owned by the build preflight and must be preserved. The test
    removes only rebuildable firmware artifacts so it cannot create partial
    signing state before invoking ``build-wolfboot``.
    """

    wolfboot_dir = repo_root / "tools" / "wolfboot"
    _skip_if_missing(wolfboot_dir, "wolfBoot source tree is missing")

    shutil.rmtree(repo_root / "build", ignore_errors=True)
    for relative_path in (
        "tools/wolfboot/wolfboot.elf",
        "tools/wolfboot/wolfboot.bin",
        "tools/wolfboot/wolfboot.hex",
        "tools/wolfboot/wolfboot.map",
        "tools/wolfboot/.config",
    ):
        path = repo_root / relative_path
        if path.exists():
            path.unlink()


def _skip_if_missing(path: Path, reason: str) -> None:
    if not path.exists():
        pytest.skip(f"{reason}: {path}")


def _secure_boot_result_dirs(results_dir: Path) -> list[Path]:
    """Return result directories containing secure-boot execution manifests."""

    if not results_dir.exists():
        return []

    result_dirs: list[Path] = []
    for path in results_dir.iterdir():
        if not path.is_dir():
            continue

        manifest_path = path / "manifest.json"
        if not manifest_path.is_file():
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        if not isinstance(manifest, dict):
            continue
        if not isinstance(manifest.get("secure_boot_flash"), dict):
            continue
        if manifest.get("boot_mode") != EXPECTED_BOOT_MODE:
            continue
        if manifest.get("boot_crypto") != EXPECTED_BOOT_CRYPTO:
            continue

        result_dirs.append(path)

    return sorted(result_dirs)


def _single_secure_boot_result_dir(results_dir: Path) -> Path:
    result_dirs = _secure_boot_result_dirs(results_dir)
    assert len(result_dirs) == 1
    return result_dirs[0]


def _prepare_instrumented_wolfboot(repo_root: Path, results_dir: Path) -> None:
    build_completed = _run_cli(
        repo_root,
        [
            "build-wolfboot",
            "--boot-algorithm",
            EXPECTED_BOOT_CRYPTO,
            "--results-dir",
            str(results_dir),
        ],
    )
    assert build_completed.returncode == 0, (
        f"build-wolfboot stdout:\n{build_completed.stdout}\n"
        f"build-wolfboot stderr:\n{build_completed.stderr}\n"
        f"wolfBoot build log:\n"
        f"{_result_log_context(results_dir, 'wolfboot_build.log')}"
    )
    assert (repo_root / WOLFBOOT_ARTIFACT).is_file()


def _prepare_signed_secure_boot_application(repo_root: Path, results_dir: Path) -> None:
    build_completed = _run_cli(
        repo_root,
        [
            "build",
            "--experiment",
            BUILD_PROVENANCE_EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
            "--configure-preset",
            "Release",
            "--build-preset",
            "Release",
            "--artifact",
            RELOCATED_APPLICATION_ELF,
            "--force",
        ],
    )
    assert build_completed.returncode == 0, (
        f"framework build stdout:\n{build_completed.stdout}\n"
        f"framework build stderr:\n{build_completed.stderr}\n"
        f"firmware build log:\n"
        f"{_result_log_context(results_dir, 'build.log')}"
    )
    assert (repo_root / RELOCATED_APPLICATION_ELF).is_file()

    signing_completed = _run_cli(
        repo_root,
        [
            "sign-application",
            "--boot-algorithm",
            EXPECTED_BOOT_CRYPTO,
            "--results-dir",
            str(results_dir),
        ],
    )
    assert signing_completed.returncode == 0, (
        f"sign-application stdout:\n{signing_completed.stdout}\n"
        f"sign-application stderr:\n{signing_completed.stderr}\n"
        f"signing log:\n"
        f"{_result_log_context(results_dir, 'signing.log')}"
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

    artifact_freshness = manifest["secure_boot_flash"].get("artifact_freshness", {})
    assert artifact_freshness.get("artifact_freshness_status") == "recorded_not_enforced"
    if artifact_freshness.get("status") == "available":
        assert len(artifact_freshness["fingerprint"]) == 64
        assert artifact_freshness["fingerprint_inputs"]

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

    assert "boot_timing" in manifest
    assert isinstance(manifest["boot_timing"]["derived_verification_time_ms"], (int, float))
    assert manifest["boot_timing"]["derived_verification_time_ms"] > 0
    assert isinstance(manifest["boot_timing"]["verification_cycles"], int)
    assert manifest["boot_timing"]["verification_cycles"] > 0
    assert manifest["boot_timing"]["bootloader_hclk_hz"] > 0
    assert manifest["boot_timing"]["verification_result_code"] == 0
    assert (
        manifest["boot_timing"]["verification_time_source"]
        == "framework_derived_from_uart_cycles_and_reported_hclk"
    )
    assert isinstance(manifest["uart"]["derived_verification_time_ms"], (int, float))
    assert manifest["uart"]["derived_verification_time_ms"] > 0
    assert isinstance(manifest["uart"]["verification_cycles"], int)
    assert manifest["uart"]["verification_cycles"] > 0
    assert manifest["uart"]["bootloader_hclk_hz"] > 0
    assert manifest["uart"]["verification_result_code"] == 0
    assert isinstance(manifest["secure_boot_run"]["derived_verification_time_ms"], (int, float))
    assert manifest["secure_boot_run"]["derived_verification_time_ms"] > 0
    assert isinstance(manifest["secure_boot_run"]["verification_cycles"], int)
    assert manifest["secure_boot_run"]["verification_cycles"] > 0
    assert manifest["secure_boot_run"]["bootloader_hclk_hz"] > 0
    assert manifest["secure_boot_run"]["verification_result_code"] == 0

    assert "runtime_memory" in manifest
    runtime_memory = manifest["runtime_memory"]
    benchmark_memory = manifest["secure_boot_benchmark"]["runtime_memory_metrics"]
    assert manifest["secure_boot_benchmark"]["model_phase"] == "phase_11_4_runtime_memory_metrics"
    assert benchmark_memory["max_stack_used_bytes"] == runtime_memory["max_stack_used_bytes"]
    assert benchmark_memory["stack_metric_source"] == runtime_memory["stack_metric_source"]

    if runtime_memory["max_stack_used_bytes"] is None:
        assert runtime_memory["stack_metric_source"] == "unavailable"
        assert benchmark_memory["status"] == "unavailable"
        assert runtime_memory["limitations"]
        assert benchmark_memory["runtime_memory_limitations"]
    else:
        assert isinstance(runtime_memory["max_stack_used_bytes"], int)
        assert runtime_memory["max_stack_used_bytes"] > 0
        assert runtime_memory["stack_metric_source"] == "uart_explicit_stack_high_water_marker"
        assert benchmark_memory["status"] == "available"


def _restore_valid_secure_boot_application(repo_root: Path, results_dir: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        repo_root,
        [
            "flash-secure-boot",
            "--experiment",
            SECURE_BOOT_EXPERIMENT_CONFIG,
            "--boot-algorithm",
            EXPECTED_BOOT_CRYPTO,
            "--results-dir",
            str(results_dir),
            "--uart-duration-seconds",
            "10",
        ],
    )


@pytest.mark.hardware
@pytest.mark.short
def test_secure_boot_build_sign_flash_uart_workflow(tmp_path, pqc_require_capabilities):
    """Build, sign, flash, and UART-check the Phase 10h secure-boot workflow.

    This hardware-dependent system workflow auto-skips unless the local build
    toolchain, SSH gateway, configured flash helper, and configured ST-LINK VCP
    UART device are available. It builds the instrumented wolfBoot ELF, builds
    and signs the relocated HAL application, flashes both artifacts, captures
    UART, and verifies timing evidence from a clean non-signing build-output state.

    The test validates positive secure-boot evidence by requiring the distinct
    secure-boot application UART marker, the normal boot marker, the tick
    marker, and a parsed wolfBoot verification-time value after the two-artifact
    flash workflow. Runtime stack evidence is accepted when present and must be
    recorded as unavailable with limitations when no explicit firmware-side stack
    marker is emitted.
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
    _skip_if_missing(repo_root / WOLFBOOT_BUILD_PROFILE, "wolfBoot build profile is missing")

    _clean_secure_boot_generated_outputs(repo_root)
    _prepare_instrumented_wolfboot(repo_root, results_dir)
    _prepare_signed_secure_boot_application(repo_root, results_dir)

    flash_completed = _run_cli(
        repo_root,
        [
            "flash-secure-boot",
            "--experiment",
            SECURE_BOOT_EXPERIMENT_CONFIG,
            "--boot-algorithm",
            EXPECTED_BOOT_CRYPTO,
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
    assert "verification_time_source: framework_derived_from_uart_cycles_and_reported_hclk" in uart_log
    assert "verification_cycles:" in uart_log
    assert "bootloader_hclk_hz:" in uart_log
    assert "verification_result_code: 0" in uart_log
    assert "max_stack_used_bytes:" in uart_log
    # The secure-boot contract is established by the parsed boot, tick,
    # secure-boot, verification, and stack evidence above. Incidental FreeRTOS
    # diagnostic strings are intentionally not required because UART capture may
    # begin after one-time scheduler startup messages have already been emitted.
    if "max_stack_used_bytes: unavailable" in uart_log:
        assert "stack_metric_source: unavailable" in uart_log
    else:
        assert "stack_metric_source: uart_explicit_stack_high_water_marker" in uart_log

@pytest.mark.hardware
@pytest.mark.long
def test_secure_boot_negative_corrupted_application_then_restore_workflow(
    tmp_path, pqc_require_capabilities
):
    """Flash a corrupted signed application and restore the valid image afterward.

    This hardware-dependent Phase 10j workflow auto-skips under the same
    capability rules as the positive secure-boot hardware test. It builds the
    instrumented wolfBoot ELF and signed relocated application before flashing.
    It verifies that a result-local corrupted signed image does not produce the normal
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
    _skip_if_missing(repo_root / WOLFBOOT_BUILD_PROFILE, "wolfBoot build profile is missing")

    _clean_secure_boot_generated_outputs(repo_root)
    _prepare_instrumented_wolfboot(repo_root, results_dir)
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
        # The negative verdict is based on absence of the canonical application
        # markers recorded in the manifest, not optional scheduler diagnostics.
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
        restored_uart_log = (restored_result_dir / "uart.log").read_text(encoding="utf-8")
        assert "Boot marker present: true" in restored_uart_log
        assert "Tick marker present: true" in restored_uart_log
        assert "Secure-boot marker present: true" in restored_uart_log

