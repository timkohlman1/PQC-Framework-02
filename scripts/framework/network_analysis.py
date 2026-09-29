"""A5 retained transport observations. No capture, decryption or clock alignment.

Explicit endpoint selections are operator assertions, retained with their evidence
reference. They must not be inferred from a broker port shared by several clients.
"""
from __future__ import annotations

from dataclasses import replace
import ipaddress
import json
import math
from pathlib import Path

import pandas as pd

from framework.packet_analysis import (ANALYSER_VERSION, analyse_run, read_pcap,
    _connection_key, _reassemble)
from framework.timing_dataset import verify_source_inputs
from framework.timing_summary import digest, summarise, field

VERSION = '1.0.0'
AXES = {'rate_kbit': 'kbit/s', 'rtt_ms': 'ms', 'loss_percent': '% per direction', 'mtu': 'bytes'}
METRICS = {'wire_bytes': 'bytes', 'tcp_payload_bytes': 'bytes', 'packets': 'packets',
           'overlap_segments': 'segments', 'overlap_bytes': 'bytes',
           'fragment_packets': 'packets', 'payload_segments': 'segments'}
RAW = {'packet_capture': 'gateway-network-capture.pcap',
       'resolved_case_snapshot': 'resolved-case.json', 'run_provenance': 'run-provenance.json',
       'network_condition_record': 'gateway-network-degradation.log'}


def retained(root, manifest, role, inputs):
    """Fixed role/path allowlist; no credential or payload export."""
    items = [a for a in manifest.get('artifacts', []) if a.get('role') == role]
    if not items or items[0].get('acquisition', {}).get('status') != 'available':
        return None
    if len(items) != 1 or items[0].get('path') != RAW[role]:
        raise ValueError('ambiguous/unsupported retained ' + role)
    path = root / RAW[role]
    if path.is_symlink() or not path.is_file() or not items[0].get('sha256') or digest(path) != items[0]['sha256']:
        raise ValueError('retained input hash/path mismatch: ' + role)
    inputs.append(dict(path=str(path), sha256=digest(path), role=role))
    return path


def packet_summary(root, manifest, inputs):
    """Reuse current derived output only after checking output and every input."""
    output = root / 'analysis/packet_capture/packet_analysis.json'
    lineage = output.with_name('packet_analysis_lineage.json')
    if output.exists() or lineage.exists():
        if not output.is_file() or not lineage.is_file() or output.is_symlink() or lineage.is_symlink():
            raise ValueError('stale packet analysis: missing/unsafe lineage')
        data, seal = json.loads(output.read_text()), json.loads(lineage.read_text())
        if (seal.get('sha256') != digest(output) or data.get('analyser_version') != ANALYSER_VERSION
                or seal.get('named_inputs') != data.get('inputs')):
            raise ValueError('stale packet analysis: output/version mismatch')
        expected = {'manifest': root / 'manifest.json', 'packet_capture': root / RAW['packet_capture']}
        for a in manifest.get('artifacts', []):
            if a.get('role') in ('tls_key_log', 'stm32_result_stream') and a.get('acquisition', {}).get('status') == 'available':
                expected[a['role']] = root / a['path']
        if (root / 'resolved-case.json').is_file():
            expected['resolved_case'] = root / 'resolved-case.json'
        if set(data['inputs']) != set(expected):
            raise ValueError('stale packet analysis: input set mismatch')
        for name, path in expected.items():
            item = data['inputs'][name]
            if path.resolve().parent != root.resolve() or path.is_symlink() or item['path'] != path.name or not path.is_file() or digest(path) != item['sha256']:
                raise ValueError('stale packet analysis: input hash mismatch')
            inputs.append(dict(path=str(path), sha256=item['sha256'], role=name))
        inputs.extend(dict(path=str(p), sha256=digest(p), role='derived_packet_analysis') for p in (output, lineage))
        return data, 'verified_existing'
    # Existing local built-in path: no key-log contents or external tool needed.
    data = analyse_run(root / 'manifest.json', use_tshark=False)
    inputs.extend(dict(path=str(root / i['path']), sha256=i['sha256'], role=k) for k, i in data['inputs'].items())
    return data, 'recomputed_in_memory'


def validate_selection(selection):
    allowed = {'client_ip', 'server_ip', 'server_port', 'evidence_reference', 'window'}
    if set(selection) != allowed:
        raise ValueError('selection requires client_ip, server_ip, server_port, evidence_reference and window')
    for key in ('client_ip', 'server_ip'):
        if ipaddress.ip_address(selection[key]).version != 4:
            raise ValueError('only retained IPv4 TCP is supported')
    if selection['client_ip'] == selection['server_ip'] or type(selection['server_port']) is not int or not 1 <= selection['server_port'] <= 65535:
        raise ValueError('invalid workload endpoints')
    if not isinstance(selection['evidence_reference'], str) or not selection['evidence_reference'].strip():
        raise ValueError('workload identity requires an evidence reference')
    window = selection['window']
    if window == {'kind': 'retained_flow'}:
        return
    if set(window) != {'kind', 'start', 'end', 'definition'} or window['kind'] != 'pcap_epoch':
        raise ValueError('window must be retained_flow or a defined pcap_epoch interval')
    if not window['definition'] or any(type(window[k]) not in (int, float) or not math.isfinite(window[k]) for k in ('start', 'end')) or window['start'] >= window['end']:
        raise ValueError('invalid PCAP interval')


def tls_identity(packets, server):
    """Bounded plaintext ServerHello extraction; no certificates or secrets."""
    stream = _reassemble([(p.tcp_seq, p.tcp_payload, p.number) for p in packets
                          if p.src_ip == server and p.tcp_seq is not None and p.tcp_payload])
    handshake = bytearray()
    pos = 0
    while pos + 5 <= len(stream):
        typ, major = stream[pos], stream[pos+1]
        length = int.from_bytes(stream[pos+3:pos+5], 'big')
        if major != 3 or length > 18432 or pos+5+length > len(stream):
            break
        if typ == 22:
            handshake.extend(stream[pos+5:pos+5+length])
        pos += 5+length
    identities = []
    pos = 0
    while pos+4 <= len(handshake):
        typ = handshake[pos]; size = int.from_bytes(handshake[pos+1:pos+4], 'big')
        body = handshake[pos+4:pos+4+size]; pos += 4+size
        if len(body) != size or typ != 2 or len(body) < 38:
            continue
        # HelloRetryRequest selects a requested group, not a negotiated identity.
        if body[2:34].hex() == 'cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c':
            continue
        cursor = 35 + body[34]
        if cursor+5 > len(body):
            continue
        cipher = int.from_bytes(body[cursor:cursor+2], 'big')
        extlen = int.from_bytes(body[cursor+3:cursor+5], 'big'); cursor += 5
        end = cursor+extlen
        if end != len(body):
            continue
        version = int.from_bytes(body[:2], 'big'); group = None
        valid = True
        while cursor+4 <= end:
            kind = int.from_bytes(body[cursor:cursor+2], 'big'); length = int.from_bytes(body[cursor+2:cursor+4], 'big')
            value = body[cursor+4:cursor+4+length]; cursor += 4+length
            if cursor > end:
                valid = False; break
            if kind == 43 and length == 2: version = int.from_bytes(value, 'big')
            if kind == 51 and length >= 4: group = int.from_bytes(value[:2], 'big')
        if valid and cursor == end:
            identities.append(dict(version_code=version, cipher_suite_code=cipher, key_share_group_code=group))
    return identities


def flow_observations(packets, selection):
    """One 4-tuple/window, directions separate. Inclusive recorded PCAP bytes."""
    validate_selection(selection)
    client, server, port = (selection[k] for k in ('client_ip', 'server_ip', 'server_port'))
    window = selection['window']
    groups = {}
    for p in packets:
        if window['kind'] == 'pcap_epoch' and not window['start'] <= p.timestamp < window['end']:
            continue
        direction = ('client_to_server' if (p.src_ip, p.dst_ip, p.dst_port) == (client, server, port)
                     else 'server_to_client' if (p.src_ip, p.dst_ip, p.src_port) == (server, client, port) else None)
        if direction and _connection_key(p):
            groups.setdefault(_connection_key(p), []).append((p, direction))
    rows, diagnostics = [], []
    for key, members in sorted(groups.items()):
        flow_id = '|'.join(f'{ip}:{p}' for ip, p in key)
        identities = tls_identity([p for p, _ in members], server)
        reused = sum(bool(p.tcp_flags & 2 and not p.tcp_flags & 16) for p, _ in members) > 1
        for direction in ('client_to_server', 'server_to_client'):
            selected = [p for p, d in members if d == direction]
            seqs = [p.tcp_seq for p in selected if p.tcp_seq is not None]
            wrapped = bool(seqs and max(seqs)-min(seqs) > 2**31)
            intervals = []; overlap_total = overlaps = 0
            for p in selected:
                length = len(p.tcp_payload); overlap = 0
                if length and p.tcp_seq is not None:
                    start, end = p.tcp_seq, p.tcp_seq+length
                    overlap = sum(max(0, min(end, b)-max(start, a)) for a,b in intervals)
                    merged = []
                    for a,b in sorted(intervals+[(start,end)]):
                        if merged and a <= merged[-1][1]: merged[-1] = (merged[-1][0], max(b,merged[-1][1]))
                        else: merged.append((a,b))
                    intervals = merged
                overlap_total += overlap; overlaps += bool(overlap)
                diagnostics.append(dict(flow_id=flow_id, direction=direction, packet_number=p.number,
                    pcap_epoch_seconds=p.timestamp, wire_bytes=p.wire_len, captured_bytes=p.captured_len,
                    tcp_payload_bytes=length, overlap_bytes=overlap, tcp_flags=p.tcp_flags,
                    fragment_offset=p.ip_fragment_offset, more_fragments=p.ip_more_fragments))
            rows.append(dict(flow_id=flow_id, direction=direction, window=window,
                first_packet=min((p.timestamp for p in selected), default=None), last_packet=max((p.timestamp for p in selected), default=None),
                packets=len(selected), wire_bytes=sum(p.wire_len for p in selected),
                tcp_payload_bytes=sum(len(p.tcp_payload) for p in selected),
                payload_segments=sum(bool(p.tcp_payload) for p in selected),
                overlap_segments=None if reused or wrapped else overlaps, overlap_bytes=None if reused or wrapped else overlap_total,
                overlap_reason='sequence_wrap_unsupported' if wrapped else 'multiple_SYN_or_tuple_reuse' if reused else 'sequence_overlap_indicator_not_cause',
                fragment_packets=sum(p.ip_more_fragments or bool(p.ip_fragment_offset) for p in selected),
                fragmentation_scope='first_fragments_with_TCP_header; later fragments unassigned',
                segmentation='captured_TCP_payload_segments; not application_message_segmentation',
                tls_identities=identities, tls_identity_status='observed_ServerHello' if identities else 'unavailable',
                certificate_identity_status='unavailable_without_supported_decryption',
                capture_truncated=any(p.captured_len < p.wire_len for p in selected)))
    return rows, diagnostics


def comparison_axis(reference, treatment):
    """Never call a disabled/enabled or mixed-condition change one-factor."""
    if not reference or not treatment:
        return None, 'missing_condition'
    configs = [r.get('controls', {}).get('network_configured', {}) for r in reference+treatment]
    if any(any(type(c.get(k)) not in (int,float) or not math.isfinite(c[k]) for k in AXES) or type(c.get('enabled')) is not bool for c in configs):
        return None, 'unknown_network_properties'
    if len({c['enabled'] for c in configs}) != 1:
        return None, 'enabled_boundary_changes_multiple_effective_properties'
    if not configs[0]['enabled']:
        return None, 'disabled_network_values_are_not_effective_conditions'
    if any(c['rate_kbit'] <= 0 or c['rtt_ms'] < 0 or not 0 <= c['loss_percent'] <= 100 or not 576 <= c['mtu'] <= 9000 for c in configs):
        return None, 'invalid_network_units_or_values'
    a, b = configs[:len(reference)], configs[len(reference):]
    if len({json.dumps(c,sort_keys=True) for c in a}) != 1 or len({json.dumps(c,sort_keys=True) for c in b}) != 1:
        return None, 'mixed_conditions_within_group'
    changed = [k for k in AXES if a[0][k] != b[0][k]]
    return (changed[0], None) if len(changed) == 1 else (None, 'mixed_impairment' if len(changed)>1 else 'no_network_change')


def summarise_network(dataset, spec, selections):
    verify_source_inputs(dataset.metadata)
    if set(selections) - {r['run_key'] for r in dataset.runs}:
        raise ValueError('network selections contain unknown run keys')
    base_frames, _ = summarise(dataset, spec)
    inventory = base_frames['inventory'].to_dict('records')
    rows, diagnostics, availability, inputs = [], [], [], []
    for run in inventory:
        context = dict(run_key=run['run_key'], run_id=run['run_id'], condition=run['condition'], exclusion_reason=run['exclusion_reason'])
        root = Path(run['input_path'])
        manifest = json.loads((root/'manifest.json').read_text())
        if manifest.get('final_index', {}).get('status') != 'finalized':
            availability.append({**context, 'status': 'manifest_not_finalized'}); continue
        pcap = retained(root, manifest, 'packet_capture', inputs)
        if pcap is None:
            availability.append({**context, 'status': 'missing_pcap'}); continue
        if run['run_key'] not in selections:
            availability.append({**context, 'status': 'workload_identity_not_selected'}); continue
        selection = selections[run['run_key']]; validate_selection(selection)
        snapshot_path = retained(root, manifest, 'resolved_case_snapshot', inputs)
        snapshot = json.loads(snapshot_path.read_text()) if snapshot_path else {}
        mqtt = snapshot.get('effective_non_secret_parameters', {}).get('mqtt', {})
        broker = mqtt.get('broker', {}); host = mqtt.get('orchestration', {}).get('host')
        if broker.get('port') != selection['server_port'] or host != selection['server_ip']:
            raise ValueError('selected broker differs from retained resolved workload endpoint')
        summary, reuse = packet_summary(root, manifest, inputs)
        _, packets = read_pcap(pcap)
        observed, detail = flow_observations(packets, selection)
        network = run.get('controls', {}).get('network_configured', {})
        provenance_path = retained(root, manifest, 'run_provenance', inputs)
        provenance = json.loads(provenance_path.read_text()).get('records', {}) if provenance_path else {}
        recorded = provenance.get('network_degradation', {})
        from framework.network_degradation import network_degradation_config, _verified_state
        state_path = retained(root, manifest, 'network_condition_record', inputs)
        applied, applied_reason = None, 'no_retained_independent_state'
        if state_path and network.get('enabled'):
            config = network_degradation_config({'experiment': snapshot.get('effective_non_secret_parameters', {})})
            valid, applied_reason = _verified_state(state_path.read_text(), config)
            if valid:
                applied = {k: network.get(k) for k in AXES}
                applied_reason = 'independently_recorded_state; not achieved network performance'
        status = recorded.get('status')
        availability.append({**context, 'status': 'available' if observed else 'no_selected_packets',
            'decryption_status': summary['tls_keylog_analysis']['status'] if 'tls_key_log' in summary['inputs'] else 'missing_keylog', 'derived_status': reuse,
            'configured': network, 'recorded_apply_status': status,
            'verified_applied': applied, 'verified_applied_reason': applied_reason,
            'observed_rate_rtt_loss_mtu': None,
            'observed_properties_reason': 'packet_counts_do_not_measure_impairment_parameters',
            'identity_basis': 'operator_assertion', 'selection': selection,
            'capture_point': snapshot.get('effective_non_secret_parameters', {}).get('network', {}).get('packet_capture', {}).get('interface', 'unknown')})
        rows.extend({**context, **row} for row in observed)
        diagnostics.extend({**context, **row} for row in detail)
    # Timing and completion reuse A2. Comparison acceptance retains all A2
    # controls and additionally constrains the treatment to a single network axis.
    transport = []
    for run in inventory:
        selected = [r for r in rows if r['run_key'] == run['run_key']]
        for direction in ('client_to_server', 'server_to_client'):
            members = [r for r in selected if r['direction'] == direction]
            for metric in METRICS:
                values = [r[metric] for r in members]
                value = sum(values) if values and all(v is not None for v in values) else None
                transport.append(dict(run_key=run['run_key'], run_id=run['run_id'],
                    metric=direction+'.'+metric, value_us=value, epoch_index=None, iteration_id=None,
                    validity='valid' if value is not None else 'unavailable', reason=None if value is not None else 'no_qualified_flow',
                    timing_policy_exclusion=None))
    transport_frames, _ = summarise(replace(dataset, timings=tuple(transport)), spec,
        metrics={d+'.'+m:{'unit':u} for d in ('client_to_server','server_to_client') for m,u in METRICS.items()})
    comparisons = matched_comparisons(inventory, base_frames['differences'].to_dict('records') + transport_frames['differences'].to_dict('records'), spec, selections)
    frames = {
        'network_flows': pd.DataFrame(rows, columns=list(rows[0]) if rows else ['run_key','flow_id','direction','packets']),
        'network_packets': pd.DataFrame(diagnostics, columns=list(diagnostics[0]) if diagnostics else ['run_key','flow_id','packet_number']),
        'network_availability': pd.DataFrame(availability),
        'network_comparisons': pd.DataFrame(comparisons, columns=list(comparisons[0]) if comparisons else ['condition','axis','reason']),
    }
    frames['network_transport_distributions'] = transport_frames['distributions']
    frames['network_transport_completeness'] = transport_frames['completeness']
    verify_source_inputs(dataset.metadata)
    for item in inputs:
        if digest(item['path']) != item['sha256']:
            raise ValueError('network input changed during analysis')
    return frames, dict(version=VERSION, inputs=inputs, selections=selections,
        sources={p.name:digest(p) for p in (Path(__file__),Path(__file__).with_name('packet_analysis.py'),Path(__file__).with_name('network_degradation.py'))},
        definitions=dict(byte_layer='PCAP original frame length (linktype dependent); captured TCP payload bytes',
            inclusion='both directions exported separately; includes repeated transmissions; no dedup across capture interfaces',
            interval='retained 4-tuple lifetime or explicit [start,end) gateway PCAP epoch window; never TLS handshake bytes',
            clock='gateway PCAP only; no STM32 alignment',
            overlap='union of previously captured sequence ranges; indicator only, no root-cause verdict; no sequence-wrap decoding',
            inference='per-flow descriptive transport observations; A2 run outcomes and success-conditional timings remain separate'))


def matched_comparisons(inventory, differences, spec, selections):
    """Apply network restrictions in addition to A2's control-matching result."""
    comparisons = []
    for difference in differences:
        reference = [r for r in inventory if r['condition']==spec['baseline'] and not r['exclusion_reason']]
        treatment = [r for r in inventory if r['condition']==difference['condition'] and not r['exclusion_reason']]
        axis, reason = comparison_axis(reference, treatment)
        allowed = {'network_condition', 'controls.profile_hashes.network_condition',
                   'controls.network_configured.'+str(axis)}
        allowed |= {'controls.profile_hashes.network_condition:' + r['network_condition']
                    for r in reference+treatment if isinstance(r.get('network_condition'), str)}
        if set(spec.get('treatment', [])) - allowed:
            reason = reason or 'non_network_treatment'
        if any(k.startswith(('controls.network_configured', 'controls.tls', 'controls.mqtt')) or k in ('tls_kex','tls_auth','auth_mode','application','payload_bytes','chunk_bytes') for k in spec.get('not_applicable', {})):
            reason = reason or 'required_network_TLS_workload_controls_waived'
        window_definitions = []
        for run in reference+treatment:
            selection = selections.get(run['run_key'])
            if selection is None:
                reason = reason or 'missing_flow_selection'; continue
            window = selection['window']
            window_definitions.append((window['kind'], window.get('definition')))
        if len(set(window_definitions)) != 1:
            reason = reason or 'incompatible_window_definitions'
        reason = reason or difference['reason']
        comparisons.append({**difference, 'axis': axis, 'axis_unit': AXES.get(axis),
            'baseline_axis_value': field(reference[0], 'controls.network_configured.'+axis) if axis and reference else None,
            'axis_value': field(treatment[0], 'controls.network_configured.'+axis) if axis and treatment else None,
            'reason': reason, 'delta_median': None if reason else difference['delta_median'],
            'percent_difference': None if reason else difference['percent_difference'],
            'percent_reason': reason or difference.get('percent_reason')})
    return comparisons


def plot_network(frames, output):
    import matplotlib.pyplot as plt
    comparisons = frames['network_comparisons'].to_dict('records')
    fig, axes = plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    for (axis,unit), ax in zip(AXES.items(),axes.flat):
        rows = [r for r in comparisons if r['axis']==axis and r['unit']=='us' and not r['reason']]
        for metric in sorted({r['metric'] for r in rows}):
            points = sorted((r['axis_value'],r['delta_median']) for r in rows if r['metric']==metric)
            ax.scatter([p[0] for p in points],[p[1] for p in points],label=metric)
        ax.set_xlabel(axis+' ('+unit+')');ax.set_ylabel('Matched median timing difference (µs)')
        if rows: ax.legend(fontsize=7)
        else: ax.text(.5,.5,'No supported one-factor comparison',ha='center',transform=ax.transAxes)
    fig.savefig(output/'network-condition-response.png',dpi=140);plt.close(fig)

    fig, axes = plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    for (axis,unit), ax in zip(AXES.items(),axes.flat):
        rows = [r for r in comparisons if r['axis']==axis and r['metric'].endswith('.tcp_payload_bytes') and not r['reason']]
        for metric in sorted({r['metric'] for r in rows}):
            points = sorted((r['axis_value'],r['delta_median']) for r in rows if r['metric']==metric)
            ax.scatter([p[0] for p in points],[p[1] for p in points],label=metric)
        ax.set_xlabel(axis+' ('+unit+')');ax.set_ylabel('Matched TCP payload difference (bytes)')
        if rows: ax.legend(fontsize=7)
        else: ax.text(.5,.5,'No supported transport comparison',ha='center',transform=ax.transAxes)
    fig.savefig(output/'network-transport-response.png',dpi=140);plt.close(fig)
