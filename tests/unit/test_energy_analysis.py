"""Synthetic mathematical and retained-format fixtures; not instrument qualification."""
import json
from pathlib import Path
import sys
from fractions import Fraction
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from timing_dataset_support import make_run, reseal, logical, rm2_records
from test_energy_capture import _energy_capture, CAPTURE
from framework.energy_analysis import Integral, map_boundary, acquisitions, alignment, summarise_energy
from framework.timing_dataset import export_dataset
from framework.timing_dataset_loader import load_dataset


def energy_run(tmp_path, *, pairs=True, extra=None, mutations=None, timestamps=None):
    records=rm2_records()
    if pairs:
        records.append(logical('PQC_ENERGY_BOUNDARY scope=experiment s0_us=0 s1_us=3000 valid=1 clock=TIM2 counter_hz=1000000 timestamp_convention=before_gpio_write',context='energy_boundary'))
    run=make_run(tmp_path,records=records)
    path=run/'mqtt-reporting-raw.ndjson'
    with path.open('a') as f:
        f.write(''.join(_energy_capture(e0=4_000_000,e1=4_003_000,
            timestamps=timestamps or list(range(4_000_000,4_003_001,100)),mutations=mutations)))
        if extra: f.write(''.join(extra))
    reseal(run)
    return run


def dataset_for(tmp_path, **kwargs):
    run=energy_run(tmp_path/'run',**kwargs)
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    return run,load_dataset(tmp_path/'dataset')


def test_constant_load_offset_drift_and_unit_conversion():
    samples=[(t,5,.4,2) for t in range(100_000,1_102_001,1000)]
    curve=Integral(samples,1000)
    start=map_boundary(500,0,1000,100_000,1_102_000)
    assert start==601_000
    row=curve.interval(100_000,1_102_000)
    assert row['energy_j']==pytest.approx(2.004)
    assert row['duration_s']==1.002
    assert row['average_power_w']==pytest.approx(2)
    assert curve.interval(start,1_102_000)['energy_j']==pytest.approx(1.002)
    assert map_boundary(2**60+1,2**60,2**60+3,2**60,2**60+4)==2**60+Fraction(4,3)


def test_cumulative_boundary_interpolation_and_zero():
    curve=Integral([(0,1,0,0),(1000,1,2,2),(2000,1,2,2)],1000)
    assert curve.interval(500,1500)['energy_j']==pytest.approx(.0015)
    assert curve.interval(500,1500)['bracketing_sample_indices']==[[0,1],[1,2]]
    assert Integral([(0,1,0,0),(1000,1,0,0)],1000).interval(0,1000)['energy_j']==0


@pytest.mark.parametrize('start,end,reason',[(-1,100,'coverage'),(0,3001,'coverage'),(100,2500,'gap'),(1500,2500,'gap'),(0,0,'nonpositive')])
def test_no_extrapolation_or_gap_bridging(start,end,reason):
    curve=Integral([(0,1,1,1),(1000,1,1,1),(3000,1,1,1)],1000)
    with pytest.raises(ValueError,match=reason):curve.interval(start,end)


@pytest.mark.parametrize('args',[(0,0,0,0,1),(0,0,1,2,1),(2,0,1,0,1),(True,0,1,0,1)])
def test_malformed_clock_pairs(args):
    with pytest.raises(ValueError):map_boundary(*args)


def test_total_phases_identity_and_boundary_policy(tmp_path):
    run,ds=dataset_for(tmp_path)
    key=ds.runs[0]['run_key']
    spec={'conditions':{'baseline':{}},'baseline':'baseline'}
    selection={'trace_run':key,'boundaries':{key:{'electrical_boundary':'synthetic supply','evidence_reference':'synthetic test'}}}
    before={p:p.read_bytes() for p in run.iterdir() if p.is_file()}
    frames,lineage=summarise_energy(ds,spec,selection)
    rows=frames['energy_intervals'].to_dict('records')
    assert {r['scope'] for r in rows}=={'recorded_interval','whole_workload','tls_handshake','application_transfer'}
    expected={'recorded_interval':.0015,'whole_workload':.0015,'tls_handshake':.000075,'application_transfer':.00025}
    for r in rows:
        assert r['validity']=='valid',r
        assert r['energy_j']==pytest.approx(expected[r['scope']])
        assert r['average_power_w']==pytest.approx(.5)
        assert r['interval_id']==key+':'+CAPTURE
    assert len(frames['energy_trace'])==31
    assert 'value_us' not in frames['energy_observations']
    assert set(frames['energy_observations']['unit'])=={'J','W'}
    assert set(frames['energy_observations']['capture_id'])=={CAPTURE}
    assert lineage['inputs']
    assert all(p.read_bytes()==data for p,data in before.items())
    unknown,_=summarise_energy(ds,spec,{})
    assert not unknown['energy_observations']['exclusion_reason'].isna().any()
    assert set(unknown['energy_distributions']['n_observations'])=={0}


def test_missing_pair_keeps_instrument_total(tmp_path):
    _,ds=dataset_for(tmp_path,pairs=False)
    frames,_=summarise_energy(ds,{'conditions':{'b':{}},'baseline':'b'},{})
    rows={r['scope']:r for r in frames['energy_intervals'].to_dict('records')}
    assert rows['recorded_interval']['energy_j']==pytest.approx(.0015)
    assert rows['whole_workload']['energy_j'] is None
    assert rows['tls_handshake']['reason']


def test_multiple_captures_never_cross_join(tmp_path):
    extra=_energy_capture('1111111111111111',4_000_000,4_003_000,timestamps=list(range(4_000_000,4_003_001,100)))
    run,ds=dataset_for(tmp_path,extra=extra)
    states=acquisitions(run/'mqtt-reporting-raw.ndjson')
    assert len(states)==2
    assert alignment(run/'mqtt-reporting-raw.ndjson',ds.runs[0]['run_id'],states)[0] is None
    frames,_=summarise_energy(ds,{'conditions':{'b':{}},'baseline':'b'},{})
    rows=frames['energy_intervals'].to_dict('records')
    assert sum(r['validity']=='valid' for r in rows)==2
    assert all(r['reason'] for r in rows if r['scope']!='recorded_interval')


def test_capture_valid_tail_is_not_extrapolated(tmp_path):
    _,ds=dataset_for(tmp_path,timestamps=list(range(4_000_000,4_002_901,100)))
    frames,_=summarise_energy(ds,{'conditions':{'b':{}},'baseline':'b'},{})
    rows={r['scope']:r for r in frames['energy_intervals'].to_dict('records')}
    assert rows['recorded_interval']['acquisition_valid']
    assert rows['recorded_interval']['duration_s']==.003
    assert rows['recorded_interval']['reason']=='outside_sample_coverage'
    assert rows['application_transfer']['validity']=='valid'


@pytest.mark.parametrize('mutation',[{'sample_gaps':1},{'logical_sha256':'0'*64},{'schema':2},{'calibration_id':'unknown'},{'e0_us':'malformed'}])
def test_invalid_acquisition_does_not_invalidate_timings(tmp_path,mutation):
    _,ds=dataset_for(tmp_path,mutations=mutation)
    assert any(t['validity']=='valid' for t in ds.timings)
    frames,_=summarise_energy(ds,{'conditions':{'b':{}},'baseline':'b'},{})
    assert set(frames['energy_intervals']['validity'])=={'unavailable'}


def test_input_tamper_detected(tmp_path):
    run,ds=dataset_for(tmp_path)
    with (run/'mqtt-reporting-raw.ndjson').open('a') as f:f.write('\n')
    with pytest.raises(ValueError):summarise_energy(ds,{'conditions':{'b':{}},'baseline':'b'},{})


def test_multiple_stm32_pairs_and_other_run_never_pair(tmp_path):
    from timing_dataset_support import wire
    run,ds=dataset_for(tmp_path)
    path=run/'mqtt-reporting-raw.ndjson'
    marker=logical('PQC_ENERGY_BOUNDARY scope=experiment s0_us=0 s1_us=3000 valid=1 clock=TIM2 counter_hz=1000000 timestamp_convention=before_gpio_write',context='energy_boundary')
    with path.open('a') as f:f.write(wire(ds.runs[0]['run_id'],[[marker]]))
    states=acquisitions(path)
    assert alignment(path,ds.runs[0]['run_id'],states)[2]=='expected_one_stm32_interval'
    assert alignment(path,'different-run',states)[0] is None


def test_policy_strata_prevent_pooling(tmp_path):
    first=energy_run(tmp_path/'one')
    second=energy_run(tmp_path/'two')
    # Give the independent synthetic run its own identity before sealing.
    for name in ('manifest.json','mqtt-reporting-raw.ndjson'):
        p=second/name;p.write_text(p.read_text().replace('synthetic-0001','synthetic-0002'))
    reseal(second)
    export_dataset(run_dirs=[first,second],output=tmp_path/'dataset')
    ds=load_dataset(tmp_path/'dataset')
    selection={'boundaries':{row['run_key']:{'electrical_boundary':str(i),'evidence_reference':'test'} for i,row in enumerate(ds.runs)}}
    frames,_=summarise_energy(ds,{'conditions':{'b':{}},'baseline':'b'},selection)
    rows=frames['energy_distributions'].to_dict('records')
    assert len(rows)==16
    assert all(row['n_observations']==1 for row in rows)
    assert len(set(frames['energy_intervals']['comparison_policy_id']))==2


def test_failed_and_absent_runs_remain_visible(tmp_path):
    run=make_run(tmp_path/'failed',failed=True)
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    ds=load_dataset(tmp_path/'dataset')
    frames,_=summarise_energy(ds,{'conditions':{'b':{}},'baseline':'b'},{})
    assert len(frames['energy_availability'])==1
    assert frames['energy_intervals'].empty


def test_a6_documentation_routes_to_canonical_methods():
    architecture=(ROOT/'docs/007_framework_architecture.md').read_text()
    for token in ('DTR-A6-EVIDENCE','--energy-spec','energy_comparison.ipynb',
                  'outside_sample_coverage','2000000','physical acquisition qualification'):
        assert token in architecture
    assert '#offline-workload-and-bounded-phase-energy-analysis-request-a6' in (ROOT/'README.md').read_text()
