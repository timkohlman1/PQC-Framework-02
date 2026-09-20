"""Source contracts for durable campaign execution and hardware-test evidence."""
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_campaign_executor_streams_long_running_experiment_output_to_durable_logs():
    source = (REPO_ROOT / "scripts/framework/campaign_executor.py").read_text(encoding="utf-8")
    assert "def _stream_command_to_log(" in source
    assert 'log_handle.write(line)' in source
    assert 'sys.stdout.write(line)' in source
    assert 'if runner is _default_runner:' in source
    assert '_stream_command_to_log(command, repo_root, log_path)' in source


def test_hardware_campaign_validation_owns_persistent_results_and_retains_subprocess_output():
    source = (REPO_ROOT / "tests/hardware/test_campaign_executor_hw.py").read_text(encoding="utf-8")

    # The file owns a fresh evidence directory within the persistent pytest run;
    # it must not reuse the legacy fixed location from a different test execution.
    assert "HardwareFileRun.create(" in source
    assert "session_result_dir(pytestconfig)" in source
    assert 'module_name="test_campaign_executor_hw"' in source
    assert 'results_root = context.evidence_root / "campaign-runs"' in source
    assert '"--results-root", str(results_root)' in source
    assert 'REPO_ROOT / "results" / "hardware" / "request11-campaign"' not in source

    # Capturing the short-lived CLI output is permitted when both streams and
    # its exit status are written to the test-owned evidence directory.
    assert 'capture_output=True' in source
    assert '(context.evidence_root / "campaign.stdout.log").write_text(completed.stdout' in source
    assert '(context.evidence_root / "campaign.stderr.log").write_text(completed.stderr' in source
    assert '(context.evidence_root / "campaign.returncode.json").write_text(' in source
    assert '"return_code": completed.returncode' in source

    # The functional test must still exercise distinct, retained repetitions.
    assert 'context.case(template="baseline", repetitions=2)' in source
    assert 'assert len(manifest["runs"]) == 2' in source
    assert 'assert len({run["manifest"] for run in manifest["runs"]}) == 2' in source
