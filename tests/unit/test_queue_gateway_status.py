"""Advisory gateway display classification without network access."""
import json
import subprocess
from types import SimpleNamespace

import pytest
import gateway_lock


@pytest.mark.parametrize('busy,owner,status,hostname', [
    (False, {}, 'READY', ''),
    (True, {'description': 'lab-host user=dev command=run'}, 'IN USE', 'lab-host'),
    (True, {}, 'IN USE', 'unknown'),
])
def test_lock_status(tmp_path, monkeypatch, busy, owner, status, hostname):
    config = tmp_path / 'gateway.yaml'
    config.write_text('identity:\n  fqdn: gateway.test\n  ssh_user: dev\n')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps({'busy': busy, 'owner': owner}))
    monkeypatch.setattr(subprocess, 'run', run)
    result = gateway_lock.gateway_status(config)
    assert result == {'gateway': 'gateway.test', 'status': status, 'hostname': hostname}
    assert len(calls) == 1 and calls[0][0] == 'ssh'
    assert 'status' in calls[0][-1]


@pytest.mark.parametrize('error,ping,status', [
    ('Permission denied', 1, 'CONNECTION ERROR'),
    ('Connection refused', 1, 'CONNECTION ERROR'),
    ('Connection timed out', 0, 'CONNECTION ERROR'),
    ('Connection timed out', 1, 'OFFLINE'),
    ('Connection timed out', 2, 'CONNECTION ERROR'),
])
def test_failed_ssh_distinguishes_reachability(tmp_path, monkeypatch, error, ping, status):
    config = tmp_path / 'gateway.yaml'
    config.write_text('identity:\n  fqdn: gateway.test\n  ssh_user: dev\n')
    def run(command, **kwargs):
        return SimpleNamespace(returncode=255 if command[0] == 'ssh' else ping,
                               stdout='', stderr=error)
    monkeypatch.setattr(subprocess, 'run', run)
    assert gateway_lock.gateway_status(config)['status'] == status


def test_multiple_gateway_profiles(tmp_path, monkeypatch):
    directory = tmp_path / 'configs/gateways'
    directory.mkdir(parents=True)
    for name in ('a.yaml', 'b.yml', 'README.md'):
        (directory / name).touch()
    monkeypatch.setattr(gateway_lock, 'ROOT', tmp_path)
    monkeypatch.setattr(gateway_lock, 'gateway_status', lambda p: p.stem)
    assert gateway_lock.gateway_statuses() == ['a', 'b']


def test_terminal_queue_and_completed_rows(monkeypatch):
    from framework import queue_tui
    monkeypatch.setattr(queue_tui.curses, 'has_colors', lambda: False)
    class Screen:
        def erase(self): pass
        def getmaxyx(self): return (30, 140)
        def refresh(self): pass
    terminal = queue_tui.Terminal.__new__(queue_tui.Terminal)
    terminal.screen = Screen()
    terminal.queue = SimpleNamespace(dispatch=lambda: 'running')
    terminal.gateways = [{'gateway': 'first', 'status': 'IN USE', 'hostname': 'lab'},
                         {'gateway': 'second', 'status': 'READY', 'hostname': ''}]
    terminal.gateway_error = ''
    terminal.message = ''
    terminal.shutdown_future = None
    terminal.version = {'label': 'abcdef0*', 'date': '2026-10-01'}
    terminal.cursor = [0, 0, 0]
    row = dict(id='abcdef123456', profile='example.yaml', selected=False, success=5,
               errors=1, repeats=2, attempts=10, progress_available=True, status='running',
               version='abcdef0*', detail='', conditions=1, repetitions=10, completed_at=1700000000, exported=True)
    terminal.jobs = terminal.rows = [row]
    monkeypatch.setattr(queue_tui, 'log_tail', lambda *args: [f'log {i}' for i in range(8)])
    lines = {}
    terminal.put = lambda y, x, text, style=0: lines.__setitem__((y, x), text)
    terminal.tab = 1
    terminal.draw()
    assert lines[2, 2] == 'first: IN USE - lab'
    assert lines[3, 2] == 'second: READY'
    assert '5/10' in lines[7, 2] and '5/1/10' in lines[7, 2]
    terminal.tab = 2
    terminal.draw()
    assert '5/1/2' in lines[7, 2] and 'YES' in lines[7, 2]
    assert '2023-' in lines[7, 2]
    assert 'abcdef0*' in lines[0, 2] and 'abcdef0*' in lines[7, 2]
    assert lines[13, 2].startswith('─ Log')
    assert [lines[y, 2] for y in range(14, 22)] == [f'log {i}' for i in range(8)]
    assert lines[22, 2].startswith('──')
