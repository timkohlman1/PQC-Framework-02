from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


REPEAT_COUNT = 2
EXPECTED_STLINK_SERIAL = "066EFF3932504E3043111818"
FREERTOS_UART_MARKERS = (
    "FreeRTOS defaultTask created: name=defaultTask",
    "FreeRTOS networkTask created: name=networkTask",
    "FreeRTOS scheduler starting: cmsis_rtos=v2 default_task=defaultTask",
    "FreeRTOS networkTask started: initialization active",
    "FreeRTOS task-context smoke starting: context=freertos_task scheduler=running serialized=true",
    "lwIP runtime network: context=freertos_task scheduler=running",
)


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
        build_profile="configs/algorithms/ecdsa_p256.yaml",
        signing_profile="configs/algorithms/ecdsa_p256.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="ed25519",
        profile_id="ed25519_benchmark",
        algorithm="ED25519",
        signature_algorithm="ed25519",
        boot_mode="wolfboot_ed25519",
        boot_crypto="ed25519",
        build_profile="configs/algorithms/ed25519.yaml",
        signing_profile="configs/algorithms/ed25519.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_ed25519_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="rsa2048",
        profile_id="rsa2048_benchmark",
        algorithm="RSA2048",
        signature_algorithm="rsa2048",
        boot_mode="wolfboot_rsa2048",
        boot_crypto="rsa2048",
        build_profile="configs/algorithms/rsa2048.yaml",
        signing_profile="configs/algorithms/rsa2048.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_rsa2048_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="ecc384",
        profile_id="ecc384_benchmark",
        algorithm="ECC384",
        signature_algorithm="ecc384",
        boot_mode="wolfboot_ecc384",
        boot_crypto="ecc384",
        build_profile="configs/algorithms/ecc384.yaml",
        signing_profile="configs/algorithms/ecc384.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_ecc384_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="ecc521",
        profile_id="ecc521_benchmark",
        algorithm="ECC521",
        signature_algorithm="ecc521",
        boot_mode="wolfboot_ecc521",
        boot_crypto="ecc521",
        build_profile="configs/algorithms/ecc521.yaml",
        signing_profile="configs/algorithms/ecc521.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_ecc521_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="ed448",
        profile_id="ed448_benchmark",
        algorithm="ED448",
        signature_algorithm="ed448",
        boot_mode="wolfboot_ed448",
        boot_crypto="ed448",
        build_profile="configs/algorithms/ed448.yaml",
        signing_profile="configs/algorithms/ed448.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_ed448_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="rsa3072",
        profile_id="rsa3072_benchmark",
        algorithm="RSA3072",
        signature_algorithm="rsa3072",
        boot_mode="wolfboot_rsa3072",
        boot_crypto="rsa3072",
        build_profile="configs/algorithms/rsa3072.yaml",
        signing_profile="configs/algorithms/rsa3072.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_rsa3072_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="rsa4096",
        profile_id="rsa4096_benchmark",
        algorithm="RSA4096",
        signature_algorithm="rsa4096",
        boot_mode="wolfboot_rsa4096",
        boot_crypto="rsa4096",
        build_profile="configs/algorithms/rsa4096.yaml",
        signing_profile="configs/algorithms/rsa4096.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_rsa4096_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="mldsa44",
        profile_id="mldsa44_benchmark",
        algorithm="ML-DSA-44",
        signature_algorithm="mldsa44",
        boot_mode="wolfboot_mldsa44",
        boot_crypto="mldsa44",
        build_profile="configs/algorithms/mldsa44.yaml",
        signing_profile="configs/algorithms/mldsa44.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_mldsa44_v1_signed.bin",
    ),
    SecureBootBenchmarkProfile(
        name="mldsa65",
        profile_id="mldsa65_benchmark",
        algorithm="ML-DSA-65",
        signature_algorithm="mldsa65",
        boot_mode="wolfboot_mldsa65",
        boot_crypto="mldsa65",
        build_profile="configs/algorithms/mldsa65.yaml",
        signing_profile="configs/algorithms/mldsa65.yaml",
        experiment_profile="configs/experiments/secure_boot_uart.yaml",
        signed_application_artifact="build/Release/stm32_basic_hal1_mldsa65_v1_signed.bin",
    ),
)



def _benchmark_profile_param(profile: SecureBootBenchmarkProfile):
    """Return a pytest parameter marked for the short or long suite.

    ML-DSA-65 is the short-suite secure-boot algorithm benchmark because it is
    the highest currently implemented ML-DSA secure-boot profile and gives
    routine PQC-path coverage. The rest of the benchmark matrix is long-suite
    coverage for all-in validation.
    """

    if profile.name == "mldsa65":
        return pytest.param(profile, id=profile.name, marks=pytest.mark.short)
    return pytest.param(profile, id=profile.name, marks=pytest.mark.long)


HARDWARE_PROFILE_SELECTION_ENV = "PQC_HARDWARE_SECURE_BOOT_PROFILES"
HARDWARE_ALL_PROFILES_ENV = "PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _selected_benchmark_profile_names(environment: dict[str, str] | None = None) -> set[str]:
    """Return the benchmark profiles selected for this hardware run.

    ML-DSA-65 is always selected for routine coverage. The named-profile
    environment variable adds comma-separated profiles, while the all-profile
    environment variable selects the complete matrix.
    """

    env = os.environ if environment is None else environment
    available = {profile.name for profile in BENCHMARK_PROFILES}
    if _truthy(env.get(HARDWARE_ALL_PROFILES_ENV)):
        return available

    requested = {
        item.strip().lower()
        for item in env.get(HARDWARE_PROFILE_SELECTION_ENV, "").split(",")
        if item.strip()
    }
    unknown = sorted(requested - available)
    if unknown:
        raise pytest.UsageError(
            f"Unknown secure-boot hardware profile(s): {', '.join(unknown)}. "
            f"Available profiles: {', '.join(sorted(available))}."
        )
    return {"mldsa65", *requested}


def _benchmark_profile_params() -> tuple[object, ...]:
    selected = _selected_benchmark_profile_names()
    params: list[object] = []
    for profile in BENCHMARK_PROFILES:
        parameter = _benchmark_profile_param(profile)
        if profile.name not in selected:
            parameter = pytest.param(
                profile,
                id=profile.name,
                marks=(
                    pytest.mark.long,
                    pytest.mark.skip(
                        reason=(
                            "secure-boot hardware profile not selected; set "
                            f"{HARDWARE_PROFILE_SELECTION_ENV} or "
                            f"{HARDWARE_ALL_PROFILES_ENV}=1"
                        )
                    ),
                ),
            )
        params.append(parameter)
    return tuple(params)


def _assert_freertos_uart_markers(uart_log: str) -> None:
    for marker in FREERTOS_UART_MARKERS:
        assert marker in uart_log
    assert "tick" in uart_log


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
    """Remove only the relocated CMake output used directly by this test.

    wolfBoot generated-state cleanup is owned by the build-wolfboot preflight.
    The hardware test must not invoke ``keysclean`` or remove any private key,
    public key, or generated keystore member from the reusable local tuple.
    """

    shutil.rmtree(repo_root / "build" / "Release", ignore_errors=True)


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
        ["build-wolfboot", "--boot-algorithm", profile.signature_algorithm],
    )
    assert wolfboot_completed.returncode == 0, (
        f"{profile.name} build-wolfboot stdout:\n{wolfboot_completed.stdout}\n"
        f"{profile.name} build-wolfboot stderr:\n{wolfboot_completed.stderr}"
    )
    assert (repo_root / "tools" / "wolfboot" / "wolfboot.elf").is_file()

    configure_completed = _run_command(repo_root, ["cmake", "--preset", "Release"])
    assert configure_completed.returncode == 0, (
        f"{profile.name} cmake configure stdout:\n{configure_completed.stdout}\n"
        f"{profile.name} cmake configure stderr:\n{configure_completed.stderr}"
    )

    build_completed = _run_command(repo_root, ["cmake", "--build", "--preset", "Release"])
    assert build_completed.returncode == 0, (
        f"{profile.name} cmake build stdout:\n{build_completed.stdout}\n"
        f"{profile.name} cmake build stderr:\n{build_completed.stderr}"
    )

    signing_completed = _run_cli(
        repo_root,
        ["sign-application", "--boot-algorithm", profile.signature_algorithm],
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
            "--boot-algorithm",
            profile.signature_algorithm,
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
    assert isinstance(run["primary_derived_verification_time_ms"], int | float)
    assert run["primary_derived_verification_time_ms"] > 0
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
    assert aggregate["headline_metrics"]["primary_derived_verification_time_ms"] == run["primary_derived_verification_time_ms"]
    assert aggregate["headline_metrics"]["primary_verification_cycles"] == run["primary_verification_cycles"]
    assert aggregate["derived_verification_time_ms"]["median"] == run["primary_derived_verification_time_ms"]
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
        assert sample["bootloader_hclk_hz"] > 0
        application_clock = manifest["application_clock"]["clock_hz"]
        assert set(application_clock) == {"sysclk_hz", "hclk_hz", "pclk1_hz", "pclk2_hz"}
        assert manifest["application_clock"]["source"] in {
            "uart_reported_hal_rcc_from_running_default_task",
            "unavailable",
        }
        if manifest["application_clock"]["source"] == "unavailable":
            assert all(value is None for value in application_clock.values())
        else:
            assert all(isinstance(value, int) and value > 0 for value in application_clock.values())

        checkpoints = manifest["uart"]["application_memory_checkpoints"]
        checkpoint_by_stage = {checkpoint["stage"]: checkpoint for checkpoint in checkpoints}
        assert {"pre_scheduler", "default_task_runtime"}.issubset(checkpoint_by_stage)
        assert checkpoint_by_stage["pre_scheduler"]["task_stacks"] == []
        default_runtime_stacks = {
            item["task"]: item
            for item in checkpoint_by_stage["default_task_runtime"]["task_stacks"]
        }
        assert default_runtime_stacks["defaultTask"]["peak_used_bytes"] >= 0
        assert default_runtime_stacks["networkTask"]["peak_used_bytes"] >= 0
        assert manifest["runtime_memory"]["heap_used_bytes"] >= checkpoint_by_stage["pre_scheduler"]["heap_peak_used_bytes"]
        assert sample["verification_time_source"] == "framework_derived_from_uart_cycles_and_reported_hclk"
        assert sample["verification_cycles_source"] == "uart_explicit_verification_cycles_marker"
        assert sample["derived_verification_time_ms"] > 0
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
        assert "verification_time_source: framework_derived_from_uart_cycles_and_reported_hclk" in uart_log
        _assert_freertos_uart_markers(uart_log)
        pre_scheduler_line = next(
            line for line in uart_log.splitlines()
            if line.startswith("lwIP runtime smoke: context=pre_scheduler ")
        )
        assert "scheduler=not_started" in pre_scheduler_line
        assert "network=unavailable" in pre_scheduler_line
        assert "tls_handshake=unavailable" in pre_scheduler_line
        assert "mqtt_connect=unavailable" in pre_scheduler_line
        assert "end_to_end=unavailable" in pre_scheduler_line

        live_line = next(
            line for line in uart_log.splitlines()
            if line.startswith("lwIP runtime network: context=freertos_task ")
        )
        assert "scheduler=running" in live_line
        assert "network=available" in live_line
        assert "wifi=connected" in live_line
        assert "link=up" in live_line
        assert "tcp=available" in live_line
        assert "st67w61m1=available" in live_line

    assert (result_dir / "secure_boot_flash.log").is_file()
    return manifest


@pytest.mark.hardware
@pytest.mark.parametrize("profile", _benchmark_profile_params())
def test_secure_boot_algorithm_benchmark_profile(
    profile: SecureBootBenchmarkProfile,
    pqc_require_capabilities,
):
    """Run clean secure-boot benchmark workflows by short/long test suite.

    The ML-DSA-65 profile is marked short for routine PQC secure-boot hardware
    confidence. The remaining algorithm profiles are marked long for full-matrix
    validation. Pytest marker selection deselects the non-requested profile set;
    capability gating still skips selected cases when hardware is unavailable.
    Result artifacts are intentionally left under results/ as benchmark evidence.
    """

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        "uart_device",
        strict_mode="hardware",
    )

    repo_root = _repo_root()
    _prepare_profile_artifacts(repo_root, profile)
    result_dir = _run_profile_benchmark(repo_root, profile)
    manifest = _assert_profile_benchmark_manifest(repo_root, result_dir, profile)

    assert manifest["secure_boot_benchmark"]["classical_profile_metadata"]["profile_id"] == profile.profile_id
