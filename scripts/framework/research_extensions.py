"""Bounded S1/S2 imports for A8; never execute experiments or infer transitions."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from statistics import median

import pandas as pd

from framework.timing_dataset import verify_source_inputs, read_json
from framework.timing_metrics import decode_epochs, _fields
from framework.timing_summary import summarise, digest

VERSION = '1.0.0'


def summarise_baremetal(dataset, spec):
    """Raw DWT cycle references; operations within one boot are not independent runs."""
    from benchmark_summary import summarize
    verify_source_inputs(dataset.metadata)
    rows, observations, availability, inputs, metrics = [], [], [], [], {}
    for run in dataset.runs:
        if run.get('application') != 'baremetal_benchmark':
            continue
        root = Path(run['input_path'])
        base = {k:run[k] for k in ('run_key', 'run_id', 'firmware_sha256')}
        try:
            if run['selected_input_status'] != 'verified':
                raise ValueError('selected_inputs_unavailable')
            epochs, errors = decode_epochs(root/'mqtt-reporting-raw.ndjson', run['run_id'])
            if errors or len(epochs) != 1 or epochs[0].errors:
                raise ValueError('invalid_benchmark_epoch')
            records = [{'context':r['context'],'text':r['text']} for r in epochs[0].records]
            parsed = [json.loads(r['text']) for r in records if r.get('context') == 'baremetal_benchmark']
            provenance = [r for r in parsed if r.get('type') == 'benchmark_provenance']
            count = provenance[0]['iterations'] if len(provenance) == 1 else None
            if type(count) is not int or not 1 <= count <= 10:
                raise ValueError('unsupported_iteration_count')
            result = summarize(records, expected_repetitions=count)
            hclk = result['hclk_hz']
            if type(hclk) is not int or hclk <= 0:
                raise ValueError('invalid_recorded_clock')
            for index, sample in enumerate(parsed):
                if 'operation' not in sample:
                    continue
                valid = sample['outcome'] == 0
                rows.append(dict(base, operation=sample['operation'], parameter=sample['parameter'],
                    iteration_id=sample['iteration'], epoch_index=0, source_record=index+1,
                    cycles=sample['cycles'] if valid else None, hclk_hz=hclk,
                    validity='valid' if valid else 'unavailable',
                    reason=None if valid else 'algorithm_not_compiled'))
            for row in result['statistics']:
                metric = row['operation'] + ':' + row['parameter']
                metrics[metric] = {'unit':'cycles'}
                observations.append(dict(run_key=run['run_key'], run_id=run['run_id'], metric=metric,
                    value_us=row['median_cycles'], validity='valid', reason=None,
                    epoch_index=None, iteration_id=None, timing_policy_exclusion=None))
            availability.append(dict(base, status='available', reason=None, iterations=count))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            # Never export arbitrary exception text or raw records.
            availability.append(dict(base, status='unavailable', reason='invalid_or_missing_benchmark_evidence', iterations=None))
    frames, _ = summarise(replace(dataset, timings=tuple(observations)), spec, metrics=metrics)
    output = {'baremetal_samples':pd.DataFrame(rows, columns=['run_key','run_id','firmware_sha256','operation','parameter','iteration_id','epoch_index','source_record','cycles','hclk_hz','validity','reason'], dtype=object),
              'baremetal_availability':pd.DataFrame(availability, columns=['run_key','run_id','firmware_sha256','status','reason','iterations'], dtype=object)}
    for name in ('distributions','differences','completeness'):
        frames[name]['estimand'] = 'across-run median of within-run raw-cycle medians'
        output['baremetal_'+name] = frames[name]
    verify_source_inputs(dataset.metadata)
    return output, dict(version=VERSION, inputs=inputs, definitions={
        'cycles':'raw DWT_CYCCNT; no clock-normalized cycle equivalents',
        'time':'not exported; cycle boundary differs from RTOS elapsed time',
        'memory':'current benchmark workload does not measure peak RAM',
        'statistics':'one median per boot; observed operation repetitions retained separately'})


def ota_stages(records):
    """Ordered stage evidence only. UART lines have no measured timestamp/boot ID."""
    allowed = {'request_accepted','transfer_complete','activation_reset','boot_state','confirmed',
        'confirmation_withheld','transfer_failed','candidate_manifest_authenticated',
        'candidate_application_authenticated','swap_requested','candidate_first_boot','rollback_requested'}
    rows = []
    for line_number, line in enumerate(records.splitlines(), 1):
        match = re.search(r'\b(PQC_OTA_(?:APP|BOOT) .*)', line)
        if not match:
            continue
        try:
            marker, fields = _fields(match.group(1))
        except ValueError:
            continue
        if fields.get('phase') not in allowed:
            continue
        row = dict(source_line=line_number, owner='application' if marker.endswith('APP') else 'wolfboot',
                   stage=fields['phase'], duration_ms=None, duration_reason='no_recorded_stage_clock')
        for key in ('active_bank','target_bank','from_bank','to_bank','staged','booted','confirmed',
                    'boot_received','manifest_received','app_received','migration','flags'):
            value = fields.get(key)
            row[key] = int(value) if value is not None and re.fullmatch(r'[0-9]+', value) else None
        rows.append(row)
    return rows


def summarise_ota(dataset, spec):
    """Retain delivery and observable stages, with final identity deliberately gated.

    Current capture stores an external plan path, not a sealed candidate identity.
    An old path's present contents must never be used to authenticate a transition.
    """
    verify_source_inputs(dataset.metadata)
    base, _ = summarise(dataset, spec)
    stages, outcomes, inputs, images = [], [], [], []
    for run in base['inventory'].to_dict('records'):
        if run.get('exclusion_reason'):
            continue
        root = Path(run['input_path'])
        if run['selected_input_status'] != 'verified':
            if run.get('firmware_mode') == 'dual_bank_ota':
                outcomes.append(dict(run_key=run['run_key'], condition=run['condition'],
                    scenario='unknown', delivery_outcome='unknown', transition_outcome='unconfirmed',
                    final_identity_reason='selected_inputs_unavailable'))
            continue
        manifest = read_json((root/'manifest.json').read_bytes())
        from framework.timing_dataset import _artifact as retained
        raw_provenance, _ = retained(root,manifest,'run_provenance',inputs)
        provenance = read_json(raw_provenance) if raw_provenance is not None else {}
        ota = provenance.get('records',{}).get('ota', {})
        if not ota.get('requested'):
            continue
        rc = ota.get('delivery', {}).get('return_code')
        delivery = 'completed' if type(rc) is int and rc == 0 else 'failed' if type(rc) is int else 'unknown'
        from framework.resource_analysis import _artifact
        try:
            raw = _artifact(root, manifest, 'diagnostic_uart', inputs)
        except (OSError, ValueError, KeyError):
            raw = None
        rows = ota_stages(raw.decode('utf-8', errors='replace')) if raw else []
        for row in rows:
            stages.append(dict(row, run_key=run['run_key'], condition=run['condition']))
        # Deferred boot identities remain epoch-scoped; no inferred association
        # between an external plan filename and the image that finally executed.
        from framework.secure_boot_analysis import decode_boot
        epochs, errors = decode_epochs(root/'mqtt-reporting-raw.ndjson',run['run_id'])
        for epoch in epochs:
            _, boot = decode_boot(epoch.records,invalid='invalid_epoch' if errors or epoch.errors else None)
            images.append(dict(run_key=run['run_key'],condition=run['condition'],epoch_index=epoch.index,
                image_content_sha256=boot['image_content_sha256'],image_part=boot['image_part'],
                image_payload_bytes=boot['image_payload_bytes'],handoff=boot['handoff'],reason=boot['reason'],
                identity_kind='wolfboot_verified_image_content_sha256'))
        phases = {r['stage'] for r in rows}
        requests = [r for r in rows if r['stage']=='request_accepted']
        flags = requests[0]['flags'] if len(requests)==1 else None
        scenario = ('bootloader_migration' if flags is not None and flags & 1 else
                    'rollback_validation' if flags is not None and flags & 0x80000000 else
                    'application_update' if flags is not None else 'unknown')
        outcomes.append(dict(run_key=run['run_key'], condition=run['condition'], scenario=scenario,
            delivery_outcome=delivery, transfer_observed='transfer_complete' in phases,
            activation_observed='activation_reset' in phases,
            manifest_authentication_observed='candidate_manifest_authenticated' in phases,
            application_authentication_observed='candidate_application_authenticated' in phases,
            confirmation_observed='confirmed' in phases,
            rollback_observed='rollback_requested' in phases,
            transition_outcome='unconfirmed', final_identity_reason='sealed_candidate_to_final_image_binding_unavailable',
            duration_ms=None, duration_reason='no_common_clock_across_resets',
            copy_swap_reason='not_applicable_hardware_bank_activation',
            exclusion_reason=run['exclusion_reason']))
    verify_source_inputs(dataset.metadata)
    return {'ota_images':pd.DataFrame(images, columns=['run_key','condition','epoch_index','image_content_sha256','image_part','image_payload_bytes','handoff','reason','identity_kind'],dtype=object), 'ota_stages':pd.DataFrame(stages, columns=list(stages[0]) if stages else ['run_key','condition','stage','owner','duration_ms','duration_reason'], dtype=object),
            'ota_outcomes':pd.DataFrame(outcomes, columns=list(outcomes[0]) if outcomes else ['run_key','condition','scenario','delivery_outcome','transition_outcome','final_identity_reason'], dtype=object)}, dict(
                version=VERSION, inputs=inputs, definitions={'success':'delivery is not activation or final-image proof',
                    'negative':'rollback validation is separate from normal updates; absent rejection evidence remains unknown',
                    'clocks':'application, gateway and wolfBoot clocks are never subtracted across resets',
                    'energy':'no supported multi-boot interval binding'})
