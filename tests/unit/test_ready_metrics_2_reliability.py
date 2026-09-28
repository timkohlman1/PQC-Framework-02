from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def reliability():
    path = Path(__file__).resolve().parents[2] / "scripts/ready_metrics_2_reliability_v2.py"
    spec = importlib.util.spec_from_file_location("rm2_reliability", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest():
    return {"run": {"return_code": 0, "failure_stage": "none"},
            "execution_outcome": {"status": "completed"},
            "capture_acceptance": {"accepted": True},
            "final_index": {"status": "finalized"}}


def trial(tmp_path, content=b"ready\n", data=None):
    result = tmp_path / "sample" / "run-id"
    result.mkdir(parents=True)
    (result / "manifest.json").write_text(json.dumps(data if data is not None else manifest()))
    if content is not None:
        (result / "uart.log").write_bytes(content)
    return result.parent


def test_success_requires_process_and_manifest_agreement(reliability):
    data = manifest()
    assert reliability.success_from_manifest(data, 0)[0]
    assert not reliability.success_from_manifest(data, 1)[0]
    for key, value in (("run", {"return_code": 1}),
                       ("execution_outcome", {"status": "failed"}),
                       ("capture_acceptance", {"accepted": False}),
                       ("final_index", {"status": "pending"})):
        assert not reliability.success_from_manifest({**data, key: value}, 0)[0]
    assert not reliability.success_from_manifest({}, 0)[0]


def test_explicit_legacy_verdict_supported_but_unknown_format_fails(reliability):
    data = {"run": {"return_code": 0}, "result": "baseline_run_passed"}
    assert reliability.success_from_manifest(data, 0)[0]
    data["result"] = "build_passed"
    assert not reliability.success_from_manifest(data, 0)[0]


@pytest.mark.parametrize("content, expected", [
    (b"[ERROR] transport\n", True), (b"\xff ERROR: failed", True),
    (b"error ERRORS NO_ERROR", False), (b"", None), (None, None),
])
def test_error_word_and_missing_uart(reliability, tmp_path, content, expected):
    row = reliability.inspect_trial(trial(tmp_path, content), 0)
    assert row["uart_has_ERROR"] is expected
    assert row["success"] is True  # UART diagnostics are a separate statistic.


def test_failed_trial_still_scans_uart_and_ignores_other_logs(reliability, tmp_path):
    directory = trial(tmp_path, b"all fine")
    (directory / "run-id" / "build.log").write_text("ERROR")
    row = reliability.inspect_trial(directory, 1)
    assert not row["success"]
    assert row["uart_has_ERROR"] is False
    (directory / "run-id" / "uart.log").write_text("ERROR")
    assert reliability.inspect_trial(directory, 1)["uart_has_ERROR"] is True


def test_missing_and_ambiguous_manifests_fail_closed(reliability, tmp_path):
    assert not reliability.inspect_trial(tmp_path, 0)["success"]
    directory = trial(tmp_path)
    second = directory / "other"
    second.mkdir()
    (second / "manifest.json").write_text(json.dumps(manifest()))
    row = reliability.inspect_trial(directory, 0)
    assert not row["success"] and row["uart_has_ERROR"] is None


def test_invalid_manifest_does_not_hide_error_capture(reliability, tmp_path):
    directory = trial(tmp_path, b"ERROR")
    (directory / "run-id" / "manifest.json").write_text("{bad json")
    row = reliability.inspect_trial(directory, 0)
    assert not row["success"] and row["uart_has_ERROR"] is True


def test_uart_symlink_is_not_followed(reliability, tmp_path):
    directory = trial(tmp_path, None)
    target = tmp_path / "outside.log"
    target.write_text("ERROR")
    (directory / "run-id" / "uart.log").symlink_to(target)
    assert reliability.inspect_trial(directory, 0)["uart_has_ERROR"] is None


def test_percentages_include_failed_trials_and_expose_unknowns(reliability, tmp_path):
    summary = {"trials": [
        {"success": True, "uart_has_ERROR": False},
        {"success": False, "uart_has_ERROR": True},
        {"success": False, "uart_has_ERROR": None},
    ]}
    reliability.save_summary(tmp_path, summary)
    saved = json.loads((tmp_path / "summary.json").read_text())
    assert saved["success_percent"] == pytest.approx(100 / 3)
    assert saved["UART_ERROR_percent_of_attempted"] == pytest.approx(100 / 3)
    assert saved["UART_ERROR_percent_of_known"] == 50
    assert saved["UART_unknown_runs"] == 1


def test_empty_summary_has_no_invented_zero_rates(reliability, tmp_path):
    summary = {"trials": []}
    reliability.save_summary(tmp_path, summary)
    assert summary["success_percent"] is None
    assert summary["UART_ERROR_percent_of_attempted"] is None


def test_purge_includes_stopped_containers_and_named_volumes(reliability, monkeypatch, tmp_path):
    calls = []
    def fake(argv, root, **kwargs):
        calls.append(argv)
        stdout = "container1\n" if argv[1:3] == ["ps", "-aq"] else ""
        if argv[1:4] == ["volume", "ls", "-q"]:
            stdout = "named-volume\n"
        return subprocess.CompletedProcess(argv, 0, stdout=stdout)
    monkeypatch.setattr(reliability, "command", fake)
    reliability.purge_docker(tmp_path)
    assert calls.index(["docker", "rm", "-f", "container1"]) < calls.index(["docker", "volume", "rm", "named-volume"])
    assert ["docker", "builder", "prune", "--all", "--force"] in calls


def test_remote_docker_is_refused_before_cleanup(reliability, monkeypatch, tmp_path):
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_HOST", "ssh://gateway")
    monkeypatch.setattr(reliability, "command", lambda *a, **kw: pytest.fail("must not execute commands"))
    with pytest.raises(ValueError, match="local"):
        reliability.require_local_docker(tmp_path)


def test_context_takes_precedence_over_docker_host(reliability, monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_CONTEXT", "remote")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    def fake(argv, root, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout="remote" if argv[-1] == "show" else "tcp://gateway:2376")
    monkeypatch.setattr(reliability, "command", fake)
    with pytest.raises(ValueError, match="local"):
        reliability.require_local_docker(tmp_path)


def test_clear_root_rejects_symlink_before_any_commands(reliability, tmp_path):
    for path in ("scripts/dev.sh", "scripts/resolve_campaign.py", "scripts/provision_certificates.py",
                 "scripts/experiment.py", "docker/python/Dockerfile", reliability.CAMPAIGN_PATH):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    (tmp_path / "secrets").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="symlink"):
        reliability.validate_root(tmp_path)


def test_previous_results_are_not_reused_when_no_new_manifest(reliability, tmp_path):
    directory = trial(tmp_path, b"ERROR")
    previous = set(directory.glob("*/manifest.json"))
    row = reliability.inspect_trial(directory, 0, previous)
    assert not row["success"] and row["uart_has_ERROR"] is None
    assert "found 0" in row["reason"]


def test_preflight_uses_campaign_directory_not_bare_filename(reliability, tmp_path):
    for relative in ("scripts/dev.sh", "scripts/resolve_campaign.py",
                     "scripts/provision_certificates.py", "scripts/experiment.py",
                     "docker/python/Dockerfile", "configs/campaigns/ready_metrics_2.yaml"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    reliability.validate_root(tmp_path)
    assert not (tmp_path / "ready_metrics_2.yaml").exists()
    (tmp_path / "configs/campaigns/ready_metrics_2.yaml").unlink()
    (tmp_path / "ready_metrics_2.yaml").touch()
    with pytest.raises(ValueError, match="configs/campaigns/ready_metrics_2.yaml"):
        reliability.validate_root(tmp_path)
