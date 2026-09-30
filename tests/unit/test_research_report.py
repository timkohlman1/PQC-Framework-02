"""Synthetic A8 selection, arithmetic, privacy and missing-evidence contracts."""
import copy
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
for path in (ROOT/'scripts',ROOT/'tests',ROOT/'tests/unit'):
    sys.path.insert(0,str(path))
from framework.research_report import (budget_checks, coverage, project, scalar, latex, specification,
    dependency, verify_dependencies, analyse, SUMMARY_COLUMNS)
from framework.timing_summary import summarise
from framework.timing_dataset import export_dataset
from framework.timing_dataset_loader import load_dataset
from timing_dataset_support import make_run, logical, reseal
from test_timing_summary import data, spec, row


def test_evidence_equivalence_is_explicit_and_never_promotes_simulation():
    d=data()
    for i,r in enumerate(d.runs):
        r['evidence_class']='stm32_st67_classical_tls_e2e' if i<2 else 'stm32_st67_pqc_hybrid_tls_e2e'
    f,_=summarise(d,spec())
    assert 'conflicting_control:evidence_class' in row(f,'differences','treatment')['reason']
    s={**spec(),'evidence_policy':'stm32_st67_tls'}
    f,_=summarise(d,s)
    assert row(f,'differences','treatment')['delta_median']==20
    assert {r['evidence_class'] for r in f['inventory'].to_dict('records')}=={'stm32_st67_classical_tls_e2e','stm32_st67_pqc_hybrid_tls_e2e'}
    for forbidden in ('fake','host_tls','stm32_st67_plaintext_e2e',None):
        d.runs[2]['evidence_class']=forbidden
        f,_=summarise(d,s)
        assert row(f,'differences','treatment')['delta_median'] is None


def test_projection_retains_counts_and_does_not_export_nested_raw_data():
    d=data(); d.runs[0]['build_references']={'private_key':'DO_NOT_EXPORT'}
    f,_=summarise(d,spec())
    values,deltas,inventory,outcomes=project({'id':'test','security_domain':'key_establishment'},f)
    r=next(r for r in values if r['condition']=='baseline' and r['metric']=='tls_handshake')
    assert (r['value'],r['n_runs'],r['n_observations'])==(5,2,2)
    assert 'DO_NOT_EXPORT' not in json.dumps([values,deltas,inventory,outcomes])
    assert next(r for r in deltas if r['metric']=='tls_handshake')['delta']==20


def test_budget_never_sums_builds_or_passes_missing_evidence():
    budgets=[dict(analysis='a',condition='c',table='resource_distributions',metric='ram',unit='bytes',limit=100)]
    assert budget_checks(budgets,[])[0]['status']=='not_assessed'
    sample={k:v for k,v in budgets[0].items() if k!='limit'};sample['value']=80
    r=budget_checks(budgets,[sample])[0]
    assert r['headroom']==20 and r['status']=='within_budget'
    assert budget_checks(budgets,[sample,sample])[0]['status']=='not_assessed'
    sample['unit']='KiB'
    assert budget_checks(budgets,[sample])[0]['status']=='not_assessed'


def test_all_twenty_thesis_tables_remain_visible_without_evidence():
    result=coverage([],[],[],[],{})
    assert len({r['section'] for r in result})==20
    assert all(r['status']=='incomplete' for r in result)
    assert any(r['metric']=='disjoint_total_crypto' and not r['implemented_analysis'] for r in result)


def test_safe_scalar_and_latex_escaping(tmp_path):
    with pytest.raises(ValueError):scalar({'private_key':'secret'})
    for value in ('-----BEGIN PRIVATE KEY-----','CLIENT_RANDOM abc','password=secret'):
        with pytest.raises(ValueError):scalar(value)
    assert '/home/' not in scalar('missing:/home/user/private/path')
    path=tmp_path/'fragment.tex'
    latex(path,[dict(condition='a_&%',metric='x#',value=0,unit='us',n_runs=1,n_observations=1)])
    assert r'a\_\&\%' in path.read_text() and ' & 0 &' in path.read_text()


def test_missing_dependency_and_symlinks_are_frozen(tmp_path):
    p=tmp_path/'later';item=dependency(p);verify_dependencies([item]);p.write_text('new')
    with pytest.raises(ValueError,match='changed'):verify_dependencies([item])
    q=tmp_path/'alias';q.symlink_to(p)
    with pytest.raises(ValueError,match='symlink'):dependency(q)


def test_throughput_uses_payload_interval_and_not_request_or_host_time(tmp_path):
    run=make_run(tmp_path/'run'); export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    item=dict(dataset=str(tmp_path/'dataset'),spec={'conditions':{'base':{}},'baseline':'base'},domains=['timing'])
    _,frames,_,_=analyse(item)
    r=frames['application_distributions'].iloc[0]
    assert r['median']==40000  # 20 bytes / (1400 - 900) us
    assert r['unit']=='bytes/s'


def test_report_spec_rejects_unknown_and_arbitrary_notebooks(tmp_path):
    p=tmp_path/'spec.json';p.write_text(json.dumps({'version':1,'analyses':[{'id':'x'}],'notebooks':['/tmp/unsafe.ipynb']}))
    with pytest.raises(ValueError,match='notebook'):specification(p)


def test_baremetal_cycles_repetitions_and_invalid_failure(tmp_path):
    from test_baremetal_benchmark_summary import records
    from framework.research_extensions import summarise_baremetal
    sample=[logical(r['text'],context='baremetal_benchmark') for r in records()]
    run=make_run(tmp_path/'run',application='baremetal_benchmark',records=sample)
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    frames,_=summarise_baremetal(load_dataset(tmp_path/'dataset'),{'conditions':{'base':{}},'baseline':'base'})
    assert len(frames['baremetal_samples'])==76
    assert frames['baremetal_samples'].cycles.isna().sum()==6
    assert len(frames['baremetal_distributions'])==7
    assert set(frames['baremetal_distributions']['median'])=={105.5}
    assert set(frames['baremetal_distributions']['n_runs'])=={1}


def test_ota_delivery_and_bank_markers_do_not_prove_final_identity(tmp_path):
    from framework.research_extensions import summarise_ota
    from framework.run_evidence import register_artifact
    run=make_run(tmp_path/'run')
    p=run/'uart.log';p.write_text('PQC_OTA_APP phase=request_accepted active_bank=1 inactive_bank=2 flags=0\nPQC_OTA_APP phase=transfer_complete app_received=123\nPQC_OTA_APP phase=activation_reset active_bank=1\nPQC_OTA_BOOT phase=candidate_first_boot active_bank=2\nPQC_OTA_APP phase=confirmed active_bank=2 confirmed=1\n')
    prov=run/'run-provenance.json';obj=json.loads(prov.read_text());obj['records']['ota']={'requested':True,'delivery':{'return_code':0,'duration_seconds':2.5},'plan':'do-not-open-current-plan.json'}
    prov.write_text(json.dumps(obj))
    m=json.loads((run/'manifest.json').read_text())
    register_artifact(m,result_dir=run,role='diagnostic_uart',path=p,stage='synthetic',tool=__name__)
    (run/'manifest.json').write_text(json.dumps(m));reseal(run)
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    frames,meta=summarise_ota(load_dataset(tmp_path/'dataset'),{'conditions':{'base':{}},'baseline':'base'})
    r=frames['ota_outcomes'].iloc[0]
    assert r['delivery_outcome']=='completed' and r['confirmation_observed']
    assert r['transition_outcome']=='unconfirmed' and r['duration_ms'] is None
    assert all(v is None for v in frames['ota_stages']['duration_ms'])
    assert meta['inputs']


def test_current_source_commit_and_dirty_state_come_from_recorded_provenance(tmp_path):
    run=make_run(tmp_path/'run')
    p=run/'run-provenance.json';obj=json.loads(p.read_text())
    obj['records']['source']={'git_commit':'a'*40,'git_dirty':True,'source_state_sha256':'b'*64}
    p.write_text(json.dumps(obj));reseal(run)
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    row=load_dataset(tmp_path/'dataset').runs[0]
    assert row['source_commit']=='a'*40
    assert row['controls']['source']=={'git_dirty':True,'state_identity':'b'*64}


def test_dirty_source_states_cannot_be_matched_by_commit_alone():
    d=data()
    for i,run in enumerate(d.runs):run['controls']['source']={'git_dirty':True,'state_identity':'a' if i<2 else 'b'}
    f,_=summarise(d,spec())
    assert 'conflicting_control:controls.source.state_identity' in row(f,'differences','treatment')['reason']


def test_single_baremetal_repetition_has_no_sample_standard_deviation():
    from test_baremetal_benchmark_summary import records,summary
    data=records()
    parsed=[json.loads(r['text']) for r in data]
    selected=[r for r in parsed if r.get('type')=='benchmark_provenance' or r.get('type')=='complete' or r.get('iteration')==0]
    selected[0]['iterations']=1;selected[-1]['records']=13
    result=summary.summarize([{'context':'baremetal_benchmark','text':json.dumps(r)} for r in selected],expected_repetitions=1)
    assert all(r['n']==1 and r['stdev_cycles'] is None for r in result['statistics'])


def test_research_documentation_retains_gaps_and_rebuild_contract():
    text=(ROOT/'docs/007_framework_architecture.md').read_text().split('## Frozen research reports (Analysis Request A8)',1)[1]
    for required in ('--rebuild','--verify','source.git_commit','stm32_st67_tls','not_assessed',
                     'unconfirmed','same valid run/epoch/iteration','0700','RQ1–RQ6','longtable'):
        assert required in text


def test_runtime_repetition_inherits_only_verified_matching_preparation_source(tmp_path):
    prep=make_run(tmp_path/'results/preparations/build')
    p=prep/'run-provenance.json';obj=json.loads(p.read_text());obj['records']['source']={'git_commit':'a'*40,'git_dirty':False}
    p.write_text(json.dumps(obj));reseal(prep)
    run=make_run(tmp_path/'results/runs/one')
    p=run/'run-provenance.json';obj=json.loads(p.read_text());obj['records'].pop('source')
    obj['records']['preparation']={'manifest':str(prep/'manifest.json'),'verified':False,'firmware_sha256':'d'*64}
    p.write_text(json.dumps(obj));reseal(run)
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    data=load_dataset(tmp_path/'dataset',verify_inputs=True)
    assert data.runs[0]['source_commit']=='a'*40
    assert data.runs[0]['preparation_verified'] is False  # Preserve the original recorded flag.
    assert data.runs[0]['controls']['source']['state_identity']=='a'*40
    assert data.runs[0]['selected_input_status']=='verified'
    assert any(a['role']=='preparation_manifest' for a in data.metadata['inputs'][0]['artifacts'])
    p=prep/'run-provenance.json';obj=json.loads(p.read_text());obj['records']['firmware']['sha256']='b'*64
    p.write_text(json.dumps(obj));reseal(prep)
    with pytest.raises(ValueError,match='changed'):load_dataset(tmp_path/'dataset',verify_inputs=True)
    export_dataset(run_dirs=[run],output=tmp_path/'mismatched')
    row=load_dataset(tmp_path/'mismatched').runs[0]
    assert row['source_commit'] is None and row['selected_input_status']=='verified'
    assert 'linked_preparation_source_unavailable_or_invalid' in row['inventory_reasons']


def test_runtime_only_uses_compact_preparation_verdict_before_capture(tmp_path,monkeypatch):
    import experiment
    from argparse import Namespace
    prep=tmp_path/'prep';prep.mkdir()
    manifest=prep/'manifest.json'
    manifest.write_text(json.dumps({'run':{'id':'prepared','return_code':0},'execution_outcome':{'status':'completed','result':'preparation_passed'}}))
    (prep/'run-provenance.json').write_text(json.dumps({'records':{'firmware':{'sha256':'a'*64}}}))
    result=tmp_path/'runtime';result.mkdir()
    updates=[]
    monkeypatch.setattr(experiment,'load_experiment_bundle',lambda p:{})
    monkeypatch.setattr(experiment,'_is_st67_mqtt_e2e',lambda b:True)
    monkeypatch.setattr(experiment,'create_result_folder',lambda *a:(result,{'run_id':'runtime'}))
    monkeypatch.setattr(experiment,'_report_experiment_start',lambda *a:None)
    monkeypatch.setattr(experiment,'repo_root_from_experiment_path',lambda p:tmp_path)
    monkeypatch.setattr(experiment,'update_manifest',lambda p,v:updates.append(v))
    def stop(**kwargs):raise RuntimeError('test_stops_before_hardware')
    monkeypatch.setattr(experiment,'_execute_mqtt_e2e_uart_capture',stop)
    args=Namespace(profile_preparation_manifest=manifest,experiment='synthetic',results_dir=result,skip_hardware_reset=True,uart_duration_seconds=1)
    with pytest.raises(RuntimeError,match='test_stops_before_hardware'):experiment._run_runtime_only_measurement(args)
    assert updates[0]['profile_preparation_reference']['result']=='preparation_passed'
