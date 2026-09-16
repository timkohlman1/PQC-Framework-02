"""Capability-gated Request-11 campaign execution validation."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _enabled() -> bool:
    return os.environ.get("PQC_CAMPAIGN_HW", "").strip().lower() in {"1", "true", "yes", "on"}


def _new_campaign_manifest(results_root: Path, before: set[Path]) -> Path:
    candidates = {
        path.resolve()
        for path in results_root.glob("*/campaign-manifest.json")
        if path.is_file()
    } - before
    assert len(candidates) == 1, (
        f"expected exactly one new campaign manifest under {results_root}, "
        f"found {len(candidates)}"
    )
    return next(iter(candidates))


@pytest.mark.hardware
def test_campaign_repetitions_reuse_preparation_and_isolate_run_evidence():
    if not _enabled():
        pytest.skip("set PQC_CAMPAIGN_HW=1 to run live Request-11 campaign validation")
    campaign = os.environ.get("PQC_CAMPAIGN_HW_CONFIG", "baseline").strip()
    results_root = REPO_ROOT / "results" / "hardware" / "request11-campaign"
    results_root.mkdir(parents=True, exist_ok=True)
    before = {
        path.resolve()
        for path in results_root.glob("*/campaign-manifest.json")
        if path.is_file()
    }
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_campaign.py",
            campaign,
            "--results-root", str(results_root),
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    manifest_path = _new_campaign_manifest(results_root, before)
    assert completed.returncode == 0, (
        f"campaign execution failed with return code {completed.returncode}; "
        f"persistent evidence: {manifest_path.parent}"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "completed"
    assert manifest["cleanup"]["status"] == "passed"
    assert manifest["runs"]
    preparation_refs = {g["preparation_manifest"] for g in manifest["firmware_groups"]}
    assert None not in preparation_refs
    for run in manifest["runs"]:
        run_manifest = json.loads(Path(run["manifest"]).read_text(encoding="utf-8"))
        campaign_execution = run_manifest["configuration"]["campaign_execution"]
        assert campaign_execution["firmware_sha256"] == run["firmware_sha256"]
        assert campaign_execution["repetition_index"] == run["repetition_index"]
        assert run_manifest["final_index"]["status"] == "finalized"
        assert run_manifest["capture_acceptance"]["accepted"] is True
