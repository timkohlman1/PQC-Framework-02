"""Gateway process-group deadline qualification; synthetic publisher wait."""
import json
import time
from pathlib import Path

import pytest
import yaml
from framework.bounded_command import run, capture_command
from framework.hardware_test_support import session_result_dir

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.hardware


def test_remote_capture_deadline_stops_waiting_process_group(pytestconfig, pqc_require_capabilities):
    pqc_require_capabilities('gateway', strict_mode='hardware')
    identity = yaml.safe_load((ROOT/'configs/gateways/pqc_gateway1.yaml').read_text())['identity']
    target = identity['ssh_user'] + '@' + identity['fqdn']
    # Deliberately stalled descendant holds the SSH output pipe open, as did the publisher.
    command = capture_command(target, 'sleep 20 & child=$!; echo child=$child; wait "$child"', 1)
    start = time.monotonic()
    result = run(command, cwd=ROOT, timeout=15)
    elapsed = time.monotonic() - start
    folder = session_result_dir(pytestconfig)/'capture-deadline'
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'deadline.json').write_text(json.dumps({'return_code': result.returncode,
        'elapsed': elapsed, 'stdout': result.stdout, 'stderr': result.stderr}, indent=2))
    assert result.returncode == 124, result.stderr
    assert elapsed < 12
    assert 'child=' in result.stdout
