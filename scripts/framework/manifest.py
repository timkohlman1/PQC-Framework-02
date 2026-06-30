"""Result manifest helpers for experiment runs.

This module creates deterministic result-directory metadata without building
firmware, flashing hardware, opening UART devices, using SSH, or touching
network resources.
"""

from __future__ import annotations

import json
import re
import statistics
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

RUN_ID_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<sequence>\d{3})_(?P<experiment>[A-Za-z0-9_.-]+)$")
DEFAULT_RESULT_STATUS = "pending"
DEFAULT_TRANSPORT_MODE = "direct_uart"
DEFAULT_NETWORK_PROFILE = "none"


SECURE_BOOT_BENCHMARK_SCHEMA_VERSION = 1
SECURE_BOOT_BENCHMARK_MODEL_PHASE = "phase_11_1_schema_only"
SECURE_BOOT_BENCHMARK_REPEATED_MODEL_PHASE = "phase_11_2_repeated_run_support"
SECURE_BOOT_BENCHMARK_STATIC_METRICS_MODEL_PHASE = "phase_11_3_static_build_resource_metrics"
SECURE_BOOT_BENCHMARK_RUNTIME_MEMORY_MODEL_PHASE = "phase_11_4_runtime_memory_metrics"
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
    unsigned_application_artifact_path: str | None = None,
    unsigned_application_sha256: str | None = None,
    unsigned_application_size_bytes: int | None = None,
    bootloader_text_bytes: int | None = None,
    bootloader_data_bytes: int | None = None,
    bootloader_bss_bytes: int | None = None,
    bootloader_flash_bytes: int | None = None,
    bootloader_static_ram_bytes: int | None = None,
    retained_wolfboot_artifact_path: str | None = None,
    retained_wolfboot_artifact_size_bytes: int | None = None,
    static_metrics_source: str = UNAVAILABLE_METRIC_SOURCE,
    static_metrics_limitations: str | list[str] | None = None,
    verification_time_ms: int | None = None,
    verification_cycles: int | None = None,
    verification_cpu_hz: int | None = None,
    verification_result_code: int | None = None,
    verification_time_source: str = UNAVAILABLE_METRIC_SOURCE,
    verification_cycles_source: str = UNAVAILABLE_METRIC_SOURCE,
    runtime_measurement_method: str | None = None,
    runtime_limitations: str | list[str] | None = None,
    max_stack_used_bytes: int | None = None,
    stack_metric_source: str = UNAVAILABLE_METRIC_SOURCE,
    heap_used_bytes: int | None = None,
    heap_metric_source: str = UNAVAILABLE_METRIC_SOURCE,
    runtime_memory_limitations: str | list[str] | None = None,
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
        "Runtime stack and heap metrics require explicit firmware-side measurement evidence; "
        "no explicit firmware-side stack or heap evidence was available for this run."
    )
    unavailable_heap_reason = (
        "Heap usage is not recorded because the secure-boot verification path does not provide "
        "explicit firmware-side heap measurement evidence."
    )
    unavailable_repeated_reason = (
        "Repeated execution has not been configured for this run."
    )
    unavailable_aggregate_reason = (
        "Aggregate statistics require repeated-run samples; no repeated samples are available for this run."
    )

    if runtime_limitations is None:
        runtime_limitations_list: list[str] = []
    elif isinstance(runtime_limitations, list):
        runtime_limitations_list = [str(item) for item in runtime_limitations]
    else:
        runtime_limitations_list = [str(runtime_limitations)]

    if static_metrics_limitations is None:
        static_limitations_list: list[str] = []
    elif isinstance(static_metrics_limitations, list):
        static_limitations_list = [str(item) for item in static_metrics_limitations]
    else:
        static_limitations_list = [str(static_metrics_limitations)]

    if runtime_memory_limitations is None:
        runtime_memory_limitations_list: list[str] = []
    elif isinstance(runtime_memory_limitations, list):
        runtime_memory_limitations_list = [str(item) for item in runtime_memory_limitations]
    else:
        runtime_memory_limitations_list = [str(runtime_memory_limitations)]

    static_metric_values = [
        bootloader_text_bytes,
        bootloader_data_bytes,
        bootloader_bss_bytes,
        bootloader_flash_bytes,
        bootloader_static_ram_bytes,
    ]
    static_metrics_available = all(value is not None for value in static_metric_values)
    if static_metrics_available:
        build_time_status = "available"
        build_time_unavailable = None
        build_time_limitations = static_limitations_list
    else:
        build_time_status = "unavailable"
        build_time_unavailable = _unavailable_reason(unavailable_build_reason)
        build_time_limitations = [unavailable_build_reason] + static_limitations_list

    signed_overhead_bytes = None
    signed_overhead_percent = None
    if signed_application_size_bytes is not None and unsigned_application_size_bytes is not None:
        signed_overhead_bytes = signed_application_size_bytes - unsigned_application_size_bytes
        signed_overhead_percent = (
            None
            if unsigned_application_size_bytes == 0
            else (signed_overhead_bytes / unsigned_application_size_bytes) * 100
        )

    signed_artifact_status = (
        "available"
        if signed_application_size_bytes is not None
        and wolfboot_elf_size_bytes is not None
        and unsigned_application_size_bytes is not None
        and signed_overhead_bytes is not None
        else "partial"
        if signed_application_size_bytes is not None or wolfboot_elf_size_bytes is not None or unsigned_application_size_bytes is not None
        else "unavailable"
    )
    signed_artifact_limitations: list[str] = []
    unsigned_unavailable = None
    overhead_unavailable = None
    if unsigned_application_size_bytes is None:
        unsigned_unavailable = _unavailable_reason(unavailable_unsigned_reason)
        signed_artifact_limitations.append(unavailable_unsigned_reason)
    if signed_overhead_bytes is None:
        overhead_unavailable = _unavailable_reason(unavailable_overhead_reason)
        signed_artifact_limitations.append(unavailable_overhead_reason)

    runtime_status = "available" if verification_time_ms is not None else "unavailable"
    cycles_status = "available" if verification_cycles is not None else "unavailable"
    runtime_memory_available = max_stack_used_bytes is not None
    runtime_memory_status = "available" if runtime_memory_available else "unavailable"
    runtime_memory_unavailable = None if runtime_memory_available else _unavailable_reason(unavailable_runtime_memory_reason)
    heap_unavailable = None if heap_used_bytes is not None else _unavailable_reason(unavailable_heap_reason)
    estimated_total_ram_pressure_bytes = (
        None
        if bootloader_static_ram_bytes is None or max_stack_used_bytes is None
        else bootloader_static_ram_bytes + max_stack_used_bytes
    )
    if runtime_memory_available:
        runtime_memory_limitations_final = list(runtime_memory_limitations_list)
        if heap_used_bytes is None:
            runtime_memory_limitations_final.append(unavailable_heap_reason)
    else:
        runtime_memory_limitations_final = [unavailable_runtime_memory_reason] + runtime_memory_limitations_list

    if runtime_memory_available:
        model_phase = SECURE_BOOT_BENCHMARK_RUNTIME_MEMORY_MODEL_PHASE
    elif static_metrics_available:
        model_phase = SECURE_BOOT_BENCHMARK_STATIC_METRICS_MODEL_PHASE
    else:
        model_phase = SECURE_BOOT_BENCHMARK_MODEL_PHASE

    return {
        "schema_version": SECURE_BOOT_BENCHMARK_SCHEMA_VERSION,
        "model_phase": model_phase,
        "benchmark_scope": "secure_boot_classical_signing_algorithm",
        "profile_id": experiment_id,
        "boot_mode": boot_mode,
        "boot_crypto": boot_crypto,
        "signature_algorithm": signature_algorithm,
        "signature_size_bytes": signature_size_bytes,
        "image_version": image_version,
        "build_time_metrics": {
            "status": build_time_status,
            "unavailable": build_time_unavailable,
            "source": static_metrics_source,
            "bootloader_text_bytes": bootloader_text_bytes,
            "bootloader_data_bytes": bootloader_data_bytes,
            "bootloader_bss_bytes": bootloader_bss_bytes,
            "bootloader_flash_bytes": bootloader_flash_bytes,
            "bootloader_static_ram_bytes": bootloader_static_ram_bytes,
            "static_ram_bytes": bootloader_static_ram_bytes,
            "limitations": build_time_limitations,
        },
        "signed_artifact_metrics": {
            "status": signed_artifact_status,
            "wolfboot_artifact_path": wolfboot_artifact_path,
            "wolfboot_sha256": wolfboot_sha256,
            "wolfboot_elf_size_bytes": wolfboot_elf_size_bytes,
            "retained_wolfboot_artifact_path": retained_wolfboot_artifact_path,
            "retained_wolfboot_artifact_size_bytes": retained_wolfboot_artifact_size_bytes,
            "signed_application_artifact_path": signed_application_artifact_path,
            "signed_application_sha256": signed_application_sha256,
            "signed_application_size_bytes": signed_application_size_bytes,
            "signature_size_bytes": signature_size_bytes,
            "unsigned_application_artifact_path": unsigned_application_artifact_path,
            "unsigned_application_sha256": unsigned_application_sha256,
            "unsigned_application_size_bytes": unsigned_application_size_bytes,
            "unsigned_application_size_unavailable": unsigned_unavailable,
            "signed_image_overhead_bytes": signed_overhead_bytes,
            "signed_image_overhead_percent": signed_overhead_percent,
            "signed_image_overhead_unavailable": overhead_unavailable,
            "limitations": signed_artifact_limitations,
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
            "status": runtime_memory_status,
            "unavailable": runtime_memory_unavailable,
            "max_stack_used_bytes": max_stack_used_bytes,
            "stack_metric_source": stack_metric_source,
            "heap_used_bytes": heap_used_bytes,
            "heap_metric_source": heap_metric_source,
            "heap_unavailable": heap_unavailable,
            "static_ram_bytes": bootloader_static_ram_bytes,
            "estimated_total_ram_pressure_bytes": estimated_total_ram_pressure_bytes,
            "measurement_method": (
                "Parse explicit firmware-side stack high-water evidence emitted by the secure-boot application over UART."
                if runtime_memory_available
                else None
            ),
            "runtime_memory_limitations": runtime_memory_limitations_final,
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
                "runtime_memory_metrics": {
                    "max_stack_used_bytes": None,
                    "stack_metric_source": None,
                    "heap_used_bytes": None,
                    "heap_metric_source": None,
                    "runtime_memory_limitations": None,
                },
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
                "range": None,
                "coefficient_of_variation_percent": None,
            },
            "verification_cycles": {
                "minimum": None,
                "mean": None,
                "median": None,
                "maximum": None,
                "standard_deviation": None,
                "range": None,
                "coefficient_of_variation_percent": None,
            },
            "derived_metrics": {
                "cycles_per_kb": None,
                "time_ms_per_kb": None,
            },
            "limitations": [unavailable_aggregate_reason],
        },
        "limitations": (
            ([] if static_metrics_available else [unavailable_build_reason])
            + ([] if runtime_memory_available else [unavailable_runtime_memory_reason])
            + [unavailable_repeated_reason, unavailable_aggregate_reason]
            + static_limitations_list
            + runtime_memory_limitations_list
        ),
    }



def _read_c_string(blob: bytes, offset: int) -> str:
    end = blob.find(b"\x00", offset)
    if end < 0:
        end = len(blob)
    return blob[offset:end].decode("utf-8", errors="replace")



def read_elf_alloc_section_metrics(elf_path: Path | str) -> dict[str, Any]:
    """Read static section-size metrics from an ELF file without target execution.

    The flash-relevant size is calculated as the sum of SHF_ALLOC sections
    that occupy bytes in the ELF image. NOBITS sections such as `.bss` count
    toward static RAM but not flash bytes.
    """

    path = Path(elf_path)
    data = path.read_bytes()
    if len(data) < 52 or data[:4] != b"\x7fELF":
        raise ValueError(f"not an ELF file: {path}")

    elf_class = data[4]
    endian_id = data[5]
    if elf_class not in {1, 2}:
        raise ValueError(f"unsupported ELF class in {path}: {elf_class}")
    if endian_id == 1:
        endian = "<"
    elif endian_id == 2:
        endian = ">"
    else:
        raise ValueError(f"unsupported ELF endianness in {path}: {endian_id}")

    if elf_class == 1:
        header_format = endian + "16sHHIIIIIHHHHHH"
        section_format = endian + "IIIIIIIIII"
        sh_type_index = 1
        sh_flags_index = 2
        sh_offset_index = 4
        sh_size_index = 5
        _, _, _, _, _, _, e_shoff, _, _, _, _, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(header_format, data, 0)
    else:
        header_format = endian + "16sHHIQQQIHHHHHH"
        section_format = endian + "IIQQQQIIQQ"
        sh_type_index = 1
        sh_flags_index = 2
        sh_offset_index = 4
        sh_size_index = 5
        _, _, _, _, _, _, e_shoff, _, _, _, _, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(header_format, data, 0)

    if e_shoff == 0 or e_shnum == 0:
        raise ValueError(f"ELF file has no section table: {path}")
    if e_shstrndx >= e_shnum:
        raise ValueError(f"ELF file has invalid section string table index: {path}")

    section_headers = []
    section_header_size = struct.calcsize(section_format)
    for index in range(e_shnum):
        offset = e_shoff + index * e_shentsize
        if offset + section_header_size > len(data):
            raise ValueError(f"ELF section header extends past end of file: {path}")
        section_headers.append(struct.unpack_from(section_format, data, offset))

    string_header = section_headers[e_shstrndx]
    string_offset = int(string_header[sh_offset_index])
    string_size = int(string_header[sh_size_index])
    string_table = data[string_offset:string_offset + string_size]

    SHF_ALLOC = 0x2
    SHT_NOBITS = 8
    named_sizes = {".text": 0, ".data": 0, ".bss": 0}
    flash_bytes = 0

    for header in section_headers:
        name = _read_c_string(string_table, int(header[0]))
        section_type = int(header[sh_type_index])
        flags = int(header[sh_flags_index])
        size = int(header[sh_size_index])
        if name in named_sizes:
            named_sizes[name] += size
        if flags & SHF_ALLOC and section_type != SHT_NOBITS:
            flash_bytes += size

    static_ram_bytes = named_sizes[".data"] + named_sizes[".bss"]
    return {
        "bootloader_text_bytes": named_sizes[".text"],
        "bootloader_data_bytes": named_sizes[".data"],
        "bootloader_bss_bytes": named_sizes[".bss"],
        "bootloader_flash_bytes": flash_bytes,
        "bootloader_static_ram_bytes": static_ram_bytes,
        "static_ram_bytes": static_ram_bytes,
    }



def build_secure_boot_benchmark_sample(
    *,
    run_index: int,
    timestamp: str,
    verification_time_ms: float | int | None,
    verification_cycles: int | None,
    verification_cpu_hz: int | None,
    verification_result_code: int | None,
    verification_time_source: str,
    verification_cycles_source: str,
    uart_marker_detection_result: dict[str, Any],
    sample_verdict: str,
    referenced_artifact_identity: dict[str, Any],
    max_stack_used_bytes: int | None = None,
    stack_metric_source: str = UNAVAILABLE_METRIC_SOURCE,
    heap_used_bytes: int | None = None,
    heap_metric_source: str = UNAVAILABLE_METRIC_SOURCE,
    runtime_memory_limitations: str | None = None,
) -> dict[str, Any]:
    """Build one Phase 11.2 repeated-run benchmark sample."""

    return {
        "run_index": int(run_index),
        "timestamp": timestamp,
        "verification_time_ms": verification_time_ms,
        "verification_cycles": verification_cycles,
        "verification_cpu_hz": verification_cpu_hz,
        "verification_result_code": verification_result_code,
        "verification_time_source": verification_time_source,
        "verification_cycles_source": verification_cycles_source,
        "uart_marker_detection_result": uart_marker_detection_result,
        "sample_verdict": sample_verdict,
        "valid_for_statistics": sample_verdict == "passed"
        and verification_time_ms is not None
        and verification_cycles is not None,
        "referenced_artifact_identity": referenced_artifact_identity,
        "runtime_memory_metrics": {
            "max_stack_used_bytes": max_stack_used_bytes,
            "stack_metric_source": stack_metric_source,
            "heap_used_bytes": heap_used_bytes,
            "heap_metric_source": heap_metric_source,
            "runtime_memory_limitations": runtime_memory_limitations,
        },
    }


def _metric_statistics(values: list[float | int]) -> dict[str, Any]:
    if not values:
        return {
            "minimum": None,
            "mean": None,
            "median": None,
            "maximum": None,
            "standard_deviation": None,
            "range": None,
            "coefficient_of_variation_percent": None,
        }
    mean_value = statistics.mean(values)
    standard_deviation = 0.0 if len(values) == 1 else statistics.stdev(values)
    return {
        "minimum": min(values),
        "mean": mean_value,
        "median": statistics.median(values),
        "maximum": max(values),
        "standard_deviation": standard_deviation,
        "range": max(values) - min(values),
        "coefficient_of_variation_percent": (
            None if mean_value == 0 else (standard_deviation / mean_value) * 100
        ),
    }


def calculate_secure_boot_benchmark_aggregate_statistics(
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate Phase 11.2 aggregate statistics over valid samples only."""

    valid_samples = [
        sample
        for sample in samples
        if sample.get("valid_for_statistics") is True
    ]
    failed_samples = [
        sample
        for sample in samples
        if sample.get("valid_for_statistics") is not True
    ]
    time_values = [
        sample["verification_time_ms"]
        for sample in valid_samples
        if sample.get("verification_time_ms") is not None
    ]
    cycle_values = [
        sample["verification_cycles"]
        for sample in valid_samples
        if sample.get("verification_cycles") is not None
    ]
    time_stats = _metric_statistics(time_values)
    cycle_stats = _metric_statistics(cycle_values)

    return {
        "status": "available" if samples else "unavailable",
        "sample_count": len(samples),
        "valid_sample_count": len(valid_samples),
        "failed_sample_count": len(failed_samples),
        "verification_time_ms": time_stats,
        "verification_cycles": cycle_stats,
        "headline_metrics": {
            "primary_verification_time_ms": time_stats["median"],
            "primary_verification_cycles": cycle_stats["median"],
            "primary_statistic": "median",
        },
        "derived_metrics": {
            "cycles_per_kb": None,
            "time_ms_per_kb": None,
        },
        "limitations": [
            "Aggregate statistics include only samples marked valid_for_statistics. Host-side SSH duration, UART capture duration, reset delay, and marker ordering are not used as verification timing evidence."
        ],
    }


def apply_repeated_run_samples_to_benchmark_model(
    benchmark: dict[str, Any],
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a benchmark model updated with repeated-run samples and aggregates.

    Repeated-run evidence is additive. Do not downgrade a benchmark model that
    already contains Phase 11.3 static build/resource metrics back to the Phase
    11.2 model phase when samples are attached.
    """

    updated = dict(benchmark)
    build_time_metrics = updated.get("build_time_metrics", {})
    static_metrics_available = (
        isinstance(build_time_metrics, dict)
        and build_time_metrics.get("status") == "available"
    )
    runtime_memory_metrics = updated.get("runtime_memory_metrics", {})
    runtime_memory_available = (
        isinstance(runtime_memory_metrics, dict)
        and runtime_memory_metrics.get("status") == "available"
    )
    updated["model_phase"] = (
        SECURE_BOOT_BENCHMARK_RUNTIME_MEMORY_MODEL_PHASE
        if runtime_memory_available
        else SECURE_BOOT_BENCHMARK_STATIC_METRICS_MODEL_PHASE
        if static_metrics_available
        else SECURE_BOOT_BENCHMARK_REPEATED_MODEL_PHASE
    )
    updated["repeated_run_samples"] = {
        "status": "completed" if samples else "not_configured",
        "samples": samples,
        "sample_schema": {
            "run_index": None,
            "timestamp": None,
            "verification_time_ms": None,
            "verification_cycles": None,
            "verification_cpu_hz": None,
            "verification_result_code": None,
            "verification_time_source": None,
            "verification_cycles_source": None,
            "uart_marker_detection_result": None,
            "sample_verdict": None,
            "valid_for_statistics": None,
            "referenced_artifact_identity": None,
            "runtime_memory_metrics": {
                "max_stack_used_bytes": None,
                "stack_metric_source": None,
                "heap_used_bytes": None,
                "heap_metric_source": None,
                "runtime_memory_limitations": None,
            },
        },
        "limitations": [
            "Each sample is based on explicit firmware/UART verification markers only; host-side SSH duration, UART capture duration, reset delay, and marker ordering are not used as timing evidence."
        ],
    }
    updated["aggregate_statistics"] = calculate_secure_boot_benchmark_aggregate_statistics(samples)
    stale_repeated_limitations = {
        "Repeated execution has not been configured for this run.",
        "Aggregate statistics require repeated-run samples; no repeated samples are available for this run.",
    }
    limitations = [
        limitation
        for limitation in list(updated.get("limitations", []))
        if not samples or limitation not in stale_repeated_limitations
    ]
    repeated_limitation = (
        "Phase 11.2 repeated-run support records one sample per secure-boot reset/capture and uses median values as primary headline metrics."
    )
    if samples and repeated_limitation not in limitations:
        limitations.append(repeated_limitation)
    updated["limitations"] = limitations
    return updated


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
