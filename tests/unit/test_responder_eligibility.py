"""Retire affected delivery measurements without modifying raw captures."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
from timing_dataset_support import make_run, reseal
from framework.timing_dataset import export_dataset
from framework.timing_dataset_loader import load_dataset
from framework.timing_summary import summarise


def test_legacy_delivery_is_excluded_but_capture_and_readiness_remain(tmp_path):
    run=make_run(tmp_path/'run')
    manifest=run/'manifest.json'; data=json.loads(manifest.read_text())
    data['artifacts']=[a for a in data['artifacts'] if a['role']!='mqtt_publisher_log']
    manifest.write_text(json.dumps(data)); reseal(run)
    out=tmp_path/'dataset'; export_dataset(run_dirs=[run],output=out)
    dataset=load_dataset(out)
    assert dataset.runs[0]['selected_input_status']=='verified'
    frames,_=summarise(dataset,{'conditions':{'one':{}},'baseline':'one'})
    samples=frames['observations'].to_dict('records')
    delivery=[r for r in samples if r['metric']=='ttlb']
    assert delivery and delivery[0]['exclusion_reason']=='superseded_delivery_responder_startup_confound'
    assert next(r for r in samples if r['metric']=='mqtt_readiness')['exclusion_reason'] is None


def test_current_responder_log_is_a_hash_verified_analysis_input(tmp_path):
    from framework.timing_dataset import DatasetError
    import pytest
    run=make_run(tmp_path/'run'); out=tmp_path/'dataset'
    export_dataset(run_dirs=[run],output=out)
    dataset=load_dataset(out)
    assert dataset.runs[0]['controls']['mqtt']['responder_contract']=='preconnected_loopback_mosquitto_v1'
    log=run/'mqtt-publisher.log'; log.chmod(0o600); log.write_text('changed fixture')
    with pytest.raises(DatasetError): load_dataset(out,verify_inputs=True)


def test_compact_loss_recipe_cannot_restore_retired_delivery_values():
    from test_thesis_tables import loss_frame
    from framework.thesis_tables import metric
    rows=loss_frame()
    rows['application']='mqtt_ready_metrics_2'
    assert metric(rows,'completion')['n']==0
    assert metric(rows,'loss_handshake')['n']>0
    from framework.mqtt_responder import CONTRACT
    rows['control__mqtt__responder_contract']=CONTRACT
    assert metric(rows,'completion')['n']>0


def test_legacy_workload_energy_is_retired_but_handshake_energy_is_retained(tmp_path):
    from test_energy_analysis import dataset_for
    from dataclasses import replace
    from framework.energy_analysis import summarise_energy
    _,dataset=dataset_for(tmp_path)
    run=dict(dataset.runs[0]);run['controls']={**run['controls'],'mqtt':{**run['controls']['mqtt'],'responder_contract':'legacy_or_unverified_on_request'}}
    dataset=replace(dataset,runs=(run,))
    frames,_=summarise_energy(dataset,{'conditions':{'one':{}},'baseline':'one'},
        {'boundaries':{run['run_key']:{'electrical_boundary':'synthetic supply','evidence_reference':'test fixture'}}})
    rows=frames['energy_observations'].to_dict('records')
    whole=[r for r in rows if r['metric'].startswith('whole_workload.')]
    assert whole and all(r['exclusion_reason']=='superseded_delivery_responder_startup_confound' for r in whole)
    tls=[r for r in rows if r['metric'].startswith('tls_handshake.')]
    assert tls and all(r['exclusion_reason']!='superseded_delivery_responder_startup_confound' for r in tls)


def test_impaired_host_loopback_cannot_supply_network_completion():
    from test_thesis_tables import loss_frame
    from framework.thesis_tables import metric
    from framework.mqtt_responder import CONTRACT, LEGACY_CONTRACT
    rows=loss_frame();rows['application']='mqtt_ready_metrics_2'
    rows['control__network_configured__enabled']=True
    rows['control__mqtt__responder_contract']=LEGACY_CONTRACT
    assert metric(rows,'completion')['n']==0
    rows['control__mqtt__responder_contract']=CONTRACT
    assert metric(rows,'completion')['n']>0
