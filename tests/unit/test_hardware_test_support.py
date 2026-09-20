"""Unit coverage for the source-only, no-hardware test-file support layer."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework import hardware_test_support as support


def _context(tmp_path: Path) -> support.HardwareFileRun:
    repo = tmp_path / "repo"
    (repo / "configs" / "campaigns").mkdir(parents=True)
    (repo / "configs" / "campaigns" / "secure_boot.yaml").write_text(
        yaml.safe_dump({
            "id": "secure_boot", "matrix": {"secure_boot": ["ecdsa_p256", "rsa3072"]},
            "fixed": {"network_condition": "baseline"}, "workload": "baseline",
            "execution": {"repetitions": 1},
        }), encoding="utf-8"
    )
    return support.HardwareFileRun.create(
        repo_root=repo, session_result_dir=tmp_path / "results", module_name="sample_hw"
    )


def test_distinct_file_invocations_have_distinct_ownership(tmp_path):
    first = _context(tmp_path)
    second = support.HardwareFileRun.create(
        repo_root=first.repo_root, session_result_dir=tmp_path / "results", module_name="sample_hw"
    )
    assert first.generated_root != second.generated_root
    assert first.evidence_root != second.evidence_root
    assert first.evidence_root.is_dir() and second.evidence_root.is_dir()


def test_independent_resolved_conditions_are_retained(tmp_path, monkeypatch):
    context = _context(tmp_path)

    class FakeResolver:
        def __init__(self, root):
            assert root == context.repo_root

        def materialize_campaign(self, source, output_root):
            target = output_root / "cases"
            target.mkdir(parents=True)
            (target / "0001.yaml").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            (output_root / "campaign-resolved.yaml").write_text("case_count: 1\n", encoding="utf-8")
            return output_root

    monkeypatch.setattr(support, "ConfigResolver", FakeResolver)
    rate = context.case(template="secure_boot", workload="mqtt_validation",
                        network_condition="validation_rate", case_name="rate")
    loss = context.case(template="secure_boot", workload="mqtt_validation",
                        network_condition="validation_loss", case_name="loss")
    assert rate != loss
    rate_config = yaml.safe_load(rate.read_text(encoding="utf-8"))
    loss_config = yaml.safe_load(loss.read_text(encoding="utf-8"))
    assert rate_config["fixed"]["network_condition"] == "validation_rate"
    assert loss_config["fixed"]["network_condition"] == "validation_loss"
    assert rate_config["fixed"]["secure_boot"] == "integrity_sha256"
    assert rate_config["matrix"] == {}
    assert (context.evidence_root / "configuration" / "rate" / "resolved-case.yaml").is_file()
    assert (context.evidence_root / "configuration" / "loss" / "resolved-case.yaml").is_file()
    with pytest.raises(FileExistsError):
        context.case(template="secure_boot", case_name="rate")
    with pytest.raises(ValueError):
        context.case(template="secure_boot", case_name="../other")


def test_experiment_failure_retains_command_logs(tmp_path, monkeypatch):
    context = _context(tmp_path)
    monkeypatch.setattr(support.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 17, "setup output", "setup error"))
    with pytest.raises(AssertionError, match="rc=17"):
        context.run_experiment(case=tmp_path / "case.yaml", name="failed")
    result = context.evidence_root / "failed"
    assert (result / "experiment.stdout.log").read_text(encoding="utf-8") == "setup output"
    assert (result / "experiment.stderr.log").read_text(encoding="utf-8") == "setup error"
    assert json.loads((result / "experiment.returncode.json").read_text(encoding="utf-8")) == {"return_code": 17}
