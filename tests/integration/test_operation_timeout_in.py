"""Real disposable processes exercise timeout, cleanup grace and stalled pipes."""
import sys
import time
import subprocess
from pathlib import Path

import pytest
from framework.bounded_command import run, capture_command
from framework.campaign_executor import _stream_command_to_log, CampaignCleanupError

pytestmark = pytest.mark.integration


def test_control_timeout_retains_partial_output(tmp_path):
    result = run([sys.executable, '-u', '-c', "import time; print('partial evidence'); time.sleep(20)"],
                 cwd=tmp_path, timeout=.2)
    assert result.returncode == 125
    assert 'partial evidence' in result.stdout
    assert 'remote completion unverified' in result.stderr


def test_remote_deadline_bounds_publisher_wait_and_descendants(tmp_path):
    script = "sleep 20 & publisher=$!; wait $publisher"
    command = capture_command('unused', script, .2)
    start = time.monotonic()
    result = subprocess.run(['sh', '-c', command[-1]], capture_output=True, text=True, timeout=8)
    assert result.returncode == 124
    assert time.monotonic() - start < 7


def test_campaign_watchdog_allows_cleanup_but_requires_review(tmp_path, monkeypatch):
    monkeypatch.setenv('PQC_CAMPAIGN_OPERATION_TIMEOUT_SECONDS', '.3')
    script = "import time\ntry:\n print('started', flush=True); time.sleep(20)\nfinally:\n print('cleanup completed', flush=True)"
    with pytest.raises(CampaignCleanupError, match='Operation exceeded'):
        _stream_command_to_log([sys.executable, '-u', '-c', script], tmp_path, tmp_path/'command.log')
    assert 'cleanup completed' in (tmp_path/'command.log').read_text()


@pytest.mark.parametrize('module', ['packet_capture', 'result_collector', 'network_degradation'])
def test_cleanup_adapters_execute_real_bounded_commands(tmp_path, module):
    import importlib
    adapter = importlib.import_module('framework.' + module)
    result = adapter._run([sys.executable, '-c', "print('control complete')"], cwd=tmp_path)
    assert result.return_code == 0 and result.stdout.strip() == 'control complete'


def test_campaign_watchdog_kills_group_after_ignored_interrupt(tmp_path, monkeypatch):
    import framework.campaign_executor as executor
    timer = executor.threading.Timer
    monkeypatch.setattr(executor.threading, 'Timer',
                        lambda delay, callback: timer(.2 if delay == 90 else delay, callback))
    monkeypatch.setenv('PQC_CAMPAIGN_OPERATION_TIMEOUT_SECONDS', '.3')
    script = "import signal,time,subprocess,sys; signal.signal(signal.SIGINT, signal.SIG_IGN); subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); print('started',flush=True); time.sleep(20)"
    start = time.monotonic()
    with pytest.raises(CampaignCleanupError):
        _stream_command_to_log([sys.executable, '-u', '-c', script], tmp_path, tmp_path/'ignored.log')
    assert time.monotonic() - start < 5


def test_control_adapter_retains_stderr(tmp_path):
    from framework.campaign_executor import _default_runner
    result = _default_runner([sys.executable, '-c', "import sys; print('diagnostic',file=sys.stderr)"], tmp_path)
    assert 'diagnostic' in result.stdout


def test_watchdog_interrupt_cleans_separate_control_process_group(tmp_path, monkeypatch):
    monkeypatch.setenv('PQC_CAMPAIGN_OPERATION_TIMEOUT_SECONDS', '.5')
    scripts = Path(__file__).resolve().parents[2]/'scripts'
    pid_file = tmp_path/'control-child.pid'
    inner = f"import time,os; from pathlib import Path; Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(20)"
    script = f"import sys; sys.path.insert(0, {str(scripts)!r}); from framework.bounded_command import run; run([sys.executable,'-u','-c',{inner!r}], cwd='.',timeout=30)"
    start = time.monotonic()
    with pytest.raises(CampaignCleanupError):
        _stream_command_to_log([sys.executable, '-u', '-c', script], tmp_path, tmp_path/'interrupted.log')
    assert time.monotonic() - start < 5
    import os
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


@pytest.mark.parametrize('code', [0, 7, 124])
def test_completed_remote_status_is_distinct_from_deadline(tmp_path, code):
    from framework.bounded_command import capture_result, CAPTURE_COMPLETE
    script = f"trap 'echo cleanup-finished >&2' EXIT; echo retained-evidence; exit {code}"
    command = capture_command('unused', script, 5)
    result = subprocess.run(['sh', '-c', command[-1]], capture_output=True, text=True, timeout=8)
    assert result.returncode == code
    assert result.stderr.index('cleanup-finished') < result.stderr.index(CAPTURE_COMPLETE)
    classified, reason = capture_result(result, remote_deadline=270, capture_limit=180)
    assert classified.returncode == code and reason is None
    assert 'retained-evidence' in classified.stdout
    assert 'deadline exceeded' not in classified.stderr
    assert 'remote completion unverified' not in classified.stderr
    if code == 124:
        assert '180s' in classified.stderr and '270s' not in classified.stderr


def test_cleanup_stall_does_not_acknowledge_remote_completion(tmp_path):
    from framework.bounded_command import capture_result, CAPTURE_COMPLETE
    script = "trap 'echo cleanup-started >&2; sleep 20' EXIT; exit 124"
    command = capture_command('unused', script, .2)
    result = subprocess.run(['sh', '-c', command[-1]], capture_output=True, text=True, timeout=8)
    assert result.returncode == 124
    assert 'cleanup-started' in result.stderr and CAPTURE_COMPLETE not in result.stderr
    classified, reason = capture_result(result, remote_deadline=.2, capture_limit=.1)
    assert classified.returncode == 125 and 'remote completion unverified' in reason
    assert 'deadline exceeded (0.2s)' in classified.stderr


def test_inner_acquisition_timer_expires_without_outer_deadline(tmp_path):
    from framework.bounded_command import capture_result, CAPTURE_COMPLETE
    command = capture_command('unused', "timeout .1s sh -c 'echo device-partial; sleep 20'", 5)
    result = subprocess.run(['sh', '-c', command[-1]], capture_output=True, text=True, timeout=8)
    assert result.returncode == 124 and CAPTURE_COMPLETE in result.stderr
    classified, reason = capture_result(result, remote_deadline=5, capture_limit=.1)
    assert classified.returncode == 124 and reason is None
    assert classified.stdout == 'device-partial\n'
    assert '0.1s' in classified.stderr and 'deadline exceeded' not in classified.stderr
