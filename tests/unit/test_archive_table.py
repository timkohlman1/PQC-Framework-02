"""Flat archive contracts: separate observations, nulls, identity and provenance."""
import json
from pathlib import Path
import shutil
import sys
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))
from timing_dataset_support import make_run, tls_records
from framework.archive_table import export_archive, load_archive, Observations
from framework.campaign_executor import canonical_sha256


def test_raw_and_derived_scalars_share_one_simple_nullable_row(tmp_path):
    make_run(tmp_path/'raw'/'run',run_id='NA')
    output=tmp_path/'flat'
    export_archive(results_root=tmp_path/'raw',output=output)
    frame=load_archive(output,verify_sources=True)
    assert len(frame)==1
    row=frame.iloc[0]
    assert row['run_id']=='NA' and row['build_number']=='00042'
    assert row['timing__tls_handshake_us']==150
    assert row['recorded__PQC_RM2_METRICS__received_bytes']==20
    assert row['application__payload_throughput_bytes_s']==40000
    assert pd.isna(row['energy__whole_workload__energy_j'])
    assert not any(c.endswith(('__valid','__reason','__n_valid')) for c in frame)
    assert str(frame['run_success'].dtype)=='boolean'
    assert not (output/'observations.csv').exists()


def test_repeated_tls_has_rows_per_handshake_and_no_runwide_values(tmp_path):
    make_run(tmp_path/'raw'/'run',application='tls_handshake_repeat',
        epochs=[tls_records(0,repeat=True),tls_records(1,repeat=True)])
    output=tmp_path/'flat';export_archive(results_root=tmp_path/'raw',output=output)
    frame=load_archive(output)
    assert len(frame)==2 and frame['row_id'].nunique()==2 and frame['run_key'].nunique()==1
    assert set(frame['iteration_id'])=={0,1}
    assert set(frame['row_kind'])=={'handshake'}
    assert list(frame['timing__tls_handshake_us'])==[150,150]
    assert frame['energy__whole_workload__energy_j'].isna().all()
    assert frame['packet__client_to_server__wire_bytes'].isna().all()
    assert frame['resource__freertos_heap_peak_used_bytes'].isna().all()


def test_copies_deduplicate_but_reused_ids_and_failures_remain(tmp_path):
    root=tmp_path/'raw';a=make_run(root/'a')
    shutil.copytree(a,root/'copy')
    make_run(root/'failed',failed=True)
    output=tmp_path/'flat';export_archive(results_root=root,output=output)
    frame=load_archive(output)
    assert len(frame)==2 and frame['run_id'].nunique()==1
    assert frame['run_key'].nunique()==2
    assert set(frame['run_success'])=={True,False}
    assert pd.isna(frame.loc[~frame['run_success'],'timing__tls_handshake_us'].iloc[0])
    with (output/'runs.csv').open('a') as f:f.write('tamper')
    with pytest.raises(ValueError,match='hash mismatch'):load_archive(output)


def test_blocked_attempts_without_captures_are_visible(tmp_path):
    root=tmp_path/'raw'/'campaign';root.mkdir(parents=True)
    data={'campaign_id':'test','state':'completed_with_failures','runs':[{
        'case_id':'case','repetition_index':1,'state':'blocked','manifest':None,
        'failure':{'stage':'preparation','message':'build failed'}}]}
    data['final_index']={'status':'finalized','sha256':canonical_sha256(data)}
    (root/'campaign-manifest.json').write_text(json.dumps(data))
    out=tmp_path/'flat';export_archive(results_root=root,output=out)
    row=load_archive(out,verify_sources=True).iloc[0]
    assert row['row_kind']=='campaign_attempt_without_capture'
    assert row['attempt_state']=='blocked' and row['campaign_manifest_valid']
    assert not row['run_success'] and pd.isna(row['timing__tls_handshake_us'])


def test_runwide_values_not_replicated_and_conflicts_are_null():
    obs=Observations();obs.iterations['run']={(0,0,0),(0,1,1)}
    obs.add('run','run_energy',10,True)
    obs.add('run','build_bytes',20,True,scope='build')
    obs.add('run','tls_us',100,True,scope='iteration',epoch=0,iteration=0)
    obs.add('run','tls_us',200,True,scope='iteration',epoch=0,iteration=1)
    rows,_=obs.project({'run':{'run_key':'run','row_kind':'retained_capture','application':'tls_handshake_repeat'}})
    assert [r['tls_us'] for r in rows]==[100,200]
    assert all(r['run_energy'] is None and r['build_bytes']==20 for r in rows)


def test_reliable_timing_survives_an_unrelated_overall_run_failure(tmp_path):
    from timing_dataset_support import reseal
    run=make_run(tmp_path/'raw'/'run')
    path=run/'manifest.json';manifest=json.loads(path.read_text())
    manifest['run']['return_code']=12
    manifest['execution_outcome'].update(status='failed',failure_stage='energy_capture')
    path.write_text(json.dumps(manifest));reseal(run)
    out=tmp_path/'flat';export_archive(results_root=tmp_path/'raw',output=out)
    row=load_archive(out).iloc[0]
    assert not row['run_success']
    assert row['timing__tls_handshake_us']==150
    assert row['failure_stage'] == 'energy_capture'


def test_baremetal_is_one_row_per_run_with_shared_role_columns(tmp_path):
    from test_baremetal_benchmark_summary import records
    from timing_dataset_support import logical
    for name, factor in (('ML_KEM_512', 1), ('ML_KEM_768', 2)):
        stream = []
        for record in records():
            item = json.loads(record['text'])
            if name == 'ML_KEM_768':
                if item.get('parameter') == 'ML_KEM_512': item['parameter'] = 'ML_KEM_768'
                elif item.get('parameter') == 'ML_KEM_768': item['parameter'] = 'ML_KEM_512'
            if item.get('outcome') == 0: item['cycles'] *= factor
            stream.append(logical(json.dumps(item), context='baremetal_benchmark'))
        make_run(tmp_path/'raw'/name, run_id=name, application='baremetal_benchmark', records=stream)
    out=tmp_path/'flat';export_archive(results_root=tmp_path/'raw',output=out)
    frame=load_archive(out,verify_sources=True).set_index('primitive_kem_parameter')
    assert len(frame)==2 and frame['run_key'].nunique()==2
    assert set(frame['row_kind'])=={'retained_capture'}
    assert set(frame['primitive_repetitions'])=={10}
    assert set(frame['primitive_signature_algorithm'])=={'ML-DSA'}
    assert set(frame['primitive_signature_parameter'])=={'ML_DSA_65'}
    assert frame.loc['ML_KEM_512','primitive__kem_keygen_median_cycles']==105.5
    assert frame.loc['ML_KEM_768','primitive__kem_keygen_median_cycles']==211
    assert frame.loc['ML_KEM_512','primitive__signature_verify_median_cycles']==105.5
    assert frame['timing__rtlb_us'].isna().all()
    assert not any('ML_KEM_' in c or 'ML_DSA_' in c for c in frame)
    assert not any(c.startswith('primitive__mldsa') for c in frame)


def comparison_run(root, name, kex, mode, certificate='rsa3072', records=None):
    """Synthetic transport selection with identical application boundaries."""
    from timing_dataset_support import reseal, rm2_records
    plain=mode=='plaintext'
    choices={'tls_kex':kex,'tls_auth':certificate}
    if plain: choices['mqtt_transport']='plaintext'
    stream=records if records is not None else rm2_records()
    if plain:
        stream=[r for r in stream if not r['text'].startswith('PQC_TLS_HANDSHAKE_TIMING')]
    run=make_run(root/name,run_id=name,choices=choices,records=stream)
    path=run/'resolved-case.json';obj=json.loads(path.read_text())
    mqtt=obj['effective_non_secret_parameters']['mqtt']
    mqtt['evidence_class']=('stm32_st67_plaintext_e2e' if plain else
        'stm32_st67_pqc_hybrid_tls_e2e' if mode.startswith('pqc_hybrid') else 'stm32_st67_classical_tls_e2e')
    mqtt['tls']={'mode':mode,'authentication':'server'}
    if not plain: mqtt['tls'].update(key_exchange_group=kex,certificate_profile=certificate)
    path.write_text(json.dumps(obj))
    if plain:
        path=run/'manifest.json';obj=json.loads(path.read_text())
        obj['capture_contract']['experiment_class']='mqtt_plaintext_runtime'
        obj['capture_contract']['features']={'tls_runtime':False}
        path.write_text(json.dumps(obj))
    reseal(run)
    return run


def test_tls_signature_roles_compare_algorithms_in_one_column(tmp_path):
    from test_tls_analysis import aggregate
    for profile, operation in (('rsa3072','rsa_verify'),('mldsa65','mldsa65_verify')):
        comparison_run(tmp_path/'raw',profile,'secp256r1','classical_tls_server_auth',
                       profile, records=tls_records()+[aggregate(operation)])
    out=tmp_path/'flat';export_archive(results_root=tmp_path/'raw',output=out)
    frame=load_archive(out)
    column='tls__aggregate__signature_verify__elapsed_us'
    assert frame.groupby('tls_auth')[column].first().to_dict()=={'rsa3072':40,'mldsa65':40}
    assert set(frame['tls_signature_verify_implementation'])=={'rsa','mldsa65'}
    assert not any(c.startswith(('tls__aggregate__rsa_', 'tls__aggregate__mldsa')) for c in frame)


def test_mixed_signature_implementations_are_not_silently_pooled(tmp_path):
    from test_tls_analysis import aggregate
    comparison_run(tmp_path/'raw','mixed','secp256r1','classical_tls_server_auth',
        records=tls_records()+[aggregate('rsa_verify'),aggregate('mldsa65_verify')])
    out=tmp_path/'flat';export_archive(results_root=tmp_path/'raw',output=out)
    row=load_archive(out).iloc[0]
    assert row['tls_signature_verify_implementation']=='mixed'
    assert pd.isna(row['tls__aggregate__signature_verify__elapsed_us'])
    assert 'derived_tls:unavailable_values' in row['analysis_errors']


def test_runwide_values_stay_on_one_baremetal_row():
    obs=Observations();obs.iterations['run']={(0,0,0),(0,1,1)}
    obs.add('run','run_energy',10,True)
    rows,_=obs.project({'run':{'run_key':'run','row_kind':'retained_capture','application':'baremetal_benchmark'}})
    assert len(rows)==1 and rows[0]['run_energy']==10


def test_repeated_tls_never_acquires_application_end_to_end_metrics(tmp_path):
    from timing_dataset_support import rm2_records
    # Even if other valid timings occur in the stream, they do not belong to each handshake.
    make_run(tmp_path/'raw'/'run',application='tls_handshake_repeat',records=rm2_records()+tls_records(repeat=True)[1:])
    out=tmp_path/'flat';export_archive(results_root=tmp_path/'raw',output=out)
    row=load_archive(out).iloc[0]
    assert row['row_kind']=='handshake'
    for metric in ('rtfb','rtlb','ttfb','ttlb','req_tfb','req_tlb','mqtt_readiness'):
        assert pd.isna(row['timing__'+metric+'_us'])
