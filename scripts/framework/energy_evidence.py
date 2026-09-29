"""Integrity and alignment-anchor validation for passive ESP32 energy captures.

No energy integration is performed here. The retained evidence is a packed raw
sample stream plus the two ESP32 GPIO timestamps and the matching STM32 TIM2
boundary record. Offline analysis owns clock fitting and joule integration.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import struct
from pathlib import Path

SAMPLE_FIELDS = ("timestamp_us", "bus_v", "current_a", "power_w")
SAMPLE_STRUCT = struct.Struct("<qfff")
ENERGY_CHUNK_TOPIC = "pqc/instrument/energy/capture/chunk"
ENERGY_COMPLETE_TOPIC = "pqc/instrument/energy/capture/complete"
CAPTURE_ID = re.compile(r"[0-9a-f]{16}")
COUNTERS = (
    "i2c_errors",
    "alert_timeouts",
    "coalesced_alerts",
    "timing_errors",
    "saturation_errors",
    "sample_gaps",
    "sync_queue_drops",
)


def envelope(line: str) -> tuple[str, dict]:
    outer = json.loads(line)
    payload = outer["payload"]
    if isinstance(payload, dict) and "payload" in payload:
        payload = payload["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("non-object MQTT payload")
    return str(outer["topic"]), payload


def chunk_bytes(obj: dict) -> bytes:
    if "data_b64" in obj:
        if "data_hex" in obj:
            raise ValueError("ambiguous chunk encoding")
        return base64.b64decode(obj["data_b64"], validate=True)
    if "data_hex" in obj:
        return bytes.fromhex(obj["data_hex"])
    raise ValueError("chunk payload encoding missing")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _stm32_boundaries(lines: list[str], run_id: str) -> list[tuple[int, int]]:
    chunks: dict[int, bytes] = {}
    boundaries: list[tuple[int, int]] = []
    for line in lines:
        if not line.strip():
            continue
        topic, obj = envelope(line)
        if not topic.startswith(f"pqc/result/stm32/{run_id}/"):
            continue
        _require(obj.get("source") == "stm32" and obj.get("run_id") == run_id,
                 "STM32 source/run identity mismatch")
        if obj.get("type") == "chunk":
            sequence = obj.get("sequence")
            _require(type(sequence) is int and sequence >= 0 and sequence not in chunks,
                     "invalid/duplicate STM32 chunk sequence")
            chunks[sequence] = chunk_bytes(obj)
            continue
        _require(obj.get("type") == "complete", "unexpected STM32 result envelope")
        count = obj.get("chunk_count")
        _require(type(count) is int and set(chunks) == set(range(count)),
                 "incomplete STM32 result stream")
        logical = b"".join(chunks[i] for i in range(count))
        _require(hashlib.sha256(logical).hexdigest() == obj.get("logical_sha256"),
                 "STM32 logical hash mismatch")
        _require(len(logical) == obj.get("logical_bytes"), "STM32 logical byte count mismatch")
        chunks = {}
        for raw_record in logical.splitlines():
            if not raw_record.strip():
                continue
            record = json.loads(raw_record)
            if not isinstance(record, dict) or record.get("context") != "energy_boundary":
                continue
            text = str(record.get("text", ""))
            _require(text.startswith("PQC_ENERGY_BOUNDARY "), "invalid STM32 energy boundary marker")
            values = dict(re.findall(r"(\w+)=([^\s]+)", text))
            _require(values.get("scope") == "experiment" and values.get("valid") == "1",
                     "invalid STM32 experiment boundary")
            _require(values.get("clock") == "TIM2" and values.get("counter_hz") == "1000000",
                     "unexpected STM32 boundary clock")
            _require(values.get("timestamp_convention") == "before_gpio_write",
                     "unexpected STM32 GPIO timestamp convention")
            s0 = int(values["s0_us"])
            s1 = int(values["s1_us"])
            _require(0 <= s0 < s1, "non-monotonic STM32 boundary")
            boundaries.append((s0, s1))
    _require(not chunks, "incomplete trailing STM32 result stream")
    return boundaries


def validate_energy_evidence(path: Path, run_id: str) -> dict:
    """Validate the latest completed passive capture in this run's fresh stream."""
    result = {
        "passed": False,
        "failure_reasons": [],
        "capture_id": None,
        "sample_count": 0,
        "sample_record_bytes": SAMPLE_STRUCT.size,
        "superseded_capture_count": 0,
        "alignment": None,
    }
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        captures: dict[str, dict] = {}
        completion_order: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            topic, obj = envelope(line)
            if topic not in {ENERGY_CHUNK_TOPIC, ENERGY_COMPLETE_TOPIC}:
                continue
            _require(obj.get("source") == "energy" and obj.get("schema") == 1,
                     "invalid energy source/schema")
            capture_id = str(obj.get("capture_id", ""))
            _require(CAPTURE_ID.fullmatch(capture_id) is not None, "invalid energy capture ID")
            state = captures.setdefault(capture_id, {"chunks": {}, "complete": None})
            if topic == ENERGY_CHUNK_TOPIC:
                _require(obj.get("type") == "chunk", "energy chunk topic/type mismatch")
                sequence = obj.get("sequence")
                _require(type(sequence) is int and sequence >= 0, "invalid energy chunk sequence")
                data = chunk_bytes(obj)
                if sequence in state["chunks"]:
                    _require(state["chunks"][sequence] == data, "conflicting duplicate energy chunk")
                else:
                    state["chunks"][sequence] = data
            else:
                _require(obj.get("type") == "complete", "energy completion topic/type mismatch")
                if state["complete"] is not None:
                    _require(state["complete"] == obj, "conflicting duplicate energy completion")
                else:
                    state["complete"] = obj
                    completion_order.append(capture_id)

        _require(bool(completion_order), "missing energy completion")
        boundaries = _stm32_boundaries(lines, run_id)
        _require(len(boundaries) == 1, "expected exactly one experiment-wide STM32 energy boundary")
        s0, s1 = boundaries[0]
        stm32_duration = s1 - s0
        duration_tolerance = max(5000, stm32_duration // 100)

        selected_id = None
        for candidate_id in reversed(completion_order):
            candidate = captures[candidate_id].get("complete")
            if not isinstance(candidate, dict):
                continue
            e0_candidate = candidate.get("e0_us")
            e1_candidate = candidate.get("e1_us")
            if type(e0_candidate) is not int or type(e1_candidate) is not int or not 0 <= e0_candidate < e1_candidate:
                continue
            if abs((e1_candidate - e0_candidate) - stm32_duration) <= duration_tolerance:
                selected_id = candidate_id
                break
        _require(selected_id is not None, "no energy capture duration matches the STM32 experiment window")

        selected = captures[selected_id]
        complete = selected["complete"]
        chunks = selected["chunks"]
        _require(isinstance(complete, dict), "selected energy completion missing")
        samples = decode_acquisition(complete, chunks)
        logical = b"".join(chunks[i] for i in range(complete["chunk_count"]))
        sample_count = complete["sample_count"]
        timestamps = [sample[0] for sample in samples]
        e0, e1 = complete["e0_us"], complete["e1_us"]
        pretrigger = complete["pretrigger_us"]

        _require(abs((e1 - e0) - stm32_duration) <= duration_tolerance,
                 "selected energy capture duration no longer matches STM32 window")
        scale = stm32_duration / (e1 - e0)
        _require(math.isfinite(scale) and scale > 0.0, "invalid cross-clock alignment anchors")

        result.update({
            "passed": True,
            "capture_id": selected_id,
            "sample_count": sample_count,
            "logical_bytes": len(logical),
            "logical_sha256": complete.get("logical_sha256"),
            "superseded_capture_count": max(0, len(completion_order) - 1),
            "pretrigger_us": pretrigger,
            "pretrigger_complete": complete["pretrigger_complete"],
            "available_pretrigger_us": max(0, e0 - timestamps[0]),
            "pretrigger_max_gap_us": max(
                (timestamps[i + 1] - timestamps[i]
                 for i in range(len(timestamps) - 1) if timestamps[i + 1] < e0),
                default=0,
            ),
            "first_timestamp_us": timestamps[0],
            "last_timestamp_us": timestamps[-1],
            "alignment": {
                "esp32_start_us": e0,
                "esp32_end_us": e1,
                "stm32_start_us": s0,
                "stm32_end_us": s1,
                "linear_scale_stm32_us_per_esp32_us": scale,
                "timestamp_convention": "STM32 TIM2 sampled before GPIO write; ESP32 timestamps observed GPIO edges",
            },
        })
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, struct.error) as exc:
        result["failure_reasons"].append(str(exc))
    return result


def decode_acquisition(complete: dict, chunks: dict[int, bytes]) -> list[tuple]:
    """Validate one instrument-local acquisition without requiring STM32 pairs.

    Shared with capture acceptance; does not associate intervals or integrate.
    """
    count = complete.get("chunk_count")
    _require(type(count) is int and count >= 1 and set(chunks) == set(range(count)),
             "energy chunk count/sequence mismatch")
    logical = b"".join(chunks[i] for i in range(count))
    _require(hashlib.sha256(logical).hexdigest() == complete.get("logical_sha256"),
             "energy logical hash mismatch")
    _require(len(logical) == complete.get("logical_bytes"), "energy logical byte count mismatch")

    contract = {
        "clock_hz": 1000000,
        "sample_record_bytes": SAMPLE_STRUCT.size,
        "sample_encoding": "little_endian_ieee754_v1",
        "sample_fields": list(SAMPLE_FIELDS),
        "sync_gpio": 11,
        "alert_gpio": 12,
        "calibration_id": "empirical_dmm_reference_loads_2026-09-25",
        "calibration_status": "empirical_two_load_current_scaling",
        "nominal_shunt_ohms": 0.015,
        "effective_shunt_ohms": 0.029,
        "acquisition_mode": "alert_triggered_bus_shunt",
        "bus_conversion_us": 50,
        "shunt_conversion_us": 50,
        "averaging": 1,
        "i2c_hz": 400000,
        "gap_limit_us": 10000,
    }
    _require(all(complete.get(key) == value for key, value in contract.items()),
             "energy capture configuration/calibration mismatch")
    _require(re.fullmatch(r"[0-9a-f]{64}", str(complete.get("firmware_sha256", ""))) is not None,
             "missing ESP32 firmware identity")
    _require(type(complete.get("pretrigger_complete")) is bool, "invalid pre-trigger status")
    _require(all(type(complete.get(key)) is int and complete.get(key) == 0 for key in COUNTERS),
             "energy acquisition/sync fault counter increment")

    sample_count = complete.get("sample_count")
    _require(type(sample_count) is int and sample_count >= 2, "invalid energy sample count")
    _require(len(logical) == sample_count * SAMPLE_STRUCT.size, "sample byte/count mismatch")
    e0 = complete.get("e0_us")
    e1 = complete.get("e1_us")
    pretrigger = complete.get("pretrigger_us")
    _require(all(type(v) is int for v in (e0, e1, pretrigger)) and 0 <= e0 < e1 and 0 < pretrigger <= 1_000_000,
             "invalid ESP32 GPIO timestamps/pre-trigger")

    samples = [SAMPLE_STRUCT.unpack_from(logical, offset)
               for offset in range(0, len(logical), SAMPLE_STRUCT.size)]
    timestamps = [sample[0] for sample in samples]
    _require(all(all(math.isfinite(float(v)) for v in sample[1:]) for sample in samples),
             "non-finite electrical sample")
    _require(all(timestamps[i] < timestamps[i + 1] for i in range(len(timestamps) - 1)),
             "non-monotonic sample timestamps")
    gap_limit = int(complete["gap_limit_us"])
    # Pre-edge history is best effort. Only the part of a gap inside the
    # measured GPIO interval contributes to the continuity requirement.
    _require(all(timestamps[i + 1] - max(timestamps[i], e0) <= gap_limit
                 for i in range(len(timestamps) - 1) if timestamps[i + 1] >= e0),
             "sample timestamp gap exceeds limit in measured interval")
    _require(e0 - pretrigger <= timestamps[0] <= e0 + gap_limit
             and e0 <= timestamps[-1] <= e1,
             "capture exceeds pre-trigger limit or does not span measured interval")
    _require(e1 - timestamps[-1] <= gap_limit,
             "final energy sample is too far before falling GPIO edge")
    _require(complete.get("first_timestamp_us") == timestamps[0]
             and complete.get("last_timestamp_us") == timestamps[-1],
             "energy completion sample bounds mismatch")

    return samples
