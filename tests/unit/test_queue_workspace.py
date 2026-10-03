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
    profiles = tmp_path / 'results/profiles'
    profiles.mkdir(parents=True)
    shutil.copy2(tmp_path / 'configs/campaigns/baseline.yaml', profiles / 'baseline.yaml')
    return tmp_path


def test_catalogue_lists_only_local_profiles_including_invalid(repository):
    (repository / 'results/profiles/invalid.yaml').write_text('profile_type: broken\n')
    profiles = workspace.catalogue()['profiles']
    assert len(profiles) == len(list((repository / 'results/profiles').glob('*.yaml')))
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
    with pytest.raises(ValueError, match='results/profiles'):
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
    paths = ['results/profiles/example.yaml', 'results/queue/queue.sqlite3', 'results/queue/jobs/example/plan.json',
             'results/queue/exports/example/runs.csv', 'results/queue/exports/example/analysis.ipynb']
    result = subprocess.run(['git', 'check-ignore', *paths], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0 and result.stdout.splitlines() == paths


def test_requeue_keeps_original_profile_but_uses_current_source(repository, monkeypatch):
    from framework.run_queue import read
    workspace.prepare('results/q/old', 'baseline', 4)
    previous = repository / 'results/q/old'
    before = (previous / 'profiles/campaign.yaml').read_bytes()
    monkeypatch.setattr(collection, 'source_identity', lambda: {'source': 'new checkout'})
    with pytest.raises(ValueError, match='source/submodule'):
        collection.check(previous)
    (repository / 'results/profiles/baseline.yaml').unlink()
    info = workspace.prepare('results/q/new', repetitions=2, from_job='results/q/old')
    assert info['repetitions'] == 2 and info['profile'] == 'baseline.yaml'
    new = repository / 'results/q/new'
    assert collection.check(new)['source'] == {'source': 'new checkout'}
    assert read(new / 'plan.json')['requeued_from'] == 'results/q/old'
    assert (previous / 'profiles/campaign.yaml').read_bytes() == before
    (previous / 'profiles/campaign.yaml').write_text('tampered')
    with pytest.raises(ValueError, match='profile changed'):
        workspace.prepare('results/q/refused', from_job='results/q/old')


def test_catalogue_is_empty_without_local_profiles(repository):
    shutil.rmtree(repository / 'results/profiles')
    assert workspace.catalogue() == {'profiles': []}
    assert list((repository / 'configs/campaigns').glob('*.yaml'))
    with pytest.raises(FileNotFoundError):
        workspace.prepare('results/q/template-is-not-a-profile', 'baseline')


def test_profile_edits_affect_new_jobs_only_and_both_snapshots_are_verified(repository):
    import yaml
    from framework.run_queue import digest, read
    profile = repository / 'results/profiles/baseline.yaml'
    original = profile.read_bytes()
    workspace.prepare('results/q/first', 'baseline', 3)
    first = repository / 'results/q/first'
    plan = collection.check(first)
    assert (first / 'profiles/input.yaml').read_bytes() == original
    assert plan['profile_origin']['sha256'] == digest(profile)
    assert len(plan['profile_hashes']) == 2
    data = yaml.safe_load(original)
    data['execution']['repetitions'] = 5
    profile.write_text(yaml.safe_dump(data))
    assert collection.check(first)['steps'][0]['repetitions'] == 3
    workspace.prepare('results/q/second', 'baseline')
    second = collection.check(repository / 'results/q/second')
    assert second['steps'][0]['repetitions'] == 5
    assert second['profile_origin']['sha256'] != plan['profile_origin']['sha256']
    profile.unlink()
    assert collection.check(first) == plan
    (first / 'profiles/input.yaml').write_bytes(original + b'# tampered\n')
    with pytest.raises(ValueError, match='profile changed'):
        collection.check(first)
    with pytest.raises(ValueError, match='profile changed'):
        workspace.prepare('results/q/refused', from_job='results/q/first')


def test_requeue_legacy_plan_without_input_copy(repository):
    from framework.run_queue import digest, read
    workspace.prepare('results/q/old', 'baseline')
    old = repository / 'results/q/old'
    plan = read(old / 'plan.json')
    plan['profile_hashes'].pop('results/q/old/profiles/input.yaml')
    plan.pop('profile_origin')
    for key in ('template', 'profile_name'):
        plan['steps'][0].pop(key)
    (old / 'profiles/input.yaml').unlink()
    (old / 'plan.json').write_text(json.dumps(plan))
    (old / 'plan.sha256').write_text(digest(old / 'plan.json'))
    (repository / 'results/profiles/baseline.yaml').unlink()
    info = workspace.prepare('results/q/new', from_job='results/q/old')
    assert info['profile'] == 'baseline.yaml' and info['template'] == 'Legacy'
