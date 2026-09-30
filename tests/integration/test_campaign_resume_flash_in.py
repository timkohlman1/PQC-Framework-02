"""Offline resume restoration checks; no gateway or hardware commands are run."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from framework.campaign_executor import CampaignError, CampaignExecutor, RepetitionError
from framework.config_resolver import ConfigResolver
from test_campaign_continue_in import campaign

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def preparation(path, identity, sha):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "run": {"return_code": 0}, "final_index": {"status": "finalized"},
        "configuration": {"firmware_identity": identity}, "firmware": {"sha256": sha},
    }))


@pytest.mark.parametrize("force,return_code", [(False, 0), (True, 0), (True, 42)])
def test_saved_preparation_reenters_flash_path_only_when_forced(tmp_path, monkeypatch, force, return_code):
    case = ConfigResolver(ROOT).expand_campaign("tls_matrix_energy")[0]
    identity = case["provenance"]["firmware_identity"]
    old = tmp_path / "old" / "manifest.json"
    preparation(old, identity, "old-sha")
    state = {"firmware_groups": [{"preparation_manifest": str(old), "validated_firmware_sha256": "old-sha"}]}
    calls = []

    def runner(command, cwd):
        calls.append(command)
        assert command[2] == "run"
        assert "--runtime-only" not in command
        assert "--prepare-only" in command
        out = Path(command[command.index("--results-dir") + 1]) / "new" / "manifest.json"
        script = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True); p.write_text(sys.argv[2]); sys.exit(int(sys.argv[3]))"
        payload = {"run": {"return_code": return_code}, "final_index": {"status": "finalized"},
                   "configuration": {"firmware_identity": identity}, "firmware": {"sha256": "new-sha"}}
        return subprocess.run([sys.executable, "-c", script, str(out), json.dumps(payload), str(return_code)],
                              text=True, capture_output=True, check=False)

    monkeypatch.setattr("framework.campaign_executor._materialize_preparation_case", lambda **kwargs: None)
    executor = CampaignExecutor(ROOT, runner=runner)
    kwargs = dict(campaign_root=tmp_path, generated_root=tmp_path, state=state,
                  manifest_path=tmp_path / "campaign-manifest.json", group_index=1,
                  representative=case, firmware_identity=identity, force_reflash=force)
    if return_code:
        with pytest.raises(CampaignError, match="firmware preparation failed"):
            executor._ensure_preparation(**kwargs)
        assert state["firmware_groups"][0]["preparation_manifest"] is None
    else:
        _, sha = executor._ensure_preparation(**kwargs)
        assert sha == ("new-sha" if force else "old-sha")
    assert len(calls) == int(force)
    if force:
        assert state["firmware_groups"][0]["previous_preparations"][0]["manifest"] == str(old)
    assert json.loads(old.read_text())["firmware"]["sha256"] == "old-sha"


@pytest.mark.parametrize("changed_sha", [False, True])
def test_resume_restores_pending_group_before_runtime_and_skips_completed_group(campaign, monkeypatch, changed_sha):
    executor, cases, _ = campaign
    events = []
    attempt = 0

    def prepare(**kwargs):
        force = kwargs.get("force_reflash", False)
        group = kwargs["state"]["firmware_groups"][kwargs["group_index"] - 1]
        sha = "new-sha" if force and changed_sha else "old-sha"
        path = kwargs["campaign_root"] / f"prep-{kwargs['group_index']}-{force}" / "manifest.json"
        preparation(path, kwargs["firmware_identity"], sha)
        group["preparation_manifest"] = str(path)
        events.append(("flash", kwargs["group_index"], force))
        return path, sha

    def runtime(**kwargs):
        nonlocal attempt
        attempt += 1
        events.append(("runtime", kwargs["case"]["id"], kwargs["repetition"]))
        if attempt == 1:
            raise RepetitionError("runtime failed", manifest=None, return_code=12, log=kwargs["campaign_root"] / "failure.log")
        path = kwargs["campaign_root"] / f"run-{attempt}" / "manifest.json"
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

    monkeypatch.setattr(executor, "_ensure_preparation", prepare)
    monkeypatch.setattr(executor, "_run_repetition", runtime)
    manifest = executor.execute("tls_matrix_energy")
    events.clear()
    executor.execute("tls_matrix_energy", resume_manifest=manifest)
    assert events[0] == ("flash", 1, True)
    assert [event for event in events if event[0] == "flash"] == [("flash", 1, True)]
    assert len([event for event in events if event[0] == "runtime"]) == (2 if changed_sha else 1)
    assert json.loads(manifest.read_text())["state"] == "completed"
    events.clear()
    executor.execute("tls_matrix_energy", resume_manifest=manifest)
    assert events == []  # A fully validated finished campaign never touches the board.


def test_resume_flash_failure_blocks_runtime(campaign, monkeypatch, capsys):
    executor, _, _ = campaign
    def fail(**kwargs):
        assert kwargs["force_reflash"] is False
        raise CampaignError("first preparation failed")
    monkeypatch.setattr(executor, "_ensure_preparation", fail)
    executor.execute("tls_matrix_energy")
    manifest = next(executor.results_root.glob("*/campaign-manifest.json"))
    def flash_fail(**kwargs):
        assert kwargs["force_reflash"] is True
        raise CampaignError("flash failed")
    monkeypatch.setattr(executor, "_ensure_preparation", flash_fail)
    monkeypatch.setattr(executor, "_run_repetition", lambda **kwargs: pytest.fail("runtime must not start"))
    executor.execute("tls_matrix_energy", resume_manifest=manifest)
    state = json.loads(manifest.read_text())
    assert state["state"] == "completed_with_failures"
    assert state["summary"]["blocked"] == 4
    console = capsys.readouterr().out
    assert "[Blocked] 4/4" in console
