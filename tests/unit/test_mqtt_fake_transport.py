from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def load_fake_transport_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "framework" / "mqtt_fake_transport.py"
    spec = importlib.util.spec_from_file_location("mqtt_fake_transport", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fake_mqtt_transport_records_successful_connect_publish_disconnect():
    fake_transport = load_fake_transport_module()

    scenario = fake_transport.FakeMqttTransportScenario()
    result = fake_transport.run_fake_mqtt_transport_scenario(scenario)

    assert result["model_phase"] == "phase_m3_fake_no_network_transport_harness"
    assert result["evidence_label"] == "fake/no-network transport evidence"
    assert result["simulated"] is True
    assert [event["operation"] for event in result["events"]] == [
        "connect",
        "publish",
        "disconnect",
    ]
    assert result["summary"]["control_flow_success"] is True
    assert result["evidence_boundaries"]["claims_mqtt_runtime_success"] is False
    assert result["evidence_boundaries"]["claims_network_success"] is False


def test_fake_mqtt_transport_records_publish_timeout_without_success_claims():
    fake_transport = load_fake_transport_module()

    scenario = fake_transport.FakeMqttTransportScenario(
        scenario_id="publish_timeout",
        connect_outcome="success",
        publish_outcome="timeout",
        disconnect_outcome="success",
    )
    result = fake_transport.run_fake_mqtt_transport_scenario(scenario)

    assert result["summary"]["timeout_operations"] == ["publish"]
    assert result["summary"]["control_flow_success"] is False
    assert result["evidence_boundaries"]["claims_mqtt_runtime_success"] is False


def test_fake_mqtt_transport_records_skipped_publish_after_connect_failure():
    fake_transport = load_fake_transport_module()

    scenario = fake_transport.FakeMqttTransportScenario(
        scenario_id="connect_failure",
        connect_outcome="failure",
    )
    result = fake_transport.run_fake_mqtt_transport_scenario(scenario)

    assert result["events"][0]["operation"] == "connect"
    assert result["events"][0]["outcome"] == "failure"
    assert result["events"][1]["operation"] == "publish"
    assert result["events"][1]["attempted"] is False
    assert result["events"][2]["operation"] == "disconnect"
    assert result["events"][2]["attempted"] is False
    assert result["summary"]["failed_operations"] == ["connect"]


def test_fake_mqtt_transport_records_reconnect_attempts():
    fake_transport = load_fake_transport_module()

    scenario = fake_transport.FakeMqttTransportScenario(
        scenario_id="reconnect_timeout",
        reconnect_outcome="timeout",
        reconnect_attempts=2,
    )
    result = fake_transport.run_fake_mqtt_transport_scenario(scenario)

    reconnect_events = [event for event in result["events"] if event["operation"] == "reconnect"]
    assert [event["attempt"] for event in reconnect_events] == [1, 2]
    assert result["summary"]["timeout_operations"] == ["reconnect", "reconnect"]
    assert result["summary"]["reconnect_attempts"] == 2


def test_fake_mqtt_transport_rejects_unknown_outcome():
    fake_transport = load_fake_transport_module()

    scenario = fake_transport.FakeMqttTransportScenario(connect_outcome="socket")

    with pytest.raises(fake_transport.FakeMqttTransportConfigError, match="connect_outcome"):
        fake_transport.run_fake_mqtt_transport_scenario(scenario)
