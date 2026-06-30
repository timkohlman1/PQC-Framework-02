"""Result manifest helpers for experiment runs.

This module creates deterministic result-directory metadata without building
firmware, flashing hardware, opening UART devices, using SSH, or touching
network resources.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

RUN_ID_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<sequence>\d{3})_(?P<experiment>[A-Za-z0-9_.-]+)$")
DEFAULT_RESULT_STATUS = "pending"
DEFAULT_TRANSPORT_MODE = "direct_uart"
DEFAULT_NETWORK_PROFILE = "none"


SECURE_BOOT_BENCHMARK_SCHEMA_VERSION = 1
SECURE_BOOT_BENCHMARK_MODEL_PHASE = "phase_11_1_schema_only"
UNAVAILABLE_METRIC_SOURCE = "unavailable"


def _unavailable_reason(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "source": UNAVAILABLE_METRIC_SOURCE,
        "reason": reason,
    }


def build_secure_boot_benchmark_model(
    *,
    experiment_id: str,
    boot_mode: str,
    boot_crypto: str | None,
    signature_algorithm: str | None,
    signature_size_bytes: int | None,
    image_version: Any = None,
    wolfboot_artifact_path: str | None = None,
    wolfboot_sha256: str | None = None,
    wolfboot_elf_size_bytes: int | None = None,
    signed_application_artifact_path: str | None = None,
    signed_application_sha256: str | None = None,
    signed_application_size_bytes: int | None = None,
    verification_time_ms: int | None = None,
    verification_cycles: int | None = None,
    verification_cpu_hz: int | None = None,
    verification_result_code: int | None = None,
    verification_time_source: str = UNAVAILABLE_METRIC_SOURCE,
    verification_cycles_source: str = UNAVAILABLE_METRIC_SOURCE,
    runtime_measurement_method: str | None = None,
    runtime_limitations: str | list[str] | None = None,
) -> dict[str, Any]:
    """Build the Phase 11.1 secure-boot benchmark evidence schema.

    The Phase 11.1 model is intentionally schema-first. It records any
    already available secure-boot timing and artifact-size evidence, while
    explicitly marking repeated-run, aggregate, static-resource, stack, and
    heap metrics as unavailable until later Phase 11 sub-steps implement the
    required collection mechanisms.
    """

    unavailable_build_reason = (
        "Phase 11.1 defines the benchmark schema only; static build/resource "
        "metrics are added in the later Phase 11.3 build-metrics step."
    )
    unavailable_unsigned_reason = (
        "Unsigned application size is not linked into the Phase 11.1 secure-boot "
        "run schema yet."
    )
    unavailable_overhead_reason = (
        "Signed-image overhead requires both unsigned and signed image sizes; "
        "Phase 11.1 records the schema placeholder only when either input is unavailable."
    )
    unavailable_runtime_memory_reason = (
        "Runtime stack and heap metrics require explicit firmware-side measurement "
        "evidence and are added in the later Phase 11.4 runtime-memory step."
    )
    unavailable_repeated_reason = (
        "Phase 11.1 defines the repeated-run sample schema only; repeated execution "
        "is added in the later Phase 11.2 step."
    )
    unavailable_aggregate_reason = (
        "Aggregate statistics require repeated-run samples and are calculated in "
        "later Phase 11 steps."
    )

    if runtime_limitations is None:
        runtime_limitations_list: list[str] = []
    elif isinstance(runtime_limitations, list):
        runtime_limitations_list = [str(item) for item in runtime_limitations]
    else:
        runtime_limitations_list = [str(runtime_limitations)]

    runtime_status = "available" if verification_time_ms is not None else "unavailable"
    cycles_status = "available" if verification_cycles is not None else "unavailable"

    return {
        "schema_version": SECURE_BOOT_BENCHMARK_SCHEMA_VERSION,
        "model_phase": SECURE_BOOT_BENCHMARK_MODEL_PHASE,
        "benchmark_scope": "secure_boot_classical_signing_algorithm",
        "profile_id": experiment_id,
        "boot_mode": boot_mode,
        "boot_crypto": boot_crypto,
        "signature_algorithm": signature_algorithm,
        "signature_size_bytes": signature_size_bytes,
        "image_version": image_version,
        "build_time_metrics": {
            "status": "unavailable",
            "unavailable": _unavailable_reason(unavailable_build_reason),
            "bootloader_text_bytes": None,
            "bootloader_data_bytes": None,
            "bootloader_bss_bytes": None,
            "bootloader_flash_bytes": None,
            "bootloader_static_ram_bytes": None,
            "static_ram_bytes": None,
            "limitations": [unavailable_build_reason],
        },
        "signed_artifact_metrics": {
            "status": "partial" if signed_application_size_bytes is not None or wolfboot_elf_size_bytes is not None else "unavailable",
            "wolfboot_artifact_path": wolfboot_artifact_path,
            "wolfboot_sha256": wolfboot_sha256,
            "wolfboot_elf_size_bytes": wolfboot_elf_size_bytes,
            "signed_application_artifact_path": signed_application_artifact_path,
            "signed_application_sha256": signed_application_sha256,
            "signed_application_size_bytes": signed_application_size_bytes,
            "signature_size_bytes": signature_size_bytes,
            "unsigned_application_size_bytes": None,
            "unsigned_application_size_unavailable": _unavailable_reason(unavailable_unsigned_reason),
            "signed_image_overhead_bytes": None,
            "signed_image_overhead_percent": None,
            "signed_image_overhead_unavailable": _unavailable_reason(unavailable_overhead_reason),
            "limitations": [unavailable_unsigned_reason, unavailable_overhead_reason],
        },
        "runtime_verification_metrics": {
            "status": runtime_status,
            "verification_time_ms": verification_time_ms,
            "verification_cycles": verification_cycles,
            "verification_cpu_hz": verification_cpu_hz,
            "verification_result_code": verification_result_code,
            "verification_time_source": verification_time_source,
            "verification_cycles_source": verification_cycles_source,
            "measurement_method": runtime_measurement_method,
            "limitations": runtime_limitations_list,
        },
        "runtime_memory_metrics": {
            "status": "unavailable",
            "unavailable": _unavailable_reason(unavailable_runtime_memory_reason),
            "max_stack_used_bytes": None,
            "stack_metric_source": UNAVAILABLE_METRIC_SOURCE,
            "heap_used_bytes": None,
            "heap_metric_source": UNAVAILABLE_METRIC_SOURCE,
            "estimated_total_ram_pressure_bytes": None,
            "runtime_memory_limitations": [unavailable_runtime_memory_reason],
        },
        "repeated_run_samples": {
            "status": "not_configured",
            "unavailable": _unavailable_reason(unavailable_repeated_reason),
            "samples": [],
            "sample_schema": {
                "run_index": None,
                "timestamp": None,
                "verification_time_ms": None,
                "verification_cycles": None,
                "verification_cpu_hz": None,
                "verification_result_code": None,
                "uart_marker_detection_result": None,
                "sample_verdict": None,
                "referenced_artifact_identity": None,
            },
            "limitations": [unavailable_repeated_reason],
        },
        "aggregate_statistics": {
            "status": "unavailable",
            "unavailable": _unavailable_reason(unavailable_aggregate_reason),
            "sample_count": 0,
            "valid_sample_count": 0,
            "failed_sample_count": 0,
            "verification_time_ms": {
                "minimum": None,
                "mean": None,
                "median": None,
                "maximum": None,
                "standard_deviation": None,
            },
            "verification_cycles": {
                "minimum": None,
                "mean": None,
                "median": None,
                "maximum": None,
                "standard_deviation": None,
            },
            "derived_metrics": {
                "cycles_per_kb": None,
                "time_ms_per_kb": None,
            },
            "limitations": [unavailable_aggregate_reason],
        },
        "limitations": [
            unavailable_build_reason,
            unavailable_runtime_memory_reason,
            unavailable_repeated_reason,
            unavailable_aggregate_reason,
        ],
    }


def _coerce_timestamp(timestamp: datetime | None) -> datetime:
    """Return a timestamp, using local time when one is not supplied."""

    if timestamp is None:
        return datetime.now().astimezone()
    return timestamp


def format_manifest_timestamp(timestamp: datetime | None = None) -> str:
    """Format a manifest timestamp as ISO 8601 text."""

    return _coerce_timestamp(timestamp).isoformat(timespec="seconds")


def _safe_run_id_component(value: str) -> str:
    """Convert a value into a conservative run-id component."""

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    safe = safe.strip("_.-")

    if not safe:
        raise ValueError("run ID component must contain at least one safe character")

    return safe


def next_run_id(
    experiment_id: str,
    results_root: Path | str = "results",
    timestamp: datetime | None = None,
) -> str:
    """Generate the next run ID for a results root.

    The format is:

        YYYY-MM-DD_NNN_experiment_id

    The numeric sequence is allocated per date across all existing result
    directories under ``results_root``.
    """

    current_timestamp = _coerce_timestamp(timestamp)
    run_date = current_timestamp.date().isoformat()
    safe_experiment_id = _safe_run_id_component(experiment_id)
    root = Path(results_root)

    highest_sequence = 0

    if root.exists():
        for child in root.iterdir():
            if not child.is_dir():
                continue

            match = RUN_ID_PATTERN.match(child.name)
            if match is None or match.group("date") != run_date:
                continue

            highest_sequence = max(highest_sequence, int(match.group("sequence")))

    return f"{run_date}_{highest_sequence + 1:03d}_{safe_experiment_id}"


def build_manifest(
    bundle: dict[str, dict[str, Any]],
    run_id: str,
    timestamp: datetime | None = None,
    result: str = DEFAULT_RESULT_STATUS,
) -> dict[str, Any]:
    """Build the initial manifest dictionary for an experiment bundle."""

    experiment = bundle["experiment"]
    board = bundle["board"]
    host = bundle["host"]
    boot = bundle.get("boot", {})

    firmware = experiment.get("firmware", {})
    transport = experiment.get("transport", {})
    network = experiment.get("network", {})

    return {
        "run_id": run_id,
        "timestamp": format_manifest_timestamp(timestamp),
        "experiment": experiment["id"],
        "board": board["id"],
        "gateway": host["id"],
        "boot_mode": boot.get("mode", firmware.get("mode", "unknown")),
        "transport_mode": transport.get("mode", DEFAULT_TRANSPORT_MODE),
        "network_profile": network.get("profile", DEFAULT_NETWORK_PROFILE),
        "result": result,
    }


def write_manifest(path: Path | str, manifest: dict[str, Any]) -> None:
    """Write a manifest JSON file with stable formatting."""

    manifest_path = Path(path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path | str) -> dict[str, Any]:
    """Read a manifest JSON file."""

    manifest_path = Path(path)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def update_manifest(path: Path | str, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge top-level updates into a manifest JSON file and rewrite it."""

    manifest_path = Path(path)
    manifest = read_manifest(manifest_path)
    manifest.update(updates)
    write_manifest(manifest_path, manifest)
    return manifest


def create_result_folder(
    bundle: dict[str, dict[str, Any]],
    results_root: Path | str = "results",
    timestamp: datetime | None = None,
    result: str = DEFAULT_RESULT_STATUS,
) -> tuple[Path, dict[str, Any]]:
    """Create results/<run_id>/ with manifest.json and notes.md."""

    current_timestamp = _coerce_timestamp(timestamp)
    root = Path(results_root)
    run_id = next_run_id(bundle["experiment"]["id"], root, current_timestamp)
    result_dir = root / run_id

    result_dir.mkdir(parents=True, exist_ok=False)

    manifest = build_manifest(bundle, run_id, current_timestamp, result=result)
    write_manifest(result_dir / "manifest.json", manifest)
    (result_dir / "notes.md").write_text(
        f"# Notes for {run_id}\n\n"
        "Add manual observations for this experiment run here.\n",
        encoding="utf-8",
    )

    return result_dir, manifest
