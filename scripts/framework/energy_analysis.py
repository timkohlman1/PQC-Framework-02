"""A6 offline power integration and bounded two-edge clock correlation.

Current v1 acquisition contains instantaneous W, not cumulative joules. Integrate
once (trapezoids), then interpolate cumulative J linearly at bracketed boundaries.
No extrapolation, gap bridging, automatic trimming or cross-run clock matching.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from framework.analysis_paths import result_path
from framework.energy_evidence import (CAPTURE_ID, COUNTERS, ENERGY_CHUNK_TOPIC,
    ENERGY_COMPLETE_TOPIC, chunk_bytes, decode_acquisition, envelope, _stm32_boundaries)
from framework.timing_dataset import verify_source_inputs
from framework.timing_metrics import decode_epochs
from framework.timing_summary import digest, summarise

VERSION = '1.1.0'
SCOPES = ('recorded_interval', 'whole_workload', 'tls_handshake', 'application_transfer')


def acquisitions(path):
    """Retain all encountered capture identities, including partial/invalid attempts."""
    states = {}
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        topic, obj = envelope(line)
        if topic not in (ENERGY_CHUNK_TOPIC, ENERGY_COMPLETE_TOPIC):
            continue
        cid = str(obj.get('capture_id', ''))
        if not CAPTURE_ID.fullmatch(cid):
            raise ValueError('invalid_energy_capture_identity')
        state = states.setdefault(cid, dict(chunks={}, complete=None, records=[], errors=[]))
        state['records'].append(line_no)
        try:
            if obj.get('schema') != 1 or type(obj.get('schema')) is not int or obj.get('source') != 'energy':
                raise ValueError('unsupported_energy_schema')
            if topic == ENERGY_CHUNK_TOPIC:
                seq = obj.get('sequence')
                if obj.get('type') != 'chunk' or type(seq) is not int or seq < 0:
                    raise ValueError('invalid_chunk_sequence')
                data = chunk_bytes(obj)
                if seq in state['chunks'] and state['chunks'][seq] != data:
                    raise ValueError('conflicting_duplicate_chunk')
                state['chunks'][seq] = data
            else:
                if obj.get('type') != 'complete':
                    raise ValueError('invalid_completion_type')
                if state['complete'] is not None and state['complete'] != obj:
                    raise ValueError('conflicting_duplicate_completion')
                state['complete'] = obj
        except (ValueError, TypeError, KeyError) as exc:
            state['errors'].append(str(exc))
    for state in states.values():
        try:
            if state['errors']:
                raise ValueError(';'.join(state['errors']))
            if state['complete'] is None:
                raise ValueError('missing_energy_completion')
            # Bound count before the shared decoder constructs its sequence set.
            if type(state['complete'].get('chunk_count')) is not int or state['complete']['chunk_count'] > len(state['chunks']):
                raise ValueError('energy_chunk_count_mismatch')
            state['samples'] = decode_acquisition(state['complete'], state['chunks'])
            state['reason'] = None
        except (ValueError, TypeError, KeyError) as exc:
            state['samples'] = []
            state['reason'] = str(exc)
        del state['chunks']
    return states


class Integral:
    """Piecewise-linear cumulative energy, split at rejected gaps."""
    def __init__(self, samples, gap_limit):
        self.t = [s[0] for s in samples]
        self.power = [s[3] for s in samples]
        if len(samples) < 2 or any(type(t) is not int for t in self.t):
            raise ValueError('invalid_samples')
        if not all(math.isfinite(p) for p in self.power):
            raise ValueError('nonfinite_power')
        self.j = [0.0]
        self.segments = [0]
        for i in range(1, len(samples)):
            dt = self.t[i] - self.t[i-1]
            if dt <= 0:
                raise ValueError('nonmonotonic_samples')
            gap = dt > gap_limit
            self.segments.append(self.segments[-1] + int(gap))
            self.j.append(0.0 if gap else self.j[-1] + dt * (self.power[i-1]+self.power[i]) / 2_000_000)

    def at(self, timestamp):
        if timestamp < self.t[0] or timestamp > self.t[-1]:
            raise ValueError('outside_sample_coverage')
        i = bisect_left(self.t, timestamp)
        if self.t[i] == timestamp:
            return self.j[i], self.segments[i], [i, i]
        if self.segments[i] != self.segments[i-1]:
            raise ValueError('rejected_sample_gap')
        fraction = float((timestamp-self.t[i-1])/(self.t[i]-self.t[i-1]))
        return self.j[i-1]+fraction*(self.j[i]-self.j[i-1]), self.segments[i], [i-1, i]

    def interval(self, start, end):
        if end <= start:
            raise ValueError('nonpositive_interval')
        a, sa, ia = self.at(start)
        b, sb, ib = self.at(end)
        if sa != sb:
            raise ValueError('rejected_sample_gap')
        duration = float((end-start)/1_000_000)
        return dict(duration_s=duration, energy_j=b-a, average_power_w=(b-a)/duration,
                    bracketing_sample_indices=[ia, ib])


def map_boundary(value, s0, s1, e0, e1):
    if any(type(v) is not int for v in (value, s0, s1, e0, e1)) or not 0 <= s0 < s1 or not 0 <= e0 < e1:
        raise ValueError('malformed_clock_pair')
    if not s0 <= value <= s1:
        raise ValueError('outside_paired_interval')
    return e0 + Fraction((value-s0)*(e1-e0), s1-s0)


def alignment(path, run_id, states):
    """One experiment pair only in current schema; ambiguous durations stay unpaired."""
    try:
        pairs = _stm32_boundaries(path.read_text().splitlines(), run_id)
        if len(pairs) != 1:
            raise ValueError('expected_one_stm32_interval')
        epochs, errors = decode_epochs(path, run_id)
        if errors or any(epoch.errors for epoch in epochs):
            raise ValueError('invalid_stm32_pair_transport')
        references = [record['ref'] for epoch in epochs for record in epoch.records
                      if record['marker'] == 'PQC_ENERGY_BOUNDARY' and record['context'] == 'energy_boundary']
        if len(references) != 1:
            raise ValueError('invalid_stm32_pair_identity')
        s0, s1 = pairs[0]
        candidates = []
        for cid, state in states.items():
            c = state['complete'] or {}
            e0, e1 = c.get('e0_us'), c.get('e1_us')
            if type(e0) is int and type(e1) is int and 0 <= e0 < e1 and abs((e1-e0)-(s1-s0)) <= max(5000,(s1-s0)//100):
                candidates.append(cid)
        if len(candidates) != 1:
            raise ValueError('ambiguous_or_missing_capture_pair')
        return candidates[0], (s0, s1), None, references
    except (ValueError, KeyError, TypeError) as exc:
        return None, None, str(exc), []


def workload_bounds(path, run_id, pair):
    """Separate the measured workload from an explicitly recorded tail guard."""
    epochs, errors = decode_epochs(path, run_id)
    records = [record for epoch in epochs for record in epoch.records
               if record['marker'] == 'PQC_ENERGY_BOUNDARY' and record['context'] == 'energy_boundary']
    if errors or any(epoch.errors for epoch in epochs) or len(records) != 1:
        raise ValueError('invalid_workload_boundary')
    fields = records[0]['fields']
    if 'workload_end_us' not in fields and 'tail_guard_ms' not in fields:
        return pair  # Legacy captures used the GPIO interval itself.
    try:
        end = int(fields['workload_end_us'])
        guard = int(fields['tail_guard_ms'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('invalid_workload_tail_guard') from None
    if guard != 20 or not pair[0] < end <= pair[1] or pair[1] - end < guard * 1000:
        raise ValueError('invalid_workload_tail_guard')
    return pair[0], end


def phase_bounds(timings):
    phases = []
    for t in timings:
        if t['metric'] != 'tls_handshake':
            continue
        reason = None
        if t['validity'] != 'valid' or t.get('clock_source') != 'TIM2' or t.get('timestamp_origin') != 'application_timebase_start' or t.get('counter_hz') != 1_000_000:
            reason = 'unavailable_or_incompatible_phase_clock'
        phases.append(('tls_handshake', t.get('start_us'), t.get('end_us'), t, reason))
    groups = {}
    for t in timings:
        if t['metric'] in ('req_tfb', 'req_tlb'):
            groups.setdefault((t['epoch_index'], t['iteration_id']), {})[t['metric']] = t
    for group in groups.values():
        a, b = group.get('req_tfb'), group.get('req_tlb')
        reason = None
        if not a or not b or any(t['validity'] != 'valid' or t.get('clock_source') != 'TIM2' or t.get('counter_hz') != 1_000_000 or t.get('timestamp_origin') != 'application_timebase_start' for t in (a,b)):
            reason = 'unavailable_or_incompatible_phase_clock'
        elif a['start_us'] != b['start_us'] or a.get('clock_provenance') != b.get('clock_provenance'):
            reason = 'incompatible_transfer_identity'
        phases.append(('application_transfer', a.get('end_us') if a else None, b.get('end_us') if b else None, b or a, reason))
    return phases


def analyse_run(path, run, timings, boundary):
    states = acquisitions(path)
    selected, pair, pair_reason, pair_refs = alignment(path, run['run_id'], states)
    rows, traces = [], {}
    for cid, state in states.items():
        c = state['complete'] or {}
        e0, e1 = c.get('e0_us'), c.get('e1_us')
        policy = {k:c.get(k) for k in ('calibration_id','calibration_status','nominal_shunt_ohms',
                  'effective_shunt_ohms','acquisition_mode','bus_conversion_us','shunt_conversion_us','averaging','gap_limit_us')}
        base = dict(run_key=run['run_key'], run_id=run['run_id'], capture_id=cid,
            interval_id=run['run_key']+':'+cid, source_records=state['records'],
            source_sha256=digest(path), logical_sha256=c.get('logical_sha256'), electrical_boundary=boundary.get('electrical_boundary'),
            electrical_boundary_reference=boundary.get('evidence_reference'), calibration=policy,
            acquisition_schema=c.get('schema'), sample_encoding=c.get('sample_encoding'),
            metric_version=VERSION, firmware_sha256=c.get('firmware_sha256'), sample_count=c.get('sample_count'),
            acquisition_counters={k:c.get(k) for k in COUNTERS}, acquisition_valid=not state['reason'],
            acquisition_reason=state['reason'], alignment_reason=pair_reason if selected is None else None if selected==cid else 'unpaired_capture',
            alignment_source_records=pair_refs if selected==cid else [],
            alignment={'stm32_us':list(pair), 'esp32_us':[e0,e1]} if selected==cid else None,
            execution_outcome=run['execution_outcome'], capture_acceptance=run['capture_acceptance'])
        integral = Integral(state['samples'], c['gap_limit_us']) if state['samples'] else None
        if integral:
            base['maximum_gap_us'] = max(b-a for a,b in zip(integral.t,integral.t[1:]))
            base['sample_coverage_us'] = [integral.t[0],integral.t[-1]]
            traces[cid] = (integral, e0, e1)
        intervals = [('recorded_interval', e0, e1, {}, None)]
        workload_start, workload_end = e0, e1
        workload_reason = base['alignment_reason']
        if selected == cid and not workload_reason:
            try:
                bounds = workload_bounds(path, run['run_id'], pair)
                workload_start, workload_end = (map_boundary(t, *pair, e0, e1) for t in bounds)
            except ValueError as exc:
                workload_reason = str(exc)
        intervals.append(('whole_workload', workload_start, workload_end, {}, workload_reason))
        if selected == cid:
            for scope, start, end, timing, reason in phase_bounds(timings):
                try:
                    if reason:
                        raise ValueError(reason)
                    start = map_boundary(start, *pair, e0, e1)
                    end = map_boundary(end, *pair, e0, e1)
                except ValueError as exc:
                    reason = str(exc); start = end = None
                intervals.append((scope, start, end, timing, reason))
        for scope in ('tls_handshake','application_transfer'):
            if not any(i[0]==scope for i in intervals):
                intervals.append((scope,None,None,{},base['alignment_reason'] or 'phase_boundaries_not_recorded'))
        for scope, start, end, timing, reason in intervals:
            row = {**base, 'scope':scope, 'epoch_index':timing.get('epoch_index'), 'iteration_id':timing.get('iteration_id'),
                'handshake_id':timing.get('handshake_id'), 'phase_source_records':timing.get('source_records', []),
                'esp32_start_us':str(start) if start is not None else None,
                'esp32_end_us':str(end) if end is not None else None,
                'duration_s':float((end-start)/1_000_000) if type(start) in (int,Fraction) and type(end) in (int,Fraction) and end>start else None,'energy_j':None,'average_power_w':None,'bracketing_sample_indices':None,
                'validity':'unavailable','reason':state['reason'] or reason}
            if not row['reason']:
                try:
                    row.update(integral.interval(start,end), validity='valid')
                except ValueError as exc:
                    row['reason'] = str(exc)
            rows.append(row)
    return rows, traces


def summarise_energy(dataset, spec, selection):
    verify_source_inputs(dataset.metadata)
    if set(selection)-{'boundaries','trace_run'}:
        raise ValueError('unsupported_energy_selection')
    boundaries = selection.get('boundaries', {})
    known = {r['run_key'] for r in dataset.runs}
    if set(boundaries)-known or selection.get('trace_run', next(iter(known),None)) not in known:
        raise ValueError('unknown_energy_run_key')
    for boundary in boundaries.values():
        if set(boundary) != {'electrical_boundary','evidence_reference'} or any(not isinstance(v,str) or not v.strip() for v in boundary.values()):
            raise ValueError('electrical_boundary_requires_evidence_reference')
    frames, _ = summarise(dataset,spec)
    inventory = frames['inventory'].to_dict('records')
    rows, availability, inputs, trace_rows = [], [], [], []
    for run in inventory:
        context = {k:run[k] for k in ('run_key','run_id','condition','exclusion_reason')}
        root = result_path(run['input_path'])
        manifest_path = root/'manifest.json'
        try:
            manifest = json.loads(manifest_path.read_text())
            if manifest.get('final_index',{}).get('status') != 'finalized':
                raise ValueError('manifest_not_finalized')
            artifacts = [a for a in manifest.get('artifacts',[]) if a.get('role')=='stm32_result_stream']
            if not artifacts or artifacts[0].get('acquisition',{}).get('status')!='available':
                raise ValueError('energy_not_captured_or_not_applicable')
            a = artifacts[0]; path=root/'mqtt-reporting-raw.ndjson'
            if len(artifacts)!=1 or a.get('path')!=path.name or path.is_symlink() or not path.is_file() or digest(path)!=a.get('sha256'):
                raise ValueError('energy_source_hash_or_path_mismatch')
            inputs.extend(dict(path=str(p),sha256=digest(p)) for p in (manifest_path,path))
            observed, traces = analyse_run(path,run,[t for t in dataset.timings if t['run_key']==run['run_key']], boundaries.get(run['run_key'],{}))
            rows.extend({**r,**context} for r in observed)
            availability.append({**context,'status':'captured' if observed else 'energy_not_captured_or_not_applicable'})
            if selection.get('trace_run')==run['run_key']:
                for cid,(curve,e0,e1) in traces.items():
                    trace_rows.extend(dict(run_key=run['run_key'],capture_id=cid,sample_index=i,
                        timestamp_us=t,power_w=p,cumulative_j=j,segment=seg,e0_us=e0,e1_us=e1)
                        for i,(t,p,j,seg) in enumerate(zip(curve.t,curve.power,curve.j,curve.segments)))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            availability.append({**context,'status':'unavailable','reason':str(exc)})
    # Metric identities include policy and electrical boundary: never pool incompatible observations.
    observations, metrics = [], {}
    for row in rows:
        policy = json.dumps({'boundary':row['electrical_boundary'],'calibration':row['calibration'],'instrument_firmware_sha256':row['firmware_sha256']},sort_keys=True)
        policy_id = hashlib.sha256(policy.encode()).hexdigest()[:16]
        row['comparison_policy_id'] = policy_id
        for measure,unit in (('energy_j','J'),('average_power_w','W')):
            metric = row['scope']+'.'+measure+'.'+policy_id
            metrics[metric] = {'unit':unit}
            observations.append(dict(run_key=row['run_key'],run_id=row['run_id'],metric=metric,
                value_us=row[measure],unit=unit,capture_id=row['capture_id'],interval_id=row['interval_id'],
                scope=row['scope'],source_records=row['source_records'],source_sha256=row['source_sha256'],
                comparison_policy_id=policy_id,epoch_index=row['epoch_index'],iteration_id=row['iteration_id'],
                validity=row['validity'],reason=row['reason'],
                timing_policy_exclusion=None if row['electrical_boundary'] else 'electrical_boundary_unknown'))
    energy_frames,_ = summarise(replace(dataset,timings=tuple(observations)),spec,metrics=metrics)
    # A2's internal scalar slot is named value_us; energy exports carry explicit SI units.
    energy_frames['observations'] = energy_frames['observations'].rename(columns={'value_us':'value'})
    result = {'energy_intervals':pd.DataFrame(rows,dtype=object) if rows else pd.DataFrame(columns=['run_key','capture_id','scope','energy_j','reason']),
              'energy_availability':pd.DataFrame(availability,dtype=object),
              'energy_trace':pd.DataFrame(trace_rows,dtype=object) if trace_rows else pd.DataFrame(columns=['run_key','capture_id','timestamp_us','power_w','cumulative_j','segment'])}
    result.update({'energy_'+k:v for k,v in energy_frames.items() if k in ('distributions','differences','completeness','observations')})
    verify_source_inputs(dataset.metadata)
    if any(digest(i['path'])!=i['sha256'] for i in inputs):
        raise ValueError('energy_input_changed_during_analysis')
    return result,dict(version=VERSION,inputs=inputs,selection=selection,
        sources={p.name:digest(p) for p in (Path(__file__),Path(__file__).with_name('energy_evidence.py'),Path(__file__).with_name('timing_metrics.py'))},
        definitions=dict(integration='W trapezoids -> J once; linear cumulative-J interpolation within valid brackets; no extrapolation or gap bridging',
            affine='e=e0+(s-s0)*(e1-e0)/(s1-s0); rational microseconds',
            pairing='one STM32 experiment boundary and exactly one duration-compatible acquisition; no cross-run or multi-interval guessing',
            application_transfer='first requested payload byte to final payload byte, not request-to-last-byte',
            recorded_interval='ESP32 e0 to e1; remains distinct from device whole_workload',
            whole_workload='STM32 s0 to explicit workload_end_us when recorded; excludes the 20 ms tail guard; legacy captures use s1',
            comparison='A2 success-conditional summaries; unknown electrical boundary excluded; policy/scope strata separate; repeated intervals descriptive only',
            qualification='parser validity is not instrument accuracy or calibration qualification; physical boundary is operator-asserted with evidence reference'))
