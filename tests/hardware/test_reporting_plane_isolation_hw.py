"""Capability-gated live validation for Request 15 reporting-plane isolation.

Each configured case is a resolver-generated experiment whose network condition
isolates one impairment family (rate, RTT, loss or MTU). The test runs the normal
experiment authority rather than applying qdisc state independently.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


CASE_ENV = {
    "rate": "PQC_REPORTING_ISOLATION_RATE_CASE",
    "rtt": "PQC_REPORTING_ISOLATION_RTT_CASE",
    "loss": "PQC_REPORTING_ISOLATION_LOSS_CASE",
    "mtu": "PQC_REPORTING_ISOLATION_MTU_CASE",
}


def _enabled() -> bool:
    return os.environ.get("PQC_REPORTING_ISOLATION_HW", "").strip().lower() in {"1", "true", "yes", "on"}


def _latest_run(results_dir: Path) -> Path:
    candidates=[path for path in results_dir.iterdir() if path.is_dir() and (path / "manifest.json").is_file()]
    assert candidates, f"no run manifest produced under {results_dir}"
    return max(candidates,key=lambda path:path.stat().st_mtime_ns)


@pytest.mark.hardware
@pytest.mark.parametrize("condition", ("rate", "rtt", "loss", "mtu"))
def test_reporting_collection_remains_complete_under_experiment_impairment(condition: str, tmp_path: Path):
    if not _enabled():
        pytest.skip("set PQC_REPORTING_ISOLATION_HW=1 to run live Request-15 isolation validation")
    case_value=os.environ.get(CASE_ENV[condition], "").strip()
    if not case_value:
        pytest.skip(f"{CASE_ENV[condition]} must name a resolver-generated case")
    case=Path(case_value)
    assert case.is_file(), f"missing resolved case: {case}"

    results_dir=tmp_path / condition
    completed=subprocess.run(
        [sys.executable,"scripts/experiment.py","run","--experiment",str(case),"--results-dir",str(results_dir)],
        text=True,encoding="utf-8",errors="replace",capture_output=True,check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr

    run_dir=_latest_run(results_dir)
    manifest=json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    degradation=manifest["network_degradation"]
    assert degradation["boundary"] == "experiment_broker_host_veth"
    assert degradation["reporting_plane_impairment_exempt"] is True
    assert degradation["mtu_scope"] == "experiment_broker_veth_pair_only"
    assert degradation["status"] == "removed"
    assert degradation["cleanup_return_code"] == 0

    collection=manifest["result_collection"]
    assert collection["status"] == "complete"
    assert collection["completion_integrity"] is True
    assert collection["source_integrity"]["stm32"]["passed"] is True
    assert (run_dir / collection["raw_stream"]).is_file()

    capture=manifest["gateway_packet_capture"]
    assert "not port 1886" in str(capture["filter"])
