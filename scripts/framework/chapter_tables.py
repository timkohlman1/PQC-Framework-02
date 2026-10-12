"""Chapter 5 views of the shared analysis frames; no evidence parsing or statistics.

Routes explicitly name selections and optional condition labels. Empty routes are
research gaps, never invitations to pick another campaign or the latest export.
"""
from fnmatch import fnmatchcase

import pandas as pd

from framework.research_report import SECTIONS, project


TITLES = {
    'dataset-summary': 'Selected experiment evidence',
    'classical-tls-baseline': 'Classical TLS reference measurements',
    'classical-secureboot-baseline': 'Classical secure-boot reference measurements',
    'baremetal-reference': 'Bare-metal primitive reference measurements',
    'kex-timing': 'TLS key-establishment timing and memory footprint',
    'kex-resources': 'TLS key-establishment resources',
    'kex-network-application': 'Key-establishment transport and application measurements',
    'cert-family': 'Certificate-family measurements',
    'auth-mode': 'Server and mutual authentication measurements',
    'ready-metrics2': 'Application readiness and transfer measurements',
    'repeated-tls': 'Repeated TLS handshake measurements',
    'network-impairment-summary': 'Network impairment measurements',
    'packet-analysis': 'Selected TCP-flow measurements',
    'secureboot-auth': 'Secure-boot authentication measurements',
    'ota-capability': 'Persistent cost of OTA capability',
    'application-update': 'Application-update evidence',
    'bootloader-recovery': 'Bootloader migration and recovery evidence',
    'energy-tls-mqtt': 'TLS and application energy measurements',
    'energy-secureboot-ota': 'Regular-boot energy requirement',
    'cross-domain-summary': 'Matched differences for observed configurations',
}

# Explicit presentation projections. Inclusive operations are never summed.
TIMING = [('distributions', m) for m in ('rtfb', 'rtlb', 'ttfb', 'ttlb', 'req_tfb', 'req_tlb', 'mqtt_readiness')]
TLS = [('tls_run_distributions', 'tls_handshake')]
RESOURCE = [('resource_distributions', m) for m in
            ('flash_section_bytes', 'ram_static_base_bytes', 'freertos_heap_peak_used_bytes', 'simultaneous_system_peak_bytes')]
BOOT = [('secure_boot_distributions', m) for m in
        ('integrity', 'authenticity', 'image_verification', 'application_start', 'bootloader_flash_bytes',
         'bootloader_static_ram_bytes', 'boot_stack_high_water_bytes', 'image_header_reserved_bytes', 'image_signature_used_bytes')]
KEX_OPERATIONS = [('tls_operation_distributions', 'aggregate:' + metric + ':elapsed') for metric in
                  ('*keygen', '*shared_secret', '*decapsulate', 'certificate', 'certificate_verify')]
AUTH_OPERATIONS = [('tls_operation_distributions', 'aggregate:' + metric + ':elapsed') for metric in
                   ('certificate', 'certificate_verify', 'x509_verify', '*sign', '*verify')]
PACKETS = [('network_transport_distributions', '*')]
MEASUREMENTS = {
    'classical-tls-baseline': TLS + TIMING + RESOURCE,
    'classical-secureboot-baseline': BOOT,
    'baremetal-reference': [('baremetal_distributions', '*')],
    'kex-timing': TLS + [('tls_operation_distributions', 'aggregate:' + p + ':elapsed') for p in ('server_hello', 'encrypted_extensions', 'finished')] + KEX_OPERATIONS + RESOURCE,
    'kex-resources': RESOURCE,
    'kex-network-application': TIMING + PACKETS,
    'cert-family': TLS + AUTH_OPERATIONS + RESOURCE,
    'auth-mode': TLS + [('tls_operation_distributions', 'aggregate:*sign:elapsed')] + RESOURCE,
    'ready-metrics2': TIMING + [('application_distributions', 'payload_throughput')],
    'repeated-tls': TLS,
    'network-impairment-summary': [('distributions', m) for m in ('rtlb', 'ttlb')] + TLS + [('tls_operation_distributions', 'aggregate:'+m+':elapsed') for m in ('server_hello','certificate','certificate_verify','finished')],
    'packet-analysis': PACKETS,
    'secureboot-auth': BOOT,
    'ota-capability': RESOURCE + [('secure_boot_distributions', 'bootloader_flash_bytes')],
    'energy-tls-mqtt': [('energy_distributions', 'whole_workload.*'), ('energy_distributions', 'tls_handshake.*'),
                        ('energy_distributions', 'application_transfer.*')],
}

GAPS = {
    'primary_ram': 'D1: full instrumented-device RAM and separately itemised overhead are required. Existing regional peaks do not establish a simultaneous device peak or minimum usable RAM.',
    'primitive_detail': 'D2: primitive cost is reported in DWT cycles; no clock conversion or primitive-specific RAM/code-size claim is made.',
    'crypto_total': 'D3: nested measured timelines retain inclusive operation intervals. Overlapping phases and operations are not summed or treated as isolated CPU time.',
    'handshake_bytes': 'D4: selected TCP-flow totals are not handshake-only bytes; a validated handshake traffic boundary is required.',
    'recovery_delay': 'D4: TCP sequence overlap is reported explicitly, not assumed to be a causal recovery delay. Cross-clock recovery timing is unavailable.',
    'ota_capacity': 'D5: available update capacity requires a validated bank-layout and image-headroom calculation.',
    'ota_identity': 'D6: current scope is implementation footprint and basic retained lifecycle evidence; these observations do not claim production qualification.',
    'ota_time': 'D6: OTA timing and expanded recovery-transition experiments are outside the agreed current scope.',
    'boot_energy': 'D7: regular-boot energy needs a validated boot-origin acquisition boundary. OTA energy is outside the agreed scope.',
    'energy_quality': 'D8: energy spread and acquisition uncertainty are distinct; retained gap and fault diagnostics cannot be replaced by an unsupported error bar.',
    'inference': 'D9: matched effects require known compatible controls; independent runs are not inferred from hardware resets. Missing effects are not zero.',
}
SECTION_GAPS = {
    'classical-tls-baseline': ['primary_ram'], 'baremetal-reference': ['primitive_detail'],
    'kex-timing': ['crypto_total'], 'kex-resources': ['primary_ram'],
    'kex-network-application': ['handshake_bytes'], 'cert-family': ['primary_ram', 'handshake_bytes'],
    'auth-mode': ['primary_ram', 'handshake_bytes'], 'repeated-tls': ['crypto_total'],
    'packet-analysis': ['recovery_delay'], 'ota-capability': ['primary_ram', 'ota_capacity'],
    'application-update': ['ota_identity', 'ota_time'], 'bootloader-recovery': ['ota_identity', 'ota_time'],
    'energy-secureboot-ota': ['boot_energy'], 'energy-tls-mqtt': ['energy_quality', 'inference'],
    'cross-domain-summary': ['inference'],
}
METHOD = ('Values are descriptive medians unless identified as counts, fractions, percentiles or matched differences. '
          'Repeated TLS and primitive operations are reduced within each run first. '
          'Static resources use unique builds; regional peaks are not additive. '
          'Runs and observations are distinct counts; a dash means unavailable or inapplicable, never zero. '
          'Full precision, quartiles, p95, sample units, controls and evidence strata remain in the companion CSV and report. '
          'Execution completion is separate from capture acceptance and metric validity.')


def validate(routes, selections=None):
    if not isinstance(routes, dict) or set(routes) != set(SECTIONS):
        raise ValueError('chapter_tables must explicitly route all 20 Chapter 5 sections (empty lists are allowed)')
    for section, entries in routes.items():
        if not isinstance(entries, list):
            raise ValueError('chapter routes must be lists')
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {'selection', 'conditions', 'panel', 'label'} or 'selection' not in entry:
                raise ValueError('chapter route requires selection and optional exact conditions')
            name = entry['selection']
            identity = (name, entry.get('panel'))
            if not isinstance(name, str) or identity in seen:
                raise ValueError('duplicate or invalid chapter selection')
            seen.add(identity)
            if entry.get('panel') not in (None, 'rate', 'rtt', 'loss', 'mtu'):
                raise ValueError('unknown network presentation panel')
            if 'label' in entry and (not isinstance(entry['label'], str) or not entry['label'].strip()):
                raise ValueError('chapter selection label must be nonempty')
            if selections is not None and name not in selections:
                raise ValueError('unknown chapter selection: ' + name)
            conditions = entry.get('conditions')
            if conditions is not None and (not isinstance(conditions, list) or not conditions or
                    any(not isinstance(v, str) for v in conditions) or len(set(conditions)) != len(conditions)):
                raise ValueError('chapter conditions must be distinct exact labels')


def collect(prepared):
    """Project the same full-precision frames used by the default publisher."""
    from framework.analysis_comparison import clean
    routes = prepared['specification']['presentation']['chapter_tables']
    validate(routes, prepared['selected'])
    projected = {}
    for name, analysis in prepared['analyses'].items():
        frames = {key: pd.DataFrame(data['rows'], columns=data['columns']) for key, data in analysis['frames'].items()}
        projected[name] = [clean(part) for part in project({'id': name, 'security_domain': name}, frames)]
        for row in projected[name][0]:
            if row['value'] is None and not row['reason']:
                row['reason'] = 'no_eligible_measurements'
    result = {}
    for section, entries in routes.items():
        rows = []
        for entry in entries:
            name = entry['selection']
            start = len(rows)
            if name not in projected:
                raise ValueError('chapter views require domain recipes: ' + name)
            summaries, differences, inventory, outcomes = projected[name]
            known = set(prepared['analyses'][name]['normalized_comparison']['conditions'])
            allowed = set(entry.get('conditions', known))
            if allowed - known:
                raise ValueError('unknown chapter condition in ' + section)
            if section == 'dataset-summary':
                if allowed != known:
                    raise ValueError('dataset audit requires the whole selection, including attempts without captures')
                all_rows, current = prepared['selected'][name]
                all_rows, current = all_rows.drop_duplicates('run_key'), current.drop_duplicates('run_key')
                counts = dict(resolved_cases=int(current.case_id.nunique()), current_attempts=len(current),
                    historical_attempts=len(all_rows) - len(current),
                    attempts_without_capture=int(current.row_kind.eq('campaign_attempt_without_capture').sum()))
                if 'run_success' in current:
                    counts.update(completed_attempts=int(current.run_success.eq(True).sum()),
                        unsuccessful_attempts=int(current.run_success.eq(False).sum()),
                        unknown_outcomes=int(current.run_success.isna().sum()))
                if 'capture_valid' in current:
                    counts['accepted_captures'] = int(current.capture_valid.eq(True).sum())
                for metric, count in counts.items():
                    rows.append(dict(analysis=name, table='attempt_audit', condition='Complete selected campaign',
                        metric=metric, value=count, statistic='count', unit='cases' if metric=='resolved_cases' else 'attempts',
                        n_runs=None, n_observations=None, reason=None))
            candidates = [r for r in summaries if r['condition'] in allowed and any(
                r['table'] == table and fnmatchcase(r['metric'], pattern) for table, pattern in MEASUREMENTS.get(section, []))]
            if section == 'energy-tls-mqtt':
                candidates = [r for r in candidates if '.energy_j.' not in r['metric']]
                for r in prepared['analyses'][name]['frames'].get('energy_run_spread', {}).get('rows', []):
                    if r['condition'] in allowed and not r['metric'].startswith('recorded_interval.'):
                        rows.append(dict(r, analysis=name, table='energy_run_spread', value=r['mean'],
                                         statistic='mean_sd', reason=r.get('spread_reason')))
            rows.extend(dict(r, statistic='median') for r in candidates)
            if section in ('repeated-tls', 'network-impairment-summary'):
                rows.extend(dict(r, value=r.get('p95'), statistic='p95',
                    reason=None if r.get('p95') is not None else 'no_eligible_measurements') for r in candidates if section == 'repeated-tls' or r['metric'] == 'ttlb')
            if section == 'network-impairment-summary':
                rows.extend(dict(r, value=r.get('iqr'), statistic='iqr') for r in candidates if r['metric'] == 'ttlb')
                rows.extend(dict(r, value=r.get('percent_difference'), statistic='percent_difference', unit='percent',
                    metric='ttlb_change', n_runs=r.get('treatment_runs'), n_observations=None)
                    for r in differences if r['table'] == 'network_comparisons' and r['metric'] == 'ttlb' and r['condition'] in allowed)
            if section == 'cross-domain-summary':
                representative = {'tls_handshake', 'ttlb', 'image_verification', 'flash_section_bytes',
                                  'ram_static_base_bytes', 'freertos_heap_peak_used_bytes'}
                rows.extend(dict(r, value=r['delta'], statistic='delta_median', n_runs=r.get('treatment_runs'),
                    n_observations=None, reason=r.get('reason')) for r in differences if r['condition'] in allowed and
                    (r['metric'] in representative or fnmatchcase(r['metric'], 'whole_workload.energy_j.*')))
            if section in ('auth-mode', 'network-impairment-summary', 'repeated-tls', 'secureboot-auth'):
                unique = {}
                for row in outcomes:
                    if row['condition'] in allowed:
                        unique.setdefault((row['condition'], row['capture_class'], row['evidence_class']), row)
                for row in unique.values():
                    outcome_metrics = ('included_runs', 'failed_runs', 'unknown_runs', 'capture_accepted_runs') if section == 'network-impairment-summary' else ('included_runs', 'failed_runs', 'unknown_runs', 'completion_fraction', 'capture_accepted_runs')
                    for metric in outcome_metrics:
                        rows.append(dict(analysis=name, table='completeness', condition=row['condition'], metric=metric,
                            capture_class=row['capture_class'], evidence_class=row['evidence_class'],
                            value=row.get(metric), unit='fraction' if metric.endswith('fraction') else 'runs',
                            statistic='count' if metric.endswith('runs') else 'fraction', n_runs=row['included_runs'],
                            n_observations=None, reason=None, sample_unit='retained_run'))
            if section in ('application-update', 'bootloader-recovery'):
                for row in prepared['analyses'][name]['frames'].get('ota_outcomes', {}).get('rows', []):
                    if row['condition'] in allowed:
                        rows.append(dict(analysis=name, table='ota_outcomes', condition=row['condition'],
                            metric='delivery / transition', value=str(row.get('delivery_outcome')) + ' / ' + str(row.get('transition_outcome')),
                            unit='state', statistic='observed_state', n_runs=1, n_observations=1,
                            reason=row.get('final_identity_reason'), run_key=row['run_key']))
            for row in rows[start:]:
                row['panel'] = entry.get('panel')
                row['selection_label'] = entry.get('label', SELECTION_LABELS.get(name, name))
        if not rows:
            rows.append(dict(analysis=None, condition='No eligible evidence selected', metric='coverage', value=None,
                unit=None, n_runs=0, n_observations=0, reason='not_selected_or_no_eligible_measurement'))
        result[section] = dict(rows=rows, gaps=[GAPS[key] for key in SECTION_GAPS.get(section, [])])
    return result


def text(value):
    if value is None:
        return '\u2014'
    return format(value, '.6g') if isinstance(value, float) else str(value)


# Display aliases change presentation only; the CSV retains exact metric identities.
LABELS = {
    'tls_handshake': 'Handshake', 'server_hello': 'ServerHello', 'encrypted_extensions': 'Enc. extensions', 'finished': 'Finished', 'ttlb_change': 'TTLB change', 'capture_accepted_runs': 'Accepted', 'mqtt_readiness': 'MQTT ready',
    'rtfb': 'RTFB', 'rtlb': 'RTLB', 'ttfb': 'TTFB', 'ttlb': 'TTLB',
    'req_tfb': 'ReqTFB', 'req_tlb': 'ReqTLB', 'payload_throughput': 'Payload rate',
    'certificate': 'Certificate', 'certificate_verify': 'CertVerify',
    'x509_verify': 'X.509 verify', 'signature_sign': 'Signature sign', 'signature_verify': 'Signature verify',
    'ecdhe_keygen': 'ECDHE keygen', 'ecdhe_shared_secret': 'ECDHE shared secret',
    'mlkem_keygen': 'ML-KEM keygen', 'mlkem_decapsulate': 'ML-KEM decaps.',
    'mlkem_encapsulate': 'ML-KEM encaps.', 'mldsa_keygen': 'ML-DSA keygen',
    'mldsa_sign': 'ML-DSA sign', 'mldsa_verify': 'ML-DSA verify', 'sha256_hash:32_bytes': 'SHA-256 (32 B)',
    'flash_section_bytes': 'App. Flash', 'ram_static_base_bytes': 'Static RAM',
    'freertos_heap_peak_used_bytes': 'Heap peak', 'simultaneous_system_peak_bytes': 'Whole-device peak RAM',
    'integrity': 'Integrity', 'authenticity': 'Authenticate', 'image_verification': 'Image verify',
    'application_start': 'App. start', 'bootloader_flash_bytes': 'Boot Flash',
    'bootloader_static_ram_bytes': 'Boot RAM', 'boot_stack_high_water_bytes': 'Boot stack peak',
    'image_header_reserved_bytes': 'Header reserved', 'image_signature_used_bytes': 'Signature size',
    'included_runs': 'Attempts', 'failed_runs': 'Failed', 'unknown_runs': 'Unknown',
    'completion_fraction': 'Completed', 'resolved_cases': 'Conditions', 'current_attempts': 'Attempts',
    'historical_attempts': 'Earlier attempts', 'attempts_without_capture': 'No capture',
    'completed_attempts': 'Completed', 'unsuccessful_attempts': 'Unsuccessful',
    'unknown_outcomes': 'Unknown', 'accepted_captures': 'Accepted captures',
    'packets': 'Packets', 'payload_segments': 'Payload seg.', 'tcp_payload_bytes': 'TCP payload',
    'wire_bytes': 'Wire bytes', 'overlap_bytes': 'Overlap bytes', 'overlap_segments': 'Overlap seg.',
    'duration_s': 'Duration', 'fragment_packets': 'IP fragments', 'average_power_w': 'Mean power', 'energy_j': 'Energy',
}
CONDITIONS = {
    'secp256r1': 'P-256', 'secp384r1': 'P-384', 'secp521r1': 'P-521', 'x25519': 'X25519',
    'SecP256r1MLKEM768': 'P-256 + ML-KEM-768', 'SecP384r1MLKEM1024': 'P-384 + ML-KEM-1024',
    'X25519MLKEM768': 'X25519 + ML-KEM-768',
    'ML_KEM_512': 'ML-KEM-512', 'ML_KEM_768': 'ML-KEM-768', 'ML_KEM_1024': 'ML-KEM-1024',
    'ecdsa-p256': 'ECDSA P-256', 'ecdsa-p384': 'ECDSA P-384',
    'ecdsa_p256': 'ECDSA P-256', 'ecdsa_p384': 'ECDSA P-384', 'ecdsa_p521': 'ECDSA P-521',
    'rsa2048': 'RSA-2048', 'rsa3072': 'RSA-3072', 'rsa4096': 'RSA-4096',
    'mldsa44': 'ML-DSA-44', 'mldsa65': 'ML-DSA-65', 'mldsa87': 'ML-DSA-87',
    'ed25519': 'Ed25519', 'ed448': 'Ed448', 'integrity_sha256': 'Integrity only',
    'server': 'server', 'mutual': 'mutual', 'trial_reference': 'reference',
    'dual_bank_no_ota': 'OTA off', 'dual_bank_ota': 'OTA on',
}
SELECTION_LABELS = {
    'kex': 'Key establishment', 'authentication': 'Authentication', 'boot': 'Normal boot',
    'boot_stack': 'Stack profiling', 'baremetal': 'Primitive reference', 'repeated': 'Repeated TLS',
    'energy': 'Energy', 'ota': 'OTA lifecycle', 'ota_overhead': 'OTA capability',
    'app_tls_reference': 'TLS: reference payload', 'app_tls_payload_4096': 'TLS: small payload',
    'app_tls_chunk_128': 'TLS: small chunks', 'app_plain_reference': 'Plaintext: reference payload',
    'app_plain_payload_4096': 'Plaintext: small payload', 'app_plain_chunk_128': 'Plaintext: small chunks',
    'loss_tls': 'Loss: TLS', 'loss_plaintext': 'Loss: plaintext', 'rate_tls': 'Rate: TLS',
    'rate_plaintext': 'Rate: plaintext', 'rtt_tls': 'RTT: TLS', 'rtt_plaintext': 'RTT: plaintext',
    'mtu_tls': 'MTU: TLS', 'mtu_plaintext': 'MTU: plaintext',
    'authentication_followup': 'ML-DSA confirmation batch', 'loss_zero_followup': 'Zero-loss confirmation batch',
}


def display_metric(metric):
    """Align mutually exclusive primitive implementations, never sum their times."""
    import re
    if metric.startswith('aggregate:') and metric.endswith(':elapsed'):
        metric = metric[len('aggregate:'):-len(':elapsed')]
        if re.fullmatch(r'(p256|p384|p521|x25519)_(keygen|shared_secret)', metric):
            return 'ecdhe_' + metric.split('_', 1)[1]
        if re.fullmatch(r'mlkem(512|768|1024)_(keygen|decapsulate)', metric):
            return 'mlkem_' + metric.split('_', 1)[1]
        if re.fullmatch(r'(rsa|ecdsa|mldsa65)_(sign|verify)', metric):
            return 'signature_' + metric.rsplit('_', 1)[1]
    if re.fullmatch(r'mlkem_(keygen|encapsulate|decapsulate):ML_KEM_(512|768|1024)', metric):
        return metric.split(':')[0]
    if re.fullmatch(r'mldsa_(keygen|sign|verify):ML_DSA_65', metric):
        return metric.split(':')[0]
    return metric


def condition_label(condition):
    pieces = []
    for part in condition.split('; '):
        field, sep, value = part.partition('=')
        value = value if sep else field
        if value.startswith('thesis_loss_'): label = 'loss ' + value.removeprefix('thesis_loss_') + '%'
        elif value.startswith('thesis_rate_'): label = value.removeprefix('thesis_rate_') + ' kbit/s'
        elif value.startswith('thesis_rtt_'): label = 'RTT ' + value.removeprefix('thesis_rtt_') + ' ms'
        elif value.startswith('thesis_mtu_'): label = 'MTU ' + value.removeprefix('thesis_mtu_')
        elif field == 'payload_bytes' and sep: label = 'payload ' + value + ' B'
        elif field == 'chunk_bytes' and sep: label = 'chunk ' + value + ' B'
        else: label = CONDITIONS.get(value, value)
        pieces.append(label)
    return '; '.join(pieces)


def display_value(value, unit, *, compact=False):
    if value is None: return text(None)
    if not isinstance(value, (int, float)): return str(value)
    value = value / 1000 if unit in ('us', 'cycles') else value / 1024 if unit == 'bytes' else value * 100 if unit == 'fraction' else value
    if float(value).is_integer(): return format(value, ',.0f')
    places = (6 if 0 < abs(value) < .001 else 3) if not compact else (3 if abs(value) < 1 else 2 if abs(value) < 100 else 1)
    return format(value, ',.' + str(places) + 'f').rstrip('0').rstrip('.')


def sample_notes(rows):
    """Counts belong in the postscript, with build and runtime units kept distinct."""
    samples = {}
    for row in rows:
        if row.get('value') is None or row.get('statistic') in ('count', 'fraction', 'observed_state'): continue
        static = row.get('sample_unit') in ('unique_build', 'unique_build_or_image')
        count = row.get('n_observations') if static else row.get('n_runs')
        if count is not None and count > 0:
            samples.setdefault((row.get('analysis'), static), set()).add(count)
    notes = []
    for (name, static), counts in samples.items():
        count = text(min(counts)) if len(counts) == 1 else text(min(counts)) + '--' + text(max(counts))
        unit = 'distinct build/image observations' if static else 'eligible runs'
        label = next((r.get('selection_label') for r in rows if r.get('analysis') == name and r.get('selection_label')), SELECTION_LABELS.get(name, name or 'Sample'))
        notes.append(label + ': ' + count + ' ' + unit + ' per condition' +
                     (' (varies by metric; exact counts in CSV)' if len(counts) > 1 else '') + '.')
    return notes



def transpose_panel(groups, columns, selection_labels):
    """Change orientation only; keep exact values and scalar identities."""
    keys = list(groups)
    def order(key):
        import re
        return [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', key[1])]
    keys.sort(key=order)
    single = len(keys) == 1
    output_columns = [(('Value' if single else condition_label(k[1])), None, None, None, None, None, None) for k in keys]
    if len(set(output_columns)) != len(output_columns):
        raise ValueError('ambiguous transposed conditions; select one evidence stratum per column')
    result = {}
    for column in columns:
        metric, unit, statistic, *_ = column
        label = LABELS.get(metric, metric.replace('_', ' '))
        shown_unit = {'us': 'ms', 'bytes': 'KiB', 'fraction': '%', 'cycles': 'thousand cycles'}.get(unit, unit)
        if shown_unit: label += ' (' + shown_unit + ')'
        if statistic in ('p95', 'iqr'): label += ' [' + statistic + ']'
        key = (None, label, None, None, None)
        if key in result: raise ValueError('ambiguous transposed measurement')
        result[key] = {new:groups[old][column] for old, new in zip(keys, output_columns) if column in groups[old]}
    return result, output_columns

def render(section, data, *, table_id=None, caption=None):
    from collections import Counter
    from math import ceil
    from framework.thesis_tables import escape_tex
    def esc(value):
        return escape_tex(text(value)).replace(r'\_', r'\_\allowbreak{}').replace(':', r':\allowbreak{}').replace('=', r'=\allowbreak{}')
    def words(value): return str(value).replace('_', ' ')
    # Validate exact scalar identities before any display aliases are applied.
    table_id = table_id or section
    caption = caption or TITLES[section]
    transpose = section in ('classical-tls-baseline', 'classical-secureboot-baseline', 'baremetal-reference')
    wide = section in ('kex-timing', 'cert-family', 'auth-mode', 'ready-metrics2', 'network-impairment-summary')
    selection_labels = {r.get('analysis'): r.get('selection_label') or SELECTION_LABELS.get(r.get('analysis'), r.get('analysis') or 'Selection') for r in data['rows']}
    strata = {}
    for row in data['rows']:
        if row.get('capture_class') or row.get('evidence_class'):
            strata.setdefault((row.get('analysis'), row.get('condition')), set()).add((row.get('capture_class'), row.get('evidence_class')))
    seen = set()
    families = {}
    omitted = []
    outcomes = [r for r in data['rows'] if r.get('table') == 'completeness']
    show_outcomes = section in ('network-impairment-summary', 'repeated-tls') or any(
        r.get('metric') in ('failed_runs', 'unknown_runs') and r.get('value') not in (None, 0) for r in outcomes)
    for row in data['rows']:
        raw_column = tuple(row.get(k) for k in ('metric', 'unit', 'statistic', 'table', 'sample_unit', 'region', 'accounting'))
        key = tuple(row.get(k) for k in ('analysis', 'condition', 'capture_class', 'evidence_class', 'run_key'))
        if (key, raw_column) in seen: raise ValueError('ambiguous chapter scalar; preserve its observation stratum')
        seen.add((key, raw_column))
        if row.get('table') == 'completeness' and not show_outcomes: continue
        if row['metric'] == 'unknown_runs' and not any(r.get('metric') == 'unknown_runs' and r.get('value') not in (0, None) for r in outcomes): continue
        # Static build facts lack runtime evidence-class columns. Attach them only
        # where one unambiguous runtime stratum exists for this condition.
        if not key[2] and not key[3] and len(strata.get(key[:2], set())) == 1:
            capture, evidence = next(iter(strata[key[:2]]))
            key = (*key[:2], capture, evidence, key[4])
        metric = display_metric(row['metric']); table = row.get('table', '') or ''
        unit = row.get('unit'); statistic = row.get('statistic')
        if table == 'completeness': family = 'Run outcomes'
        elif table == 'attempt_audit': family = 'Dataset inventory'
        elif 'differences' in table or table == 'network_comparisons': family = words(table)
        elif metric.startswith(('client_to_server.', 'server_to_client.')):
            direction, metric = metric.split('.', 1)
            family = 'Client to server' if direction == 'client_to_server' else 'Server to client'
            if wide: metric = direction + '.' + metric
        elif table in ('energy_distributions', 'energy_run_spread'):
            phase, metric, policy = metric.split('.', 2)
            family = {'whole_workload': 'Whole workload', 'tls_handshake': 'TLS handshake', 'application_transfer': 'Application transfer'}.get(phase, words(phase)) + ' [' + policy + ']'
        elif unit == 'bytes': family = 'Memory and image size'
        elif table == 'ota_outcomes': family = 'Observed update states'
        elif table == 'baremetal_distributions': family = 'Primitive operations'
        else: family = 'Timing and application measurements'
        if wide or transpose: family = 'Measurements'
        column = (metric, unit, statistic, table, row.get('sample_unit'), row.get('region'), row.get('accounting'))
        columns, groups = families.setdefault(family, ([], {}))
        if column not in columns: columns.append(column)
        cells = groups.setdefault(key, {})
        if column in cells:
            # Only distinct, mutually exclusive implementation columns may share a display role.
            if cells[column].get('value') is not None and row.get('value') is not None:
                raise ValueError('ambiguous chapter scalar after primitive-role alignment')
            if row.get('value') is None: continue
        cells[column] = row
    panels = []
    for family, (columns, groups) in families.items():
        available = [c for c in columns if any(c in cells and cells[c].get('value') is not None for cells in groups.values())]
        if wide:
            priority = ['included_runs', 'failed_runs', 'unknown_runs', 'capture_accepted_runs', 'completion_fraction',
                        'rtfb', 'rtlb', 'ttfb', 'ttlb', 'req_tfb', 'req_tlb', 'mqtt_readiness', 'tls_handshake',
                        'server_hello', 'encrypted_extensions', 'certificate', 'certificate_verify', 'finished',
                        'ecdhe_keygen', 'ecdhe_shared_secret', 'mlkem_keygen', 'mlkem_decapsulate',
                        'flash_section_bytes', 'ram_static_base_bytes', 'freertos_heap_peak_used_bytes']
            available.sort(key=lambda c: priority.index(c[0]) if c[0] in priority else len(priority))
        missing = [c for c in columns if c not in available]
        if missing:
            omitted.append(family.split(' [')[0] + ': ' + ', '.join(LABELS.get(c[0], words(c[0])) for c in missing))
        if not available: continue
        # Balanced panels avoid a single final metric occupying an entire page width.
        limit = 30 if wide or transpose or section == 'dataset-summary' else 7 if family in ('Client to server', 'Server to client') else 5
        size = ceil(len(available) / ceil(len(available) / limit))
        for offset in range(0, len(available), size): panels.append((family, available[offset:offset+size], groups))
    if not panels and families:
        family, (columns, groups) = next(iter(families.items()))
        panels = [(family, columns[:5], groups)]
    if not panels:
        # A research gap still has its stable table anchor and explicit explanation.
        row = dict(value=None, reason='no_eligible_measurements')
        panels = [('Evidence availability', [('coverage', None, None, None, None, None, None)],
                   {(None, 'No eligible measurements', None, None, None): {('coverage', None, None, None, None, None, None): row}})]
    lines = [r'% Generated by analyse_results.py; requires booktabs, longtable and array.',
             r'\begingroup\renewcommand{\baselinestretch}{1.0}\footnotesize',
             r'\setlength{\tabcolsep}{3pt}\setlength{\LTpre}{5pt}\setlength{\LTpost}{4pt}',
             r'\setlength{\parskip}{2pt}\renewcommand{\arraystretch}{1.08}']
    if section == 'dataset-summary': lines.insert(2, r'\scriptsize')
    if wide:
        lines.insert(1, r'\begin{landscape}')
        lines.insert(3, r'\scriptsize')
    evidence_notes = {}
    for index, (family, panel, groups) in enumerate(panels):
        # Transpose single-condition baselines and the three-variant primitive reference.
        if transpose:
            groups, panel = transpose_panel(groups, panel, selection_labels)
        width = (.80 if wide else .64) / len(panel)
        spec = (r'@{}>{\raggedright\arraybackslash}p{\dimexpr.20\linewidth-2\tabcolsep\relax}' if wide else r'@{}>{\raggedright\arraybackslash}p{\dimexpr.36\linewidth-2\tabcolsep\relax}') + (
            r'>{\raggedleft\arraybackslash}p{\dimexpr' + format(width, '.5f') + r'\linewidth-2\tabcolsep\relax}') * len(panel) + '@{}'
        if index:
            lines.append(r'\begingroup\ifdefined\theHtable\renewcommand{\theHtable}{pqc-' + table_id + '-panel-' + str(index) + r'}\fi')
        lines.append(r'\begin{longtable}{' + spec + '}')
        if index == 0: lines.append(r'\caption{' + esc(caption) + r'}\label{tab:results-' + table_id + r'}\\')
        # No unnumbered caption inside subsequent longtables: it increments the table counter.
        title = family.split(' [')[0]
        if family != 'Measurements': lines.append(r'\multicolumn{' + str(len(panel)+1) + r'}{@{}l}{\textit{' + esc(title) + r'}}\\')
        headers = ['Measurement' if transpose else 'Experiment batch' if section == 'dataset-summary' else 'Condition']
        for metric, unit, statistic, source, sample, region, accounting in panel:
            heading = LABELS.get(metric, words(metric))
            if section == 'dataset-summary':
                heading = {'resolved_cases':'Cond.', 'current_attempts':'Att.', 'historical_attempts':'Earlier', 'attempts_without_capture':'No cap.',
                           'completed_attempts':'Done', 'unsuccessful_attempts':'Failed', 'unknown_outcomes':'Unk.',
                           'accepted_captures':'Acc.'}.get(metric, heading)
            if wide:
                heading = {'certificate':'Cert.', 'certificate_verify':'CV', 'encrypted_extensions':'EE',
                           'server_hello':'SH', 'finished':'Fin.', 'tls_handshake':'TLS total',
                           'ecdhe_shared_secret':'ECDHE shared'}.get(metric, heading)
            if statistic == 'delta_median': heading += ' difference'
            if statistic in ('p95', 'iqr'): heading += ' (' + ('IQR' if statistic == 'iqr' else statistic) + ')'
            if statistic == 'mean_sd': heading += ' (mean +/- SD)'
            if transpose: heading = metric
            display_unit = {'us': 'ms', 'bytes': 'KiB', 'fraction': '%', 'bytes/s': 'B/s', 'cycles': 'thousand cycles'}.get(unit, unit)
            headers.append(esc(heading) + (r'\newline (' + esc(display_unit) + ')' if display_unit not in (None, 'runs', 'cases', 'attempts', 'state', 'packets', 'segments') else ''))
        header = ' & '.join(headers) + r' \\ \midrule'
        lines += [r'\toprule ' + header, r'\endfirsthead', r'\toprule ' + header, r'\endhead',
                  r'\midrule\multicolumn{' + str(len(panel)+1) + r'}{r}{Continued on next page}\\\endfoot',
                  r'\bottomrule\endlastfoot']
        present = [(key, cells) for key, cells in groups.items() if any(c in cells for c in panel)]
        # Omit an entirely unavailable selection block, never an individual failed
        # condition within a measured selection. This keeps reliability rows visible.
        measured_selections = {key[0] for key, cells in present
                               if any(c in cells and cells[c].get('value') is not None for c in panel)}
        if measured_selections:
            missing_selections = list(dict.fromkeys(key[0] for key, _ in present if key[0] not in measured_selections))
            if missing_selections:
                omitted.append(title + ' unavailable for ' + ', '.join(SELECTION_LABELS.get(n, n or 'selection') for n in missing_selections))
                present = [(key, cells) for key, cells in present if key[0] in measured_selections]
        labels = Counter((key[0], key[1]) for key, _ in present)
        selections = {key[0] for key, _ in present}
        previous = object()
        for key, cells in present:
            name, condition, capture, ev, run_key = key
            if len(selections) > 1 and name != previous and section != 'dataset-summary' and not transpose:
                lines.append(r'\multicolumn{' + str(len(panel)+1) + r'}{@{}l}{\textit{' + esc(selection_labels.get(name, name or 'Selection')) + r'}}\\')
                previous = name
            label = selection_labels.get(name, name or condition) if section == 'dataset-summary' else condition if transpose else condition_label(condition)
            if labels[(name, condition)] > 1 and (capture or ev):
                stratum = (capture, ev)
                marker = evidence_notes.setdefault(stratum, 'E' + str(len(evidence_notes)+1))
                label += ' [' + marker + ']'
            if run_key: label += ' / ' + run_key[:8]
            cells_tex = [esc(label)]
            for column in panel:
                row = cells.get(column)
                value = esc(display_value(row.get('value'), row.get('unit') if transpose else column[1], compact=wide)) if row else esc(None)
                if row and row.get('statistic') == 'mean_sd':
                    value += r' $\pm$ ' + esc(display_value(row.get('standard_deviation'), row.get('unit')))
                if row and row.get('reason'): value += r'\textsuperscript{*}'
                cells_tex.append(value)
            lines.append(' & '.join(cells_tex) + r' \\')
        lines.append(r'\end{longtable}')
        # longtable increments the counter even without a caption.
        if index: lines.append(r'\addtocounter{table}{-1}\endgroup')
    notes = sample_notes(data['rows'])
    if section == 'dataset-summary': notes.append('Cond.: resolved conditions; Att.: current attempts; Earlier: historical attempts; No cap.: attempts without a capture; Done: completed; Unk.: unknown outcome. Acc.: accepted captures, not workload successes.')
    if transpose:
        notes.append('Selected conditions: ' + '; '.join(dict.fromkeys(condition_label(r['condition']) for r in data['rows'])) + '.')
    if outcomes and not show_outcomes:
        counts = sorted({r['value'] for r in outcomes if r['metric'] == 'included_runs' and r.get('value') is not None})
        if counts: notes.append('All retained runs completed; ' + (text(counts[0]) if len(counts)==1 else text(counts[0])+'--'+text(counts[-1])) + ' attempts per condition.')
    notes.append('Medians unless labelled otherwise. A dash denotes unavailable or inapplicable evidence; * identifies a reason in the companion CSV. Counts, full precision and evidence boundaries remain in that CSV.')
    if section == 'network-impairment-summary': notes.append('Failed attempts include workload and acquisition failures; accepted captures are a separate count. Latencies are conditional on usable successful runs. Phase intervals are inclusive and are not added.')
    if wide: notes.append('SH: ServerHello; EE: EncryptedExtensions; Cert.: Certificate; CV: CertificateVerify; Fin.: Finished. Display rounding does not change the full-precision CSV.')
    if section == 'energy-tls-mqtt': notes.append('Energy is the mean +/- sample SD of one median per eligible run; SD describes repeatability, not instrument or missing-sample uncertainty. Duration and power are medians. Invalid intervals remain excluded with reasons.')
    if any(r.get('unit') == 'cycles' for r in data['rows']): notes.append('Cycle values are shown in thousands (1 = 1,000 cycles); exact integer counts remain in the CSV.')
    if any(r.get('unit') == 'bytes' for r in data['rows']): notes.append('KiB = 1,024 bytes.')
    if any(r.get('table') == 'resource_distributions' for r in data['rows']): notes.append('Static memory and regional peaks overlap and must not be added.')
    if any(r.get('table') == 'tls_operation_distributions' for r in data['rows']): notes.append('Primitive columns align observed implementations by role; inclusive intervals are not summed.')
    if omitted: notes.append('Unavailable columns or selection blocks retained in the CSV: ' + '; '.join(omitted) + '.')
    for note in notes: lines.append(r'\noindent ' + esc(note) + r'\par')
    for key, marker in evidence_notes.items(): lines.append(r'\noindent ' + marker + ': ' + esc(', '.join(v for v in key if v)) + r'.\par')
    for gap in data['gaps']: lines.append(r'\noindent ' + esc(gap) + r'\par')
    lines.append(r'\endgroup')
    if wide: lines.append(r'\end{landscape}')
    return '\n'.join(lines) + '\n'


def publish(directory, prepared):
    """Outputs are covered by the parent publication's hashes and strict rebuild."""
    from framework.thesis_tables import write_csv, canonical
    data = collect(prepared)
    index = []
    for section, table in data.items():
        stem = 'results-' + section
        parts = []
        if section == 'network-impairment-summary' and any(r.get('panel') for r in table['rows']):
            for axis, title in [('rate', 'Rate limit'), ('rtt', 'Round-trip delay'), ('loss', 'Packet loss'), ('mtu', 'MTU')]:
                selected = [r for r in table['rows'] if r.get('panel') == axis]
                if not selected: continue
                part = 'results-network-' + axis + '.tex'
                (directory / part).write_text(render(section, dict(rows=selected, gaps=table['gaps']), table_id='network-'+axis, caption=title+' effects on completion and transfer time'))
                parts.append(part)
        (directory / (stem + '.tex')).write_text(render(section, table) if not parts else '% Separate axis tables: ' + ', '.join(parts) + '\n')
        write_csv(directory / (stem + '.csv'), table['rows'])
        index.append(dict(section=section, tex=stem + '.tex', csv=stem + '.csv',
            parts=parts, measured_rows=sum(r.get('value') is not None for r in table['rows']), gaps=table['gaps']))
    (directory / 'chapter-tables.json').write_text(canonical(index))
    return index
