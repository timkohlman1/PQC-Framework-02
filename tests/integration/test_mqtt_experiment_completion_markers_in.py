from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_CLI = REPO_ROOT / "scripts" / "experiment.py"

CASE_MARKERS = (
    ("baseline", 0, "PQC_EXPERIMENT_COMPLETE experiment=classical_tls_server_auth status=done"),
    ("tls_authentication", 1, "PQC_EXPERIMENT_COMPLETE experiment=classical_tls_mutual status=done"),
    ("tls_key_exchange", 4, "PQC_EXPERIMENT_COMPLETE experiment=pqc_hybrid_tls_server_auth status=done"),
    ("tls_pq_only", 1, "PQC_EXPERIMENT_COMPLETE experiment=pqc_tls_mutual status=done"),
)

def _load_experiment_module():
    spec = importlib.util.spec_from_file_location("experiment_completion_marker_integration", EXPERIMENT_CLI)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

@pytest.mark.integration
@pytest.mark.parametrize(("campaign_id", "case_offset", "expected_marker"), CASE_MARKERS)
def test_experiment_bundle_resolves_matching_completion_marker(campaign_id: str, case_offset: int, expected_marker: str):
    cli = _load_experiment_module()
    from framework.config_resolver import ConfigResolver
    resolver = ConfigResolver(REPO_ROOT)
    case = resolver.expand_campaign(campaign_id)[case_offset]
    bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
    assert cli._mqtt_completion_marker(bundle) == expected_marker
    assert expected_marker in cli._mqtt_e2e_required_uart_markers(bundle)

@pytest.mark.integration
@pytest.mark.parametrize(("boot_args", "expected_mode", "expected_algorithm"), (
    (["--boot-mode", "direct_flash"], "direct_flash", None),
    (["--boot-mode", "wolfboot", "--boot-algorithm", "integrity_sha256"], "wolfboot", "integrity_sha256"),
    (["--boot-mode", "wolfboot", "--boot-algorithm", "mldsa65"], "wolfboot", "mldsa65"),
))
def test_run_parser_accepts_direct_and_secure_boot_matrix(boot_args: list[str], expected_mode: str, expected_algorithm: str | None):
    cli = _load_experiment_module()
    args = cli.build_arg_parser().parse_args(["run", "--experiment", ".pqc-generated-state/campaigns/baseline/cases/0001_baseline.yaml", *boot_args])
    assert args.boot_mode == expected_mode
    assert args.boot_algorithm == expected_algorithm
