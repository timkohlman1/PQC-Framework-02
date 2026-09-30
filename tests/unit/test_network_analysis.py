"""A5 known-answer offline flow, lineage and matching tests."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
from framework.packet_analysis import Packet, write_analysis
from framework.network_analysis import (flow_observations, comparison_axis, packet_summary,
    validate_selection, tls_identity)
from framework.run_evidence import sha256_file


def selection():
    return dict(client_ip='10.0.0.2',server_ip='10.0.0.1',server_port=8883,
        evidence_reference='synthetic explicit STM32 client identity',window={'kind':'retained_flow'})


def packet(n, seq=1, payload=b'12345', client='10.0.0.2', port=8883):
    return Packet(n,float(n),60,60,client,'10.0.0.1',6,src_port=50000,dst_port=port,
                  tcp_seq=seq,tcp_flags=24,tcp_payload=payload)


def test_multiple_clients_reporting_and_unrelated_packets_do_not_change_metrics():
    workload=[packet(1),packet(2,seq=1),packet(3,seq=10),packet(4,seq=6,payload=b'1234')]
    expected, diag=flow_observations(workload,selection())
    # Health check and responder share the broker, reporting shares the client.
    mixed=workload+[packet(5,client='127.0.0.1'),packet(6,client='10.0.0.3'),packet(7,port=1886)]
    actual, detail=flow_observations(mixed,selection())
    assert actual==expected and detail==diag
    outgoing=actual[0]
    assert outgoing['wire_bytes']==240 and outgoing['tcp_payload_bytes']==19
    assert outgoing['overlap_bytes']==5 and outgoing['overlap_segments']==1
    assert outgoing['payload_segments']==4
    assert outgoing['tls_identity_status']=='unavailable'
    assert not any('payload'==k for row in detail for k in row)


def test_window_is_half_open_and_never_device_time():
    s=selection();s['window']=dict(kind='pcap_epoch',start=2,end=3,definition='selected packet window')
    rows,detail=flow_observations([packet(1),packet(2),packet(3)],s)
    assert rows[0]['packets']==1 and detail[0]['packet_number']==2
    s['window']['kind']='stm32'
    with pytest.raises(ValueError):validate_selection(s)


def test_reused_tuple_does_not_claim_retransmission_bytes():
    a,b=packet(1),packet(2);a.tcp_flags=b.tcp_flags=2
    rows,_=flow_observations([a,b],selection())
    assert rows[0]['overlap_bytes'] is None


def test_missing_decryption_does_not_prevent_serverhello_identity():
    # TLS 1.3 version and secp256r1 ServerHello key-share extension.
    ext=bytes.fromhex('002b0002030400330006001700020102')
    body=bytes.fromhex('0303')+bytes(32)+b'\0'+bytes.fromhex('130100')+len(ext).to_bytes(2,'big')+ext
    handshake=b'\2'+len(body).to_bytes(3,'big')+body
    payload=b'\x16\x03\x03'+len(handshake).to_bytes(2,'big')+handshake
    p=packet(1,payload=payload);p.src_ip,p.dst_ip=p.dst_ip,p.src_ip;p.src_port,p.dst_port=p.dst_port,p.src_port
    assert tls_identity([p],'10.0.0.1')==[dict(version_code=772,cipher_suite_code=4865,key_share_group_code=23)]
    p.tcp_payload=p.tcp_payload[:-1]
    assert tls_identity([p],'10.0.0.1')==[]


def config(**changes):
    return {'controls':{'network_configured':dict(enabled=True,rate_kbit=10000,rtt_ms=10,loss_percent=0,mtu=1500,**changes)}}


@pytest.mark.parametrize('axis,value',[('rate_kbit',5000),('rtt_ms',20),('loss_percent',1.5),('mtu',1200)])
def test_axes_and_units(axis,value):
    a=config();b=deepcopy(a);b['controls']['network_configured'][axis]=value
    assert comparison_axis([a],[b])==(axis,None)
    b['controls']['network_configured']['rtt_ms' if axis!='rtt_ms' else 'mtu']=33 if axis!='rtt_ms' else 1200
    assert comparison_axis([a],[b])==(None,'mixed_impairment')


def test_disabled_baseline_does_not_imply_zero_effective_rate_or_mtu():
    a=config();b=deepcopy(a);b['controls']['network_configured']['enabled']=False
    assert comparison_axis([a],[b])[0] is None


def test_stale_derived_analysis_is_rejected(tmp_path):
    fixture=Path(__file__).parents[1]/'fixtures/pcap/retransmission.pcap'
    p=tmp_path/'gateway-network-capture.pcap';p.write_bytes(fixture.read_bytes())
    m={'run':{'id':'fixture'},'final_index':{'status':'finalized'},'artifacts':[dict(role='packet_capture',path=p.name,sha256=sha256_file(p),acquisition={'status':'available'})]}
    (tmp_path/'manifest.json').write_text(json.dumps(m))
    write_analysis(tmp_path/'manifest.json',use_tshark=False)
    data,mode=packet_summary(tmp_path,m,[])
    assert mode=='verified_existing' and data['tcp']['packets']>0
    p.write_bytes(p.read_bytes()+b'x')
    with pytest.raises(ValueError,match='stale'):packet_summary(tmp_path,m,[])


def test_matching_retains_a2_TLS_controls_and_refuses_waivers():
    from framework.network_analysis import matched_comparisons
    reference={**config(), 'run_key':'a','condition':'base','exclusion_reason':None}
    treatment=deepcopy(reference);treatment.update(run_key='b',condition='slow')
    treatment['controls']['network_configured']['rate_kbit']=5000
    spec={'baseline':'base','treatment':['network_condition','controls.network_configured.rate_kbit']}
    selection_map={'a':selection(),'b':selection()}
    diff=dict(condition='slow',metric='tls_handshake',unit='us',reason=None,delta_median=5,percent_difference=10)
    def result():return matched_comparisons([reference,treatment],[diff],spec,selection_map)[0]
    assert result()['delta_median']==5 and result()['axis_unit']=='kbit/s'
    diff['reason']='conflicting_control:tls_kex'
    assert result()['delta_median'] is None
    diff['reason']=None;spec['treatment'].append('tls_kex')
    assert result()['reason']=='non_network_treatment'
    spec['treatment'].pop();spec['not_applicable']={'controls.tls.key_exchange_group':'waive'}
    assert result()['delta_median'] is None
    spec.pop('not_applicable');selection_map['b']['window']=dict(kind='pcap_epoch',start=1,end=2,definition='different')
    assert result()['reason']=='incompatible_window_definitions'


def test_network_doc_routes_and_metric_boundaries():
    root=Path(__file__).parents[2]
    text=(root/'docs/007_framework_architecture.md').read_text()
    assert 'DTR-A5-EVIDENCE' in text
    assert 'No key log or packet payload is exported' in text
    assert 'network_comparison.ipynb' in text
    assert 'network_spec' not in (root/'scripts/framework/timing_dataset_schema.py').read_text()


def test_tcp_sequence_spaces_are_independent_between_directions():
    a=packet(1,seq=1);b=packet(2,seq=2**32-20)
    b.src_ip,b.dst_ip=b.dst_ip,b.src_ip;b.src_port,b.dst_port=b.dst_port,b.src_port
    rows,_=flow_observations([a,b],selection())
    assert all(row['overlap_bytes']==0 for row in rows)
    c=packet(3,seq=2**32-10)
    rows,_=flow_observations([a,b,c],selection())
    assert rows[0]['overlap_bytes'] is None


def test_three_condition_hash_selection_does_not_invalidate_pairwise_axis():
    from framework.network_analysis import matched_comparisons
    rows = []
    for i, (name, rate) in enumerate([('base',100000),('slow',1024),('slower',256)]):
        r = config(); r.update(run_key=str(i), condition=name, network_condition=name, exclusion_reason=None)
        r['controls']['network_configured']['rate_kbit'] = rate
        rows.append(r)
    spec = {'baseline':'base', 'treatment':['network_condition','controls.network_configured.rate_kbit',
        *['controls.profile_hashes.network_condition:'+r['condition'] for r in rows]]}
    diff = dict(condition='slow',metric='bytes',reason=None,delta_median=5,percent_difference=10)
    answer = matched_comparisons(rows,[diff],spec,{r['run_key']:selection() for r in rows})[0]
    assert answer['reason'] is None and answer['delta_median'] == 5
    spec['treatment'].append('tls_auth')
    assert matched_comparisons(rows,[diff],spec,{r['run_key']:selection() for r in rows})[0]['reason'] == 'non_network_treatment'


def test_transport_comparison_requires_identical_network_and_keeps_a2_controls():
    from framework.network_analysis import matched_comparisons
    a = {**config(), 'run_key': 'a', 'condition': 'base', 'exclusion_reason': None}
    b = deepcopy(a); b.update(run_key='b', condition='tls')
    spec = {'baseline': 'base', 'evidence_policy': 'stm32_st67_transport',
            'treatment': ['tls_kex', 'controls.tls.mode']}
    diff = {'condition': 'tls', 'reason': None, 'delta_median': 2, 'percent_difference': 10}
    selections = {'a': selection(), 'b': selection()}
    assert matched_comparisons([a,b], [diff], spec, selections)[0]['reason'] is None
    diff['reason'] = 'unmatched_controls'
    assert matched_comparisons([a,b], [diff], spec, selections)[0]['reason'] == 'unmatched_controls'
    diff['reason'] = None
    b['controls']['network_configured']['rtt_ms'] = 20
    assert matched_comparisons([a,b], [diff], spec, selections)[0]['delta_median'] is None
