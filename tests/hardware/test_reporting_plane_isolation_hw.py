"""Validate experiment-broker impairment isolation with retained gateway and STM32 evidence.

Each condition owns a resolved case and run directory. The file's executions are
sequential, and no UART verbosity or prior hardware image is assumed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.hardware_test_support import HardwareFileRun, session_result_dir
from framework.config_resolver import ConfigResolver
from framework.result_collector import _parse_raw_stream
from framework.network_degradation import NetworkDegradationConfig, _verified_state

pytestmark = [pytest.mark.hardware, pytest.mark.long]
CONDITIONS = ("rate", "rtt", "loss", "mtu")


def _json_file(path: Path) -> dict:
    assert path.is_file(), f"missing retained evidence: {path}"
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"expected JSON object: {path}"
    return value


def _indexed_file(run_dir: Path, manifest: dict, role: str) -> Path:
    indexed = [item for item in manifest.get("artifacts", []) if item.get("role") == role]
    assert len(indexed) == 1, f"expected exactly one {role} artifact: {run_dir}"
    relative = indexed[0].get("path")
    assert isinstance(relative, str) and relative and not Path(relative).is_absolute(), (
        f"invalid {role} path: {relative!r}"
    )
    path = (run_dir / relative).resolve()
    assert path.is_relative_to(run_dir.resolve()) and path.is_file(), (
        f"missing or out-of-run {role} evidence: {relative}"
    )
    return path


def _finalized_manifest(run_dir: Path) -> dict:
    manifest = _json_file(run_dir / "manifest.json")
    outcome = manifest.get("execution_outcome", {})
    assert outcome.get("status") == "completed" and outcome.get("failure_stage") == "none", outcome
    assert outcome.get("result") == "baseline_run_passed", outcome
    assert manifest.get("capture_acceptance", {}).get("accepted") is True
    assert manifest.get("final_index", {}).get("status") == "finalized"
    assert manifest.get("run", {}).get("state") == "finalized"
    return manifest


def _assert_impairment(run_dir: Path, condition: str, profile: dict) -> None:
    """Check independent observed gateway state and verified restoration."""
    assert condition in CONDITIONS
    manifest = _finalized_manifest(run_dir)
    _indexed_file(run_dir, manifest, "packet_capture")
    path = _indexed_file(run_dir, manifest, "network_condition_record")
    text = path.read_text(encoding="utf-8", errors="replace")
    assert "Apply command:" in text and "Cleanup command:" in text, path
    apply, cleanup = text.split("Cleanup command:", 1)
    assert re.search(r"\bservice=mqtt-classical(?=;)", apply), "unexpected experiment broker boundary"
    assert re.search(r"(?m)^Return code: 0\s*$", apply), f"impairment application failed: {path}"
    assert re.search(r"(?m)^Cleanup return code: 0\s*$", cleanup), f"impairment cleanup failed: {path}"
    assert re.search(r"(?m)^PQC_EXPERIMENT_VETH=veth[\w-]+\s*$", apply), "missing experiment veth"
    assert re.search(r"(?m)^PQC_REPORTING_PEER_INDEX=\d+\s*$", apply), "missing reporting interface identity"
    impairment = profile["impairment"]
    config = NetworkDegradationConfig(
        interface=impairment["interface"],
        ifb_interface=impairment.get("ifb_interface", "ifb-pqc0"),
        rate_kbit=impairment["rate_kbit"], rtt_ms=impairment["rtt_ms"],
        loss_percent=float(impairment["loss_percent"]), mtu=impairment["mtu"],
        management_safe=True, broker_service="mqtt-classical",
    )
    apply_stdout = apply.split("\n\n", 1)[1]
    valid, reason = _verified_state(apply_stdout, config)
    assert valid, f"requested impairment is not verified by live gateway state: {reason}; {path}"
    original = re.search(r"(?m)^PQC_ORIGINAL_MTU=(\d+)\s*$", apply)
    container_original = re.search(r"(?m)^PQC_CONTAINER_ORIGINAL_MTU=(\d+)\s*$", apply)
    assert original and container_original, "missing original interface MTUs"
    assert "PQC_RESTORED_STATE_BEGIN" in cleanup and "PQC_RESTORED_STATE_END" in cleanup
    cleanup_stdout = cleanup.split("\n\n", 1)[1]
    restored = cleanup_stdout.split("PQC_RESTORED_STATE_BEGIN", 1)[1].split("PQC_RESTORED_STATE_END", 1)[0]
    assert re.search(rf"(?m)^\d+: veth[^\n]*\bmtu {original.group(1)}\b", restored), "host MTU not restored"
    assert re.search(rf"(?m)^\d+: eth0[^\n]*\bmtu {container_original.group(1)}\b", restored), "container MTU not restored"
    assert "qdisc netem " not in restored and "qdisc ingress " not in restored


def _assert_reporting(run_dir: Path) -> None:
    manifest = _finalized_manifest(run_dir)
    raw = _indexed_file(run_dir, manifest, "stm32_result_stream")
    _indexed_file(run_dir, manifest, "reporting_broker_log")
    _indexed_file(run_dir, manifest, "run_provenance")
    collector = _json_file(run_dir / "mqtt-reporting-collector.log")
    assert collector.get("run_id") == run_dir.name
    assert collector.get("expected_sources") == ["stm32"]
    assert collector.get("stop_return_code") == 0 and collector.get("copy_return_code") == 0
    validation = collector.get("validation", {})
    assert validation.get("passed") is True and validation.get("failure_reasons") == []
    assert validation.get("completion_count") == 1
    stm32 = validation.get("source_results", {}).get("stm32", {})
    assert stm32.get("passed") is True and stm32.get("completion_count") == 1
    assert stm32.get("missing_sequences") == [] and stm32.get("duplicate_sequences") == []
    assert stm32.get("observed_chunk_count", 0) > 0
    assert stm32.get("observed_chunk_count") == stm32.get("expected_chunk_count")
    assert stm32.get("observed_record_count", 0) > 0
    assert stm32.get("observed_record_count") == stm32.get("expected_record_count")
    assert stm32.get("observed_sha256") and stm32["observed_sha256"] == stm32.get("expected_sha256")
    # Independently validate the retained raw stream, not just the collector summary.
    observed = _parse_raw_stream(raw, run_dir.name, ("stm32",), {"stm32": 1})
    assert observed.passed, f"invalid retained STM32 stream: {observed.failure_reasons}"
    assert observed.completion_count == 1
    assert observed.source_results["stm32"]["observed_record_count"] == stm32["observed_record_count"]
    assert observed.observed_sha256 == validation.get("observed_sha256")


@pytest.fixture(scope="module")
def reporting_file_context(pytestconfig):
    return HardwareFileRun.create(
        repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig),
        module_name="test_reporting_plane_isolation_hw",
    )


@pytest.mark.parametrize("condition", CONDITIONS)
def test_reporting_collection_remains_complete_under_experiment_impairment(
    condition: str, reporting_file_context: HardwareFileRun, pqc_require_capabilities,
):
    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware"
    )
    # Each condition owns a resolved case and retained run; no other test file is a prerequisite.
    case = reporting_file_context.case(
        template="mqtt_plaintext_validation", network_condition=f"validation_{condition}",
        case_name=condition,
    )
    bundle = ConfigResolver(ROOT).to_legacy_bundle(
        ConfigResolver(ROOT).load_resolved_case(case), resolve_secrets=False
    )
    mqtt = bundle["experiment"]["mqtt"]
    assert mqtt["evidence_class"] == "stm32_st67_plaintext_e2e"
    assert mqtt["transport_backend"] == "st67w61m1_lwip_sockets"
    assert mqtt["tls"]["mode"] == "plaintext"
    assert mqtt["broker"]["port"] == 1883
    profile = yaml.safe_load((ROOT / "configs" / "network_conditions" / f"validation_{condition}.yaml").read_text(encoding="utf-8"))
    run_dir, _ = reporting_file_context.run_experiment(case=case, name=condition)
    _assert_impairment(run_dir, condition, profile)
    _assert_reporting(run_dir)


def test_retained_rate_condition_verifies_both_directions_across_repetitions(
    reporting_file_context: HardwareFileRun, pqc_require_capabilities,
):
    """A two-repetition live campaign must preserve and reverify one impairment."""
    import subprocess

    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware"
    )
    reporting_file_context.case(
        template="mqtt_plaintext_validation", network_condition="validation_rate",
        repetitions=2, case_name="retained_rate",
    )
    source = reporting_file_context.generated_root / "retained_rate" / "campaign.yaml"
    results = reporting_file_context.evidence_root / "retained-rate-campaign"
    results.mkdir()
    completed = subprocess.run(
        [sys.executable, "scripts/run_campaign.py", str(source), "--results-root", str(results)],
        cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    (results / "campaign.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (results / "campaign.stderr.log").write_text(completed.stderr, encoding="utf-8")
    assert completed.returncode == 0, f"campaign failed; raw logs: {results}"
    manifests = sorted(results.glob("*/campaign-manifest.json"))
    assert len(manifests) == 1, f"missing campaign manifest: {results}"
    campaign = _json_file(manifests[0])
    assert campaign["state"] == "completed" and campaign["cleanup"]["status"] == "passed"
    runs = campaign["runs"]
    assert len(runs) == 2 and {item["repetition_index"] for item in runs} == {1, 2}
    assert len({item["manifest"] for item in runs}) == 2
    for item in runs:
        run_dir = Path(item["manifest"]).parent
        manifest = _finalized_manifest(run_dir)
        _indexed_file(run_dir, manifest, "packet_capture")
        _assert_reporting(run_dir)
    applied = [item for item in campaign["condition_events"] if item["status"] == "applied"]
    assert len(applied) == 1 and applied[0]["network_condition"] == "validation_rate"
    control_log = manifests[0].parent / applied[0]["control_log"]
    text = control_log.read_text(encoding="utf-8")
    assert text.count("Retained-state verification return code: 0") >= 4
    assert "Repetition 1 packet counters:" in text and "Repetition 2 packet counters:" in text
    assert re.search(r"(?m)^Cleanup return code: 0\s*$", text)
    assert "PQC_RESTORED_STATE_BEGIN" in text and "PQC_RESTORED_STATE_END" in text


@pytest.mark.parametrize("condition", CONDITIONS)
def test_persistent_esp32_reporting_integrity_under_experiment_impairment(
    condition: str, reporting_file_context: HardwareFileRun, pqc_require_capabilities,
    pytestconfig,
):
    """Optional strict instrument lab gate; never infer ESP32 success from STM32-only evidence."""
    if not pytestconfig.getoption("--pqc-request8-esp32-hardware"):
        pytest.skip("persistent, calibrated and provisioned ESP32/INA228 energy source not enabled for Request 8")
    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware"
    )
    case = reporting_file_context.case(
        template="mqtt_plaintext_validation", network_condition=f"validation_{condition}",
        instruments={"energy": "esp32_ina228"}, case_name=f"esp32_{condition}",
    )
    run_dir, _ = reporting_file_context.run_experiment(case=case, name=f"esp32_{condition}")
    profile = yaml.safe_load(
        (ROOT / "configs" / "network_conditions" / f"validation_{condition}.yaml").read_text(encoding="utf-8")
    )
    _assert_impairment(run_dir, condition, profile)
    manifest = _finalized_manifest(run_dir)
    raw = _indexed_file(run_dir, manifest, "stm32_result_stream")
    _indexed_file(run_dir, manifest, "energy_result_stream")
    collector = _json_file(run_dir / "mqtt-reporting-collector.log")
    assert collector.get("expected_sources") == ["stm32", "energy"]
    validation = collector.get("validation", {})
    assert validation.get("passed") is True and validation.get("failure_reasons") == []
    for source in ("stm32", "energy"):
        source_result = validation.get("source_results", {}).get(source, {})
        assert source_result.get("passed") is True
        assert source_result.get("completion_count") == 1
        assert source_result.get("missing_sequences") == []
        assert source_result.get("duplicate_sequences") == []
        assert source_result.get("observed_sha256") == source_result.get("expected_sha256")
    observed = _parse_raw_stream(raw, run_dir.name, ("stm32", "energy"), {"stm32": 1, "energy": 1})
    assert observed.passed, observed.failure_reasons
