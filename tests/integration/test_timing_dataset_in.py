"""Local real-process A1 CLI/export/loader boundary; no hardware or network."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "scripts", ROOT / "tests"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
from timing_dataset_support import make_run

pytestmark = pytest.mark.integration


def invoke(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts/export_timing_dataset.py"), *map(str, args)],
                          cwd=ROOT, text=True, capture_output=True, timeout=30, check=False)


def test_cli_export_check_and_fresh_process_view(tmp_path):
    run = make_run(tmp_path / "run")
    failed = make_run(tmp_path / "failed", run_id="synthetic-failed", failed=True)
    output = tmp_path / "dataset"
    exported = invoke("--run-dir", run, "--run-dir", failed, "--run-dir", run, "--output", output)
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout)["counts"]["valid_timings"] == 8
    checked = invoke("--check", output, "--verify-source-inputs")
    assert checked.returncode == 0, checked.stderr
    env = dict(os.environ, PYTHONPATH=str(ROOT / "scripts"))
    code = "from framework.timing_dataset_loader import load_dataset; import sys; d=load_dataset(sys.argv[1]); assert len(d.timing_view())==2; assert len(d.timings)==16"
    loaded = subprocess.run([sys.executable, "-c", code, str(output)], cwd=tmp_path,
                            env=env, text=True, capture_output=True, timeout=30)
    assert loaded.returncode == 0, loaded.stderr


def test_cli_discovery_freezes_inputs_and_does_not_overwrite(tmp_path):
    root = tmp_path / "results"; make_run(root / "campaign/runs/run")
    output = root / "analysis/timing"
    result = invoke("--results-root", root, "--output", output)
    assert result.returncode == 0, result.stderr
    make_run(root / "campaign/runs/later", run_id="synthetic-later")
    checked = invoke("--check", output, "--verify-source-inputs")
    assert checked.returncode == 0 and json.loads(checked.stdout)["counts"]["runs"] == 1
    refused = invoke("--results-root", root, "--output", output)
    assert refused.returncode == 2 and "never overwritten" in refused.stderr


def test_cli_tampered_dataset_and_bad_selection_fail(tmp_path):
    run = make_run(tmp_path / "run"); output = tmp_path / "dataset"
    assert invoke("--run-dir", run, "--output", output).returncode == 0
    with (output / "timings.csv").open("a") as handle: handle.write("changed\n")
    assert invoke("--check", output).returncode == 2
    assert invoke("--run-dir", run, "--results-root", run, "--output", tmp_path / "bad").returncode == 2
