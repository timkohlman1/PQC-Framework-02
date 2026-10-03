"""Real host processes and generated-notebook execution with synthetic evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from framework.run_queue import Queue
from framework.campaign_executor import canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
pytestmark = pytest.mark.integration


@pytest.mark.parametrize('stop_kind', ['entry_pause', 'worker_signal', 'queue_quit'])
def test_worker_observes_cross_process_pause_and_starts_next_unpaused_entry(tmp_path, stop_kind):
    scripts = tmp_path / 'scripts'
    (scripts / 'framework').mkdir(parents=True)
    for name in ('run_queue.py', 'collect_thesis_evidence.py'):
        shutil.copy2(ROOT / 'scripts' / name, scripts / name)
    for name in ('run_queue.py', 'run_console.py', 'progress.py'):
        shutil.copy2(ROOT / 'scripts/framework' / name, scripts / 'framework' / name)
    # The shim owns no hardware; it simulates a completed command with a sealed verdict.
    shim = scripts / 'dev.sh'
    shim.write_text('''#!/usr/bin/env python3
import hashlib, json, pathlib, sys, time
root=pathlib.Path(__file__).resolve().parents[1]
a=sys.argv[1:]
if a[0]=='python':
    raise SystemExit(0)
pause=root/pathlib.Path(a[a.index('--pause-file')+1]).relative_to('/workspace')
output=root/pathlib.Path(a[a.index('--results-root')+1]).relative_to('/workspace')
folder=output/'owned'; folder.mkdir(parents=True)
(root/'command-started').touch()
if (root/'wait-for-pause').exists():
    deadline=time.monotonic()+15
    while not pause.exists():
        if time.monotonic()>deadline: raise SystemExit(3)
        time.sleep(.02)
paused=pause.exists()
if paused: time.sleep(.3)
(root/'cleanup-complete').touch()
data={'state':'paused' if paused else 'completed', 'cleanup':{'status':'passed'},
      'pause':{'reason':'requested'}, 'runs':[],
      'summary':{'planned':1, 'completed':0 if paused else 1, 'failed':0, 'blocked':0}}
if not paused:
    data['final_index']={'status':'finalized','sha256':hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
(folder/'campaign-manifest.json').write_text(json.dumps(data))
raise SystemExit(75 if paused else 0)
''')
    shim.chmod(0o755)
    queue = Queue(tmp_path)
    ids = ['a' * 12, 'b' * 12]
    for position, identifier in enumerate(ids):
        (queue.folder(identifier) / 'profiles').mkdir(parents=True)
        (queue.folder(identifier) / 'profiles/campaign.yaml').write_text('synthetic')
        with queue.connect() as db:
            db.execute('''INSERT INTO jobs(id,position,profile,repetitions,conditions,attempts,status,created)
                          VALUES (?,?,?,1,1,1,'queued',?)''', (identifier, position, 'fixture', time.time()))
    with queue.connect() as db:
        db.execute("UPDATE settings SET value='running' WHERE key='dispatch'")
    environment = dict(os.environ)
    environment.pop('PQC_CONTAINER', None)
    command = [sys.executable, str(scripts / 'run_queue.py')]
    (tmp_path / 'wait-for-pause').touch()
    worker = subprocess.Popen(command + ['worker', '--once'], env=environment,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic()+15
        while not (tmp_path / 'command-started').exists():
            assert time.monotonic() < deadline
            time.sleep(.03)
        if stop_kind == 'worker_signal':
            import signal
            worker.send_signal(signal.SIGTERM)
        elif stop_kind == 'queue_quit':
            stopped = subprocess.run(command + ['quit'], env=environment, capture_output=True, text=True, timeout=15)
            assert stopped.returncode == 0, stopped.stderr
            assert (tmp_path / 'cleanup-complete').exists()
            assert not queue.worker_alive()
        else:
            stopped = subprocess.run(command + ['pause', ids[0]], env=environment, capture_output=True, text=True, timeout=10)
            assert stopped.returncode == 0, stopped.stderr
        stdout, _ = worker.communicate(timeout=15)
        assert worker.returncode == 0, stdout
        assert queue.job(ids[0])['status'] == 'paused'
        assert queue.job(ids[1])['status'] == 'queued'
        (tmp_path / 'wait-for-pause').unlink()
        with queue.connect() as db:
            db.execute("UPDATE settings SET value='running' WHERE key='dispatch'")
        second = subprocess.run(command + ['worker', '--once'], env=environment, capture_output=True, text=True, timeout=15)
        assert second.returncode == 0, second.stderr
        assert queue.job(ids[1])['status'] == 'completed', queue.job(ids[1])
        assert queue.job(ids[0])['status'] == 'paused'
    finally:
        if worker.poll() is None:
            worker.terminate()
            worker.communicate(timeout=20)


@pytest.mark.parametrize('without_captures', [False, True])
def test_selected_export_and_notebook_execute_without_unrelated_rows(tmp_path, monkeypatch, without_captures):
    import nbformat
    from nbclient import NotebookClient
    import queue_workspace as workspace
    from framework import thesis_collection as collection
    from framework.archive_table import load_archive
    from timing_dataset_support import make_run
    monkeypatch.setattr(workspace, 'ROOT', tmp_path)
    monkeypatch.setattr(collection, 'ROOT', tmp_path)
    monkeypatch.setattr(collection, 'source_identity', lambda: {'fixture': 'synthetic'})
    # Notebook root discovery locates the maintained framework without copying dependencies.
    (tmp_path / 'scripts').symlink_to(ROOT / 'scripts', target_is_directory=True)
    selection = []
    for index in range(3):
        folder = tmp_path / 'results/queue/jobs' / str(index)
        campaign = folder / 'campaigns' / ('fixture-' + str(index))
        campaign.mkdir(parents=True)
        if not without_captures:
            make_run(campaign / 'runs' / 'capture', run_id='run-' + str(index))
        manifest = {'state': 'completed', 'cleanup': {'status': 'passed'},
                    'campaign_id': 'fixture', 'runs': [],
                    'summary': {'planned': 1, 'completed': 1, 'failed': 0, 'blocked': 0}}
        if without_captures:
            manifest.update(state='completed_with_failures',
                summary={'planned': 1, 'completed': 0, 'failed': 1, 'blocked': 0},
                runs=[{'case_id': str(index), 'repetition_index': 1, 'state': 'failed',
                       'manifest': None, 'accepted_failure': {'decision': 'operator_accept'}}])
        manifest['final_index'] = {'status': 'finalized', 'sha256': canonical_sha256(manifest)}
        path = campaign / 'campaign-manifest.json'
        path.write_text(json.dumps(manifest))
        (folder / 'annotations.json').write_text('{}')
        from framework.run_queue import digest
        selection.append({'id': str(index), 'root': campaign.relative_to(tmp_path).as_posix(),
                          'job_root': folder.relative_to(tmp_path).as_posix(), 'status': manifest['state'],
                          'manifest_sha': digest(path), 'attempts': 1})
    request = tmp_path / 'results/selection.json'
    request.write_text(json.dumps({'jobs': selection[:2]}))
    result = workspace.export_selection('results/selection.json', 'results/exports/combined')
    output = tmp_path / result['output']
    frame = load_archive(output, verify_sources=True)
    if without_captures:
        assert len(frame) == 2 and frame.run_id.isna().all() and not frame.run_success.any()
    else:
        assert set(frame.run_id) == {'run-0', 'run-1'}
    notebook = nbformat.read(output / 'analysis.ipynb', as_version=4)
    NotebookClient(notebook, timeout=60, kernel_name='python3', resources={'metadata': {'path': str(output)}}).execute()
    text = '\n'.join(o.get('text', '') for c in notebook.cells if c.cell_type == 'code' for o in c.outputs)
    assert 'original values, missingness, nullable types, row identity and timestamps preserved' in text
    # Generated notebooks have no frozen results or executed cells until the user runs them.
    fresh = nbformat.read(output / 'analysis.ipynb', as_version=4)
    assert all(not c.get('outputs') for c in fresh.cells)
    for name in ('runs.csv', 'analysis.ipynb', 'queue-selection.json', 'archive.json'):
        assert (output / name).is_file()


@pytest.mark.parametrize('exit_key', [b'd', b'q'])
def test_terminal_renders_and_detaches_in_a_real_pty(tmp_path, exit_key):
    import pty
    import select
    script = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from framework.run_queue import Queue
from framework.queue_tui import run
q=Queue(Path(sys.argv[2]))
q.gateway_statuses=lambda: [{'gateway':'fixture-gateway','status':'READY','hostname':''}]
q.catalogue=lambda: [{'profile':'baseline.yaml','repetitions':1,'conditions':1,'attempts':1,'workload':'ready_metrics','error':None}]
run(q)
'''
    master, slave = pty.openpty()
    import fcntl, struct, termios
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, 0, 0))
    child = subprocess.Popen([sys.executable, '-c', script, str(ROOT / 'scripts'), str(tmp_path)],
                             stdin=slave, stdout=slave, stderr=slave, env={**os.environ, 'TERM': 'xterm-256color'})
    os.close(slave)
    data = b''
    try:
        deadline = time.monotonic()+10
        while b'baseline' not in data or b'fixture-gateway: READY' not in data:
            assert time.monotonic() < deadline, data.decode(errors='replace')
            if select.select([master], [], [], .1)[0]:
                data += os.read(master, 8192)
        os.write(master, exit_key)
        child.wait(timeout=10)
        assert child.returncode == 0
        assert b'EXPERIMENT QUEUE' in data
        assert b'fixture-gateway: READY' in data
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)


def test_remove_discover_and_purge_through_separate_cli_processes(tmp_path):
    scripts = tmp_path / 'scripts'
    (scripts / 'framework').mkdir(parents=True)
    shutil.copy2(ROOT / 'scripts/run_queue.py', scripts / 'run_queue.py')
    shutil.copy2(ROOT / 'scripts/framework/run_queue.py', scripts / 'framework/run_queue.py')
    queue = Queue(tmp_path)
    identifier = 'c' * 12
    folder = queue.folder(identifier)
    folder.mkdir(parents=True)
    (folder / 'evidence.log').write_text('retained')
    with queue.connect() as db:
        db.execute("INSERT INTO jobs(id,position,profile,repetitions,conditions,attempts,status,created) VALUES (?,1,'fixture',1,1,1,'queued',0)", (identifier,))
    env = dict(os.environ)
    env.pop('PQC_CONTAINER', None)
    def cli(*args):
        result = subprocess.run([sys.executable, str(scripts / 'run_queue.py'), *args],
                                env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    cli('remove', identifier)
    assert (folder / 'evidence.log').read_text() == 'retained'
    assert cli('list')['jobs'][0]['status'] == 'removed'
    with queue.connect() as db:
        db.execute('DELETE FROM jobs WHERE id=?', (identifier,))
    assert cli('list')['jobs'][0]['status'] == 'retained'
    cli('purge', identifier, '--confirm', identifier)
    assert cli('list')['jobs'] == [] and not folder.exists()


def test_current_framework_version_tracks_git_commit_and_dirty_files(tmp_path):
    from framework.run_queue import framework_version
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git('init')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'user.name', 'Queue test')
    (tmp_path / 'source.txt').write_text('initial')
    git('add', 'source.txt')
    git('commit', '-m', 'fixture')
    short, date = git('show', '-s', '--format=%h %cs', 'HEAD').split()
    assert framework_version(tmp_path) == {'label': short, 'date': date}
    (tmp_path / 'untracked.txt').write_text('dirty')
    assert framework_version(tmp_path)['label'] == short + '*'


@pytest.mark.parametrize('use_template', [False, True])
def test_campaign_menu_creates_valid_yaml_in_real_terminal(tmp_path, use_template):
    import pty
    import select
    import fcntl
    import struct
    import termios
    import yaml
    shutil.copytree(ROOT / 'configs', tmp_path / 'configs')
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from framework.run_queue import Queue
from framework.queue_tui import run
from framework.campaign_editor import operate
import queue_workspace
root=Path(sys.argv[2]); queue_workspace.ROOT=root
q=Queue(root)
q.catalogue=lambda: queue_workspace.catalogue()['profiles']
q.gateway_statuses=lambda: [{'gateway':'fixture','status':'READY','hostname':''}]
q.campaign_editor=lambda request: operate(root, request)
run(q)
"""
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 140, 0, 0))
    child = subprocess.Popen([sys.executable, '-c', script, str(ROOT / 'scripts'), str(tmp_path)],
                             stdin=slave, stdout=slave, stderr=slave, env={**os.environ, 'TERM': 'xterm-256color'})
    os.close(slave)
    output = b''
    def expect(needle):
        nonlocal output
        deadline = time.monotonic()+15
        while needle not in output:
            assert time.monotonic() < deadline, output.decode(errors='replace')[-4000:]
            if select.select([master], [], [], .1)[0]:
                output += os.read(master, 32768)
        output = b''
    try:
        expect(b'profiles. Space to select')
        os.write(master, b'n')
        expect(b'NEW PROFILE / starting point')
        if use_template:
            os.write(master, b'j\n')
            expect(b'choose template')
            os.write(master, b'\n')  # first sorted template: baremetal_benchmark.yaml
        else:
            os.write(master, b'\n')
        expect(b'Profile name')
        os.write(master, b'terminal_campaign\n')
        expect(b'EDIT PROFILE')
        os.write(master, b'S')
        expect(b'Profile filename')
        os.write(master, b'\n')
        path = tmp_path / 'results/profiles/terminal_campaign.yaml'
        deadline = time.monotonic()+15
        while not path.exists():
            assert time.monotonic() < deadline
            if select.select([master], [], [], .1)[0]:
                output += os.read(master, 32768)
        data = yaml.safe_load(path.read_text())
        assert data['id'] == 'terminal_campaign'
        assert data['queue_profile']['template'] == ('baremetal_benchmark.yaml' if use_template else None)
        # Wait for return to main UI before requesting its pause-and-quit control.
        expect(b'profiles. Space to select')
        os.write(master, b'q')
        child.wait(timeout=15)
        assert child.returncode == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)


def test_campaign_editor_helper_process_validates_saves_and_freezes(tmp_path):
    shutil.copytree(ROOT / 'configs', tmp_path / 'configs')
    shutil.copy2(ROOT / '.gitignore', tmp_path / '.gitignore')
    for args in [('init',), ('config', 'user.email', 'fixture@example.invalid'),
                 ('config', 'user.name', 'Queue test'), ('add', '.'), ('commit', '-m', 'fixture')]:
        subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True)
    (tmp_path / 'results').mkdir()
    request = tmp_path / 'results/editor.json'
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import queue_workspace
queue_workspace.ROOT=Path(sys.argv[2])
queue_workspace.collection.ROOT=Path(sys.argv[2])
raise SystemExit(queue_workspace.main(sys.argv[3:]))
"""
    def helper(*args, expected=0):
        result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'scripts'), str(tmp_path), *args],
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == expected, result.stdout + result.stderr
        return json.loads(result.stdout.strip().splitlines()[-1]) if expected == 0 else result.stdout
    def call(value):
        request.write_text(json.dumps(value))
        return helper('campaign-editor', '--request', 'results/editor.json')
    assert helper('profiles') == {'profiles': []}
    loaded = call({'action': 'load', 'template': 'thesis_authentication.yaml', 'name': 'subprocess_campaign'})
    saved = call({'action': 'save', 'profile': 'subprocess_campaign.yaml', 'data': loaded['data']})
    assert saved['conditions'] == 8
    info = helper('prepare', '--profile', 'subprocess_campaign', '--job', 'results/q/first', '--repetitions', '3')
    assert info['template'] == 'thesis_authentication.yaml' and info['attempts'] == 24
    original_plan = json.loads((tmp_path / 'results/q/first/plan.json').read_text())
    loaded = call({'action': 'load', 'profile': 'subprocess_campaign.yaml'})
    loaded['data']['execution']['repetitions'] = 2
    saved = call({**loaded, 'action': 'save'})
    helper('check', '--job', 'results/q/first')
    info = helper('prepare', '--profile', 'subprocess_campaign', '--job', 'results/q/second')
    assert info['attempts'] == 16
    next_plan = json.loads((tmp_path / 'results/q/second/plan.json').read_text())
    assert next_plan['profile_origin']['sha256'] != original_plan['profile_origin']['sha256']
    assert next_plan['source'] == original_plan['source']
    call({'action': 'delete', 'profile': 'subprocess_campaign.yaml', 'sha256': saved['sha256'], 'confirm': 'subprocess_campaign.yaml'})
    assert helper('profiles') == {'profiles': []}
    helper('check', '--job', 'results/q/first')
    assert (tmp_path / 'configs/campaigns/thesis_authentication.yaml').is_file()
    captured = tmp_path / 'results/q/first/profiles/input.yaml'
    captured.write_text(captured.read_text() + '# tamper\n')
    assert 'frozen campaign profile changed' in helper('check', '--job', 'results/q/first', expected=2)


def test_profile_lifecycle_keeps_git_source_identity_clean(tmp_path):
    from framework.campaign_editor import operate
    from framework.source import capture_git_provenance
    shutil.copytree(ROOT / 'configs', tmp_path / 'configs')
    shutil.copy2(ROOT / '.gitignore', tmp_path / '.gitignore')
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True,
            capture_output=True, text=True).stdout.strip()
    git('init')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'user.name', 'Queue test')
    git('add', '.')
    git('commit', '-m', 'fixture')
    before = capture_git_provenance(tmp_path)
    loaded = operate(tmp_path, {'action': 'load', 'template': 'thesis_authentication.yaml', 'name': 'local_auth'})
    saved = operate(tmp_path, {**loaded, 'action': 'save', 'profile': 'local_auth.yaml'})
    assert git('status', '--porcelain') == ''
    assert capture_git_provenance(tmp_path) == before
    loaded = operate(tmp_path, {'action': 'load', 'profile': 'local_auth.yaml'})
    loaded['data']['execution']['repetitions'] = 3
    saved = operate(tmp_path, {**loaded, 'action': 'save'})
    assert git('status', '--porcelain') == ''
    assert capture_git_provenance(tmp_path) == before
    operate(tmp_path, {'action': 'delete', 'profile': 'local_auth.yaml', 'sha256': saved['sha256'], 'confirm': 'local_auth.yaml'})
    assert git('status', '--porcelain') == ''
    assert capture_git_provenance(tmp_path) == before
