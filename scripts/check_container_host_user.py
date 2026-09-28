#!/usr/bin/env python3
"""Host-side, stdlib-only ownership gate using the built development image.

No gateway, real SSH material, firmware or experiment is used. Temporary dummy
SSH configuration exercises the gateway wrapper's local setup only. The gateway
lease marker is scoped to these child probes; no gateway command is executed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


class CheckError(RuntimeError):
    pass


def _run(args: list[str], *, cwd: Path, env: dict[str, str], expected: int = 0) -> str:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True,
                            timeout=120, check=False)
    if result.returncode != expected:
        raise CheckError(f'probe exited {result.returncode}, expected {expected}: '
                         f'{result.stdout}\n{result.stderr}')
    return result.stdout


def _snapshot(path: Path) -> tuple[int, int, int, str]:
    info = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ''
    return info.st_uid, info.st_gid, info.st_mode & 0o7777, digest


IDENTITY_PROBE = r'''
import json, os, pwd, tempfile
from pathlib import Path
home = Path.home()
assert home == Path(pwd.getpwuid(os.getuid()).pw_dir)
(home / 'writable-home').write_text('probe')
parent = Path('results/analysis')
parent.mkdir(parents=True, exist_ok=True)
path = Path(tempfile.mkdtemp(prefix='.stage-', dir=parent))
(path / 'value.txt').write_text('host-user-probe')
path = path.rename(parent / 'ownership-probe')
print(json.dumps({'uid': os.getuid(), 'gid': os.getgid(),
                  'groups': sorted(os.getgroups()), 'home': str(home),
                  'mode': path.stat().st_mode & 0o777,
                  'gateway': os.environ.get('PQC_CONTAINER_ENABLE_GATEWAY')}))
'''

SSH_PROBE = r'''
import json, os, pwd, subprocess
from pathlib import Path
home = Path.home()
assert home == Path(pwd.getpwuid(os.getuid()).pw_dir)
assert home != Path('/root')
assert (home / '.ssh').stat().st_mode & 0o777 == 0o700
assert (home / '.ssh/config').stat().st_mode & 0o777 == 0o600
assert (home / '.ssh/test-identity').stat().st_mode & 0o777 == 0o600
assert os.environ['PQC_CONTAINER_ENABLE_GATEWAY'] == '1'
try:
    Path('/host-ssh/should-not-exist').write_text('must fail')
except PermissionError:
    pass
except OSError as exc:
    assert exc.errno == 30, str(exc)  # EROFS
else:
    raise AssertionError('host SSH mount was writable')
configured = subprocess.run(['ssh', '-G', '-T', 'pqc-host-user-check.invalid'],
                            text=True, capture_output=True, check=True)
assert 'user pqc-probe\n' in configured.stdout
print(json.dumps({'uid': os.getuid(), 'gid': os.getgid(), 'ssh_config': 'verified'}))
'''

OVERLAY_TEST = r'''
import json, os
from pathlib import Path

def test_private_generated_overlays():
    for name in ('build', '.pqc-generated-state'):
        path = Path(name)
        assert not (path / 'host-sentinel').exists()
        assert path.stat().st_uid == os.getuid() != 0
        (path / 'container-only').write_text('probe')
    Path('overlay-result.json').write_text(json.dumps({'uid': os.getuid(), 'gid': os.getgid()}))
'''


def run_checks(repo_root: Path) -> dict[str, object]:
    if sys.platform != 'linux' or os.getuid() == 0 or os.getgid() == 0:
        raise CheckError('Run ./scripts/dev.sh check-host-user as a non-root Linux user')
    if shutil.which('docker') is None:
        raise CheckError('Docker is unavailable; ownership runtime check was not run')
    env = {k: v for k, v in os.environ.items() if not k.startswith('PQC_')}
    env['PQC_DOCKER_IMAGE'] = os.environ.get('PQC_DOCKER_IMAGE', 'pqc-framework-stm32-build')
    endpoint = env.get('DOCKER_HOST', '')
    if env.get('DOCKER_CONTEXT') or not endpoint:
        context = _run(['docker', 'context', 'show'], cwd=repo_root, env=env).strip()
        endpoint = _run(['docker', 'context', 'inspect', context, '--format',
                         '{{.Endpoints.docker.Host}}'], cwd=repo_root, env=env).strip()
    if not endpoint.startswith('unix://'):
        raise CheckError('This ownership gate requires a local Unix-socket Docker daemon')
    security = _run(['docker', 'info', '--format', '{{json .SecurityOptions}}'],
                    cwd=repo_root, env=env)
    if any(word in security for word in ('rootless', 'userns')):
        raise CheckError('Rootless/userns remapping is not qualified by this ownership policy')
    _run(['docker', 'image', 'inspect', env['PQC_DOCKER_IMAGE']], cwd=repo_root, env=env)
    with tempfile.TemporaryDirectory(prefix='pqc-host-user-check-') as directory:
        root = Path(directory)
        (root / 'scripts').mkdir()
        shutil.copy2(repo_root / 'scripts/dev.sh', root / 'scripts/dev.sh')
        ssh = root / 'dummy-ssh'
        ssh.mkdir(mode=0o700)
        (ssh / 'config').write_text('Host pqc-host-user-check.invalid\n'
                                   '    HostName 127.0.0.1\n    User pqc-probe\n'
                                   '    IdentityFile ~/.ssh/test-identity\n')
        (ssh / 'test-identity').write_text('synthetic permission fixture, not a private key\n')
        (ssh / 'test-identity').chmod(0o600)
        before = {p.name: _snapshot(p) for p in ssh.iterdir()}
        env.update(PQC_DOCKER_SSH_DIR=str(ssh), PQC_GATEWAY_LOCK_HELD='1')
        wrapper = ['sh', str(root / 'scripts/dev.sh')]
        plain = json.loads(_run([*wrapper, 'python', '-c', IDENTITY_PROBE], cwd=root, env=env))
        if (plain['uid'], plain['gid']) != (os.getuid(), os.getgid()):
            raise CheckError('container workload identity differs from host')
        if plain['mode'] != 0o700 or plain['gateway'] is not None:
            raise CheckError('private output or gateway separation did not survive')
        if plain['groups'] != sorted(set(os.getgroups()) | {os.getgid()}):
            raise CheckError('supplementary groups differ from host')
        output = root / 'results/analysis/ownership-probe'
        for path in (output, output / 'value.txt'):
            if (path.stat().st_uid, path.stat().st_gid) != (os.getuid(), os.getgid()):
                raise CheckError('host-visible output has incorrect ownership')
        if (output / 'value.txt').read_text() != 'host-user-probe':
            raise CheckError('host cannot read generated output')
        gateway = json.loads(_run([*wrapper, 'python-gateway', '-c', SSH_PROBE], cwd=root, env=env))
        if (gateway['uid'], gateway['gid']) != (os.getuid(), os.getgid()):
            raise CheckError('gateway wrapper workload is not mapped to host identity')
        if {p.name: _snapshot(p) for p in ssh.iterdir()} != before:
            raise CheckError('host SSH fixture changed')
        overlay_before = {}
        for name in ('build', '.pqc-generated-state'):
            (root / name).mkdir()
            (root / name / 'host-sentinel').write_text('must remain unchanged')
            overlay_before[name] = _snapshot(root / name)
        (root / 'test_overlay_probe.py').write_text(OVERLAY_TEST)
        _run([*wrapper, 'pytest-hardware', '-q', 'test_overlay_probe.py'], cwd=root, env=env)
        for name, original in overlay_before.items():
            if _snapshot(root / name) != original or (root / name / 'container-only').exists():
                raise CheckError('isolated mount changed host generated state')
            if (root / name / 'host-sentinel').read_text() != 'must remain unchanged':
                raise CheckError('host overlay sentinel changed')
        _run([*wrapper, 'run', 'sh', '-c', 'exit 17'], cwd=root, env=env, expected=17)
    return {'status': 'verified', 'host_uid': os.getuid(), 'host_gid': os.getgid(),
            'checks': ['host_output_ownership', 'private_directory_0700', 'writable_home',
                       'passwd_home', 'supplementary_groups', 'dummy_ssh_read_only',
                       'isolated_generated_volumes', 'workload_exit_status'],
            'scope': 'local_container_only_no_gateway_or_firmware'}


def main() -> int:
    if len(sys.argv) != 1:
        print('Usage: ./scripts/dev.sh check-host-user', file=sys.stderr)
        return 2
    try:
        print(json.dumps(run_checks(Path(__file__).resolve().parents[1]), sort_keys=True))
    except (OSError, ValueError, CheckError, subprocess.TimeoutExpired) as exc:
        print(f'Container ownership check failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
