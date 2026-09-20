"""Test multi-repetition campaign preparation and independently retained runs."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.hardware_test_support import HardwareFileRun, session_result_dir

pytestmark = [pytest.mark.hardware, pytest.mark.long]


def test_campaign_repetitions_reuse_preparation_and_isolate_run_evidence(
    pytestconfig, pqc_require_capabilities,
):
    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware"
    )
    context = HardwareFileRun.create(
        repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig),
        module_name="test_campaign_executor_hw",
    )
    # Canonical baseline has only one repetition, so a test-owned source must
    # request two to exercise the actual repetition/reuse contract.
    context.case(template="baseline", repetitions=2)
    campaign = context.generated_root / "default" / "campaign.yaml"
    results_root = context.evidence_root / "campaign-runs"
    results_root.mkdir()
    completed = subprocess.run(
        [sys.executable, "scripts/run_campaign.py", str(campaign),
         "--results-root", str(results_root)],
        cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    (context.evidence_root / "campaign.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (context.evidence_root / "campaign.stderr.log").write_text(completed.stderr, encoding="utf-8")
    (context.evidence_root / "campaign.returncode.json").write_text(
        json.dumps({"return_code": completed.returncode}, indent=2) + "\n", encoding="utf-8"
    )
    manifests = sorted(results_root.glob("*/campaign-manifest.json"))
    assert completed.returncode == 0, f"campaign rc={completed.returncode}; evidence: {context.evidence_root}"
    assert len(manifests) == 1, f"expected one campaign manifest; evidence: {context.evidence_root}"
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["state"] == "completed"
    assert manifest["cleanup"]["status"] == "passed"
    assert len(manifest["runs"]) == 2, "two repetitions must produce separate run evidence"
    preparation_refs = {group["preparation_manifest"] for group in manifest["firmware_groups"]}
    assert len(preparation_refs) == 1 and None not in preparation_refs
    assert {run["repetition_index"] for run in manifest["runs"]} == {1, 2}
    assert len({run["manifest"] for run in manifest["runs"]}) == 2
    for run in manifest["runs"]:
        run_manifest = json.loads(Path(run["manifest"]).read_text(encoding="utf-8"))
        campaign_execution = run_manifest["configuration"]["campaign_execution"]
        assert campaign_execution["firmware_sha256"] == run["firmware_sha256"]
        assert campaign_execution["repetition_index"] == run["repetition_index"]
        assert run_manifest["final_index"]["status"] == "finalized"
        assert run_manifest["capture_acceptance"]["accepted"] is True
