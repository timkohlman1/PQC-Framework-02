"""Raw acquisition acceptance only: no clock fitting or energy integration."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from pathlib import Path

FIELDS = "interval_index sample_index sequence timestamp_us relative_us bus_v current_a power_w read_duration_us status_flags diagnostic_flags".split()
COUNTERS = "i2c_errors alert_timeouts coalesced_alerts timing_errors saturation_errors sample_gaps sync_queue_drops".split()


def envelope(line: str) -> tuple[str, dict]:
    outer = json.loads(line)
    payload = outer["payload"]
    if isinstance(payload, dict) and "payload" in payload:
        payload = payload["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("non-object MQTT payload")
    return outer["topic"], payload


def chunk_bytes(obj: dict) -> bytes:
    if "data_b64" in obj:
        if "data_hex" in obj:
            raise ValueError("ambiguous chunk encoding")
        return base64.b64decode(obj["data_b64"], validate=True)
    return bytes.fromhex(obj["data_hex"])


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def validate_energy_evidence(path: Path, run_id: str, token: str, expected_intervals: int) -> dict:
    """Join independently hashed raw streams without normalizing the evidence."""
    try:
        _require(1 <= expected_intervals <= 32, "invalid interval count")
        _require(re.fullmatch(r"[0-9a-f]{32}", token) is not None, "invalid association token")
        streams = {"stm32": [], "energy": []}
        chunks = {"stm32": {}, "energy": {}}
        completion = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            topic, obj = envelope(line)
            source = obj.get("source")
            _require(source in streams and obj.get("run_id") == run_id, "source/run identity mismatch")
            prefix = "pqc/result/stm32" if source == "stm32" else "pqc/instrument/energy"
            _require(topic == f"{prefix}/{run_id}/" + ("complete" if obj.get("type") == "error" else str(obj.get("type"))), "topic mismatch")
            if obj.get("type") == "error":
                raise ValueError(f"{source} terminal error: {obj.get('status')}")
            if obj.get("type") == "chunk":
                seq = obj.get("sequence")
                _require(type(seq) is int and seq >= 0 and seq not in chunks[source], "invalid/duplicate sequence")
                chunks[source][seq] = chunk_bytes(obj)
                continue
            _require(obj.get("type") == "complete", "unexpected envelope")
            count = obj.get("chunk_count")
            _require(type(count) is int and count == len(chunks[source]) and set(chunks[source]) == set(range(count)), "chunk count/sequence mismatch")
            raw = b"".join(chunks[source][i] for i in range(count))
            _require(hashlib.sha256(raw).hexdigest() == obj.get("logical_sha256"), "logical hash mismatch")
            _require(len(raw) == obj.get("logical_bytes"), "logical byte count mismatch")
            lines = raw.splitlines()
            _require(len(lines) == obj.get("record_count") and raw.endswith(b"\n"), "record framing/count mismatch")
            if source == "stm32":
                _require(obj.get("overflowed") is False and obj.get("dropped_record_count") == 0,
                         "STM32 result overflow/drop")
            streams[source].append([json.loads(record) for record in lines])
            chunks[source] = {}
            if source == "energy":
                _require(completion is None, "duplicate energy completion")
                completion = obj
        _require(not any(chunks.values()), "incomplete trailing stream")
        _require(len(streams["energy"]) == 1 and completion is not None, "missing energy completion")
        _require(len(streams["stm32"]) == expected_intervals, "STM32 epoch count mismatch")
        records = streams["energy"][0]
        session = records[0]
        contract = {
            "record": "session", "schema": 3, "source": "energy", "run_id": run_id,
            "association_token": token, "clock_hz": 1000000, "interval_count": expected_intervals,
            "sync_gpio": 11, "alert_gpio": 12, "calibration_id": "empirical_dmm_reference_loads_2026-09-25",
            "calibration_status": "empirical_two_load_current_scaling", "nominal_shunt_ohms": .015,
            "effective_shunt_ohms": .029, "acquisition_mode": "alert_triggered_bus_shunt",
            "bus_conversion_us": 50, "shunt_conversion_us": 50, "averaging": 1, "i2c_hz": 400000,
            "gap_limit_us": 10000, "analysis": "offline_only", "sample_encoding": "array_v1",
            "collection_acquisition": "paused", "sample_fields": FIELDS, "sample_record_bytes": 64,
        }
        _require(isinstance(session, dict) and all(session.get(k) == v for k, v in contract.items()), "session configuration/calibration mismatch")
        _require(re.fullmatch(r"[0-9a-f]{64}", session.get("firmware_sha256", "")) is not None, "missing firmware identity")
        _require(re.fullmatch(r"[0-9a-f]{32}", session.get("session_id", "")) is not None, "missing boot-session identity")
        _require(session["sample_record_bytes"] > 0 and session["ring_capacity_samples"] >= 2
                 and session["ring_allocated_bytes"] == session["sample_record_bytes"] * session["ring_capacity_samples"]
                 and session["psram_reserve_bytes"] >= 512 * 1024
                 and session["ring_allocated_bytes"] <= session["psram_total_bytes"] - session["psram_reserve_bytes"], "invalid ring allocation")
        boundaries = {}
        for epoch in streams["stm32"]:
            for record in epoch:
                _require(isinstance(record, dict), "malformed STM32 record")
                if record.get("context") != "energy_boundary":
                    continue
                text = record.get("text", "")
                _require(text.startswith("PQC_ENERGY_BOUNDARY "), "invalid STM32 boundary record")
                values = dict(re.findall(r"(\w+)=([^\s]+)", text))
                idx = int(values["interval_index"])
                _require(record.get("source") == "stm32" and record.get("iteration") == idx,
                         "STM32 boundary identity mismatch")
                _require(idx not in boundaries and values["valid"] == "1"
                         and values["clock"] == "TIM2" and values["counter_hz"] == "1000000"
                         and values["timestamp_convention"] == "before_gpio_write", "invalid/duplicate STM32 boundary")
                boundaries[idx] = (int(values["s0_us"]), int(values["s1_us"]))
        _require(set(boundaries) == set(range(expected_intervals)), "missing STM32 boundaries")
        groups = []
        for record in records[1:]:
            if isinstance(record, dict):
                _require(record.get("record") == "interval", "unexpected energy record")
                groups.append((record, []))
            else:
                _require(bool(groups) and isinstance(record, list) and len(record) == len(FIELDS), "invalid sample array")
                groups[-1][1].append(dict(zip(FIELDS, record)))
        _require(len(groups) == expected_intervals, "energy interval count mismatch")
        previous_end = previous_stm32_end = previous_sequence = -1
        total_samples = 0
        for index, (interval, samples) in enumerate(groups):
            e0, e1 = interval["e0_us"], interval["e1_us"]
            s0, s1 = boundaries[index]
            _require(all(type(interval[k]) is int for k in (
                "e0_us", "e1_us", "interval_index", "interval_sequence", "start_sample_sequence", "end_sample_sequence", *COUNTERS)),
                "noninteger interval metadata")
            _require(interval["interval_index"] == index and interval["interval_sequence"] > previous_sequence
                     and 0 <= s0 < s1 and 0 <= e0 < e1 and e0 >= previous_end and s0 >= previous_stm32_end, "invalid interval ordering")
            _require(interval.get("stm32_boundary_source") == "stm32.energy_boundary" and interval.get("run_association") == "collector_token", "boundary association mismatch")
            _require(all(interval.get(k) == 0 for k in COUNTERS), "acquisition fault counter increment")
            _require(len(samples) >= 2 and samples[0]["timestamp_us"] <= e0 and samples[-1]["timestamp_us"] >= e1, "missing bracketing samples")
            _require(samples[0]["sequence"] == interval["start_sample_sequence"] and samples[-1]["sequence"] == interval["end_sample_sequence"], "sample bounds mismatch")
            for j, sample in enumerate(samples):
                _require(sample["interval_index"] == index and sample["sample_index"] == j
                         and sample["sequence"] == samples[0]["sequence"]+j
                         and sample["relative_us"] == sample["timestamp_us"]-e0, "sample identity/time mismatch")
                _require(all(type(sample[k]) in (int, float) and math.isfinite(sample[k]) for k in FIELDS), "invalid numeric sample")
                _require(all(type(sample[k]) is int for k in FIELDS if k not in {"bus_v", "current_a", "power_w"}), "noninteger sample metadata")
                _require(sample["status_flags"] == 0 and sample["read_duration_us"] >= 0, "invalid sensor sample")
                if j:
                    _require(0 < sample["timestamp_us"]-samples[j-1]["timestamp_us"] <= 10000, "sample time gap/order failure")
            previous_end, previous_stm32_end, previous_sequence = e1, s1, interval["interval_sequence"]
            total_samples += len(samples)
        _require(completion.get("sample_count") == total_samples and completion.get("interval_count") == expected_intervals
                 and completion.get("acquisition_status") == "raw", "completion acquisition/count mismatch")
        return {"passed": True, "scope": "raw_acquisition_only", "failure_reasons": []}
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
        return {"passed": False, "scope": "raw_acquisition_only", "failure_reasons": [str(exc)]}
