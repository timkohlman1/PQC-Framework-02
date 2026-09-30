"""Real STM32 campaigns against the manually provisioned persistent appliance."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml
from framework.hardware_test_support import HardwareFileRun, session_result_dir
from framework.energy_analysis import acquisitions, Integral, workload_bounds, map_boundary

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.hardware, pytest.mark.long]


@pytest.mark.parametrize("workload", ["ready_metrics", "tls_handshake_repeat", "baremetal_benchmark"])
def test_energy_campaign(workload, pytestconfig, pqc_require_capabilities):
    pqc_require_capabilities("local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware")
    context = HardwareFileRun.create(repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig), module_name="test_energy_capture_hw")
    campaign = yaml.safe_load((ROOT/"configs/campaigns/baseline.yaml").read_text())
    campaign.update(id="energy-hw", workload=workload, instruments={"energy":"esp32_ina228"})
    campaign["execution"]["repetitions"] = 2
    if workload == "tls_handshake_repeat":
        campaign["matrix"] = {"workload.iterations.handshakes_per_run": [2]}
    elif workload == "baremetal_benchmark":
        campaign["matrix"] = {"tls_kex": ["ML_KEM_768"], "workload.iterations.operations_per_run": [2]}
    source = context.generated_root/"campaign.yaml"
    source.write_text(yaml.safe_dump(campaign))
    results = context.evidence_root/"campaign-runs"
    completed = subprocess.run([sys.executable,"scripts/run_campaign.py",str(source),"--results-root",str(results)],
        cwd=ROOT, capture_output=True, text=True, timeout=1200)
    (context.evidence_root/"campaign.stdout.log").write_text(completed.stdout)
    (context.evidence_root/"campaign.stderr.log").write_text(completed.stderr)
    (context.evidence_root/"campaign.returncode.json").write_text(json.dumps({"return_code":completed.returncode}))
    assert completed.returncode == 0, f"campaign failed; retained evidence: {context.evidence_root}"
    manifest_path = next(results.glob("*/campaign-manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    assert manifest["state"] == "completed" and len(manifest["runs"]) == 2
    captures = set()
    for run in manifest["runs"]:
        path = Path(run["manifest"])
        final = json.loads(path.read_text())
        assert final["capture_acceptance"]["accepted"]
        acceptance = json.loads(path.with_name("energy-capture.json").read_text())
        assert acceptance["passed"] and acceptance["capture_received"] and acceptance["workload_passed"]
        assert acceptance["sample_count"] > 0
        assert acceptance["sample_record_bytes"] == 20
        assert acceptance["alignment"]["stm32_end_us"] > acceptance["alignment"]["stm32_start_us"]
        assert acceptance["alignment"]["esp32_end_us"] > acceptance["alignment"]["esp32_start_us"]
        assert not path.with_name("energy-association.json").exists()
        captures.add(acceptance["capture_id"])
        roles = {a["role"]: a for a in final["artifacts"]}
        for role in ("stm32_result_stream", "energy_result_stream"):
            assert roles[role]["acquisition"]["status"] == "available"
        # A valid transfer alone does not prove coverage of the workload interval.
        trace = acquisitions(path.parent/roles["energy_result_stream"]["path"])[acceptance["capture_id"]]
        assert trace["reason"] is None
        complete = trace["complete"]
        a = acceptance["alignment"]
        pair = (a["stm32_start_us"], a["stm32_end_us"])
        bounds = workload_bounds(path.parent/roles["stm32_result_stream"]["path"], path.parent.name, pair)
        mapped = [map_boundary(t, *pair, complete["e0_us"], complete["e1_us"]) for t in bounds]
        integrated = Integral(trace["samples"], complete["gap_limit_us"]).interval(*mapped)
        assert integrated["duration_s"] > 0
    assert len(captures) == 2
    for group in manifest["firmware_groups"]:
        preparation = manifest_path.parent/group["preparation_manifest"]
        prepared = json.loads(preparation.read_text())
        assert prepared["capture_contract"]["experiment_class"] == "prepare_only"
        assert not preparation.with_name("energy-association.json").exists()
