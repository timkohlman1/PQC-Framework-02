"""A7 read-only normal-boot analysis; no flashing, signing or OTA execution."""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path
from statistics import median

import numpy as np

from framework.analysis_paths import result_path
from framework.resource_analysis import _read, _build_root, _row
from framework.timing_dataset import read_json, _verify_header, verify_source_inputs, DatasetError
from framework.timing_metrics import decode_epochs, uint
from framework.run_evidence import sha256_file

VERSION = '1.0.0'
BOUNDARIES = {
    'integrity': 'integrity_sha256_call',
    'authenticity': 'signature_authenticity_call',
    'image_verification': 'selected_image_integrity_start_to_authenticity_end',
    'boot': 'hal_init_entry_to_hal_prepare_boot',
    'application_start': 'reset_to_application_startup',
}
RESOURCE_DEFINITIONS = {
    'bootloader_flash_bytes': ('FLASH', 'allocated_file_backed_sections'),
    'bootloader_static_ram_bytes': ('RAM', 'data_plus_bss_excludes_stack_and_other_reservations'),
    'bootloader_elf_file_bytes': ('file', 'ELF_container_not_flash_use'),
    'packaged_image_bytes': ('FLASH', 'retained_packaged_image_size'),
    'image_payload_bytes': ('FLASH', 'recorded_header_firmware_length'),
    'image_header_reserved_bytes': ('FLASH', 'header_capacity_including_padding'),
    'image_metadata_used_bytes': ('FLASH', 'fixed_prefix_plus_TLV_headers_and_values'),
    'image_signature_used_bytes': ('FLASH', 'signature_TLV_value_subset_of_header'),
    'boot_stack_high_water_bytes': ('RAM/boot_stack', 'selected_image_verification_watermark'),
}


def image_layout(data):
    """Use the framework's actual WOLF length/TLV model, not profile constants."""
    from framework.secure_boot_flash import _signed_wolfboot_image_layout
    header, payload = _signed_wolfboot_image_layout(bytearray(data), Path('retained.bin'))
    offset, used, signatures, tags = 8, 8, [], set()
    while offset + 4 <= header:
        if data[offset] == 255 or offset & 1:
            offset += 1
            continue
        tag, length = struct.unpack_from('<HH', data, offset)
        if tag == 0:
            break
        if tag in tags or length == 0 or offset + 4 + length > header:
            raise ValueError('invalid_or_duplicate_image_TLV')
        tags.add(tag)
        used += 4 + length
        if tag == 0x20:
            signatures.append(length)
        offset += 4 + length
    return dict(packaged_image_bytes=len(data), image_payload_bytes=payload,
                image_header_reserved_bytes=header, image_metadata_used_bytes=used,
                image_signature_used_bytes=sum(signatures) if signatures else None)


def decode_boot(records, *, invalid=None):
    """One mailbox observation per epoch, never multiplied by TLS iterations."""
    records = [r for r in records if r['context'] == 'secure_boot']
    def select(marker, **fields):
        found = [r for r in records if r['marker'] == marker and all(r['fields'].get(k) == v for k,v in fields.items())]
        if len(found) != 1:
            raise ValueError('missing_or_duplicate:' + marker)
        r = found[0]; f = r['fields']
        if f.get('schema') != '1' or (marker != 'PQC_SECURE_BOOT_STACK' and f.get('mailbox_version') != '8'):
            raise ValueError('unsupported_mailbox_or_schema')
        return f, r['ref']
    issue = invalid
    profile = {}
    try:
        profile, _ = select('PQC_SECURE_BOOT_PROFILE')
        if profile.get('signature_algorithm') in (None, 'unknown'):
            raise ValueError('unknown_signature_algorithm')
        if any(r['marker'] == 'PQC_SECURE_BOOT' and r['fields'].get('mailbox_status') == 'unavailable' for r in records):
            raise ValueError('mailbox_unavailable')
    except ValueError as exc:
        issue = issue or str(exc)
    algorithm = profile.get('signature_algorithm')
    rows = []
    for metric, boundary in BOUNDARIES.items():
        row = dict(metric=metric, boundary=boundary, cycles=None, hclk_hz=None, elapsed_ms=None,
                   validity='unavailable', reason=issue, result_code=None, source_records=[], clock_domain=None)
        try:
            if issue:
                raise ValueError(issue)
            if metric == 'application_start':
                raise ValueError('application_start_not_recorded')
            if metric in ('integrity', 'authenticity'):
                kind = 'integrity_sha256' if metric == 'integrity' else 'signature_authenticity'
                f, ref = select('PQC_SECURE_BOOT', verification_type=kind)
                row['source_records'] = [ref]
                if f.get('mailbox_status') != 'present' or f.get('signature_algorithm') != algorithm:
                    raise ValueError('mailbox_profile_mismatch')
                if metric == 'authenticity' and algorithm == 'integrity_sha256' and f.get('measurement_status') == 'not_applicable':
                    row.update(validity='not_applicable', reason='integrity_reference_has_no_signature')
                    rows.append(row)
                    continue
                if not re.fullmatch(r'-?[0-9]+', f.get('result', '')):
                    raise ValueError('invalid_verification_result')
                row['result_code'] = int(f['result'])
            elif metric == 'image_verification':
                f, ref = select('PQC_SECURE_BOOT_VERIFICATION')
                row['source_records'] = [ref]
                if f.get('boundary') != boundary or f.get('selected_image_valid') != '1':
                    raise ValueError('invalid_selected_image_boundary')
            else:
                f, ref = select('PQC_SECURE_BOOT_TOTAL')
                bridge, bref = select('PQC_SECURE_BOOT_HANDOFF')
                row['source_records'] = [ref, bref]
                def wide(obj, prefix):
                    hi, lo = uint(obj.get(prefix+'_high')), uint(obj.get(prefix+'_low'))
                    if max(hi, lo) > 0xffffffff:
                        raise ValueError('invalid_split_timestamp')
                    return (hi << 32) | lo
                elapsed = wide(f, 'elapsed_us')
                if (f.get('boundary') != boundary or f.get('clock_domain') != 'reset_origin_lptim2_dwt_bridge'
                        or f.get('measurement_valid') != '1' or bridge.get('bridge_status') != '1'
                        or bridge.get('origin_kind') != '1' or bridge.get('bridge_counter_hz') != '1000000'
                        or bridge.get('bridge_counter_bits') != '16' or elapsed == 0
                        or elapsed != wide(bridge, 'reset_origin_to_handoff_us')):
                    raise ValueError('invalid_boot_bridge')
                row.update(elapsed_ms=elapsed/1000, clock_domain='reset_origin_lptim2_dwt_bridge', validity='valid')
                rows.append(row)
                continue
            cycles, hz = uint(f.get('cycles')), uint(f.get('hclk_hz'))
            row.update(cycles=cycles, hclk_hz=hz, clock_domain='bootloader_DWT_HCLK')
            if f.get('measurement_valid') != '1' or not 0 < cycles <= 0xffffffff or not 0 < hz <= 0xffffffff:
                raise ValueError('invalid_measurement_or_bootloader_clock')
            row.update(elapsed_ms=1000*cycles/hz, validity='valid')
        except ValueError as exc:
            row['reason'] = str(exc)
        rows.append(row)
    clocks = {r['hclk_hz'] for r in rows if r['validity']=='valid' and r['hclk_hz'] is not None}
    if len(clocks) > 1:
        for row in rows:
            if row['clock_domain']=='bootloader_DWT_HCLK':
                row.update(validity='unavailable', elapsed_ms=None, reason='inconsistent_mailbox_hclk')
    identity = dict(algorithm=algorithm, image_content_sha256=None, image_payload_bytes=None,
                    image_part=None, handoff='unconfirmed', reason=issue,
                    bootloader_hclk_hz=next((r['hclk_hz'] for r in rows if r['metric']=='integrity' and r['validity']=='valid'), None))
    try:
        if issue:
            raise ValueError(issue)
        f, ref = select('PQC_SECURE_BOOT_IMAGE')
        vf, _ = select('PQC_SECURE_BOOT_VERIFICATION')
        if (f.get('identity_kind') != 'wolfboot_verified_image_content_sha256'
                or not re.fullmatch('[0-9a-f]{64}', f.get('image_sha256', ''))
                or vf.get('selected_image_valid') != '1'
                or f.get('image_part') != vf.get('selected_image_part')
                or f.get('image_fw_size_bytes') != vf.get('selected_image_fw_size_bytes')
                or uint(f.get('image_fw_size_bytes')) == 0):
            raise ValueError('unconfirmed_image_identity')
        identity.update(image_content_sha256=f['image_sha256'], image_part=uint(f['image_part']),
                        image_payload_bytes=uint(f['image_fw_size_bytes']), source_records=[ref])
        by = {r['metric']: r for r in rows}
        verified = by['integrity']['validity'] == 'valid' and by['integrity']['result_code'] == 0
        verified &= (by['authenticity']['validity'] == 'not_applicable' if algorithm == 'integrity_sha256'
                     else by['authenticity']['validity'] == 'valid' and by['authenticity']['result_code'] == 0)
        if verified and by['boot']['validity'] == 'valid':
            identity['handoff'] = 'observed_application_report_after_handoff'
    except ValueError as exc:
        identity['reason'] = str(exc)
    return rows, identity


def _retained(root, manifest, role, inputs):
    found = [a for a in manifest['artifacts'] if a.get('role') == role and a.get('acquisition', {}).get('status') == 'available']
    if len(found) != 1:
        raise ValueError('retained_artifact_missing_or_ambiguous:' + role)
    a = found[0]
    if not a.get('path'):
        matches = [f for f in manifest.get('retained_files', [])
            if f.get('sha256') == a.get('sha256') and f.get('path')
            and Path(f['path']).suffix in ({'.elf'} if role == 'wolfboot_image' else {'.bin'})
            and not any(part in Path(f['path']).parts for part in ('cryptographic-material', 'keys'))]
        # Multiple retained copies of the exact same bytes are not ambiguous.
        if matches:
            a = {**a, **sorted(matches, key=lambda f: f['path'])[0]}
    p = Path(a.get('path') or '')
    if p.is_absolute() or '..' in p.parts or not p.parts or any(x in p.parts for x in ('cryptographic-material', 'keys')):
        raise ValueError('unsafe_artifact_path')
    suffixes = {'wolfboot_image': {'.elf', '.bin'}, 'signed_application': {'.bin'}}
    if p.suffix not in suffixes[role] or not re.fullmatch('[0-9a-f]{64}', a.get('sha256') or '') or type(a.get('size_bytes')) is not int:
        raise ValueError('invalid_artifact_identity')
    return _read(root/p, inputs, a['sha256'], a['size_bytes']), root/p


def extract_secure_boot(dataset):
    verify_source_inputs(dataset.metadata)
    inputs, observations, outcomes, resources = [], [], [], []
    for run in dataset.runs:
        root = result_path(run['input_path']); key = run['run_key']
        negative = run.get('capture_class') == 'secure_boot_negative_validation'
        base = dict(run_key=key, run_id=run['run_id'], profile=run.get('secure_boot'),
                    capture_class=run.get('capture_class'), case_kind='rejection_validation' if negative else 'normal_boot',
                    packaged_image_sha256=run.get('firmware_sha256'), build_references=run['build_references'])
        epochs, error = [], None
        try:
            if run['selected_input_status'] != 'verified':
                raise ValueError('selected_stream_unavailable_or_invalid')
            epochs, errors = decode_epochs(root/'mqtt-reporting-raw.ndjson', run['run_id'])
            if errors:
                raise ValueError('invalid_reporting_stream')
        except (OSError, ValueError, UnicodeError) as exc:
            error = str(exc)
        decoded = []
        for ep in epochs:
            rows, identity = decode_boot(ep.records, invalid='invalid_reporting_epoch' if ep.errors else error)
            algorithm = {'ecc384':'ecdsa_p384', 'ecc521':'ecdsa_p521'}.get(identity['algorithm'], identity['algorithm'])
            if algorithm and algorithm != run.get('secure_boot'):
                rows, identity = decode_boot(ep.records, invalid='configured_observed_profile_mismatch')
            decoded.append((rows, identity, ep.index, ep.logical_sha256))
        if not decoded:
            rows, identity = decode_boot([], invalid=error or 'boot_evidence_not_recorded')
            decoded = [(rows, identity, None, None)]
        for rows, identity, epoch, logical_hash in decoded:
            for row in rows:
                row.update(base, epoch_index=epoch, logical_sha256=logical_hash,
                           scope='boot_lifetime', timing_comparable=not negative and len(decoded)==1
                           and run.get('boot_stack_profiling') is False and run.get('boot_uart_diagnostics') is False)
                observations.append(row)
            outcome = ('unexpected_handoff' if negative else 'normal_handoff') if identity['handoff'] != 'unconfirmed' else 'unknown'
            if negative and outcome == 'unknown' and run.get('execution_result') == 'secure_boot_negative_test_passed':
                outcome = 'expected_rejection_validation_passed'
            outcomes.append(dict(base, **identity, epoch_index=epoch, observed_outcome=outcome,
                validation_result=run.get('execution_result'), normal_boot_success=outcome == 'normal_handoff',
                missing_workload_interpretation='expected_absence_in_negative_capture' if negative else 'not_boot_outcome_evidence'))
        values, reasons, build_id, image_id = {}, {}, None, None
        try:
            build_root = _build_root(run)
            # Direct-flash runs retain signing and boot artifacts alongside their
            # capture; their build reference is the application ELF-only record.
            own = read_json(_read(root/'manifest.json', inputs, run['manifest_sha256']))
            if any(a.get('role') == 'wolfboot_image' and a.get('sha256') for a in own.get('artifacts', [])):
                build_root = root if any(a.get('role') == 'run_provenance' for a in own['artifacts']) and not run.get('preparation_run_id') else build_root
            bm = read_json(_read(build_root/'manifest.json', inputs,
                                run['manifest_sha256'] if build_root == root else None))
            _verify_header(bm)
            for role in ('wolfboot_image', 'signed_application'):
                try:
                    data, path = _retained(build_root, bm, role, inputs)
                    digest = hashlib.sha256(data).hexdigest()
                    if role == 'wolfboot_image':
                        from framework.manifest import read_elf_alloc_section_metrics
                        build_id = digest
                        metrics = read_elf_alloc_section_metrics(path)
                        values.update({k:metrics[k] for k in ('bootloader_flash_bytes', 'bootloader_static_ram_bytes')})
                        values['bootloader_elf_file_bytes'] = len(data)
                    else:
                        if digest != run.get('firmware_sha256'):
                            raise ValueError('packaged_image_identity_mismatch')
                        image_id = digest
                        values.update(image_layout(data))
                except (OSError, ValueError, KeyError, struct.error) as exc:
                    for m in RESOURCE_DEFINITIONS:
                        if (m.startswith('bootloader')) == (role == 'wolfboot_image'):
                            reasons[m] = str(exc)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            reasons = {m:str(exc) for m in RESOURCE_DEFINITIONS}
        # Stack measurement belongs to a separate instrumented boot lifetime.
        stack_records = [r for ep in epochs if not ep.errors for r in ep.records if r['context']=='secure_boot' and r['marker']=='PQC_SECURE_BOOT_STACK']
        if len(stack_records) == 1 and not error and len(decoded)==1 and decoded[0][1]['reason'] is None:
            f = stack_records[0]['fields']
            try:
                peak, capacity = uint(f.get('high_water_bytes')), uint(f.get('watermark_capacity_bytes'))
                if (f.get('schema') != '1' or f.get('boundary') != 'selected_image_integrity_begin_to_verification_end'
                        or f.get('profiling_enabled') != '1' or f.get('timing_comparable') != '0'
                        or f.get('measurement_status') != 'measured' or f.get('selected_image_valid') != '1'
                        or not 0 < peak <= capacity or run.get('boot_stack_profiling') is not True):
                    raise ValueError('invalid_stack_evidence')
                values['boot_stack_high_water_bytes'] = peak
            except ValueError as exc:
                reasons['boot_stack_high_water_bytes'] = str(exc)
        for metric, definition in RESOURCE_DEFINITIONS.items():
            resource = _row(metric, definition, values.get(metric),
                None if values.get(metric) is not None else reasons.get(metric, 'not_recorded'),
                **base, build_id=build_id, image_id=image_id,
                scope='boot_lifetime' if metric.startswith('boot_stack') else 'build',
                observation_id=key if metric.startswith('boot_stack') else build_id if metric.startswith('bootloader') else image_id,
                source_records=[r['ref'] for r in stack_records] if metric.startswith('boot_stack') else [])
            if metric=='image_signature_used_bytes' and image_id and 'image_header_reserved_bytes' in values and values.get(metric) is None and all(d[1]['algorithm']=='integrity_sha256' for d in decoded):
                resource.update(validity='not_applicable', reason='integrity_reference_has_no_signature_TLV')
            resources.append(resource)
    verify_source_inputs(dataset.metadata)
    for item in inputs:
        if sha256_file(Path(item['path'])) != item['sha256']:
            raise DatasetError('secure_boot_input_changed_during_analysis')
    return dict(observations=observations, outcomes=outcomes, resources=resources,
                inputs=list({(i['path'],i['sha256']):i for i in inputs}.values()))


def control_problems(runs, spec, outcomes):
    from framework.timing_summary import CORE_CONTROLS, OBSERVED_CONTROLS, leaves, field, comparison_field
    controls = set(CORE_CONTROLS) | set(spec['controls'])
    for run in runs:
        controls |= leaves(run.get('controls', {}))
    controls -= OBSERVED_CONTROLS | set(spec['treatment']) | set(spec['not_applicable'])
    problems = []
    for name in sorted(controls):
        values = [comparison_field(r,name,spec) for r in runs]
        if any(v is None or v == '' or v == {} for v in values):
            problems.append('unknown_control:' + name)
        elif len({json.dumps(v, sort_keys=True) for v in values}) != 1:
            problems.append('conflicting_control:' + name)
    # Application payload size is mandatory even when firmware hashes differ by profile.
    sizes = [o['image_payload_bytes'] for o in outcomes if o['run_key'] in {r['run_key'] for r in runs}]
    if not sizes or None in sizes:
        problems.append('unknown_image_payload_size')
    elif len(set(sizes)) != 1:
        problems.append('conflicting_image_payload_size')
    clocks = [o.get('bootloader_hclk_hz') for o in outcomes if o['run_key'] in {r['run_key'] for r in runs}]
    if not clocks or None in clocks:
        problems.append('unknown_bootloader_hclk')
    elif len(set(clocks)) != 1:
        problems.append('conflicting_bootloader_hclk')
    return problems


def summarise_secure_boot(dataset, spec):
    import pandas as pd
    from framework.timing_summary import summarise
    frames, spec = summarise(dataset, spec)
    data = extract_secure_boot(dataset)
    inventory = frames['inventory'].to_dict('records')
    groups = {label:[r for r in inventory if r['condition']==label and not r['exclusion_reason']]
              for label in spec['conditions']}
    distributions, differences = [], []
    for label, runs in groups.items():
        keys = {r['run_key'] for r in runs}
        conflicts = [p for p in control_problems(runs, spec, data['outcomes']) if p.startswith('conflicting_')]
        good = {o['run_key'] for o in data['outcomes'] if o['normal_boot_success']}
        for metric in [*BOUNDARIES, *RESOURCE_DEFINITIONS]:
            timing = metric in BOUNDARIES
            candidates = [r for r in data['observations' if timing else 'resources'] if r['run_key'] in keys and r['metric']==metric]
            usable = [r for r in candidates if r['validity']=='valid' and r['case_kind']=='normal_boot'
                      and (not timing or r['timing_comparable'] and r['run_key'] in good)]
            # Preserve build deduplication and refuse conflicting duplicates.
            grouped = {}
            for r in usable:
                ident = r['run_key'] if timing else r['observation_id']
                if ident is not None:
                    grouped.setdefault(ident, []).append(r['elapsed_ms'] if timing else r['value_bytes'])
            samples = {k:v[0] for k,v in grouped.items() if len(set(v))==1 and (not timing or len(v)==1)}
            if conflicts:
                samples = {}
            repeated = timing or metric.startswith('boot_stack')
            quartiles = (list(map(float, np.quantile(list(samples.values()), [.25, .75, .95], method='linear')))
                         if repeated and samples else [None, None, None])
            distributions.append(dict(condition=label, metric=metric, unit='ms' if timing else 'bytes',
                median=median(samples.values()) if samples else None, n_observations=len(samples),
                q1=quartiles[0], q3=quartiles[1], p95=quartiles[2],
                n_runs=len(samples) if repeated else None,
                quantile_method='linear' if repeated else None,
                observation_ids=sorted(samples), run_keys=sorted(keys),
                sample_unit='run' if timing or metric.startswith('boot_stack') else 'unique_build_or_image',
                reason=None if samples else ';'.join(conflicts) or 'no_unambiguous_usable_evidence'))
    baseline = spec['baseline']
    for label, runs in groups.items():
        if label == baseline:
            continue
        all_runs = runs + groups[baseline]
        problems = control_problems(all_runs, spec, data['outcomes'])
        if not runs or not groups[baseline]:
            problems.append('empty_condition_or_baseline')
        for metric in [*BOUNDARIES, *RESOURCE_DEFINITIONS]:
            a = next(r for r in distributions if r['condition']==baseline and r['metric']==metric)
            b = next(r for r in distributions if r['condition']==label and r['metric']==metric)
            reason = ';'.join(problems) or a['reason'] or b['reason']
            if metric == 'authenticity' and any(r.get('secure_boot')=='integrity_sha256' for r in all_runs):
                reason = 'integrity_reference_is_not_signature_authentication'
            differences.append(dict(condition=label, baseline=baseline, metric=metric, unit=a['unit'],
                delta_median=None if reason else b['median']-a['median'], reason=reason,
                baseline_ids=a['observation_ids'], treatment_ids=b['observation_ids']))
    output = {'secure_boot_'+k:pd.DataFrame(v, dtype=object) for k,v in data.items() if k!='inputs'}
    outcome_counts = []
    for label, runs in groups.items():
        keys = {r['run_key'] for r in runs}
        for state in ('normal_handoff', 'expected_rejection_validation_passed', 'unexpected_handoff', 'unknown'):
            matching = [o for o in data['outcomes'] if o['run_key'] in keys and o['observed_outcome']==state]
            outcome_counts.append(dict(condition=label, observed_outcome=state,
                n_runs=len({o['run_key'] for o in matching}), n_epochs=len(matching),
                run_keys=sorted({o['run_key'] for o in matching})))
    output['secure_boot_outcome_counts'] = pd.DataFrame(outcome_counts, dtype=object)
    output['secure_boot_distributions'] = pd.DataFrame(distributions, dtype=object)
    output['secure_boot_differences'] = pd.DataFrame(differences, columns=['condition','baseline','metric','unit','delta_median','reason','baseline_ids','treatment_ids'], dtype=object)
    return output, dict(version=VERSION, source_sha256=sha256_file(Path(__file__)), inputs=data['inputs'],
        boundaries=BOUNDARIES, resources=RESOURCE_DEFINITIONS,
        policy='v8 structural mailbox validity is not freshness proof; no concurrent bootloader/application RAM sum; integrity is a reference; descriptive per-run/build medians',
        energy='A6 currently records application-origin intervals only; no matching boot interval, boot energy unavailable')
