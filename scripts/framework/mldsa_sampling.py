"""Decode deferred outer ML-DSA signing-loop counts, linked to TLS events.

Counts are observed software-backend evidence. Historical/missing/truncated
records are unavailable, never inferred from signing time or treated as zero.
"""
from __future__ import annotations


def _uint(value, maximum=2**32-1):
    if not isinstance(value, str) or not value.isdecimal():
        raise ValueError('invalid_unsigned_count')
    number = int(value)
    if number > maximum:
        raise ValueError('count_out_of_range')
    return number


def extract_mldsa_sampling(records):
    groups = []
    for record in records:
        if record['marker'] == 'PQC_TLS_EVENT_BUFFER':
            groups.append([])
        if groups:
            groups[-1].append(record)
    rows = []
    for group in groups:
        buffer = group[0]['fields']
        headers = [r for r in group if r['marker'] == 'PQC_MLDSA_SAMPLING_BUFFER']
        samples = [r for r in group if r['marker'] == 'PQC_MLDSA_SAMPLING']
        signs = [r for r in group if r['marker'] == 'PQC_TLS_EVENT' and r['fields'].get('name') == 'mldsa65_sign']
        for event in signs:
            f = event['fields']
            row = dict(iteration=buffer.get('iteration'), handshake=buffer.get('handshake'),
                       event_sequence=f.get('sequence'), validity='unavailable', reason='',
                       attempts=None, rejected=None, accepted=None, aborted=None,
                       result=f.get('result'), start_us=f.get('start_us'), end_us=f.get('end_us'),
                       source_records=[event.get('ref', {})])
            try:
                if not headers:
                    raise ValueError('sampling_not_recorded')
                if len(headers) != 1:
                    raise ValueError('ambiguous_sampling_buffer')
                h = headers[0]['fields']
                if h.get('schema') != '1':
                    raise ValueError('unsupported_sampling_schema')
                if any(h.get(k) != buffer.get(k) for k in ('iteration', 'handshake')):
                    raise ValueError('sampling_context_mismatch')
                count = _uint(h.get('count')); capacity = _uint(h.get('capacity'))
                if _uint(h.get('dropped')) or count > capacity or len(samples) != count:
                    raise ValueError('sampling_buffer_incomplete')
                if [_uint(s['fields'].get('index')) for s in samples] != list(range(count)):
                    raise ValueError('sampling_index_mismatch')
                if any(buffer.get(k) != '0' for k in ('dropped', 'overflow', 'truncated', 'incomplete', 'invalid_sequence_count')):
                    raise ValueError('tls_hierarchy_incomplete')
                selected = [s for s in samples if s['fields'].get('event_sequence') == f.get('sequence')]
                if len(selected) != 1:
                    raise ValueError('expected_one_software_call_per_sign_event')
                s = selected[0]; v = s['fields']
                if v.get('schema') != '1' or v.get('backend') != 'wolfcrypt_software':
                    raise ValueError('unsupported_sampling_backend')
                counts = {k: _uint(v.get(k)) for k in ('attempts','rejected','accepted','aborted')}
                if counts['attempts'] != sum(counts[k] for k in ('rejected','accepted','aborted')):
                    raise ValueError('sampling_count_identity')
                if counts['accepted'] > 1 or counts['aborted'] > 1:
                    raise ValueError('invalid_terminal_candidate_count')
                if f.get('completed') != '1' or f.get('result_available') != '1' or v.get('result') != f.get('result'):
                    raise ValueError('signing_outcome_mismatch')
                result = int(v['result'])
                if result == 0 and (counts['accepted'] != 1 or counts['aborted'] != 0):
                    raise ValueError('successful_signing_count_identity')
                start, end = _uint(f.get('start_us'),2**64-1), _uint(f.get('end_us'),2**64-1)
                if end < start:
                    raise ValueError('nonmonotonic_signing_span')
                row.update(**counts, result=result, start_us=start, end_us=end,
                           duration_us=end-start, validity='valid', reason='observed',
                           source_records=[headers[0].get('ref', {}), s.get('ref', {}),event.get('ref', {})])
            except (ValueError,TypeError) as exc:
                row['reason'] = str(exc)
            rows.append(row)
    return rows
