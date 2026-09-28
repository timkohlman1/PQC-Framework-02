"""Checkout outcomes and provenance edge cases without Docker or hardware."""
from pathlib import Path
import json
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import checkout_report as checkout


def test_porcelain_handles_rename_spaces_newlines_and_secret_like_names():
    raw = 'R  new name\0old name\0 M line\nbreak\0?? password=filename\0'
    entries = checkout.parse_status(raw)
    assert entries == [
        {'index': 'R', 'worktree': ' ', 'path': 'new name', 'original_path': 'old name'},
        {'index': ' ', 'worktree': 'M', 'path': 'line\nbreak'},
        {'index': '?', 'worktree': '?', 'path': 'password=filename'},
    ]


@pytest.mark.parametrize('states,expected', [
    ([], 'incomplete'), (['passed'], 'passed'),
    (['passed', 'passed_with_skips'], 'passed_with_skips'),
    (['not_run', 'passed'], 'incomplete'), (['interrupted'], 'incomplete'),
    (['failed', 'not_run'], 'failed'),
])
def test_outcome_never_promotes_missing_evidence(states, expected):
    assert checkout.overall([{'outcome': value} for value in states]) == expected


def test_junit_retains_skips_errors_and_failures(tmp_path):
    xml = tmp_path / 'tests.xml'
    xml.write_text('<testsuites><testsuite tests="7" failures="1" errors="1" skipped="2"/></testsuites>')
    assert checkout.junit_counts(xml) == {'tests': 7, 'failures': 1, 'errors': 1, 'skipped': 2, 'passed': 3}
    xml.write_text('<testsuites/>')
    with pytest.raises(ValueError):
        checkout.junit_counts(xml)


def test_missing_binary_and_timeout_are_unavailable(tmp_path, monkeypatch):
    result = checkout.command(['/definitely/missing/checkout-command'], tmp_path)
    assert result['outcome'] == 'unavailable' and result['exit_code'] is None
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)
    monkeypatch.setattr(checkout.subprocess, 'run', timeout)
    assert checkout.command(['probe'], tmp_path)['outcome'] == 'unavailable'


def test_redaction_and_markdown_escaping():
    assert 'supersecret' not in checkout.redact('PQC_WIFI_PSK=supersecret\n')
    assert 'supersecret' not in checkout.redact("{'PQC_WIFI_PSK': 'supersecret'}")
    assert 'private-data' not in checkout.redact('-----BEGIN RSA PRIVATE KEY-----\nprivate-data\n-----END RSA PRIVATE KEY-----')
    assert checkout.cell('a|<b>\n`code`') == '"a\\|&lt;b&gt;\\n&#96;code&#96;"'


def test_fixed_plan_does_not_select_gateway_or_general_integration():
    plan = checkout.planned_checks('results/checkout/example')
    commands = [argv for _, argv, _ in plan]
    assert ['./scripts/dev.sh', 'python', 'scripts/check_dependency_pins.py'] in commands
    pytest_commands = [argv for argv in commands if argv[:2] == ['./scripts/dev.sh', 'pytest']]
    assert [argv[2] for argv in pytest_commands] == ['tests/unit', 'tests/integration/test_checkout_report_in.py']


def test_notebook_structure_and_code_compile():
    notebook = json.loads((ROOT / 'notebooks/00_checkout.ipynb').read_text())
    assert notebook['nbformat'] == 4
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            assert isinstance(cell['outputs'], list)
            compile(''.join(cell['source']), '<checkout-notebook>', 'exec')
    assert 'run_checkout' in (ROOT / 'scripts/checkout_report.py').read_text()


def test_checkout_docs_and_ignored_outputs():
    assert 'notebooks/00_checkout.ipynb' in (ROOT / 'README.md').read_text()
    architecture = (ROOT / 'docs/007_framework_architecture.md').read_text()
    for value in ('results/checkout/', 'report.sha256', 'test_checkout_report_in.py'):
        assert value in architecture
    result = subprocess.run(['git', '-c', f'safe.directory={ROOT}', 'check-ignore', '--no-index', 'results/checkout/example/report.json',
                             'notebooks/.ipynb_checkpoints/00_checkout-checkpoint.ipynb'],
                            cwd=ROOT, text=True, capture_output=True, check=True)
    assert len(result.stdout.splitlines()) == 2


def test_interruption_is_not_a_pass(tmp_path, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(checkout.subprocess, 'run', interrupt)
    result = checkout.command(['probe'], tmp_path)
    assert result['outcome'] == 'interrupted'
    assert result['exit_code'] is None
