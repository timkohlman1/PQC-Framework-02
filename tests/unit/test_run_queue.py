"""Queue ordering, decisions and restart state: no Docker, network or hardware."""
import json
from pathlib import Path

import pytest

from framework.run_queue import Queue, digest
from framework.campaign_executor import canonical_sha256


@pytest.fixture
def queue(tmp_path, monkeypatch):
    q = Queue(tmp_path)
    def offline(action, *args):
        assert action == 'prepare'
        folder = tmp_path / args[args.index('--job') + 1]
        folder.mkdir(parents=True)
        return {'profile': args[args.index('--profile') + 1],
                'repetitions': int(args[args.index('--repetitions') + 1]) if '--repetitions' in args else 3,
                'conditions': 2, 'attempts': 6}
    monkeypatch.setattr(q, 'offline', offline)
    return q


def verdict(q, identifier, *, state='completed', failures=0, cleanup='passed', accepted=False):
    path = q.folder(identifier) / 'campaigns/owned/campaign-manifest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    planned = q.job(identifier)['attempts']
    value = {'state': state, 'cleanup': {'status': cleanup},
             'summary': {'planned': planned, 'completed': planned-failures, 'failed': failures, 'blocked': 0},
             'runs': [{'state': 'failed', **({'accepted_failure': {'decision': 'operator_accept'}} if accepted else {})} for _ in range(failures)]}
    value['final_index'] = {'status': 'finalized', 'sha256': canonical_sha256(value)}
    path.write_text(json.dumps(value))
    return path


def activate(q):
    with q.connect() as db:
        db.execute("UPDATE settings SET value='running' WHERE key='dispatch'")


def test_order_paused_skip_append_and_persistence(queue):
    a, b, c = queue.add(['baseline', 'secure_boot', 'thesis_kex'])
    queue.pause(a)
    queue.move(c, 'up')
    activate(queue)
    assert queue.claim()['id'] == c
    queue.add(['baseline'], 4)
    reopened = Queue(queue.root)
    assert [r['id'] for r in reopened.jobs()][:3] == [a, c, b]
    assert reopened.job(a)['status'] == 'paused'
    assert reopened.job(c)['status'] == 'running'
    assert reopened.claim()['id'] == b
    with pytest.raises(ValueError, match='waiting'):
        reopened.move(c, 'down')


def test_pause_active_is_cooperative_and_stop_persists(queue):
    a, b = queue.add(['one', 'two'])
    activate(queue)
    queue.claim()
    queue.pause(a)
    assert queue.job(a)['status'] == 'pausing'
    assert (queue.folder(a) / 'pause.request').exists()
    queue.stop()
    assert queue.claim() is None
    assert queue.job(b)['status'] == 'queued'


def test_failure_requires_explicit_decision_and_keeps_evidence(queue):
    identifier, = queue.add(['one'])
    path = verdict(queue, identifier, state='paused', failures=1)
    before = path.read_bytes()
    queue.finish(identifier, 'attention', 'failed')
    with pytest.raises(ValueError, match='retry or accept'):
        queue.decide(identifier, 'resume')
    queue.decide(identifier, 'accept')
    assert queue.job(identifier)['mode'] == 'accept'
    assert path.read_bytes() == before
    queue.finish(identifier, 'completed_with_failures', 'accepted')
    queue.mark(identifier)
    with pytest.raises(ValueError, match='unmark'):
        queue.decide(identifier, 'retry')
    queue.mark(identifier)
    queue.decide(identifier, 'retry')
    assert queue.job(identifier)['status'] == 'queued'


def test_unsafe_cleanup_halts_dispatch(queue):
    identifier, second = queue.add(['one', 'two'])
    activate(queue)
    row = queue.claim()
    def runner(command, log):
        if 'campaign-gateway' in command:
            verdict(queue, identifier, cleanup='failed')
            return 1
        return 0
    queue.run_job(row, runner)
    assert queue.job(identifier)['status'] == 'attention'
    assert queue.dispatch().startswith('halted')
    assert queue.claim() is None
    assert queue.job(second)['status'] == 'queued'


def test_safe_failure_yields_to_next_and_accept_does_not_relabel_success(queue):
    identifier, second = queue.add(['one', 'two'])
    activate(queue)
    row = queue.claim()
    def runner(command, log):
        if 'campaign-gateway' in command:
            path = verdict(queue, identifier, state='paused', failures=1)
            value = json.loads(path.read_text())
            value['pause'] = {'reason': 'error'}
            path.write_text(json.dumps(value))
            return 75
        return 0
    queue.run_job(row, runner)
    assert queue.job(identifier)['status'] == 'attention'
    assert queue.claim()['id'] == second
    queue.decide(identifier, 'accept')
    row = queue.claim()
    def accepted(command, log):
        if 'campaign-gateway' in command:
            assert '--accept-failed' in command and '--resume' in command
            verdict(queue, identifier, state='completed_with_failures', failures=1, accepted=True)
            return 1
        return 0
    queue.run_job(row, accepted)
    assert queue.job(identifier)['status'] == 'completed_with_failures'


def test_resume_before_first_dispatch_does_not_invent_manifest(queue):
    identifier, = queue.add(['one'])
    queue.pause(identifier)
    queue.decide(identifier, 'resume')
    assert not (queue.folder(identifier) / 'pause.request').exists()
    assert queue.manifest(identifier) is None


def test_source_check_failure_never_launches_hardware(queue):
    identifier, = queue.add(['one'])
    activate(queue)
    calls = []
    queue.run_job(queue.claim(), lambda command, log: calls.append(command) or 2)
    assert len(calls) == 1 and 'campaign-gateway' not in calls[0]
    assert queue.job(identifier)['status'] == 'attention'


def test_export_only_marked_and_locks_selected_jobs_without_blocking_reads(queue, monkeypatch):
    first, second = queue.add(['one', 'two'])
    for identifier in (first, second):
        verdict(queue, identifier)
        queue.finish(identifier, 'completed', 'done')
    queue.mark(first)
    def offline(action, *args):
        assert action == 'export'
        selection = json.loads((queue.root / args[args.index('--selection')+1]).read_text())
        assert [r['id'] for r in selection['jobs']] == [first]
        assert Queue(queue.root).jobs()  # Export must not hold the DB write lock.
        queue.mark(first)  # Unmarking cannot release the in-flight export guard.
        with pytest.raises(ValueError, match='export in progress'):
            queue.decide(first, 'retry')
        return {'rows': 1}
    monkeypatch.setattr(queue, 'offline', offline)
    assert queue.export()['rows'] == 1
    with queue.entry_lock(first, exclusive=True):
        pass


def test_export_refuses_changed_completed_evidence(queue):
    identifier, = queue.add(['one'])
    path = verdict(queue, identifier)
    queue.finish(identifier, 'completed', 'done')
    queue.mark(identifier)
    path.write_text(path.read_text() + ' ')
    with pytest.raises(ValueError, match='changed'):
        queue.export()


def test_restart_requires_recovery_decision(queue):
    identifier, = queue.add(['one'])
    activate(queue)
    queue.claim()
    with pytest.raises(ValueError, match='interrupted'):
        queue.start()
    assert queue.job(identifier)['status'] == 'attention'
    assert queue.dispatch().startswith('halted')


def test_invalid_counts_and_paths_fail_before_planning(queue, tmp_path):
    for count in (0, -1, True, 1001):
        with pytest.raises(ValueError, match='repetitions'):
            queue.add(['one'], count)
    with pytest.raises(ValueError, match='below results'):
        Queue(tmp_path, '../outside')
    (tmp_path / 'results/link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        Queue(tmp_path, 'results/link/queue')


def test_decision_refuses_changed_paused_manifest(queue):
    identifier, = queue.add(['one'])
    path = verdict(queue, identifier, state='paused')
    queue.finish(identifier, 'paused', 'pause')
    path.write_text(path.read_text() + ' ')
    with pytest.raises(ValueError, match='manifest changed'):
        queue.decide(identifier, 'resume')


def test_stop_cannot_clear_an_unresolved_cleanup_halt(queue):
    identifier, = queue.add(['one'])
    queue.finish(identifier, 'attention', 'cleanup failed', safe=False)
    queue.stop()
    assert queue.dispatch().startswith('halted')
    with pytest.raises(ValueError, match='cleanup'):
        queue.start()


def test_display_progress_history_completion_and_export_version(queue, monkeypatch):
    identifier = queue.add(['fixture'])[0]
    row = queue.display_jobs()[0]
    assert (row['success'], row['errors'], row['repeats'], row['attempts']) == (0, 0, 0, 6)
    path = verdict(queue, identifier)
    data = json.loads(path.read_text())
    data['runs'] = [{'state': 'completed', 'previous_attempts': [{'state': 'failed'}]},
                    {'state': 'failed', 'accepted_failure': {'decision': 'operator_accept'}},
                    {'state': 'blocked'}]
    path.write_text(json.dumps(data))
    row = queue.display_jobs()[0]
    assert (row['success'], row['errors'], row['repeats']) == (1, 2, 1)
    assert row['completed_at'] is None
    queue.finish(identifier, 'completed_with_failures', 'done')
    queue.mark(identifier)
    monkeypatch.setattr(queue, 'offline', lambda *args: {'rows': 3})
    queue.export()
    row = Queue(queue.root).display_jobs()[0]
    assert row['completed_at'] and row['exported']
    queue.mark(identifier)
    queue.decide(identifier, 'retry')
    assert not queue.display_jobs()[0]['exported']
    data['runs'][1]['state'] = 'completed'
    path.write_text(json.dumps(data))
    queue.finish(identifier, 'completed_with_failures', 'done again')
    assert not queue.display_jobs()[0]['exported']
    path.write_text('{')
    assert not queue.display_jobs()[0]['progress_available']


def test_old_export_records_are_visible(queue):
    identifier = queue.add(['fixture'])[0]
    verdict(queue, identifier)
    queue.finish(identifier, 'completed', 'done')
    destination = queue.directory / 'exports/legacy'
    destination.mkdir(parents=True)
    (destination / 'queue-selection.json').write_text(json.dumps({'jobs': [queue.job(identifier)]}))
    with queue.connect() as db:
        queue.event(db, None, 'export', queue.relative(destination))
    assert queue.display_jobs()[0]['exported']


def test_display_does_not_claim_missing_or_changed_evidence_exported(queue, monkeypatch):
    identifier = queue.add(['fixture'])[0]
    path = verdict(queue, identifier)
    queue.finish(identifier, 'completed', 'done')
    queue.mark(identifier)
    monkeypatch.setattr(queue, 'offline', lambda *args: {'rows': 1})
    queue.export()
    assert queue.display_jobs()[0]['exported']
    path.write_text(path.read_text() + ' ')
    assert not queue.display_jobs()[0]['exported']
    path.unlink()
    row = queue.display_jobs()[0]
    assert not row['progress_available'] and not row['exported']


def test_remove_retains_files_and_cannot_be_dispatched(queue):
    first, second = queue.add(['one', 'two'])
    path = verdict(queue, first, state='paused')
    before = path.read_bytes()
    queue.remove(first)
    assert queue.job(first)['status'] == 'removed'
    assert path.read_bytes() == before
    assert Queue(queue.root).display_jobs()[0]['status'] == 'removed'
    activate(queue)
    assert queue.claim()['id'] == second
    with pytest.raises(ValueError, match='waiting'):
        queue.remove(second)
    with pytest.raises(ValueError, match='active'):
        queue.purge(second, second)
    with pytest.raises(ValueError, match='paused or finished'):
        queue.decide(first, 'resume')


def test_remove_cannot_bypass_cleanup_halt(queue):
    identifier = queue.add(['one'])[0]
    queue.finish(identifier, 'attention', 'uncertain cleanup', safe=False)
    with pytest.raises(ValueError, match='recovery halt'):
        queue.remove(identifier)


def test_purge_keeps_other_jobs_and_combined_exports(queue):
    first, second = queue.add(['one', 'two'])
    path = verdict(queue, first, state='paused')
    queue.remove(first)
    export = queue.directory / 'exports/shared.csv'
    export.parent.mkdir()
    export.write_text('retained combined data')
    outside = queue.root / 'unrelated.txt'
    outside.write_text('keep')
    # A link inside the deleted tree is removed, never followed.
    (queue.folder(first) / 'external-link').symlink_to(outside)
    with pytest.raises(ValueError, match='exact entry ID'):
        queue.purge(first, 'yes')
    assert path.exists()
    queue.purge(first, first)
    assert not queue.folder(first).exists()
    assert [row['id'] for row in queue.display_jobs()] == [second]
    assert export.read_text() == 'retained combined data'
    assert outside.read_text() == 'keep'


def test_orphan_folder_discovery_and_purge(queue):
    identifier = queue.add(['old'])[0]
    plan = {'source': {'repository': {'git_commit': 'abcdef0123456789', 'git_dirty': True}},
            'steps': [{'profile': 'old.yaml', 'repetitions': 3, 'conditions': 2, 'attempts': 6}]}
    (queue.folder(identifier) / 'plan.json').write_text(json.dumps(plan))
    with queue.connect() as db:
        db.execute('DELETE FROM jobs WHERE id=?', (identifier,))
    row = queue.display_jobs()[0]
    assert row['status'] == 'retained' and row['version'] == 'abcdef0*'
    assert row['profile'] == 'old.yaml'
    activate(queue)
    assert queue.claim() is None
    queue.purge(identifier, identifier)
    assert queue.display_jobs() == []


def test_partial_retained_directory_is_discoverable(queue):
    folder = queue.folder('a' * 12)
    folder.mkdir(parents=True)
    (folder / 'partial.log').write_text('partial')
    assert queue.display_jobs()[0]['status'] == 'retained'
    queue.purge(folder.name, folder.name)
    assert not folder.exists()


def test_purge_respects_export_lock_and_selection(queue, monkeypatch):
    identifier = queue.add(['one'])[0]
    verdict(queue, identifier)
    queue.finish(identifier, 'completed', 'done')
    queue.mark(identifier)
    with pytest.raises(ValueError, match='unmark'):
        queue.purge(identifier, identifier)
    def offline(*args):
        queue.mark(identifier)
        with pytest.raises(ValueError, match='export in progress'):
            queue.purge(identifier, identifier)
        return {'rows': 1}
    monkeypatch.setattr(queue, 'offline', offline)
    queue.export()
    queue.purge(identifier, identifier)
    assert not queue.folder(identifier).exists()


def test_purge_failure_preserves_database_entry(queue, monkeypatch):
    import shutil
    identifier = queue.add(['one'])[0]
    queue.remove(identifier)
    def fail(*args): raise OSError('disk error')
    fail.avoids_symlink_attacks = True
    monkeypatch.setattr(shutil, 'rmtree', fail)
    with pytest.raises(OSError, match='disk error'):
        queue.purge(identifier, identifier)
    assert queue.job(identifier)['status'] == 'removed'


def test_purge_rejects_symlink_job_and_unregistered_active_manifest(queue):
    identifier = 'b' * 12
    outside = queue.root / 'outside'
    outside.mkdir()
    queue.folder(identifier).parent.mkdir(parents=True, exist_ok=True)
    queue.folder(identifier).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        queue.purge(identifier, identifier)
    assert outside.exists()
    other = queue.add(['one'])[0]
    verdict(queue, other, state='running')
    with queue.connect() as db:
        db.execute('DELETE FROM jobs WHERE id=?', (other,))
    with pytest.raises(ValueError, match='active run'):
        queue.purge(other, other)


def test_source_label_includes_dirty_submodule():
    from framework.run_queue import source_label
    assert source_label({}) == 'unknown'
    source = {'repository': {'git_commit': 'abcdef012345', 'git_dirty': False},
              'submodules': {'entries': [{'dirty': True}]}}
    assert source_label(source) == 'abcdef0*'


def test_unregistered_folder_cannot_be_purged_while_worker_holds_lock(queue):
    import fcntl
    identifier = 'd' * 12
    queue.folder(identifier).mkdir(parents=True)
    with (queue.directory / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='stop the queue worker'):
            queue.purge(identifier, identifier)
    assert queue.folder(identifier).exists()


def test_log_tail_returns_eight_lines_and_tolerates_concurrent_purge(queue, monkeypatch):
    from framework.run_queue import log_tail
    identifier = queue.add(['one'])[0]
    log = queue.folder(identifier) / 'logs/dispatch-0001.log'
    log.parent.mkdir()
    log.write_text(''.join(f'line {i}\n' for i in range(12)))
    assert log_tail(queue, identifier, 8) == [f'line {i}' for i in range(4, 12)]
    original = Path.open
    def vanished(path, *args, **kwargs):
        if path == log:
            raise FileNotFoundError('concurrent purge')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', vanished)
    assert log_tail(queue, identifier, 8) == []


def test_quit_stops_idle_queue_and_detects_lost_active_worker(queue):
    activate(queue)
    queue.shutdown()
    assert queue.dispatch() == 'stopped'
    queue.add(['one'])
    activate(queue)
    queue.claim()
    with pytest.raises(ValueError, match='cleanup is unverified'):
        queue.shutdown()
