"""Read current deferred STM32 records and derive A1 timings, without capture writes.

Only the outer handshake is interpreted from TLS instrumentation. Phase/primitive
coverage and energy validity are deliberately not timing-dataset prerequisites.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.energy_evidence import chunk_bytes, envelope
from framework.result_collector import _parse_raw_stream
from framework.tls_instrumentation import _parse_fields
from framework.timing_dataset_schema import METRIC_VERSION, TIMING_COLUMNS

U64_MAX = (1 << 64) - 1
READY_DEFINITION = "tcp_connect_start_to_first_mqtt_connack_plaintext_byte"
RM2_NAMES = ("mqtt_readiness", "rtfb", "rtlb", "ttfb", "ttlb", "req_tfb", "req_tlb")


@dataclass
class Epoch:
    index: int
    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    logical_sha256: str | None = None
    complete_line: int | None = None


def uint(value: Any) -> int:
    """Read decimal integer tokens without float/bool coercion or sentinel guesses."""
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        result = int(value)
    else:
        raise ValueError("missing_or_invalid_integer")
    if not 0 <= result <= U64_MAX:
        raise ValueError("integer_out_of_range")
    return result


def _fields(text: str) -> tuple[str, dict[str, str]]:
    parts = text.strip().split()
    if not parts:
        return "", {}
    keys = [part.split("=", 1)[0] for part in parts[1:] if "=" in part]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_marker_field")
    return parts[0], _parse_fields(" ".join(parts[1:]))


def decode_epochs(path: Path, run_id: str) -> tuple[list[Epoch], list[str]]:
    """Reuse collector validation; independently retain completion-bounded identities.

    The small preflight bounds the collector's sequence-range allocation and enforces
    the versioned envelope. Fixed-topic energy is skipped *before* payload decoding.
    Its acquisition validity cannot invalidate an otherwise intact STM32 stream.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    epochs: list[Epoch] = []
    chunks: dict[int, bytes] = {}
    errors: list[str] = []
    global_errors: list[str] = []
    safe_for_collector = True

    def finish(complete_line: int | None) -> None:
        nonlocal chunks, errors
        logical = b"".join(chunks[key] for key in sorted(chunks))
        epoch = Epoch(len(epochs), errors=list(errors), complete_line=complete_line,
                      logical_sha256=hashlib.sha256(logical).hexdigest())
        if complete_line is None:
            epoch.errors.append("completion_missing")
        try:
            for number, line in enumerate(logical.decode("utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                obj = json.loads(line)
                if (not isinstance(obj, dict) or obj.get("schema_version") != 1
                        or type(obj.get("schema_version")) is not int
                        or obj.get("source") != "stm32"
                        or not isinstance(obj.get("context"), str)
                        or not isinstance(obj.get("text"), str)
                        or type(obj.get("iteration")) is not int):
                    raise ValueError("invalid_logical_record")
                uint(obj["iteration"])
                for text_line, text in enumerate(obj["text"].splitlines(), 1):
                    marker, fields = _fields(text)
                    expected_context = {
                        "PQC_RM2_TIMEBASE": "rm2_timebase", "PQC_RM2_CHECKPOINTS": "rm2_checkpoints",
                        "PQC_RM2_METRICS": "rm2_metrics", "PQC_RM2_COMPLETE": "rm2_complete",
                        "PQC_TLS_HANDSHAKE_TIMING": "tls", "PQC_TLS_EVENT_BUFFER": "tls",
                        "PQC_TLS_EVENT": "tls", "PQC_TLS_REPEAT_ITERATION": "tls_handshake_repeat",
                    }.get(marker)
                    if expected_context and obj["context"] != expected_context:
                        raise ValueError("logical_context_mismatch")
                    epoch.records.append({"marker": marker, "fields": fields,
                        "iteration": obj["iteration"], "context": obj["context"],
                        "ref": {"epoch": epoch.index, "record": number,
                                "text_line": text_line, "context": obj["context"]}})
        except (ValueError, TypeError, UnicodeError):
            epoch.errors.append("invalid_logical_record")
        epochs.append(epoch)
        chunks, errors = {}, []

    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            outer = json.loads(line)
            topic = outer.get("topic") if isinstance(outer, dict) else None
            if isinstance(topic, str) and topic.startswith("pqc/instrument/"):
                continue
            topic, obj = envelope(line)
            if (obj.get("schema_version") != 1 or type(obj.get("schema_version")) is not int
                    or obj.get("run_id") != run_id or obj.get("source") != "stm32"
                    or topic not in (f"pqc/result/stm32/{run_id}/chunk", f"pqc/result/stm32/{run_id}/complete")):
                raise ValueError("reporting_identity_or_schema_mismatch")
            kind = obj.get("type")
            if kind == "chunk" and topic.endswith("/chunk"):
                sequence = uint(obj.get("sequence"))
                if type(obj.get("sequence")) is not int or sequence >= len(lines):
                    raise ValueError("invalid_chunk_sequence")
                if sequence in chunks:
                    errors.append("duplicate_chunk_sequence")
                else:
                    chunks[sequence] = chunk_bytes(obj)
            elif kind == "complete" and topic.endswith("/complete"):
                # The existing validator checks the declared sizes and digest below.
                for key in ("chunk_count", "record_count", "logical_bytes", "dropped_record_count"):
                    uint(obj.get(key))
                    if type(obj.get(key)) is not int:
                        raise ValueError("invalid_completion_integer")
                if obj["chunk_count"] > len(lines):
                    raise ValueError("invalid_chunk_count")
                if (not isinstance(obj.get("logical_sha256"), str)
                        or not re.fullmatch(r"[0-9a-f]{64}", obj["logical_sha256"])
                        or type(obj.get("overflowed")) is not bool):
                    raise ValueError("invalid_completion_metadata")
                if obj["overflowed"] or obj["dropped_record_count"]:
                    errors.append("result_buffer_truncated")
                if sorted(chunks) != list(range(obj["chunk_count"])):
                    errors.append("chunk_sequence_mismatch")
                finish(number)
            else:
                raise ValueError("unsupported_reporting_record")
        except (ValueError, TypeError, KeyError, UnicodeError):
            safe_for_collector = False
            global_errors.append(f"invalid_stm32_envelope_at_line_{number}")
    if chunks or errors:
        finish(None)
    if safe_for_collector:
        try:
            validation = _parse_raw_stream(path, run_id)
            streams = validation.source_results.get("stm32", {}).get("streams", [])
            for epoch in epochs:
                if epoch.index >= len(streams) or not streams[epoch.index]["passed"]:
                    epoch.errors.append("collector_transport_integrity_failed")
            if not streams:
                global_errors.append("stm32_source_missing")
        except (ValueError, TypeError, KeyError, OSError):
            global_errors.append("collector_validation_failed")
    if not epochs:
        global_errors.append("stm32_source_missing")
    return epochs, sorted(set(global_errors))


def blank_metric(metric: str, reason: str, *, epoch: Epoch | None = None,
                 iteration: int | None = None, repeated: bool = False) -> dict[str, Any]:
    row = dict.fromkeys(TIMING_COLUMNS)
    row.update(metric=metric, unit="us", metric_version=METRIC_VERSION,
               validity="unavailable", reason=reason, operation_outcome="unknown",
               scope="intra_run_iteration" if repeated else "framework_run",
               epoch_index=epoch.index if epoch else None, iteration_id=iteration,
               logical_sha256=epoch.logical_sha256 if epoch else None,
               source_records=[], clock_provenance={}, comparison_inclusion="not_assessed")
    return row


def _one(records: list[dict], marker: str) -> dict:
    found = [record for record in records if record["marker"] == marker]
    if not found:
        raise ValueError("missing_" + marker.lower())
    if len(found) != 1:
        raise ValueError("ambiguous_" + marker.lower())
    return found[0]


def _use(row: dict, record: dict) -> dict:
    if record["ref"] not in row["source_records"]:
        row["source_records"].append(record["ref"])
    return record["fields"]


def _version(fields: dict, version: str) -> None:
    if fields.get("schema") != version:
        raise ValueError("unsupported_marker_schema")


def _duration(row: dict, start: int, end: int, reported: Any) -> None:
    row.update(start_us=start, end_us=end)
    if end < start:
        raise ValueError("invalid_boundary_order")
    result = end - start
    if uint(reported) != result:
        raise ValueError("reported_duration_mismatch")
    row.update(value_us=result, validity="valid", reason=None)


def _clock(row: dict, records: list[dict]) -> dict:
    f = _use(row, _one(records, "PQC_RM2_TIMEBASE"))
    _version(f, "3")
    row["clock_provenance"] = dict(f)
    row["clock_source"] = f.get("source")
    row["timestamp_origin"] = "application_timebase_start"
    hz = uint(f.get("counter_hz"))
    if (f.get("source") != "TIM2" or hz != 1_000_000
            or uint(f.get("counter_bits")) != 32
            or f.get("wrap_handling") != "update_irq_64bit_extension"
            or uint(f.get("timer_input_clock_hz")) != (uint(f.get("prescaler")) + 1) * hz):
        raise ValueError("invalid_clock_provenance")
    row["counter_hz"] = hz
    return f


def _rm2(metric: str, records: list[dict], epoch: Epoch, iteration: int,
         snapshot: dict) -> dict:
    row = blank_metric(metric, "missing_evidence", epoch=epoch, iteration=iteration)
    try:
        clock = _clock(row, records)
        checkpoints = _use(row, _one(records, "PQC_RM2_CHECKPOINTS"))
        _version(checkpoints, "3")
        tcp = uint(checkpoints.get("tcp_connect_start_us"))
        if metric == "mqtt_readiness":
            row.update(start_boundary="tcp_connect_start_us", end_boundary="mqtt_readiness_checkpoint_us")
            if (checkpoints.get("mqtt_readiness_valid") != "1"
                    or checkpoints.get("mqtt_readiness_definition") != READY_DEFINITION):
                raise ValueError("mqtt_readiness_invalid")
            _duration(row, tcp, uint(checkpoints.get("mqtt_readiness_checkpoint_us")),
                      checkpoints.get("mqtt_readiness_us"))
            row["operation_outcome"] = "checkpoint_observed"
            return row
        values = _use(row, _one(records, "PQC_RM2_METRICS"))
        complete = _use(row, _one(records, "PQC_RM2_COMPLETE"))
        _version(values, "3")
        _version(complete, "3")
        if values.get("metric_contract") != "ready_metrics_2_canonical_v3":
            raise ValueError("unsupported_metric_contract")
        if (values.get("complete_valid") != "1" or complete.get("status") != "success"
                or complete.get("record_count") != "4"):
            raise ValueError("application_transfer_incomplete")
        payload, received = uint(values.get("payload_bytes")), uint(values.get("received_bytes"))
        chunk = uint(values.get("chunk_bytes"))
        if not payload or received != payload or not 0 < chunk <= 400:
            raise ValueError("application_payload_invalid")
        transfer = snapshot.get("effective_non_secret_parameters", {}).get("mqtt", {}).get("transfer", {})
        for key, value in (("payload_bytes", payload), ("chunk_bytes", chunk)):
            if key in transfer and uint(transfer[key]) != value:
                raise ValueError("configured_payload_mismatch")
        request = uint(checkpoints.get("application_request_us"))
        first = uint(checkpoints.get("application_first_byte_us"))
        last = uint(checkpoints.get("application_last_byte_us"))
        if not tcp <= request <= first <= last:
            raise ValueError("invalid_boundary_order")
        if uint(complete.get("measurement_complete_us")) != last:
            raise ValueError("completion_boundary_mismatch")
        if uint(values.get("application_transfer_us")) != last - first:
            raise ValueError("transfer_duration_mismatch")
        boundary = "application_first_byte_us" if metric in ("rtfb", "ttfb", "req_tfb") else "application_last_byte_us"
        end = first if boundary == "application_first_byte_us" else last
        row["end_boundary"] = boundary
        if metric in ("rtfb", "rtlb"):
            row["start_boundary"] = "operational_wolfboot_entry"
            row["timestamp_origin"] = "operational_wolfboot_entry"
            if (clock.get("reset_origin_valid") != "1" or checkpoints.get("reset_origin_valid") != "1"
                    or values.get("reset_metrics_valid") != "1"):
                raise ValueError("reset_origin_unavailable")
            if (clock.get("reset_origin") != "operational_wolfboot_entry"
                    or checkpoints.get("reset_origin") != clock["reset_origin"]
                    or clock.get("reset_origin_kind") != "1"
                    or clock.get("handoff_bridge") != "LPTIM2_HSI16_DIV16"):
                raise ValueError("reset_origin_mismatch")
            offset = uint(clock.get("reset_origin_to_application_timebase_us"))
            if uint(checkpoints.get("reset_origin_to_application_timebase_us")) != offset:
                raise ValueError("reset_offset_mismatch")
            row["reset_offset_us"] = offset
            if offset + end > U64_MAX:
                raise ValueError("integer_out_of_range")
            _duration(row, 0, offset + end, values.get(metric + "_us"))
        else:
            row["start_boundary"] = "application_request_us" if metric.startswith("req_") else "tcp_connect_start_us"
            _duration(row, request if metric.startswith("req_") else tcp, end, values.get(metric + "_us"))
        row["operation_outcome"] = "success"
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        row.update(value_us=None, validity="unavailable", reason=str(exc) if isinstance(exc, ValueError) else "malformed_metric_record")
    return row


def _tls(records: list[dict], epoch: Epoch, iteration: int, repeated: bool) -> dict:
    row = blank_metric("tls_handshake", "missing_evidence", epoch=epoch,
                       iteration=iteration, repeated=repeated)
    row.update(start_boundary="tls_handshake_start_us", end_boundary="tls_handshake_end_us",
               timestamp_origin="application_timebase_start", clock_source="application_monotonic_us")
    try:
        statuses = [r for r in records if r["marker"] == "PQC_TLS_REPEAT_ITERATION"]
        status = None
        if statuses:
            status = _use(row, _one(records, "PQC_TLS_REPEAT_ITERATION"))
            _version(status, "1")
            if uint(status.get("iteration")) != iteration:
                raise ValueError("iteration_identity_mismatch")
            row["handshake_id"] = uint(status.get("handshake"))
            row["operation_outcome"] = status.get("tls_outcome", "unknown")
            if status.get("instrumentation_available") != "1":
                raise ValueError("handshake_not_instrumented")
            if status.get("timing_source") != "TIM2_1MHz":
                raise ValueError("invalid_clock_provenance")
            row.update(counter_hz=1_000_000, clock_source="TIM2")
            row["clock_provenance"] = {"timing_source": status["timing_source"]}
        timing = _use(row, _one(records, "PQC_TLS_HANDSHAKE_TIMING"))
        row["clock_provenance"]["timebase_available"] = timing.get("timebase_available")
        if timing.get("timebase_available") != "1":
            raise ValueError("application_timebase_unavailable")
        result = timing.get("result", "")
        if not re.fullmatch(r"-?[0-9]+", result):
            raise ValueError("invalid_handshake_result")
        row["result_code"] = int(result)
        row["operation_outcome"] = "success" if result == "1" else "failed"
        if result != "1":
            raise ValueError("tls_handshake_failed")
        if status and status.get("tls_outcome") != "success":
            raise ValueError("handshake_outcome_conflict")
        if any(r["marker"] == "PQC_RM2_TIMEBASE" for r in records):
            _clock(row, records)
        buffer_records = [r for r in records if r["marker"] == "PQC_TLS_EVENT_BUFFER"]
        if buffer_records:
            buffer = _use(row, _one(records, "PQC_TLS_EVENT_BUFFER"))
            _version(buffer, "1")
            if uint(buffer.get("iteration")) != iteration:
                raise ValueError("iteration_identity_mismatch")
            handshake = uint(buffer.get("handshake"))
            if row["handshake_id"] is not None and handshake != row["handshake_id"]:
                raise ValueError("handshake_identity_mismatch")
            row["handshake_id"] = handshake
        start, end = uint(timing.get("start_us")), uint(timing.get("end_us"))
        _duration(row, start, end, timing.get("elapsed_us"))
        if status and uint(status.get("handshake_elapsed_us")) != row["value_us"]:
            raise ValueError("reported_duration_mismatch")
        outer = [r for r in records if r["marker"] == "PQC_TLS_EVENT" and r["fields"].get("name") == "handshake"]
        if len(outer) > 1:
            raise ValueError("ambiguous_outer_handshake")
        if outer:
            event = _use(row, outer[0])
            row["invocation_sequence"] = uint(event.get("sequence"))
            if (event.get("completed") != "1" or event.get("result_available") != "1"
                    or event.get("result") != result or event.get("parent_sequence") != "-1"
                    or uint(event.get("start_us")) != start or uint(event.get("end_us")) != end
                    or uint(event.get("elapsed_us")) != row["value_us"]):
                raise ValueError("outer_handshake_conflict")
    except (ValueError, TypeError, KeyError) as exc:
        row.update(value_us=None, validity="unavailable", reason=str(exc) if isinstance(exc, ValueError) else "malformed_metric_record")
    return row


def extract_timings(epochs: list[Epoch], snapshot: dict, *, global_errors: list[str] | None = None) -> list[dict]:
    effective = snapshot.get("effective_non_secret_parameters", {})
    application = effective.get("firmware", {}).get("application")
    tls_mode = effective.get("mqtt", {}).get("tls", {}).get("mode")
    tls_selected = tls_mode not in (None, "", "plaintext", "not_applicable")
    repeated = application == "tls_handshake_repeat"
    rm2 = application == "mqtt_ready_metrics_2"
    rows: list[dict] = []
    for epoch in epochs:
        relevant = [r for r in epoch.records if r["marker"].startswith("PQC_RM2_")
                    or r["marker"] in ("PQC_TLS_HANDSHAKE_TIMING", "PQC_TLS_REPEAT_ITERATION")]
        # Final experiment-wide energy epochs do not constitute handshake attempts.
        iterations = sorted({r["iteration"] for r in relevant})
        for iteration in iterations:
            records = [r for r in epoch.records if r["iteration"] == iteration]
            epoch_rows = []
            if tls_selected or any(r["marker"] in ("PQC_TLS_HANDSHAKE_TIMING", "PQC_TLS_REPEAT_ITERATION") for r in records):
                epoch_rows.append(_tls(records, epoch, iteration, repeated))
            if rm2:
                epoch_rows.extend(_rm2(name, records, epoch, iteration, snapshot) for name in RM2_NAMES)
            elif not repeated and application in ("mqtt_ready_metrics", "mqtt_validation"):
                epoch_rows.append(blank_metric("mqtt_readiness", "readiness_checkpoint_not_recorded_in_current_workload",
                                               epoch=epoch, iteration=iteration))
            blockers = list(global_errors or []) + epoch.errors
            if len(iterations) > 1:
                blockers.append("multiple_iterations_in_one_reporting_epoch")
            if blockers:
                for row in epoch_rows:
                    row.update(value_us=None, validity="unavailable", reason=";".join(sorted(set(blockers))))
            rows.extend(epoch_rows)
    # Preserve a repeated iteration identity encountered in more than one epoch,
    # but never treat the duplicate as two valid observations of that iteration.
    if repeated:
        counts: dict[int, set[int]] = {}
        for row in rows:
            counts.setdefault(row["iteration_id"], set()).add(row["epoch_index"])
        for row in rows:
            if len(counts[row["iteration_id"]]) > 1:
                row.update(value_us=None, validity="unavailable", reason="duplicate_iteration_identity")
    if not rows:
        names = (["tls_handshake"] if tls_selected else []) + (list(RM2_NAMES) if rm2 else [])
        if not repeated and application in ("mqtt_ready_metrics", "mqtt_validation"):
            names.append("mqtt_readiness")
        reason = ";".join(global_errors or []) or "timing_records_unavailable"
        rows = [blank_metric(name, reason, repeated=False) for name in names]
        # A run-level availability row is not an invented intra-run iteration.
    return rows
