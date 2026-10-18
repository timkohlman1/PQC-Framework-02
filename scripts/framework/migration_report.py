"""Project existing domain statistics into an A/B report; never infer missing costs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from framework.migration import SIDES, LABELS, atomic_json, choice_value
from framework.run_queue import owned_path, digest, read

VERSION = '1.2.0'
# Original scientific units are retained in JSON; only presentation is scaled.
METRICS = [
    ('RAM estimate', 'resources', 'peak_based_ram_estimate_bytes', 1024, 'KiB'),
    ('Application Flash', 'resources', 'flash_section_bytes', 1024, 'KiB'),
    ('Bootloader Flash', 'secure_boot', 'bootloader_flash_bytes', 1024, 'KiB'),
    ('Packaged application image', 'secure_boot', 'packaged_image_bytes', 1024, 'KiB'),
    ('TLS handshake', 'timing', 'tls_handshake', 1000, 'ms'),
    ('MQTT readiness', 'timing', 'mqtt_readiness', 1000, 'ms'),
    ('TTFB', 'timing', 'ttfb', 1000, 'ms'),
    ('TTLB', 'timing', 'ttlb', 1000, 'ms'),
    ('RTFB', 'timing', 'rtfb', 1000, 'ms'),
    ('RTLB', 'timing', 'rtlb', 1000, 'ms'),
    ('ReqTFB', 'timing', 'req_tfb', 1000, 'ms'),
    ('ReqTLB', 'timing', 'req_tlb', 1000, 'ms'),
]
NOTES = (
    'Change is To minus From; a positive cost means an increase. Percent change uses From as the denominator. '
    'Timings are medians of eligible successful runs; failures are retained separately. '
    'The measured MQTT request/response workload delivers the response payload from gateway to device. '
    'TTFB/TTLB begin at TCP-connect start; RTFB/RTLB begin at operational wolfBoot entry; '
    'ReqTFB/ReqTLB begin at the payload request. Each ends at the first/last application payload byte. '
    'RAM is the maximum per-run estimate: retained application static storage plus heap, scratch, newlib and main-stack peaks, '
    'excluding identified experiment storage and avoiding double counting pool backing arrays. '
    'Regional peaks need not be simultaneous; this is not a validated production minimum or a prediction for another device. '
    'Application Flash excludes the bootloader. The packaged image includes the application and its image header; '
    'do not add it to application Flash. These sizes do not establish complete dual-bank/OTA slot capacity. '
    'All chosen changes are evaluated together; differences do not isolate individual causes. '
    'From is queued before To; order is not randomised and environmental drift remains a limitation. '
    'Ten attempts are a pilot default, not a precision guarantee. NA retains missingness, never zero.'
)
from framework.tls_optimizations import DEFAULTS as TLS_OPTION_DEFAULTS
TREATMENTS = {
    **{k: ['controls.tls.' + k] for k in TLS_OPTION_DEFAULTS},
    'tls_kex': ['tls_kex', 'controls.tls.mode', 'controls.tls.key_exchange_group'],
    'tls_auth': ['tls_auth', 'controls.tls.certificate_profile', 'controls.tls.server_signature_algorithm'],
    'auth_mode': ['auth_mode', 'controls.tls.mode', 'controls.tls.authentication'],
    'mldsa_memory_mode': ['controls.tls.mldsa_memory_mode'],
    'secure_boot': ['secure_boot', 'controls.choices.secure_boot'],
    'firmware_mode': ['firmware_mode', 'controls.firmware.firmware_mode',
                      'controls.firmware.dual_bank_enabled', 'controls.firmware.ota_enabled'],
    'standby_signing_keys': ['controls.choices.standby_signing_keys', 'controls.firmware.standby_signing_keys'],
    'payload_bytes': ['payload_bytes'], 'chunk_bytes': ['chunk_bytes'],
    'network_condition': ['network_condition', *['controls.network_configured.' + k
                       for k in ('enabled', 'rate_kbit', 'rtt_ms', 'loss_percent', 'mtu')]],
}


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def session_identity(session):
    return identity({k:session[k] for k in ('id', 'choices', 'profiles', 'profile_hashes', 'jobs', 'export', 'queue')})


def specification(dataset, session):
    from framework.timing_summary import leaves
    from framework.timing_dataset_schema import RUN_COLUMNS
    known = set(RUN_COLUMNS) | set().union(*(leaves(r.get('controls', {})) for r in dataset.runs))
    changed = {key for key in LABELS if choice_value(session['choices']['from'], key) != choice_value(session['choices']['to'], key)}
    treatment = set()
    for key in changed:
        treatment.update(TREATMENTS.get(key, ()))
        treatment.update(k for k in known if k.startswith('controls.profile_hashes.' + key + ':'))
    if 'mqtt_transport' in changed:
        treatment.update(('tls_kex', 'tls_auth', 'auth_mode'))
        treatment.update(k for k in known if k.startswith(('controls.tls.',
            'controls.profile_hashes.tls_kex:', 'controls.profile_hashes.tls_auth:')))
    return dict(conditions={side: {'campaign_id': Path(session['profiles'][side]).stem} for side in SIDES},
        baseline='from', treatment=sorted(treatment & known), independent_runs=False,
        evidence_policy='stm32_st67_transport')


def one(rows, **keys):
    found = [r for r in rows if all(r.get(k) == v for k,v in keys.items())]
    return found[0] if len(found) == 1 else {'reason': 'missing_or_ambiguous_evidence'}


def project(frames, session):
    """Use domain-provided matching decisions; no automatic control waivers."""
    result = []
    for title, domain, metric, scale, unit in METRICS:
        prefix = '' if domain == 'timing' else 'resource_' if domain == 'resources' else 'secure_boot_'
        rows = frames.get(prefix + 'distributions', [])
        value_key = 'summary_bytes' if metric == 'peak_based_ram_estimate_bytes' else 'median_bytes' if domain == 'resources' else 'median'
        pair = {s: one(rows, condition=s, metric=metric) for s in SIDES}
        values = {s: pair[s].get(value_key) for s in SIDES}
        reason = next((pair[s].get('reason') or 'no_eligible_measurements' for s in SIDES if values[s] is None), None)
        delta = one(frames.get(prefix + 'differences', []), condition='to', metric=metric)
        # Static boot/image sizes are not a boot-timing causal comparison. Use the
        # shared resource control guard, preserving the boot analyser's own eligibility.
        if domain == 'secure_boot':
            guard = one(frames.get('resource_differences', []), condition='to', metric='flash_section_bytes')
            reason = reason or guard.get('reason')
            change = values['to'] - values['from'] if not reason else None
        else:
            reason = reason or delta.get('reason')
            change = delta.get('delta_summary_bytes' if metric == 'peak_based_ram_estimate_bytes' else 'delta_median_bytes' if domain == 'resources' else 'delta_median')
        # Resource capacity summaries may not average distinct compiled layouts.
        if domain != 'timing' and metric not in ('freertos_heap_peak_used_bytes', 'peak_based_ram_estimate_bytes'):
            if any(pair[s].get('n_observations', 0) != 1 for s in SIDES):
                reason = reason or 'requires_one_verified_build_or_image_per_state'
                change = None
                for s in SIDES:
                    if pair[s].get('n_observations', 0) != 1:
                        values[s] = None
        if reason:
            change = None
        percent_reason = reason or ('zero_baseline' if values['from'] == 0 else None)
        percent = 100 * change / values['from'] if change is not None and not percent_reason else None
        side_reasons = {s: pair[s].get('reason') if values[s] is None else None for s in SIDES}
        if metric == 'tls_handshake':
            for s in SIDES:
                if session['choices'][s]['mqtt_transport'] == 'plaintext':
                    values[s] = None; side_reasons[s] = 'not_applicable_to_plaintext'
                    change = percent = None; reason = percent_reason = 'handshake_not_comparable_to_plaintext'
        result.append(dict(label=title, metric=metric, unit=unit, divisor=scale,
            values=values, delta=change, percent=percent, reason=reason, percent_reason=percent_reason,
            side_reasons=side_reasons, samples={s:pair[s].get('n_runs', pair[s].get('n_observations', 0)) for s in SIDES},
            quartiles={s:[pair[s].get('q1'), pair[s].get('q3')] for s in SIDES}))
    return result


def number(value, scale=1, signed=False):
    return 'NA' if value is None else format(value/scale, '+,.3f' if signed else ',.3f')


def table_rows(rows):
    return [[r['label'] + ' (' + r['unit'] + ')', *[number(r['values'][s], r['divisor']) for s in SIDES],
             number(r['delta'], r['divisor'], True), number(r['percent'], signed=True)] for r in rows]


def tex(value):
    replacements = {'\\': r'\textbackslash{}', '&':r'\&', '%':r'\%', '$':r'\$', '#':r'\#',
                    '_':r'\_', '{':r'\{', '}':r'\}', '~':r'\textasciitilde{}', '^':r'\textasciicircum{}'}
    return ''.join(replacements.get(c,c) for c in str(value))


def render(rows, session, counts):
    headers = ['Measurement', 'From', 'To', 'Change', 'Change (%)']
    body = table_rows(rows)
    widths = [max(len(str(row[i])) for row in [headers, *body]) for i in range(len(headers))]
    console = '\n'.join('  '.join(str(cell).ljust(widths[i]) for i,cell in enumerate(row)) for row in [headers, *body])
    count_note = 'Attempts: ' + '; '.join(f"{s.title()} {c['completed']} completed, {c['failed']} failed, "
        f"{c['blocked']} blocked, {c['without_capture']} without a capture / {c['planned']} planned" for s,c in counts.items()) + '.'
    sample_note = 'Eligible timing samples (From/To): ' + ', '.join(
        f"{r['label']} {r['samples']['from']}/{r['samples']['to']}" for r in rows if r['unit'] == 'ms') + '.'
    reasons = sorted({r['reason'] for r in rows if r['reason']} | {r['percent_reason'] for r in rows if r['percent_reason']})
    reason_note = 'Unavailable comparisons: ' + '; '.join(reasons) + '.' if reasons else ''
    def latex(headers, body, columns):
        return '% Requires booktabs and tabularx. Include inside a table or minipage.\n' + '\\begingroup\\small\n' + \
            '\\setlength{\\tabcolsep}{4pt}\n\\noindent\\begin{tabularx}{\\linewidth}{' + columns + '}\n\\toprule\n' + \
            ' & '.join(map(tex, headers)) + r' \\' + '\n\\midrule\n' + \
            '\n'.join(' & '.join(map(tex,row)) + r' \\' for row in body) + '\n\\bottomrule\n\\end{tabularx}\n\\endgroup\n'
    comparison = latex(headers, body, '@{}Xrrrr@{}')
    comparison += '\\par\\smallskip{\\footnotesize ' + tex(count_note + ' ' + sample_note + ' ' + NOTES + (' Unavailable reasons and eligibility details are retained in comparison.json.' if reasons else '')) + '\\par}\n'
    # Keep legacy selections reproducible when neither side recorded this field.
    selections = []
    for key, label in LABELS.items():
        if key == 'mldsa_memory_mode' and not any(key in session['choices'][s] for s in SIDES):
            continue
        values = [choice_value(session['choices'][s], key) for s in SIDES]
        selections.append([label, *[str(v if v is not None else 'Not applicable').replace('_', ' ') for v in values]])
    selections += [['Attempts (fixed)', *[str(session['choices']['repetitions'])]*2],
                   ['Workload', 'Fresh connection, MQTT wake-and-transfer', 'Fresh connection, MQTT wake-and-transfer'],
                   ['Energy measurement', 'Off', 'Off']]
    return {'comparison.txt': console + '\n\n' + '\n'.join([count_note, sample_note, NOTES, reason_note]) + '\n',
            'comparison.tex': comparison, 'selections.tex': latex(['Selection', 'From', 'To'], selections, '@{}XXX@{}')}


def verify(root, session):
    from framework.archive_table import load_archive
    folder = owned_path(root, Path('results/migrations') / session['id'] / 'report')
    metadata = read(folder / 'provenance.json')
    if metadata['session_identity'] != session_identity(session):
        raise ValueError('report session selection changed')
    archive = owned_path(root, session['export'])
    if frozen_profiles(root, session) != metadata['frozen_profiles']:
        raise ValueError('frozen comparison inputs changed')
    load_archive(archive, verify_sources=True)
    for name, sha in metadata['archive_files'].items():
        if digest(archive/name) != sha:
            raise ValueError('report archive changed: ' + name)
    for name, sha in metadata['files'].items():
        if digest(folder/name) != sha:
            raise ValueError('report output changed: ' + name)
    return {'output': folder.relative_to(root).as_posix()}


def frozen_profiles(root, session):
    """Bind displayed choices to captured job inputs, not editable local profiles."""
    import yaml
    from framework.migration import profile
    inputs = {}
    for side in SIDES:
        folder = owned_path(root, Path(session['queue']) / 'jobs' / session['jobs'][side])
        plan_path = folder / 'plan.json'
        if digest(plan_path) != (folder / 'plan.sha256').read_text().strip():
            raise ValueError('frozen queue plan changed')
        plan = read(plan_path)
        path = folder / 'profiles/input.yaml'
        if digest(path) != session['profile_hashes'][side]:
            raise ValueError('frozen profile identity differs from migration selection')
        data = yaml.safe_load(path.read_text())
        if data != profile(data, session['choices'][side], Path(session['profiles'][side]).stem,
                           session['choices']['repetitions']):
            raise ValueError('displayed migration choices differ from frozen experiment profile')
        for name, sha in plan['profile_hashes'].items():
            target = owned_path(root, name)
            if digest(target) != sha:
                raise ValueError('frozen campaign profile changed')
            inputs[name] = sha
        inputs[plan_path.relative_to(root).as_posix()] = digest(plan_path)
    return inputs


def publish(root, session):
    from framework.archive_table import load_archive
    from framework.analysis_comparison import current_rows, dataset_for, clean
    from framework.research_report import analyse_dataset
    from framework.timing_summary import digest as file_digest
    from framework.timing_dataset import verify_source_inputs
    archive = owned_path(root, session['export'])
    folder = owned_path(root, Path('results/migrations') / session['id'] / 'report')
    if folder.exists():
        return verify(root, session)
    frozen = frozen_profiles(root, session)
    for name, sha in read(archive/'export-files.json').items():
        if digest(archive/name) != sha:
            raise ValueError('export file changed: ' + name)
    selected = read(archive/'queue-selection.json')
    # Export jobs are embedded under 'jobs' by the maintained queue exporter.
    if {r['id'] for r in selected['jobs']} != set(session['jobs'].values()):
        raise ValueError('archive does not contain exactly the two comparison jobs')
    frame = load_archive(archive, verify_sources=True)
    frame['_export'] = str(archive)
    frame = current_rows(frame)
    expected = {Path(session['profiles'][s]).stem for s in SIDES}
    if set(frame.campaign_id.dropna()) != expected:
        raise ValueError('archive campaigns do not match the frozen comparison profiles')
    counts = {}
    for side in SIDES:
        group = frame[frame.campaign_id.eq(Path(session['profiles'][side]).stem)].drop_duplicates('run_key')
        if len(group) != session['choices']['repetitions']:
            raise ValueError('current attempt count differs from planned fixed count')
        counts[side] = dict(planned=len(group), completed=int(group.attempt_state.eq('completed').sum()),
            failed=int(group.attempt_state.eq('failed').sum()), blocked=int(group.attempt_state.eq('blocked').sum()),
            without_capture=int(group.row_kind.eq('campaign_attempt_without_capture').sum()))
    dataset = dataset_for(frame)
    spec = specification(dataset, session)
    if dataset.runs:
        _, frames, spec, lineage = analyse_dataset(dataset, dict(spec=spec, domains=['timing','resources','secure_boot']))
        frames = {k:clean(v.to_dict('records')) for k,v in frames.items()}
    else:
        frames, lineage = {}, {}
    rows = project(frames, session)
    outputs = render(rows, session, counts)
    parent = folder.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.report-', dir=parent))
    try:
        for name, content in outputs.items():
            (temporary/name).write_text(content)
        atomic_json(temporary/'comparison.json', clean(dict(version=VERSION, selections=session['choices'],
            rows=rows, counts=counts, specification=spec, domain_tables=frames, lineage=lineage)))
        archive_files = {name: file_digest(archive/name) for name in ('archive.json', 'runs.csv', 'queue-selection.json')}
        atomic_json(temporary/'provenance.json', dict(version=VERSION, session_identity=session_identity(session),
            archive_files=archive_files, frozen_profiles=frozen, dataset_id=dataset.metadata['dataset_id'],
            files={p.name:file_digest(p) for p in temporary.iterdir()},
            analysis_sources={name:file_digest(Path(__file__).with_name(name)) for name in
                ('migration.py','migration_report.py','timing_summary.py','resource_analysis.py','secure_boot_analysis.py')}))
        verify_source_inputs(dataset.metadata)
        temporary.rename(folder)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return verify(root, session)
