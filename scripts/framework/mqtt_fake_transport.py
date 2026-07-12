"""Deterministic fake/no-network MQTT transport harness.

The harness models MQTT client control-flow outcomes without sockets, TLS,
broker access, gateway access, UART access, or STM32 hardware. Evidence from
this module is simulated fake-transport evidence only and must not be treated as
real MQTT, TLS, broker, network, or STM32 runtime success.
"""

from __future__ import annotations

from typing import Any

FAKE_MQTT_TRANSPORT_SCHEMA_VERSION = 1
FAKE_MQTT_TRANSPORT_MODEL_PHASE = "phase_m3_fake_no_network_transport_harness"
FAKE_MQTT_EVIDENCE_CLASS = "fake_no_network"
FAKE_MQTT_TRANSPORT_BACKEND = "fake_no_network"
FAKE_MQTT_EVIDENCE_LABEL = "fake/no-network transport evidence"
FAKE_MQTT_VALID_OUTCOMES = {"success", "failure", "timeout"}


class FakeMqttTransportConfigError(ValueError):
    """Raised when a fake MQTT transport scenario is invalid."""


class FakeMqttTransportScenario:
    """Configuration for one deterministic fake/no-network MQTT scenario."""

    def __init__(
        self,
        *,
        scenario_id: str = "connect_publish_disconnect_success",
        connect_outcome: str = "success",
        publish_outcome: str = "success",
        disconnect_outcome: str = "success",
        reconnect_outcome: str = "success",
        reconnect_attempts: int = 0,
        topic: str = "pqc/fake/no-network",
        message: str = "fake MQTT payload",
    ) -> None:
        self.scenario_id = scenario_id
        self.connect_outcome = connect_outcome
        self.publish_outcome = publish_outcome
        self.disconnect_outcome = disconnect_outcome
        self.reconnect_outcome = reconnect_outcome
        self.reconnect_attempts = reconnect_attempts
        self.topic = topic
        self.message = message


def _validate_outcome(name: str, value: str) -> None:
    if value not in FAKE_MQTT_VALID_OUTCOMES:
        allowed = ", ".join(sorted(FAKE_MQTT_VALID_OUTCOMES))
        raise FakeMqttTransportConfigError(f"{name} must be one of: {allowed}")


def validate_fake_mqtt_transport_scenario(scenario: FakeMqttTransportScenario) -> None:
    """Validate a fake/no-network MQTT scenario.

    Validation is local and deterministic. It does not touch network resources.
    """

    if not isinstance(scenario.scenario_id, str) or not scenario.scenario_id.strip():
        raise FakeMqttTransportConfigError("scenario_id must be a non-empty string")
    if not isinstance(scenario.reconnect_attempts, int) or scenario.reconnect_attempts < 0:
        raise FakeMqttTransportConfigError("reconnect_attempts must be a non-negative integer")
    if not isinstance(scenario.topic, str) or not scenario.topic.strip():
        raise FakeMqttTransportConfigError("topic must be a non-empty string")
    if not isinstance(scenario.message, str):
        raise FakeMqttTransportConfigError("message must be a string")

    _validate_outcome("connect_outcome", scenario.connect_outcome)
    _validate_outcome("publish_outcome", scenario.publish_outcome)
    _validate_outcome("disconnect_outcome", scenario.disconnect_outcome)
    _validate_outcome("reconnect_outcome", scenario.reconnect_outcome)


def scenario_from_config(config: dict[str, Any] | None) -> FakeMqttTransportScenario:
    """Build a fake MQTT scenario from a small mapping.

    Missing fields use deterministic defaults. The accepted shape intentionally
    matches the framework's simple YAML parser: scalar fields only.
    """

    source = dict(config or {})
    scenario = FakeMqttTransportScenario(
        scenario_id=str(source.get("scenario", "connect_publish_disconnect_success")),
        connect_outcome=str(source.get("connect_outcome", "success")),
        publish_outcome=str(source.get("publish_outcome", "success")),
        disconnect_outcome=str(source.get("disconnect_outcome", "success")),
        reconnect_outcome=str(source.get("reconnect_outcome", "success")),
        reconnect_attempts=int(source.get("reconnect_attempts", 0)),
        topic=str(source.get("topic", "pqc/fake/no-network")),
        message=str(source.get("message", "fake MQTT payload")),
    )
    validate_fake_mqtt_transport_scenario(scenario)
    return scenario


def _event(
    *,
    index: int,
    operation: str,
    outcome: str,
    attempted: bool = True,
    reason: str | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "index": index,
        "operation": operation,
        "attempted": attempted,
        "outcome": outcome,
        "simulated": True,
        "evidence_class": FAKE_MQTT_EVIDENCE_CLASS,
        "evidence_label": FAKE_MQTT_EVIDENCE_LABEL,
    }
    if reason:
        event["reason"] = reason
    if attempt is not None:
        event["attempt"] = attempt
    return event


def run_fake_mqtt_transport_scenario(scenario: FakeMqttTransportScenario) -> dict[str, Any]:
    """Run a deterministic fake/no-network MQTT control-flow scenario."""

    validate_fake_mqtt_transport_scenario(scenario)

    events: list[dict[str, Any]] = []
    event_index = 1

    events.append(
        _event(
            index=event_index,
            operation="connect",
            outcome=scenario.connect_outcome,
        )
    )
    event_index += 1

    connected = scenario.connect_outcome == "success"
    publish_attempted = connected
    if publish_attempted:
        events.append(
            _event(
                index=event_index,
                operation="publish",
                outcome=scenario.publish_outcome,
            )
        )
        event_index += 1
    else:
        events.append(
            _event(
                index=event_index,
                operation="publish",
                attempted=False,
                outcome="skipped",
                reason="connect did not succeed in the fake/no-network scenario",
            )
        )
        event_index += 1

    disconnect_attempted = connected
    if disconnect_attempted:
        events.append(
            _event(
                index=event_index,
                operation="disconnect",
                outcome=scenario.disconnect_outcome,
            )
        )
        event_index += 1
    else:
        events.append(
            _event(
                index=event_index,
                operation="disconnect",
                attempted=False,
                outcome="skipped",
                reason="connect did not succeed in the fake/no-network scenario",
            )
        )
        event_index += 1

    reconnect_events: list[dict[str, Any]] = []
    for attempt in range(1, scenario.reconnect_attempts + 1):
        reconnect_event = _event(
            index=event_index,
            operation="reconnect",
            outcome=scenario.reconnect_outcome,
            attempt=attempt,
        )
        events.append(reconnect_event)
        reconnect_events.append(reconnect_event)
        event_index += 1

    timeout_operations = [
        event["operation"]
        for event in events
        if event.get("attempted") is True and event.get("outcome") == "timeout"
    ]
    failed_operations = [
        event["operation"]
        for event in events
        if event.get("attempted") is True and event.get("outcome") == "failure"
    ]
    successful_operations = [
        event["operation"]
        for event in events
        if event.get("attempted") is True and event.get("outcome") == "success"
    ]

    control_flow_completed = True
    if scenario.connect_outcome == "success":
        required_success = [scenario.publish_outcome, scenario.disconnect_outcome]
        if scenario.reconnect_attempts:
            required_success.append(scenario.reconnect_outcome)
        control_flow_success = all(outcome == "success" for outcome in required_success)
    else:
        control_flow_success = False

    return {
        "schema_version": FAKE_MQTT_TRANSPORT_SCHEMA_VERSION,
        "model_phase": FAKE_MQTT_TRANSPORT_MODEL_PHASE,
        "scenario_id": scenario.scenario_id,
        "evidence_class": FAKE_MQTT_EVIDENCE_CLASS,
        "evidence_label": FAKE_MQTT_EVIDENCE_LABEL,
        "transport_backend": FAKE_MQTT_TRANSPORT_BACKEND,
        "simulated": True,
        "topic": scenario.topic,
        "message_size_bytes": len(scenario.message.encode("utf-8")),
        "configured_outcomes": {
            "connect": scenario.connect_outcome,
            "publish": scenario.publish_outcome,
            "disconnect": scenario.disconnect_outcome,
            "reconnect": scenario.reconnect_outcome,
            "reconnect_attempts": scenario.reconnect_attempts,
        },
        "events": events,
        "summary": {
            "event_count": len(events),
            "successful_operations": successful_operations,
            "failed_operations": failed_operations,
            "timeout_operations": timeout_operations,
            "reconnect_attempts": len(reconnect_events),
            "control_flow_completed": control_flow_completed,
            "control_flow_success": control_flow_success,
        },
        "evidence_boundaries": {
            "claims_broker_success": False,
            "claims_network_success": False,
            "claims_tls_success": False,
            "claims_mqtt_runtime_success": False,
            "claims_stm32_runtime_success": False,
            "note": (
                "Phase M3 fake/no-network transport evidence is deterministic simulated "
                "control-flow evidence only. It is not broker, TLS, network, STM32 runtime, "
                "gateway, Wi-Fi, UART, or hardware evidence."
            ),
        },
    }
