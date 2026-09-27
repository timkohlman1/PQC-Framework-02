"""Protocol acceptance, disabled profile isolation, and bounded control contracts."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
import yaml

from framework.energy_evidence import FIELDS, COUNTERS, validate_energy_evidence
from framework.energy_gateway import healthy
from framework.energy_capture import EnergyCapture
from framework.config_resolver import ConfigResolver
from framework.result_collector import _parse_raw_stream

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "a" * 32


def records(intervals=1, shared=False):
    session = dict(record="session", schema=3, source="energy", run_id="run", association_token=TOKEN,
        clock_hz=1000000, interval_count=intervals, sync_gpio=11, alert_gpio=12,
        calibration_id="empirical_dmm_reference_loads_2026-09-25",
        calibration_status="empirical_two_load_current_scaling", nominal_shunt_ohms=.015,
        effective_shunt_ohms=.029, acquisition_mode="alert_triggered_bus_shunt",
        bus_conversion_us=50, shunt_conversion_us=50, averaging=1, i2c_hz=400000,
        gap_limit_us=10000, analysis="offline_only", sample_encoding="array_v1",
        collection_acquisition="paused", sample_fields=FIELDS, firmware_sha256="b"*64,
        session_id="c"*32, sample_record_bytes=64, ring_capacity_samples=114688,
        ring_allocated_bytes=7*1024*1024, psram_reserve_bytes=512*1024, psram_total_bytes=8*1024*1024)
    energy, stm = [session], []
    for i in range(intervals):
        start = 1000 + i*(1000 if shared else 10000)
        seq = 100 + i*(1 if shared else 10)
        energy.append(dict(record="interval", interval_index=i, interval_sequence=i+10,
            e0_us=start+100, e1_us=start+900, start_sample_sequence=seq, end_sample_sequence=seq+1,
            stm32_boundary_source="stm32.energy_boundary", run_association="collector_token",
            **dict.fromkeys(COUNTERS, 0)))
        energy.extend([[i,j,seq+j,start+j*1000,j*1000-100,5.,.1,.5,150,0,2] for j in range(2)])
        stm.append([dict(source="stm32", iteration=i, context="energy_boundary",
            text=f"PQC_ENERGY_BOUNDARY interval_index={i} s0_us={start+5000} s1_us={start+5800} valid=1 clock=TIM2 counter_hz=1000000 timestamp_convention=before_gpio_write")])
    return energy, stm


def wire(energy, stm):
    messages = []
    for source, epochs in (("stm32", stm), ("energy", [energy])):
        prefix = "pqc/result/stm32" if source == "stm32" else "pqc/instrument/energy"
        for epoch in epochs:
            raw = b"".join(json.dumps(r).encode()+b"\n" for r in epoch)
            # Deliberately split inside a JSON record, not at a newline boundary.
            parts = [raw[:37], raw[37:]]
            for seq, part in enumerate(parts):
                payload = dict(type="chunk", source=source, run_id="run", sequence=seq)
                payload["data_b64" if source == "energy" else "data_hex"] = base64.b64encode(part).decode() if source == "energy" else part.hex()
                messages.append(dict(topic=f"{prefix}/run/chunk", payload=payload))
            completion = dict(type="complete", source=source, run_id="run", logical_sha256=hashlib.sha256(raw).hexdigest(),
                logical_bytes=len(raw), record_count=len(epoch), chunk_count=2, overflowed=False, dropped_record_count=0)
            if source == "energy":
                completion.update(sample_count=sum(isinstance(r,list) for r in epoch), interval_count=len(stm), acquisition_status="raw")
            messages.append(dict(topic=f"{prefix}/run/complete", payload=completion))
    return messages


def validate(tmp_path, messages, n=1):
    path = tmp_path/"raw.ndjson"
    path.write_text("".join(json.dumps(m)+"\n" for m in messages))
    return validate_energy_evidence(path, "run", TOKEN, n)


@pytest.mark.parametrize("shared", [False, True])
def test_accepts_per_interval_sequences_and_shared_bracketing_samples(tmp_path, shared):
    messages = wire(*records(2, shared))
    assert validate(tmp_path, messages, 2)["passed"]
    result = _parse_raw_stream(tmp_path/"raw.ndjson", run_id="run", expected_sources=("stm32","energy"), expected_completion_counts={"stm32":2,"energy":1})
    assert result.passed


@pytest.mark.parametrize("mutation", ["token", "calibration", "gap", "counter", "bracket", "boundary", "sequence", "float_sequence", "nan", "missing_epoch", "stm32_record"])
def test_rejects_invalid_raw_acquisition_after_valid_transfer_hash(tmp_path, mutation):
    energy, stm = records()
    if mutation == "token": energy[0]["association_token"] = "d"*32
    if mutation == "calibration": energy[0]["effective_shunt_ohms"] = .015
    if mutation == "gap": energy[-1][3] += 20000; energy[-1][4] += 20000
    if mutation == "counter": energy[1]["i2c_errors"] = 1
    if mutation == "bracket": energy[2][3] += 200; energy[2][4] += 200
    if mutation == "boundary": stm[0][0]["text"] = stm[0][0]["text"].replace("valid=1", "valid=0")
    if mutation == "sequence": energy[-1][2] += 1
    if mutation == "float_sequence": energy[-1][2] = float(energy[-1][2])
    if mutation == "nan": energy[-1][5] = float("nan")
    if mutation == "missing_epoch": stm = []
    if mutation == "stm32_record": stm = [[[]]]
    assert not validate(tmp_path, wire(energy, stm))["passed"]


@pytest.mark.parametrize("mutation", ["hash", "bytes", "count", "duplicate", "missing", "terminal", "wrong_run", "bad_base64", "stm32_overflow"])
def test_rejects_broken_or_terminal_transfer(tmp_path, mutation):
    messages = wire(*records())
    if mutation == "hash": messages[-1]["payload"]["logical_sha256"] = "0"*64
    if mutation == "bytes": messages[-1]["payload"]["logical_bytes"] += 1
    if mutation == "count": messages[-1]["payload"]["record_count"] += 1
    if mutation == "duplicate": messages.insert(-1, messages[-2])
    if mutation == "missing": messages.pop()
    if mutation == "terminal": messages[-1]["payload"].update(type="error", status="capacity_exceeded")
    if mutation == "wrong_run": messages[-1]["payload"]["run_id"] = "other"
    if mutation == "bad_base64": messages[-2]["payload"]["data_b64"] = "?!"
    if mutation == "stm32_overflow": messages[2]["payload"]["overflowed"] = True
    assert not validate(tmp_path, messages)["passed"]


def test_readiness_requires_exact_fresh_healthy_token():
    status = dict(source="energy", status="ready", association_token=TOKEN, sensor_online=True,
        sensor_valid=True, acquisition="continuous", status_timestamp_us=200000, sample_timestamp_us=199000,
        ring_capacity_samples=10, ring_used_samples=1, sample_record_bytes=64, ring_allocated_bytes=640)
    assert healthy(status, TOKEN)
    for changes in ({"association_token":"b"*32}, {"sample_timestamp_us":100000}, {"sensor_valid":False},
                    {"acquisition":"paused_for_collection"}, {"ring_used_samples":0}, {"ring_allocated_bytes":1}):
        assert not healthy({**status, **changes}, TOKEN)


def energy_case(tmp_path, workload="ready_metrics"):
    config = yaml.safe_load((ROOT/"configs/campaigns/baseline.yaml").read_text())
    config.update(instruments={"energy":"esp32_ina228"}, workload=workload)
    path = tmp_path/"energy.yaml"
    path.write_text(yaml.safe_dump(config))
    resolver = ConfigResolver(ROOT)
    case = resolver.expand_campaign(path)[0]
    return case, resolver.to_legacy_bundle(case)


def test_energy_changes_firmware_identity_not_experiment_choices(tmp_path):
    case, bundle = energy_case(tmp_path)
    baseline = ConfigResolver(ROOT).expand_campaign("baseline")[0]
    assert case["choices"] == baseline["choices"]
    assert case["provenance"]["firmware_identity"] != baseline["provenance"]["firmware_identity"]
    assert bundle["experiment"]["instruments"]["energy"]


def test_control_lifecycle_uses_plain_token_and_bounded_framework_gateway(tmp_path):
    _, bundle = energy_case(tmp_path)
    calls = []
    def runner(command, **kwargs):
        import shlex
        args = json.loads(shlex.split(command[-1])[-1]); calls.append(args)
        assert kwargs["timeout"] <= 315
        return subprocess.CompletedProcess(command, 0, "ack\n", "")
    capture = EnergyCapture(bundle, tmp_path, runner)
    assert capture.associate() and capture.collect("/tmp/report.ndjson") and capture.cleanup()
    assert [c["action"] for c in calls] == ["cleanup", "associate", "collect", "cleanup"]
    assert calls[1]["token"] == calls[2]["token"] == capture.token
    assert calls[0]["token"] != calls[-1]["token"] != capture.token


def test_failed_cleanup_prevents_association(tmp_path):
    _, bundle = energy_case(tmp_path)
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, 1)
    assert not EnergyCapture(bundle, tmp_path, runner).associate()
    assert len(calls) == 1


def test_cancelled_collection_returns_failure_for_finally_cleanup(tmp_path):
    _, bundle = energy_case(tmp_path)
    def runner(*args, **kwargs):
        raise KeyboardInterrupt()
    capture = EnergyCapture(bundle, tmp_path, runner)
    assert not capture.collect("/tmp/raw")
    assert "failed" in (tmp_path/"energy-collect.log").read_text()


def test_unsupported_reporting_warns_and_removes_energy(tmp_path, monkeypatch):
    from dataclasses import replace
    original = ConfigResolver.load_profile
    def load(self, domain, ident):
        profile = original(self, domain, ident)
        if domain == "workload":
            profile = replace(profile, data={**profile.data, "evidence": {"deferred_reporting":False}})
        return profile
    monkeypatch.setattr(ConfigResolver, "load_profile", load)
    with pytest.warns(UserWarning, match="Energy measurement disabled"):
        case, bundle = energy_case(tmp_path)
    assert not case["selections"].get("instruments")
    assert not bundle["experiment"].get("instruments")


def test_sync_faults_between_intervals_are_rejected(tmp_path):
    _, bundle = energy_case(tmp_path)
    capture = EnergyCapture(bundle, tmp_path)
    capture.readiness = dict(sync_unexpected_rising=4, sync_orphan_falling=2,
                            sync_queue_drops=0, sync_processed_rising=20, sync_processed_falling=20)
    capture.resumed_status = {**capture.readiness, "sync_processed_rising":21,"sync_processed_falling":21}
    assert capture.sync_valid()
    capture.resumed_status["sync_unexpected_rising"] += 1
    assert not capture.sync_valid()


def test_partial_energy_retention_does_not_invalidate_stm32_artifact(tmp_path):
    from framework.manifest import create_result_folder, update_manifest, finalize_run_evidence
    _, bundle = energy_case(tmp_path)
    folder, _ = create_result_folder(bundle, tmp_path/"results")
    (folder/"mqtt-reporting-raw.ndjson").write_text("retained incomplete capture\n")
    update_manifest(folder/"manifest.json", {"result_collection": {
        "status":"invalid", "raw_stream":"mqtt-reporting-raw.ndjson", "source_integrity":{"stm32":{"passed":True}}},
        "energy_capture":{"passed":False}})
    final = finalize_run_evidence(folder/"manifest.json")
    roles = {a["role"]:a for a in final["artifacts"]}
    assert roles["stm32_result_stream"]["acquisition"]["status"] == "available"
    assert roles["energy_result_stream"]["acquisition"]["status"] == "invalid"
    assert roles["energy_result_stream"]["sha256"]
    assert not final["capture_acceptance"]["accepted"]


def test_preparation_contract_requires_deployment_but_not_runtime(tmp_path):
    from framework.run_evidence import build_capture_contract
    _, bundle = energy_case(tmp_path)
    contract = build_capture_contract(bundle, operation="prepare_only")
    required = {i["role"] for i in contract["items"] if i["requirement"] == "required"}
    assert {"application_elf", "build_log", "deployment_provenance", "flash_log"} <= required
    assert not {"energy_result_stream", "stm32_result_stream", "packet_capture"} & required
