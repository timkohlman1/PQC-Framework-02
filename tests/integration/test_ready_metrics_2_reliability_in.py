"""Real subprocess orchestration with disposable command shims; no Docker/hardware."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ready_metrics_2_reliability_v2.py"


def executable(path, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n" + source)
    path.chmod(0o755)


@pytest.fixture
def laboratory(tmp_path):
    root = tmp_path / "repo"
    binary = tmp_path / "bin"
    ledger = tmp_path / "commands.jsonl"
    env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
               RM2_TEST_LEDGER=str(ledger), RM2_TEST_SCRIPTS=str(SCRIPT.parent), DOCKER_HOST="unix:///fake-docker.sock")
    env.pop("DOCKER_CONTEXT", None)
    prefix = '''import json, os, pathlib, sys
args = sys.argv[1:]
root = pathlib.Path.cwd()
with open(os.environ["RM2_TEST_LEDGER"], "a") as stream:
    stream.write(json.dumps([pathlib.Path(sys.argv[0]).name, *args]) + "\\n")
'''
    executable(binary / "sudo", prefix + '''
if args[:2] == ["find", "-P"]:
    target = pathlib.Path(args[2])
    assert target.parent == root
    import shutil
    for item in target.iterdir():
        if item.is_dir() and not item.is_symlink(): shutil.rmtree(item)
        else: item.unlink()
elif args[:2] == ["mkdir", "-p"]:
    pathlib.Path(args[-1]).mkdir(parents=True, exist_ok=True)
''')
    executable(binary / "docker", prefix + '''
if args == ["info"] and os.environ.get("RM2_FAIL_SETUP") == "docker":
    raise SystemExit(9)
if args == ["ps", "-aq"]: print("old-container")
if args == ["volume", "ls", "-q"]: print("old-volume")
''')
    executable(root / "scripts/dev.sh", prefix + '''
if args[:2] == ["python", "scripts/resolve_campaign.py"]:
    if os.environ.get("RM2_FAIL_SETUP") == "resolver":
        raise SystemExit(9)
    assert args[2:] == ["ready_metrics_2.yaml"], args
    cases = root / ".pqc-generated-state/campaigns/ready_metrics_2/cases"
    cases.mkdir(parents=True)
    for name in ("0002_second.yaml", "0001_first.yaml"):
        (cases / name).write_text("execution: {repetitions: 7}\\n")
if args[:2] == ["experiment-gateway", "run"]:
    directory = root / args[args.index("--results-dir") + 1]
    calls = [json.loads(line) for line in pathlib.Path(os.environ["RM2_TEST_LEDGER"]).read_text().splitlines()]
    index = sum(call[:3] == ["dev.sh", "experiment-gateway", "run"] for call in calls)
    if index == 3: raise SystemExit(4)  # failure before a result is created
    if os.environ.get("RM2_TEST_INTERRUPT"):
        import signal
        os.kill(os.getppid(), signal.SIGINT)
        raise SystemExit(130)
    sys.path.insert(0, os.environ["RM2_TEST_SCRIPTS"])
    from framework.manifest import next_run_id
    from datetime import datetime, timezone
    run = directory / next_run_id("ready_metrics_2", directory, datetime(2026, 1, 1, tzinfo=timezone.utc))
    run.mkdir()
    data = {"run": {"return_code": 0 if index == 1 else 1},
            "execution_outcome": {"status": "completed" if index == 1 else "failed"},
            "capture_acceptance": {"accepted": index == 1},
            "final_index": {"status": "finalized"}}
    (run / "manifest.json").write_text(json.dumps(data))
    (run / "uart.log").write_text("ready\\n" if index == 1 else "[ERROR] fault\\n")
    raise SystemExit(0 if index == 1 else 1)
''')
    executable(root / "scripts/provision_certificates.py", prefix)
    for relative in ("scripts/experiment.py", "scripts/resolve_campaign.py",
                     "docker/python/Dockerfile", "configs/campaigns/ready_metrics_2.yaml"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    for name in (".pqc-generated-state", "build", "results", "secrets"):
        directory = root / name
        directory.mkdir()
        (directory / ".old").write_text("disposable test content")
    # Patch only the root-user guard so this subprocess fixture also works in
    # the root-run development container. All command launches are real.
    driver = "import os, runpy; os.geteuid = lambda: 1000; runpy.run_path(" + repr(str(SCRIPT)) + ", run_name='__main__')"
    return root, env, ledger, [sys.executable, "-c", driver, "--repo-root", str(root)]


def test_independent_processes_first_case_failure_continuation_and_rates(laboratory):
    root, env, ledger, cli = laboratory
    completed = subprocess.run([*cli, "--execute", "--runs", "3"], env=env, capture_output=True, text=True)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    summary = json.loads(next((root / "results/reliability").glob("*/summary.json")).read_text())
    assert summary["attempted_runs"] == 3 and summary["requested_runs"] == 3
    assert summary["success_percent"] == pytest.approx(100 / 3)
    assert summary["UART_ERROR_percent_of_attempted"] == pytest.approx(100 / 3)
    assert summary["UART_unknown_runs"] == 1
    assert summary["resolved_case_count"] == 2
    commands = [json.loads(line) for line in ledger.read_text().splitlines()]
    runs = [cmd for cmd in commands if cmd[:3] == ["dev.sh", "experiment-gateway", "run"]]
    assert len(runs) == 3
    assert all(cmd[cmd.index("--experiment") + 1].endswith("0001_first.yaml") for cmd in runs)
    assert len({cmd[cmd.index("--results-dir") + 1] for cmd in runs}) == 1
    manifest_paths = [Path(row["manifest"]) for row in summary["trials"] if row["manifest"]]
    assert [path.parent.name for path in manifest_paths] == [
        "2026-01-01_001_ready_metrics_2", "2026-01-01_002_ready_metrics_2"]
    # The runner reuses the prepared workspace; reset/build/provision are disabled.
    assert ["dev.sh", "build-image"] not in commands
    assert ["provision_certificates.py"] not in commands
    assert [cmd for cmd in commands if cmd[0] == "docker"] == [["docker", "info"]]
    assert not any(cmd[0] == "sudo" for cmd in commands)
    assert all((root / name / ".old").read_text() == "disposable test content"
               for name in ("build", "results", "secrets", ".pqc-generated-state"))
    assert all("--runtime-only" not in cmd and "--prepare-only" not in cmd for cmd in runs)
    case = root / summary["selected_case"]
    assert "repetitions: 7" in case.read_text()  # never rewritten or executed as a campaign


def test_default_dry_run_and_invalid_count_have_no_side_effects(laboratory):
    root, env, ledger, cli = laboratory
    for arguments, code in (([], 0), (["--runs", "0"], 2)):
        completed = subprocess.run([*cli, *arguments], env=env, capture_output=True, text=True)
        assert completed.returncode == code
        assert not ledger.exists()
        assert (root / "secrets/.old").exists()


@pytest.mark.parametrize("failure_stage", ["docker", "resolver"])
def test_setup_failure_stops_before_trials(laboratory, failure_stage):
    root, env, ledger, cli = laboratory
    env["RM2_FAIL_SETUP"] = failure_stage
    completed = subprocess.run([*cli, "--execute"], env=env, capture_output=True, text=True)
    assert completed.returncode == 2, completed.stdout + completed.stderr
    calls = [json.loads(line) for line in ledger.read_text().splitlines()]
    expected = [["docker", "info"]]
    if failure_stage == "resolver":
        expected.append(["dev.sh", "python", "scripts/resolve_campaign.py", "ready_metrics_2.yaml"])
    assert calls == expected
    assert not (root / "results/reliability").exists()


def test_interrupt_keeps_partial_summary_and_stops_new_trials(laboratory):
    root, env, ledger, cli = laboratory
    env["RM2_TEST_INTERRUPT"] = "1"
    completed = subprocess.run([*cli, "--execute", "--runs", "3"], env=env, capture_output=True, text=True)
    assert completed.returncode == 130, completed.stdout + completed.stderr
    summary = json.loads(next((root / "results/reliability").glob("*/summary.json")).read_text())
    assert summary["status"] == "interrupted"
    assert summary["attempted_runs"] == 1
    commands = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert sum(cmd[:3] == ["dev.sh", "experiment-gateway", "run"] for cmd in commands) == 1


def test_campaign_argument_materializes_with_real_resolver(tmp_path):
    """Exercise the actual CLI; fake commands previously missed the doubled path."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("reliability_v2", SCRIPT)
    reliability = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reliability)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT.parent / "resolve_campaign.py"),
         reliability.CAMPAIGN, "--output-root", str(tmp_path / "resolved")],
        cwd=SCRIPT.parents[1], text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    cases = sorted((tmp_path / "resolved/cases").glob("*.yaml"))
    assert len(cases) == 1
    assert cases[0].name.startswith("0001_ready_metrics_2-")
