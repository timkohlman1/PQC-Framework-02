"""Interactive migration planning and queue orchestration (host stdlib only)."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from framework.run_queue import Queue, ACTIVE, DONE, digest, owned_path, read

VERSION = 1
SIDES = ('from', 'to')
LABELS = {
    'mqtt_transport': 'MQTT transport', 'tls_kex': 'TLS key exchange',
    'tls_auth': 'TLS certificate/signature', 'auth_mode': 'TLS authentication',
    'secure_boot': 'Firmware authentication', 'firmware_mode': 'Firmware layout / OTA support',
    'standby_signing_keys': 'Standby firmware signing keys',
    'network_condition': 'Network condition', 'payload_bytes': 'Response payload (bytes)',
    'chunk_bytes': 'MQTT chunk (bytes)',
}
DEFAULTS = dict(mqtt_transport='tls', tls_kex='secp256r1', tls_auth='ecdsa-p256',
    auth_mode='server', secure_boot='integrity_sha256', firmware_mode='single_bank',
    standby_signing_keys=0, network_condition='baseline', payload_bytes=204800, chunk_bytes=400)


def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)


@contextmanager
def session_lock(path):
    with path.with_suffix('.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('this comparison is already open in another process')
        yield


def helper(queue, action, session=None):
    command = [str(queue.root / 'scripts/dev.sh'), 'python', 'scripts/migration_workspace.py', action]
    if session is not None:
        command += ['--session', queue.relative(session)]
    result = subprocess.run(command, cwd=queue.root, text=True, capture_output=True)
    if result.returncode:
        raise ValueError((result.stderr + result.stdout)[-6000:] or 'migration helper failed')
    return json.loads(result.stdout.strip().splitlines()[-1])


def choose(title, values, default, *, descriptions=None, unchanged=False, ask=input, tell=print):
    values = list(values)
    if not values:
        raise ValueError('no supported choices for ' + title)
    descriptions = descriptions or {}
    inherited = unchanged and default in values
    options = [default, *[v for v in values if v != default]] if inherited else values
    default_index = 0 if inherited else (values.index(default) if default in values else 0)
    tell('\n' + title)
    for index, value in enumerate(options):
        label = f'Unchanged ({value})' if inherited and index == 0 else str(value)
        explanation = descriptions.get(value)
        tell(f'  {index+1}. {label}' + (f' — {explanation}' if explanation else ''))
    while True:
        reply = ask(f'Choice [{default_index+1}]: ').strip()
        if not reply:
            return options[default_index]
        if reply.isdecimal() and 1 <= int(reply) <= len(options):
            return options[int(reply)-1]
        tell('Enter one of the displayed numbers.')


def integer(title, default, low, high, *, ask=input, tell=print):
    while True:
        reply = ask(f'{title} [{default}]: ').strip()
        value = default if not reply else int(reply) if reply.isdecimal() else None
        if type(value) is int and low <= value <= high:
            return value
        tell(f'Enter a whole number from {low} to {high}.')


def wizard(catalogue, *, ask=input, tell=print):
    tell('Compare two fresh-connection MQTT wake-and-transfer configurations on the framework testbed.\n'
         'Ten fixed attempts per state are a pilot default; failures remain outcomes. Energy is off.\n'
         'The gateway sends the response payload to the device. Firmware layout choices measure built-in support, not an executed OTA update.')
    result = {}
    for side in SIDES:
        tell('\nCURRENT STATE (from)' if side == 'from' else '\nFUTURE STATE (to)')
        prior = result.get('from', DEFAULTS)
        chosen = {}
        def select(key, values=None):
            selected = choose(LABELS[key], values if values is not None else catalogue['options'][key],
                prior.get(key) if prior.get(key) is not None else DEFAULTS.get(key), descriptions=catalogue['descriptions'].get(key, {}),
                unchanged=side == 'to' and prior.get(key) is not None, ask=ask, tell=tell)
            chosen[key] = selected
            return selected
        select('mqtt_transport')
        if chosen['mqtt_transport'] == 'tls':
            select('tls_kex'); select('tls_auth')
            select('auth_mode', catalogue['auth_modes'][chosen['tls_auth']])
        else:
            chosen.update(tls_kex=None, tls_auth=None, auth_mode=None)
            tell('TLS key exchange and authentication do not apply to plaintext.')
        select('secure_boot'); select('firmware_mode')
        if chosen['secure_boot'] in catalogue['signed_boot']:
            select('standby_signing_keys')
        else:
            chosen['standby_signing_keys'] = 0
        select('network_condition')
        for key, presets in [('payload_bytes', [256, 1024, 4096, 32768, 204800]),
                             ('chunk_bytes', [128, 256, 400, 1024])]:
            values = sorted({*presets, prior[key]})
            if key == 'chunk_bytes':
                values = [v for v in values if v <= chosen['payload_bytes']]
            choice = select(key, [*values, 'Custom'])
            if choice == 'Custom':
                chosen[key] = integer(LABELS[key], min(prior[key], chosen.get('payload_bytes', 1048576)),
                    1, chosen['payload_bytes'] if key == 'chunk_bytes' else 1048576, ask=ask, tell=tell)
        result[side] = chosen
    result['repetitions'] = integer('Attempts per state', 10, 1, 1000, ask=ask, tell=tell)
    return result


def profile(base, choices, name, repetitions):
    data = deepcopy(base)
    data.update(id=name, description='MQTT migration A/B: ' + name, workload='ready_metrics_2')
    data.pop('queue_profile', None); data.pop('analysis_baselines', None); data.pop('instruments', None)
    data['fixed'] = {k: choices[k] for k in ('mqtt_transport', 'secure_boot', 'firmware_mode',
                                          'standby_signing_keys', 'network_condition')}
    data['fixed'].update(boot_stack_profiling=False, boot_uart_diagnostics=False)
    if choices['mqtt_transport'] == 'tls':
        data['fixed'].update({k: choices[k] for k in ('tls_kex', 'tls_auth', 'auth_mode')})
    data['matrix'] = {'workload.transfer.' + k: [choices[k]] for k in ('payload_bytes', 'chunk_bytes')}
    data['execution'].update(repetitions=repetitions, energy_monitoring='off', workload_failures='record')
    return data


def new_session(queue, catalogue, choices):
    name = 'migration_' + time.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    folder = owned_path(queue.root, 'results/migrations/' + name)
    folder.mkdir(parents=True)
    value = dict(schema='pqc-migration', version=VERSION, id=name, queue=queue.relative(queue.directory),
                 choices=choices, profiles={}, profile_hashes={}, jobs={}, export=None, report=None)
    path = folder / 'session.json'
    atomic_json(path, value)
    print('Preparing session: ' + str(path), flush=True)
    for side in SIDES:
        data = profile(catalogue['base'], choices[side], name + '_' + side, choices['repetitions'])
        # Validate both definitions before any jobs can become dispatchable.
        queue.campaign_editor({'action': 'validate', 'data': data})
    for side in SIDES:
        filename = name + '_' + side + '.yaml'
        data = profile(catalogue['base'], choices[side], name + '_' + side, choices['repetitions'])
        queue.campaign_editor({'action': 'save', 'profile': filename, 'sha256': None, 'data': data})
        value['profiles'][side] = filename
        value['profile_hashes'][side] = digest(queue.root / 'results/profiles' / filename)
        atomic_json(path, value)
    return path, value


def submit(queue, path, value):
    """Recover a post-registration interruption without submitting a second pair."""
    if set(value['profiles']) != set(SIDES):
        raise ValueError('profile creation was incomplete; start a new comparison (no jobs submitted)')
    by_profile = {name: [r for r in queue.jobs() if r['profile'] == name]
                  for name in value['profiles'].values()}
    found = {side: by_profile[value['profiles'][side]] for side in SIDES}
    if any(found.values()):
        if any(len(rows) != 1 for rows in found.values()):
            raise ValueError('partial or duplicated queue registration; inspect session profiles before continuing')
        ids = {side: found[side][0]['id'] for side in SIDES}
        if value['jobs'] and value['jobs'] != ids:
            raise ValueError('session queue identity changed')
    else:
        if value['jobs']:
            raise ValueError('recorded jobs are missing; refusing to repeat experiments')
        for side in SIDES:
            if digest(queue.root / 'results/profiles' / value['profiles'][side]) != value['profile_hashes'][side]:
                raise ValueError('local migration profile changed before enqueueing')
        ids = dict(zip(SIDES, queue.add([value['profiles'][s] for s in SIDES])))
    value['jobs'] = ids
    atomic_json(path, value)
    return ids


def wait_for_jobs(queue, ids, *, ask=input, tell=print, sleep=time.sleep, poll=5):
    previous = None
    while True:
        rows = queue.jobs()
        own = [next((r for r in rows if r['id'] == ids[s]), None) for s in SIDES]
        if any(r is None or r['status'] == 'removed' for r in own):
            raise ValueError('a comparison job was removed; retained captures are not a completed comparison')
        states = ', '.join(f"{s}: {r['status']} ({r['id']})" for s, r in zip(SIDES, own))
        ahead = [r for r in rows if r['id'] not in ids.values() and r['status'] in ACTIVE | {'queued'}
                 and r['position'] < max(r['position'] for r in own)]
        message = states + (f"; waiting for {len(ahead)} other queue job(s): " + ', '.join(r['id'] for r in ahead) if ahead else '')
        # Counts are read only for our two campaigns, not the whole historical queue.
        progress = []
        for r in own:
            manifest = queue.manifest(r['id'])
            if manifest:
                try:
                    runs = read(manifest)['runs']
                    summary = {state: sum(item.get('state') == state for item in runs)
                               for state in ('completed', 'failed', 'blocked')}
                    progress.append(f"{r['id']}: {summary.get('completed', 0)} completed, "
                                    f"{summary.get('failed', 0)} failed, {summary.get('blocked', 0)} blocked / {r['attempts']} planned")
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    progress.append(r['id'] + ': progress unavailable')
        message += '\n' + '; '.join(progress) if progress else ''
        if message != previous:
            tell(message); previous = message
        if all(r['status'] in DONE for r in own):
            return
        if queue.dispatch().startswith('halted'):
            raise ValueError('queue halted for cleanup/recovery; inspect run_queue.py before resuming this session')
        for r in own:
            if r['status'] == 'attention':
                manifest = queue.manifest(r['id'])
                data = read(manifest) if manifest else {}
                if (data.get('state') == 'completed_with_failures' and data.get('cleanup', {}).get('status') == 'passed'
                        and any(x.get('state') in {'failed', 'blocked'} and not x.get('accepted_failure') for x in data.get('runs', []))):
                    tell(r['detail'])
                    decision = choose('Keep the fixed trial count?', ['Retain failed attempts and analyse', 'Detach for inspection'],
                                      'Retain failed attempts and analyse', ask=ask, tell=tell)
                    if decision == 'Detach for inspection':
                        raise ValueError('detached; resolve the entry and resume this session')
                    queue.decide(r['id'], 'accept')
                else:
                    raise ValueError('comparison needs inspection: ' + r['id'] + ': ' + r['detail'])
            if r['status'] == 'paused':
                raise ValueError('comparison job paused externally; resume it in run_queue.py, then resume this session')
        if queue.dispatch() != 'running' or not queue.worker_alive():
            raise ValueError('queue dispatch stopped; start it in run_queue.py, then resume this session')
        sleep(poll)


def run(queue, path, value, *, ask=input, tell=print):
    with session_lock(path):
        if value.get('schema') != 'pqc-migration' or value.get('version') != VERSION:
            raise ValueError('unsupported migration session')
        ids = submit(queue, path, value)
        if not all(queue.job(i)['status'] in DONE for i in ids.values()):
            if queue.dispatch() != 'running' or not queue.worker_alive():
                choice = choose('The shared queue is stopped', ['Start shared queue', 'Detach'],
                                'Start shared queue', ask=ask, tell=tell)
                if choice == 'Detach':
                    return None
                queue.start()
                deadline = time.monotonic() + 5
                while not queue.worker_alive() and time.monotonic() < deadline:
                    time.sleep(.1)
            wait_for_jobs(queue, ids, ask=ask, tell=tell)
        if not value['export']:
            value['export'] = queue.export(identifiers=[ids[s] for s in SIDES])['output']
            atomic_json(path, value)
        if not value['report']:
            value['report'] = helper(queue, 'report', path)
            atomic_json(path, value)
        else:
            helper(queue, 'verify', path)
        report = owned_path(queue.root, value['report']['output'])
        tell((report / 'comparison.txt').read_text())
        tell('LaTeX: ' + str(report / 'comparison.tex') + '\n       ' + str(report / 'selections.tex'))
        return value['report']
