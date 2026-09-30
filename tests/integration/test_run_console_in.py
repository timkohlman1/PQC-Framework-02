"""Actual child streams and retained transcripts, with no gateway/hardware calls."""
import hashlib
import json
import os
import signal
import time
from pathlib import Path
import subprocess
import sys

import pytest

from framework.campaign_executor import _stream_command_to_log
from framework.run_console import RunStatus
import collect_thesis_evidence as driver

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("code", [0, 7])
def test_experiment_cli_transcript_is_in_sealed_inventory(tmp_path, code):
    child = r'''from pathlib import Path
import sys
import experiment
from framework.config_resolver import ConfigResolver
from framework.manifest import create_result_folder, finalize_run_evidence
root, destination, code = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
resolver = ConfigResolver(root)
case = resolver.expand_campaign("baseline")[0]
bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
def fake_run(args):
    result, manifest = create_result_folder(bundle, destination)
    experiment._report_experiment_start(bundle, manifest["run_id"])
    print("durable stdout details")
    print("durable stderr details", file=sys.stderr)
    finalize_run_evidence(result / "manifest.json")
    return code
experiment.run_full_baseline_command = fake_run
raise SystemExit(experiment.main(["run", "--experiment", "unused.yaml"]))
'''
    result = subprocess.run([sys.executable, "-c", child, str(ROOT), str(tmp_path), str(code)],
                            env={**os.environ, "PYTHONPATH": str(ROOT / "scripts"), "PQC_PROGRESS_TTY": "0"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == code, result.stdout + result.stderr
    assert len(result.stdout.splitlines()) == 1
    assert ("[Success]" if code == 0 else "[Failed]") in result.stdout
    assert not result.stderr
    manifest_path = next(tmp_path.glob("*/manifest.json"))
    transcript = manifest_path.parent / "console.log"
    assert "durable stdout details" in transcript.read_text()
    assert "durable stderr details" in transcript.read_text()
    manifest = json.loads(manifest_path.read_text())
    record = next(r for r in manifest["retained_files"] if r["path"] == "console.log")
    assert record["sha256"] == hashlib.sha256(transcript.read_bytes()).hexdigest()


def test_campaign_parent_keeps_details_in_file_and_receives_actual_run_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PQC_PROGRESS_TTY", "0")
    progress = RunStatus()
    progress.start("pending", 0, 20)
    log = tmp_path / "preparation.log"
    child = "import sys; print('  Run ID: 2026-09-30_001_actual', flush=True); print('verbose child details'); print('stderr details', file=sys.stderr); sys.exit(4)"
    result = _stream_command_to_log([sys.executable, "-c", child], ROOT, log, progress)
    assert result.returncode == 4
    assert progress.run_id == "2026-09-30_001_actual"
    assert capsys.readouterr().out == ""
    progress.finish("Failed", done=1)
    assert "actual [Failed] 1/20" in capsys.readouterr().out
    assert "verbose child details" in log.read_text()
    assert "stderr details" in log.read_text()
    assert "return_code=4" in log.read_text()


def test_host_collector_preserves_in_place_updates_through_pipe(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(driver, "terminal_environment", lambda: {"PQC_PROGRESS_TTY": "1", "PQC_PROGRESS_COLUMNS": "120"})
    log = tmp_path / "collector.log"
    child = "from framework.run_console import RunStatus; r=RunStatus(); r.start('actual', 0, 20); r.finish('Success', done=1)"
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "scripts"))
    assert driver.run_command([sys.executable, "-c", child], log) == 0
    output = capsys.readouterr().out
    assert output.count("\r\x1b[2K") == 2
    assert output.count("\n") == 1
    assert log.read_bytes() == output.encode()


@pytest.mark.parametrize("layer", ["campaign", "collector"])
def test_interrupt_drains_child_cleanup_before_waiting(tmp_path, layer):
    log = tmp_path / "child.log"
    child = """import sys,time
try:
    print('READY', flush=True)
    time.sleep(60)
except KeyboardInterrupt:
    print('cleanup-' * 30000, flush=True)
    print('CLEANUP_DONE', flush=True)
    sys.exit(130)
"""
    parent = r'''import sys
from pathlib import Path
from framework.campaign_executor import _stream_command_to_log
from collect_thesis_evidence import run_command
command = [sys.executable, "-c", sys.argv[3]]
try:
    if sys.argv[1] == "campaign":
        _stream_command_to_log(command, Path.cwd(), Path(sys.argv[2]))
    else:
        run_command(command, Path(sys.argv[2]))
except KeyboardInterrupt:
    sys.exit(130)
'''
    env = {**os.environ, "PYTHONPATH": str(ROOT / "scripts"), "PQC_PROGRESS_TTY": "0"}
    # Send SIGINT only to this test-owned parent; it must forward cancellation.
    # Write the parent's output to a file so the test itself adds no pipe limit.
    with (tmp_path / "parent.log").open("wb") as output:
        process = subprocess.Popen([sys.executable, "-c", parent, layer, str(log), child],
                                   cwd=ROOT, env=env, stdout=output, stderr=output,
                                   start_new_session=True)
        try:
            deadline = time.monotonic() + 15
            while not log.exists() or b"READY" not in log.read_bytes():
                assert process.poll() is None, (tmp_path / "parent.log").read_text()
                assert time.monotonic() < deadline, "child did not become ready"
                time.sleep(0.02)
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=15) == 130
            assert "CLEANUP_DONE" in log.read_text()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
