from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_campaign_executor_streams_long_running_experiment_output_to_durable_logs():
    source = (REPO_ROOT / "scripts/framework/campaign_executor.py").read_text(encoding="utf-8")
    assert "def _stream_command_to_log(" in source
    assert 'log_handle.write(line)' in source
    assert 'sys.stdout.write(line)' in source
    assert 'if runner is _default_runner:' in source
    assert '_stream_command_to_log(command, repo_root, log_path)' in source


def test_hardware_campaign_validation_uses_persistent_results_and_does_not_capture_subprocess_output():
    source = (REPO_ROOT / "tests/hardware/test_campaign_executor_hw.py").read_text(encoding="utf-8")
    assert 'REPO_ROOT / "results" / "hardware" / "request11-campaign"' in source
    assert "capture_output=True" not in source
    assert "persistent evidence:" in source
