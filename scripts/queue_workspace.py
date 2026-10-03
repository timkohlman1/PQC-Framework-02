#!/usr/bin/env python3
"""Docker-side resolver and offline export operations for the host queue."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import yaml
from framework import thesis_collection as collection
from framework.campaign_executor import ExecutionPolicy, validate_policy_against_case
from framework.config_resolver import ConfigResolver, ResolutionError
from framework.run_queue import DONE, owned_path, digest, read

ROOT = Path(__file__).resolve().parents[1]


def catalogue():
    resolver = ConfigResolver(ROOT)
    values = []
    for path in sorted((ROOT / 'configs/campaigns').rglob('*')):
        if path.suffix not in {'.yaml', '.yml'} or not path.is_file():
            continue
        row = {'profile': path.relative_to(ROOT / 'configs/campaigns').as_posix()}
        try:
            if path.is_symlink():
                raise ValueError('symlink profiles are not supported')
            _, data = resolver.load_campaign(path)
            policy = ExecutionPolicy.from_mapping(data['execution'])
            cases = resolver.expand_campaign(path)
            for case in cases:
                validate_policy_against_case(policy=policy, case=case, resolver=resolver)
            row.update(id=data['id'], workload=data['workload'], repetitions=policy.repetitions,
                       conditions=len(cases), attempts=len(cases) * policy.repetitions, error=None)
        except (ValueError, RuntimeError, KeyError, OSError) as exc:
            row['error'] = str(exc)
        values.append(row)
    return {'profiles': values}


def prepare(job, profile, repetitions=None):
    folder = owned_path(ROOT, job)
    source = ROOT / 'configs/campaigns' / profile
    if not source.suffix:
        source = source.with_suffix('.yaml')
    source = Path(source.absolute())
    if not source.resolve().is_relative_to(ROOT / 'configs/campaigns') or any(p.is_symlink() for p in [source, *source.parents]):
        raise ValueError('choose a non-symlink campaign from configs/campaigns')
    resolver = ConfigResolver(ROOT)
    _, data = resolver.load_campaign(source)
    count = data['execution']['repetitions'] if repetitions is None else repetitions
    if type(count) is not int or not 1 <= count <= 1000:
        raise ValueError('repetitions must be 1..1000')
    data['execution']['repetitions'] = count
    energy = collection.instrument_campaign(resolver, data)
    if folder.exists():
        raise ValueError('queue entry directory already exists')
    (folder / 'profiles').mkdir(parents=True, mode=0o700)
    frozen = folder / 'profiles/campaign.yaml'
    frozen.write_text(yaml.safe_dump(data, sort_keys=False))
    cases = resolver.expand_campaign(frozen)
    policy = ExecutionPolicy.from_mapping(data['execution'])
    for case in cases:
        validate_policy_against_case(policy=policy, case=case, resolver=resolver)
    if not cases:
        raise ValueError('campaign has no cases')
    info = {'id': data['id'], 'profile': source.relative_to(ROOT / 'configs/campaigns').as_posix(),
            'source': frozen.relative_to(ROOT).as_posix(), 'kind': 'campaign',
            'repetitions': count, 'conditions': len(cases), 'attempts': len(cases) * count,
            'energy_requested': energy}
    plan = {'schema': 'pqc-thesis-collection', 'version': 1, 'steps': [info],
            'profile_hashes': {info['source']: digest(frozen)}, 'source': collection.source_identity(),
            'planned_campaign_attempts': info['attempts'], 'independent_runs': False,
            'limitations': collection.GAPS}
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
    prep = sub.add_parser('prepare')
    prep.add_argument('--job', required=True)
    prep.add_argument('--profile', required=True)
    prep.add_argument('--repetitions', type=int)
    check = sub.add_parser('check')
    check.add_argument('--job', required=True)
    exp = sub.add_parser('export')
    exp.add_argument('--selection', required=True)
    exp.add_argument('--output', required=True)
    args = p.parse_args(argv)
    try:
        if args.action == 'profiles':
            result = catalogue()
        elif args.action == 'prepare':
            result = prepare(args.job, args.profile, args.repetitions)
        elif args.action == 'check':
            collection.check(owned_path(ROOT, args.job))
            result = {'status': 'verified'}
        else:
            result = export_selection(args.selection, args.output)
        print(json.dumps(result))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print('queue-workspace: ' + str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
