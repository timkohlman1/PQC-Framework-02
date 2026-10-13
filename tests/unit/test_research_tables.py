import pytest
from framework.research_tables import handshake_window, render, validate, bar, classification, ranking_positions, collect


def packets():
    def row(n,source,types='',length=100,mqtt=''):
        return dict(zip(('frame.number','frame.time_epoch','ip.src','tcp.srcport','tcp.stream','tcp.len','tls.handshake.type','mqtt.msgtype'),
                        (str(n),str(n/1000),source,'8883' if source=='server' else '1234','0',str(length),types,mqtt)))
    return [row(1,'client','1'),row(2,'server','2'),row(3,'server','11,15,20'),row(4,'server'),row(5,'client','20'),row(6,'client',mqtt='1')]


def test_window_excludes_mqtt_and_includes_retransmitted_payload():
    result=handshake_window(packets(),'client',8883)
    assert result['packet_ms']==pytest.approx(4)
    assert result['a_ms']==pytest.approx(1)
    assert result['b_ms']==pytest.approx(3)
    assert result['cbytes']==200 and result['sbytes']==300 and result['traffic_bytes']==500
    assert result['client_finished_packet']==5


@pytest.mark.parametrize('mutation',[lambda r:r.append(dict(r[0],**{'tcp.stream':'1'})),
    lambda r:r.pop(4),lambda r:r[4].update({'mqtt.msgtype':'1'}),
    lambda r:r.append(dict(r[1],**{'frame.number':'7'}))])
def test_ambiguous_or_incomplete_windows_are_not_estimated(mutation):
    rows=packets();mutation(rows)
    with pytest.raises(ValueError):handshake_window(rows,'client',8883)


def test_ranking_excludes_unavailable_from_rank_and_escapes_labels():
    item=dict(id='rank',kind='ranking',metric='total_ms',caption='Test',entries=[dict(label='a',reason='missing')])
    rows=[dict(label='missing',total_ms=None),dict(label='A_B',total_ms=20),dict(label='fast',total_ms=10)]
    text=render(item,rows)
    assert text.index('fast')<text.index('A\\_B')<text.index('missing')
    assert r'\resizebox{\linewidth}{!}' in text
    assert r'\begin{tikzpicture}' in text and r'\begin{longtable}' not in text
    assert all(label in text for label in ('Post-quantum','Pre-quantum','Hybrid'))
    assert ranking_positions(rows,'total_ms')[0][1]==0
    assert ranking_positions(rows,'total_ms')[-1][1]==4


def test_network_scale_is_per_column_and_missing_is_not_zero():
    item=dict(id='net',kind='network',caption='Test',scenarios=['base','loss'],entries=[dict(label=l,scenario=s,reason='pending') for l in ['a','b'] for s in ['base','loss']])
    validate([item])
    rows=[dict(label='a',scenario='base',total_ms=10),dict(label='b',scenario='base',total_ms=20),dict(label='a',scenario='loss',total_ms=100),dict(label='b',scenario='loss',total_ms=None)]
    text=render(item,rows)
    assert text.count('rectangle (18.000,1.3)')==2 and 'rectangle (9.000,1.3)' in text
    assert 'Lvl & Algorithm' in text and 'Legend:' in text
    assert r'\textemdash{}' in text
    item['entries'].pop()
    with pytest.raises(ValueError,match='every network cell'):validate([item])


def test_negative_or_nonfinite_metric_rejected():
    for n in (-1,float('nan'),float('inf')):
        with pytest.raises(ValueError):bar(n,10)


def test_levels_are_grouped_and_hybrid_components_are_distinguished():
    rows=[dict(label='strong',algorithm='ML_KEM_1024'),dict(label='classic',algorithm='secp256r1'),dict(label='hybrid',algorithm='SecP256r1MLKEM768')]
    for row in rows:row.update(total_ms=20,packet_ms=11,a_ms=1,b_ms=10,cbytes=100,sbytes=200)
    text=render(dict(id='summary',kind='summary',caption='Test'),rows)
    assert text.index('classic')<text.index('hybrid')<text.index('strong')
    assert r'1 & \textbf{classic}' in text and '3 & hybrid' in text and '5 & strong' in text
    assert r'\shortstack' not in text
    assert text.count('rectangle (46,1.5)')==3
    assert 'Latency median (ms)' in text and 'Target (ms)' not in text
    assert '{11.00}' in text and '{20.00}' not in text
    assert 'ClientHello $\\rightarrow$ client Finished' in text
    assert 'fill=researchOrange' not in text
    assert classification(rows[2])==(3,'hybrid','kex',128)


def test_unknown_algorithm_and_nonpositive_log_rank_rejected():
    item=dict(id='test',kind='summary',caption='Test',entries=[dict(label='x',algorithm='invented',reason='none')])
    with pytest.raises(ValueError,match='unknown research algorithm'):validate([item])
    with pytest.raises(ValueError,match='positive'):ranking_positions([dict(label='zero',total_ms=0)],'total_ms')


def test_summary_aggregates_complete_latency_before_median(monkeypatch):
    # Median(a + b) is 13; median(a) + median(b) would incorrectly give 12.
    samples=[dict(packet_ms=a+b,a_ms=a,b_ms=b,cbytes=100,sbytes=200,traffic_bytes=300)
             for a,b in ((1,100),(10,1),(11,2))]
    monkeypatch.setattr('framework.research_tables.decode',lambda run,endpoint:samples[run['run_key']])
    selection=dict(id='tls',network={n:{} for n in range(3)})
    prepared=dict(specification=dict(selections=[selection]),analyses=dict(tls=dict(
        normalized_comparison=dict(conditions={'case':{}}),
        frames=dict(inventory=dict(rows=[dict(condition='case',run_key=n) for n in range(3)])))))
    item=dict(id='summary',kind='summary',caption='Test',entries=[dict(label='Test',selection='tls',condition='case')])
    tables,observations=collect(prepared,[item]);row=tables['summary'][0]
    assert row['packet_ms']==13 and row['a_ms']==10 and row['b_ms']==2
    assert row['n_packets_runs']==3 and len(observations)==3
    assert row['total_ms'] is None
    assert '{13.00}' in render(item,tables['summary'])


def test_network_coverage_keeps_missing_capture_denominator():
    import pandas as pd
    from framework.research_tables import render_coverage
    inventory=[dict(condition='case',case_id='A',run_key='ok',execution_outcome='completed',capture_acceptance='accepted'),
               dict(condition='case',case_id='A',run_key='bad',execution_outcome='failed',capture_acceptance='rejected')]
    attempts=pd.DataFrame([dict(case_id='A',run_key=k,row_kind=kind) for k,kind in
        [('ok','capture'),('bad','capture'),('absent','campaign_attempt_without_capture')]])
    prepared=dict(specification=dict(selections=[dict(id='tls')]),selected={'tls':(attempts,attempts)},analyses=dict(tls=dict(
        normalized_comparison=dict(conditions={'case':{}}),frames=dict(inventory=dict(rows=inventory),
        tls_run_distributions=dict(rows=[dict(condition='case',metric='tls_handshake',median=1200,q1=1100,q3=1300,p95=1400,n_runs=1)])))))
    item=dict(id='net',kind='network',caption='Test',scenarios=['base'],entries=[dict(label='A',selection='tls',condition='case',scenario='base')])
    tables,_=collect(prepared,[item]);r=tables['net'][0]
    assert (r['current_attempts'],r['captured_attempts'],r['no_capture_attempts'])==(3,2,1)
    assert (r['completed_attempts'],r['failed_attempts'],r['accepted_captures'])==(1,1,1)
    assert r['p95_ms']==1.4 and r['total_ms']==1.2
    assert '1/3 [1]' in render_coverage(item,tables['net'])
