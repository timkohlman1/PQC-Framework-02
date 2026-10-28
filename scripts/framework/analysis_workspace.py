"""Select queue exports, preview existing recipes and publish reproducible outputs.

Archive decoding and scientific policy belong to archive_table/thesis_tables.
This module owns discovery and selection, not another statistical implementation.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile

import pandas as pd

from framework.analysis_paths import result_path
from framework.archive_table import load_archive, export_archive
from framework import analysis_comparison as comparison
from framework.thesis_tables import (ROOT, KINDS, canonical, digest, load_inputs,
    read_spec, prepare, build, verify, eligible)
from framework.timing_dataset import _has_symlink

DEFAULT_FIGURES = {
    'secure_boot': ['integrity', 'auth'], 'secure_boot_stack': [],
    'tls_auth': ['handshake'], 'tls_kex': ['handshake'],
    'tls_auth_followup': ['handshake', 'sign', 'verify'],
    'network_loss': ['success', 'completion', 'loss_handshake'],
}


def catalogue(directory=None):
    """Bounded export discovery, with invalid archives visible as findings."""
    directories = [result_path(directory)] if directory else [ROOT/'results/queue/exports', ROOT/'results/analysis/exports']
    rows = []
    paths = sorted({p for root in directories for p in root.glob('*/archive.json')})
    for path in paths:
        base = dict(export=path.parent.name, path=str(path.parent.absolute()))
        try:
            frame = load_archive(path.parent)
            for campaign, group in frame.groupby('campaign_id', dropna=False):
                current = comparison.current_rows(group)
                retained = current[current.row_kind.ne('campaign_attempt_without_capture')]
                rows.append(dict(base, campaign=None if pd.isna(campaign) else str(campaign),
                    status='outputs_verified', rows=len(group), current_attempts=current.run_key.nunique(),
                    successful_captures=retained.loc[retained.run_success.eq(True), 'run_key'].nunique(),
                    no_capture_attempts=int(current.row_kind.eq('campaign_attempt_without_capture').sum()),
                    history_rows=int(group.get('attempt_current', pd.Series(dtype='boolean')).eq(False).sum()),
                    sources=', '.join(sorted(retained.source_commit.dropna().unique())),
                    row_kinds=', '.join(sorted(group.row_kind.dropna().unique())),
                    error=None))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            rows.append(dict(base, status='invalid', error=str(exc)))
    return rows


def export_path(value, directory=None):
    directory = Path(directory) if directory else ROOT / 'results/queue/exports'
    value = Path(value).expanduser()
    path = directory / value if not value.is_absolute() and len(value.parts) == 1 else value
    if not path.is_absolute():
        path = ROOT / path
    path = result_path(path).absolute()
    if _has_symlink(path):
        raise ValueError('symlink exports are unsupported')
    return path


def draft(exports, requests, *, directory=None, presentation=None):
    """Resolve researcher choices into the existing pinned selection contract."""
    if not exports or not requests:
        raise ValueError('choose exports and at least one recipe/campaign selection')
    paths = [export_path(value, directory) for value in exports]
    pinned = [dict(path=str(path), archive_sha256=digest(path / 'archive.json')) for path in paths]
    frame, _ = load_inputs({'exports': pinned})
    selections = []
    network_has_tls = False
    for request in requests:
        if not isinstance(request, dict) or set(request) - ({'id', 'kind', 'filters', 'stack_selection', 'baseline_selection', 'group_by', 'baseline', 'treatment'} | comparison.FIELDS):
            raise ValueError('requests contain only id, kind, filters and optional related selection IDs')
        if request.get('kind') not in KINDS or not request.get('filters'):
            raise ValueError('choose a known recipe and explicit campaign filters')
        subset = frame
        for key, value in request['filters'].items():
            if key not in frame:
                raise ValueError('unknown filter column: ' + key)
            subset = subset[subset[key].eq(value).fillna(False)]
        current = comparison.current_rows(subset) if request['kind'] in comparison.RECIPES else subset[subset.attempt_current.eq(True).fillna(False)]
        captured = current[current.row_kind.ne('campaign_attempt_without_capture')]
        if request['kind'] == 'network_loss':
            network_has_tls |= bool(captured.transport_mode.eq('tls').any())
        commits = captured.source_commit.dropna().unique()
        general = request['kind'] in comparison.RECIPES
        if not general and ({'group_by','baseline','treatment'} & set(request)):
            raise ValueError('grouping options require a domain recipe')
        if current.empty or (len(commits) != 1 and not general):
            raise ValueError('selection must contain current attempts and exactly one captured source commit: ' + request.get('id', '?'))
        item = {k:v for k,v in request.items() if k not in ('group_by', 'baseline', 'treatment')}
        if general:
            dataset = comparison.dataset_for(current)
            if not dataset.runs:
                raise ValueError('select at least one retained capture')
            if 'comparison' in item and {'group_by','baseline','treatment'} & set(request):
                raise ValueError('use either comparison or grouping convenience options')
            if 'comparison' not in item:
                item['comparison'] = comparison.comparison_for(dataset, group_by=request.get('group_by'), baseline=request.get('baseline'), treatment=request.get('treatment'))
            domains = item.get('domains', comparison.RECIPES[item['kind']])
            defaults = comparison.attributions(current, dataset)
            for key in ('network','energy'):
                if key in domains:
                    item.setdefault(key, defaults[key])
        selections.append(dict(item, source_commit=str(commits[0]) if len(commits)==1 else None, expected_current_runs=int(current.run_key.nunique())))
    options = dict(presentation or {})
    if 'figures' not in options:
        options['figures'] = sorted({m for item in selections for m in DEFAULT_FIGURES.get(item['kind'], ['*'])})
        if not network_has_tls and 'loss_handshake' in options['figures']:
            options['figures'].remove('loss_handshake')
    return read_spec(dict(version=1, exports=pinned, selections=selections, presentation=options))


def selection_audit(spec):
    """Expose excluded attempts even when a recipe refuses to produce statistics."""
    spec = read_spec(spec)
    frame, _ = load_inputs(spec)
    rows = []
    for item in spec['selections']:
        selected = frame
        for key, value in item['filters'].items():
            if key not in selected:
                raise ValueError('unknown filter column: ' + key)
            selected = selected[selected[key].eq(value).fillna(False)]
        current = comparison.current_rows(selected) if item['kind'] in comparison.RECIPES else selected[selected.attempt_current.eq(True).fillna(False)]
        current = current.drop_duplicates('run_key')
        rows.append(dict(selection=item['id'], recipe=item['kind'],
            current_attempts=int(current.run_key.nunique()),
            history_rows=int(selected.get('attempt_current', pd.Series(dtype=bool)).eq(False).sum()),
            successful_rows=int(current.run_success.eq(True).sum()),
            unsuccessful_rows=int(current.run_success.eq(False).sum()),
            eligible_rows=len(eligible(current)),
            no_capture_rows=int(current.row_kind.eq('campaign_attempt_without_capture').sum()),
            timing_excluded_rows=int(current.timing_policy_exclusion.notna().sum()),
            observation_policy='current attempt per slot or standalone capture; domain-defined observation unit' if item['kind'] in comparison.RECIPES else 'current attempt per slot; one retained capture; recipe-defined statistic'))
    return rows


def save_selection(spec, destination):
    spec = read_spec(spec)
    destination = Path(destination).absolute()
    if _has_symlink(destination):
        raise ValueError('selection must not use symlinks')
    for export in spec['exports']:
        if destination.is_relative_to(Path(export['path']).resolve()):
            raise ValueError('save selection outside source archives')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x') as stream:
        stream.write(canonical(spec))
    return destination


def publish(spec, *, name='analysis', output=None):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', name):
        raise ValueError('analysis name must contain letters, digits, underscores or hyphens')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    output = Path(output) if output else ROOT / 'results/analysis/reports' / name / stamp
    if not output.is_absolute():
        output = ROOT / output
    report = build(spec, output)
    verify(output)
    return output, report


def display_preview(prepared):
    """Display tables and figures without publishing a report or changing sources."""
    from IPython.display import display, Markdown, Image
    from framework.analysis_presentation import render
    for table in prepared['tables']:
        display(Markdown('### ' + table['caption']))
        display(pd.DataFrame(table['rows'], columns=table['headers']))
        display(Markdown(table['notes']))
    display(Markdown('Full-precision statistics and per-metric counts:'))
    display(pd.DataFrame(prepared['metrics']))
    with tempfile.TemporaryDirectory(prefix='pqc-analysis-preview-') as directory:
        figures = render(directory, prepared['tables'], prepared['metrics'], prepared['specification'].get('presentation', {}))
        for figure in figures:
            display(Image(filename=str(Path(directory) / (figure['id'] + '.png'))))
            display(Markdown(figure['caption']))


def recipes():
    descriptions = {
        'secure_boot': 'Compact boot timing and static size table; optional separate stack selection.',
        'secure_boot_stack': 'Supplementary boot stack evidence linked from secure_boot.',
        'tls_auth': 'Compact authentication matrix: medians, quartiles, eligible counts, static sizes and regional maxima.',
        'tls_kex': 'Compact key exchange matrix with the same table policy.',
        'tls_auth_followup': 'A separate matched authentication batch linked to its original selection.',
        'network_loss': 'Configured loss grid: all-current-attempt outcomes and success-conditional timing medians.',
        'timing': 'Timing checkpoints and payload throughput; descriptive observations; repeated samples are not independent.',
        'resources': 'Memory and flash: unique builds or final run lifetimes; no addition of overlapping regions.',
        'tls': 'TLS handshakes and operation attribution; repeated handshakes reduce to a median per run.',
        'network': 'Packet flow metrics and matched impairment axes; explicit endpoint/window attribution.',
        'energy': 'Recorded and aligned phase energy/power; explicit electrical boundary and evidence reference.',
        'boot_evidence': 'Detailed boot timing, mailbox validity and image/static evidence; diagnostic exclusions retained.',
        'baremetal': 'Raw primitive cycles; within-run operation medians, then across-run summaries.',
        'ota': 'Delivery, stages, images and unconfirmed transitions; no invented cross-reset duration.',
        'comparison': 'Several selected domains sharing one set of runs and comparison conditions.',
    }
    return [dict(recipe=key, purpose=value, domains=list(comparison.RECIPES.get(key, ()))) for key,value in descriptions.items()]


def describe(exports, filters, *, directory=None):
    paths = [export_path(value, directory) for value in exports]
    frame, _ = load_inputs({'exports':[dict(path=str(p), archive_sha256=digest(p/'archive.json')) for p in paths]})
    for key,value in filters.items():
        if key not in frame:
            raise ValueError('unknown filter column: ' + key)
        frame = frame[frame[key].eq(value).fillna(False)]
    current = comparison.current_rows(frame)
    if current.empty:
        raise ValueError('selection has no current attempts')
    dataset = comparison.dataset_for(current)
    from framework.timing_summary import CORE_CONTROLS, leaves, field
    fields = set(CORE_CONTROLS) | {'case_id','run_id','campaign_id'}
    for run in dataset.runs:
        fields |= leaves(run.get('controls', {}))
    controls = []
    for key in sorted(fields):
        values = sorted({json.dumps(field(run,key), sort_keys=True) for run in dataset.runs})
        controls.append(dict(field=key, distinct_values=len(values), values=[json.loads(v) for v in values[:30]], truncated=len(values)>30))
    return dict(current_attempts=int(current.run_key.nunique()), retained_runs=len(dataset.runs),
        no_capture_attempts=int(current.loc[current.row_kind.eq('campaign_attempt_without_capture'),'run_key'].nunique()),
        controls=controls, metrics=sorted({r['metric'] for r in dataset.timings}),
        runs=[{k:r.get(k) for k in ('run_key','run_id','case_id','execution_outcome','capture_acceptance','selected_input_status')} for r in dataset.runs])


def import_sources(sources, *, output=None, annotations=None):
    """Archive explicitly selected retained folders using the existing exporter."""
    paths = [Path(value).absolute() if Path(value).is_absolute() else ROOT/value for value in sources]
    if not paths or any(not p.is_dir() or _has_symlink(p) for p in paths):
        raise ValueError('choose existing non-symlink retained source directories')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    output = Path(output) if output else ROOT/'results/analysis/exports'/stamp
    if not output.is_absolute():
        output = ROOT/output
    if any(output == p or output.is_relative_to(p) or p.is_relative_to(output) for p in paths):
        raise ValueError('archive output must be outside selected retained folders')
    metadata = export_archive(results_root=paths[0], source_roots=paths, output=output, annotations=annotations)
    return output, metadata


def rebuild(report, *, output):
    """Replay the pinned selection and require identical scientific CSV/LaTeX."""
    original = verify(report, verify_sources=True)
    sources = original.get('analysis_sources')
    if not sources:
        raise ValueError('this older report has no complete analysis-source inventory; publish a new revision explicitly')
    current = {p.name:digest(p) for p in sorted((ROOT/'scripts/framework').glob('*.py'))}
    if sources != current:
        raise ValueError('analysis source changed; publish a new revision to perform a deliberate reanalysis')
    from framework.thesis_tables import analysis_environment
    if original['environment'] != analysis_environment():
        raise ValueError('analysis environment changed; publish a deliberate reanalysis')
    expected = {p.name:digest(p) for p in Path(report).iterdir() if p.suffix in ('.csv','.tex')}
    output = Path(output)
    if not output.is_absolute():
        output = ROOT/output
    rebuilt = build(original['specification'], output, expected_scientific=expected)
    verify(output)
    return output, rebuilt
