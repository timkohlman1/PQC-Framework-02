#!/usr/bin/env python3
"""Docker-side resolver and offline export operations for the host queue."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import yaml
from framework import thesis_collection as collection
from framework.campaign_executor import ExecutionPolicy, validate_policy_against_case
from framework.config_resolver import ConfigResolver
from framework.run_queue import DONE, owned_path, digest, read

ROOT = Path(__file__).resolve().parents[1]


def catalogue():
    resolver = ConfigResolver(ROOT)
    values = []
    from framework.campaign_editor import PROFILE_DIRECTORY, path_for
    for path in sorted((ROOT / PROFILE_DIRECTORY).rglob('*')):
        if path.suffix not in {'.yaml', '.yml'} or not path.is_file():
            continue
        row = {'profile': path.relative_to(ROOT / PROFILE_DIRECTORY).as_posix()}
        try:
            path_for(ROOT, row['profile'])
            _, data = resolver.load_campaign(path)
            policy = ExecutionPolicy.from_mapping(data['execution'])
            cases = resolver.expand_campaign(path)
            for case in cases:
                validate_policy_against_case(policy=policy, case=case, resolver=resolver)
            row.update(id=data['id'], profile_name=data['id'], template=data.get('queue_profile', {}).get('template'),
                       workload=data['workload'], repetitions=policy.repetitions,
                       conditions=len(cases), attempts=len(cases) * policy.repetitions, error=None)
        except (ValueError, RuntimeError, KeyError, OSError, AttributeError, TypeError, yaml.YAMLError) as exc:
            row['error'] = str(exc)
        values.append(row)
    return {'profiles': values}


def prepare(job, profile=None, repetitions=None, from_job=None):
    folder = owned_path(ROOT, job)
    resolver = ConfigResolver(ROOT)
    if folder.exists():
        raise ValueError('queue entry directory already exists')
    if from_job:
        previous = owned_path(ROOT, from_job)
        # Verify every retained profile, including original input when available.
        plan = collection.check(previous, verify_source=False)
        source = previous / 'profiles/campaign.yaml'
        profile_name = plan['steps'][0]['profile']
    else:
        from framework.campaign_editor import path_for, PROFILE_DIRECTORY
        source = path_for(ROOT, profile)
        profile_name = source.relative_to(ROOT / PROFILE_DIRECTORY).as_posix()
    # Resolve the exact bytes recorded here, never re-read the mutable profile.
    original = source.read_bytes()
    (folder / 'profiles').mkdir(parents=True, mode=0o700)
    captured = folder / 'profiles/input.yaml'
    captured.write_bytes(original)
    _, data = resolver.load_campaign(captured)
    count = data['execution']['repetitions'] if repetitions is None else repetitions
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError('repetitions must be 1..1000')
    template = data.get('queue_profile', {}).get('template')
    if from_job and 'queue_profile' not in data:
        template = plan['steps'][0].get('template', 'Legacy')
    data['execution']['repetitions'] = count
    energy = collection.instrument_campaign(resolver, data)
    frozen = folder / 'profiles/campaign.yaml'
    frozen.write_text(yaml.safe_dump(data, sort_keys=False))
    cases = resolver.expand_campaign(frozen)
    policy = ExecutionPolicy.from_mapping(data['execution'])
    for case in cases:
        validate_policy_against_case(policy=policy, case=case, resolver=resolver)
    if not cases:
        raise ValueError('campaign has no cases')
    info = {'id': data['id'], 'profile': profile_name, 'profile_name': data['id'],
            'template': template,
            'source': frozen.relative_to(ROOT).as_posix(), 'kind': 'campaign',
            'repetitions': count, 'conditions': len(cases), 'attempts': len(cases) * count,
            'energy_requested': energy}
    plan = {'schema': 'pqc-thesis-collection', 'version': 1, 'steps': [info],
            'profile_hashes': {info['source']: digest(frozen), captured.relative_to(ROOT).as_posix(): digest(captured)},
            'profile_origin': {'path': source.relative_to(ROOT).as_posix(), 'sha256': digest(captured),
                               'template': data.get('queue_profile', {})},
            'source': collection.source_identity(),
            'planned_campaign_attempts': info['attempts'], 'independent_runs': False,
            'limitations': collection.GAPS}
    from framework.run_queue import source_label, commit_date
    plan['display_version'] = {'label': source_label(plan['source']),
                               'date': commit_date(str(ROOT), plan['source'].get('repository', {}).get('git_commit'))}
    if from_job:
        plan['requeued_from'] = from_job
    collection.write(folder / 'plan.json', plan)
    (folder / 'plan.sha256').write_text(digest(folder / 'plan.json') + '\n')
    collection.write(folder / 'annotations.json', collection.annotations(
        read(ROOT / 'configs/analysis/thesis_collection_annotations.json')))
    return info


def export_selection(selection, output):
    from collect_thesis_evidence import campaign_verdict
    from framework.archive_table import export_archive
    from framework.archive_notebook import write_notebook
    destination = owned_path(ROOT, output)
    request = read(owned_path(ROOT, selection))
    jobs = request['jobs']
    if not jobs or len({j['id'] for j in jobs}) != len(jobs):
        raise ValueError('select distinct completed queue entries')
    roots = []
    notes = None
    for job in jobs:
        folder = owned_path(ROOT, job['job_root'])
        selected = owned_path(ROOT, job['root'])
        if not selected.is_relative_to(folder / 'campaigns') or selected.parent != folder / 'campaigns':
            raise ValueError('selection is outside its queue entry')
        manifest = selected / 'campaign-manifest.json'
        if job['status'] not in DONE or digest(manifest) != job['manifest_sha']:
            raise ValueError('selection changed or is incomplete')
        data = read(manifest)
        _, valid, _ = campaign_verdict(manifest, 0 if data['state'] == 'completed' else 1, job['attempts'])
        if not valid or any(r.get('state') in {'failed', 'blocked'} and not r.get('accepted_failure') for r in data.get('runs', [])):
            raise ValueError('campaign is not finalized or has unresolved failures')
        current_notes = collection.annotations(read(folder / 'annotations.json'))
        if notes is not None and notes != current_notes:
            raise ValueError('selected entries have different electrical/network annotations; export compatible selections separately')
        notes = current_notes
        roots.append(selected)
    # Explicit roots avoid accidentally discovering other queued or completed runs.
    metadata = export_archive(results_root=ROOT / 'results', output=destination,
                              annotations=notes, source_roots=roots)
    collection.write(destination / 'queue-selection.json', {
        'schema': 'pqc-queue-selection', 'version': 1, 'jobs': jobs,
        'analysis_source': collection.source_identity(),
        'notebook_scope': 'Untitled general nullable-type, UTC and diagnostic normalisation',
    })
    notebook = write_notebook(destination, ROOT)
    collection.write(destination / 'export-files.json', {
        name: digest(destination / name) for name in ('runs.csv', 'archive.json', 'queue-selection.json', notebook.name)
    })
    return {'output': destination.relative_to(ROOT).as_posix(), 'rows': metadata['rows'], 'notebook': notebook.name}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    sub.add_parser('profiles')
    editor = sub.add_parser('campaign-editor')
    editor.add_argument('--request', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--job', required=True)
    origin = prep.add_mutually_exclusive_group(required=True)
    origin.add_argument('--profile')
    origin.add_argument('--from-job')
    prep.add_argument('--repetitions', type=int)
    check = sub.add_parser('check')
    check.add_argument('--job', required=True)
    exp = sub.add_parser('export')
    exp.add_argument('--selection', required=True)
    exp.add_argument('--output', required=True)
    args = p.parse_args(argv)
    try:
        if args.action == 'campaign-editor':
            from framework.campaign_editor import operate
            result = operate(ROOT, read(owned_path(ROOT, args.request)))
        elif args.action == 'profiles':
            result = catalogue()
        elif args.action == 'prepare':
            result = prepare(args.job, args.profile, args.repetitions, args.from_job)
        elif args.action == 'check':
            collection.check(owned_path(ROOT, args.job))
            result = {'status': 'verified'}
        else:
            result = export_selection(args.selection, args.output)
        print(json.dumps(result))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        print('queue-workspace: ' + str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
