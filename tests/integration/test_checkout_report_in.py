"""Real Git/CLI/report boundary with disposable Docker/wrapper shims, no network."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def invoke(argv, cwd, env=None):
    return subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True, timeout=60)


@pytest.fixture
def checkout_tree(tmp_path):
    root = tmp_path / 'checkout with spaces'
    (root / 'scripts').mkdir(parents=True)
    (root / 'notebooks').mkdir()
    (root / 'AI_BUILD_GUIDE.md').write_text('Fixture repository.\n')
    (root / '.gitignore').write_text('results/\n')
    (root / 'tracked.txt').write_text('initial\n')
    shutil.copyfile(ROOT / 'scripts/checkout_report.py', root / 'scripts/checkout_report.py')
    shutil.copyfile(ROOT / 'notebooks/00_checkout.ipynb', root / 'notebooks/00_checkout.ipynb')
    wrapper = root / 'scripts/dev.sh'
    wrapper.write_text('''#!/bin/sh
if [ "$1" = python ] && [ "$2" = -c ]; then
    printf '%s\\n' '{"python":"fixture-python","packages":{},"tools":{}}'
    exit 0
fi
if [ "$1" = pytest ]; then
    for arg in "$@"; do
        case "$arg" in
            --junitxml=*)
                if [ "${CHECKOUT_MODE:-}" != missing_junit ]; then
                    printf '%s\\n' '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="1"/></testsuites>' > "${arg#--junitxml=}"
                fi ;;
        esac
    done
fi
if [ "${CHECKOUT_MODE:-}" = failure ] && [ "$1" = python ]; then
    echo 'simulated policy failure' >&2
    exit 1
fi
if [ "${CHECKOUT_MODE:-}" = mutate ] && [ "$1" = pytest ]; then
    printf '\\n# changed during run\\n' >> scripts/dev.sh
fi
exit 0
''')
    wrapper.chmod(0o755)
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    docker = bindir / 'docker'
    docker.write_text('''#!/bin/sh
if [ "${CHECKOUT_MODE:-}" = unavailable ]; then
    echo 'fixture Docker unavailable' >&2
    exit 1
fi
if [ "$1" = image ]; then
    printf '"sha256:%064d"\\n' 0
else
    echo 'fixture-client fixture-server'
fi
''')
    docker.chmod(0o755)
    env = {'PATH': str(bindir) + os.pathsep + os.environ['PATH'],
           'LC_ALL': 'C.UTF-8', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
    for argv in (['git','init','-q'], ['git','add','.'],
                 ['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture']):
        result = invoke(argv, root, env)
        assert result.returncode == 0, result.stderr
    return root, env


@pytest.mark.parametrize('mode,outcome', [
    ('normal', 'passed_with_skips'), ('failure', 'failed'),
    ('unavailable', 'incomplete'), ('missing_junit', 'incomplete'), ('mutate', 'passed_with_skips'),
])
def test_cli_retains_honest_report_and_integrity(checkout_tree, mode, outcome):
    root, env = checkout_tree
    env['CHECKOUT_MODE'] = mode
    (root / 'tracked.txt').write_text('dirty\n')
    (root / 'untracked file.txt').write_text('untracked\n')
    result = invoke([sys.executable, str(root / 'scripts/checkout_report.py')], root / 'notebooks', env)
    assert result.returncode == (0 if outcome == 'passed_with_skips' else 1), result.stderr
    runs = list((root / 'results/checkout').iterdir())
    assert len(runs) == 1
    run = runs[0]
    report = json.loads((run / 'report.json').read_text())
    assert report['outcome'] == outcome
    assert report['git_before']['dirty'] is True
    assert len(report['git_before']['commit']) == 40
    assert {x['path'] for x in report['git_before']['entries']} >= {'tracked.txt','untracked file.txt'}
    assert report['checkout_changed'] is (mode == 'mutate')
    assert (run / 'report.sha256').read_text().split()[0] == hashlib.sha256((run / 'report.json').read_bytes()).hexdigest()
    for name, artifact in report['artifacts'].items():
        assert hashlib.sha256((run / name).read_bytes()).hexdigest() == artifact['sha256']
    if mode == 'unavailable':
        assert any(c['outcome'] == 'not_run' for c in report['checks'])
    if mode == 'normal':
        assert report['checks'][-1]['counts']['skipped'] == 1
    assert (root / 'tracked.txt').read_text() == 'dirty\n'


def test_detached_head_and_repeated_runs_preserve_previous_report(checkout_tree):
    root, env = checkout_tree
    assert invoke(['git', 'checkout', '--detach', '-q'], root).returncode == 0
    argv = [sys.executable, 'scripts/checkout_report.py']
    assert invoke(argv, root, env).returncode == 0
    first = next((root / 'results/checkout').iterdir()) / 'report.json'
    original = first.read_bytes()
    report = json.loads(original)
    assert report['git_before']['detached_head'] is True
    assert report['git_before']['branch'] is None
    assert report['git_before']['dirty'] is False
    assert invoke(argv, root, env).returncode == 0
    assert len(list((root / 'results/checkout').iterdir())) == 2
    assert first.read_bytes() == original


def test_all_notebook_code_cells_execute_with_display_adapter(checkout_tree, monkeypatch):
    # Exercise notebook glue with real Git and subprocesses. This adapter is not
    # a Jupyter kernel/UI acceptance test; that boundary remains documented.
    import types
    root, env = checkout_tree
    original_cwd = Path.cwd()
    monkeypatch.chdir(root / 'notebooks')
    for key in list(os.environ):
        monkeypatch.delenv(key)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    display_module = types.ModuleType('IPython.display')
    shown = []
    display_module.Markdown = str
    display_module.display = shown.append
    monkeypatch.setitem(sys.modules, 'IPython', types.ModuleType('IPython'))
    monkeypatch.setitem(sys.modules, 'IPython.display', display_module)
    notebook = json.loads((root / 'notebooks/00_checkout.ipynb').read_text())
    namespace = {}
    original_path = list(sys.path)
    try:
        for cell in notebook['cells']:
            if cell['cell_type'] == 'code':
                exec(compile(''.join(cell['source']), '<checkout-notebook>', 'exec'), namespace)
    finally:
        sys.path[:] = original_path
        os.chdir(original_cwd)
    assert len(shown) == 1 and 'passed_with_skips' in shown[0]
    assert (namespace['report_dir'] / 'report.sha256').is_file()
