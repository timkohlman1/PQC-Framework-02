"""Clock boundaries, single-run selection, and non-additive measured examples."""
from dataclasses import replace
import copy
import pytest
from framework.analysis_timelines import measured_rows, validate, publish
from framework.timing_dataset_loader import TimingDataset

KEY='a'*64
ITEM=dict(id='timeline-example',selection='example',run_key=KEY,kind='application',epoch_index=0,iteration_id=0,caption='Synthetic fixture')

def fixture():
    intervals={'mqtt_readiness':(10,20),'ttfb':(10,40),'ttlb':(10,90),'req_tfb':(30,40),'req_tlb':(30,90),'rtfb':(0,140),'rtlb':(0,190)}
    rows=[dict(run_key=KEY,epoch_index=0,iteration_id=0,metric=m,start_us=a,end_us=b,
        validity='valid',timing_policy_exclusion=None,reset_offset_us=100 if m in ('rtfb','rtlb') else None,
        clock_source='TIM2',counter_hz=1000000,source_records=[{'record':1}],source_sha256='b'*64)
        for m,(a,b) in intervals.items()]
    return TimingDataset((dict(run_key=KEY,execution_outcome='completed',selected_input_status='verified'),),tuple(rows),(),{})

def test_reset_bridge_aligns_endpoints_without_adding_independent_medians():
    rows=measured_rows(ITEM,fixture(),[])
    values={r['label']:(r['plot_start_us'],r['plot_end_us']) for r in rows}
    assert values['rtfb']==(0,140) and values['ttfb']==(110,140) and values['req_tfb']==(130,140)
    assert values['rtlb']==(0,190) and values['ttlb']==(110,190)

@pytest.mark.parametrize('change',['clock','bridge','endpoint','failed','duplicate'])
def test_ambiguous_or_incompatible_evidence_is_refused(change):
    d=fixture()
    if change=='clock':d.timings[0]['clock_source']='gateway'
    if change=='bridge':d.timings[-1]['reset_offset_us']=101
    if change=='endpoint':d.timings[-1]['end_us']=191
    if change=='failed':d.runs[0]['execution_outcome']='failed'
    if change=='duplicate':d=replace(d,timings=d.timings+(d.timings[0],))
    with pytest.raises(ValueError):measured_rows(ITEM,d,[])

def test_tls_nested_invocations_keep_original_intervals():
    base=dict(run_key=KEY,epoch_index=0,iteration_id=0,representation='invocation',validity='valid',clock_source='TIM2',counter_hz=1000000,source_records=[],source_sha256='b'*64)
    rows=[dict(base,operation='handshake',start_us=100,end_us=500,sequence=0,parent_sequence=-1,depth=0),
          dict(base,operation='certificate',start_us=200,end_us=400,sequence=1,parent_sequence=0,depth=1),
          dict(base,operation='ecdsa_verify',start_us=220,end_us=390,sequence=2,parent_sequence=1,depth=2)]
    result=measured_rows(dict(ITEM,kind='tls'),fixture(),rows)
    assert [(r['plot_start_us'],r['plot_end_us']) for r in result]==[(0,400),(100,300),(120,290)]
    assert result[-1]['parent_sequence']==1
    rows[-1]['end_us']=501
    with pytest.raises(ValueError):measured_rows(dict(ITEM,kind='tls'),fixture(),rows)

def test_plot_outputs_are_owned_and_keep_the_exact_intervals(tmp_path,monkeypatch):
    from framework import analysis_comparison
    monkeypatch.setattr(analysis_comparison,'dataset_for',lambda _:fixture())
    prepared=dict(specification={'presentation':{'timelines':[ITEM]}},selected={'example':(None,None)},analyses={'example':{'frames':{}}})
    figures=publish(tmp_path,prepared)
    assert len(figures)==2
    assert 'Broker' not in (tmp_path/'timeline-example.csv').read_text()
    assert all((tmp_path/(f['id']+'.'+suffix)).is_file() for f in figures for suffix in ('pdf','svg','png','tex'))
    assert 'Reset means operational wolfBoot entry' in figures[-1]['caption']


def test_explicit_unique_safe_ids_and_epoch_required():
    validate([ITEM])
    with pytest.raises(ValueError):validate([ITEM,ITEM])
    with pytest.raises(ValueError):validate([dict(ITEM,id='../outside')])
    with pytest.raises(ValueError):validate([dict(ITEM,epoch_index=True)])
