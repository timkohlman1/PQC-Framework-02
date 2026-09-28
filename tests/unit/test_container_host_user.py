from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runtime():
    return load_script('container_runtime')


@pytest.fixture
def wrapper(tmp_path):
    root = tmp_path / 'repo with spaces'
    (root / 'scripts').mkdir(parents=True)
    shutil.copy2(ROOT / 'scripts/dev.sh', root / 'scripts/dev.sh')
    tools = tmp_path / 'fake-bin'
    tools.mkdir()
    (tools / 'id').write_text('#!/bin/sh\ncase "$1" in\n'
                             '-u) echo "${FAKE_UID:-1234}";;\n'
                             '-g) echo "${FAKE_GID:-2345}";;\n'
                             '-G) echo "2345 3456";;\nesac\n')
    (tools / 'id').chmod(0o755)
    (tools / 'docker').write_text(f'#!{sys.executable}\n'
        'import json, os, sys\n'
        'from pathlib import Path\n'
        'Path(os.environ["RECORD"]).write_text(json.dumps({"argv":sys.argv[1:], '
        '"env":{k:v for k,v in os.environ.items() if k.startswith("PQC_")}}))\n'
        'sys.exit(int(os.environ.get("FAKE_RC", "0")))\n')
    (tools / 'docker').chmod(0o755)
    ssh = tmp_path / 'dummy ssh'
    ssh.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith('PQC_')}
    env.update(PATH=str(tools) + os.pathsep + env['PATH'], RECORD=str(tmp_path / 'record.json'),
               PQC_DOCKER_SSH_DIR=str(ssh), PQC_GATEWAY_LOCK_HELD='1',
               PQC_RUNTIME_UID='0', PQC_RUNTIME_GID='0')

    def run(args, additions=None, dotenv=None):
        current = dict(env)
        current.update(additions or {})
        if dotenv is not None:
            (root / '.env').write_text(dotenv)
        record = Path(current['RECORD'])
        record.unlink(missing_ok=True)
        completed = subprocess.run(['sh', str(root / 'scripts/dev.sh'), *args], cwd=root,
                                   env=current, text=True, capture_output=True, timeout=10)
        return completed, json.loads(record.read_text()) if record.exists() else None
    return run


WORKLOADS = [
    ('pytest', ['python', '-m', 'pytest']),
    ('pytest-gateway', ['python', '-m', 'pytest']),
    ('pytest-hardware', ['python', '-m', 'pytest']),
    ('experiment', ['python', 'scripts/experiment.py']),
    ('experiment-gateway', ['python', 'scripts/experiment.py']),
    ('campaign', ['python', 'scripts/run_campaign.py']),
    ('campaign-gateway', ['python', 'scripts/run_campaign.py']),
    ('python', ['python']), ('python-gateway', ['python']),
    ('cmake', ['cmake']), ('shell', ['sh']), ('run', []),
]


@pytest.mark.parametrize('name,prefix', WORKLOADS)
def test_every_workload_uses_host_mapping_and_installed_bootstrap(wrapper, name, prefix):
    payload = ['a path with spaces', '$(not-a-shell-command)', '']
    result, record = wrapper([name, *payload])
    assert result.returncode == 0, result.stderr
    argv, env = record['argv'], record['env']
    assert argv[:2] == ['run', '--rm']
    assert argv[argv.index('--user') + 1] == '0:0'  # setup only, never workload
    assert argv[argv.index('--entrypoint') + 1] == '/usr/local/bin/python3'
    start = argv.index('/usr/local/libexec/pqc-container-runtime.py')
    assert argv[start - 1] == '-I'
    assert argv[start + 1:] == prefix + payload
    assert env['PQC_RUNTIME_UID'] == '1234'
    assert env['PQC_RUNTIME_GID'] == '2345'
    assert env['PQC_RUNTIME_GROUPS'] == '2345 3456'
    assert '--security-opt' in argv and 'no-new-privileges' in argv
    assert '--privileged' not in argv
    assert not any('/root/.ssh' in value for value in argv)
    gateway = name.endswith('-gateway') or name == 'pytest-hardware'
    assert ('PQC_CONTAINER_ENABLE_GATEWAY=1' in argv) == gateway
    assert any(value.endswith('/host-ssh:ro') for value in argv) == gateway
    assert env['PQC_RUNTIME_ISOLATED'] == ('1' if name == 'pytest-hardware' else '0')


def test_hardware_overlay_mounts_start_empty_and_preserve_default_selection(wrapper):
    result, record = wrapper(['pytest-hardware'])
    argv = record['argv']
    assert result.returncode == 0
    for target in ('build', '.pqc-generated-state'):
        assert f'type=volume,target=/workspace/{target},volume-nocopy' in argv
    assert argv[-4:] == ['tests/hardware', '-m', 'hardware', '--pqc-require-hardware']


@pytest.mark.parametrize('name,prefix', WORKLOADS)
def test_root_workloads_fail_before_docker(wrapper, name, prefix):
    result, record = wrapper([name, '--help'], {'FAKE_UID': '0'})
    assert result.returncode == 2
    assert record is None
    assert 'non-root' in result.stderr


def test_build_image_still_installs_tools_as_root_without_host_identity(wrapper):
    result, record = wrapper(['build-image'], {'FAKE_UID': '0'})
    assert result.returncode == 0
    assert record['argv'] == ['build', '-f', 'docker/python/Dockerfile', '-t', 'pqc-framework-stm32-build', '.']


@pytest.mark.parametrize('names', [(), ('PQC_WIFI_SSID',), ('PQC_WIFI_PSK',), ('PQC_WIFI_SSID', 'PQC_WIFI_PSK')])
def test_wifi_values_are_forwarded_by_name_only(wrapper, names):
    additions = {name: 'synthetic confidential ' + name for name in names}
    result, record = wrapper(['python', 'test.py'], additions)
    assert result.returncode == 0
    for name, value in additions.items():
        assert name in record['argv']
        assert value not in ' '.join(record['argv'])
        assert record['env'][name] == value


def test_dotenv_precedence_and_unrelated_values_do_not_leak(wrapper):
    result, record = wrapper(['python', 'test.py'], {'PQC_WIFI_SSID': 'caller'},
                             'PQC_WIFI_SSID="file"\nPQC_WIFI_PSK="dummy psk"\nUNRELATED=ignored\n')
    assert result.returncode == 0
    assert record['env']['PQC_WIFI_SSID'] == 'caller'
    assert record['env']['PQC_WIFI_PSK'] == 'dummy psk'
    assert 'dummy psk' not in ' '.join(record['argv'])


def test_wrapper_preserves_failure_exit_code(wrapper):
    result, record = wrapper(['run', 'false'], {'FAKE_RC': '17'})
    assert result.returncode == 17


def test_wrapper_preserves_campaign_and_ota_environment(wrapper):
    supplied = {'PQC_CAMPAIGN_HW': '1', 'PQC_CAMPAIGN_HW_CONFIG': 'baseline',
                'PQC_OTA_HW_CASE': 'case with spaces', 'PQC_OTA_HW': '1'}
    result, record = wrapper(['python', 'test.py'], supplied)
    assert result.returncode == 0
    for name, value in supplied.items():
        assert name in record['argv']
        assert record['env'][name] == value


def test_missing_ssh_directory_fails_without_starting_docker(wrapper):
    result, record = wrapper(['python-gateway', 'test.py'], {'PQC_DOCKER_SSH_DIR': '/nonexistent-pqc-test-ssh'})
    assert result.returncode == 2 and record is None


@pytest.mark.parametrize('key,value', [
    ('PQC_RUNTIME_UID', ''), ('PQC_RUNTIME_UID', '0'), ('PQC_RUNTIME_UID', '-1'),
    ('PQC_RUNTIME_UID', '4294967295'), ('PQC_RUNTIME_UID', '1;id'),
    ('PQC_RUNTIME_GID', '0'), ('PQC_RUNTIME_GROUPS', '1234 invalid'),
    ('PQC_RUNTIME_UMASK', '0088'), ('PQC_RUNTIME_UMASK', '07777'),
])
def test_invalid_identity_is_rejected(runtime, key, value):
    env = {'PQC_RUNTIME_UID': '1234', 'PQC_RUNTIME_GID': '2345'}
    env[key] = value
    with pytest.raises(runtime.RuntimeSetupError):
        runtime.read_identity(env)


def test_identity_and_umask_preserved(runtime):
    assert runtime.read_identity({'PQC_RUNTIME_UID': '1234', 'PQC_RUNTIME_GID': '2345',
                                 'PQC_RUNTIME_GROUPS': '3456 2345 3456', 'PQC_RUNTIME_UMASK': '0002'}) == (1234, 2345, [2345, 3456], 0o002)


@pytest.mark.parametrize('existing', [False, True])
def test_account_has_resolvable_non_root_home_with_or_without_uid_collision(runtime, tmp_path, existing):
    (tmp_path / 'passwd').write_text('root:x:0:0:root:/root:/bin/sh\n' +
        ('existing:x:1234:77:old:/old:/bin/false\n' if existing else ''))
    (tmp_path / 'group').write_text('root:x:0:\n')
    name = runtime.prepare_account(1234, 2345, Path('/tmp/private-home'), etc=tmp_path)
    assert name == ('existing' if existing else 'pqc-1234')
    assert f'{name}:x:1234:2345:' in (tmp_path / 'passwd').read_text()
    assert ':/tmp/private-home:/bin/sh\n' in (tmp_path / 'passwd').read_text()
    assert (tmp_path / 'passwd').read_text().startswith('root:x:0:0:root:/root:/bin/sh\n')
    assert 'pqc-2345:x:2345:' in (tmp_path / 'group').read_text()


def test_ssh_copy_preserves_host_bytes_modes_and_symlink_target(runtime, tmp_path):
    source, home = tmp_path / 'source', tmp_path / 'home'
    source.mkdir(); home.mkdir()
    fixture = source / 'config'; fixture.write_text('synthetic config\n'); fixture.chmod(0o640)
    target = tmp_path / 'outside'; target.write_text('unchanged'); target.chmod(0o644)
    (source / 'linked').symlink_to(target)
    runtime.copy_ssh(source, home)
    assert fixture.read_text() == 'synthetic config\n'
    assert fixture.stat().st_mode & 0o777 == 0o640
    assert (home / '.ssh/config').stat().st_mode & 0o777 == 0o600
    assert (home / '.ssh').stat().st_mode & 0o777 == 0o700
    assert (home / '.ssh/linked').is_symlink()
    assert target.stat().st_mode & 0o777 == 0o644 and target.read_text() == 'unchanged'


@pytest.mark.parametrize('case', ['empty', 'nonempty', 'missing_mount', 'symlink'])
def test_overlay_init_never_recurses_or_chowns_an_unmounted_host_directory(runtime, monkeypatch, tmp_path, case):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir(); b.mkdir()
    if case == 'nonempty': (b / 'sentinel').write_text('untouched')
    if case == 'symlink':
        b.rmdir(); b.symlink_to(a, target_is_directory=True)
    info = tmp_path / 'mountinfo'
    mounts = [a] if case == 'missing_mount' else [a, b]
    info.write_text(''.join(f'10 9 0:1 / {p} rw - ext4 test rw\n' for p in mounts))
    called = []
    monkeypatch.setattr(runtime.os, 'fchown', lambda fd, uid, gid: called.append((fd, uid, gid)))
    if case == 'empty':
        runtime.prepare_overlays(1234, 2345, paths=(a, b), mountinfo=info)
        assert len(called) == 2
    else:
        with pytest.raises(runtime.RuntimeSetupError):
            runtime.prepare_overlays(1234, 2345, paths=(a, b), mountinfo=info)
        assert called == []


def test_privilege_drop_precedes_ssh_and_command_exec(runtime, monkeypatch, tmp_path):
    monkeypatch.setenv('PQC_RUNTIME_UID', '1234'); monkeypatch.setenv('PQC_RUNTIME_GID', '2345')
    monkeypatch.setenv('PQC_RUNTIME_GROUPS', '2345 3456')
    monkeypatch.setenv('PQC_RUNTIME_ISOLATED', '0')
    monkeypatch.setenv('PQC_CONTAINER_ENABLE_GATEWAY', '1')
    monkeypatch.setattr(runtime.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(runtime.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    monkeypatch.setattr(runtime, 'prepare_account', lambda *a: 'pqc-1234')
    events = []
    monkeypatch.setattr(runtime.os, 'chown', lambda *a: events.append('home-owner'))
    monkeypatch.setattr(runtime.os, 'setgroups', lambda groups: events.append(('groups', groups)))
    monkeypatch.setattr(runtime.os, 'setresgid', lambda *a: events.append(('gid', a)))
    monkeypatch.setattr(runtime.os, 'setresuid', lambda *a: events.append(('uid', a)))
    monkeypatch.setattr(runtime.os, 'getresuid', lambda: (1234,) * 3)
    monkeypatch.setattr(runtime.os, 'getresgid', lambda: (2345,) * 3)
    monkeypatch.setattr(runtime.os, 'umask', lambda *a: None)
    # main sets these after dropping IDs; register originals for monkeypatch undo.
    for key in ('HOME', 'USER', 'LOGNAME', 'XDG_CACHE_HOME'):
        monkeypatch.setenv(key, os.environ.get(key, ''))
    monkeypatch.setattr(runtime, 'copy_ssh', lambda *a: events.append('ssh'))
    monkeypatch.setattr(runtime.os, 'execvp', lambda *a: events.append(('exec', a)))
    runtime.main(['python', 'one argument', ''])
    assert events == ['home-owner', ('groups', [2345, 3456]), ('gid', (2345,) * 3),
                      ('uid', (1234,) * 3), 'ssh', ('exec', ('python', ['python', 'one argument', '']))]


def test_failed_drop_never_executes_command(runtime, monkeypatch, tmp_path):
    monkeypatch.setenv('PQC_RUNTIME_UID', '1234'); monkeypatch.setenv('PQC_RUNTIME_GID', '2345')
    monkeypatch.setenv('PQC_RUNTIME_ISOLATED', '0'); monkeypatch.setenv('PQC_CONTAINER_ENABLE_GATEWAY', '0')
    monkeypatch.setattr(runtime.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(runtime.tempfile, 'mkdtemp', lambda **kw: str(tmp_path))
    monkeypatch.setattr(runtime, 'prepare_account', lambda *a: 'pqc-1234')
    monkeypatch.setattr(runtime.os, 'chown', lambda *a: None)
    def fail(*args): raise PermissionError('test drop failure')
    monkeypatch.setattr(runtime.os, 'setgroups', fail)
    monkeypatch.setattr(runtime.os, 'execvp', lambda *a: pytest.fail('must not exec'))
    assert runtime.main(['test']) == 126


def test_provisioner_keeps_pinned_runtime_but_drops_before_material_creation(monkeypatch, tmp_path):
    module = load_script('provision_certificates')
    monkeypatch.setattr(module.shutil, 'which', lambda command: '/fake/docker')
    monkeypatch.setattr(module.os, 'getuid', lambda: 1234)
    monkeypatch.setattr(module.os, 'getgid', lambda: 2345)
    monkeypatch.setattr(module.os, 'getgroups', lambda: [2345, 3456])
    calls = []
    monkeypatch.setattr(module, '_run', lambda command: calls.append(command))
    target = tmp_path / 'output with spaces;$(false)'
    args = module.build_parser().parse_args(['--output', str(target), '--profile', 'test-profile', '--force'])
    module.provision_with_docker(args)
    command = calls[0]
    assert module.DOCKER_IMAGE in command
    assert 'PQC_RUNTIME_UID=1234' in command and 'PQC_RUNTIME_GID=2345' in command
    assert 'PQC_RUNTIME_UMASK=0077' in command
    shell = command[command.index('-ec') + 1]
    assert 'apk add' in shell and 'python3 -I /work/container_runtime.py' in shell
    assert '$(false)' not in shell
    assert command[-4:] == ['/output/' + target.name, '--profile', 'test-profile', '--force']


def test_root_provisioner_refused_before_creating_output(monkeypatch, tmp_path):
    module = load_script('provision_certificates')
    monkeypatch.setattr(module.shutil, 'which', lambda command: '/fake/docker')
    monkeypatch.setattr(module.os, 'getuid', lambda: 0)
    args = module.build_parser().parse_args(['--output', str(tmp_path / 'new' / 'certs')])
    with pytest.raises(SystemExit, match='non-root'):
        module.provision_with_docker(args)
    assert not (tmp_path / 'new').exists()


def test_image_installs_bootstrap_without_changing_pins_or_runtime_packages():
    text = (ROOT / 'docker/python/Dockerfile').read_text()
    assert 'COPY scripts/container_runtime.py /usr/local/libexec/pqc-container-runtime.py' in text
    assert 'ENTRYPOINT ["/usr/local/bin/python3", "-I", "/usr/local/libexec/pqc-container-runtime.py"]' in text
    assert 'CMD ["python", "-m", "pytest", "tests/unit"]' in text
    assert 'ARG DEBIAN_SNAPSHOT=20260914T040000Z' in text


def test_host_gate_is_registered_in_wrapper_and_ci():
    wrapper = (ROOT / 'scripts/dev.sh').read_text()
    ci = (ROOT / '.github/workflows/ci.yml').read_text()
    assert 'check-host-user)' in wrapper
    assert './scripts/dev.sh check-host-user' in ci
    assert 'Verify provisioned material ownership' in ci


def test_documented_ownership_and_deferred_gates_preserve_security():
    setup = (ROOT / 'docs/002_host_gateway_setup.md').read_text()
    architecture = (ROOT / 'docs/007_framework_architecture.md').read_text()
    for value in ('check-host-user', 'volume-nocopy', '0077', '0700', 'no-new-privileges'):
        assert value in setup
    assert '--from=0:0' in setup
    assert 'does not follow symlinks' in setup
    register = architecture.split('## Consolidated deferred-test register', 1)[1]
    for name in ('DTR-HOST-USER', 'DTR-HOST-USER-GATEWAY'):
        row = next(line for line in register.splitlines() if line.startswith('| ' + name + ' |'))
        assert len(row.strip('|').split('|')) == 8
    assert len((ROOT / 'README.md').read_text().splitlines()) <= 200


def test_generic_run_without_arguments_keeps_default_unit_command(wrapper):
    result, record = wrapper(['run'])
    assert result.returncode == 0
    assert record['argv'][-4:] == ['python', '-m', 'pytest', 'tests/unit']
