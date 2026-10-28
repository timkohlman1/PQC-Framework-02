"""Capture expiry and unresolved control-plane execution are separate outcomes."""
import subprocess
import pytest
from framework.bounded_command import CAPTURE_COMPLETE, capture_result


@pytest.mark.parametrize('stderr', ['', f'{CAPTURE_COMPLETE} rc=0\n',
    f'{CAPTURE_COMPLETE} rc=124\npartial cleanup\n',
    f'{CAPTURE_COMPLETE} rc=124\n{CAPTURE_COMPLETE} rc=124\n'])
def test_missing_or_ambiguous_completion_keeps_timeout_unverified(stderr):
    result, reason = capture_result(subprocess.CompletedProcess(['ssh'],124,'partial',stderr),
                                   remote_deadline=270,capture_limit=180)
    assert result.returncode == 125 and result.stdout == 'partial'
    assert 'remote completion unverified' in reason
    assert '270s' in result.stderr


@pytest.mark.parametrize('code,word', [(125,'control'),(137,'killed'),(255,'SSH transport')])
def test_control_failures_remain_unverified_even_with_a_capture_marker(code,word):
    original = subprocess.CompletedProcess(['ssh'],code,'partial',f'{CAPTURE_COMPLETE} rc=124\n')
    result, reason = capture_result(original,remote_deadline=270,capture_limit=180)
    assert result.returncode == (125 if code == 137 else code)
    assert word in reason and 'remote completion unverified' in reason
    assert 'acquisition time limit' not in result.stderr


def test_normal_capture_timeout_preserves_124_and_diagnostics():
    original = subprocess.CompletedProcess(['ssh'],124,'',
        f'PQC_MQTT_UART_CAPTURE termination_reason=hard_timeout raw_capture_rc=124\n{CAPTURE_COMPLETE} rc=124\n')
    result, reason = capture_result(original,remote_deadline=270,capture_limit=180)
    assert result.returncode == 124 and reason is None
    assert original.stderr in result.stderr and '180s' in result.stderr
    assert '270s' not in result.stderr and 'SSH' not in result.stderr
