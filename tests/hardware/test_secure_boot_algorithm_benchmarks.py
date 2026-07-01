from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


REPEAT_COUNT = 2
EXPECTED_STLINK_SERIAL = "066EFF3932504E3043111818"


@dataclass(frozen=True)
class SecureBootBenchmarkProfile:
    name: str
    profile_id: str
    algorithm: str
    signature_algorithm: str
    boot_mode: str
    boot_crypto: str
    build_profile: str
    signing_profile: str
    experiment_profile: str
    signed_application_artifact: str


BENCHMARK_PROFILES = (
    SecureBootBenchmarkProfile(
        name="ecc256",
        profile_id="ecc256_reference",
        algorithm="ECC256",
        signature_algorithm="ecdsa_p256",
        boot_mode="wolfboot_ecdsa_p256",
        boot_crypto="ecdsa_p256",
        build_profile="configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml",
        signing_profile="configs/signing/wolfboot_ecdsa_p256_app.yaml",
        experiment_profile="configs/experiments/wolfboot_ecdsa_p256_uart.yaml",
        signed_application_artifact="build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="ed25519",
        profile_id="ed25519_benchmark",
        algorithm="ED25519",
        signature_algorithm="ed25519",
        boot_mode="wolfboot_ed25519",
        boot_crypto="ed25519",
        build_profile="configs/builds/wolfboot_stm32l4_ed25519.yaml",
        signing_profile="configs/signing/wolfboot_ed25519_app.yaml",
        experiment_profile="configs/experiments/wolfboot_ed25519_uart.yaml",
        signed_application_artifact="build/RelocatedDebug/stm32_basic_hal1_ed25519_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="rsa2048",
        profile_id="rsa2048_benchmark",
        algorithm="RSA2048",
        signature_algorithm="rsa2048",
        boot_mode="wolfboot_rsa2048",
        boot_crypto="rsa2048",
        build_profile="configs/builds/wolfboot_stm32l4_rsa2048.yaml",
        signing_profile="configs/signing/wolfboot_rsa2048_app.yaml",
        experiment_profile="configs/experiments/wolfboot_rsa2048_uart.yaml",
        signed_application_artifact="build/RelocatedDebug/stm32_basic_hal1_rsa2048_v1_signed.bin",
    ),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_command(repo_root: Path, args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd if cwd is not None else repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_cli(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run_command(repo_root, [sys.executable, "scripts/experiment.py", *args])


def _skip_if_missing(path: Path, reason: str) -> None:
    if not path.exists():
        pytest.skip(f"{reason}: {path}")


def _clean_generated_secure_boot_outputs(repo_root: Path) -> None:
    """Clean generated outputs using the same scope as the manual benchmark run.

    The benchmark hardware test intentionally leaves result evidence under
    results/. It only removes generated wolfBoot and relocated application
    outputs that can otherwise make a profile switch reuse stale build state.
    """

    wolfboot_dir = repo_root / "tools" / "wolfboot"
    _skip_if_missing(wolfboot_dir, "wolfBoot source tree is missing")
    if shutil.which("make") is None:
        pytest.skip("make is unavailable; wolfBoot keysclean cannot run")

    keysclean_completed = _run_command(
        repo_root,
        ["make", "WOLFBOOT_ROOT=.", "keysclean"],
        cwd=wolfboot_dir,
    )
    assert keysclean_completed.returncode == 0, (
        f"wolfBoot keysclean stdout:\n{keysclean_completed.stdout}\n"
        f"wolfBoot keysclean stderr:\n{keysclean_completed.stderr}"
    )

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

    shutil.rmtree(repo_root / "build", ignore_errors=True)


def _parse_result_directory(repo_root: Path, stdout: str) -> Path:
    match = re.search(r"^Result directory:\s*(.+)$", stdout, flags=re.MULTILINE)
    assert match is not None, f"command output did not include a result directory:\n{stdout}"
    result_dir = Path(match.group(1).strip())
    if not result_dir.is_absolute():
        result_dir = repo_root / result_dir
    return result_dir


def _prepare_profile_artifacts(repo_root: Path, profile: SecureBootBenchmarkProfile) -> None:
    _skip_if_missing(repo_root / profile.build_profile, "wolfBoot build profile is missing")
    _skip_if_missing(repo_root / profile.signing_profile, "signing profile is missing")
    _skip_if_missing(repo_root / profile.experiment_profile, "secure-boot experiment profile is missing")

    _clean_generated_secure_boot_outputs(repo_root)

    wolfboot_completed = _run_cli(
        repo_root,
        ["build-wolfboot", "--profile", profile.build_profile],
    )
    assert wolfboot_completed.returncode == 0, (
        f"{profile.name} build-wolfboot stdout:\n{wolfboot_completed.stdout}\n"
        f"{profile.name} build-wolfboot stderr:\n{wolfboot_completed.stderr}"
    )
    assert (repo_root / "tools" / "wolfboot" / "wolfboot.elf").is_file()

    configure_completed = _run_command(repo_root, ["cmake", "--preset", "RelocatedDebug"])
    assert configure_completed.returncode == 0, (
        f"{profile.name} cmake configure stdout:\n{configure_completed.stdout}\n"
        f"{profile.name} cmake configure stderr:\n{configure_completed.stderr}"
    )

    build_completed = _run_command(repo_root, ["cmake", "--build", "--preset", "RelocatedDebug"])
    assert build_completed.returncode == 0, (
        f"{profile.name} cmake build stdout:\n{build_completed.stdout}\n"
        f"{profile.name} cmake build stderr:\n{build_completed.stderr}"
    )

    signing_completed = _run_cli(
        repo_root,
        ["sign-application", "--profile", profile.signing_profile],
    )
    assert signing_completed.returncode == 0, (
        f"{profile.name} sign-application stdout:\n{signing_completed.stdout}\n"
        f"{profile.name} sign-application stderr:\n{signing_completed.stderr}"
    )
    assert (repo_root / profile.signed_application_artifact).is_file()


def _run_profile_benchmark(repo_root: Path, profile: SecureBootBenchmarkProfile) -> Path:
    completed = _run_cli(
        repo_root,
        [
            "flash-secure-boot",
            "--experiment",
            profile.experiment_profile,
            "--repeat-count",
            str(REPEAT_COUNT),
        ],
    )
    assert completed.returncode == 0, (
        f"{profile.name} flash-secure-boot stdout:\n{completed.stdout}\n"
        f"{profile.name} flash-secure-boot stderr:\n{completed.stderr}"
    )
    assert f"Benchmark sample count: {REPEAT_COUNT}" in completed.stdout
    assert f"Benchmark valid samples: {REPEAT_COUNT}" in completed.stdout
    assert "Benchmark failed samples: 0" in completed.stdout
    assert "Verification result code: 0" in completed.stdout
    assert "Verification timing source: uart_explicit_verification_time_marker" in completed.stdout
    return _parse_result_directory(repo_root, completed.stdout)


def _assert_profile_benchmark_manifest(
    repo_root: Path,
    result_dir: Path,
    profile: SecureBootBenchmarkProfile,
) -> dict:
    manifest_path = result_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["result"] in {
        "secure_boot_positive_boot_evidence_passed",
        "secure_boot_benchmark_repeated_run_passed",
    }
    assert manifest["boot_mode"] == profile.boot_mode
    assert manifest["boot_crypto"] == profile.boot_crypto

    flash = manifest["secure_boot_flash"]
    assert flash["return_code"] == 0
    assert flash["failure_stage"] == "none"
    assert flash["stlink_serial"] == EXPECTED_STLINK_SERIAL
    assert flash["wolfboot"]["artifact_exists"] is True
    assert len(flash["wolfboot"]["sha256"]) == 64
    assert flash["signed_application"]["artifact_exists"] is True
    assert len(flash["signed_application"]["sha256"]) == 64

    assert manifest["uart"]["return_code"] == 0
    assert manifest["uart"]["boot_marker_present"] is True
    assert manifest["uart"]["tick_present"] is True
    assert manifest["uart"]["secure_boot_marker_present"] is True
    assert manifest["uart"]["data_captured"] is True

    run = manifest["secure_boot_run"]
    assert run["return_code"] == 0
    assert run["failure_stage"] == "none"
    assert run["repeat_count_requested"] == REPEAT_COUNT
    assert run["repeated_run_sample_count"] == REPEAT_COUNT
    assert run["positive_boot_evidence_passed"] is True
    assert run["primary_statistic"] == "median"
    assert isinstance(run["primary_verification_time_ms"], int | float)
    assert run["primary_verification_time_ms"] > 0
    assert isinstance(run["primary_verification_cycles"], int | float)
    assert run["primary_verification_cycles"] > 0

    benchmark = manifest["secure_boot_benchmark"]
    metadata = benchmark["classical_profile_metadata"]
    assert metadata["profile_id"] == profile.profile_id
    assert metadata["algorithm"] == profile.algorithm
    assert metadata["signature_algorithm"] == profile.signature_algorithm

    aggregate = benchmark["aggregate_statistics"]
    assert aggregate["sample_count"] == REPEAT_COUNT
    assert aggregate["valid_sample_count"] == REPEAT_COUNT
    assert aggregate["failed_sample_count"] == 0
    assert aggregate["headline_metrics"]["primary_statistic"] == "median"
    assert aggregate["headline_metrics"]["primary_verification_time_ms"] == run["primary_verification_time_ms"]
    assert aggregate["headline_metrics"]["primary_verification_cycles"] == run["primary_verification_cycles"]
    assert aggregate["verification_time_ms"]["median"] == run["primary_verification_time_ms"]
    assert aggregate["verification_cycles"]["median"] == run["primary_verification_cycles"]

    repeated = benchmark["repeated_run_samples"]
    assert repeated["status"] == "completed"
    samples = repeated["samples"]
    assert len(samples) == REPEAT_COUNT
    for index, sample in enumerate(samples, start=1):
        assert sample["run_index"] == index
        assert sample["sample_verdict"] == "passed"
        assert sample["valid_for_statistics"] is True
        assert sample["verification_result_code"] == 0
        assert sample["verification_cpu_hz"] == 80000000
        assert sample["verification_time_source"] == "uart_explicit_verification_time_marker"
        assert sample["verification_cycles_source"] == "uart_explicit_verification_cycles_marker"
        assert sample["verification_time_ms"] > 0
        assert sample["verification_cycles"] > 0

        marker_result = sample["uart_marker_detection_result"]
        assert marker_result["boot_marker_present"] is True
        assert marker_result["tick_present"] is True
        assert marker_result["secure_boot_marker_present"] is True
        assert marker_result["data_captured"] is True
        assert marker_result["uart_return_code"] == 0

        log_path = result_dir / f"uart_sample_{index:03d}.log"
        assert log_path.is_file()
        uart_log = log_path.read_text(encoding="utf-8")
        assert "Boot marker present: true" in uart_log
        assert "Tick marker present: true" in uart_log
        assert "Secure-boot marker present: true" in uart_log
        assert "verification_time_source: uart_explicit_verification_time_marker" in uart_log

    assert (result_dir / "secure_boot_flash.log").is_file()
    return manifest


@pytest.mark.hardware
def test_secure_boot_classical_algorithm_benchmark_profiles_side_by_side(pqc_require_capabilities):
    """Run clean ECC256 and ED25519 secure-boot benchmark workflows.

    This hardware test automates the manual side-by-side command sequences used
    for Phase 11.5b. Each profile starts from a cleaned generated wolfBoot/app
    build state, then builds wolfBoot, rebuilds the relocated HAL app, signs the
    matching application image, flashes wolfBoot plus the signed app, and records
    two UART benchmark samples. Result artifacts are intentionally left under
    the repository results/ directory as benchmark evidence.
    """

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        "uart_device",
        strict_mode="hardware",
    )

    repo_root = _repo_root()
    manifests: dict[str, dict] = {}

    for profile in BENCHMARK_PROFILES:
        _prepare_profile_artifacts(repo_root, profile)
        result_dir = _run_profile_benchmark(repo_root, profile)
        manifests[profile.name] = _assert_profile_benchmark_manifest(repo_root, result_dir, profile)

    assert set(manifests) == {"ecc256", "ed25519", "rsa2048"}
    assert manifests["ecc256"]["secure_boot_benchmark"]["classical_profile_metadata"]["profile_id"] == "ecc256_reference"
    assert manifests["ed25519"]["secure_boot_benchmark"]["classical_profile_metadata"]["profile_id"] == "ed25519_benchmark"
    assert manifests["rsa2048"]["secure_boot_benchmark"]["classical_profile_metadata"]["profile_id"] == "rsa2048_benchmark"
