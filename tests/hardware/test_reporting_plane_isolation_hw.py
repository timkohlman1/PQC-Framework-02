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
    """Verify applied gateway configuration and cleanup, not measured wire performance."""
    assert condition in CONDITIONS
    manifest = _finalized_manifest(run_dir)
    path = _indexed_file(run_dir, manifest, "network_condition_record")
    text = path.read_text(encoding="utf-8", errors="replace")
    assert "Apply command:" in text and "Cleanup command:" in text, path
    apply, cleanup = text.split("Cleanup command:", 1)
    assert re.search(r"(?m)^Return code: 0\s*$", apply), f"impairment application failed: {path}"
    assert re.search(r"(?m)^Cleanup return code: 0\s*$", cleanup), f"impairment cleanup failed: {path}"
    assert re.search(r"\bservice=mqtt-classical(?=;)", apply), "unexpected experiment broker boundary"
    assert re.search(r"(?m)^PQC_EXPERIMENT_VETH=veth[\w-]+\s*$", apply), "missing experiment veth"
    assert re.search(r"(?m)^PQC_EXPERIMENT_CONTAINER_PID=[1-9]\d*\s*$", apply)
    assert "PQC_APPLIED_STATE_BEGIN" in apply and "PQC_APPLIED_STATE_END" in apply
    state = apply.rsplit("PQC_APPLIED_STATE_BEGIN", 1)[1].split("PQC_APPLIED_STATE_END", 1)[0]
    assert len(re.findall(r"(?m)^qdisc netem\b", state)) >= 2, "missing bidirectional netem state"
    assert "ifb-pqc0" in apply, "missing ingress redirect interface"
    assert "mirred egress redirect dev $ifb" in apply, "missing ingress-to-IFB redirection"
    assert "service=mqtt-reporting" not in apply, "reporting service selected for impairment"
    impairment = profile["impairment"]
    assert impairment["enabled"] is True and impairment["management_safe"] is True
    mtu = impairment["mtu"]
    assert re.search(rf"(?m)^\d+: veth[^\n]*\bmtu {mtu}\b", state), "experiment veth MTU differs"
    assert f"link set dev eth0 mtu {mtu}" in apply, "container-side MTU not configured"
    rate = impairment["rate_kbit"]
    rate_label = f"{rate // 1000}Mbit" if rate % 1000 == 0 else f"{rate}Kbit"
    assert len(re.findall(rf"(?m)^qdisc netem[^\n]*\brate {re.escape(rate_label)}\b", state)) >= 2, (
        "experiment broker rate configuration differs"
    )
    if condition == "loss":
        loss_label = str(impairment["loss_percent"])
        assert len(re.findall(rf"(?m)^qdisc netem[^\n]*\bloss {re.escape(loss_label)}%", state)) >= 2, (
            "loss qdisc missing"
        )
    if condition == "rtt":
        assert len(re.findall(rf"(?m)^qdisc netem[^\n]*\bdelay {impairment['rtt_ms'] // 2}ms\b", state)) >= 2, "delay qdisc missing"
    # Cleanup must restore the original MTU and remove both qdiscs and IFB.
    assert "qdisc del dev $iface root" in cleanup
    assert "qdisc del dev $iface ingress" in cleanup
    assert "qdisc del dev $ifb root" in cleanup
    original = re.search(r"(?m)^PQC_ORIGINAL_MTU=(\d+)\s*$", apply)
    container_original = re.search(r"(?m)^PQC_CONTAINER_ORIGINAL_MTU=(\d+)\s*$", apply)
    assert original and container_original, "original MTU values not retained"
    assert f"link set dev $iface mtu {original.group(1)}" in cleanup
    assert f"link set dev eth0 mtu {container_original.group(1)}" in cleanup
    assert "link del dev $ifb type ifb" in cleanup
    assert f'[ "$actual_mtu" = "{original.group(1)}" ]' in cleanup, "missing MTU restoration check"


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
