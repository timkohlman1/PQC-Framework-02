"""Validate one independent plaintext MQTT hardware experiment using retained evidence.

The two related tests share preparation and hardware execution within this file.
UART diagnostics are supplementary: full/minimal/off modes cannot determine
MQTT or deferred-reporting success. The experiment is still required to produce
broker-side protocol evidence and a complete STM32 reporting stream.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.hardware_test_support import HardwareFileRun, session_result_dir
from framework.config_resolver import ConfigResolver
from framework.result_collector import _parse_raw_stream

pytestmark = [pytest.mark.hardware, pytest.mark.long]


def _read_json(run_dir: Path, filename: str) -> dict:
    path = run_dir / filename
    assert path.is_file(), f"missing retained evidence: {path}"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"expected JSON object: {path}"
    return value


def _finalized_evidence(run_dir: Path, required_roles: tuple[str, ...]) -> dict:
    manifest = _read_json(run_dir, "manifest.json")
    outcome = manifest.get("execution_outcome", {})
    assert outcome.get("status") == "completed", f"experiment not completed: {run_dir}"
    assert outcome.get("failure_stage") == "none", f"experiment failed: {outcome}"
    assert outcome.get("result") == "baseline_run_passed", f"experiment failed: {outcome}"
    assert manifest.get("capture_acceptance", {}).get("accepted") is True
    assert manifest.get("final_index", {}).get("status") == "finalized"
    assert manifest.get("run", {}).get("state") == "finalized"
    artifacts = manifest.get("artifacts", [])
    assert isinstance(artifacts, list), "finalized artifact index is missing"
    for role in required_roles:
        matches = [item for item in artifacts if item.get("role") == role]
        assert len(matches) == 1, f"expected exactly one {role} artifact: {run_dir}"
        relative = matches[0].get("path")
        assert isinstance(relative, str) and relative and not Path(relative).is_absolute(), (
            f"invalid {role} artifact path: {relative!r}"
        )
        path = (run_dir / relative).resolve()
        assert path.is_relative_to(run_dir.resolve()) and path.is_file(), (
            f"missing or out-of-run {role} evidence: {relative}"
        )
    return manifest


def _assert_broker_evidence(run_dir: Path) -> None:
    _finalized_evidence(run_dir, (
        "observer_evidence", "experiment_broker_log", "mqtt_publisher_log",
        "mqtt_subscriber_log", "mqtt_subscriber_raw_log",
    ))
    broker = _read_json(run_dir, "mqtt-broker-message-evidence.json")
    assert broker.get("available") is True
    assert broker.get("passed") is True
    assert broker.get("required_for_pass") is True
    assert broker.get("collection_return_code") == 0
    for field in (
        "stm32_connected", "stm32_subscribe_received", "stm32_suback_sent",
        "command_publish_received", "command_publish_delivered",
        "response_publish_received", "response_publish_delivered",
    ):
        assert broker.get(field) is True, f"missing broker-side STM32 MQTT evidence: {field}"
    subscriber = _read_json(run_dir, "mqtt-subscriber.log")
    assert subscriber.get("marker_present") is True
    assert subscriber.get("subscriber_rc") == 0
    assert subscriber.get("response_matched") == "1"
    expected = subscriber.get("expected_response_count")
    assert isinstance(expected, int) and expected > 0
    assert subscriber.get("response_count") == expected
    assert (run_dir / "mqtt-subscriber-raw.log").stat().st_size > 0


def _assert_reporting_evidence(run_dir: Path) -> None:
    _finalized_evidence(run_dir, (
        "stm32_result_stream", "reporting_broker_log", "run_provenance",
    ))
    collector = _read_json(run_dir, "mqtt-reporting-collector.log")
    assert collector.get("run_id") == run_dir.name
    assert collector.get("expected_sources") == ["stm32"]
    assert collector.get("stop_return_code") == 0
    assert collector.get("copy_return_code") == 0
    logged = collector.get("validation", {})
    assert logged.get("passed") is True, f"reporting validation failed: {logged.get('failure_reasons')}"
    assert logged.get("failure_reasons") == []
    assert logged.get("completion_count") == 1
    assert logged.get("duplicate_sequences") == []
    assert logged.get("missing_sequences") == []
    stm32 = logged.get("source_results", {}).get("stm32", {})
    assert stm32.get("passed") is True
    assert stm32.get("completion_count") == 1
    assert stm32.get("observed_record_count", 0) > 0
    assert stm32.get("observed_record_count") == stm32.get("expected_record_count")
    assert stm32.get("observed_chunk_count", 0) > 0
    assert stm32.get("observed_chunk_count") == stm32.get("expected_chunk_count")
    assert stm32.get("observed_sha256") and stm32.get("observed_sha256") == stm32.get("expected_sha256")
    # Independently re-parse the retained raw stream. A forged/stale collector
    # summary alone cannot satisfy the test, nor can a stream from another run.
    raw = run_dir / "mqtt-reporting-raw.ndjson"
    assert raw.is_file() and raw.stat().st_size > 0
    observed = _parse_raw_stream(raw, run_dir.name, ("stm32",), {"stm32": 1})
    assert observed.passed, f"invalid retained STM32 result stream: {observed.failure_reasons}"
    assert observed.completion_count == 1
    assert observed.source_results["stm32"]["observed_record_count"] > 0
    assert observed.source_results["stm32"]["observed_record_count"] == stm32["observed_record_count"]
    assert observed.observed_sha256 == logged.get("observed_sha256")


@pytest.fixture(scope="module")
def mqtt_hardware_run(pytestconfig, pqc_capabilities):
    unavailable = [pqc_capabilities.check(name) for name in (
        "local_toolchain", "gateway", "flash_helper", "uart_device",
    ) if not pqc_capabilities.check(name).available]
    if unavailable:
        reason = "; ".join(f"{item.name}: {item.reason}" for item in unavailable)
        if pytestconfig.getoption("--pqc-require-hardware"):
            pytest.fail(f"PQC capability unavailable: {reason}")
        pytest.skip(f"PQC capability unavailable: {reason}")
    context = HardwareFileRun.create(
        repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig),
        module_name="test_mqtt_plaintext_st67_e2e_hw",
    )
    case = context.case(template="mqtt_plaintext_validation")
    resolver = ConfigResolver(ROOT)
    bundle = resolver.to_legacy_bundle(resolver.load_resolved_case(case), resolve_secrets=False)
    mqtt = bundle["experiment"]["mqtt"]
    assert mqtt["evidence_class"] == "stm32_st67_plaintext_e2e"
    assert mqtt["transport_backend"] == "st67w61m1_lwip_sockets"
    assert mqtt["tls"]["mode"] == "plaintext"
    assert mqtt["broker"]["port"] == 1883
    run_dir, _ = context.run_experiment(case=case, name="mqtt_validation")
    return run_dir


def test_mqtt_plaintext_st67_e2e_retained_broker_evidence(mqtt_hardware_run):
    """Validate the STM32's plaintext MQTT exchange from retained broker evidence."""
    _assert_broker_evidence(mqtt_hardware_run)


def test_mqtt_plaintext_st67_e2e_reporting_evidence(mqtt_hardware_run):
    """Validate the complete, run-specific STM32 buffered reporting stream."""
    _assert_reporting_evidence(mqtt_hardware_run)
