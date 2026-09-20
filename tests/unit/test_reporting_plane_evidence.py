"""Pure evidence-contract checks for experiment-veth impairment and STM32 reporting."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _validator():
    path = ROOT / "tests/hardware/test_reporting_plane_isolation_hw.py"
    spec = importlib.util.spec_from_file_location("reporting_plane_hardware_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, data: dict):
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


@pytest.fixture
def evidence(tmp_path):
    run = tmp_path / "unique-reporting-run"
    run.mkdir()
    roles = {
        "network_condition_record": "gateway-network-degradation.log",
        "stm32_result_stream": "mqtt-reporting-raw.ndjson",
        "reporting_broker_log": "mqtt-broker-reporting-log.log",
        "run_provenance": "run-provenance.json",
    }
    for name in roles.values():
        (run / name).write_text("retained\n", encoding="utf-8")
    _write_json(run / "manifest.json", {
        "execution_outcome": {"status": "completed", "failure_stage": "none", "result": "baseline_run_passed"},
        "capture_acceptance": {"accepted": True},
        "final_index": {"status": "finalized"},
        "run": {"state": "finalized"},
        "artifacts": [{"role": role, "path": name} for role, name in roles.items()],
    })
    logical = b'{"event":"mqtt_response"}\n'
    digest = hashlib.sha256(logical).hexdigest()
    def envelope(topic, payload):
        return json.dumps({"topic": topic, "payload": json.dumps(payload)})
    records = [
        envelope(f"pqc/result/stm32/{run.name}/chunk", {
            "type": "chunk", "source": "stm32", "run_id": run.name,
            "sequence": 0, "data_hex": logical.hex(),
        }),
        envelope(f"pqc/result/stm32/{run.name}/complete", {
            "type": "complete", "source": "stm32", "run_id": run.name,
            "chunk_count": 1, "record_count": 1, "logical_bytes": len(logical),
            "logical_sha256": digest,
        }),
    ]
    (run / "mqtt-reporting-raw.ndjson").write_text("\n".join(records) + "\n", encoding="utf-8")
    _write_json(run / "mqtt-reporting-collector.log", {
        "run_id": run.name, "expected_sources": ["stm32"],
        "stop_return_code": 0, "copy_return_code": 0,
        "validation": {
            "passed": True, "failure_reasons": [], "completion_count": 1,
            "observed_sha256": digest,
            "source_results": {"stm32": {
                "passed": True, "completion_count": 1, "missing_sequences": [], "duplicate_sequences": [],
                "observed_chunk_count": 1, "expected_chunk_count": 1,
                "observed_record_count": 1, "expected_record_count": 1,
                "observed_sha256": digest, "expected_sha256": digest,
            }},
        },
    })
    profile = {"impairment": {
        "enabled": True, "management_safe": True, "mtu": 1200,
        "rate_kbit": 100000, "loss_percent": 0, "rtt_ms": 0,
    }}
    apply = (
        "Apply command: ssh gateway 'service=mqtt-classical; ifb=ifb-pqc0; "
        "sudo tc filter add action mirred egress redirect dev $ifb; "
        "link set dev eth0 mtu 1200; PQC_APPLIED_STATE_BEGIN'\n"
        "Return code: 0\n"
        "PQC_EXPERIMENT_VETH=veth12345\nPQC_EXPERIMENT_CONTAINER_PID=1234\n"
        "PQC_ORIGINAL_MTU=1500\nPQC_CONTAINER_ORIGINAL_MTU=1500\n"
        "PQC_APPLIED_STATE_BEGIN\n"
        "123: veth12345@if2: <UP> mtu 1200 qdisc netem state UP\n"
        "qdisc netem a: root rate 100Mbit\n"
        "qdisc netem b: root rate 100Mbit\n"
        "PQC_APPLIED_STATE_END\n"
    )
    cleanup = (
        "Cleanup command: ssh gateway 'qdisc del dev $iface root; "
        "qdisc del dev $iface ingress; qdisc del dev $ifb root; "
        "link set dev $iface mtu 1500; link set dev eth0 mtu 1500; "
        "link del dev $ifb type ifb; [ \"$actual_mtu\" = \"1500\" ]'\n"
        "Cleanup return code: 0\n"
    )
    (run / "gateway-network-degradation.log").write_text(apply + cleanup, encoding="utf-8")
    return run, profile


def test_valid_impairment_and_reporting_evidence_without_uart(evidence):
    run, profile = evidence
    module = _validator()
    module._assert_impairment(run, "mtu", profile)
    module._assert_reporting(run)


def test_rejects_wrong_experiment_mtu(evidence):
    run, profile = evidence
    profile["impairment"]["mtu"] = 1100
    with pytest.raises(AssertionError, match="MTU"):
        _validator()._assert_impairment(run, "mtu", profile)


def test_rejects_failed_cleanup(evidence):
    run, profile = evidence
    path = run / "gateway-network-degradation.log"
    path.write_text(path.read_text().replace("Cleanup return code: 0", "Cleanup return code: 1"))
    with pytest.raises(AssertionError, match="cleanup failed"):
        _validator()._assert_impairment(run, "mtu", profile)


def test_rejects_wrong_broker_boundary(evidence):
    run, profile = evidence
    path = run / "gateway-network-degradation.log"
    path.write_text(path.read_text().replace("service=mqtt-classical", "service=mqtt-reporting"))
    with pytest.raises(AssertionError, match="experiment broker boundary"):
        _validator()._assert_impairment(run, "mtu", profile)


def test_rejects_tls_broker_boundary_for_plaintext_case(evidence):
    run, profile = evidence
    path = run / "gateway-network-degradation.log"
    path.write_text(path.read_text().replace("service=mqtt-classical;", "service=mqtt-classical-server-auth;"))
    with pytest.raises(AssertionError, match="experiment broker boundary"):
        _validator()._assert_impairment(run, "mtu", profile)


def test_rejects_incomplete_reporting_stream(evidence):
    run, _ = evidence
    path = run / "mqtt-reporting-raw.ndjson"
    path.write_text(path.read_text().splitlines()[0] + "\n")
    with pytest.raises(AssertionError, match="invalid retained STM32 stream"):
        _validator()._assert_reporting(run)


def test_rejects_reporting_from_other_run(evidence):
    run, _ = evidence
    path = run / "mqtt-reporting-collector.log"
    data = json.loads(path.read_text())
    data["run_id"] = "wrong-run"
    _write_json(path, data)
    with pytest.raises(AssertionError):
        _validator()._assert_reporting(run)


def test_rejects_missing_bidirectional_impairment(evidence):
    run, profile = evidence
    path = run / "gateway-network-degradation.log"
    data = path.read_text()
    path.write_text(data.replace("qdisc netem b: root rate 100Mbit", "qdisc fq_codel b: root"))
    with pytest.raises(AssertionError, match="rate configuration differs|bidirectional netem"):
        _validator()._assert_impairment(run, "mtu", profile)


def test_rejects_missing_indexed_network_record(evidence):
    run, profile = evidence
    (run / "gateway-network-degradation.log").unlink()
    with pytest.raises(AssertionError, match="missing or out-of-run"):
        _validator()._assert_impairment(run, "mtu", profile)
