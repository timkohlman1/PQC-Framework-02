"""Actual CLI/notebook templates and vector output; synthetic data, no hardware."""
import json
from pathlib import Path
import subprocess
import sys

from nbclient import NotebookClient
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/integration'))
from test_thesis_tables_in import fixture
from framework import analysis_workspace as workspace
from analysis_notebook_support import analysis_book

pytestmark = pytest.mark.integration


def invoke(*args):
    return subprocess.run([sys.executable, str(ROOT / 'scripts/analyse_results.py'), *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize('network', [False, True])
def test_catalogue_selection_preview_cli_and_notebook_publish_agree(tmp_path, monkeypatch, network):
    _, raw = fixture(tmp_path, network=network)
    before = raw.read_bytes()
    selection = tmp_path / 'chosen.json'
    result = invoke('catalog', '--exports-root', tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]['campaign'] == 'auth'
    result = invoke('select', '--export', tmp_path / 'archive', '--campaign', 'auth', '--recipe', 'network_loss' if network else 'tls_auth', '--output', selection)
    assert result.returncode == 0, result.stderr
    result = invoke('preview', '--spec', selection)
    assert result.returncode == 0 and 'current_attempts' in result.stdout, result.stderr
    output = tmp_path / 'cli'
    result = invoke('publish', '--spec', selection, '--output', output)
    assert result.returncode == 0, result.stderr
    book = analysis_book()
    monkeypatch.setenv('PQC_ANALYSIS_SPEC', str(selection))
    monkeypatch.setenv('PQC_ANALYSIS_PUBLISH', '1')
    monkeypatch.setenv('PQC_ANALYSIS_OUTPUT', str(tmp_path / 'notebook'))
    NotebookClient(book, timeout=180, kernel_name='python3', resources={'metadata': {'path': str(ROOT / 'notebooks')}}).execute()
    for suffix in ('csv', 'tex'):
        for path in output.glob('*.' + suffix):
            assert path.read_bytes() == (tmp_path / 'notebook' / path.name).read_bytes()
    figures = json.loads((output / 'report.json').read_text())['figures']
    assert len(figures) == (3 if network else 1)
    name = figures[0]['id']
    assert (output / (name + '.pdf')).read_bytes().startswith(b'%PDF')
    assert '<svg' in (output / (name + '.svg')).read_text()
    assert (output / (name + '.png')).read_bytes().startswith(b'\x89PNG')
    assert raw.read_bytes() == before
    assert invoke('verify', output, '--verify-sources').returncode == 0
    raw.unlink()
    assert invoke('verify', output).returncode == 0
    assert invoke('verify', output, '--verify-sources').returncode == 2
    assert invoke('publish', '--spec', selection, '--output', output).returncode == 2


def test_no_capture_attempt_is_visible_before_comparison_refusal(tmp_path):
    spec, _ = fixture(tmp_path, network=True)
    value = workspace.read_spec(spec)
    # Exercise preview's audit even when the recipe cannot attribute an attempt.
    from unittest.mock import patch
    frame, provenance = workspace.load_inputs(value)
    frame.loc[1, 'row_kind'] = 'campaign_attempt_without_capture'
    with patch.object(workspace, 'load_inputs', return_value=(frame, provenance)):
        assert workspace.selection_audit(value)[0]['no_capture_rows'] == 1
    from framework.thesis_tables import select
    with pytest.raises(ValueError, match='attempts without captures'):
        select(frame, value['selections'][0])
