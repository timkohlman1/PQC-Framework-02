from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_runtime_only_parser_accepts_campaign_owned_reuse_controls():
    module_path = REPO_ROOT / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("campaign_runtime_in", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    args = module.build_arg_parser().parse_args([
        "run",
        "--experiment", ".pqc-generated-state/campaigns/baseline/cases/example.yaml",
        "--runtime-only",
        "--profile-preparation-manifest", "results/preparation/manifest.json",
        "--campaign-managed-broker",
        "--campaign-managed-condition",
        "--campaign-id", "baseline",
        "--campaign-case-id", "baseline-0001",
        "--campaign-condition-identity", "condition-sha",
        "--campaign-repetition-index", "3",
    ])
    assert args.runtime_only is True
    assert args.campaign_managed_broker is True
    assert args.campaign_managed_condition is True
    assert args.campaign_repetition_index == 3
    assert args.skip_hardware_reset is False


@pytest.mark.integration
def test_campaign_wrapper_commands_exist_on_linux():
    sh = (REPO_ROOT / "scripts/dev.sh").read_text(encoding="utf-8")
    assert "campaign-gateway)" in sh
    assert "campaign)" in sh
    assert "scripts/run_campaign.py" in sh
