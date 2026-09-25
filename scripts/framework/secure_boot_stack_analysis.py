"""Offline, read-only analysis of raw STM32 secure-boot stack evidence.

A finalized run manifest is never rewritten. Input identities and analysis
output hashes are recorded separately under an analysis directory.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

PARSER_VERSION = "request4-stack-1"
BOUNDARY = "selected_image_integrity_begin_to_verification_end"


class StackEvidenceError(ValueError):
    """Raw reporting evidence is absent, contradictory, or corrupted."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fields(text: str, prefix: str) -> dict[str, str]:
    if not text.startswith(prefix + " "):
        raise StackEvidenceError(f"expected {prefix} structured record")
    pairs = text[len(prefix):].strip().split()
    result = {}
    for pair in pairs:
        if "=" not in pair:
            raise StackEvidenceError(f"invalid {prefix} field: {pair!r}")
        key, value = pair.split("=", 1)
        if key in result:
            raise StackEvidenceError(f"duplicate {prefix} field: {key}")
        result[key] = value
    return result


def _decode_payload(line: str, expected_run_id: str) -> dict[str, Any] | None:
    envelope = json.loads(line)
    if not isinstance(envelope, dict):
        raise StackEvidenceError("reporting envelope must be an object")
    payload = envelope.get("payload")
    if isinstance(payload, dict) and "payload" in payload:
        payload = payload["payload"]
    message = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(message, dict):
        raise StackEvidenceError("reporting message must be an object")
    if message.get("source") != "stm32":
        return None
    if message.get("run_id") != expected_run_id:
        raise StackEvidenceError("STM32 reporting run ID does not match manifest")
    return message


def _raw_records(raw: bytes, expected_run_id: str) -> list[dict[str, Any]]:
    chunks: dict[int, bytes] = {}
    results: list[dict[str, Any]] = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            message = _decode_payload(line, expected_run_id)
            if message is None:
                continue
            kind = message.get("type")
            if kind == "chunk":
                seq = message["sequence"]
                if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0 or seq in chunks:
                    raise StackEvidenceError("invalid/duplicate STM32 chunk sequence")
                chunks[seq] = bytes.fromhex(message["data_hex"])
            elif kind == "complete":
                count = message["chunk_count"]
                if not isinstance(count, int) or count < 1 or set(chunks) != set(range(count)):
                    raise StackEvidenceError("incomplete STM32 result epoch")
                if message.get("overflowed") is not False or message.get("dropped_record_count") != 0:
                    raise StackEvidenceError("STM32 buffer overflow or dropped records")
                logical = b"".join(chunks[index] for index in range(count))
                if len(logical) != message.get("logical_bytes") or _sha256(logical) != message.get("logical_sha256"):
                    raise StackEvidenceError("STM32 completion length/hash mismatch")
                lines = [item for item in logical.splitlines() if item.strip()]
                if len(lines) != message.get("record_count"):
                    raise StackEvidenceError("STM32 completion record-count mismatch")
                for item in lines:
                    record = json.loads(item)
                    if not isinstance(record, dict):
                        raise StackEvidenceError("STM32 logical record must be an object")
                    results.append(record)
                chunks.clear()
            else:
                raise StackEvidenceError(f"unknown STM32 message type {kind!r}")
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            if isinstance(exc, StackEvidenceError):
                raise
            raise StackEvidenceError(f"invalid STM32 reporting stream: {exc}") from exc
    if chunks or not results:
        raise StackEvidenceError("STM32 stream has an incomplete or absent epoch")
    return results


def analyse_run(manifest_path: Path | str) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise StackEvidenceError("manifest must be an object")
    if manifest.get("boot_selection", {}).get("boot_stack_profiling") is not True:
        raise StackEvidenceError("run manifest does not select stack profiling")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise StackEvidenceError("manifest has no run ID")
    raw_path = manifest_path.parent / "mqtt-reporting-raw.ndjson"
    raw_bytes = raw_path.read_bytes()
    records = _raw_records(raw_bytes, run_id)
    texts = [record["text"] for record in records
             if record.get("context") == "secure_boot" and isinstance(record.get("text"), str)]
    stack = [_fields(text, "PQC_SECURE_BOOT_STACK") for text in texts
             if text.startswith("PQC_SECURE_BOOT_STACK ")]
    profile = [_fields(text, "PQC_SECURE_BOOT_PROFILE") for text in texts
               if text.startswith("PQC_SECURE_BOOT_PROFILE ")]
    if len(stack) != 1 or len(profile) != 1:
        raise StackEvidenceError("expected one stack and one profile record per run")
    data = stack[0]
    if data.get("schema") != "1" or data.get("boundary") != BOUNDARY or \
            data.get("profiling_enabled") != "1" or data.get("timing_comparable") != "0":
        raise StackEvidenceError("invalid stack record schema/boundary/mode")
    status = data.get("measurement_status")
    if status not in ("measured", "unavailable"):
        raise StackEvidenceError("unknown stack measurement status")
    if status == "measured":
        try:
            bytes_used = int(data["high_water_bytes"])
            capacity = int(data["watermark_capacity_bytes"])
        except (ValueError, KeyError) as exc:
            raise StackEvidenceError("measured stack fields not numeric") from exc
        if bytes_used <= 0 or capacity <= 0 or data.get("selected_image_valid") != "1":
            raise StackEvidenceError("invalid measured stack status or selected image")
    else:
        if data.get("high_water_bytes") != "unavailable":
            raise StackEvidenceError("unavailable stack was assigned a numeric value")
        bytes_used = None
    algorithm = profile[0].get("signature_algorithm")
    if not algorithm or algorithm == "unknown":
        raise StackEvidenceError("unidentified secure-boot algorithm")
    if profile[0].get("mailbox_version") != "8":
        raise StackEvidenceError("stack result has incompatible mailbox schema")
    return {
        "run_id": run_id, "algorithm": algorithm, "stack_status": status,
        "stack_high_water_bytes": bytes_used, "boundary": BOUNDARY,
        "timing_comparable": False,
        "inputs": {
            "manifest": {"path": str(manifest_path), "sha256": _sha256(manifest_bytes), "size": len(manifest_bytes)},
            "raw_stream": {"path": str(raw_path), "sha256": _sha256(raw_bytes), "size": len(raw_bytes)},
        },
    }


def aggregate_runs(paths: Iterable[Path | str]) -> dict[str, Any]:
    runs = [analyse_run(path) for path in paths]
    if not runs:
        raise StackEvidenceError("no stack profiling runs provided")
    if len({run["run_id"] for run in runs}) != len(runs):
        raise StackEvidenceError("duplicate run ID in aggregation")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        groups[run["algorithm"]].append(run)
    profiles = []
    for algorithm, observations in sorted(groups.items()):
        measured = [run["stack_high_water_bytes"] for run in observations
                    if run["stack_status"] == "measured"]
        profiles.append({
            "algorithm": algorithm, "sample_count": len(observations),
            "measured_count": len(measured), "unavailable_count": len(observations) - len(measured),
            "minimum_stack_high_water_bytes": min(measured) if measured else None,
            "median_stack_high_water_bytes": statistics.median(measured) if measured else None,
            "maximum_stack_high_water_bytes": max(measured) if measured else None,
            "run_ids": [run["run_id"] for run in observations],
        })
    return {"schema": "pqc-secure-boot-stack-analysis", "version": 1,
            "parser_version": PARSER_VERSION, "boundary": BOUNDARY,
            "timing_comparable": False, "runs": runs, "profiles": profiles}


def write_analysis(summary: dict[str, Any], output_dir: Path | str) -> Path:
    output_dir = Path(output_dir)
    if "analysis" not in output_dir.parts:
        raise StackEvidenceError("derived output must be written under an analysis/ namespace")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "secure_boot_stack_summary.json"
    contents = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output.write_bytes(contents)
    lineage = {"parser_version": PARSER_VERSION, "boundary": BOUNDARY,
               "inputs": [run["inputs"] for run in summary["runs"]],
               "output": {"path": output.name, "sha256": _sha256(contents), "size": len(contents)}}
    (output_dir / "secure_boot_stack_lineage.json").write_text(
        json.dumps(lineage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
