"""A1 known-answer and failure tests. All generated captures are synthetic."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "scripts", ROOT / "tests"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from framework.run_evidence import sha256_file
from framework.timing_dataset import DatasetError, discover_inputs, export_dataset
from framework.timing_dataset_loader import load_dataset
from timing_dataset_support import EXPECTED, logical, make_run, reseal, rm2_records, tls_records


def exported(tmp_path, run, name="dataset"):
    output = tmp_path / name
    export_dataset(run_dirs=[run], output=output)
    return load_dataset(output, verify_inputs=True)


def values(data):
    return {row["metric"]: row["value_us"] for row in data.timings}


def hashes(root):
    return {str(p.relative_to(root)): (sha256_file(p), p.stat().st_mode) for p in root.rglob("*") if p.is_file()}


def test_all_eight_hand_checkable_formulas_and_raw_immutability(tmp_path):
    run = make_run(tmp_path / "run")
    before = hashes(run)
    data = exported(tmp_path, run)
    assert values(data) == EXPECTED
    assert hashes(run) == before
    assert data.runs[0]["build_number"] == "00042"
    assert data.runs[0]["repetition_index"] == 3
    assert data.runs[0]["iteration_ids"] == [0]
    for row in data.timings:
        assert row["source_records"] and row["source_sha256"] and row["logical_sha256"]
        assert row["value_us"] == row["end_us"] - row["start_us"]
        assert row["comparison_inclusion"] == "not_assessed"
    assert data.timing_view()[0]["rtfb_us"] == 200 + 1900


@pytest.mark.parametrize("marker,field,old,new,metric", [
    (2, "rtfb_us", 2100, 2101, "rtfb"), (2, "rtlb_us", 2600, 2601, "rtlb"),
    (2, "ttfb_us", 900, 901, "ttfb"), (2, "ttlb_us", 1400, 1401, "ttlb"),
    (2, "req_tfb_us", 500, 501, "req_tfb"), (2, "req_tlb_us", 1000, 1001, "req_tlb"),
    (1, "mqtt_readiness_us", 300, 301, "mqtt_readiness"),
    (4, "elapsed_us", 150, 151, "tls_handshake"),
])
def test_each_reported_scalar_is_cross_checked(tmp_path, marker, field, old, new, metric):
    records = rm2_records()
    records[marker]["text"] = records[marker]["text"].replace(f"{field}={old}", f"{field}={new}")
    data = exported(tmp_path, make_run(tmp_path / "run", records=records))
    found = {row["metric"]: row for row in data.timings}
    assert found[metric]["value_us"] is None
    assert found[metric]["reason"] == "reported_duration_mismatch"
    for name in EXPECTED.keys() - {metric}:
        assert found[name]["value_us"] == EXPECTED[name]


@pytest.mark.parametrize("field", ["start_us", "end_us", "elapsed_us"])
def test_missing_tls_boundaries_are_not_zero(tmp_path, field):
    records = rm2_records()
    records[4]["text"] = " ".join(t for t in records[4]["text"].split() if not t.startswith(field + "="))
    data = exported(tmp_path, make_run(tmp_path / "run", records=records))
    row = next(r for r in data.timings if r["metric"] == "tls_handshake")
    assert row["value_us"] is None and row["reason"]


@pytest.mark.parametrize("marker", [0, 1, 2, 3])
def test_missing_rm2_record_is_explicit(tmp_path, marker):
    records = rm2_records(); del records[marker]
    data = exported(tmp_path, make_run(tmp_path / "run", records=records))
    assert any(row["reason"] for row in data.timings if row["metric"] in ("rtfb", "ttfb"))


@pytest.mark.parametrize("changed,reason", [
    (("application_first_byte_us=1900", "application_first_byte_us=1200"), "invalid_boundary_order"),
    (("reset_origin_to_application_timebase_us=200", "reset_origin_to_application_timebase_us=201"), "reset_offset_mismatch"),
])
def test_invalid_boundary_cases(tmp_path, changed, reason):
    records = rm2_records(); records[1]["text"] = records[1]["text"].replace(*changed)
    data = exported(tmp_path, make_run(tmp_path / "run", records=records))
    row = next(r for r in data.timings if r["metric"] == "rtfb")
    assert row["value_us"] is None and row["reason"] == reason


def test_invalid_reset_handoff_only_disables_reset_metrics(tmp_path):
    records = rm2_records()
    for record in records:
        record["text"] = record["text"].replace("reset_origin_valid=1", "reset_origin_valid=0").replace("reset_metrics_valid=1", "reset_metrics_valid=0")
    records[2]["text"] = records[2]["text"].replace("rtfb_us=2100", "rtfb_us=0").replace("rtlb_us=2600", "rtlb_us=0")
    data = exported(tmp_path, make_run(tmp_path / "run", records=records))
    assert values(data) == {**EXPECTED, "rtfb": None, "rtlb": None}
    assert all(r["reason"] == "reset_origin_unavailable" for r in data.timings if r["metric"] in ("rtfb", "rtlb"))


def test_observed_zero_is_valid_and_large_timestamps_are_exact(tmp_path):
    records = tls_records()
    big = 2**53 + 7
    for record in records:
        record["text"] = record["text"].replace("start_us=1100", f"start_us={big}").replace("end_us=1250", f"end_us={big}").replace("elapsed_us=150", "elapsed_us=0")
    data = exported(tmp_path, make_run(tmp_path / "run", records=records, application="mqtt_validation", run_id="000001"))
    timing = next(r for r in data.timings if r["metric"] == "tls_handshake")
    assert timing["value_us"] == 0 and timing["start_us"] == big and type(timing["start_us"]) is int
    assert data.runs[0]["run_id"] == "000001"


def test_failed_and_unreadable_inputs_are_retained(tmp_path):
    run = make_run(tmp_path / "failed", failed=True)
    unreadable = tmp_path / "broken"; unreadable.mkdir()
    (unreadable / "manifest.json").write_text("bad JSON")
    output = tmp_path / "dataset"
    export_dataset(run_dirs=[run, unreadable, tmp_path / "missing"], output=output)
    data = load_dataset(output)
    assert len(data.runs) == 3
    failed = next(r for r in data.runs if r["run_id"])
    assert failed["execution_outcome"] == "failed" and failed["capture_acceptance"] == "incomplete"
    assert all(t["value_us"] is None and t["reason"] for t in data.timings)
    assert len(data.timing_view()) == 3


def test_repeated_input_paths_and_copies_do_not_inflate_counts(tmp_path):
    run = make_run(tmp_path / "run"); alias = tmp_path / "copy"; shutil.copytree(run, alias)
    output = tmp_path / "dataset"
    export_dataset(run_dirs=[run, run, alias], output=output)
    data = load_dataset(output)
    assert len(data.runs) == 1 and len(data.timings) == 8
    assert data.metadata["selection"]["repeated_path_count"] == 1
    assert len(data.runs[0]["input_paths"]) == 2


def test_corrupt_duplicate_copy_is_not_silently_accepted(tmp_path):
    run = make_run(tmp_path / "a"); alias = tmp_path / "z"; shutil.copytree(run, alias)
    with (alias / "mqtt-reporting-raw.ndjson").open("a") as f: f.write("tamper\n")
    output = tmp_path / "dataset"
    export_dataset(run_dirs=[run, alias], output=output)
    data = load_dataset(output)
    assert len(data.runs) == 1
    assert all(t["value_us"] is None for t in data.timings)
    assert any(i["code"] == "duplicate_copy_evidence_conflict" for i in data.issues)


def test_distinct_attempts_and_root_scoped_run_id_collisions_stay_separate(tmp_path):
    a = make_run(tmp_path / "a")
    b = make_run(tmp_path / "b", choices={"boot_uart_diagnostics": True})
    output = tmp_path / "dataset"; export_dataset(run_dirs=[a, b], output=output)
    data = load_dataset(output)
    assert len(data.runs) == 2 and len(data.timings) == 16
    assert len({r["run_key"] for r in data.runs}) == 2
    assert any(i["code"] == "run_id_reused_across_captures" for i in data.issues)
    assert all(t["value_us"] is not None for t in data.timings)


@pytest.mark.parametrize("name", ["resolved-case.json", "run-provenance.json", "mqtt-reporting-raw.ndjson"])
def test_consumed_artifact_tampering_is_detected(tmp_path, name):
    run = make_run(tmp_path / "run")
    with (run / name).open("ab") as f: f.write(b" ")
    data = exported(tmp_path, run)
    assert data.runs[0]["selected_input_status"] != "verified"
    assert not any(t["value_us"] is not None for t in data.timings)
    assert any("mismatch" in i["detail"] for i in data.issues)


def test_dataset_check_detects_input_changed_after_export(tmp_path):
    run = make_run(tmp_path / "run"); exported(tmp_path, run)
    with (run / "resolved-case.json").open("ab") as f: f.write(b" ")
    load_dataset(tmp_path / "dataset")  # independent frozen derivative remains loadable
    with pytest.raises(DatasetError, match="consumed input changed"):
        load_dataset(tmp_path / "dataset", verify_inputs=True)


@pytest.mark.parametrize("filename", ["runs.csv", "timings.csv", "issues.csv", "dataset.json"])
def test_export_hashes_are_enforced(tmp_path, filename):
    run = make_run(tmp_path / "run"); exported(tmp_path, run)
    with (tmp_path / "dataset" / filename).open("ab") as f: f.write(b" ")
    with pytest.raises(DatasetError, match="hash"):
        load_dataset(tmp_path / "dataset")


def test_missing_unrelated_capture_does_not_invalidate_timing(tmp_path):
    run = make_run(tmp_path / "run")
    p = run / "manifest.json"; manifest = json.loads(p.read_text())
    manifest["artifacts"].append({"role": "packet_capture", "requirement": "required", "path": "not-supplied.pcap", "sha256": "f"*64, "size_bytes": 10, "acquisition": {"status": "available"}})
    p.write_text(json.dumps(manifest)); reseal(run, refresh_files=False)
    data = exported(tmp_path, run)
    assert values(data) == EXPECTED
    assert data.metadata["parameters"]["capture_recheck"] == "selected_inputs_only"


def test_invalid_optional_energy_and_tls_phase_flags_do_not_gate_timings(tmp_path):
    records = rm2_records()
    records[5]["text"] = records[5]["text"].replace("overflow=0", "overflow=1").replace("incomplete=0", "incomplete=1")
    run = make_run(tmp_path / "run", records=records)
    with (run / "mqtt-reporting-raw.ndjson").open("a") as f:
        f.write(json.dumps({"topic": "pqc/instrument/energy/capture/complete", "payload": "invalid-energy-json"}) + "\n")
    reseal(run)
    assert values(exported(tmp_path, run)) == EXPECTED


@pytest.mark.parametrize("change", ["schema", "identity", "overflow", "hash", "duplicate", "missing_complete", "chunk_count"])
def test_reporting_corruption_is_unavailable_not_a_latency(tmp_path, change):
    run = make_run(tmp_path / "run")
    p = run / "mqtt-reporting-raw.ndjson"; lines = p.read_text().splitlines()
    if change == "duplicate":
        lines.insert(1, lines[0])
    elif change == "missing_complete":
        lines.pop()
    else:
        which = -1 if change in ("overflow", "hash", "chunk_count") else 0
        outer = json.loads(lines[which]); payload = outer["payload"]
        obj = json.loads(payload["payload"] if isinstance(payload, dict) else payload)
        if change == "schema": obj["schema_version"] = 99
        if change == "identity": obj["run_id"] = "other-run"
        if change == "overflow": obj["overflowed"] = True
        if change == "hash": obj["logical_sha256"] = "f" * 64
        if change == "chunk_count": obj["chunk_count"] = 10**12
        outer["payload"] = json.dumps(obj); lines[which] = json.dumps(outer)
    p.write_text("\n".join(lines) + "\n"); reseal(run)
    data = exported(tmp_path, run)
    assert all(t["value_us"] is None for t in data.timings)
    assert data.issues


def test_missing_and_failed_repeat_iterations_not_invented(tmp_path):
    epochs = [tls_records(2, repeat=True), tls_records(7, repeat=True)]
    epochs[1][-1]["text"] = epochs[1][-1]["text"].replace("tls_outcome=success", "tls_outcome=failed")
    epochs[1][0]["text"] = epochs[1][0]["text"].replace("result=1", "result=-1")
    run = make_run(tmp_path / "run", epochs=epochs, application="tls_handshake_repeat")
    data = exported(tmp_path, run)
    assert [t["iteration_id"] for t in data.timings] == [2, 7]
    assert [t["value_us"] for t in data.timings] == [150, None]
    assert data.runs[0]["observed_iteration_count"] == 2
    assert data.timings[1]["operation_outcome"] == "failed"


def test_final_energy_epoch_is_not_a_handshake_attempt(tmp_path):
    epochs = [tls_records(0, repeat=True), tls_records(1, repeat=True), [logical("PQC_ENERGY_BOUNDARY scope=experiment s0_us=1 s1_us=2", context="energy_boundary")]]
    data = exported(tmp_path, make_run(tmp_path / "run", epochs=epochs, application="tls_handshake_repeat"))
    assert len(data.timings) == 2 and data.runs[0]["observed_stream_count"] == 3


def test_duplicate_iteration_id_is_explicit(tmp_path):
    data = exported(tmp_path, make_run(tmp_path / "run", epochs=[tls_records(1, repeat=True), tls_records(1, repeat=True)], application="tls_handshake_repeat"))
    assert len(data.timings) == 2
    assert all(t["reason"] == "duplicate_iteration_identity" for t in data.timings)


def test_aggregate_only_does_not_manufacture_iterations(tmp_path):
    records = [logical("PQC_TLS_PHASE name=server_hello count=10 total_us=1000")]
    data = exported(tmp_path, make_run(tmp_path / "run", records=records, application="tls_handshake_repeat"))
    assert len(data.timings) == 1 and data.timings[0]["iteration_id"] is None
    assert data.timings[0]["value_us"] is None
    assert data.timings[0]["scope"] == "framework_run"


@pytest.mark.parametrize("flag,excluded", [("boot_stack_profiling", set(EXPECTED)), ("boot_uart_diagnostics", {"rtfb", "rtlb"})])
def test_timing_policy_exclusions_are_separate_from_validity(tmp_path, flag, excluded):
    data = exported(tmp_path, make_run(tmp_path / "run", choices={flag: True}))
    assert values(data) == EXPECTED
    assert {t["metric"] for t in data.timings if t["timing_policy_exclusion"]} == excluded


def test_reconstructed_real_marker_excerpt(tmp_path):
    fixture = json.loads((ROOT / "tests/fixtures/timing_dataset/ready_metrics_2_excerpt.json").read_text())
    assert fixture["fixture_kind"] == "reconstructed_parser_test_excerpt_not_original_sealed_capture"
    run = make_run(tmp_path / "run", records=fixture["records"], transfer=fixture["transfer"], run_id="synthetic-reconstructed-excerpt")
    assert values(exported(tmp_path, run)) == fixture["expected_us"]


def test_repeated_export_is_byte_equivalent(tmp_path):
    run = make_run(tmp_path / "run")
    exported(tmp_path, run, "first"); exported(tmp_path, run, "second")
    assert {p.name: p.read_bytes() for p in (tmp_path / "first").iterdir()} == {p.name: p.read_bytes() for p in (tmp_path / "second").iterdir()}


@pytest.mark.parametrize("kind", ["unfinalized", "bad_seal", "unknown_schema", "identity_conflict"])
def test_invalid_capture_or_identity_is_diagnosed(tmp_path, kind):
    run = make_run(tmp_path / "run")
    p = run / "manifest.json"; m = json.loads(p.read_text())
    if kind == "unfinalized": m["final_index"]["status"] = "pending"
    elif kind == "bad_seal": m["capture_acceptance"]["accepted"] = False
    elif kind == "unknown_schema": m["schema"]["version"] = 99
    elif kind == "identity_conflict": m["configuration"]["configuration_identity"] = "f"*64
    p.write_text(json.dumps(m))
    if kind == "identity_conflict": reseal(run)
    data = exported(tmp_path, run)
    assert data.issues and not any(t["value_us"] is not None for t in data.timings)


def test_no_secret_values_or_raw_payloads_exported(tmp_path):
    run = make_run(tmp_path / "run")
    p = run / "run-provenance.json"; d = json.loads(p.read_text())
    d["records"]["private_key"] = "DO_NOT_EXPORT_PRIVATE_KEY_CONTENT"
    d["records"]["tls_key_log"] = "DO_NOT_EXPORT_TLS_KEYLOG_CONTENT"
    p.write_text(json.dumps(d)); reseal(run)
    (run / ".env").write_text("DO_NOT_EXPORT_WIFI_PASSWORD")
    exported(tmp_path, run)
    text = "\n".join(p.read_text() for p in (tmp_path / "dataset").iterdir())
    assert "DO_NOT_EXPORT" not in text and '"data_hex"' not in text


def test_discovery_prunes_preparations_and_raw_children(tmp_path):
    selected = make_run(tmp_path / "results/campaign/runs/run")
    make_run(tmp_path / "results/campaign/preparations/prep")
    make_run(tmp_path / "results/analysis/old")
    directories, _ = discover_inputs(results_root=tmp_path / "results")
    assert directories == [selected]


def test_refuse_output_over_raw_existing_and_symlink_paths(tmp_path):
    run = make_run(tmp_path / "run")
    with pytest.raises(DatasetError): export_dataset(run_dirs=[run], output=run / "analysis/a1")
    exported(tmp_path, run)
    with pytest.raises(DatasetError): exported(tmp_path, run)
    symlink = tmp_path / "link"; symlink.symlink_to(run, target_is_directory=True)
    data = exported(tmp_path, symlink, "symlink-dataset")
    assert data.runs[0]["manifest_status"] != "verified"


def test_unknown_marker_schema_and_duplicate_fields_rejected(tmp_path):
    records = rm2_records(); records[0]["text"] = records[0]["text"].replace("schema=3", "schema=99")
    data = exported(tmp_path, make_run(tmp_path / "run", records=records))
    assert all(r["value_us"] is None for r in data.timings)
    records = rm2_records(); records[0]["text"] += " counter_hz=1000000"
    data = exported(tmp_path, make_run(tmp_path / "run2", records=records), "dataset2")
    assert all(r["value_us"] is None for r in data.timings)


def test_wrong_logical_context_is_not_accepted(tmp_path):
    records = rm2_records(); records[0]["context"] = "wrong_context"
    data = exported(tmp_path, make_run(tmp_path / "run", records=records))
    assert all(t["value_us"] is None for t in data.timings)


def test_analysis_calls_no_gateway_process_or_capture_mutator(tmp_path, monkeypatch):
    run = make_run(tmp_path / "run")
    import subprocess
    import socket
    from framework import run_evidence
    def forbidden(*args, **kwargs):
        raise AssertionError("offline analysis invoked forbidden side effect")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    for name in ("finalize_manifest", "verify_and_freeze_raw_artifacts", "verify_retained_files", "register_derived"):
        monkeypatch.setattr(run_evidence, name, forbidden)
    assert values(exported(tmp_path, run)) == EXPECTED


def test_negative_validation_capture_class_remains_distinct(tmp_path):
    run = make_run(tmp_path / "run", failed=True)
    p = run / "manifest.json"
    manifest = json.loads(p.read_text())
    manifest["capture_contract"]["experiment_class"] = "secure_boot_negative_validation"
    p.write_text(json.dumps(manifest)); reseal(run)
    data = exported(tmp_path, run)
    assert data.runs[0]["capture_class"] == "secure_boot_negative_validation"
    assert data.timing_view()[0]["capture_class"] == "secure_boot_negative_validation"
    assert data.timing_view()[0]["execution_outcome"] == "failed"
    assert not any(t["value_us"] is not None for t in data.timings)


@pytest.mark.parametrize('conflict',[False,True])
def test_signed_deployment_is_distinct_from_linked_build_hash(tmp_path, conflict):
    from framework.run_evidence import register_artifact
    run = make_run(tmp_path/'run')
    image = run/'signed.bin'; image.write_bytes(b'synthetic signed application')
    fw_hash = sha256_file(image)
    path = run/'manifest.json'; manifest = json.loads(path.read_text())
    register_artifact(manifest,result_dir=run,role='signed_application',path=image,stage='synthetic',tool=__name__)
    path.write_text(json.dumps(manifest))
    path = run/'run-provenance.json'; value = json.loads(path.read_text())
    value['records'].update(firmware={'sha256':fw_hash,'evidence_role':'signed_application'},
        preparation={'manifest':'results/builds/42/manifest.json','firmware_sha256':'a'*64},
        build_reference={'record_manifest':'results/builds/42/manifest.json','artifact_sha256':('b' if conflict else 'a')*64})
    path.write_text(json.dumps(value)); reseal(run)
    result = exported(tmp_path,run)
    assert (result.runs[0]['selected_input_status']=='verified') is (not conflict)
    if not conflict:
        assert result.runs[0]['firmware_sha256'] == fw_hash
