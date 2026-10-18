"""Decode bounded host-side activity evidence; no inferred radio or idle states."""
import base64
import binascii
import struct

CODES = {1: 'chip_enable', 2: 'ready_wait', 3: 'ready_received', 4: 'ready_guard', 5: 'connect_wait', 6: 'connecting_received', 7: 'connected_received', 8: 'connected_guard', 9: 'link_up', 10: 'dhcp_start', 11: 'ipv4_available', 12: 'tcpip_init', 13: 'power_mode', 14: 'disconnect_received', 15: 'connection_reason', 16: 'chip_reset_assert', 17: 'netif_startup_guard', 100: 'at_other', 101: 'at_at', 102: 'at_cwnetmode', 103: 'at_get_clock', 104: 'at_set_clock', 105: 'at_gmr', 106: 'at_iorst', 107: 'at_slwkio', 108: 'at_pwr', 109: 'at_cwantenable', 110: 'at_cwant', 111: 'at_cwmode', 112: 'at_cwautoconn', 113: 'at_cwcountry', 114: 'at_slwkdtim', 115: 'at_cipstamac', 116: 'at_cipapmac', 117: 'at_cwjap', 118: 'at_cwjaps', 119: 'at_cwreconncfg', 120: 'at_cwstate', 121: 'at_get_ap_dtim', 122: 'at_sysram', 123: 'at_sysstore', 124: 'at_cwlap', 125: 'at_cwlapopt', 126: 'at_cwqap', 127: 'at_wps', 128: 'at_efuse', 129: 'at_vbat', 130: 'at_cmd', 131: 'at_fs'}

def extract_activity(records):
    headers=[r for r in records if r['marker']=='PQC_ACTIVITY_TRACE']
    rows=[r for r in records if r['marker']=='PQC_ACTIVITY_DATA']
    if not headers and not rows: return None
    if len(headers)!=1: raise ValueError('activity_header_count')
    h=headers[0]['fields']
    version=h.get('schema')
    if version not in ('1','2') or any(r['context']!='activity_trace' or r['fields'].get('schema')!=version for r in headers+rows):
        raise ValueError('activity_schema')
    if h.get('clock')!='TIM2' or h.get('encoding')!=('le12_u8x2_base64' if version=='1' else 'le12_varuint16_base64'): raise ValueError('activity_encoding')
    try:
        values={k:int(h[k]) for k in ('origin_us','elapsed_us','events','bins','bin_us','dropped','errors','saturated','clipped')}
    except (ValueError, KeyError, TypeError) as exc: raise ValueError('activity_header_fields') from exc
    if version=='2':
        try: values['wire_clipped_bins']=int(h['wire_clipped_bins'])
        except (KeyError,TypeError,ValueError) as exc: raise ValueError('activity_wire_clipping') from exc
    else: values['wire_clipped_bins']=0
    v=values
    if not (0<=v['origin_us']<2**64 and 0<=v['elapsed_us']<2**32 and 0<=v['events']<=128
            and 1<=v['bins']<=1024 and v['bin_us']==10000 and all(v[k]>=0 for k in ('dropped','errors','saturated','clipped'))):
        raise ValueError('activity_header_bounds')
    if v['wire_clipped_bins']<0 or v['bins']+v['wire_clipped_bins']!=min(1024,v['elapsed_us']//10000+1): raise ValueError('activity_bin_coverage')
    streams={'events':bytearray(),'spi':bytearray()}
    for row in rows:
        f=row['fields']; stream=f.get('stream')
        if stream not in streams: raise ValueError('activity_stream')
        try:
            offset=int(f['offset']); data=base64.b64decode(f['base64'],validate=True)
        except (KeyError,ValueError,TypeError,binascii.Error) as exc: raise ValueError('activity_chunk') from exc
        if offset!=len(streams[stream]) or not 0<len(data)<=384: raise ValueError('activity_chunk_order')
        streams[stream].extend(data)
    if len(streams['events'])!=v['events']*12: raise ValueError('activity_stream_length')
    if version=='1':
        if len(streams['spi'])!=v['bins']*2: raise ValueError('activity_stream_length')
        counts=list(struct.iter_unpack('BB',streams['spi']))
    else:
        vals=[];value=0;shift=0
        for b in streams['spi']:
            value|=(b&127)<<shift
            if value>65535 or shift>14: raise ValueError('activity_varint_range')
            if b&128: shift+=7
            else:
                if shift and b==0: raise ValueError('activity_varint_noncanonical')
                vals.append(value);value=0;shift=0
        if shift or len(vals)!=v['bins']*2: raise ValueError('activity_varint_length')
        counts=list(zip(vals[::2],vals[1::2]))
    events=[]; opened={}; spans=[]; previous=0
    for index,(dt,tag,token,value) in enumerate(struct.iter_unpack('<IHHi',streams['events']),1):
        kind,code=tag>>14,tag&16383
        if code not in CODES or kind>2 or not previous<=dt<=v['elapsed_us']: raise ValueError('activity_event')
        previous=dt
        event=dict(index=index,time_us=v['origin_us']+dt,elapsed_us=dt,code=code,name=CODES[code],kind=kind,token=token,value=value)
        if kind==0:
            if token: raise ValueError('activity_instant_token')
        elif kind==1:
            if token!=index: raise ValueError('activity_begin_token')
            opened[token]=event
        else:
            start=opened.pop(token,None)
            if start is None or start['code']!=code: raise ValueError('activity_end_token')
            spans.append(dict(name=CODES[code],code=code,start_us=start['time_us'],end_us=event['time_us'],value=start['value'],result=value,token=token))
        events.append(event)
    return dict(**v, events_decoded=events,spans=spans,unfinished=list(opened.values()),
        schema=int(version),spi_counts=counts,
        event_complete=not (v['dropped'] or v['errors'] or opened),
        spi_complete=not (v['errors'] or v['saturated'] or v['clipped'] or v['wire_clipped_bins'] or v['elapsed_us']>=10240000))
