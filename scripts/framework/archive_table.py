"""Typed, nullable experiment and individual-handshake rows; no acquisition side effects.

Only repeated TLS handshakes split a capture into multiple rows. Run-wide values are
not copied onto handshake rows. Detailed diagnostics stay in specialist exports.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import median

from framework.timing_dataset import (DatasetError, PRUNED, _has_symlink, _artifact,
    encode_cell, export_dataset, read_json, verify_source_inputs)
from framework.timing_dataset_loader import load_dataset, _decode
from framework.timing_dataset_schema import RUN_COLUMNS, METRICS, NULL
from framework.run_evidence import sha256_file

VERSION = 2
SPEC = {'conditions': {'archive': {}}, 'baseline': 'archive', 'independent_runs': False}
RAW_MARKERS = {'PQC_RM2_METRICS', 'PQC_RM2_COMPLETE', 'PQC_TLS_HANDSHAKE_TIMING',
               'PQC_ENERGY_BOUNDARY'}
BASE = {k:v for k,v in RUN_COLUMNS.items() if v != 'json'}
BASE.update(dict.fromkeys(('row_kind', 'campaign_execution_id', 'campaign_manifest_path',
    'campaign_manifest_sha256', 'campaign_state', 'attempt_state', 'attempt_error',
    'git_state_identity', 'tls_mode', 'energy_profile', 'electrical_boundary',
    'electrical_boundary_reference', 'network_identity_reference', 'issue_codes',
    'input_aliases', 'analysis_errors', 'row_id', 'data_status', 'profile_hashes', 'created_at', 'handshake_outcome', 'tcp_outcome', 'handshake_failure_stage', 'energy_firmware_sha256', 'energy_calibration', 'packet_client_ip', 'packet_server_ip'), 'string'))
BASE.update(dict.fromkeys(('transport_mode', 'kex_class', 'workspace_implementation',
    'primitive_signature_algorithm', 'primitive_signature_parameter',
    'primitive_kem_algorithm', 'primitive_kem_parameter',
    'primitive_hash_algorithm', 'primitive_hash_parameter'), 'string'))
BASE['primitive_repetitions'] = 'integer'
BASE.update(dict.fromkeys(('epoch_index','iteration_id','handshake_id','campaign_slot_index','packet_server_port'),'integer'))
BASE.update(dict.fromkeys(('run_success', 'selected_inputs_valid', 'capture_valid', 'git_dirty',
                          'campaign_manifest_valid', 'energy_enabled'), 'boolean'))

PRIMITIVES = {
    'mldsa_keygen': ('signature', 'ML-DSA', 'keygen'),
    'mldsa_sign': ('signature', 'ML-DSA', 'sign'),
    'mldsa_verify': ('signature', 'ML-DSA', 'verify'),
    'mlkem_keygen': ('kem', 'ML-KEM', 'keygen'),
    'mlkem_encapsulate': ('kem', 'ML-KEM', 'encapsulate'),
    'mlkem_decapsulate': ('kem', 'ML-KEM', 'decapsulate'),
    'sha256_hash': ('hash', 'SHA-256', 'digest'),
}
TLS_ROLES = {
    **{name+'_'+op: ('kex_classical_'+op, name)
       for name in ('p256','p384','p521','x25519') for op in ('keygen','shared_secret')},
    **{name+'_'+op: ('kex_kem_'+op, name)
       for name in ('mlkem512','mlkem768','mlkem1024') for op in ('keygen','decapsulate')},
    **{name+'_'+op: ('signature_'+op, name)
       for name in ('rsa','ecdsa','mldsa65') for op in ('sign','verify')},
    'sha256': ('hash','sha256'), 'sha384': ('hash','sha384'),
    'hkdf_extract': ('kdf_extract','hkdf'), 'hkdf_expand': ('kdf_expand','hkdf'),
    'x509_verify': ('certificate_chain_verify','x509'),
}
BASE.update(dict.fromkeys(('tls_'+role+'_implementation' for role,_ in TLS_ROLES.values()), 'string'))


def _resource_name(metric):
    return 'resource__'+metric.replace('mldsa_workspace_', 'workspace_')


def _transport_dimensions(run):
    tls = run.get('controls', {}).get('tls', {})
    if run.get('application') == 'baremetal_benchmark':
        return {'transport_mode':'not_applicable', 'kex_class':None}
    mode = tls.get('mode')
    if mode == 'plaintext' and run.get('tls_kex') == 'not_applicable':
        return {'transport_mode':'plaintext', 'kex_class':'not_applicable'}
    for prefix, family in (('classical_tls_', 'classical'), ('pqc_hybrid_tls_', 'hybrid_pqc'), ('pqc_tls_', 'pqc')):
        if isinstance(mode,str) and mode.startswith(prefix):
            return {'transport_mode':'tls', 'kex_class':family}
    return {'transport_mode':None, 'kex_class':None}


def _primitive_observations(samples, observations, rows):
    grouped = defaultdict(list)
    for sample in samples:
        # Uncompiled alternatives are inventory records, not measured repetitions.
        if sample['validity'] == 'valid':
            grouped[sample['run_key']].append(sample)
    for key, members in grouped.items():
        clocks = {m['hclk_hz'] for m in members}
        observations.add(key, 'primitive__hclk_hz', next(iter(clocks)) if len(clocks)==1 else None,
            len(clocks)==1, unit='Hz', origin='recorded_benchmark')
        counts = set()
        for role in ('signature','kem','hash'):
            selected = [m for m in members if PRIMITIVES.get(m['operation'],(None,))[0]==role]
            identities = {(PRIMITIVES[m['operation']][1],m['parameter']) for m in selected}
            if len(identities) != 1:
                if identities: rows[key]['analysis_errors']='primitive:ambiguous_algorithm_or_parameter'
                continue
            algorithm, parameter = next(iter(identities))
            rows[key].update({'primitive_'+role+'_algorithm':algorithm,
                              'primitive_'+role+'_parameter':parameter})
            for operation in sorted({PRIMITIVES[m['operation']][2] for m in selected}):
                values = [m['cycles'] for m in selected if PRIMITIVES[m['operation']][2]==operation]
                counts.add(len(values))
                observations.add(key, f'primitive__{role}_{operation}_median_cycles', median(values), True,
                    unit='cycles', origin='within_run_benchmark_median')
        rows[key]['primitive_repetitions'] = next(iter(counts)) if len(counts)==1 else None



def _name(value):
    # Preserve punctuation without collisions; pandas supports bracket selection.
    from urllib.parse import quote
    return quote(str(value), safe='_')


def _scalar_controls(value, prefix='control'):
    for key, item in sorted(value.items()):
        name = prefix + '__' + _name(key)
        if isinstance(item, dict):
            yield from _scalar_controls(item, name)
        elif item is None or type(item) in (str, int, float, bool):
            yield name, item


def _kind(values):
    types = {type(v) for v in values if v is not None}
    if types <= {bool}: return 'boolean'
    if types <= {int}: return 'integer'
    if types <= {int, float}: return 'number'
    return 'string'


def _walk_campaigns(root):
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in PRUNED | {'reports', 'datasets', 'snapshot'}
                         and not (base/d).is_symlink())
        if 'campaign-manifest.json' in files:
            yield base/'campaign-manifest.json'


def _campaign_rows(root, rows, inputs):
    """Include blocked attempts that never acquired a run manifest."""
    paths = {str(Path(path).resolve()): row for row in rows.values()
             for path in json.loads(row['input_aliases'])}
    seen = set()
    for path in _walk_campaigns(root):
        if _has_symlink(path): continue
        data = read_json(path.read_bytes())
        digest = sha256_file(path)
        inputs.append({'path': str(path), 'sha256': digest})
        from framework.campaign_executor import canonical_sha256
        index = data.get('final_index', {})
        valid = (index.get('status') == 'finalized' and index.get('sha256') ==
                 canonical_sha256({k:v for k,v in data.items() if k != 'final_index'}))
        for ordinal, attempt in enumerate(data.get('runs', [])):
            identity = (digest, ordinal)
            if identity in seen: continue
            seen.add(identity)
            recorded = attempt.get('manifest')
            target = None
            if recorded:
                candidate = Path(recorded)
                # Relocate using the owned campaign root, never run ID alone.
                parts = candidate.parts
                if 'runs' in parts:
                    candidate = path.parent/Path(*parts[len(parts)-1-parts[::-1].index('runs'):])
                target = paths.get(str(candidate.parent.resolve()))
            if target is None:
                key = hashlib.sha256((digest+':'+str(ordinal)).encode()).hexdigest()
                target = dict(run_key=key, row_kind='campaign_attempt_without_capture',
                    run_id=None, campaign_id=data.get('campaign_id'),
                    case_id=attempt.get('case_id'), repetition_index=attempt.get('repetition_index'),
                    attempt_index=attempt.get('attempt_index'), campaign_slot_index=ordinal, execution_outcome='not_executed',
                    selected_input_status='no_run_manifest', selected_inputs_valid=False,
                    capture_valid=False, run_success=False, input_aliases='[]',
                    configuration_identity=attempt.get('configuration_identity'),
                    firmware_identity=attempt.get('firmware_identity'),
                    firmware_sha256=attempt.get('firmware_sha256'),
                    condition_identity=attempt.get('condition_identity'),
                    network_condition=attempt.get('network_condition'))
                rows[key] = target
            target.update(campaign_slot_index=ordinal,campaign_execution_id=path.parent.name,
                campaign_manifest_path=str(path), campaign_manifest_sha256=digest,
                campaign_manifest_valid=valid, campaign_state=data.get('state'),
                attempt_state=attempt.get('state'),
                # Framework-owned diagnostic only; no stderr or payload copying.
                attempt_error=(attempt.get('failure') or {}).get('message'))
            if target['row_kind'] == 'campaign_attempt_without_capture':
                target['failure_stage'] = (attempt.get('failure') or {}).get('stage')


class Observations:
    def __init__(self):
        self.catalog = {}
        self.rows = []
        self.iterations = defaultdict(set)
        self.iteration_status = {}

    def define(self, metric, unit, origin, aggregation='unique'):
        definition = {'unit': unit, 'origin': origin, 'aggregation': aggregation}
        if metric in self.catalog and self.catalog[metric] != definition:
            raise DatasetError('conflicting archive metric definition: '+metric)
        self.catalog[metric] = definition

    def add(self, key, metric, value, valid, reason=None, *, unit='', origin='derived',
            aggregation='unique', reference=None, epoch=None, iteration=None, handshake=None, scope='run'):
        self.define(metric, unit, origin, aggregation)
        finite = type(value) in (int,float) and math.isfinite(value)
        self.rows.append(dict(run_key=key, metric=metric, value=value if valid and finite else None,
            valid=bool(valid and finite), reason=reason if reason else None if valid and finite else 'not_recorded_or_invalid',
            reference=json.dumps(reference, sort_keys=True) if reference is not None else None,
            epoch_index=epoch, iteration_id=iteration, handshake_id=handshake, scope=scope))

    def project(self, parents):
        grouped = defaultdict(list)
        for item in self.rows: grouped[item['run_key'], item['metric']].append(item)
        output = []
        for key, parent in parents.items():
            repeated = parent.get('application') == 'tls_handshake_repeat'
            identities = sorted(self.iterations[key], key=lambda x: tuple(-1 if v is None else v for v in x)) if repeated else []
            for identity in identities or [(None,None,None)]:
                row = dict(parent)
                row.update(zip(('epoch_index','iteration_id','handshake_id'),identity))
                row.update(self.iteration_status.get((key,*identity[:2]),{}))
                row['row_kind'] = 'handshake' if identities else parent['row_kind']
                row['row_id'] = hashlib.sha256((key+':'+repr(identity)).encode()).hexdigest()
                reasons = set(filter(None,[parent.get('analysis_errors')]))
                available = 0
                for metric, definition in sorted(self.catalog.items()):
                    observed = grouped[key, metric]
                    if repeated:
                        observed = [r for r in observed if r['scope']=='build' or
                            (identities and r['scope']=='iteration' and
                             (r['epoch_index'],r['iteration_id']) == identity[:2])]
                    good = [r['value'] for r in observed if r['valid']]
                    bad = [r for r in observed if not r['valid']]
                    if bad:
                        good = []
                        reasons.add(definition['origin']+':unavailable_values')
                    if definition['aggregation']=='unique' and len(set(good)) > 1:
                        good = [];reasons.add(definition['origin']+':multiple_unattributed_values')
                    row[metric] = (sum(good) if definition['aggregation']=='sum' else good[0]) if good else None
                    available += bool(good)
                row['data_status'] = ('partial' if reasons else 'available') if available else 'unavailable'
                row['analysis_errors'] = ';'.join(sorted(reasons)) or None
                output.append(row)
        return output, {metric:('integer' if self.catalog[metric]['origin'] in ('recorded_scalar','recorded_benchmark') else 'number') for metric in sorted(self.catalog)}


def _extract(dataset, annotations, observations, rows, inputs):
    from framework.resource_analysis import extract_resources, STATIC, RUNTIME, TLS
    from framework.secure_boot_analysis import extract_secure_boot, BOUNDARIES, RESOURCE_DEFINITIONS
    from framework.tls_analysis import summarise_tls, PHASES
    from framework.energy_analysis import summarise_energy, SCOPES
    from framework.research_extensions import summarise_baremetal, summarise_ota
    from framework.timing_metrics import decode_epochs
    from framework.network_analysis import METRICS as NETWORK_METRICS
    observations.define('primitive__hclk_hz','Hz','recorded_benchmark')
    for role,_,operation in PRIMITIVES.values():
        observations.define(f'primitive__{role}_{operation}_median_cycles','cycles','within_run_benchmark_median')
    for metric in METRICS: observations.define('timing__'+metric+'_us','us','derived_timing')
    for metric in (*STATIC, *RUNTIME, *TLS, 'simultaneous_system_peak_bytes'):
        observations.define(_resource_name(metric),'bytes','derived_resource','unique')
    for metric in BOUNDARIES: observations.define('boot__'+metric+'_ms','ms','derived_boot','unique')
    for metric in RESOURCE_DEFINITIONS: observations.define('boot__'+metric,'bytes','derived_boot','unique')
    for representation in ('aggregate','invocation'):
        for op in sorted({role for role,_ in TLS_ROLES.values()} | PHASES | {'handshake'}):
            for measure, unit in (('elapsed_us','us'),('count','count')):
                observations.define(f'tls__{representation}__{op}__{measure}',unit,'derived_tls')
    for scope in SCOPES:
        for measure, unit in (('energy_j','J'),('average_power_w','W'),('duration_s','s')):
            observations.define('energy__'+scope+'__'+measure,unit,'derived_energy')
    for direction in ('client_to_server','server_to_client'):
        for metric,unit in NETWORK_METRICS.items():
            observations.define('packet__'+direction+'__'+metric,unit,'derived_pcap','sum')
    observations.define('application__payload_throughput_bytes_s','bytes/s','derived_timing')
    for t in dataset.timings:
        observations.add(t['run_key'],'timing__'+t['metric']+'_us',t['value_us'],
            t['validity']=='valid' and next(r for r in dataset.runs if r['run_key']==t['run_key'])['selected_input_status']=='verified',
            t['reason'], unit='us',origin='derived_timing',reference=t['source_records'],epoch=t.get('epoch_index'),iteration=t.get('iteration_id'),handshake=t.get('handshake_id'),
            scope='iteration' if t['metric']=='tls_handshake' else 'run')
    valid_keys = {r['run_key'] for r in dataset.runs if r['selected_input_status']=='verified'}
    usable = replace(dataset, runs=tuple(r for r in dataset.runs if r['run_key'] in valid_keys),
                     timings=tuple(t for t in dataset.timings if t['run_key'] in valid_keys))
    if not usable.runs: return
    resource = extract_resources(usable); inputs.extend(resource['inputs'])
    for build in resource['builds']:
        for key in build['run_keys']:
            for t in build['resources']:
                observations.add(key,_resource_name(t['metric']),t['value_bytes'],t['validity']=='valid',t['reason'],
                    unit='bytes',origin='derived_resource',aggregation='unique',reference=build['build_id'],scope='build')
    for t in resource['runtime']:
        metric=_resource_name(t['metric'])
        if t['metric'].startswith('mldsa_workspace_'):
            rows[t['run_key']]['workspace_implementation']='mldsa_workspace'
        # Task/checkpoint identities are separate columns, never pooled RAM peaks.
        for k in ('task','checkpoint','region'):
            if t.get(k) and t['metric'] not in RUNTIME and t['metric'] not in TLS:
                metric+='__'+_name(t[k])
        observations.add(t['run_key'],metric,t['value_bytes'],t['validity']=='valid',t['reason'],
            unit='bytes',origin='derived_resource',aggregation='unique',reference=t.get('source_records'),epoch=t.get('epoch_index'),iteration=t.get('iteration_id'),scope='iteration' if t.get('iteration_id') is not None else 'run')
    boot = extract_secure_boot(usable); inputs.extend(boot['inputs'])
    for name,unit,value in (('observations','ms','elapsed_ms'),('resources','bytes','value_bytes')):
        for t in boot[name]:
            metric='boot__'+t['metric']+('_ms' if unit=='ms' else '')
            valid=t['validity']=='valid' and (unit!='ms' or t.get('timing_comparable',False))
            observations.add(t['run_key'],metric,t[value],valid,t['reason'] or (None if valid else 'boot_timing_not_comparable'),
                unit=unit,origin='derived_boot',aggregation='unique',reference=t.get('source_records'),scope='build' if t.get('scope')=='build' else 'run')
    tls, lineage = summarise_tls(usable,SPEC); inputs.extend(lineage['inputs'])
    for t in tls['tls_iterations'].to_dict('records'):
        observations.iterations[t['run_key']].add((t.get('epoch_index'),t.get('iteration_id'),int(t['recorded_status']['handshake']) if str(t.get('recorded_status',{}).get('handshake','')).isdigit() else None))
        observations.iteration_status[t['run_key'],t.get('epoch_index'),t.get('iteration_id')] = {
            'handshake_outcome':t.get('tls_outcome'), 'tcp_outcome':t.get('tcp_outcome'),
            'handshake_failure_stage':t.get('failure_stage')}
    groups = defaultdict(list)
    for t in tls['tls_attribution'].to_dict('records'):
        if t.get('operation'):
            role = TLS_ROLES.get(t['operation'], (t['operation'], None))[0]
            groups[t['run_key'],t.get('epoch_index'),t.get('iteration_id'),t['representation'],role].append(t)
    good_handshakes = {(t['run_key'],t.get('epoch_index'),t.get('iteration_id'))
        for t in tls['tls_handshakes'].to_dict('records') if t.get('validity')=='valid'}
    for (key,epoch,iteration,representation,role), members in groups.items():
        implementations = {TLS_ROLES[t['operation']][1] for t in members if t['operation'] in TLS_ROLES}
        valid = ((key,epoch,iteration) in good_handshakes and len(implementations)<=1
                 and all(t['validity']=='valid' for t in members))
        if implementations:
            label = next(iter(implementations)) if len(implementations)==1 else 'mixed'
            field = 'tls_'+role+'_implementation'
            if rows[key].get('application')=='tls_handshake_repeat':
                observations.iteration_status.setdefault((key,epoch,iteration),{})[field]=label
            else:
                prior = rows[key].get(field)
                rows[key][field] = label if prior in (None,label) else 'mixed'
        if representation=='invocation' and valid:
            ordered=sorted(members,key=lambda t:t['start_us'])
            valid=not any(a['end_us']>b['start_us'] for a,b in zip(ordered,ordered[1:]))
        for measure,field,unit in (('elapsed_us','value_us','us'),('count','count','count')):
            values=[t.get(field) for t in members]
            ok=valid and all(type(v) in (int,float) for v in values)
            observations.add(key,f'tls__{representation}__{role}__{measure}',sum(values) if ok else None,ok,
                'invalid_or_ambiguous_tls_operation' if not ok else None,unit=unit,origin='derived_tls',
                epoch=epoch,iteration=iteration,scope='iteration')
    energy, lineage = summarise_energy(usable,SPEC,{'boundaries':{r['run_key']:annotations['energy']
        for r in usable.runs} if annotations.get('energy') else {}})
    inputs.extend(lineage['inputs'])
    for t in energy['energy_intervals'].to_dict('records'):
        if t.get('alignment_reason'): continue  # Never pool stale/superseded captures.
        key=t['run_key']
        rows[key]['energy_firmware_sha256']=t.get('firmware_sha256')
        rows[key]['energy_calibration']=json.dumps(t.get('calibration'),sort_keys=True)
        for k in ('sample_count','maximum_gap_us'):
            observations.add(key,'energy_raw__'+k,t.get(k),bool(t.get('acquisition_valid')),t.get('acquisition_reason'),
                unit='count' if k=='sample_count' else 'us',origin='recorded_energy',aggregation='unique')
        for measure,unit in (('energy_j','J'),('average_power_w','W'),('duration_s','s')):
            observations.add(key,'energy__'+t['scope']+'__'+measure,t.get(measure),
                t['validity']=='valid' and bool(t.get('electrical_boundary')),
                t['reason'] or (None if t.get('electrical_boundary') else 'electrical_boundary_unknown'),
                unit=unit,origin='derived_energy',reference=t.get('bracketing_sample_indices'),epoch=t.get('epoch_index'),iteration=t.get('iteration_id'),
                scope='iteration' if t['scope'] in ('tls_handshake','application_transfer') else 'run')
    bare, lineage = summarise_baremetal(usable,SPEC); inputs.extend(lineage['inputs'])
    _primitive_observations(bare['baremetal_samples'].to_dict('records'),observations,rows)
    for item in bare['baremetal_availability'].to_dict('records'):
        if item['status'] != 'available':
            rows[item['run_key']]['analysis_errors']='primitive:invalid_or_missing_benchmark_evidence'
    ota,lineage = summarise_ota(usable,SPEC); inputs.extend(lineage['inputs'])
    for t in ota['ota_outcomes'].to_dict('records'):
        for k,v in t.items():
            if k not in ('run_key','condition','exclusion_reason') and type(v) in (str,bool,int,float):
                rows[t['run_key']]['ota__'+k]=v
    for run in usable.runs:
        key=run['run_key']; root=Path(run['input_path'])
        epochs,errors=decode_epochs(root/'mqtt-reporting-raw.ndjson',run['run_id'])
        for epoch in epochs:
            if errors or epoch.errors: continue
            for record in epoch.records:
                if record['marker'] not in RAW_MARKERS: continue
                for field,value in record['fields'].items():
                    if re.fullmatch(r'-?[0-9]+',str(value)):
                        observations.add(key,'recorded__'+record['marker']+'__'+_name(field),int(value),True,
                            origin='recorded_scalar',aggregation='unique',reference=record['ref'],epoch=epoch.index,
                            iteration=record.get('iteration'),scope='iteration' if record['marker']=='PQC_TLS_HANDSHAKE_TIMING' else 'run')
        starts = {(t['epoch_index'],t['iteration_id']): t for t in usable.timings if t['run_key']==key and t['metric']=='req_tfb'}
        for t in usable.timings:
            a=starts.get((t['epoch_index'],t['iteration_id']))
            if t['run_key']!=key or t['metric']!='req_tlb' or not a: continue
            delta=(t.get('end_us') or 0)-(a.get('end_us') or 0)
            valid=(t['validity']==a['validity']=='valid' and delta>0 and run.get('payload_bytes') is not None)
            observations.add(key,'application__payload_throughput_bytes_s',run['payload_bytes']*1e6/delta if valid else None,
                valid,'invalid_transfer_interval' if not valid else None,unit='bytes/s',origin='derived_timing')
        if annotations.get('network'):
            try:
                from framework.thesis_collection import network_selection
                from framework.network_analysis import retained, read_pcap, flow_observations
                selections=network_selection(replace(usable,runs=(run,)),annotations['network'])
                if key not in selections: continue
                rows[key].update(packet_client_ip=selections[key]['client_ip'],
                    packet_server_ip=selections[key]['server_ip'],packet_server_port=selections[key]['server_port'])
                manifest=read_json((root/'manifest.json').read_bytes())
                path=retained(root,manifest,'packet_capture',inputs)
                if path is None: continue
                _,packets=read_pcap(path)
                flows,_=flow_observations(packets,selections[key])
                for flow in flows:
                    for metric,unit in NETWORK_METRICS.items():
                        value=flow[metric]
                        observations.add(key,'packet__'+flow['direction']+'__'+metric,value,
                            value is not None and not flow['capture_truncated'],
                            'truncated_capture' if flow['capture_truncated'] else None if value is not None else flow['overlap_reason'],
                            unit=unit,origin='derived_pcap',aggregation='sum',reference=flow['flow_id'])
            except (ValueError,OSError,KeyError) as exc:
                rows[key]['analysis_errors']='packet_analysis_unavailable:'+type(exc).__name__


def _write(path, rows, columns):
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=columns,lineterminator='\n');writer.writeheader()
        for row in rows:
            writer.writerow({k:(repr(float(row[k])) if t=='number' and row.get(k) is not None
                                  else encode_cell(row.get(k),'string' if t=='number' else t)) for k,t in columns.items()})


def export_archive(*, results_root, output, annotations=None, source_roots=None):
    root=Path(results_root).absolute();output=Path(output).absolute()
    if output.exists() or _has_symlink(output): raise DatasetError('archive output must be a new non-symlink directory')
    if output==root or root.is_relative_to(output): raise DatasetError('archive output overlaps source root')
    annotations=annotations or {}
    from framework.thesis_collection import annotations as validate_annotations
    validate_annotations(annotations)
    output.mkdir(parents=True,mode=0o700)
    from framework.timing_dataset import discover_inputs
    from framework.timing_dataset_loader import TimingDataset
    roots=[Path(p).absolute() for p in source_roots] if source_roots is not None else [root]
    paths=[]
    for selected in roots:
        if not selected.is_dir(): continue
        try:
            found,_=discover_inputs(results_root=selected);paths.extend(found)
        except DatasetError as exc:
            if 'no run inputs discovered' not in str(exc): raise
    if paths:
        export_dataset(output=output/'source-dataset',run_dirs=paths)
        dataset=load_dataset(output/'source-dataset',verify_inputs=True)
    else:
        dataset=TimingDataset(runs=(),timings=(),issues=(),metadata={'inputs':[], 'dataset_id':None})
    rows={};inputs=[]
    issues=defaultdict(set)
    for issue in dataset.issues: issues[issue['run_key']].add(issue['code'])
    for run in dataset.runs:
        row={k:run.get(k) for k in BASE}
        if run['manifest_status']=='verified':
            row['created_at']=read_json((Path(run['input_path'])/'manifest.json').read_bytes()).get('run',{}).get('created_at')
        row.update(dict(_scalar_controls({k:v for k,v in run.get('controls',{}).items() if k!='profile_hashes'})))
        row['profile_hashes']=json.dumps(run.get('controls',{}).get('profile_hashes',{}),sort_keys=True)
        source=run.get('controls',{}).get('source',{})
        row.update(row_kind='retained_capture',selected_inputs_valid=run['selected_input_status']=='verified',
            capture_valid=run['capture_acceptance']=='accepted',run_success=run['execution_outcome']=='completed',
            git_dirty=source.get('git_dirty'),git_state_identity=source.get('state_identity'),
            tls_mode=run.get('controls',{}).get('tls',{}).get('mode'),
            input_aliases=json.dumps(run['input_paths']),issue_codes=';'.join(sorted(issues[run['run_key']])),
            electrical_boundary=(annotations.get('energy') or {}).get('electrical_boundary'),
            electrical_boundary_reference=(annotations.get('energy') or {}).get('evidence_reference'),
            network_identity_reference=(annotations.get('network') or {}).get('evidence_reference'))
        energy=[k.split(':',2)[2] for k in run.get('controls',{}).get('profile_hashes',{}) if k.startswith('instrument:energy:')]
        row.update(_transport_dimensions(run))
        row.update(energy_profile=energy[0] if len(energy)==1 else None,energy_enabled=bool(energy))
        rows[run['run_key']]=row
    for selected in roots:
        if selected.is_dir(): _campaign_rows(selected,rows,inputs)
    if not rows: raise DatasetError('no recorded captures or campaign attempts found')
    observations=Observations();_extract(dataset,annotations,observations,rows,inputs)
    dynamic={k for row in rows.values() for k in row}-set(BASE)
    columns={**BASE,**{k:_kind([r.get(k) for r in rows.values()]) for k in sorted(dynamic)}}
    projected,metrics=observations.project(rows)
    columns.update(metrics)
    _write(output/'runs.csv',sorted(projected,key=lambda r:r['row_id']),columns)
    verify_source_inputs(dataset.metadata)
    for item in inputs:
        if sha256_file(Path(item['path']))!=item['sha256']: raise DatasetError('archive source changed during analysis')
    sources={str(p):sha256_file(p) for p in Path(__file__).parent.glob('*.py')}
    meta={'schema':'pqc-flat-archive','version':VERSION,'columns':columns,'column_order':list(columns),'metrics':observations.catalog,
        'rows':len(projected),'capture_rows':len(dataset.runs),'attempt_rows':len(rows),'annotations':annotations,'analysis_sources':sources,
        'inputs':inputs,'source_dataset_id':dataset.metadata['dataset_id'],
        'files':{name:sha256_file(output/name) for name in ('runs.csv',)},
        'null':NULL,'definitions':{
            'row':'one experiment run; only repeated TLS handshakes create separate rows; duplicate copies merged, reused run IDs kept separate; run-wide results are null on repeated-measurement rows',
            'primitive':'within-run median raw DWT cycles by functional role; algorithm and parameter are row fields; primitive_repetitions counts measured repetitions per operation; no conversion to application/TLS elapsed time',
            'tls':'functional-role columns share units across algorithms; implementation labels identify observed primitives; mixed implementations in one role are unavailable rather than pooled; protocol/operation and aggregate/invocation totals overlap and must not be summed',
            'status':'row-level source/capture/run status and analysis_errors; non-null values passed extraction checks, not cross-condition comparability. Valid measurements can remain in failed runs; timing_policy_exclusion remains explicit',
            'unique':'one scalar value; differing epochs/checkpoints are unavailable instead of averaged',
            'sum':'sum across selected packet flows within this run, directions separate; not handshake-only bytes',
            'recorded':'numeric fields from integrity-checked firmware records; raw status flags do not themselves validate a measurement',
            'missing':'null, never zero; high-level row reasons only; regenerate specialist exports for per-value diagnostics',
            'privacy':'no payloads, TLS key logs, certificates or credential material exported'}}
    (output/'archive.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n')
    (output/'archive.sha256').write_text(sha256_file(output/'archive.json')+'\n')
    load_archive(output)
    return meta


def load_archive(path, *, verify_sources=False):
    """Load into pandas with nullable dtypes; default pandas NA guessing is disabled."""
    import pandas as pd
    path=Path(path)
    if _has_symlink(path): raise DatasetError('symlink archive refused')
    if sha256_file(path/'archive.json')!=(path/'archive.sha256').read_text().strip():
        raise DatasetError('archive metadata hash mismatch')
    meta=read_json((path/'archive.json').read_bytes())
    if meta.get('schema')!='pqc-flat-archive' or meta.get('version') not in (1,VERSION): raise DatasetError('unsupported archive schema')
    for name,digest in meta['files'].items():
        if name not in ('runs.csv',) or _has_symlink(path/name) or sha256_file(path/name)!=digest:
            raise DatasetError('archive table hash mismatch')
    if verify_sources:
        if meta['source_dataset_id'] is not None: load_dataset(path/'source-dataset',verify_inputs=True)
        for item in meta['inputs']:
            if sha256_file(Path(item['path']))!=item['sha256']: raise DatasetError('archive source hash mismatch')
    columns={k:meta['columns'][k] for k in meta['column_order']}; values={k:[] for k in columns}
    with (path/'runs.csv').open(newline='',encoding='utf-8') as f:
        reader=csv.DictReader(f)
        if reader.fieldnames!=list(columns): raise DatasetError('archive column mismatch')
        for row in reader:
            for k,t in columns.items():
                value=row[k]
                parsed=(None if value==NULL else float(value)) if t=='number' else _decode(value,t)
                if t=='number' and parsed is not None and not math.isfinite(parsed): raise DatasetError('non-finite archive value')
                values[k].append(parsed)
    if len(values['row_id'])!=meta['rows'] or len(set(values['row_id']))!=meta['rows']:
        raise DatasetError('archive row identity/count mismatch')
    arrays={}
    for k,v in values.items():
        dtype={'number':'Float64','integer':'Int64','boolean':'boolean','string':'string'}[columns[k]]
        if columns[k]=='integer' and any(x is not None and x>2**63-1 for x in v):
            dtype='UInt64' if all(x is None or x>=0 for x in v) else 'object'
        arrays[k]=pd.array(v,dtype=dtype)
    return pd.DataFrame(arrays)
