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
        def getmaxyx(self): return (32, 140)
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
               version='abcdef0*', version_date='2026-10-01', detail='Energy capture rejected: sample gap counter incremented. ' * 6, conditions=1, repetitions=10, completed_at=1700000000, exported=True)
    terminal.jobs = terminal.rows = [row]
    monkeypatch.setattr(queue_tui, 'log_tail', lambda *args: [f'log {i}' for i in range(8)])
    lines = {}
    terminal.put = lambda y, x, text, style=0: lines.__setitem__((y, x), text)
    terminal.tab = 1
    terminal.draw()
    assert 'dirty checkout' not in lines[1, 2]
    assert lines[2, 2] == 'first: IN USE - lab'
    assert lines[3, 2] == 'second: READY'
    assert 'REPS' in lines[6, 2] and 'TOTAL RUNS' in lines[6, 2]
    assert 'RUNS OK/ERROR/TOTAL' in lines[7, 2]
    assert '5/1/10' in lines[9, 2]
    terminal.tab = 2
    terminal.draw()
    assert '5/1/10' in lines[9, 2] and 'YES' in lines[9, 2]
    assert '2' in lines[9, 2]
    assert '2023-' in lines[9, 2]
    assert 'abcdef123456' in lines[9, 2]
    assert '2026-10-01' in lines[9, 2]
    assert 'abcdef0*' in lines[0, 2] and 'abcdef0*' in lines[9, 2]
    assert 'Energy capture rejected' in lines[11, 2]
    assert len(lines[12, 2]) > 0 and len(lines[13, 2]) > 0
    assert lines[15, 2].startswith('─ Log')
    assert [lines[y, 2] for y in range(16, 24)] == [f'log {i}' for i in range(8)]
    assert lines[24, 2].startswith('──')


@pytest.mark.parametrize('key', [9, ord('2'), ord('3')])
def test_tab_change_clears_marks_and_requires_explicit_row_navigation(key):
    from framework.queue_tui import Terminal
    terminal = Terminal.__new__(Terminal)
    cleared = []
    terminal.queue = SimpleNamespace(clear_selection=lambda: cleared.append(True))
    terminal.shutdown_future = None
    terminal.tab = 0
    terminal.picked = {'baseline.yaml'}
    terminal.jobs = [{'id': 'abcdef123456', 'selected': 1}]
    terminal.rows = [{'profile': 'baseline.yaml'}]
    terminal.cursor = [0, 0, 0]
    terminal.key(key)
    assert cleared == [True]
    assert terminal.picked == set() and terminal.jobs[0]['selected'] == 0
    assert terminal.cursor == [-1, -1, -1] and terminal.rows == []
    # A newly rendered row must not become an implicit command target.
    terminal.rows = [{'id': 'abcdef123456'}]
    import curses
    terminal.key(curses.KEY_DC)
    terminal.key(ord('D'))
    terminal.key(ord('p'))
    assert terminal.cursor[terminal.tab] == -1
    terminal.key(ord('j'))
    assert terminal.cursor[terminal.tab] == 0


def test_profiles_headings_and_hints_are_consistent(monkeypatch):
    from framework import queue_tui
    monkeypatch.setattr(queue_tui.curses, 'has_colors', lambda: False)
    terminal = queue_tui.Terminal.__new__(queue_tui.Terminal)
    terminal.screen = SimpleNamespace(erase=lambda: None, getmaxyx=lambda: (30, 120), refresh=lambda: None)
    terminal.queue = SimpleNamespace(dispatch=lambda: 'stopped')
    terminal.gateways = []
    terminal.gateway_error = ''
    terminal.message = 'a to enqueue'
    terminal.shutdown_future = None
    terminal.version = {'label': 'abcdef0', 'date': '2026-10-03'}
    terminal.cursor = [0, 0, 0]
    terminal.jobs = []
    terminal.rows = [dict(profile='my_auth.yaml', profile_name='my_auth', template='thesis_authentication.yaml',
        repetitions=10, conditions=8, attempts=80, workload='ready_metrics')]
    terminal.tab = 0
    terminal.picked = set()
    terminal.filter = ''
    lines = {}
    terminal.put = lambda y, x, text, style=0: lines.__setitem__((y,x), text)
    terminal.draw()
    assert lines[5, 2].split() == ['PROFILE', 'NAME', 'TEMPLATE', 'REPS', 'CASES', 'TOTAL', 'RUNS']
    assert lines[6, 2].split()[1:] == ['my_auth', 'thesis_authentication.yaml', '10', '8', '80']
    assert 'a enqueue' in lines[26, 2]
    assert 'D delete profile' in lines[26, 2] and 'a add' not in lines[26, 2]
    assert all('ATTEMPTS' not in text for text in lines.values())
