"""Source-only checks for secure-boot hardware-test preparation and retained evidence."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
HARDWARE = ROOT / "tests/hardware/test_secure_boot_flash_workflow_hw.py"


def _module():
    spec = importlib.util.spec_from_file_location("secure_boot_flash_hw_support_under_test", HARDWARE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_import_does_not_materialize_global_campaigns(monkeypatch):
    from framework.config_resolver import ConfigResolver

    def fail_if_called(*args, **kwargs):
        raise AssertionError("case generated before hardware capability checks")

    monkeypatch.setattr(ConfigResolver, "materialize_campaign", fail_if_called)
    _module()


@pytest.mark.parametrize("algorithm", ["ecdsa_p256", "integrity_sha256"])
def test_case_generation_is_algorithm_specific_and_retained(monkeypatch, tmp_path, algorithm):
    module = _module()
    repo = tmp_path / "repo"
    source = repo / "configs/campaigns/secure_boot.yaml"
    source.parent.mkdir(parents=True)
    source.write_text(yaml.safe_dump({"id": "secure_boot", "matrix": {"secure_boot": ["ecdsa_p256", "integrity_sha256"]}, "fixed": {"network_condition": "baseline"}}), encoding="utf-8")
    context = SimpleNamespace(repo_root=repo, generated_root=repo / ".pqc-generated-state/hardware-tests/module/testidentity", evidence_root=tmp_path / "results")
    context.generated_root.mkdir(parents=True)

    class FakeResolver:
        def __init__(self, root):
            assert root == repo

        def materialize_campaign(self, campaign_file, output_root):
            configuration = yaml.safe_load(Path(campaign_file).read_text(encoding="utf-8"))
            assert configuration["matrix"] == {}
            assert configuration["fixed"]["secure_boot"] == algorithm
            (output_root / "cases").mkdir(parents=True)
            (output_root / "cases/0001_selected.yaml").write_text(yaml.safe_dump({"choices": {"secure_boot": algorithm}}), encoding="utf-8")
            (output_root / "campaign-resolved.yaml").write_text("cases: 1\n", encoding="utf-8")
            return output_root

        def load_resolved_case(self, selected):
            return yaml.safe_load(Path(selected).read_text(encoding="utf-8"))

    monkeypatch.setattr(module, "ConfigResolver", FakeResolver)
    case = module._owned_secure_boot_case(context, algorithm)
    assert case.is_file()
    evidence = context.evidence_root / "configuration" / f"secure_boot_{algorithm}"
    assert (evidence / "campaign.yaml").is_file()
    assert (evidence / "resolved-case.yaml").read_bytes() == case.read_bytes()
    assert (evidence / "campaign-resolved.yaml").is_file()


def test_case_generator_rejects_unselected_profiles(tmp_path):
    with pytest.raises(ValueError, match="unsupported"):
        _module()._owned_secure_boot_case(SimpleNamespace(), "rsa4096")


def test_result_selection_is_bound_to_exact_cli_result(tmp_path):
    module = _module()
    requested_root = tmp_path / "result"
    own = requested_root / "own"
    own.mkdir(parents=True)
    (own / "manifest.json").write_text("{}", encoding="utf-8")
    completed = subprocess.CompletedProcess([], 0, stdout=f"Result directory: {own}\n", stderr="")
    assert module._cli_result_dir(completed, requested_root) == own
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(AssertionError, match="escaped requested results root"):
        module._cli_result_dir(subprocess.CompletedProcess([], 0, f"Result directory: {foreign}\n", ""), requested_root)
    with pytest.raises(AssertionError, match="Missing manifest"):
        module._cli_result_dir(subprocess.CompletedProcess([], 0, f"Result directory: {requested_root / 'missing'}\n", ""), requested_root)


def test_command_failure_retains_logs_and_return_code(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(module, "_run_command", lambda *a, **kw: subprocess.CompletedProcess([], 7, "out", "error"))
    evidence = tmp_path / "evidence"
    completed = module._run_cli(tmp_path, ["build-wolfboot"], evidence_dir=evidence, stage="build")
    assert completed.returncode == 7
    assert (evidence / "build.stdout.log").read_text() == "out"
    assert (evidence / "build.stderr.log").read_text() == "error"
    assert json.loads((evidence / "build.returncode.json").read_text())["return_code"] == 7
    assert json.loads((evidence / "build.command.json").read_text())["arguments"][-1] == "build-wolfboot"


def test_command_launch_error_retains_diagnostics(monkeypatch, tmp_path):
    module = _module()
    def failed(*args, **kwargs):
        raise OSError("launcher unavailable")
    monkeypatch.setattr(module, "_run_command", failed)
    with pytest.raises(OSError, match="launcher unavailable"):
        module._run_cli(tmp_path, ["build-wolfboot"], evidence_dir=tmp_path / "evidence", stage="build")
    assert "launcher unavailable" in (tmp_path / "evidence/build.launch-error.log").read_text()


def test_recorded_stlink_identity_must_be_present():
    module = _module()
    module._assert_flash_identity({"secure_boot_flash": {"stlink_serial": "lab-serial"}})
    for invalid in ("", " ", None):
        with pytest.raises(AssertionError):
            module._assert_flash_identity({"secure_boot_flash": {"stlink_serial": invalid}})


@pytest.mark.parametrize("algorithm", ["ecdsa_p256", "integrity_sha256"])
def test_negative_preparation_calls_accept_algorithm(monkeypatch, algorithm, tmp_path):
    """Exercise the real negative-test preparation sequence, not just a helper mock."""
    module = _module()
    calls = []
    context = SimpleNamespace(
        evidence_root=tmp_path / "evidence", repo_root=tmp_path,
        generated_root=tmp_path / "generated",
    )
    (context.evidence_root / "negative").mkdir(parents=True)
    (context.evidence_root / "restoration").mkdir(parents=True)
    (tmp_path / "configs/secure_boot").mkdir(parents=True)
    (tmp_path / f"configs/secure_boot/{algorithm}.yaml").write_text("id: test\n")
    monkeypatch.setattr(module, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "session_result_dir", lambda cfg: tmp_path)
    monkeypatch.setattr(module.HardwareFileRun, "create", lambda **kw: context)
    context.case = lambda **kw: tmp_path / "baseline.yaml"
    monkeypatch.setattr(module, "_owned_secure_boot_case", lambda *a: tmp_path / "secureboot.yaml")
    monkeypatch.setattr(module, "_prepare_instrumented_wolfboot", lambda *a, **kw: calls.append(("wolfboot", a, kw)))
    monkeypatch.setattr(module, "_prepare_signed_secure_boot_application", lambda *a, **kw: calls.append(("sign", a, kw)))
    # Stop at the first flash command, after both real test-body preparation calls.
    def stop_at_flash(*a, **kw):
        assert calls[0][0] == "wolfboot"
        assert calls[0][1] == (tmp_path, context.evidence_root / "secure-boot-cli", algorithm)
        assert calls[1][0] == "sign"
        assert calls[1][1] == (tmp_path, context.evidence_root / "secure-boot-cli", tmp_path / "baseline.yaml", algorithm)
        raise RuntimeError("preparation complete")
    monkeypatch.setattr(module, "_run_cli", stop_at_flash)
    monkeypatch.setattr(module, "_restore_valid_secure_boot_application", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("restoration intentionally blocked")))
    with pytest.raises(AssertionError, match="negative-path validation AND restoration failed"):
        module.test_secure_boot_negative_corrupted_application_then_restore_workflow(
            None, lambda *a, **kw: None, algorithm
        )


def _positive_fixture(tmp_path):
    root = tmp_path / "flash"
    root.mkdir()
    digest = "a" * 64
    (root / "manifest.json").write_text(json.dumps({
        "run": {"state": "finalized", "return_code": 0, "failure_stage": "none"},
        "execution_outcome": {"failure_stage": "none", "result": "secure_boot_positive_boot_evidence_passed"},
        "final_index": {"status": "finalized"},
        "artifacts": [
            {"artifact_id": kind, "acquisition": {"status": "available"}, "sha256": digest}
            for kind in ("wolfboot_image", "signed_application")
        ],
    }))
    capture = {
        "schema": "pqc-secure-boot-flash-capture-v1", "boot_crypto": "ecdsa_p256",
        "flash_return_code": 0, "capture_completed": True,
        "negative_requested": False, "boot_marker_present": True,
        "secure_boot_marker_present": True, "tick_present": True,
        "result": "secure_boot_positive_boot_evidence_passed",
        "negative_test": {"original_signed_application_sha256": digest},
    }
    (root / "secure-boot-flash-capture.json").write_text(json.dumps(capture))
    (root / "secure_boot_flash.log").write_text("Download verified successfully\n" * 2)
    (root / "uart.log").write_text("\n".join([
        "[tick=0000000002] wolfBoot integrity valid: 1",
        "wolfBoot integrity result: 0", "wolfBoot authenticity valid: 1",
        "wolfBoot authenticity result: 0", "stm32-basic_hal1 secure-boot app v0.1.0",
        "stm32-basic_hal1 boot v0.1.0",
    ]))
    return root


def test_positive_flash_requires_cli_success_and_independent_boot_evidence(tmp_path):
    module = _module()
    root = _positive_fixture(tmp_path)
    outcome = subprocess.CompletedProcess([], 0, "", "")
    module._assert_positive_flash_evidence(outcome, root)
    with pytest.raises(AssertionError):
        module._assert_positive_flash_evidence(subprocess.CompletedProcess([], 8, "", ""), root)
    with pytest.raises(AssertionError):
        module._assert_positive_flash_evidence(subprocess.CompletedProcess([], 9, "", ""), root)
    (root / "uart.log").write_text("stm32-basic_hal1 boot v0.1.0")
    with pytest.raises(AssertionError, match="Missing current-run secure-boot evidence"):
        module._assert_positive_flash_evidence(outcome, root)


def test_positive_flash_rejects_failed_manifest_or_unverified_flash(tmp_path):
    module = _module()
    root = _positive_fixture(tmp_path)
    outcome = subprocess.CompletedProcess([], 0, "", "")
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["run"]["failure_stage"] = "flash"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(AssertionError):
        module._assert_positive_flash_evidence(outcome, root)
    manifest["run"]["failure_stage"] = "none"
    (root / "manifest.json").write_text(json.dumps(manifest))
    capture = json.loads((root / "secure-boot-flash-capture.json").read_text())
    capture["flash_return_code"] = 1
    (root / "secure-boot-flash-capture.json").write_text(json.dumps(capture))
    with pytest.raises(AssertionError):
        module._assert_positive_flash_evidence(outcome, root)
