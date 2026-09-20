"""Source-independent evidence-contract checks; never access gateway or STM32."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _validator():
    path = ROOT / "tests/hardware/test_mqtt_plaintext_st67_e2e_hw.py"
    spec = importlib.util.spec_from_file_location("mqtt_hardware_evidence_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


@pytest.fixture
def evidence(tmp_path):
    run = tmp_path / "hardware-run-1"
    run.mkdir()
    roles = {
        "observer_evidence": "mqtt-broker-message-evidence.json",
        "experiment_broker_log": "mqtt-broker-log.log",
        "mqtt_publisher_log": "mqtt-publisher.log",
        "mqtt_subscriber_log": "mqtt-subscriber.log",
        "mqtt_subscriber_raw_log": "mqtt-subscriber-raw.log",
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
    _write_json(run / "mqtt-broker-message-evidence.json", {
        "available": True, "passed": True, "required_for_pass": True, "collection_return_code": 0,
        "stm32_connected": True, "stm32_subscribe_received": True, "stm32_suback_sent": True,
        "command_publish_received": True, "command_publish_delivered": True,
        "response_publish_received": True, "response_publish_delivered": True,
    })
    _write_json(run / "mqtt-subscriber.log", {
        "marker_present": True, "subscriber_rc": 0, "response_matched": "1",
        "expected_response_count": 2, "response_count": 2,
    })
    logical = b'{"event":"mqtt_connected"}\n{"event":"mqtt_response"}\n'
    digest = hashlib.sha256(logical).hexdigest()
    chunks = [logical[:25], logical[25:]]
    def envelope(topic, payload):
        return json.dumps({"topic": topic, "payload": json.dumps(payload)})
    lines = [envelope(f"pqc/result/stm32/{run.name}/chunk", {
        "type": "chunk", "source": "stm32", "run_id": run.name,
        "sequence": seq, "data_hex": chunk.hex(),
    }) for seq, chunk in enumerate(chunks)]
    lines.append(envelope(f"pqc/result/stm32/{run.name}/complete", {
        "type": "complete", "source": "stm32", "run_id": run.name,
        "chunk_count": 2, "record_count": 2, "logical_bytes": len(logical),
        "logical_sha256": digest,
    }))
    (run / "mqtt-reporting-raw.ndjson").write_text("\n".join(lines) + "\n", encoding="utf-8")
    stm32 = {
        "passed": True, "completion_count": 1,
        "observed_chunk_count": 2, "expected_chunk_count": 2,
        "observed_record_count": 2, "expected_record_count": 2,
        "observed_sha256": digest, "expected_sha256": digest,
    }
    _write_json(run / "mqtt-reporting-collector.log", {
        "run_id": run.name, "expected_sources": ["stm32"],
        "stop_return_code": 0, "copy_return_code": 0,
        "validation": {
            "passed": True, "failure_reasons": [], "completion_count": 1,
            "duplicate_sequences": [], "missing_sequences": [],
            "observed_sha256": digest, "source_results": {"stm32": stm32},
        },
    })
    # Deliberately do not create uart.log: these functional checks must work
    # for full, minimal and off UART reporting.
    return run


def test_broker_and_reporting_accept_complete_evidence_without_uart(evidence):
    module = _validator()
    module._assert_broker_evidence(evidence)
    module._assert_reporting_evidence(evidence)


def test_broker_rejects_missing_stm32_publish(evidence):
    module = _validator()
    path = evidence / "mqtt-broker-message-evidence.json"
    broker = json.loads(path.read_text(encoding="utf-8"))
    broker["response_publish_delivered"] = False
    _write_json(path, broker)
    with pytest.raises(AssertionError, match="response_publish_delivered"):
        module._assert_broker_evidence(evidence)


def test_reporting_rejects_truncated_raw_stream_even_if_collector_log_says_pass(evidence):
    module = _validator()
    raw = evidence / "mqtt-reporting-raw.ndjson"
    raw.write_text(raw.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="invalid retained STM32 result stream"):
        module._assert_reporting_evidence(evidence)


def test_reporting_rejects_evidence_from_different_run(evidence):
    module = _validator()
    path = evidence / "mqtt-reporting-collector.log"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["run_id"] = "another-run"
    _write_json(path, data)
    with pytest.raises(AssertionError):
        module._assert_reporting_evidence(evidence)


def test_reporting_rejects_missing_indexed_artifact(evidence):
    module = _validator()
    (evidence / "mqtt-reporting-raw.ndjson").unlink()
    with pytest.raises(AssertionError, match="missing or out-of-run"):
        module._assert_reporting_evidence(evidence)
