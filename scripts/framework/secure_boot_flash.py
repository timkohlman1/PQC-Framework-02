"""Two-artifact wolfBoot flash helpers for secure-boot experiment runs.

This module flashes a wolfBoot bootloader artifact and a signed application
image through the configured experiment gateway. It records command output,
artifact hashes, configured flash offsets, and final status under one run result
directory. Command runners are injectable so unit tests do not require SSH,
UART, gateway access, or STM32 hardware.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Any, Callable

from framework.artifacts import calculate_file_sha256
from framework.generated_state import GeneratedStateError, require_any_recorded_artifact
from framework.fingerprint import (
    FingerprintInputError,
    calculate_existing_inputs_fingerprint,
    default_secure_boot_flash_fingerprint_inputs,
)
from framework.manifest import build_secure_boot_benchmark_model, read_elf_alloc_section_metrics, read_manifest, update_manifest
from framework.source import GitCommandExecution, GitRunner, capture_reproducibility_provenance
from framework.ssh_target import gateway_ssh_target

SECURE_BOOT_ARTIFACT_MISSING_RETURN_CODE = 40
SECURE_BOOT_SCP_FAILED_RETURN_CODE = 41
SECURE_BOOT_FLASH_FAILED_RETURN_CODE = 42
SECURE_BOOT_PROFILE_ERROR_RETURN_CODE = 43
SECURE_BOOT_KEY_MISMATCH_RETURN_CODE = 44

DEFAULT_SECURE_BOOT_FLASH_LOG_NAME = "secure_boot_flash.log"


@dataclass(frozen=True)
class CommandExecution:
    """Captured output from one command invocation."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class SecureBootFlashArtifactResult:
    """Flash evidence for one secure-boot artifact."""

    name: str
    artifact_path: Path
    artifact_exists: bool
    artifact_sha256: str | None
    offset: str
    remote_artifact_path: str
    pass_offset_to_helper: bool
    scp: CommandExecution | None
    flash: CommandExecution | None


@dataclass(frozen=True)
class SecureBootFlashResult:
    """Captured output from one wolfBoot + signed-application flash run."""

    return_code: int
    duration_seconds: float
    result_dir: Path
    log_path: Path
    stlink_serial: str
    gateway_alias: str
    flash_helper: str
    wolfboot: SecureBootFlashArtifactResult
    signed_application: SecureBootFlashArtifactResult
    failure_stage: str
    failure_reason: str | None
    negative_test_enabled: bool
    corruption_method: str | None
    original_signed_application_path: Path | None
    original_signed_application_sha256: str | None
    corrupted_signed_application_path: Path | None
    corrupted_signed_application_sha256: str | None
    key_consistency_status: str
    key_consistency_message: str | None
    signing_private_key_path: Path | None
    wolfboot_private_key_path: Path | None
    signing_private_key_sha256: str | None
    wolfboot_private_key_sha256: str | None


Runner = Callable[[list[str], Path], CommandExecution]


class SecureBootFlashProfileError(ValueError):
    """Raised when an experiment lacks required secure-boot flash fields."""


def default_runner(command: list[str], cwd: Path) -> CommandExecution:
    """Run a command without a shell and capture output and duration."""

    start = perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=perf_counter() - start,
    )


def _required(mapping: dict[str, Any], dotted_path: str) -> Any:
    current: Any = mapping
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise SecureBootFlashProfileError(
                f"secure-boot flash experiment missing required field: {dotted_path}"
            )
        current = current[part]
    if current is None or current == "":
        raise SecureBootFlashProfileError(
            f"secure-boot flash experiment has empty required field: {dotted_path}"
        )
    return current


def _optional_bool(mapping: dict[str, Any], dotted_path: str, default: bool) -> bool:
    current: Any = mapping
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    if isinstance(current, bool):
        return current
    return str(current).strip().lower() in {"true", "yes", "1", "on"}


def validate_secure_boot_flash_experiment(bundle: dict[str, dict[str, Any]]) -> None:
    """Validate fields required by the Phase 10h two-artifact flash workflow."""

    experiment = bundle.get("experiment", {})
    boot = bundle.get("boot", {})
    host = bundle.get("host", {})
    board = bundle.get("board", {})

    _required(experiment, "id")
    _required(experiment, "secure_boot_flash.wolfboot_artifact")
    _required(experiment, "secure_boot_flash.wolfboot_offset")
    _required(experiment, "secure_boot_flash.signed_application_artifact")
    _required(experiment, "secure_boot_flash.signed_application_offset")
    _required(host, "alias")
    _required(host, "flash.helper")
    _required(board, "stlink.serial")

    boot_mode = _required(boot, "mode")
    firmware_mode = _required(experiment, "firmware.mode")
    if firmware_mode != boot_mode:
        raise SecureBootFlashProfileError(
            f"secure-boot flash experiment firmware.mode '{firmware_mode}' does not match boot mode '{boot_mode}'"
        )


def construct_scp_command(
    artifact_path: Path | str,
    gateway_alias: str,
    remote_artifact_path: str,
) -> list[str]:
    """Construct the SCP command used to stage one artifact on the gateway."""

    return ["scp", str(Path(artifact_path)), f"{gateway_alias}:{remote_artifact_path}"]


def construct_ssh_flash_command(
    gateway_alias: str,
    flash_helper: str,
    remote_artifact_path: str,
    offset: str,
    *,
    pass_offset_to_helper: bool,
) -> list[str]:
    """Construct the SSH command used to invoke the gateway flash helper."""

    remote_command = f"{shlex.quote(flash_helper)} {shlex.quote(remote_artifact_path)}"
    if pass_offset_to_helper:
        remote_command += f" {shlex.quote(str(offset))}"
    return ["ssh", gateway_alias, remote_command]


def _fingerprint_evidence(
    *,
    repo_root: Path,
    bundle: dict[str, dict[str, Any]],
    wolfboot: SecureBootFlashArtifactResult,
    signed_application: SecureBootFlashArtifactResult,
) -> dict[str, Any]:
    experiment = bundle.get("experiment", {})
    experiment_id = str(experiment.get("id", "unknown"))
    algorithm_id = str(experiment.get("boot_crypto", "ecdsa_p256"))
    requested_inputs = default_secure_boot_flash_fingerprint_inputs(
        experiment_id=experiment_id,
        algorithm_id=algorithm_id,
    )
    missing_inputs = [
        relative_input
        for relative_input in requested_inputs
        if not (repo_root / relative_input).exists()
    ]
    try:
        fingerprint = calculate_existing_inputs_fingerprint(
            repo_root=repo_root,
            relative_inputs=requested_inputs,
        )
    except FingerprintInputError as exc:
        fingerprint_payload = {
            "status": "unavailable",
            "fingerprint": None,
            "fingerprint_algorithm": None,
            "fingerprint_inputs": [],
            "fingerprint_file_hashes": {},
            "fingerprint_tool_versions": {},
            "requested_fingerprint_inputs": requested_inputs,
            "missing_fingerprint_inputs": missing_inputs,
            "limitations": str(exc),
        }
    else:
        fingerprint_payload = {
            "status": "available",
            "fingerprint": fingerprint.fingerprint,
            "fingerprint_algorithm": fingerprint.algorithm,
            "fingerprint_inputs": fingerprint.inputs,
        "fingerprint_file_hashes": fingerprint.file_hashes,
        "fingerprint_tool_versions": fingerprint.tool_versions or {},
            "requested_fingerprint_inputs": requested_inputs,
            "missing_fingerprint_inputs": missing_inputs,
            "limitations": None
            if not missing_inputs
            else "Some optional secure-boot flash inputs were absent and therefore not hashed; fingerprint_inputs lists the exact files covered.",
        }

    return {
        **fingerprint_payload,
        "artifact_freshness_status": "recorded_not_enforced",
        "artifact_freshness_limitations": (
            "Phase 11.4 records secure-boot workflow and artifact fingerprints as evidence, "
            "but flash-secure-boot does not yet refuse stale artifacts. Hardware tests clean "
            "generated secure-boot outputs before rebuilding to avoid timestamp-dependent stale artifacts."
        ),
        "artifacts": {
            "wolfboot": {
                "path": str(wolfboot.artifact_path),
                "exists": wolfboot.artifact_exists,
                "sha256": wolfboot.artifact_sha256,
            },
            "signed_application": {
                "path": str(signed_application.artifact_path),
                "exists": signed_application.artifact_exists,
                "sha256": signed_application.artifact_sha256,
            },
        },
    }


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _format_execution(execution: CommandExecution | None, cwd: Path) -> list[str]:
    if execution is None:
        return ["not run", ""]
    return [
        f"Command: {_format_command(execution.command)}",
        f"Working directory: {cwd}",
        f"Return code: {execution.return_code}",
        f"Duration seconds: {execution.duration_seconds:.3f}",
        "",
        "stdout:",
        execution.stdout.rstrip(),
        "",
        "stderr:",
        execution.stderr.rstrip(),
        "",
    ]


def _remote_artifact_path(result_dir: Path, label: str, artifact_path: Path) -> str:
    safe_name = f"{result_dir.name}_{label}_{artifact_path.name}"
    return str(PurePosixPath("/tmp") / safe_name)


def _corrupt_signed_application_copy(
    *,
    source_path: Path,
    result_dir: Path,
    output_name: str,
    method: str,
) -> Path:
    """Create a result-local corrupted application image without modifying source."""

    if method != "flip_first_byte":
        raise SecureBootFlashProfileError(
            f"unsupported secure-boot negative-test corruption method: {method}"
        )

    corrupted_path = result_dir / output_name
    corrupted_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, corrupted_path)

    image = bytearray(corrupted_path.read_bytes())
    if not image:
        raise SecureBootFlashProfileError(
            f"cannot corrupt empty signed application image: {source_path}"
        )

    image[0] ^= 0x01
    corrupted_path.write_bytes(bytes(image))
    return corrupted_path



def _classical_profile_metadata(experiment: dict[str, Any]) -> dict[str, Any] | None:
    profile = experiment.get("secure_boot_benchmark_profile")
    if not isinstance(profile, dict):
        return None

    algorithm = str(profile.get("algorithm", "ECC256"))
    profile_status = str(profile.get("status", "reference_existing_phase_10_11_profile"))
    runnable = profile.get("runnable") is True

    minimum_required = ["ED25519", "ECC256", "RSA2048"]
    expanded_required = ["ECC384", "ECC521", "ED448", "RSA3072", "RSA4096"]
    mldsa_supported = ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]
    mldsa_unavailable = []
    algorithm_to_status_field = {
        "ED25519": "ed25519_status",
        "RSA2048": "rsa2048_status",
        "ECC384": "ecc384_status",
        "ECC521": "ecc521_status",
        "ED448": "ed448_status",
        "RSA3072": "rsa3072_status",
        "RSA4096": "rsa4096_status",
        "ML-DSA-44": "mldsa44_status",
        "ML-DSA-65": "mldsa65_status",
        "ML-DSA-87": "mldsa87_status",
    }

    implemented_algorithms = [*minimum_required, *expanded_required]
    implemented_mldsa_algorithms = mldsa_supported

    planned_non_runnable_algorithms: list[str] = []

    minimum_scope = {
        "status": str(profile.get("minimum_scope_status", "defined_phase_11_5a_minimum_classical_scope")),
        "required_algorithms": minimum_required,
        "implemented_reference_algorithm": "ECC256",
        "implemented_algorithms": implemented_algorithms,
        "planned_non_runnable_algorithms": planned_non_runnable_algorithms,
        "scope_limitations": str(
            profile.get(
                "scope_limitations",
                "Phase 11.5d adds optional expanded classical profiles; ML-DSA profiles are tracked separately as post-quantum secure-boot profiles.",
            )
        ),
    }

    expanded_scope = {
        "status": str(profile.get("expanded_scope_status", "phase_11_5d_expanded_classical_scope")),
        "optional_algorithms": expanded_required,
        "active_algorithm": algorithm if algorithm in expanded_required else None,
        "cross_profile_aggregation_status": "phase_11_6_available",
    }

    mldsa_scope = {
        "status": str(profile.get("mldsa_scope_status", "post_phase_11_mldsa_profiles")),
        "supported_algorithms": mldsa_supported,
        "unavailable_algorithms": mldsa_unavailable,
        "active_algorithm": algorithm if algorithm in [*mldsa_supported, *mldsa_unavailable] else None,
        "image_header_size_bytes": profile.get("image_header_size_bytes"),
        "scope_limitations": str(
            profile.get(
                "mldsa_scope_limitations",
                "ML-DSA-44, ML-DSA-65, and ML-DSA-87 fit the shared 12288-byte image-header reserve.",
            )
        ),
    }

    capability_status: dict[str, dict[str, Any]] = {}
    for candidate in ["ED25519", "RSA2048", *expanded_required, *mldsa_supported, *mldsa_unavailable]:
        key = candidate.lower().replace("-", "").replace("_", "")
        candidate_runnable = candidate in implemented_algorithms or candidate in implemented_mldsa_algorithms or (runnable and algorithm == candidate)
        if candidate in mldsa_unavailable:
            candidate_runnable = False
        default_status = (
            "configured_post_phase_11_mldsa_profile_not_hardware_validated"
            if candidate in mldsa_supported and candidate_runnable
            else "configured_post_phase_11_mldsa_profile_not_hardware_validated"
            if candidate in mldsa_unavailable
            else "configured_phase_11_5d_expanded_classical_profile_not_hardware_validated"
            if candidate in expanded_required and candidate_runnable
            else "configured_runnable_profile_not_hardware_validated"
            if candidate_runnable
            else "planned_not_active_for_this_experiment"
        )
        capability_status[key] = {
            "status": str(profile.get(algorithm_to_status_field.get(candidate, f"{key}_status"), default_status)),
            "runnable": candidate_runnable,
            "unavailable": None
            if candidate_runnable
            else {
                "status": "unavailable",
                "source": "profile_model",
                "reason": "ML-DSA-87 requires an image header larger than the current 12288-byte reserve."
                if candidate in mldsa_unavailable
                else f"{candidate} is not the active configured benchmark profile for this experiment.",
            },
        }

    if algorithm in mldsa_supported and runnable:
        model_phase = "post_phase_11_mldsa_profiles"
        benchmark_scope = "secure_boot_mldsa_signing_algorithm"
    elif algorithm in expanded_required and runnable:
        model_phase = "phase_11_5d_expanded_classical_profiles"
        benchmark_scope = "secure_boot_classical_signing_algorithm"
    elif algorithm == "RSA2048" and runnable:
        model_phase = "phase_11_5c_rsa2048_profile"
        benchmark_scope = "secure_boot_classical_signing_algorithm"
    elif algorithm == "ED25519" and runnable:
        model_phase = "phase_11_5b_ed25519_profile"
        benchmark_scope = "secure_boot_classical_signing_algorithm"
    else:
        model_phase = "phase_11_5a_classical_profile_model"
        benchmark_scope = "secure_boot_classical_signing_algorithm"

    return {
        "schema_version": int(profile.get("schema_version", 1)),
        "model_phase": model_phase,
        "benchmark_scope": benchmark_scope,
        "profile_model": str(profile.get("profile_model", "configs/benchmarks/classical_signing_profiles.yaml")),
        "profile_id": str(profile.get("profile_id", experiment.get("id", "unknown"))),
        "algorithm": algorithm,
        "wolfboot_sign": str(profile.get("wolfboot_sign", "ECC256" if algorithm == "ECC256" else algorithm)),
        "signature_algorithm": str(profile.get("signature_algorithm", experiment.get("boot_crypto", "ecdsa_p256"))),
        "curve": profile.get("curve"),
        "key_size_bits": profile.get("key_size_bits"),
        "security_category": profile.get("security_category"),
        "mldsa_level": profile.get("mldsa_level"),
        "signature_size_bytes": profile.get("signature_size_bytes"),
        "image_version": profile.get("image_version"),
        "signing_profile": profile.get("signing_profile"),
        "wolfboot_build_profile": profile.get("wolfboot_build_profile"),
        "experiment_profile": profile.get("experiment_profile"),
        "boot_profile": profile.get("boot_profile"),
        "runnable": runnable,
        "status": profile_status,
        "benchmark_assumptions": {
            "application_payload": str(profile.get("application_payload", "same_relocated_hal_application_payload")),
            "board": str(profile.get("board", experiment.get("board", "unknown"))),
            
            "measurement_method": str(profile.get("measurement_method", "uart_explicit_wolfboot_mailbox_markers")),
            "repeated_run_model": str(profile.get("repeated_run_model", "phase_11_2_repeat_count_samples")),
            "static_metrics_model": str(profile.get("static_metrics_model", "phase_11_3_elf_and_artifact_metrics")),
            "runtime_memory_model": str(profile.get("runtime_memory_model", "phase_11_4_firmware_side_stack_high_water_marker")),
        },
        "minimum_comparison_scope": minimum_scope,
        "expanded_classical_scope": expanded_scope,
        "mldsa_scope": mldsa_scope,
        "capability_status": capability_status,
    }

def _signature_size_bytes(experiment: dict[str, Any]) -> int | None:
    secure_boot_config = experiment.get("secure_boot_flash", {})
    if not isinstance(secure_boot_config, dict):
        secure_boot_config = {}
    configured = secure_boot_config.get("signature_size_bytes")
    if configured in (None, ""):
        return None
    return int(configured)


def _signature_metadata(experiment: dict[str, Any]) -> dict[str, Any]:
    secure_boot_config = experiment.get("secure_boot_flash", {})
    if not isinstance(secure_boot_config, dict):
        secure_boot_config = {}
    signature_size = _signature_size_bytes(experiment)
    return {
        "algorithm": str(secure_boot_config.get("signature_algorithm", experiment.get("boot_crypto", "ecdsa_p256"))),
        "signature_size": signature_size,
        "signature_size_bytes": signature_size,
        "image_version": secure_boot_config.get("image_version"),
    }


def _artifact_result_to_manifest(result: SecureBootFlashArtifactResult) -> dict[str, Any]:
    return {
        "artifact_path": str(result.artifact_path),
        "artifact_exists": result.artifact_exists,
        "sha256": result.artifact_sha256,
        "offset": result.offset,
        "remote_artifact_path": result.remote_artifact_path,
        "pass_offset_to_helper": result.pass_offset_to_helper,
        "scp_return_code": None if result.scp is None else result.scp.return_code,
        "helper_return_code": None if result.flash is None else result.flash.return_code,
    }


def _artifact_size_bytes(path: Path) -> int | None:
    return path.stat().st_size if path.is_file() else None


def _optional_secure_boot_artifact_path(
    *,
    repo_root: Path,
    secure_boot_config: dict[str, Any],
    key: str,
) -> Path | None:
    configured = secure_boot_config.get(key)
    if configured in (None, ""):
        return None
    return repo_root / str(configured)


def _artifact_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return calculate_file_sha256(path)


def _resolve_optional_repo_path(repo_root: Path, configured: Any) -> Path | None:
    if configured in (None, ""):
        return None
    path = Path(str(configured))
    return path if path.is_absolute() else repo_root / path


def _local_key_consistency_evidence(
    *,
    repo_root: Path,
    secure_boot_config: dict[str, Any],
) -> dict[str, Any]:
    signing_private_key_path = _resolve_optional_repo_path(
        repo_root,
        secure_boot_config.get("signing_private_key"),
    )
    wolfboot_private_key_path = _resolve_optional_repo_path(
        repo_root,
        secure_boot_config.get("wolfboot_private_key"),
    )
    signing_private_key_sha256 = _artifact_sha256(signing_private_key_path)
    wolfboot_private_key_sha256 = _artifact_sha256(wolfboot_private_key_path)

    if signing_private_key_path is None and wolfboot_private_key_path is None:
        status = "not_configured"
        message = "No local secure-boot signing-key consistency paths are configured."
    elif signing_private_key_sha256 is None or wolfboot_private_key_sha256 is None:
        status = "unavailable"
        message = "One or both configured local secure-boot signing-key files are unavailable."
    elif signing_private_key_sha256 != wolfboot_private_key_sha256:
        status = "mismatch_refused"
        message = "Configured application signing key does not match the wolfBoot private key; refusing to flash artifacts that cannot verify together."
    else:
        status = "matched"
        message = "Configured application signing key matches the wolfBoot private key."

    return {
        "status": status,
        "message": message,
        "signing_private_key_path": None if signing_private_key_path is None else str(signing_private_key_path),
        "wolfboot_private_key_path": None if wolfboot_private_key_path is None else str(wolfboot_private_key_path),
        "signing_private_key_sha256": signing_private_key_sha256,
        "wolfboot_private_key_sha256": wolfboot_private_key_sha256,
        "key_material_copied_to_results": False,
    }


def _static_resource_metrics_for_wolfboot(wolfboot_path: Path) -> tuple[dict[str, Any], list[str]]:
    if not wolfboot_path.is_file():
        return {}, [f"wolfBoot ELF artifact is not available for static section-size analysis: {wolfboot_path}"]
    try:
        return read_elf_alloc_section_metrics(wolfboot_path), []
    except (OSError, ValueError) as exc:
        return {}, [f"wolfBoot ELF static section-size analysis unavailable: {exc}"]


def _write_secure_boot_flash_log(
    *,
    log_path: Path,
    repo_root: Path,
    result: SecureBootFlashResult,
) -> None:
    lines = [
        "wolfBoot secure-boot flash log",
        "===============================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Repository root: {repo_root}",
        f"Gateway alias: {result.gateway_alias}",
        f"Flash helper: {result.flash_helper}",
        f"ST-LINK serial: {result.stlink_serial}",
        f"Final return code: {result.return_code}",
        f"Failure stage: {result.failure_stage}",
        f"Failure reason: {result.failure_reason if result.failure_reason is not None else 'none'}",
        f"Negative corrupted-application test: {str(result.negative_test_enabled).lower()}",
        f"Corruption method: {result.corruption_method if result.corruption_method is not None else 'not requested'}",
        f"Original signed application SHA-256: {result.original_signed_application_sha256 if result.original_signed_application_sha256 is not None else 'unavailable'}",
        f"Corrupted signed application path: {result.corrupted_signed_application_path if result.corrupted_signed_application_path is not None else 'not created'}",
        f"Corrupted signed application SHA-256: {result.corrupted_signed_application_sha256 if result.corrupted_signed_application_sha256 is not None else 'unavailable'}",
        f"Signing key consistency status: {result.key_consistency_status}",
        f"Signing key consistency message: {result.key_consistency_message if result.key_consistency_message is not None else 'none'}",
        f"Application signing key path: {result.signing_private_key_path if result.signing_private_key_path is not None else 'not configured'}",
        f"wolfBoot private key path: {result.wolfboot_private_key_path if result.wolfboot_private_key_path is not None else 'not configured'}",
        f"Application signing key SHA-256: {result.signing_private_key_sha256 if result.signing_private_key_sha256 is not None else 'unavailable'}",
        f"wolfBoot private key SHA-256: {result.wolfboot_private_key_sha256 if result.wolfboot_private_key_sha256 is not None else 'unavailable'}",
        "Private signing keys are local-only evidence inputs and are not copied into the result directory.",
        f"Total duration seconds: {result.duration_seconds:.3f}",
        "",
    ]

    for artifact in [result.wolfboot, result.signed_application]:
        lines += [
            f"{artifact.name} artifact",
            "-" * (len(artifact.name) + 9),
            f"Local artifact path: {artifact.artifact_path}",
            f"Local artifact exists: {str(artifact.artifact_exists).lower()}",
            f"Local artifact SHA-256: {artifact.artifact_sha256 if artifact.artifact_sha256 is not None else 'unavailable'}",
            f"Configured flash offset: {artifact.offset}",
            f"Pass offset to helper: {str(artifact.pass_offset_to_helper).lower()}",
            f"Remote artifact path: {artifact.remote_artifact_path}",
            "",
            "SCP step",
            "--------",
        ]
        lines += _format_execution(artifact.scp, repo_root)
        lines += ["Flash helper step", "-----------------"]
        lines += _format_execution(artifact.flash, repo_root)

    log_path.write_text("\n".join(lines), encoding="utf-8")


def _prepare_artifact_result(
    *,
    name: str,
    repo_root: Path,
    result_dir: Path,
    relative_path: str,
    offset: str,
    pass_offset_to_helper: bool,
) -> SecureBootFlashArtifactResult:
    artifact_path = repo_root / relative_path
    return _prepare_artifact_result_from_path(
        name=name,
        result_dir=result_dir,
        artifact_path=artifact_path,
        offset=offset,
        pass_offset_to_helper=pass_offset_to_helper,
    )


def _prepare_artifact_result_from_path(
    *,
    name: str,
    result_dir: Path,
    artifact_path: Path,
    offset: str,
    pass_offset_to_helper: bool,
) -> SecureBootFlashArtifactResult:
    artifact_exists = artifact_path.is_file()
    return SecureBootFlashArtifactResult(
        name=name,
        artifact_path=artifact_path,
        artifact_exists=artifact_exists,
        artifact_sha256=calculate_file_sha256(artifact_path) if artifact_exists else None,
        offset=str(offset),
        remote_artifact_path=_remote_artifact_path(result_dir, name, artifact_path),
        pass_offset_to_helper=pass_offset_to_helper,
        scp=None,
        flash=None,
    )


def _with_executions(
    artifact: SecureBootFlashArtifactResult,
    *,
    scp: CommandExecution | None,
    flash: CommandExecution | None,
) -> SecureBootFlashArtifactResult:
    return SecureBootFlashArtifactResult(
        name=artifact.name,
        artifact_path=artifact.artifact_path,
        artifact_exists=artifact.artifact_exists,
        artifact_sha256=artifact.artifact_sha256,
        offset=artifact.offset,
        remote_artifact_path=artifact.remote_artifact_path,
        pass_offset_to_helper=artifact.pass_offset_to_helper,
        scp=scp,
        flash=flash,
    )


def execute_secure_boot_flash(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
    result_dir: Path | str,
    runner: Runner = default_runner,
    git_runner: GitRunner | None = None,
) -> SecureBootFlashResult:
    """Flash wolfBoot and the signed application, then update the run manifest."""

    validate_secure_boot_flash_experiment(bundle)

    repo_root_path = Path(repo_root)
    result_dir_path = Path(result_dir)
    experiment = bundle["experiment"]
    secure_boot_config = experiment["secure_boot_flash"]
    host = bundle["host"]
    board = bundle["board"]

    gateway_alias = str(host["alias"])
    gateway_target = gateway_ssh_target(host)
    flash_helper = str(host["flash"]["helper"])
    stlink_serial = str(board["stlink"]["serial"])
    log_path = result_dir_path / DEFAULT_SECURE_BOOT_FLASH_LOG_NAME

    wolfboot = _prepare_artifact_result(
        name="wolfboot",
        repo_root=repo_root_path,
        result_dir=result_dir_path,
        relative_path=str(secure_boot_config["wolfboot_artifact"]),
        offset=str(secure_boot_config["wolfboot_offset"]),
        pass_offset_to_helper=_optional_bool(
            experiment,
            "secure_boot_flash.wolfboot_pass_offset_to_helper",
            False,
        ),
    )
    negative_test_enabled = _optional_bool(
        experiment,
        "secure_boot_flash.negative_test_corrupt_application",
        False,
    )
    corruption_method = (
        str(secure_boot_config.get("corruption_method", "flip_first_byte"))
        if negative_test_enabled
        else None
    )
    original_signed_application_path = repo_root_path / str(
        secure_boot_config["signed_application_artifact"]
    )
    original_signed_application_sha256 = (
        calculate_file_sha256(original_signed_application_path)
        if original_signed_application_path.is_file()
        else None
    )
    corrupted_signed_application_path: Path | None = None
    corrupted_signed_application_sha256: str | None = None

    if negative_test_enabled and original_signed_application_path.is_file():
        corrupted_signed_application_path = _corrupt_signed_application_copy(
            source_path=original_signed_application_path,
            result_dir=result_dir_path,
            output_name=str(
                secure_boot_config.get(
                    "corrupted_application_artifact",
                    "corrupted_application_signed.bin",
                )
            ),
            method=str(corruption_method),
        )
        corrupted_signed_application_sha256 = calculate_file_sha256(
            corrupted_signed_application_path
        )
        signed_application = _prepare_artifact_result_from_path(
            name="signed_application",
            result_dir=result_dir_path,
            artifact_path=corrupted_signed_application_path,
            offset=str(secure_boot_config["signed_application_offset"]),
            pass_offset_to_helper=_optional_bool(
                experiment,
                "secure_boot_flash.signed_application_pass_offset_to_helper",
                True,
            ),
        )
    else:
        signed_application = _prepare_artifact_result(
            name="signed_application",
            repo_root=repo_root_path,
            result_dir=result_dir_path,
            relative_path=str(secure_boot_config["signed_application_artifact"]),
            offset=str(secure_boot_config["signed_application_offset"]),
            pass_offset_to_helper=_optional_bool(
                experiment,
                "secure_boot_flash.signed_application_pass_offset_to_helper",
                True,
            ),
        )

    key_consistency = _local_key_consistency_evidence(
        repo_root=repo_root_path,
        secure_boot_config=secure_boot_config,
    )

    start = perf_counter()
    return_code = 0
    failure_stage = "none"
    failure_reason: str | None = None

    if key_consistency["status"] == "mismatch_refused":
        return_code = SECURE_BOOT_KEY_MISMATCH_RETURN_CODE
        failure_stage = "signing_key_consistency"
        failure_reason = str(key_consistency["message"])

    if return_code == 0:
        for required in (wolfboot, signed_application):
            if not required.artifact_exists:
                return_code = SECURE_BOOT_ARTIFACT_MISSING_RETURN_CODE
                failure_stage = f"{required.name}_artifact"
                failure_reason = f"Required artifact not found: {required.artifact_path}"
                break

    if return_code == 0:
        try:
            require_any_recorded_artifact(
                repo_root=repo_root_path,
                artifact_path=wolfboot.artifact_path,
                workflow="wolfboot_build",
            )
            require_any_recorded_artifact(
                repo_root=repo_root_path,
                artifact_path=original_signed_application_path,
                workflow="application_signing",
            )
        except GeneratedStateError as exc:
            return_code = SECURE_BOOT_ARTIFACT_MISSING_RETURN_CODE
            failure_stage = "artifact_provenance"
            failure_reason = f"Secure-boot flashing requires successful build/signing provenance: {exc}"

    if return_code == 0:
        artifacts_to_flash = [wolfboot, signed_application]
    else:
        artifacts_to_flash = []

    for artifact in artifacts_to_flash:
        if not artifact.artifact_exists:
            return_code = SECURE_BOOT_ARTIFACT_MISSING_RETURN_CODE
            failure_stage = f"{artifact.name}_artifact"
            failure_reason = f"Required artifact not found: {artifact.artifact_path}"
            break

        scp_execution = runner(
            construct_scp_command(
                artifact.artifact_path,
                gateway_target,
                artifact.remote_artifact_path,
            ),
            repo_root_path,
        )
        artifact = _with_executions(artifact, scp=scp_execution, flash=None)
        if artifact.name == "wolfboot":
            wolfboot = artifact
        else:
            signed_application = artifact

        if scp_execution.return_code != 0:
            return_code = scp_execution.return_code or SECURE_BOOT_SCP_FAILED_RETURN_CODE
            failure_stage = f"{artifact.name}_scp"
            failure_reason = f"SCP failed for {artifact.name}."
            break

        flash_execution = runner(
            construct_ssh_flash_command(
                gateway_target,
                flash_helper,
                artifact.remote_artifact_path,
                artifact.offset,
                pass_offset_to_helper=artifact.pass_offset_to_helper,
            ),
            repo_root_path,
        )
        artifact = _with_executions(artifact, scp=scp_execution, flash=flash_execution)
        if artifact.name == "wolfboot":
            wolfboot = artifact
        else:
            signed_application = artifact

        if flash_execution.return_code != 0:
            return_code = flash_execution.return_code or SECURE_BOOT_FLASH_FAILED_RETURN_CODE
            failure_stage = f"{artifact.name}_flash"
            failure_reason = f"Flash helper failed for {artifact.name}."
            break

    duration_seconds = perf_counter() - start
    source = (
        capture_reproducibility_provenance(repo_root_path)
        if git_runner is None
        else capture_reproducibility_provenance(repo_root_path, git_runner=git_runner)
    )

    fingerprint_evidence = _fingerprint_evidence(
        repo_root=repo_root_path,
        bundle=bundle,
        wolfboot=wolfboot,
        signed_application=signed_application,
    )

    result = SecureBootFlashResult(
        return_code=return_code,
        duration_seconds=duration_seconds,
        result_dir=result_dir_path,
        log_path=log_path,
        stlink_serial=stlink_serial,
        gateway_alias=gateway_alias,
        flash_helper=flash_helper,
        wolfboot=wolfboot,
        signed_application=signed_application,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        negative_test_enabled=negative_test_enabled,
        corruption_method=corruption_method,
        original_signed_application_path=original_signed_application_path,
        original_signed_application_sha256=original_signed_application_sha256,
        corrupted_signed_application_path=corrupted_signed_application_path,
        corrupted_signed_application_sha256=corrupted_signed_application_sha256,
        key_consistency_status=str(key_consistency["status"]),
        key_consistency_message=str(key_consistency["message"]),
        signing_private_key_path=None if key_consistency["signing_private_key_path"] is None else Path(str(key_consistency["signing_private_key_path"])),
        wolfboot_private_key_path=None if key_consistency["wolfboot_private_key_path"] is None else Path(str(key_consistency["wolfboot_private_key_path"])),
        signing_private_key_sha256=key_consistency["signing_private_key_sha256"],
        wolfboot_private_key_sha256=key_consistency["wolfboot_private_key_sha256"],
    )

    _write_secure_boot_flash_log(log_path=log_path, repo_root=repo_root_path, result=result)

    manifest_path = result_dir_path / "manifest.json"
    current_manifest = read_manifest(manifest_path)
    current_firmware = current_manifest.get("firmware", {})
    if not isinstance(current_firmware, dict):
        current_firmware = {}
    current_firmware.update(
        {
            "artifact": str(secure_boot_config["signed_application_artifact"]),
            "artifact_path": str(signed_application.artifact_path),
            "artifact_exists": signed_application.artifact_exists,
            "sha256": signed_application.artifact_sha256,
        }
    )

    boot_crypto = str(experiment.get("boot_crypto", "ecdsa_p256"))
    boot_signature = _signature_metadata(experiment)
    signature_size = boot_signature["signature_size"]
    flash_result_status = "secure_boot_flash_passed" if return_code == 0 else "secure_boot_flash_failed"
    boot_mode = str(bundle.get("boot", {}).get("mode", experiment.get("firmware", {}).get("mode", "unknown")))
    unsigned_application_path = _optional_secure_boot_artifact_path(
        repo_root=repo_root_path,
        secure_boot_config=secure_boot_config,
        key="unsigned_application_artifact",
    )
    static_resource_metrics, static_resource_limitations = _static_resource_metrics_for_wolfboot(wolfboot.artifact_path)
    benchmark_evidence = build_secure_boot_benchmark_model(
        experiment_id=str(experiment["id"]),
        boot_mode=boot_mode,
        boot_crypto=boot_crypto,
        signature_algorithm=boot_signature["algorithm"],
        signature_size_bytes=signature_size,
        image_version=boot_signature["image_version"],
        wolfboot_artifact_path=str(wolfboot.artifact_path),
        wolfboot_sha256=wolfboot.artifact_sha256,
        wolfboot_elf_size_bytes=_artifact_size_bytes(wolfboot.artifact_path),
        retained_wolfboot_artifact_path=str(wolfboot.artifact_path),
        retained_wolfboot_artifact_size_bytes=_artifact_size_bytes(wolfboot.artifact_path),
        signed_application_artifact_path=str(signed_application.artifact_path),
        signed_application_sha256=signed_application.artifact_sha256,
        signed_application_size_bytes=_artifact_size_bytes(signed_application.artifact_path),
        unsigned_application_artifact_path=None if unsigned_application_path is None else str(unsigned_application_path),
        unsigned_application_sha256=_artifact_sha256(unsigned_application_path),
        unsigned_application_size_bytes=_artifact_size_bytes(unsigned_application_path) if unsigned_application_path is not None else None,
        bootloader_text_bytes=static_resource_metrics.get("bootloader_text_bytes"),
        bootloader_data_bytes=static_resource_metrics.get("bootloader_data_bytes"),
        bootloader_bss_bytes=static_resource_metrics.get("bootloader_bss_bytes"),
        bootloader_flash_bytes=static_resource_metrics.get("bootloader_flash_bytes"),
        bootloader_static_ram_bytes=static_resource_metrics.get("bootloader_static_ram_bytes"),
        static_metrics_source="wolfboot_elf_section_headers" if static_resource_metrics else "unavailable",
        static_metrics_limitations=static_resource_limitations,
        verification_time_source="unavailable",
        verification_cycles_source="unavailable",
        runtime_measurement_method="UART capture has not run at the secure-boot flash stage.",
        runtime_limitations="No runtime verification timing evidence is available until post-flash UART capture runs.",
        classical_profile_metadata=_classical_profile_metadata(experiment),
    )

    update_manifest(
        manifest_path,
        {
            "result": flash_result_status,
            "source": source,
            "firmware": current_firmware,
            "boot_crypto": boot_crypto,
            "signature_size": signature_size,
            "boot_signature": boot_signature,
            "secure_boot_evidence": {
                "schema_version": 1,
                "result": flash_result_status,
                "boot_mode": boot_mode,
                "boot_crypto": boot_crypto,
                "signature_algorithm": boot_signature["algorithm"],
                "signature_size": signature_size,
                "signature_size_bytes": signature_size,
                "image_version": boot_signature["image_version"],
                "build_evidence": {
                    "wolfboot_artifact_path": str(wolfboot.artifact_path),
                    "wolfboot_sha256": wolfboot.artifact_sha256,
                    "secure_boot_flash_fingerprint": fingerprint_evidence.get("fingerprint"),
                    "secure_boot_flash_fingerprint_algorithm": fingerprint_evidence.get("fingerprint_algorithm"),
                },
                "signing_evidence": {
                    "signed_application_artifact_path": str(signed_application.artifact_path),
                    "signed_application_sha256": signed_application.artifact_sha256,
                    "secure_boot_flash_fingerprint": fingerprint_evidence.get("fingerprint"),
                    "original_signed_application_path": str(original_signed_application_path),
                    "original_signed_application_sha256": original_signed_application_sha256,
                    "key_consistency": key_consistency,
                },
                "flash_evidence": {
                    "log": DEFAULT_SECURE_BOOT_FLASH_LOG_NAME,
                    "return_code": return_code,
                    "failure_stage": failure_stage,
                    "wolfboot_offset": wolfboot.offset,
                    "signed_application_offset": signed_application.offset,
                    "wolfboot_scp_return_code": None if wolfboot.scp is None else wolfboot.scp.return_code,
                    "wolfboot_helper_return_code": None if wolfboot.flash is None else wolfboot.flash.return_code,
                    "signed_application_scp_return_code": None if signed_application.scp is None else signed_application.scp.return_code,
                    "signed_application_helper_return_code": None if signed_application.flash is None else signed_application.flash.return_code,
                },
                "uart_evidence": {
                    "log": None,
                    "skipped": True,
                    "boot_marker_present": None,
                    "tick_present": None,
                    "secure_boot_marker_present": None,
                },
                "boot_timing": {
                    "derived_verification_time_ms": None,
                    "verification_time_source": "unavailable",
                },
                "artifact_freshness": fingerprint_evidence,
                "negative_test": {
                    "enabled": negative_test_enabled,
                    "method": corruption_method,
                    "source_image_modified": False,
                },
            },
            "secure_boot_benchmark": benchmark_evidence,
            "secure_boot_flash": {
                "return_code": return_code,
                "duration_seconds": round(duration_seconds, 3),
                "log": DEFAULT_SECURE_BOOT_FLASH_LOG_NAME,
                "failure_stage": failure_stage,
                "failure_reason": failure_reason,
                "gateway_alias": gateway_alias,
                "flash_helper": flash_helper,
                "stlink_serial": stlink_serial,
                "negative_test_enabled": negative_test_enabled,
                "corruption_method": corruption_method,
                "artifact_freshness": fingerprint_evidence,
                "key_consistency": key_consistency,
                "wolfboot": _artifact_result_to_manifest(wolfboot),
                "signed_application": _artifact_result_to_manifest(signed_application),
                "negative_test": {
                    "enabled": negative_test_enabled,
                    "method": corruption_method,
                    "original_signed_application_path": str(original_signed_application_path),
                    "original_signed_application_sha256": original_signed_application_sha256,
                    "corrupted_signed_application_path": None
                    if corrupted_signed_application_path is None
                    else str(corrupted_signed_application_path),
                    "corrupted_signed_application_sha256": corrupted_signed_application_sha256,
                    "source_image_modified": False,
                },
            },
        },
    )

    return result
