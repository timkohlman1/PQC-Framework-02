"""Offline campaign control-flow tests with real disposable child processes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from framework.campaign_executor import CampaignError, CampaignExecutor, canonical_sha256
from framework.config_resolver import ConfigResolver
import run_campaign

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    executor = CampaignExecutor(REPO_ROOT, results_root=tmp_path / "results")
    resolver = executor.resolver
    source, data = resolver.load_campaign("tls_matrix_energy")
    data["execution"]["repetitions"] = 2
    cases = resolver.expand_campaign("tls_matrix_energy")[:2]
    monkeypatch.setattr(resolver, "load_campaign", lambda _: (source, data))
    monkeypatch.setattr(resolver, "expand_campaign", lambda _: cases)
    monkeypatch.setattr(resolver, "materialize_campaign", lambda _: tmp_path)
    monkeypatch.setattr(executor, "_case_path", lambda *args: tmp_path / "case.yaml")
    monkeypatch.setattr(resolver, "to_legacy_bundle", lambda case: ConfigResolver(REPO_ROOT).to_legacy_bundle(case, resolve_secrets=False))
    monkeypatch.setattr(executor, "_ensure_preparation", lambda **kwargs: (tmp_path / "prep.json", "firmware-sha"))
    monkeypatch.setattr(executor, "_ensure_broker", lambda **kwargs: None)
    cleanups = []
    monkeypatch.setattr(executor, "_stop_brokers", lambda *args: cleanups.append(True))
    monkeypatch.setattr("framework.network_degradation.apply_gateway_network_degradation", lambda **kwargs: (None, None))
    monkeypatch.setattr(run_campaign, "CampaignExecutor", lambda *args, **kwargs: executor)
    return executor, cases, cleanups


@pytest.mark.parametrize("failure", ["exit", "rejected", "missing", "malformed", "all"])
def test_failed_attempts_continue_across_groups_and_resume_preserves_evidence(campaign, failure, capsys):
    executor, cases, cleanups = campaign
    attempts = []
    retry = False

    def runner(command, cwd):
        def arg(name):
            return command[command.index(name) + 1]
        case_id = arg("--campaign-case-id")
        repetition = int(arg("--campaign-repetition-index"))
        attempts.append((case_id, repetition))
        failed = not retry and (failure == "all" or len(attempts) == 1)
        directory = Path(arg("--results-dir")) / f"attempt-{len(attempts)}"
        payload = {
            "run": {"return_code": 12 if failed and failure in {"exit", "all"} else 0},
            "final_index": {"status": "finalized"},
            "capture_acceptance": {"accepted": not failed},
            "configuration": {"campaign_execution": {
                "campaign_id": arg("--campaign-id"), "case_id": case_id,
                "condition_identity": arg("--campaign-condition-identity"),
                "repetition_index": repetition, "firmware_sha256": "firmware-sha",
            }},
        }
        script = """
import pathlib, sys
path = pathlib.Path(sys.argv[1]); path.mkdir(parents=True)
if sys.argv[3] != 'missing':
    (path / 'manifest.json').write_text(sys.argv[2] if sys.argv[3] != 'malformed' else '{')
print('disposable runtime child')
sys.exit(int(sys.argv[4]))
"""
        return subprocess.run([sys.executable, "-c", script, str(directory), json.dumps(payload),
                               failure if failed else "success", str(payload["run"]["return_code"])],
                              cwd=cwd, text=True, capture_output=True, check=False)

    executor.runner = runner
    assert run_campaign.main(["tls_matrix_energy"]) == 1
    console = capsys.readouterr().out
    assert "[Failed]" in console and "4/4" in console
    assert "disposable runtime child" not in console
    manifest = next(executor.results_root.glob("*/campaign-manifest.json"))
    state = json.loads(manifest.read_text())
    failed_count = 4 if failure == "all" else 1
    assert attempts == [(case["id"], rep) for case in cases for rep in (1, 2)]
    assert state["state"] == "completed_with_failures"
    assert state["summary"] == {"planned": 4, "completed": 4 - failed_count, "failed": failed_count, "blocked": 0}
    assert state["cleanup"]["status"] == "passed"
    assert state["final_index"]["sha256"] == canonical_sha256({k: v for k, v in state.items() if k != "final_index"})
    first_failure = state["runs"][0]
    assert first_failure["state"] == "failed"
    original_log = Path(first_failure["failure"]["log"])
    original_text = original_log.read_text()
    retry = True
    assert run_campaign.main(["--resume", str(manifest)]) == 0
    console = capsys.readouterr().out
    assert "4/4" in console
    if failure != "all":
        assert "[Skipped]" in console
    resumed = json.loads(manifest.read_text())
    assert len(attempts) == 4 + failed_count
    assert resumed["state"] == "completed"
    assert resumed["summary"]["failed"] == 0
    assert resumed["runs"][0]["previous_attempts"][0]["failure"] == first_failure["failure"]
    assert original_log.read_text() == original_text
    assert original_log.with_name(original_log.stem + "-attempt-2.log").exists()
    assert len(cleanups) == 2


def test_preparation_errors_block_groups_and_finish_matrix(campaign, monkeypatch):
    executor, _, cleanups = campaign
    def fail(**kwargs):
        raise CampaignError("preparation unavailable")
    monkeypatch.setattr(executor, "_ensure_preparation", fail)
    assert run_campaign.main(["tls_matrix_energy"]) == 1
    state = json.loads(next(executor.results_root.glob("*/campaign-manifest.json")).read_text())
    assert state["state"] == "completed_with_failures"
    assert len(state["runs"]) == 4
    assert all(run["state"] == "blocked" for run in state["runs"])
    assert state["summary"]["blocked"] == 4
    assert state["final_index"]["status"] == "finalized"
    assert len(cleanups) == 3


def test_keyboard_interrupt_is_not_swallowed(campaign):
    executor, _, cleanups = campaign
    def interrupt(*args):
        raise KeyboardInterrupt()
    executor.runner = interrupt
    with pytest.raises(KeyboardInterrupt):
        executor.execute("tls_matrix_energy")
    state = json.loads(next(executor.results_root.glob("*/campaign-manifest.json")).read_text())
    assert state["state"] == "failed"
    assert cleanups == [True]


def test_cleanup_failure_overrides_finished_matrix(campaign, monkeypatch):
    executor, _, _ = campaign
    executor.runner = lambda *args: subprocess.CompletedProcess(args[0], 12, stdout="failed runtime")
    monkeypatch.setattr(executor, "_stop_brokers", lambda *args: "broker cleanup failed")
    assert run_campaign.main(["tls_matrix_energy"]) == 1
    state = json.loads(next(executor.results_root.glob("*/campaign-manifest.json")).read_text())
    assert len(state["runs"]) == 4
    assert state["state"] == "failed"
    assert state["cleanup"]["status"] == "failed"
    assert "final_index" not in state


@pytest.mark.parametrize("failure_call", [1, 3])
def test_broker_setup_failure_blocks_remaining_group_and_runs_next(campaign, monkeypatch, failure_call):
    executor, cases, cleanups = campaign
    calls = 0
    runtime_cases = []
    def broker(**kwargs):
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise CampaignError("failed to start broker profile oqs-mtls")
    def runtime(**kwargs):
        runtime_cases.append(kwargs["case"]["id"])
        path = kwargs["campaign_root"] / f"runtime-{len(runtime_cases)}" / "manifest.json"
        path.parent.mkdir()
        path.write_text(json.dumps({
            "run": {"return_code": 0}, "final_index": {"status": "finalized"},
            "capture_acceptance": {"accepted": True},
            "configuration": {"campaign_execution": {
                "campaign_id": kwargs["campaign_id"], "case_id": kwargs["case"]["id"],
                "condition_identity": kwargs["cid"], "repetition_index": kwargs["repetition"],
                "firmware_sha256": kwargs["firmware_sha256"],
            }},
        }))
        return path
    monkeypatch.setattr(executor, "_ensure_broker", broker)
    monkeypatch.setattr(executor, "_run_repetition", runtime)
    manifest = executor.execute("tls_matrix_energy")
    state = json.loads(manifest.read_text())
    assert state["state"] == "completed_with_failures"
    blocked = 2 if failure_call == 1 else 1
    assert state["summary"] == {"planned": 4, "completed": 4-blocked, "failed": 0, "blocked": blocked}
    assert runtime_cases[-2:] == [cases[1]["id"], cases[1]["id"]]
    blocked_runs = [run for run in state["runs"] if run["state"] == "blocked"]
    assert all(run["manifest"] is None and run["failure"]["runtime_started"] is False for run in blocked_runs)
    assert len(cleanups) == 2  # Between groups and final cleanup.
    executor.execute("tls_matrix_energy", resume_manifest=manifest)
    resumed = json.loads(manifest.read_text())
    assert resumed["state"] == "completed"
    assert resumed["summary"]["blocked"] == 0


def test_broker_failure_with_failed_cleanup_does_not_start_next_group(campaign, monkeypatch):
    executor, _, _ = campaign
    calls = []
    def broker(**kwargs):
        calls.append(True)
        raise CampaignError("failed to start broker profile oqs-mtls")
    monkeypatch.setattr(executor, "_ensure_broker", broker)
    monkeypatch.setattr(executor, "_stop_brokers", lambda *args: "broker cleanup failed")
    with pytest.raises(CampaignError, match="broker cleanup failed"):
        executor.execute("tls_matrix_energy")
    assert calls == [True]
    state = json.loads(next(executor.results_root.glob("*/campaign-manifest.json")).read_text())
    assert state["state"] == "failed"
    assert state["cleanup"]["status"] == "failed"
