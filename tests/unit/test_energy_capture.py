"""Passive ESP32 energy-capture contracts and resolver integration."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest
import yaml

from framework.config_resolver import ConfigResolver
from framework.energy_capture import EnergyCapture
from framework.energy_evidence import (
    ENERGY_CHUNK_TOPIC,
    ENERGY_COMPLETE_TOPIC,
    SAMPLE_FIELDS,
    SAMPLE_STRUCT,
    validate_energy_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = "0123456789abcdef"


def _outer(topic: str, payload: dict) -> str:
    return json.dumps({"topic": topic, "payload": payload}, separators=(",", ":")) + "\n"


def _stm32_epoch(run_id: str, s0: int = 10_000_000, s1: int = 11_000_000) -> list[str]:
    record = {
        "source": "stm32",
        "iteration": 0,
        "context": "energy_boundary",
        "text": (
            "PQC_ENERGY_BOUNDARY scope=experiment "
            f"s0_us={s0} s1_us={s1} valid=1 clock=TIM2 counter_hz=1000000 "
            "timestamp_convention=before_gpio_write"
        ),
    }
    logical = (json.dumps(record, separators=(",", ":")) + "\n").encode()
    chunk = {
        "type": "chunk",
        "source": "stm32",
        "run_id": run_id,
        "sequence": 0,
        "data_hex": logical.hex(),
    }
    complete = {
        "type": "complete",
        "source": "stm32",
        "run_id": run_id,
        "chunk_count": 1,
        "logical_bytes": len(logical),
        "logical_sha256": hashlib.sha256(logical).hexdigest(),
    }
    return [
        _outer(f"pqc/result/stm32/{run_id}/chunk", chunk),
        _outer(f"pqc/result/stm32/{run_id}/complete", complete),
    ]


def _sample_bytes(e0: int = 4_000_000, e1: int = 5_000_000) -> bytes:
    # Up to 1 s optional pre-trigger plus the measured interval, sampled every 10 ms.
    records = []
    for timestamp in range(e0 - 1_000_000, e1 + 1, 10_000):
        records.append(SAMPLE_STRUCT.pack(timestamp, 5.0, 0.1, 0.5))
    return b"".join(records)


def _energy_capture(
    capture_id: str = CAPTURE,
    e0: int = 4_000_000,
    e1: int = 5_000_000,
    *,
    mutations: dict | None = None,
    timestamps: list[int] | None = None,
) -> list[str]:
    logical = (_sample_bytes(e0, e1) if timestamps is None else
               b"".join(SAMPLE_STRUCT.pack(t, 5.0, 0.1, 0.5) for t in timestamps))
    payloads = []
    # Exercise multi-chunk reconstruction while keeping record boundaries intact.
    chunk_bytes = 4000
    chunks = [logical[i : i + chunk_bytes] for i in range(0, len(logical), chunk_bytes)]
    for sequence, data in enumerate(chunks):
        payloads.append(
            _outer(
                ENERGY_CHUNK_TOPIC,
                {
                    "type": "chunk",
                    "source": "energy",
                    "schema": 1,
                    "capture_id": capture_id,
                    "sequence": sequence,
                    "data_b64": base64.b64encode(data).decode(),
                },
            )
        )
    completion = {
        "type": "complete",
        "source": "energy",
        "schema": 1,
        "capture_id": capture_id,
        "clock_hz": 1_000_000,
        "e0_us": e0,
        "e1_us": e1,
        "pretrigger_us": 1_000_000,
        "pretrigger_complete": True,
        "first_timestamp_us": SAMPLE_STRUCT.unpack_from(logical)[0],
        "last_timestamp_us": SAMPLE_STRUCT.unpack_from(logical, len(logical) - SAMPLE_STRUCT.size)[0],
        "sample_count": len(logical) // SAMPLE_STRUCT.size,
        "sample_record_bytes": SAMPLE_STRUCT.size,
        "sample_encoding": "little_endian_ieee754_v1",
        "sample_fields": list(SAMPLE_FIELDS),
        "chunk_count": len(chunks),
        "logical_bytes": len(logical),
        "logical_sha256": hashlib.sha256(logical).hexdigest(),
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
        "i2c_errors": 0,
        "alert_timeouts": 0,
        "coalesced_alerts": 0,
        "timing_errors": 0,
        "saturation_errors": 0,
        "sample_gaps": 0,
        "sync_queue_drops": 0,
        "ring_capacity_samples": 300000,
        "ring_allocated_bytes": 6000000,
        "psram_total_bytes": 8388608,
        "psram_reserve_bytes": 524288,
        "firmware_sha256": "b" * 64,
    }
    if mutations:
        completion.update(mutations)
    payloads.append(_outer(ENERGY_COMPLETE_TOPIC, completion))
    return payloads


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "mqtt-reporting-raw.ndjson"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def test_passive_capture_validates_and_derives_two_edge_alignment(tmp_path):
    path = _write(tmp_path, _stm32_epoch("run") + _energy_capture())
    result = validate_energy_evidence(path, "run")
    assert result["passed"], result["failure_reasons"]
    assert result["capture_id"] == CAPTURE
    assert result["sample_record_bytes"] == 20
    assert result["sample_count"] == 201
    assert result["alignment"] == {
        "esp32_start_us": 4_000_000,
        "esp32_end_us": 5_000_000,
        "stm32_start_us": 10_000_000,
        "stm32_end_us": 11_000_000,
        "linear_scale_stm32_us_per_esp32_us": 1.0,
        "timestamp_convention": "STM32 TIM2 sampled before GPIO write; ESP32 timestamps observed GPIO edges",
    }


def test_validator_ignores_stale_completed_capture_by_window_duration(tmp_path):
    stale = _energy_capture("1111111111111111", 1_000_000, 3_000_000)
    current = _energy_capture(CAPTURE, 4_000_000, 5_000_000)
    path = _write(tmp_path, stale + _stm32_epoch("run") + current)
    result = validate_energy_evidence(path, "run")
    assert result["passed"], result["failure_reasons"]
    assert result["capture_id"] == CAPTURE
    assert result["superseded_capture_count"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        {"logical_sha256": "0" * 64},
        {"effective_shunt_ohms": 0.015},
        {"pretrigger_us": 2_000_000},
        {"pretrigger_complete": "false"},
        {"i2c_errors": 1},
        {"firmware_sha256": "not-a-hash"},
        {"sample_record_bytes": 64},
    ],
)
def test_rejects_invalid_completion_contract(tmp_path, mutation):
    path = _write(tmp_path, _stm32_epoch("run") + _energy_capture(mutations=mutation))
    result = validate_energy_evidence(path, "run")
    assert not result["passed"]
    assert result["failure_reasons"]


def test_rejects_missing_or_duration_incompatible_stm32_boundary(tmp_path):
    no_boundary = _write(tmp_path, _energy_capture())
    assert not validate_energy_evidence(no_boundary, "run")["passed"]

    mismatch = _write(tmp_path, _stm32_epoch("run", 10_000_000, 10_500_000) + _energy_capture())
    result = validate_energy_evidence(mismatch, "run")
    assert not result["passed"]
    assert "duration" in result["failure_reasons"][0]


def _energy_case(tmp_path, workload="ready_metrics"):
    config = yaml.safe_load((ROOT / "configs/campaigns/baseline.yaml").read_text())
    config.update(instruments={"energy": "esp32_ina228"}, workload=workload)
    path = tmp_path / "energy.yaml"
    path.write_text(yaml.safe_dump(config))
    resolver = ConfigResolver(ROOT)
    case = resolver.expand_campaign(path)[0]
    return case, resolver.to_legacy_bundle(case)


def test_energy_selection_changes_firmware_identity_but_not_crypto_choices(tmp_path):
    case, bundle = _energy_case(tmp_path)
    baseline = ConfigResolver(ROOT).expand_campaign("baseline")[0]
    assert case["choices"] == baseline["choices"]
    assert case["provenance"]["firmware_identity"] != baseline["provenance"]["firmware_identity"]
    assert bundle["experiment"]["instruments"]["energy"]


def test_energy_capture_lifecycle_only_waits_for_existing_stream(tmp_path):
    _, bundle = _energy_case(tmp_path)
    completion = json.loads(_energy_capture()[-1])["payload"]
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, json.dumps(completion) + "\n", "")

    capture = EnergyCapture(bundle, tmp_path, runner)
    assert capture.wait("/tmp/report.ndjson")
    assert capture.completion == completion
    assert len(calls) == 1
    command_text = " ".join(calls[0][0])
    assert '"run_id":"' in command_text or "run_id" in command_text
    assert "mosquitto_pub" not in command_text
    assert "associate" not in command_text
    assert calls[0][1]["timeout"] <= 315
    assert (tmp_path / "energy-wait.log").exists()


def test_wait_timeout_is_a_capture_failure_and_is_logged(tmp_path):
    _, bundle = _energy_case(tmp_path)

    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    capture = EnergyCapture(bundle, tmp_path, runner)
    assert not capture.wait("/tmp/raw")
    assert "failed" in (tmp_path / "energy-wait.log").read_text().lower()


@pytest.mark.parametrize("history", [[], [3_927_027, 3_951_232], [3_999_000]])
def test_optional_pretrigger_accepts_zero_or_short_history_and_preedge_gaps(tmp_path, history):
    timestamps = history + list(range(4_000_000, 5_000_001, 10_000))
    path = _write(tmp_path, _stm32_epoch("run") + _energy_capture(
        timestamps=timestamps, mutations={"pretrigger_complete": False}))
    result = validate_energy_evidence(path, "run")
    assert result["passed"], result["failure_reasons"]
    assert result["available_pretrigger_us"] == (4_000_000 - history[0] if history else 0)
    assert result["pretrigger_complete"] is False
    assert result["pretrigger_max_gap_us"] == (24_205 if len(history) == 2 else 0)


@pytest.mark.parametrize("timestamps,passed", [
    (list(range(4_001_000, 5_000_001, 1000)), True),
    (list(range(4_010_001, 5_000_001, 1000)), False),
    ([3_990_000] + list(range(4_020_000, 5_000_001, 1000)), False),
    (list(range(4_000_000, 4_500_001, 1000)) + list(range(4_520_000, 5_000_001, 1000)), False),
    (list(range(4_000_000, 4_980_001, 1000)), False),
    ([2_999_999] + list(range(3_000_000, 5_000_001, 10_000)), False),
])
def test_optional_history_preserves_measured_coverage_and_one_second_cap(tmp_path, timestamps, passed):
    path = _write(tmp_path, _stm32_epoch("run") + _energy_capture(
        timestamps=timestamps, mutations={"pretrigger_complete": False}))
    result = validate_energy_evidence(path, "run")
    assert result["passed"] is passed, result["failure_reasons"]


@pytest.mark.parametrize("tail,passed", [([5_000_500], True), ([5_010_001], False),
                                          ([5_000_500, 5_001_000], False)])
def test_single_post_edge_sample_is_allowed_for_interpolation(tmp_path, tail, passed):
    timestamps = list(range(3_000_000, 5_000_000, 1_000)) + tail
    log = tmp_path / "subscriber.log"
    log.write_text("".join(_stm32_epoch("test") + _energy_capture(timestamps=timestamps)))
    result = validate_energy_evidence(log, "test")
    assert result["passed"] is passed
