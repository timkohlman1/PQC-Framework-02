"""Synthetic A4 fixtures; these are not experimental evidence."""
import json
import sys
from pathlib import Path

import pytest
ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "scripts", ROOT / "tests"):
    sys.path.insert(0, str(path))
from timing_dataset_support import make_run, tls_records, logical
from framework.timing_dataset import export_dataset
from framework.timing_dataset_loader import load_dataset
from framework.timing_metrics import decode_epochs
from framework.tls_analysis import decode_attribution, summarise_tls


def fixture(tmp_path, records=None):
    run = make_run(tmp_path / "run", records=records or tls_records(), application="tls_handshake_repeat")
    export_dataset(run_dirs=[run], output=tmp_path / "dataset")
    return run, load_dataset(tmp_path / "dataset")


def aggregate(name="sha256", total=40, count=2):
    return logical(f"PQC_TLS_PRIMITIVE name={name} count={count} total_us={total} min_us={total//count} max_us={total//count} first_start_us=1120 last_end_us=1180 elapsed_time_source=monotonic_us timing_source=dwt_cycles")


def decode(tmp_path, records):
    run, _ = fixture(tmp_path, records)
    epochs, errors = decode_epochs(run / "mqtt-reporting-raw.ndjson", "synthetic-0001")
    assert not errors
    return decode_attribution(epochs[0].records, json.loads((run / "resolved-case.json").read_text()))


def test_nested_evidence_and_aggregate_only(tmp_path):
    records = tls_records() + [logical("PQC_TLS_EVENT sequence=1 parent_sequence=0 level=3 depth=1 kind=protocol_phase name=certificate completed=1 result_available=1 result=0 start_us=1120 end_us=1200 elapsed_us=80"), aggregate()]
    records[1]["text"] = records[1]["text"].replace("count=1", "count=2")
    rows, coverage, issues = decode(tmp_path, records)
    assert [r["value_us"] for r in rows] == [150, 80, 40]
    assert rows[-1]["sequence"] is None and rows[-1]["count"] == 2
    assert all(r["operation"] != "total_crypto" for r in rows)
    assert next(c for c in coverage if c["operation"] == "rsa_sign")["status"] == "not_applicable"
    assert next(c for c in coverage if c["operation"] == "rsa_verify")["reason"] == "required_record_missing"


@pytest.mark.parametrize("old,new,reason", [
    ("overflow=0", "overflow=1", "event_buffer_overflow"),
    ("completed=1", "completed=0", "incomplete_span"),
    ("parent_sequence=-1", "parent_sequence=9", "invalid_parent_span"),
    ("schema=1", "schema=99", "unsupported_event_buffer_schema"),
    ("end_us=1250", "end_us=1100", "span_duration_mismatch"),
])
def test_bad_evidence_visible(tmp_path, old, new, reason):
    records = tls_records()
    for r in records:r["text"] = r["text"].replace(old,new)
    rows, _, issues = decode(tmp_path, records)
    assert rows[0]["value_us"] is None
    assert any(reason in i["code"] for i in issues)


def test_failed_stage_unknown_and_unexpected_sign(tmp_path):
    records = tls_records() + [aggregate("rsa_sign")]
    records[0]["text"] = records[0]["text"].replace("result=1", "result=-1")
    rows, coverage, issues = decode(tmp_path, records)
    assert next(c for c in coverage if c["operation"] == "rsa_verify")["reason"] == "stage_not_established"
    assert rows[-1]["reason"] == "unexpected_client_signing_in_server_mode"


def test_unequal_repetitions_equal_run_weight(tmp_path):
    runs=[]
    for name, durations in (("one",[100]),("three",[300,300,300])):
        epochs=[]
        for i,duration in enumerate(durations):
            records=tls_records(i, repeat=True)
            for r in records:
                r["text"]=r["text"].replace("1250",str(1100+duration)).replace("elapsed_us=150",f"elapsed_us={duration}")
            epochs.append(records)
        runs.append(make_run(tmp_path/name,run_id=name,epochs=epochs,application="tls_handshake_repeat"))
    export_dataset(run_dirs=runs,output=tmp_path/"dataset")
    frames,_=summarise_tls(load_dataset(tmp_path/"dataset"),{'conditions':{'base':{}},'baseline':'base','independent_runs':True,'resamples':100})
    stats=frames['tls_run_distributions'].iloc[0]
    assert stats['median']==200 and stats['n_runs']==2 and stats['n_observations']==2
    assert stats['median_ci_reason'] is None
    assert sorted(frames['tls_per_run']['observed_handshakes'])==[1,3]
    assert len(frames['tls_handshakes'])==4


def test_changed_raw_input_refused(tmp_path):
    run,dataset=fixture(tmp_path)
    with (run/'mqtt-reporting-raw.ndjson').open('a') as f:f.write('tamper')
    with pytest.raises(ValueError,match='consumed input changed'):
        summarise_tls(dataset,{'conditions':{'base':{}},'baseline':'base'})


def test_mutual_missing_sign_and_unknown_outcome(tmp_path):
    run,dataset=fixture(tmp_path,[logical('PQC_TLS_REPEAT_ITERATION schema=1 iteration=0 handshake=0 timing_source=TIM2_1MHz instrumentation_available=0',context='tls_handshake_repeat')])
    frames,_=summarise_tls(dataset,{'conditions':{'base':{}},'baseline':'base'})
    assert frames['tls_per_run'].iloc[0]['unknown_iterations']==1
    assert frames['tls_per_run'].iloc[0]['observed_handshakes']==0
    epochs,_=decode_epochs(run/'mqtt-reporting-raw.ndjson','synthetic-0001')
    snapshot=json.loads((run/'resolved-case.json').read_text())
    snapshot['effective_non_secret_parameters']['mqtt']['tls']['authentication']='mutual'
    _,coverage,_=decode_attribution(epochs[0].records,snapshot)
    assert next(c for c in coverage if c['operation']=='rsa_sign')['reason']=='stage_not_established'


def test_missing_controls_refuse_operation_comparison(tmp_path):
    _,dataset=fixture(tmp_path,tls_records()+[aggregate()])
    from dataclasses import replace
    first=dict(dataset.runs[0],tls_kex='base')
    second=dict(first,run_key='second',tls_kex='other')
    # Shared A2 matching gate, with synthetic per-run operation observations.
    from framework.timing_summary import summarise
    obs=[dict(run_key=r['run_key'],metric='sha256',validity='valid',reason=None,value_us=v,epoch_index=None,iteration_id=None) for r,v in ((first,10),(second,20))]
    frames,_=summarise(replace(dataset,runs=(first,second),timings=tuple(obs)),{'conditions':{'base':{'tls_kex':'base'},'other':{'tls_kex':'other'}},'baseline':'base','treatment':['tls_kex']},metrics={'sha256':{'unit':'us'}})
    assert frames['differences'].iloc[0]['delta_median'] is None
    assert 'unknown_control:' in frames['differences'].iloc[0]['reason']


def test_clock_provenance_and_invalid_frequency(tmp_path):
    from timing_dataset_support import rm2_records
    records=rm2_records()
    records[0]['text']=records[0]['text'].replace('counter_hz=1000000','counter_hz=999999')
    rows,_,issues=decode(tmp_path,records)
    assert rows[0]['value_us'] is None
    assert any('invalid_clock_provenance' in i['code'] for i in issues)
    assert rows[0]['clock_provenance']['counter_hz']=='999999'


def test_operation_totals_do_not_sum_nested_levels(tmp_path):
    records=tls_records(repeat=True)+[aggregate()]
    _,dataset=fixture(tmp_path,records)
    frames,_=summarise_tls(dataset,{'conditions':{'base':{}},'baseline':'base'})
    rows={r['metric']:r for r in frames['tls_operation_distributions'].to_dict('records')}
    assert rows['aggregate:sha256:elapsed']['median']==40
    assert rows['aggregate:sha256:count']['median']==2
    assert rows['aggregate:sha256:count']['unit']=='count'
    assert rows['invocation:handshake:elapsed']['median']==150
    assert not any('total_crypto' in k for k in rows)


def test_overflow_preserves_aggregate_and_zero(tmp_path):
    records=tls_records()+[aggregate(total=0)]
    records[1]['text']=records[1]['text'].replace('overflow=0','overflow=1')
    rows,_,_=decode(tmp_path,records)
    assert rows[0]['value_us'] is None
    assert rows[1]['value_us']==0 and rows[1]['validity']=='valid'


def test_mutual_required_sign_missing_on_success(tmp_path):
    run,_=fixture(tmp_path)
    epochs,_=decode_epochs(run/'mqtt-reporting-raw.ndjson','synthetic-0001')
    snapshot=json.loads((run/'resolved-case.json').read_text())
    snapshot['effective_non_secret_parameters']['mqtt']['tls']['authentication']='mutual'
    _,coverage,_=decode_attribution(epochs[0].records,snapshot)
    assert next(c for c in coverage if c['operation']=='rsa_sign')['reason']=='required_record_missing'


def test_missing_repeat_status_not_success_from_config(tmp_path):
    _,dataset=fixture(tmp_path)
    frames,_=summarise_tls(dataset,{'conditions':{'base':{}},'baseline':'base'})
    row=frames['tls_per_run'].iloc[0]
    assert row['unknown_handshakes']==1 and row['valid_handshakes']==0


def test_only_unavailable_inputs_still_export_headers(tmp_path):
    run=make_run(tmp_path/'run',failed=True)
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    frames,_=summarise_tls(load_dataset(tmp_path/'dataset'),{'conditions':{'base':{}},'baseline':'base'})
    assert frames['tls_attribution'].empty
    assert 'value_us' in frames['tls_attribution'].columns
    assert frames['tls_per_run'].iloc[0]['observed_handshakes']==0


@pytest.mark.parametrize("axis,dimension", [("tls_kex","kex"),("tls_auth","certificate"),("auth_mode","authentication")])
def test_bounded_profile_views(axis, dimension):
    import pandas as pd
    from framework.tls_analysis import bounded_views
    base=dict(tls_kex='p256',tls_auth='rsa',auth_mode='server',exclusion_reason=None)
    inventory=pd.DataFrame([dict(base,condition='base'),dict(base,condition='new',**{axis:'changed'})])
    diff=dict(condition='new',baseline='base',metric='op',unit='us',delta_median=10,percent_difference=20,reason=None,percent_reason=None)
    frames={k:pd.DataFrame([diff]) for k in ('tls_run_differences','tls_operation_differences')}
    bounded_views(frames,inventory)
    assert len(frames['tls_'+dimension+'_comparisons'])==2
    assert frames['tls_run_differences'].iloc[0]['delta_median']==10
    inventory.loc[1, next(k for k in ('tls_kex','tls_auth','auth_mode') if k!=axis)]='also_changed'
    frames={k:pd.DataFrame([diff]) for k in ('tls_run_differences','tls_operation_differences')}
    bounded_views(frames,inventory)
    assert frames['tls_run_differences'].iloc[0]['delta_median'] is None
    assert 'comparison_requires_one_tls_dimension' in frames['tls_run_differences'].iloc[0]['reason']
