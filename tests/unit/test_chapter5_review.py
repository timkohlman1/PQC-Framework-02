"""Scientific boundaries for derived thesis diagnostics; no hardware required."""
import csv
import json
from pathlib import Path
import numpy as np
import pytest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from framework.chapter5_review import Inputs, elapsed_stages, equal_run_distribution, weighted_quantiles
from framework.observed_ram import components, run_estimate, PEAKS
from framework.authentication_distribution import box


def observations():
    spans={'tls_handshake':(10,50),'mqtt_readiness':(0,60),'ttfb':(0,80),'ttlb':(0,100),'req_tfb':(70,80),'req_tlb':(70,100)}
    return {k:dict(start_us=a,end_us=b,value_us=b-a,unit='us',validity='valid') for k,(a,b) in spans.items()}


def test_disjoint_stages_conserve_connection_relative_delivery():
    stages=elapsed_stages(observations())
    assert list(stages.values())==[10,40,10,10,10,20]
    assert sum(stages.values())==100


def test_different_first_byte_boundaries_are_rejected():
    obs=observations();obs['req_tfb'].update(end_us=81,value_us=11)
    with pytest.raises(ValueError,match='common timing checkpoints'):elapsed_stages(obs)


def test_out_of_order_readiness_cannot_make_negative_overhead():
    obs=observations();obs['mqtt_readiness'].update(end_us=71,value_us=71)
    with pytest.raises(ValueError,match='out-of-order'):elapsed_stages(obs)


def test_invalid_or_incomplete_timing_is_not_a_zero_duration():
    obs=observations();obs['ttlb']['validity']='invalid'
    with pytest.raises(ValueError,match='invalid timing'):elapsed_stages(obs)
    obs=observations();del obs['req_tfb']
    with pytest.raises(ValueError,match='incomplete'):elapsed_stages(obs)


def test_equal_run_weight_is_invariant_to_sample_count():
    grid=[0,1,2,3]
    np.testing.assert_allclose(equal_run_distribution([[0,1],[2,3]],grid),[.25,.5,.75,1])
    np.testing.assert_allclose(equal_run_distribution([[0,1]*100,[2,3]],grid),[.25,.5,.75,1])
    np.testing.assert_allclose(weighted_quantiles([np.array([0,1]*100),np.array([2,3])],[.25,.75]),[0,2])


def test_power_distribution_rejects_empty_or_nonfinite_samples():
    for runs in ([],[[]],[[float('nan')]]):
        with pytest.raises(ValueError):equal_run_distribution(runs,[0,1])


def test_regional_peak_estimate_does_not_reintroduce_pool_capacity():
    peaks=dict(zip(PEAKS,[20,30,2,3]))
    assert run_estimate(100,peaks)==155
    peaks['mldsa_workspace_peak_used_bytes']=None
    with pytest.raises(ValueError):run_estimate(100,peaks)


def test_static_exclusions_are_disjoint_and_task_stacks_are_not_added_twice():
    values=dict(ram_static_base_bytes=1000,freertos_heap_reserved_bytes=400,ram2_section_bytes=50,
        ram3_section_bytes=800,result_buffer_reserved_bytes=100,workspace_reserved_bytes=600,mailbox_reserved_bytes=10)
    objects=[dict(owner='pqc_tls_instrumentation.c',name='records',start=0x20000000,end=0x20000064),
        dict(owner='pqc_tls_instrumentation.c',name='alias',start=0x20000000,end=0x20000064),
        dict(owner='lwip.c',name='network_buffer',start=0x20000100,end=0x20000132)]
    c=components(values,objects)
    assert c['application_static_bytes']==650
    assert c['excluded_experiment_bytes']==210
    assert run_estimate(c['application_static_bytes'],dict(zip(PEAKS,[40,60,2,3])))==755


def test_missing_heap_symbol_cannot_be_interpreted_as_zero():
    with pytest.raises(ValueError,match='heap backing'):components({'freertos_heap_reserved_bytes':None},[])


def test_checksum_pinning_detects_changes(tmp_path):
    p=tmp_path/'input';p.write_text('original')
    inputs=Inputs();inputs.pin(p);p.write_text('changed')
    with pytest.raises(ValueError,match='hash mismatch'):inputs.verify()


def test_relative_spread_is_scale_invariant():
    a=box([10,11,12,13,14]);b=box([v*100 for v in [10,11,12,13,14]])
    assert 100*(a['q3']-a['q1'])/a['median']==pytest.approx(100*(b['q3']-b['q1'])/b['median'])


def test_readiness_must_share_the_connection_origin():
    obs=observations();obs['mqtt_readiness'].update(start_us=1,value_us=59)
    with pytest.raises(ValueError,match='common timing checkpoints'):elapsed_stages(obs)


def test_loss_view_keeps_known_failure_separate_from_missing_evidence(tmp_path):
    from framework.chapter5_review import loss_outcomes
    class Published:
        def rows(self,report,name):
            selection='recent_7' if 'recent_7' in name else 'recent_8'
            algorithms=['secp256r1','SecP256r1MLKEM768'] if selection=='recent_7' else ['SecP256r1MLKEM768']
            inventory=[];obs=[]
            for alg in algorithms:
                for net in ('trial_reference','thesis_loss_10','thesis_loss_15'):
                    condition=alg+'-'+net
                    for i,outcome in enumerate(('success','failed','unknown')):
                        key=condition+str(i)
                        inventory.append(dict(run_key=key,condition=condition,tls_kex=alg,tls_auth='ecdsa-p256' if selection=='recent_7' else 'mldsa65',network_condition=net,execution_outcome='completed' if i==0 else 'failed'))
                        obs.append(dict(run_key=key,metric='tls_handshake',validity='valid' if i<2 else 'unavailable',exclusion_reason='',operation_outcome=outcome))
            return inventory if name.endswith('inventory.csv') else obs
    loss_outcomes(Published(),None,tmp_path)
    rows=list(csv.DictReader((tmp_path/'loss-outcomes.csv').open()))
    assert len(rows)==9
    assert all((r['handshake_success'],r['handshake_failed'],r['handshake_unclassified'])==('1','1','1') for r in rows)
