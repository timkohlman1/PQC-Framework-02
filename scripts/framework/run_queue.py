"""Persistent Linux host queue; stdlib only. Hardware stays in dev.sh children."""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from functools import lru_cache
import re
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from framework.failure_details import campaign_failure

ROOT = Path(__file__).resolve().parents[2]
DONE = {'completed', 'completed_with_failures'}
ACTIVE = {'running', 'pausing'}
HISTORY = DONE | {'removed', 'retained'}


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def owned_path(root, value):
    path = Path(os.path.abspath(root / value))
    if not path.is_relative_to(root / 'results') or path == root / 'results':
        raise ValueError('queue paths must be below results/')
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError('symlink queue paths are not supported')
    return path


def source_label(source):
    """A display label only; execution still verifies the full frozen identity."""
    repository = source.get('repository', {})
    commit = repository.get('git_commit')
    if not isinstance(commit, str) or len(commit) < 7:
        return 'unknown'
    dirty = repository.get('git_dirty') or any(
        entry.get('dirty') or entry.get('source', {}).get('git_dirty')
        for entry in source.get('submodules', {}).get('entries', []))
    return commit[:7] + ('*' if dirty else '')


def framework_version(root):
    try:
        def git(*args):
            result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                                    text=True, timeout=5)
            if result.returncode:
                raise ValueError('Git metadata unavailable')
            return result.stdout.strip()
        short, date = git('show', '-s', '--format=%h %cs', 'HEAD').split()
        dirty = bool(git('status', '--porcelain', '--untracked-files=normal', '--ignore-submodules=none'))
        return {'label': short + ('*' if dirty else ''), 'date': date}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'label': 'unknown', 'date': 'unknown'}


@lru_cache(maxsize=256)
def commit_date(root, commit):
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40,64}', commit):
        return 'unknown'
    try:
        result = subprocess.run(['git', '-C', str(root), 'show', '-s', '--format=%cs', commit],
                                capture_output=True, text=True, timeout=5)
        value = result.stdout.strip()
        return value if result.returncode == 0 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else 'unknown'
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'


class Queue:
    def __init__(self, root=ROOT, directory='results/queue'):
        self.root = Path(root).resolve()
        self.directory = owned_path(self.root, directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._stop_requested = False
        self.database = self.directory / 'queue.sqlite3'
        if self.database.is_symlink():
            raise ValueError('symlink database refused')
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, position INTEGER NOT NULL, profile TEXT NOT NULL,
                    repetitions INTEGER NOT NULL, conditions INTEGER NOT NULL, attempts INTEGER NOT NULL,
                    status TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'resume',
                    selected INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '',
                    created REAL NOT NULL, manifest_sha TEXT, invocation INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, job TEXT, at REAL NOT NULL, action TEXT NOT NULL, detail TEXT
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO settings VALUES ('dispatch', 'stopped');
                INSERT OR IGNORE INTO settings VALUES ('version', '1');
            ''')
            if db.execute("SELECT value FROM settings WHERE key='version'").fetchone()[0] != '1':
                raise ValueError('unsupported queue database version')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def event(db, job, action, detail=''):
        db.execute('INSERT INTO events(job,at,action,detail) VALUES (?,?,?,?)',
                   (job, time.time(), action, detail))

    def jobs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY position,created')]

    def gateway_statuses(self):
        result = subprocess.run([str(self.root / 'scripts/dev.sh'), 'gateway-lock', 'status-all'],
                                cwd=self.root, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise ValueError('gateway status check failed')
        return json.loads(result.stdout.strip().splitlines()[-1])

    def display_jobs(self):
        rows = self.jobs()
        known = {row["id"] for row in rows}
        for folder in sorted((self.directory / "jobs").glob("*")):
            if folder.name in known or folder.is_symlink() or not folder.is_dir():
                continue
            try:
                self.folder(folder.name)
                plan = read(folder / "plan.json")
                info = plan["steps"][0]
                rows.append(dict(id=folder.name, profile=info["profile"],
                                 repetitions=info["repetitions"], conditions=info["conditions"],
                                 attempts=info["attempts"], status="retained", selected=0,
                                 detail="Retained folder; no queue record. Not scheduled.",
                                 manifest_sha=None))
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                # Even a partial retained directory must be visible for disposal.
                if len(folder.name) == 12 and all(c in "0123456789abcdef" for c in folder.name):
                    rows.append(dict(id=folder.name, profile="Retained " + folder.name,
                                     repetitions=0, conditions=0, attempts=0, status="retained",
                                     selected=0, detail="Retained files; plan unavailable.", manifest_sha=None))
        with self.connect() as db:
            events = [dict(r) for r in db.execute(
                "SELECT * FROM events WHERE action IN ('completed','completed_with_failures','export') ORDER BY id")]
        completions, exports = {}, set()
        for event in events:
            if event['action'] in DONE:
                completions[event['job']] = event['at']
            elif event['job']:
                exports.add((event['job'], event['detail']))
            else:
                # Recover exports made by the first queue version as well.
                try:
                    selection = read(owned_path(self.root, event['detail']) / 'queue-selection.json')
                    exports.update((j['id'], j['manifest_sha']) for j in selection['jobs'])
                except (OSError, ValueError, KeyError, TypeError):
                    pass
        for row in rows:
            row['profile_name'] = Path(row['profile']).stem
            row['template'] = 'Legacy'
            row['version'] = 'unknown'
            row['version_date'] = 'unknown'
            try:
                plan = read(self.folder(row['id']) / 'plan.json')
                info = plan.get('steps', [{}])[0]
                row['profile_name'] = info.get('profile_name', info.get('id', row['profile_name']))
                row['template'] = info.get('template', 'Legacy')
                row['version'] = source_label(plan['source'])
                row['version_date'] = plan.get('display_version', {}).get('date') or commit_date(str(self.root), plan['source'].get('repository', {}).get('git_commit'))
            except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
                pass
            row.update(success=0, errors=0, repeats=0, progress_available=True,
                       completed_at=completions.get(row['id']) if row['status'] in DONE else None,
                       exported=(row['id'], row['manifest_sha']) in exports if row['status'] in DONE else False)
            try:
                manifest = self.manifest(row['id'])
                if manifest:
                    data = read(manifest)
                    runs = data['runs']
                    if row['status'] in {'removed', 'retained'}:
                        row['detail'] += ' Evidence state: ' + str(data.get('state', 'unknown'))
                        if data.get('state') in DONE:
                            from datetime import datetime
                            try:
                                row['completed_at'] = datetime.fromisoformat(data['completed_at']).timestamp()
                            except (KeyError, ValueError, TypeError):
                                pass
                        row['exported'] = (row['id'], digest(manifest)) in exports
                    if row['status'] in DONE and digest(manifest) != row['manifest_sha']:
                        row['exported'] = False
                    if row['status'] in ACTIVE and (reason := campaign_failure(data)):
                        row['detail'] = 'Continuing; failure retained for review: ' + reason
                    row['success'] = sum(r.get('state') == 'completed' for r in runs)
                    row['errors'] = sum(r.get('state') in {'failed', 'blocked'} for r in runs)
                    row['repeats'] = sum(len(r.get('previous_attempts', [])) for r in runs)
                elif row['manifest_sha'] or row['status'] in DONE:
                    row['progress_available'] = False
                    row['exported'] = False
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                row['progress_available'] = False
                row['exported'] = False
        return rows

    def job(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ValueError('unknown queue entry: ' + identifier)
        return dict(row)

    def folder(self, identifier):
        if len(identifier) != 12 or any(c not in '0123456789abcdef' for c in identifier):
            raise ValueError('invalid queue entry ID')
        return owned_path(self.root, self.directory / 'jobs' / identifier)

    def helper(self, action, *args):
        return [str(self.root / 'scripts/dev.sh'), 'python', 'scripts/queue_workspace.py',
                action, *map(str, args)]

    def relative(self, path):
        return Path(path).relative_to(self.root).as_posix()

    def container(self, path):
        return '/workspace/' + self.relative(path)

    def offline(self, action, *args):
        result = subprocess.run(self.helper(action, *args), cwd=self.root,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode:
            raise ValueError(result.stdout[-6000:] or 'framework helper failed')
        # The last line is the structured reply; wrapper notices may precede it.
        return json.loads(result.stdout.strip().splitlines()[-1])

    def campaign_editor(self, request):
        path = self.directory / ('editor-' + uuid.uuid4().hex + '.json')
        path.write_text(json.dumps(request))
        try:
            return self.offline('campaign-editor', '--request', self.relative(path))
        finally:
            path.unlink(missing_ok=True)

    def requeue(self, identifier, repetitions=None):
        with self.inventory_lock(), self.entry_lock(identifier):
            row = self.job(identifier)
            if row['status'] in ACTIVE:
                raise ValueError('pause the active entry before re-queueing it')
            count = row['repetitions'] if repetitions is None else repetitions
            if type(count) is not int or not 1 <= count <= 1000:
                raise ValueError('repetitions must be 1..1000')
            new_id = uuid.uuid4().hex[:12]
            info = self.offline('prepare', '--job', self.relative(self.folder(new_id)),
                                '--from-job', self.relative(self.folder(identifier)), '--repetitions', count)
            result = self._register([(new_id, info)])
            with self.connect() as db:
                self.event(db, new_id, 'requeued', identifier)
            return result

    def catalogue(self):
        return self.offline('profiles')['profiles']

    @contextmanager
    def inventory_lock(self):
        with (self.directory / 'inventory.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def add(self, profiles, repetitions=None):
        with self.inventory_lock():
            return self._add(profiles, repetitions)

    def _add(self, profiles, repetitions=None):
        if not profiles:
            raise ValueError('select one or more profiles')
        if repetitions is not None and (type(repetitions) is not int or not 1 <= repetitions <= 1000):
            raise ValueError('repetitions must be 1..1000')
        planned = []
        for profile in profiles:
            identifier = uuid.uuid4().hex[:12]
            folder = self.folder(identifier)
            args = ['--job', self.relative(folder), '--profile', profile]
            if repetitions is not None:
                args += ['--repetitions', repetitions]
            info = self.offline('prepare', *args)
            planned.append((identifier, info))
        return self._register(planned)

    def _register(self, planned):
        # All requested plans must validate before any becomes dispatchable.
        with self.connect() as db:
            position = db.execute('SELECT COALESCE(MAX(position),0) FROM jobs').fetchone()[0]
            for identifier, info in planned:
                position += 1
                db.execute('''INSERT INTO jobs
                    (id,position,profile,repetitions,conditions,attempts,status,created)
                    VALUES (?,?,?,?,?,?,?,?)''',
                    (identifier, position, info['profile'], info['repetitions'],
                     info['conditions'], info['attempts'], 'queued', time.time()))
                self.event(db, identifier, 'added')
        return [identifier for identifier, _ in planned]

    def dispatch(self):
        with self.connect() as db:
            return db.execute("SELECT value FROM settings WHERE key='dispatch'").fetchone()[0]

    def pause(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
            if row is None or row['status'] not in ACTIVE | {'queued'}:
                raise ValueError('only a queued or active entry can be paused')
            status = 'pausing' if row['status'] in ACTIVE else 'paused'
            self.folder(identifier).joinpath('pause.request').touch(mode=0o600)
            db.execute('UPDATE jobs SET status=?,detail=? WHERE id=?',
                       (status, 'Pause requested; the current operation and cleanup will finish.', identifier))
            self.event(db, identifier, 'pause')

    def stop(self):
        with self.connect() as db:
            db.execute("UPDATE settings SET value='stopped' WHERE key='dispatch' AND value NOT LIKE 'halted:%'")
            for row in db.execute("SELECT id FROM jobs WHERE status IN ('running','pausing')"):
                self.folder(row['id']).joinpath('pause.request').touch(mode=0o600)
                db.execute("UPDATE jobs SET status='pausing' WHERE id=?", (row['id'],))
            self.event(db, None, 'stop', 'pause active operation and stop dispatch')

    def shutdown(self):
        """Request a cooperative pause and wait until the detached worker exits."""
        self.stop()
        while self.worker_alive():
            time.sleep(.2)
        if any(row['status'] in ACTIVE for row in self.jobs()):
            raise ValueError('worker disappeared with an active entry; child cleanup is unverified, inspect recovery')

    @contextmanager
    def entry_lock(self, identifier, *, exclusive=False):
        # File locks release on process death, unlike a durable "exporting" flag.
        with owned_path(self.root, self.folder(identifier) / 'export.lock').open('a') as lock:
            try:
                fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('export in progress; wait before changing this entry')
            yield

    def decide(self, identifier, action):
        if action not in {'resume', 'retry', 'accept'}:
            raise ValueError('choose resume, retry or accept')
        with self.connect() as db, self.entry_lock(identifier, exclusive=True):
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
            if row is None or row['status'] not in {'paused', 'attention'} | DONE:
                raise ValueError('entry must be paused or finished')
            if row['selected']:
                raise ValueError('unmark this export selection before resuming it')
            manifest = self.manifest(identifier)
            if row['manifest_sha'] and (not manifest or digest(manifest) != row['manifest_sha']):
                raise ValueError('retained campaign manifest changed; inspect the evidence before recovery')
            data = read(manifest) if manifest else {}
            failures = [r for r in data.get('runs', []) if r.get('state') in {'failed', 'blocked'}]
            if row['status'] in DONE and (action != 'retry' or not failures):
                raise ValueError('finished entries can only retry recorded failures')
            if action == 'accept' and not failures:
                raise ValueError('no recorded failed attempts to accept; resume the incomplete entry')
            self.folder(identifier).joinpath('pause.request').unlink(missing_ok=True)
            db.execute("UPDATE jobs SET status='queued', mode=?, detail='' WHERE id=?",
                       (action, identifier))
            self.event(db, identifier, action)

    def remove(self, identifier):
        """Remove scheduling eligibility while retaining the evidence directory."""
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
            if row is None or row['status'] not in {'queued', 'paused', 'attention'}:
                raise ValueError('only waiting entries can be removed; pause an active entry first')
            dispatch = db.execute("SELECT value FROM settings WHERE key='dispatch'").fetchone()[0]
            if dispatch.startswith('halted') and row['status'] == 'attention':
                raise ValueError('resolve the cleanup/worker recovery halt before removing this entry')
            db.execute("UPDATE jobs SET status='removed',selected=0,detail='Removed from queue; files retained.' WHERE id=?", (identifier,))
            self.event(db, identifier, 'removed')

    def purge(self, identifier, confirmation):
        """Delete only this queue-owned job tree; combined exports are independent."""
        if confirmation != identifier:
            raise ValueError('permanent deletion requires the exact entry ID')
        folder = self.folder(identifier)
        with self.inventory_lock(), self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
            if row is not None and row['status'] not in HISTORY:
                raise ValueError('remove this waiting entry first; active entries cannot be deleted')
            if row is None and self.worker_alive():
                raise ValueError('stop the queue worker before deleting an unregistered folder')
            if row is None and not folder.is_dir():
                raise ValueError('unknown retained entry')
            if row is not None and row['selected']:
                raise ValueError('unmark the export selection before permanent deletion')
            with ExitStack() as locks:
                if folder.exists():
                    locks.enter_context(self.entry_lock(identifier, exclusive=True))
                    for manifest in (folder / 'campaigns').glob('*/campaign-manifest.json'):
                        try:
                            data = read(manifest)
                        except (OSError, ValueError):
                            data = {}
                        if isinstance(data, dict) and data.get('state') in ACTIVE:
                            raise ValueError('retained evidence reports an active run; inspect worker recovery first')
                    if not shutil.rmtree.avoids_symlink_attacks:
                        raise ValueError('safe directory deletion is unavailable on this platform')
                    shutil.rmtree(folder)
                db.execute('DELETE FROM jobs WHERE id=?', (identifier,))
                self.event(db, identifier, 'purged', 'job directory permanently deleted; combined exports retained')

    def move(self, identifier, direction):
        if direction not in {'up', 'down'}:
            raise ValueError('direction must be up or down')
        with self.connect() as db:
            rows = list(db.execute("SELECT id,position FROM jobs WHERE status IN ('queued','paused','attention') ORDER BY position,created"))
            ids = [r['id'] for r in rows]
            if identifier not in ids:
                raise ValueError('only waiting entries can be reordered')
            i = ids.index(identifier)
            j = i + (-1 if direction == 'up' else 1)
            if 0 <= j < len(rows):
                db.execute('UPDATE jobs SET position=? WHERE id=?', (rows[j]['position'], identifier))
                db.execute('UPDATE jobs SET position=? WHERE id=?', (rows[i]['position'], rows[j]['id']))
                self.event(db, identifier, 'move', direction)

    def clear_selection(self):
        with self.connect() as db:
            db.execute('UPDATE jobs SET selected=0 WHERE selected<>0')

    def mark(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
            if row is None or row['status'] not in DONE:
                raise ValueError('only completed entries can be marked for export')
            db.execute('UPDATE jobs SET selected=1-selected WHERE id=?', (identifier,))

    def manifest(self, identifier):
        paths = list((self.folder(identifier) / 'campaigns').glob('*/campaign-manifest.json'))
        if len(paths) > 1:
            raise ValueError('ambiguous campaign history')
        return paths[0] if paths else None

    def export(self, *, identifiers=None):
        with ExitStack() as locks:
            return self._export(locks, identifiers)

    def _export(self, locks, identifiers=None):
        # Freeze only the selected entries; reads and new queue operations stay responsive.
        with self.connect() as db:
            if identifiers is None:
                rows = [dict(r) for r in db.execute('SELECT * FROM jobs WHERE selected=1 ORDER BY position')]
            else:
                if not identifiers or len(set(identifiers)) != len(identifiers):
                    raise ValueError('select distinct completed queue IDs')
                rows = []
                for identifier in identifiers:
                    row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
                    if row is None:
                        raise ValueError('unknown queue entry: ' + str(identifier))
                    rows.append(dict(row))
            if not rows or any(r['status'] not in DONE for r in rows):
                raise ValueError('mark one or more completed entries first')
            selected = []
            for row in rows:
                locks.enter_context(self.entry_lock(row['id']))
                manifest = self.manifest(row['id'])
                if not manifest or digest(manifest) != row['manifest_sha']:
                    raise ValueError('completed manifest changed; inspect entry ' + row['id'])
                selected.append({**row, 'root': self.relative(manifest.parent),
                                 'job_root': self.relative(self.folder(row['id']))})
            name = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
            request = self.directory / ('selection-' + name + '.json')
            request.write_text(json.dumps({'jobs': selected}, indent=2) + '\n')
            destination = self.directory / 'exports' / name
        result = self.offline('export', '--selection', self.relative(request),
                              '--output', self.relative(destination))
        with self.connect() as db:
            self.event(db, None, 'export', self.relative(destination))
            for row in rows:
                self.event(db, row['id'], 'export', row['manifest_sha'])
        return result

    def claim(self):
        with self.connect() as db:
            if db.execute("SELECT value FROM settings WHERE key='dispatch'").fetchone()[0] != 'running':
                return None
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY position,created LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='running',invocation=invocation+1,detail='' WHERE id=?", (row['id'],))
            self.event(db, row['id'], 'started')
        return self.job(row['id'])

    def finish(self, identifier, status, detail, *, safe=True):
        manifest = self.manifest(identifier)
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,detail=?,manifest_sha=? WHERE id=?',
                       (status, detail, digest(manifest) if manifest else None, identifier))
            if not safe:
                db.execute("UPDATE settings SET value='halted: cleanup or worker recovery requires inspection' WHERE key='dispatch'")
            self.event(db, identifier, status, detail)

    def run_job(self, row, runner=None):
        identifier = row['id']
        folder = self.folder(identifier)
        logs = folder / 'logs'
        logs.mkdir(exist_ok=True)
        log = logs / f"dispatch-{row['invocation']:04d}.log"
        runner = runner or self.run_command
        try:
            rc = runner(self.helper('check', '--job', self.relative(folder)), log)
            if rc:
                explanation = next((line.removeprefix('queue-workspace: ') for line in reversed(log_tail(self, identifier, 30))
                                    if line.startswith('queue-workspace: ')), 'No diagnostic returned')
                self.finish(identifier, 'attention', 'Plan/source validation failed: ' + explanation + '; log: ' + self.relative(log))
                return
            if (folder / 'pause.request').exists():
                self.finish(identifier, 'paused', 'Paused before hardware dispatch')
                return
            manifest = self.manifest(identifier)
            if row['manifest_sha'] and (not manifest or digest(manifest) != row['manifest_sha']):
                self.finish(identifier, 'attention', 'Retained campaign manifest changed before dispatch; inspect the evidence.')
                return
            command = [str(self.root / 'scripts/dev.sh'), 'campaign-gateway',
                       '--pause-file', self.container(folder / 'pause.request'), '--defer-failed', '--preserve-completed']
            if manifest:
                command += ['--resume', self.container(manifest)]
                if row['mode'] == 'accept':
                    command.append('--accept-failed')
                elif row['mode'] == 'retry':
                    command.append('--retry-failed')
            else:
                command += [self.container(folder / 'profiles/campaign.yaml'),
                            '--results-root', self.container(folder / 'campaigns')]
            rc = runner(command, log)
            manifest = self.manifest(identifier)
            data = read(manifest) if manifest else {}
            safe = data.get('cleanup', {}).get('status') == 'passed' and rc in {0, 1, 75}
            status = data.get('state')
            reason = campaign_failure(data)
            if not safe:
                self.finish(identifier, 'attention', 'Dispatch halted: ' + (reason or f'command exit {rc}; cleanup not verified') + '; log: ' + self.relative(log), safe=False)
            elif status == 'paused':
                self.finish(identifier, 'attention' if data.get('pause', {}).get('reason') == 'error' else 'paused',
                            ('Paused on error: ' + (reason or 'reason unavailable; inspect ' + self.relative(log)))
                            if data.get('pause', {}).get('reason') == 'error' else 'Paused by request after cleanup; resume continues unfinished runs.')
            elif status in DONE:
                from collect_thesis_evidence import campaign_verdict
                verdict, verified, _ = campaign_verdict(manifest, rc, row['attempts'])
                unresolved = any(r.get('state') in {'failed', 'blocked'} and not r.get('accepted_failure')
                                 for r in data.get('runs', []))
                if not verified:
                    self.finish(identifier, 'attention', 'Campaign verdict/count validation failed', safe=False)
                else:
                    self.finish(identifier, 'attention' if unresolved else verdict,
                                ('All planned slots processed; review failures with t retry / f accept. Latest: ' + reason) if unresolved else 'Evidence finalized.')
            else:
                self.finish(identifier, 'attention', 'Campaign stopped: ' + (reason or f'command exit {rc}; incomplete campaign; inspect ' + self.relative(log)) + '. Resume unfinished runs after resolving the cause.')
        except Exception as exc:
            # Unexpected failures cannot establish that a launched hardware command cleaned up.
            self.finish(identifier, 'attention', str(exc), safe=False)

    def run_command(self, command, log):
        with Path(log).open('ab') as stream:
            stream.write(('\nCommand: ' + ' '.join(command) + '\n').encode())
            stream.flush()
            # The worker ignores terminal signals; stop is a persisted cooperative request.
            child = subprocess.Popen(command, cwd=self.root, stdin=subprocess.DEVNULL,
                                     stdout=stream, stderr=subprocess.STDOUT,
                                     start_new_session=True,
                                     env={**os.environ, 'PQC_PROGRESS_TTY': '0', 'NO_COLOR': '1'})
            while child.poll() is None:
                if self._stop_requested:
                    self._stop_requested = False
                    self.stop()
                time.sleep(.2)
            return child.returncode

    def worker(self, *, once=False):
        with (self.directory / 'worker.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            # Do not guess whether a previous worker's child has finished cleanup.
            abandoned = [r for r in self.jobs() if r['status'] in ACTIVE]
            for row in abandoned:
                self.finish(row['id'], 'attention', 'Worker interrupted; inspect gateway ownership and cleanup, then resume.', safe=False)
            if abandoned:
                return 2
            def stop_signal(signum, frame):
                # Never re-enter SQLite from a signal handler during a transaction.
                self._stop_requested = True
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, stop_signal)
            while True:
                if self._stop_requested:
                    self._stop_requested = False
                    self.stop()
                if self.dispatch() != 'running':
                    return 0
                row = self.claim()
                if row:
                    self.run_job(row)
                if once:
                    return 0
                time.sleep(.3)

    def worker_alive(self):
        with (self.directory / 'worker.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False

    def start(self):
        # An interrupted worker is recovered first, without automatically releasing a gateway lease.
        if not self.worker_alive() and any(r['status'] in ACTIVE for r in self.jobs()):
            for row in self.jobs():
                if row['status'] in ACTIVE:
                    self.finish(row['id'], 'attention', 'Worker interrupted; inspect cleanup and resume explicitly.', safe=False)
            raise ValueError('Recovered interrupted state. Inspect the active entry and gateway before resuming.')
        if self.dispatch().startswith('halted') and any(r['status'] == 'attention' for r in self.jobs()):
            raise ValueError('Inspect cleanup, then explicitly resume/retry the entry before starting dispatch.')
        with self.connect() as db:
            db.execute("UPDATE settings SET value='running' WHERE key='dispatch'")
            self.event(db, None, 'start')
        with (self.directory / 'worker.log').open('ab') as log:
            subprocess.Popen([sys.executable, str(self.root / 'scripts/run_queue.py'),
                              '--directory', self.relative(self.directory), 'worker'],
                             cwd=self.root, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True)


def log_tail(queue, identifier, lines=12):
    files = sorted((queue.folder(identifier) / 'logs').glob('dispatch-*.log'))
    if not files:
        return []
    try:
        with files[-1].open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 16384))
            return stream.read().decode('utf-8', errors='replace').splitlines()[-lines:]
    except OSError:
        # Another UI may permanently delete this retained entry after discovery.
        return []
