"""Frozen campaign planning and exporter selection validation."""
import json
from pathlib import Path
import shutil

import pytest
import queue_workspace as workspace
from framework import thesis_collection as collection

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repository(tmp_path, monkeypatch):
    shutil.copytree(ROOT / 'configs', tmp_path / 'configs')
    monkeypatch.setattr(workspace, 'ROOT', tmp_path)
    monkeypatch.setattr(collection, 'ROOT', tmp_path)
    monkeypatch.setattr(collection, 'source_identity', lambda: {'source': 'fixture'})
    return tmp_path


def test_catalogue_lists_every_campaign_including_invalid(repository):
    (repository / 'configs/campaigns/invalid.yaml').write_text('profile_type: broken\n')
    profiles = workspace.catalogue()['profiles']
    assert len(profiles) == len(list((repository / 'configs/campaigns').glob('*.yaml')))
    assert next(p for p in profiles if p['profile'] == 'invalid.yaml')['error']
    baseline = next(p for p in profiles if p['profile'] == 'baseline.yaml')
    assert baseline['repetitions'] == baseline['conditions'] == baseline['attempts'] == 1


def test_prepare_default_override_energy_and_source_guard(repository, monkeypatch):
    first = workspace.prepare('results/queue/jobs/first', 'baseline')
    second = workspace.prepare('results/queue/jobs/second', 'baseline.yaml', 4)
    assert first['repetitions'] == 1 and second['attempts'] == 4
    assert second['energy_requested']
    job = repository / 'results/queue/jobs/second'
    assert collection.check(job)['steps'][0] == second
    assert not (job / 'campaigns').exists()
    monkeypatch.setattr(collection, 'source_identity', lambda: {'source': 'changed'})
    with pytest.raises(ValueError, match='source/submodule'):
        collection.check(job)


def test_prepare_refuses_escape_and_mutated_profile(repository):
    with pytest.raises(ValueError, match='configs/campaigns'):
        workspace.prepare('results/q', '../workloads/ready_metrics.yaml')
    workspace.prepare('results/q', 'baseline')
    path = repository / 'results/q/profiles/campaign.yaml'
    path.write_text(path.read_text() + '\n# change\n')
    with pytest.raises(ValueError, match='profile changed'):
        collection.check(repository / 'results/q')


def test_queue_documentation_and_generated_output_ignore_contract():
    import subprocess
    readme = (ROOT / 'README.md').read_text()
    guide = (ROOT / 'docs/005_remote_flash_workflow.md').read_text()
    architecture = (ROOT / 'docs/007_framework_architecture.md').read_text()
    assert 'python3 scripts/run_queue.py' in readme
    for control in ('cooperative pause', 'accept', 'analysis.ipynb', 'raw_df', 'does not terminate'):
        assert control in guide
    assert 'DTR-RUN-QUEUE' in architecture
    paths = ['results/queue/queue.sqlite3', 'results/queue/jobs/example/plan.json',
             'results/queue/exports/example/runs.csv', 'results/queue/exports/example/analysis.ipynb']
    result = subprocess.run(['git', 'check-ignore', *paths], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0 and result.stdout.splitlines() == paths
