"""CLI publication/replay of Chapter 5 views using explicitly synthetic captures."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/integration'))
from test_analysis_domains_in import sources
from test_analysis_workspace_in import invoke
from framework import analysis_workspace as workspace
from framework.chapter_tables import SECTIONS

pytestmark = pytest.mark.integration


def test_chapter_fragments_share_pinned_statistics_and_strict_replay(tmp_path):
    runs, notes = sources(tmp_path / 'sources', 'tls')
    before = {p: p.read_bytes() for run in runs for p in run.rglob('*') if p.is_file()}
    archive, _ = workspace.import_sources(runs, output=tmp_path / 'archive', annotations=notes)
    routes = {section: [] for section in SECTIONS}
    routes['kex-timing'] = [{'selection': 'tls'}]
    value = workspace.draft([archive], [dict(id='tls', kind='tls', filters={'campaign_id': 'synthetic'})],
                            presentation={'figures': [], 'chapter_tables': routes})
    spec = tmp_path / 'selection.json'; workspace.save_selection(value, spec)
    out = tmp_path / 'report'
    published = invoke('publish', '--spec', spec, '--output', out)
    assert published.returncode == 0, published.stderr
    assert len(list(out.glob('results-*.tex'))) == 20
    assert '0.15' in (out / 'results-kex-timing.tex').read_text()
    assert 'D7:' in (out / 'results-energy-secureboot-ota.tex').read_text()
    report = json.loads((out / 'report.json').read_text())
    assert len(report['chapter_tables']) == 20 and report['figures'] == []
    replay = invoke('rebuild', out, '--output', tmp_path / 'replay')
    assert replay.returncode == 0, replay.stderr
    for path in out.glob('results-*'):
        assert path.read_bytes() == (tmp_path / 'replay' / path.name).read_bytes()
    assert all(path.read_bytes() == content for path, content in before.items())
    (out / 'results-kex-timing.tex').write_text('changed')
    assert invoke('verify', out).returncode == 2
