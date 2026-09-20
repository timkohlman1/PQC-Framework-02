"""Unit checks for the gateway-wide lock protocol; no SSH/hardware required."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import gateway_lock


def test_target_reads_canonical_gateway_identity(tmp_path):
    config = tmp_path / 'gateway.yaml'
    config.write_text('identity:\n  alias: fallback\n  fqdn: lab.example\n  ssh_user: dev\n')
    assert gateway_lock.gateway_target(config) == 'dev@lab.example'


def test_remote_protocol_exclusivity_and_auto_release(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    def command(mode, *args):
        return [sys.executable, '-u', '-c', gateway_lock.REMOTE, mode, *args]
    owner = subprocess.Popen(command('hold', 'first', 'test case'), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        assert owner.stdout.readline().startswith('ACQUIRED ')
        busy = subprocess.run(command('hold', 'second', 'second test'), input='',
                              capture_output=True, text=True, env=env, timeout=5)
        assert busy.returncode == 3
        assert busy.stdout.startswith('BUSY ')
        status = subprocess.run(command('status'), capture_output=True, text=True, env=env, timeout=5)
        assert '"busy": true' in status.stdout
        owner.stdin.close()
        assert owner.wait(timeout=5) == 0
        free = subprocess.run(command('status'), capture_output=True, text=True, env=env, timeout=5)
        assert '"busy": false' in free.stdout
        acquired = subprocess.run(command('hold', 'third', 'third test'), input='',
                                  capture_output=True, text=True, env=env, timeout=5)
        assert acquired.stdout.startswith('ACQUIRED ')
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)


def test_release_requires_matching_owner_and_kills_holder(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    def command(mode, *args):
        return [sys.executable, '-u', '-c', gateway_lock.REMOTE, mode, *args]
    owner = subprocess.Popen(command('hold', 'identifier', 'test case'), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        assert owner.stdout.readline().startswith('ACQUIRED ')
        wrong = subprocess.run(command('release', 'wrong'), capture_output=True,
                               text=True, env=env, timeout=5)
        assert wrong.returncode == 4
        assert owner.poll() is None
        released = subprocess.run(command('release', 'identifier'), capture_output=True,
                                  text=True, env=env, timeout=10)
        assert released.returncode == 0, released.stderr + released.stdout
        assert released.stdout.startswith('RELEASED ')
        assert owner.wait(timeout=5) != 0
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)


def test_wrapper_guards_gateway_entrypoints_and_exposes_administration():
    source = (ROOT / 'scripts/dev.sh').read_text(encoding='utf-8')
    for command in ('pytest-gateway', 'pytest-hardware', 'experiment-gateway',
                    'campaign-gateway', 'python-gateway'):
        assert command in source.split('PQC_GATEWAY_LOCK_HELD=1')[0]
    assert 'gateway-lock)' in source
    assert 'exec python3 "$repo_root/scripts/gateway_lock.py"' in source


def test_generic_run_does_not_attempt_gateway_lock(tmp_path):
    """Generic container toolchain runs must work without gateway DNS/SSH."""
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    docker = fake_bin / 'docker'
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$PQC_DOCKER_CAPTURE"\n')
    docker.chmod(0o755)
    captured = tmp_path / 'docker-args.txt'
    env = dict(os.environ, PATH=f'{fake_bin}:{os.environ.get("PATH", "")}',
               PQC_DOCKER_CAPTURE=str(captured), PQC_DOCKER_IMAGE='pqc-ci-test',
               PQC_DOCKER_SSH_DIR=str(tmp_path / 'nonexistent-ssh'))
    env.pop('PQC_GATEWAY_LOCK_HELD', None)
    result = subprocess.run(['sh', str(ROOT / 'scripts/dev.sh'), 'run', 'sh', '-lc',
                             'python --version'], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert captured.exists(), 'generic run must invoke Docker, not the SSH lease holder'
    assert 'pqc-ci-test' in captured.read_text()
    assert 'Gateway lock' not in result.stderr


def test_explicit_gateway_lock_run_remains_available():
    source = (ROOT / 'scripts/dev.sh').read_text(encoding='utf-8')
    assert 'gateway-lock)' in source
    assert 'exec python3 "$repo_root/scripts/gateway_lock.py" "$@"' in source


def test_wrong_owner_does_not_release_active_lease(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    command = lambda mode, *args: [sys.executable, '-u', '-c', gateway_lock.REMOTE, mode, *args]
    holder = subprocess.Popen(command('hold', 'owner-a', 'test'), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        assert holder.stdout.readline().startswith('ACQUIRED ')
        mismatch = subprocess.run(command('release', 'owner-b'), capture_output=True,
                                  text=True, env=env, timeout=5)
        assert mismatch.returncode == 4
        assert holder.poll() is None
    finally:
        holder.stdin.close()
        holder.wait(timeout=5)


def test_interactive_wait_spinner_reuses_one_line_and_counts_elapsed_time():
    import io
    import json

    class TTY(io.StringIO):
        def isatty(self):
            return True

    stream = TTY()
    current = [0.0]
    display = gateway_lock.WaitDisplay(stream=stream, clock=lambda: current[0])
    owner = 'BUSY ' + json.dumps({'owner_id': 'abc', 'description': 'linuxdev2 user=dev'})
    display.busy(owner)
    current[0] = 65.0
    display.busy(owner)
    display.finish()
    output = stream.getvalue()
    assert output.count('\n') == 1, 'unchanged owner must not add log lines'
    assert 'Waiting: 0m 00s' in output
    assert 'Waiting: 1m 05s' in output
    assert output.count('\r') >= 2
    assert 'linuxdev2 user=dev' in output


def test_wait_owner_change_prints_one_additional_line():
    import io
    import json

    class TTY(io.StringIO):
        def isatty(self):
            return True

    stream = TTY()
    display = gateway_lock.WaitDisplay(stream=stream, clock=lambda: 0.0)
    first = 'BUSY ' + json.dumps({'owner_id': 'one', 'description': 'machine-1'})
    second = 'BUSY ' + json.dumps({'owner_id': 'two', 'description': 'machine-2'})
    display.busy(first)
    display.busy(first)
    display.busy(second)
    display.finish()
    assert stream.getvalue().count('\n') == 2
    assert 'machine-1' in stream.getvalue()
    assert 'machine-2' in stream.getvalue()


def test_redirected_wait_output_has_no_spinner_or_repeat_messages():
    import io
    import json

    stream = io.StringIO()
    display = gateway_lock.WaitDisplay(stream=stream, clock=lambda: 100.0)
    owner = 'BUSY ' + json.dumps({'owner_id': 'abc', 'description': 'machine-1'})
    for _ in range(10):
        display.busy(owner)
    display.finish()
    output = stream.getvalue()
    assert output.count('\n') == 1
    assert '\r' not in output
    assert 'machine-1' in output


def test_wait_cancel_does_not_acquire_or_release_a_lease(monkeypatch, capsys):
    import json

    calls = []

    def busy_attempt(*args):
        calls.append(args)
        raise BlockingIOError('BUSY ' + json.dumps({'owner_id': 'another', 'description': 'other-host'}))

    def cancel_sleep(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(gateway_lock, 'attempt', busy_attempt)
    monkeypatch.setattr(gateway_lock.time, 'sleep', cancel_sleep)
    result = gateway_lock.run_locked('gateway', ['echo', 'unused'])
    assert result == 130
    assert len(calls) == 1
    assert 'Gateway wait cancelled.' in capsys.readouterr().err
