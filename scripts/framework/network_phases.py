"""Interpret one deferred network-startup trace without inferring missing phases."""
PHASES = ('module_init', 'wifi_init', 'lwip_init', 'wifi_scan', 'wifi_connect',
          'association_check', 'dhcp_wait')

def extract_network_phases(records):
    headers = [r for r in records if r['marker'] == 'PQC_NETWORK_PHASES']
    rows = [r for r in records if r['marker'] == 'PQC_NETWORK_PHASE']
    if not headers and not rows:
        return []  # Historical captures have no fabricated startup intervals.
    if len(headers) != 1 or len(rows) != len(PHASES):
        raise ValueError('incomplete_or_duplicate_network_trace')
    h = headers[0]['fields']
    expected = dict(schema='1', count=str(len(PHASES)), errors='0', clock='TIM2',
                    counter_hz='1000000', timestamp_origin='application_timebase_start')
    if headers[0]['context'] != 'network_phases' or any(h.get(k) != v for k, v in expected.items()):
        raise ValueError('invalid_network_trace_header')
    result = []
    for phase in PHASES:
        matches = [r for r in rows if r['fields'].get('phase') == phase]
        if len(matches) != 1:
            raise ValueError('missing_or_duplicate_network_phase')
        record = matches[0]; f = record['fields']
        if record['context'] != 'network_phases' or f.get('schema') != '1':
            raise ValueError('invalid_network_phase_schema')
        try:
            state, start, end, code = (int(f[k]) for k in ('state','start_us','end_us','result'))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError('invalid_network_phase_fields') from exc
        if state not in (0,1,2) or not (0 <= start < 2**64 and 0 <= end < 2**64 and -2**31 <= code < 2**31):
            raise ValueError('invalid_network_phase_state')
        if state == 2 and end < start or state == 0 and (start or end or code) or state == 1 and (end or code):
            raise ValueError('invalid_network_phase_bounds')
        result.append(dict(phase=phase, start_us=start if state else None,
            end_us=end if state==2 else None, result=code if state==2 else None,
            status=('not_attempted','incomplete','completed')[state],
            duration_us=end-start if state==2 else None, source_record=record['ref']))
    completed = [r for r in result if r['status']=='completed']
    if any(b['start_us'] < a['end_us'] for a,b in zip(completed,completed[1:])):
        raise ValueError('overlapping_network_phases')
    return result
