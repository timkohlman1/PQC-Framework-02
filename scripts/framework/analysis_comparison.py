"""Bridge pinned archive selections to the maintained domain analysis engines.

This module selects observations and projects existing statistics for publication.
It does not decode evidence or recompute domain statistics.
"""
from dataclasses import replace
import hashlib
from fnmatch import fnmatchcase
import json
import math
from pathlib import Path
import re

import pandas as pd

from framework.timing_dataset_loader import TimingDataset, load_dataset
from framework.timing_summary import field, validate_spec
from framework.research_report import DOMAINS, SUMMARY_TABLES, analyse_dataset, project, dependency, verify_dependencies

RECIPES = {
    'timing': ('timing',), 'resources': ('resources',), 'tls': ('tls',),
    'network': ('network',), 'energy': ('energy',),
    'boot_evidence': ('secure_boot',), 'baremetal': ('baremetal',), 'ota': ('ota',),
    'comparison': DOMAINS,
}
FIELDS = {'comparison', 'domains', 'network', 'energy'}
PRIMARY = {
    'timing': ['tls_handshake', 'mqtt_readiness', 'ttlb', 'payload_throughput'],
    'resources': ['flash_section_bytes', 'peak_based_ram_estimate_bytes'],
    'tls': ['tls_handshake'],
    'network': ['*.wire_bytes', '*.tcp_payload_bytes', '*.packets'],
    'energy': ['whole_workload.energy_j.*', 'tls_handshake.energy_j.*', 'application_transfer.energy_j.*'],
    'secure_boot': ['image_verification', 'bootloader_flash_bytes', 'bootloader_static_ram_bytes'],
    'baremetal': ['*'], 'ota': [],
}
METHOD = ('Domain engines retain their observation units and eligibility rules. '
    'Timing medians are conditional on successful execution and usable evidence. '
    'Repeated TLS and primitive benchmarks reduce within each run before comparing runs. '
    'Resource medians distinguish unique builds from run lifetimes; regional peaks are not additive. '
    'Quartiles describe spread, not confidence. Matched differences remain unavailable when controls conflict or are unknown. '
    'Attempts without captures stay in the attempt audit and cannot supply a controlled measurement or completion denominator.')


def clean(value):
    """JSON-compatible scientific data, preserving nested provenance and nulls."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if value is None or value is pd.NA:
        return None
    if hasattr(value, 'item'):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('non-finite analysis value')
    return value


def current_rows(frame):
    if 'attempt_current' not in frame:
        return frame
    # Standalone captures have no queue attempt designation. A null designation
    # attached to a campaign manifest is not silently treated as current.
    standalone = frame.get('campaign_manifest_path', pd.Series(None, index=frame.index, dtype=object)).isna()
    return frame[frame.attempt_current.eq(True).fillna(False) | (frame.attempt_current.isna() & standalone)]


def validate(item):
    domains = item.get('domains', RECIPES[item['kind']])
    if not isinstance(domains, (list, tuple)) or not domains or set(domains) - set(DOMAINS) or len(set(domains)) != len(domains):
        raise ValueError('select distinct supported analysis domains')
    if item['kind'] != 'comparison' and tuple(domains) != RECIPES[item['kind']]:
        raise ValueError('use comparison for multiple domains')
    if not isinstance(item.get('comparison'), dict):
        raise ValueError('domain recipes require a comparison specification')
    for key in ('network', 'energy'):
        if key in item and (key not in domains or not isinstance(item[key], dict)):
            raise ValueError(key + ' attribution requires the corresponding domain')
    if {'stack_selection', 'baseline_selection'} & set(item):
        raise ValueError('linked compact selections are not domain comparison options')


def select(frame, item):
    selected = frame
    for key, value in item['filters'].items():
        if key not in frame:
            raise ValueError('unknown filter column: ' + key)
        selected = selected[selected[key].eq(value).fillna(False)]
    current = current_rows(selected)
    if current.run_key.nunique() != item['expected_current_runs']:
        raise ValueError('unexpected current capture count for ' + item['id'])
    if 'campaign_manifest_path' in current:
        queued = current[current.campaign_manifest_path.notna()]
        if len(queued) and not queued.campaign_manifest_valid.eq(True).fillna(False).all():
            raise ValueError('selected campaign attempt inventory is not finalized and verified')
    keys = set(current.run_key)
    whole = current_rows(frame)
    if set(whole.loc[whole.run_key.isin(keys), 'row_id']) != set(current.row_id):
        raise ValueError('select complete runs; filtering individual repeated observations would bias the analysis')
    captured = current[current.row_kind.ne('campaign_attempt_without_capture')]
    if captured.empty:
        raise ValueError('selection has no retained captures; inspect the attempt audit')
    if item.get('source_commit') and not captured.source_commit.eq(item['source_commit']).fillna(False).all():
        raise ValueError('captured source conflicts with selection')
    return selected.copy(), current.copy()


def dataset_for(current):
    """Use normalized observations embedded in each archive, once per run key."""
    runs, timings, issues, inputs, identities = [], [], [], [], []
    captured = current[current.row_kind.ne('campaign_attempt_without_capture')]
    seen = set()
    for directory, group in captured.groupby('_export', sort=True):
        path = Path(directory)
        dataset = load_dataset(path / 'source-dataset', verify_inputs=True)
        archive = json.loads((path / 'archive.json').read_text())
        if dataset.metadata['dataset_id'] != archive['source_dataset_id']:
            raise ValueError('archive source dataset identity changed')
        keys = set(group.run_key)
        found = {r['run_key'] for r in dataset.runs} & keys
        if found != keys or seen & found:
            raise ValueError('missing or duplicate selected run in source datasets')
        seen |= found
        for run in dataset.runs:
            if run['run_key'] not in keys:
                continue
            row = group[group.run_key.eq(run['run_key'])].iloc[0]
            run = dict(run)
            # Queue replacements must not become independent primary attempts
            # merely because the capture predates the final campaign manifest.
            if 'attempt_index' in row and pd.notna(row['attempt_index']):
                run['attempt_index'] = int(row['attempt_index'])
            runs.append(run)
        timings.extend(t for t in dataset.timings if t['run_key'] in keys)
        issues.extend(t for t in dataset.issues if t['run_key'] in keys)
        inputs.extend(source for source in dataset.metadata['inputs'] if source['run_key'] in keys)
        identities.append(dataset.metadata['dataset_id'])
    return TimingDataset(tuple(runs), tuple(timings), tuple(issues),
        {'inputs': inputs, 'dataset_id': hashlib.sha256(json.dumps(sorted(identities)).encode()).hexdigest()})


def comparison_for(dataset, *, group_by=None, baseline=None, treatment=None):
    """Explicit grouping convenience; no automatic waiver of other controls."""
    fields = ['case_id'] if group_by is None else group_by
    if not isinstance(fields, list) or any(not isinstance(k, str) for k in fields) or len(set(fields)) != len(fields):
        raise ValueError('group_by must be a list of distinct field paths')
    conditions = {}
    for run in dataset.runs:
        selector = {key: field(run, key) for key in fields}
        if any(v is None or isinstance(v, (dict, list)) for v in selector.values()):
            raise ValueError('grouping requires known scalar fields; choose different group_by fields or an explicit comparison')
        label = '; '.join(f'{k}={v}' for k, v in selector.items()) or 'selected'
        if label in conditions and conditions[label] != selector:
            raise ValueError('ambiguous condition label; supply an explicit comparison')
        conditions[label] = selector
    conditions = dict(sorted(conditions.items()))
    value = dict(conditions=conditions, baseline=baseline or next(iter(conditions)),
        treatment=treatment or [], independent_runs=False)
    validate_spec(value, dataset)
    return value


def attributions(current, dataset):
    """Reuse only explicitly recorded archive annotations, never guess a boundary."""
    from framework.thesis_collection import network_selection
    network, boundaries = {}, {}
    for directory, group in current.groupby('_export', sort=True):
        notes = json.loads((Path(directory) / 'archive.json').read_text()).get('annotations', {})
        keys = set(group.run_key)
        subset = replace(dataset, runs=tuple(r for r in dataset.runs if r['run_key'] in keys))
        network.update(network_selection(subset, notes.get('network')))
        if notes.get('energy'):
            boundaries.update({r['run_key']: notes['energy'] for r in subset.runs})
    return dict(network=network, energy={'boundaries': boundaries})


def identifier(value):
    # Metric names can carry policy/direction/operation dimensions. Preserve the
    # original in data and captions; bounded filenames retain a collision suffix.
    return re.sub('[^a-z0-9_]+', '_', value.lower()).strip('_')[:55] + '_' + hashlib.sha256(value.encode()).hexdigest()[:8]


def analyse(item, current, *, measurements=None):
    dataset = dataset_for(current)
    dependencies = {a['path']:dependency(a['path']) for source in dataset.metadata['inputs'] for a in source['artifacts'] if a.get('path')}
    domains = list(item.get('domains', RECIPES[item['kind']]))
    task = dict(id=item['id'], security_domain='selected', spec=item['comparison'], domains=domains,
        network=item.get('network', {}), energy=item.get('energy', {}))
    _, frames, normalized, provenance = analyse_dataset(dataset, task)
    for lineage in provenance.values():
        for artifact in lineage.get('inputs', []):
            path = artifact.get('path')
            if path:
                observed = dependency(path)
                if artifact.get('consumed', True) and artifact.get('sha256') != observed['sha256']:
                    raise ValueError('analysis evidence changed while reading: ' + path)
                if path in dependencies and dependencies[path] != observed:
                    raise ValueError('analysis dependency changed while reading: ' + path)
                dependencies[path] = observed
    verify_dependencies(list(dependencies.values()))
    summaries, differences, _, _ = project(task, frames)
    summaries, differences = clean(summaries), clean(differences)
    summaries = [r for r in summaries if SUMMARY_TABLES[r['table']][1] in domains]
    all_summaries = summaries
    available_measurements = sorted({r['metric'] for r in summaries})
    patterns = measurements if measurements is not None else {domain:PRIMARY[domain] for domain in domains}
    summaries = [r for r in summaries if any(fnmatchcase(r['metric'],p) for p in
        (measurements if measurements is not None else PRIMARY[SUMMARY_TABLES[r['table']][1]]))]
    # The TLS recipe supplies one equally weighted median per run; do not show
    # the observation-weighted timing variant beside it under the same title.
    if 'tls' in domains:
        summaries = [r for r in summaries if not (r['table']=='distributions' and r['metric']=='tls_handshake')]
    selected_measurements = {r['metric'] for r in summaries}
    differences = [r for r in differences if r['metric'] in selected_measurements]
    tables, metrics = [], []

    def table(name, caption, headers, rows, notes=METHOD):
        tables.append(dict(id=item['id'] + '_' + name, caption=caption,
            headers=headers, rows=rows, selections=[item['id']], notes=notes))
        return tables[-1]['id']

    def text(value):
        if value is None:
            return '—'
        return format(value, '.6g') if isinstance(value, float) else str(value)

    groups = {}
    for row in summaries:
        key = (row['table'], row['metric'], row['unit'], row['region'], row['accounting'], row['sample_unit'])
        groups.setdefault(key, []).append(row)
    for key, rows in sorted(groups.items(), key=lambda pair: str(pair[0])):
        source, metric, unit, region, accounting, sample_unit = key
        metric_id = identifier(metric + '_' + str(unit) + '_' + str(sample_unit) + '_' + json.dumps(key))
        table_id = item['id'] + '_' + metric_id
        data = []
        for r in rows:
            condition = r['condition']
            # Preserve capture/evidence strata visibly, not as duplicate points
            # under one condition. Resource summaries have their own build scope.
            label = condition
            if r['capture_class'] or r['evidence_class']:
                label += ' [' + ', '.join(v for v in (r['capture_class'], r['evidence_class']) if v) + ']'
            reason = r['reason']
            data.append([label, text(r['value']), text(r['q1']), text(r['q3']), text(r['n_runs']), text(r['n_observations']), text(reason)])
            metrics.append(dict(table=table_id, selection=item['id'], condition=label, condition_id=condition,
                metric=metric, unit=unit, scope=sample_unit, sample_unit=sample_unit,
                n=r['n_observations'], n_runs=r['n_runs'], q1=r['q1'], q3=r['q3'], median=r['value'],
                reason=reason, reported_statistic='median', reported_value=r['value'],
                source_table=source, capture_class=r['capture_class'], evidence_class=r['evidence_class'],
                region=region, accounting=accounting, estimand=r['estimand'],
                median_ci_low=r['median_ci_low'], median_ci_high=r['median_ci_high'], median_ci_reason=r['median_ci_reason']))
        table(metric_id, item['id'] + ': ' + metric + ' (' + str(unit) + ')',
            ['Condition / evidence', 'Median', 'Q1', 'Q3', 'Runs', 'Observations', 'Unavailable reason'], data,
            METHOD + f' Source: {source}. Sample unit: {sample_unit}; region: {region or "not applicable"}; accounting: {accounting or "not applicable"}.')

    # Matched effects belong beside descriptive plots. Failed comparability is
    # an explicit result, never a numeric delta disguised as an independent effect.
    relevant = {r['table'].replace('distributions', 'differences') for r in summaries} | ({'network_comparisons'} if 'network' in domains else set())
    for source in sorted({r['table'] for r in differences} & relevant):
        rows = [r for r in differences if r['table'] == source]
        table(source, item['id'] + ': matched differences (' + source + ')',
            ['Condition / metric', 'Baseline', 'Delta median', 'Unit', 'Difference (%)', 'Reason'],
            [[r['condition'] + ' / ' + r['metric'], text(r['baseline']), text(r['delta']), text(r['unit']), text(r['percent_difference']), text(r['reason'] or r['percent_reason'])] for r in rows])

    # Completion is a run outcome, not one trial for every handshake or metric.
    outcomes = clean(frames['completeness'].to_dict('records'))
    unique = {}
    for r in outcomes:
        key = (r['condition'], r['capture_class'], r['evidence_class'])
        unique.setdefault(key, r)
    table('outcomes', item['id'] + ': retained-run outcomes',
        ['Condition / evidence', 'Included', 'Completed', 'Failed', 'Unknown', 'Accepted captures', 'Completion fraction'],
        [[' / '.join(str(v) for v in key), *[text(r[k]) for k in ('included_runs', 'completed_runs', 'failed_runs', 'unknown_runs', 'capture_accepted_runs', 'completion_fraction')]] for key, r in unique.items()],
        'Completion denominator is completed + failed retained runs, conditional on the comparison selection. '
        'Unknown outcomes and attempts without captures are not promoted to known outcomes. See observations.csv for all selected attempts.')
    if 'ota' in domains:
        rows = clean(frames['ota_outcomes'].to_dict('records'))
        table('ota_outcomes', item['id'] + ': OTA evidence',
            ['Run / condition', 'Scenario', 'Delivery', 'Transition', 'Final identity limitation'],
            [[str(r['run_key']) + ' / ' + str(r['condition']), *[text(r.get(k)) for k in ('scenario', 'delivery_outcome', 'transition_outcome', 'final_identity_reason')]] for r in rows],
            'Delivery and observed activation stages do not establish the final authenticated image. No duration is inferred across resets.')

    # Include every detailed result (including availability/diagnostics and empty
    # tables) as data, using JSON for nested provenance and a documented null token.
    exported = {name: {'columns': list(frame.columns), 'rows': clean(frame.to_dict('records'))}
        for name, frame in frames.items()}
    availability = []
    for domain in domains:
        matching = [r for r in all_summaries if SUMMARY_TABLES[r['table']][1] == domain]
        available = sum(r['value'] is not None for r in matching)
        if domain == 'ota':
            available = len(frames['ota_outcomes'])
        availability.append([domain, str(available), 'available' if available else 'no eligible evidence; see detailed availability and issues'])
    table('availability', item['id'] + ': domain availability', ['Domain', 'Available summaries / OTA records', 'Status'], availability)
    return tables, metrics, dict(frames=exported, normalized_comparison=normalized,
        dependencies=sorted(dependencies.values(), key=lambda v:v['path']), domains=domains, available_measurements=available_measurements, measurement_selection=patterns, provenance=clean(provenance), method=METHOD)
