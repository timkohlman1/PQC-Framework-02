import base64
import copy
import struct
import pytest
from framework.activity_trace import extract_activity

def records():
    h=dict(schema='1',clock='TIM2',origin_us=str(2**32),elapsed_us='100',events='2',bins='1',bin_us='10000',dropped='0',errors='0',saturated='0',clipped='0',encoding='le12_u8x2_base64')
    rows=[dict(marker='PQC_ACTIVITY_TRACE',context='activity_trace',fields=h)]
    for name,data in [('events',struct.pack('<IHHiIHHi',0,16386,1,0,100,32770,1,-2)),('spi',bytes([4,5]))]:
        rows.append(dict(marker='PQC_ACTIVITY_DATA',context='activity_trace',fields=dict(schema='1',stream=name,offset='0',base64=base64.b64encode(data).decode())))
    return rows

def test_activity_absent_and_valid():
    assert extract_activity([]) is None
    x=extract_activity(records()); assert x['event_complete'] and x['spi_complete']
    assert x['spans'][0]['start_us']==2**32 and x['spans'][0]['result']==-2

@pytest.mark.parametrize('case',range(12))
def test_activity_rejects_malformed_or_incomplete_stream(case):
    r=copy.deepcopy(records())
    if case==0: r.append(r[0])
    elif case==1: r.pop()
    elif case==2: r[1]['fields']['offset']='1'
    elif case==3: r[1]['fields']['base64']='!'
    elif case==4: r[0]['fields']['events']='129'
    elif case==5: r[0]['fields']['bin_us']='1'
    elif case==6: r[1]['context']='application'
    elif case==7: r[1]['fields']['stream']='other'
    elif case==8: r[0]['fields']['bins']='2'
    elif case==9: r[0]['fields']['elapsed_us']='90'
    elif case==10: r[1]['fields']['base64']=base64.b64encode(struct.pack('<IHHiIHHi',0,16386,1,0,100,32771,1,0)).decode()
    elif case==11: r[1]['fields']['base64']=base64.b64encode(struct.pack('<IHHiIHHi',0,16386,2,0,100,32770,2,0)).decode()
    with pytest.raises(ValueError): extract_activity(r)

@pytest.mark.parametrize('encoded,valid',[(b'\x80\x02\x00',True),(b'\x80\x00\x00',False),(b'\x80',False),(b'\xff\xff\x07\x00',False)])
def test_activity_v2_wide_counters(encoded,valid):
    r=records()
    for row in r: row['fields']['schema']='2'
    r[0]['fields'].update(encoding='le12_varuint16_base64',wire_clipped_bins='0')
    r[2]['fields']['base64']=base64.b64encode(encoded).decode()
    if valid: assert extract_activity(r)['spi_counts']==[(256,0)]
    else:
        with pytest.raises(ValueError): extract_activity(r)
