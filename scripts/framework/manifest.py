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
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from framework.run_evidence import (
    build_resolved_case_snapshot,
    build_derived_record,
    compact_final_manifest,
    discover_retained_artifacts,
    finalize_manifest as finalize_evidence_manifest,
    initialize_manifest_evidence,
    register_artifact as register_evidence_artifact_in_manifest,
    register_identity as register_evidence_identity_in_manifest,
    update_sut_outcome,
    validate_manifest_schema,
    verify_and_freeze_raw_artifacts,
    verify_retained_files,
    write_run_provenance_snapshot,
)

RUN_ID_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<sequence>\d{3})_(?P<experiment>[A-Za-z0-9_.-]+)$")
DEFAULT_RESULT_STATUS = "pending"
DEFAULT_TRANSPORT_MODE = "direct_uart"
DEFAULT_NETWORK_PROFILE = "none"
PROJECT_TIMEZONE = ZoneInfo("Australia/Melbourne")


SECURE_BOOT_BENCHMARK_SCHEMA_VERSION = 1
SECURE_BOOT_BENCHMARK_MODEL_PHASE = "phase_11_1_schema_only"
SECURE_BOOT_BENCHMARK_REPEATED_MODEL_PHASE = "phase_11_2_repeated_run_support"
SECURE_BOOT_BENCHMARK_STATIC_METRICS_MODEL_PHASE = "phase_11_3_static_build_resource_metrics"
SECURE_BOOT_BENCHMARK_RUNTIME_MEMORY_MODEL_PHASE = "phase_11_4_runtime_memory_metrics"
SECURE_BOOT_BENCHMARK_CLASSICAL_PROFILE_MODEL_PHASE = "phase_11_5a_classical_profile_model"
UNAVAILABLE_METRIC_SOURCE = "unavailable"

MQTT_TLS_RESULT_SCHEMA_VERSION = 1
MQTT_TLS_RESULT_MODEL_PHASE = "phase_m2_mqtt_tls_config_result_schema"
MQTT_FAKE_TRANSPORT_MODEL_PHASE = "phase_m3_fake_no_network_transport_harness"
MQTT_TLS_METRIC_NAMES = (
    "wifi_association",
    "ip_address",
    "tcp_connect",
    "tls_handshake",
    "mqtt_connect",
    "mqtt_publish",
    "mqtt_reconnect",
    "latency_ms",
    "throughput_bytes_per_second",
)
MQTT_TLS_EVIDENCE_LABELS = {
    "fake_no_network": "fake/no-network transport evidence",
    "host_side": "host-side evidence",
    "stm32_build_only": "STM32 build-only evidence",
    "stm32_runtime": "STM32 runtime evidence",
    "st67w61m1_backed": "future ST67W61M1-backed evidence",
    "stm32_st67_plaintext_e2e": "STM32/ST67W61M1 plaintext MQTT end-to-end evidence",
    "stm32_st67_classical_tls_e2e": "STM32/ST67W61M1 classical TLS MQTT end-to-end evidence",
    "stm32_st67_pqc_hybrid_tls_e2e": "STM32/ST67W61M1 hybrid P-256+ML-KEM-768 TLS 1.3 MQTT end-to-end evidence",
}


def _mqtt_unavailable_metric(reason: str, *, source: str = UNAVAILABLE_METRIC_SOURCE) -> dict[str, Any]:
    """Return an explicit unavailable MQTT/TLS metric record."""

    return {
        "status": "unavailable",
        "source": source,
        "reason": reason,
    }


def build_mqtt_tls_result_model(
    *,
    experiment_id: str,
    evidence_class: str,
    transport_backend: str,
    tls_mode: str,
    broker: dict[str, Any] | None = None,
    certificate_refs: dict[str, Any] | None = None,
    unavailable_metrics: dict[str, str] | None = None,
    available_metrics: dict[str, dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
    fake_transport_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Phase M2 MQTT/TLS result schema.

    The model is schema-first. It can record future MQTT/TLS evidence while
    preserving explicit unavailable records for metrics that do not yet have
    supporting firmware, host, broker, UART, or hardware evidence.
    """

    unavailable_reasons = dict(unavailable_metrics or {})
    available = dict(available_metrics or {})
    metric_records: dict[str, Any] = {}

    for metric_name in MQTT_TLS_METRIC_NAMES:
        if metric_name in available:
            metric_record = dict(available[metric_name])
            metric_record.setdefault("status", "available")
            if not metric_record.get("source"):
                raise ValueError(f"available MQTT/TLS metric '{metric_name}' must include a source")
            metric_records[metric_name] = metric_record
            continue

        reason = unavailable_reasons.get(
            metric_name,
            "No explicit MQTT/TLS evidence was available for this metric in Phase M2.",
        )
        metric_records[metric_name] = _mqtt_unavailable_metric(reason)

    unavailable_count = sum(
        1 for metric in metric_records.values() if metric.get("status") == "unavailable"
    )
    available_count = sum(
        1 for metric in metric_records.values() if metric.get("status") == "available"
    )

    result = {
        "schema_version": MQTT_TLS_RESULT_SCHEMA_VERSION,
        "model_phase": MQTT_TLS_RESULT_MODEL_PHASE,
        "experiment_id": experiment_id,
        "evidence_class": evidence_class,
        "evidence_label": MQTT_TLS_EVIDENCE_LABELS.get(evidence_class, evidence_class),
        "transport_backend": transport_backend,
        "tls": {
            "mode": tls_mode,
            "certificate_refs": dict(certificate_refs or {}),
        },
        "broker": dict(broker or {}),
        "metrics": metric_records,
        "metric_summary": {
            "available_count": available_count,
            "unavailable_count": unavailable_count,
            "total_count": len(metric_records),
        },
        "limitations": list(limitations or []),
        "evidence_boundaries": {
            "claims_runtime_success": available_count > 0,
            "claims_network_success": any(
                metric_records[name].get("status") == "available"
                for name in ("wifi_association", "ip_address", "tcp_connect")
            ),
            "claims_tls_success": metric_records["tls_handshake"].get("status") == "available",
            "claims_mqtt_success": any(
                metric_records[name].get("status") == "available"
                for name in ("mqtt_connect", "mqtt_publish", "mqtt_reconnect")
            ),
            "note": (
                "MQTT/TLS runtime success claims require explicit real evidence from logs, manifests, "
                "UART output, broker output, or equivalent records. Fake/no-network transport evidence "
                "is simulated control-flow evidence only."
            ),
        },
    }

    if fake_transport_evidence is not None:
        fake_evidence = dict(fake_transport_evidence)
        fake_evidence.setdefault("model_phase", MQTT_FAKE_TRANSPORT_MODEL_PHASE)
        fake_evidence.setdefault("simulated", True)
        result["fake_transport"] = fake_evidence

    return result


def build_mqtt_fake_transport_manifest_evidence(fake_transport_result: dict[str, Any]) -> dict[str, Any]:
    """Return a manifest-safe Phase M3 fake/no-network transport evidence block."""

    evidence = dict(fake_transport_result)
    evidence["simulated"] = True
    evidence["evidence_class"] = "fake_no_network"
    evidence["evidence_label"] = MQTT_TLS_EVIDENCE_LABELS["fake_no_network"]
    evidence["transport_backend"] = "fake_no_network"
    evidence.setdefault("model_phase", MQTT_FAKE_TRANSPORT_MODEL_PHASE)
    evidence["evidence_boundaries"] = {
        "claims_broker_success": False,
        "claims_network_success": False,
        "claims_tls_success": False,
        "claims_mqtt_runtime_success": False,
        "claims_stm32_runtime_success": False,
        "note": (
            "Phase M3 fake/no-network transport evidence is deterministic simulated "
            "control-flow evidence only. It is not broker, TLS, network, STM32 runtime, "
            "gateway, Wi-Fi, UART, or hardware evidence."
        ),
    }
    return evidence


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
    derived_verification_time_ms: int | None = None,
    verification_cycles: int | None = None,
    bootloader_hclk_hz: int | None = None,
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
    classical_profile_metadata: dict[str, Any] | None = None,
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

    runtime_status = "available" if derived_verification_time_ms is not None else "unavailable"
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

    if classical_profile_metadata:
        model_phase = SECURE_BOOT_BENCHMARK_CLASSICAL_PROFILE_MODEL_PHASE
    elif runtime_memory_available:
        model_phase = SECURE_BOOT_BENCHMARK_RUNTIME_MEMORY_MODEL_PHASE
    elif static_metrics_available:
        model_phase = SECURE_BOOT_BENCHMARK_STATIC_METRICS_MODEL_PHASE
    else:
        model_phase = SECURE_BOOT_BENCHMARK_MODEL_PHASE

    profile_metadata = dict(classical_profile_metadata or {})
    if not profile_metadata:
        profile_metadata = {
            "status": "unavailable",
            "unavailable": _unavailable_reason(
                "Phase 11.5a classical signing profile metadata was not configured for this run."
            ),
            "minimum_comparison_scope": {
                "status": "unavailable",
                "required_algorithms": ["ED25519", "ECC256", "RSA2048"],
            },
        }

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
        "classical_profile_metadata": profile_metadata,
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
            "derived_verification_time_ms": derived_verification_time_ms,
            "verification_cycles": verification_cycles,
            "bootloader_hclk_hz": bootloader_hclk_hz,
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
                "derived_verification_time_ms": None,
                "verification_cycles": None,
                "bootloader_hclk_hz": None,
                "verification_result_code": None,
                "verification_time_source": None,
                "verification_cycles_source": None,
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
            "derived_verification_time_ms": {
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
            + ([] if classical_profile_metadata else ["Phase 11.5a classical signing profile metadata was not configured for this run."])
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
    derived_verification_time_ms: float | int | None,
    verification_cycles: int | None,
    bootloader_hclk_hz: int | None,
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
        "derived_verification_time_ms": derived_verification_time_ms,
        "verification_cycles": verification_cycles,
        "bootloader_hclk_hz": bootloader_hclk_hz,
        "verification_result_code": verification_result_code,
        "verification_time_source": verification_time_source,
        "verification_cycles_source": verification_cycles_source,
        "uart_marker_detection_result": uart_marker_detection_result,
        "sample_verdict": sample_verdict,
        "valid_for_statistics": sample_verdict == "passed"
        and derived_verification_time_ms is not None
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
        sample["derived_verification_time_ms"]
        for sample in valid_samples
        if sample.get("derived_verification_time_ms") is not None
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
        "derived_verification_time_ms": time_stats,
        "verification_cycles": cycle_stats,
        "headline_metrics": {
            "primary_derived_verification_time_ms": time_stats["median"],
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
            "derived_verification_time_ms": None,
            "verification_cycles": None,
            "bootloader_hclk_hz": None,
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
    """Return a project-local Australia/Melbourne timestamp.

    Framework commands normally run inside a Docker container whose local
    timezone may be UTC. Run IDs and manifest timestamps must nevertheless use
    the experiment project's local AEST/AEDT calendar date consistently.
    """

    if timestamp is None:
        return datetime.now(PROJECT_TIMEZONE)

    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=PROJECT_TIMEZONE)

    return timestamp.astimezone(PROJECT_TIMEZONE)


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
    operation: str | None = None,
) -> dict[str, Any]:
    """Build the initial manifest dictionary for an experiment bundle."""

    experiment = bundle["experiment"]
    board = bundle["board"]
    host = bundle["host"]
    boot = bundle.get("boot", {})

    firmware = experiment.get("firmware", {})
    transport = experiment.get("transport", {})
    network = experiment.get("network", {})

    manifest = {
        "run_id": run_id,
        "timestamp": format_manifest_timestamp(timestamp),
        "experiment": experiment["id"],
        "board": board["id"],
        "gateway": host["id"],
        "boot_mode": boot.get("mode", firmware.get("mode", "unknown")),
        "transport_mode": transport.get("mode", DEFAULT_TRANSPORT_MODE),
        "network_profile": network.get("profile", DEFAULT_NETWORK_PROFILE),
        "result": result,
        "run": {
            "id": run_id,
            "created_at": format_manifest_timestamp(timestamp),
            "state": "created",
        },
    }
    initialize_manifest_evidence(manifest, bundle, operation=operation)

    resolved_configuration = experiment.get("resolved_configuration")
    if isinstance(resolved_configuration, dict):
        # Keep only the compact public identity in the root manifest. The complete
        # non-secret resolved state is retained as resolved-case.json.
        manifest["resolved_configuration"] = {
            key: resolved_configuration.get(key)
            for key in (
                "schema_version", "resolver_version", "configuration_identity",
                "firmware_identity", "selected_profiles", "choices", "profile_hashes",
                "secret_references",
            )
            if key in resolved_configuration
        }
    instruments = experiment.get("instruments")
    if isinstance(instruments, dict) and instruments:
        manifest["measurement_instruments"] = instruments
    services = experiment.get("services")
    if isinstance(services, dict):
        manifest["runtime_services"] = services

    # Scientific/result interpretation is intentionally excluded from the run
    # manifest. MQTT/TLS timing, memory and other measurement values remain in
    # raw UART/MQTT/broker artefacts for later ingestion and analysis.

    return manifest


def write_manifest(path: Path | str, manifest: dict[str, Any]) -> None:
    """Write a manifest JSON file with stable formatting."""

    manifest_path = Path(path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path | str) -> dict[str, Any]:
    """Read a manifest JSON file without silently upgrading legacy evidence."""

    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if isinstance(manifest, dict):
        compatible, reason = validate_manifest_schema(manifest)
        if not compatible:
            manifest["compatibility"] = {
                "legacy_manifest": True,
                "accepted_under_current_contract": False,
                "reason": reason,
            }
    return manifest


def update_manifest(path: Path | str, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge top-level stage updates and keep the compact evidence index in sync."""

    manifest_path = Path(path)
    manifest = read_manifest(manifest_path)
    if (manifest.get("final_index") or {}).get("status") == "finalized":
        raise ValueError("finalized run-evidence manifests are immutable")
    run_update = updates.get("run") if isinstance(updates.get("run"), dict) else None
    manifest.update({key: value for key, value in updates.items() if key != "run"})
    if run_update is not None:
        current_run = dict(manifest.get("run") or {})
        current_run.update(run_update)
        manifest["run"] = current_run
    if isinstance(manifest.get("run"), dict):
        manifest["run"]["state"] = "running"
    failure_stage = updates.get("failure_stage")
    summary_update = None
    if failure_stage is None and run_update is not None:
        failure_stage = run_update.get("failure_stage")
    if failure_stage is None:
        # Some orchestration commands historically recorded their terminal summary
        # in a transient stage block (for example ``build_flash``). Preserve only
        # the stable lifecycle facts needed by the compact final manifest.
        for value in updates.values():
            if not isinstance(value, dict):
                continue
            if value.get("failure_stage") is not None:
                failure_stage = value.get("failure_stage")
                summary_update = value
                break
    if summary_update is not None:
        current_run = dict(manifest.get("run") or {})
        current_run["failure_stage"] = failure_stage
        if summary_update.get("return_code") is not None:
            current_run["return_code"] = summary_update.get("return_code")
        manifest["run"] = current_run
    update_sut_outcome(manifest, updates.get("result"), failure_stage)
    _sync_legacy_evidence(manifest_path, manifest, updates)
    write_manifest(manifest_path, manifest)
    return manifest



def _sync_legacy_evidence(manifest_path: Path, manifest: dict[str, Any], updates: dict[str, Any]) -> None:
    """Index existing stage artefacts without duplicating their verbose payloads."""

    result_dir = manifest_path.parent

    def artifact(role: str, relative: str | None, stage: str, tool: str, result: str = "produced") -> None:
        if relative:
            register_evidence_artifact_in_manifest(
                manifest, result_dir=result_dir, role=role, path=relative,
                stage=stage, tool=tool, acquisition_result=result,
            )

    build = updates.get("build")
    firmware = updates.get("firmware")
    if isinstance(build, dict):
        artifact("build_log", build.get("log"), "build", "cmake/ninja")
    if isinstance(firmware, dict):
        result_artifacts = firmware.get("result_artifacts")
        if isinstance(result_artifacts, dict):
            for artifact_type, role in (("elf", "application_elf"), ("hex", "application_hex"), ("bin", "application_binary")):
                record = result_artifacts.get(artifact_type)
                if isinstance(record, dict) and record.get("copied"):
                    artifact(role, record.get("path") or record.get("artifact_path"), "build", "cmake/ninja")
        elif firmware.get("result_artifact") or firmware.get("result_artifact_path"):
            retained_artifact = firmware.get("result_artifact_path") or firmware.get("result_artifact")
            explicit_role = firmware.get("evidence_role")
            if isinstance(explicit_role, str) and explicit_role.strip():
                retained_role = explicit_role.strip()
            else:
                suffix = Path(str(retained_artifact)).suffix.lower()
                retained_role = {
                    ".elf": "application_elf",
                    ".hex": "application_hex",
                    ".bin": "application_binary",
                }.get(suffix, "firmware_image")
            artifact(retained_role, str(retained_artifact), "preparation_reuse", "framework.build_records", "reused")

    flash = updates.get("flash")
    if isinstance(flash, dict):
        artifact("flash_log", flash.get("log") or "flash.log", "flash", "STM32CubeProgrammer")
        register_evidence_identity_in_manifest(
            manifest, role="deployment_provenance", sha256=flash.get("firmware_sha256"),
            stage="flash", tool="STM32CubeProgrammer", acquisition_result=str(flash.get("provenance_status") or "recorded"),
            path=None, source_class="deployment",
        )

    uart = updates.get("uart")
    if isinstance(uart, dict) and not uart.get("skipped"):
        artifact("diagnostic_uart", uart.get("log"), "uart_capture", "gateway_uart")

    capture = updates.get("gateway_packet_capture")
    if isinstance(capture, dict):
        artifact("packet_capture_log", capture.get("log"), "packet_capture", "tcpdump")
        if capture.get("status") == "collected":
            artifact("packet_capture", capture.get("artifact"), "packet_capture", "tcpdump")
        elif capture.get("status") in {"failed", "start_failed"}:
            from framework.run_evidence import mark_evidence
            mark_evidence(manifest, role="packet_capture", status="unavailable", reason=str(capture.get("failure_reason") or capture.get("status")), stage="packet_capture", tool="tcpdump")

    broker = updates.get("mqtt_broker")
    if isinstance(broker, dict):
        log_name = broker.get("log") or broker.get("broker_log")
        if isinstance(log_name, str):
            artifact("experiment_broker_log", log_name, "broker_collection", "mosquitto")
        artifact("reporting_broker_log", broker.get("reporting_log"), "broker_collection", "mosquitto")
        artifact("broker_stop_log", broker.get("stop_log"), "broker_cleanup", "mosquitto")
        keylog = broker.get("tls_keylog")
        if isinstance(keylog, dict):
            artifact("tls_key_log_collection", keylog.get("collection_log"), "broker_collection", "mosquitto")
            if keylog.get("status") == "collected":
                artifact("tls_key_log", keylog.get("artifact"), "broker_collection", "mosquitto")

    mqtt_e2e = updates.get("mqtt_e2e")
    if isinstance(mqtt_e2e, dict):
        artifact("mqtt_publisher_log", mqtt_e2e.get("publisher_log"), "mqtt_observer", "mosquitto_pub")
        artifact("mqtt_subscriber_log", mqtt_e2e.get("subscriber_log"), "mqtt_observer", "mosquitto_sub")
        artifact("mqtt_subscriber_raw_log", mqtt_e2e.get("subscriber_raw_log"), "mqtt_observer", "mosquitto_sub")
        observer_path = mqtt_e2e.get("broker_message_evidence_log")
        if isinstance(observer_path, str):
            artifact("observer_evidence", observer_path, "mqtt_observer", "framework.mqtt_e2e")

    degradation = updates.get("network_degradation")
    if isinstance(degradation, dict) and degradation.get("enabled"):
        # The degradation log is appended during cleanup so it records both the
        # applied and restored states. Freeze/hash it only once that lifecycle is
        # terminal; raw evidence roles are immutable once collected.
        terminal_statuses = {
            "removed",
            "cleanup_failed",
            "apply_failed",
            "invalid",
            "campaign_retained_snapshot",
        }
        if degradation.get("status") in terminal_statuses:
            log_name = degradation.get("log")
            if isinstance(log_name, str):
                artifact("network_condition_record", log_name, "network_condition", "tc/netem")

    for stage_key, role, tool_name in (
        ("wolfboot_build", "wolfboot_build_log", "wolfBoot build"),
        ("application_signing", "application_signing_log", "wolfBoot sign"),
    ):
        stage_record = updates.get(stage_key)
        if isinstance(stage_record, dict):
            log_value = stage_record.get("log")
            if isinstance(log_value, str):
                try:
                    candidate = Path(log_value)
                    if candidate.is_absolute():
                        candidate = candidate.resolve().relative_to(result_dir.resolve())
                    artifact(role, candidate.as_posix(), stage_key, tool_name)
                except ValueError:
                    pass

    preparation_reference = updates.get("profile_preparation_reference")
    if isinstance(preparation_reference, dict) and preparation_reference.get("manifest"):
        manifest["preparation"] = {
            "mode": "reused",
            "manifest": str(preparation_reference.get("manifest")),
            "run_id": preparation_reference.get("run_id"),
            "firmware_sha256": preparation_reference.get("firmware_sha256"),
            "verified": preparation_reference.get("result") is not None,
        }
        register_evidence_identity_in_manifest(
            manifest, role="deployment_provenance", sha256=preparation_reference.get("firmware_sha256"),
            stage="preparation_reuse", tool="framework.runtime_only", acquisition_result="reused",
            path=None, source_class="deployment",
        )
        reused_artifact_identities = preparation_reference.get("reused_artifact_identities")
        if isinstance(reused_artifact_identities, dict):
            for role in ("wolfboot_image", "signed_application"):
                digest = reused_artifact_identities.get(role)
                if isinstance(digest, str) and digest.strip():
                    register_evidence_identity_in_manifest(
                        manifest, role=role, sha256=digest.strip(),
                        stage="preparation_reuse", tool="framework.runtime_only", acquisition_result="reused",
                        path=None, source_class="secure_boot",
                    )

    build_reference = updates.get("build_reference")
    if isinstance(build_reference, dict) and build_reference.get("record_manifest"):
        manifest["preparation"] = {
            "mode": "reused",
            "manifest": str(build_reference.get("record_manifest")),
            "firmware_sha256": build_reference.get("artifact_sha256"),
            "build_number": build_reference.get("build_number"),
            "verified": build_reference.get("status") in {None, "verified", "verified_build_match", "verified_build_record"},
        }

    secure = updates.get("secure_boot_evidence")
    if isinstance(secure, dict):
        build_evidence = secure.get("build_evidence") if isinstance(secure.get("build_evidence"), dict) else {}
        signing_evidence = secure.get("signing_evidence") if isinstance(secure.get("signing_evidence"), dict) else {}
        flash_evidence = secure.get("flash_evidence") if isinstance(secure.get("flash_evidence"), dict) else {}
        if isinstance(flash_evidence.get("log"), str):
            artifact("flash_log", flash_evidence.get("log"), "secure_boot_flash", "STM32CubeProgrammer")
        register_evidence_identity_in_manifest(
            manifest, role="deployment_provenance", sha256=signing_evidence.get("signed_application_sha256"),
            stage="secure_boot_flash", tool="framework.secure_boot_flash", acquisition_result="recorded",
            path=None, source_class="deployment",
        )

        def secure_artifact_or_identity(role: str, raw_path: Any, recorded_sha256: Any, stage: str, tool: str) -> None:
            if isinstance(raw_path, str):
                candidate = Path(raw_path)
                candidates = [candidate] if candidate.is_absolute() else [candidate, result_dir / candidate]
                for possible in candidates:
                    try:
                        resolved = possible.resolve()
                        relative = resolved.relative_to(result_dir.resolve())
                        if resolved.is_file():
                            register_evidence_artifact_in_manifest(
                                manifest, result_dir=result_dir, role=role, path=relative,
                                stage=stage, tool=tool, acquisition_result="produced",
                            )
                            return
                    except (OSError, ValueError):
                        continue
            register_evidence_identity_in_manifest(
                manifest, role=role, sha256=recorded_sha256,
                stage=stage, tool=tool, acquisition_result="produced",
                path=None, source_class="secure_boot",
            )

        secure_artifact_or_identity(
            "wolfboot_image", build_evidence.get("wolfboot_artifact_path"),
            build_evidence.get("wolfboot_sha256"), "secure_boot_build", "wolfBoot",
        )
        secure_artifact_or_identity(
            "signed_application", signing_evidence.get("signed_application_artifact_path"),
            signing_evidence.get("signed_application_sha256"), "application_signing", "wolfBoot sign",
        )
        # secure_boot_evidence is mutable until the run is finalized. Flash, UART,
        # negative-test verdict, and recovery stages may each update this payload.
        # Index the terminal snapshot in finalize_run_evidence(), not here: once
        # captured, raw-evidence identities must never be overwritten.



def _register_final_secure_boot_record(manifest: dict[str, Any]) -> None:
    """Freeze only the terminal secure-boot stage record as immutable evidence."""

    secure = manifest.get("secure_boot_evidence")
    if not isinstance(secure, dict):
        return
    from framework.run_evidence import canonical_sha256

    register_evidence_identity_in_manifest(
        manifest, role="secure_boot_record", sha256=canonical_sha256(secure),
        stage="secure_boot_flash", tool="framework.secure_boot_flash",
        acquisition_result="recorded", source_class="secure_boot",
    )


def register_derived_output(
    manifest_path: Path | str, *, role: str, path: Path | str, tool: str, version: str,
    input_sha256: list[str], parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write offline-analysis lineage without mutating the finalized run manifest.

    Derived outputs belong to the analysis namespace. The immutable run manifest
    remains a capture/provenance record and is never reopened to insert parsed
    metrics.
    """

    manifest_path_obj = Path(manifest_path)
    manifest = read_manifest(manifest_path_obj)
    compatible, reason = validate_manifest_schema(manifest)
    if not compatible:
        raise ValueError(reason or "legacy manifest cannot be used for current derived lineage")
    record = build_derived_record(
        result_dir=manifest_path_obj.parent,
        role=role,
        path=path,
        tool=tool,
        version=version,
        input_sha256=input_sha256,
        parameters=parameters,
    )
    analysis_dir = manifest_path_obj.parent / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    safe_role = re.sub(r"[^A-Za-z0-9_.-]+", "_", role).strip("._") or "derived"
    lineage_path = analysis_dir / f"{safe_role}.lineage.json"
    lineage_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {**record, "lineage_path": lineage_path.relative_to(manifest_path_obj.parent).as_posix()}

def finalize_run_evidence(path: Path | str, *, timestamp: datetime | None = None) -> dict[str, Any]:
    """Evaluate the class contract and seal the immutable raw-evidence index."""

    manifest_path = Path(path)
    manifest = read_manifest(manifest_path)
    compatible, reason = validate_manifest_schema(manifest)
    if not compatible:
        raise ValueError(reason or "legacy manifest cannot satisfy the current evidence contract")
    # Secure-boot evidence is updated repeatedly during flash and UART processing.
    # Freeze it once, after the terminal verdict, before compacting the manifest.
    _register_final_secure_boot_record(manifest)
    # Snapshot the reproducibility/deployment metadata before discarding the verbose
    # runtime manifest payloads. The snapshot is itself hashed as required evidence.
    write_run_provenance_snapshot(manifest, result_dir=manifest_path.parent)
    discover_retained_artifacts(manifest, result_dir=manifest_path.parent)
    material_inventory = manifest_path.parent / "material-inventory.json"
    if material_inventory.is_file():
        register_evidence_artifact_in_manifest(
            manifest, result_dir=manifest_path.parent, role="cryptographic_material_inventory",
            path="material-inventory.json", stage="provisioning", tool="framework.artifacts",
            acquisition_result="produced",
        )
    verify_and_freeze_raw_artifacts(manifest, result_dir=manifest_path.parent)
    verify_retained_files(manifest, result_dir=manifest_path.parent)
    # Strip transient stage/metric payloads before sealing so the final-index digest
    # is mechanically reproducible from the persisted compact manifest itself.
    compact_final_manifest(manifest)
    finalize_evidence_manifest(manifest, finalized_at=format_manifest_timestamp(timestamp))
    if isinstance(manifest.get("run"), dict):
        manifest["run"]["state"] = "finalized"
    write_manifest(manifest_path, manifest)
    return manifest


def create_result_folder(
    bundle: dict[str, dict[str, Any]],
    results_root: Path | str = "results",
    timestamp: datetime | None = None,
    result: str = DEFAULT_RESULT_STATUS,
    operation: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Create results/<run_id>/ with manifest.json and notes.md."""

    current_timestamp = _coerce_timestamp(timestamp)
    root = Path(results_root)
    run_id = next_run_id(bundle["experiment"]["id"], root, current_timestamp)
    result_dir = root / run_id

    result_dir.mkdir(parents=True, exist_ok=False)

    manifest = build_manifest(bundle, run_id, current_timestamp, result=result, operation=operation)
    snapshot_path = result_dir / "resolved-case.json"
    snapshot = build_resolved_case_snapshot(bundle)
    snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    register_evidence_artifact_in_manifest(
        manifest, result_dir=result_dir, role="resolved_case_snapshot", path=snapshot_path,
        stage="configuration_resolution", tool="framework.config_resolver", acquisition_result="snapshotted",
    )
    manifest["configuration"] = {
        "snapshot": snapshot_path.name,
        "sha256": next(item["sha256"] for item in manifest["artifacts"] if item["role"] == "resolved_case_snapshot"),
    }
    write_manifest(result_dir / "manifest.json", manifest)
    (result_dir / "notes.md").write_text(
        f"# Notes for {run_id}\n\n"
        "Add manual observations for this experiment run here.\n",
        encoding="utf-8",
    )

    return result_dir, manifest
