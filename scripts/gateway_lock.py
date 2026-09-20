#!/usr/bin/env python3
"""Gateway-side, cross-host advisory lease for Linux framework commands.

The remote holder owns a POSIX flock for as long as its SSH stdin is open.
Never unlink the lock inode. All participating hosts must use the same SSH
identity and gateway account, and must enter through this launcher.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'configs/gateways/pqc_gateway1.yaml'
REMOTE = r'''
import fcntl, json, os, pathlib, signal, sys, time
mode = sys.argv[1]
root = pathlib.Path.home() / '.cache' / 'pqc-framework-gateway-lock'
root.mkdir(mode=0o700, parents=True, exist_ok=True)
lock_path = root / 'gateway.lock'
state_path = root / 'owner.json'
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
def read_state():
    try:
        return json.loads(state_path.read_text())
    except (OSError, ValueError):
        return {}
def active():
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    return False
def start_time(pid):
    try:
        return pathlib.Path('/proc/%s/stat' % pid).read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, ValueError, IndexError):
        return None
if mode == 'hold':
    owner, description = sys.argv[2:4]
    if active():
        print('BUSY ' + json.dumps(read_state(), sort_keys=True), flush=True)
        sys.exit(3)
    state = {'owner_id': owner, 'description': description, 'pid': os.getpid(),
             'start_time': start_time(os.getpid()), 'since': time.time()}
    temp = root / ('owner.' + owner + '.tmp')
    temp.write_text(json.dumps(state))
    os.replace(temp, state_path)
    print('ACQUIRED ' + json.dumps(state, sort_keys=True), flush=True)
    try:
        while os.read(0, 1024):
            pass
    finally:
        if read_state().get('owner_id') == owner:
            state_path.unlink(missing_ok=True)
        fcntl.flock(fd, fcntl.LOCK_UN)
elif mode == 'status':
    busy = active()
    state = read_state() if busy else {}
    print(json.dumps({'busy': busy, 'owner': state}, sort_keys=True), flush=True)
elif mode == 'release':
    requested = sys.argv[2]
    if not active():
        print('FREE', flush=True)
    else:
        state = read_state()
        pid = state.get('pid')
        if state.get('owner_id') != requested or not isinstance(pid, int) or \
                start_time(pid) != state.get('start_time'):
            print('OWNER_MISMATCH_OR_STALE ' + json.dumps(state, sort_keys=True), flush=True)
            sys.exit(4)
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            time.sleep(.1)
            if not active():
                print('RELEASED ' + requested, flush=True)
                break
        else:
            print('RELEASE_UNCONFIRMED', flush=True)
            sys.exit(5)
else:
    sys.exit(2)
'''


def gateway_target(config: Path = CONFIG) -> str:
    """Read the two canonical identity scalar values without loading secrets."""
    section = None
    values = {}
    for raw in config.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0]
        if line and not line[0].isspace() and line.endswith(':'):
            section = line[:-1]
        elif section == 'identity' and ':' in line:
            key, value = line.strip().split(':', 1)
            values[key] = value.strip().strip('"\'')
    user = values.get('ssh_user')
    host = values.get('fqdn') or values.get('alias')
    if not user or not host:
        raise ValueError('gateway identity.ssh_user/fqdn is missing')
    return f'{user}@{host}'


def ssh_command(target: str, mode: str, *args: str) -> list[str]:
    remote = ' '.join(shlex.quote(v) for v in ('python3', '-u', '-c', REMOTE, mode, *args))
    return ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
            '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2', target, remote]


def remote_query(target: str, mode: str, *args: str) -> int:
    return subprocess.call(ssh_command(target, mode, *args))


def attempt(target: str, owner: str, description: str) -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(ssh_command(target, 'hold', owner, description),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, bufsize=1)
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], 15)
    if not ready:
        process.kill()
        process.wait()
        raise RuntimeError('gateway lock handshake timed out')
    line = process.stdout.readline().strip()
    if line.startswith('ACQUIRED '):
        return process, line
    error = process.stderr.read() if process.stderr else ''
    process.wait()
    if line.startswith('BUSY '):
        raise BlockingIOError(line)
    raise RuntimeError(f'gateway lock acquisition failed: {line} {error}')



class WaitDisplay:
    """One updating TTY line; event-only output for redirected/CI logs."""

    SPINNER = ('|', '/', '-', '\\')

    def __init__(self, stream=None, clock=None):
        self.stream = stream if stream is not None else sys.stderr
        self.clock = clock if clock is not None else time.monotonic
        self.started = self.clock()
        self.interactive = bool(getattr(self.stream, 'isatty', lambda: False)())
        self.owner_key = None
        self.width = 0
        self.frame = 0
        self.visible = False

    def _clear_line(self):
        if self.visible:
            self.stream.write('\r' + ' ' * self.width + '\r')
            self.visible = False
            self.width = 0

    def busy(self, message: str):
        # BUSY carries gateway-side JSON. Compare the complete canonical record
        # so changes to the owner, description or lease metadata are reported.
        raw = message.removeprefix('BUSY ').strip()
        try:
            owner = json.loads(raw)
            if not isinstance(owner, dict):
                raise ValueError('owner is not an object')
            key = json.dumps(owner, sort_keys=True)
            label = owner.get('description') or owner.get('owner_id') or 'unknown'
        except (ValueError, TypeError):
            key, label = raw, raw or 'unknown'
        changed = key != self.owner_key
        if changed:
            if self.interactive:
                self._clear_line()
            self.stream.write(f'Gateway busy | Owner: {label} | Ctrl-C to cancel\n')
            self.owner_key = key
        if self.interactive:
            elapsed = max(0, int(self.clock() - self.started))
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            duration = f'{hours}h {minutes:02d}m {seconds:02d}s' if hours else f'{minutes}m {seconds:02d}s'
            frame = self.SPINNER[self.frame % len(self.SPINNER)]
            self.frame += 1
            line = f'{frame} Gateway busy | Owner: {label} | Waiting: {duration} | Ctrl-C to cancel'
            self.stream.write('\r' + line + ' ' * max(0, self.width - len(line)))
            self.width = len(line)
            self.visible = True
        self.stream.flush()

    def finish(self):
        if self.interactive:
            self._clear_line()
            self.stream.flush()


def run_locked(target: str, command: list[str], *, interval: float = 2.0) -> int:
    if not command:
        raise ValueError('missing command')
    owner = uuid.uuid4().hex
    description = f'{os.uname().nodename} user={os.environ.get("USER", "unknown")} command={" ".join(command)[:140]}'
    display = WaitDisplay()
    while True:
        try:
            lease, info = attempt(target, owner, description)
            break
        except BlockingIOError as exc:
            display.busy(str(exc))
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                display.finish()
                print('Gateway wait cancelled.', file=sys.stderr)
                return 130
        except KeyboardInterrupt:
            display.finish()
            print('Gateway wait cancelled.', file=sys.stderr)
            return 130
        except (OSError, RuntimeError) as exc:
            display.finish()
            print(f'Gateway lock error: {exc}', file=sys.stderr)
            return 2
    display.finish()
    print(f'Gateway lock acquired: {info}', file=sys.stderr, flush=True)
    child = None
    lost = threading.Event()
    finished = threading.Event()
    def watch() -> None:
        while not finished.wait(.2):
            if lease.poll() is not None:
                lost.set()
                if child is not None and child.poll() is None:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                return
    try:
        child = subprocess.Popen(command, start_new_session=True)
        monitor = threading.Thread(target=watch, daemon=True)
        monitor.start()
        try:
            result = child.wait()
        except KeyboardInterrupt:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            return 130
        if lost.is_set() or lease.poll() is not None:
            print('Gateway lease lost; command terminated. Gateway state must be checked.', file=sys.stderr)
            return 3
        return result
    finally:
        finished.set()
        if lease.stdin:
            try:
                lease.stdin.close()
            except OSError:
                pass
        try:
            lease.wait(timeout=5)
        except subprocess.TimeoutExpired:
            lease.kill()
            lease.wait()
        if lease.stdout:
            lease.stdout.close()
        if lease.stderr:
            lease.stderr.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Gateway-wide experiment lock (Linux)')
    parser.add_argument('--gateway', default=None, help='Override SSH target')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    release = sub.add_parser('release', help='Terminate an identified holder; use only after checking status')
    release.add_argument('--owner-id', required=True)
    release.add_argument('--force', action='store_true', required=True)
    run = sub.add_parser('run')
    run.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        target = args.gateway or gateway_target()
        if args.action == 'status':
            return remote_query(target, 'status')
        if args.action == 'release':
            return remote_query(target, 'release', args.owner_id)
        command = args.command[1:] if args.command[:1] == ['--'] else args.command
        previous = signal.getsignal(signal.SIGTERM)
        def stop(_signum, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        try:
            return run_locked(target, command)
        finally:
            signal.signal(signal.SIGTERM, previous)
    except (OSError, ValueError) as exc:
        print(f'Gateway lock: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
