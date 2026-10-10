"""Scientific selection, missing values and presentation boundaries; synthetic only."""
import copy
import json

import pandas as pd
import pytest

from framework.thesis_tables import (METRICS, display_metric, eligible, escape_tex,
    latex, make_tables, metric, read_spec, select, statistics, contribution_frames)


def frame():
    rows=[]
    for i, duration in enumerate([1000,3000]):
        row=dict(run_key=str(i),row_id=str(i),row_kind='retained_capture',attempt_current=True,
            source_commit='a'*40,git_dirty=False,boot_stack_profiling=False,boot_uart_diagnostics=False,
            transport_mode='tls',control__network_configured__enabled=False,tls_kex='secp256r1',
            tls_auth='mldsa65',auth_mode='mutual',configuration_identity='c',firmware_identity='f',
            git_state_identity='s',run_success=True,capture_valid=True,selected_inputs_valid=True,
            timing_policy_exclusion=None,secure_boot='integrity_sha256',campaign_id='auth',
            target='target',gateway='gateway',workload='workload',payload_bytes=204800,chunk_bytes=400,
            energy_enabled=True,control__mqtt__qos=0)
        row.update({column:None for column,_,_,_ in METRICS.values()})
        row['timing__tls_handshake_us']=duration
        row['resource__flash_section_bytes']=1024
        rows.append(row)
    return pd.DataFrame(rows)


def item(kind='tls_auth'):
    return dict(id=kind,kind=kind,filters={'campaign_id':'auth'},source_commit='a'*40,expected_current_runs=2)


def test_sample_sd_units_and_missing_metrics_are_not_zero():
    result=metric(frame(),'handshake')
    assert result['mean']==2 and result['sd']==pytest.approx(2**.5)
    assert result['unit']=='ms' and result['n']==2
    assert metric(frame(),'heap')['mean'] is None
    assert display_metric(metric(frame(),'heap'),2,'maximum')=='—'
    assert statistics(pd.Series([7.]))['sd'] is None


def test_failure_policy_and_timing_exclusion_leave_other_metrics_usable():
    f=frame();f.loc[1,'run_success']=False
    assert len(eligible(f))==1 and metric(f,'handshake')['n']==1
    f.loc[0,'timing_policy_exclusion']='boot_stack_profiling'
    assert metric(f,'handshake')['n']==0
    assert metric(f,'app_flash')['value']==1


def test_static_conflicts_never_become_averaged_build_size():
    f=frame();f.loc[1,'resource__flash_section_bytes']=2048
    result=metric(f,'app_flash')
    assert result['value'] is None and result['reason']=='conflicting_static_sizes'
    assert result['mean'] is None and result['sd'] is None
    assert display_metric(result,2,'static')=='—'


@pytest.mark.parametrize('column,value,pattern',[
    ('source_commit','b'*40,'source identity'),('git_dirty',True,'source identity'),
    ('boot_stack_profiling',True,'stack profiling'),('configuration_identity','different','case control'),
    ('payload_bytes',4000,'selection control'),('control__network_configured__enabled',True,'selection control'),
    ('run_key','0','one retained capture'),('row_kind','handshake','one retained capture'),
])
def test_incompatible_runs_refuse_a_combined_row(column,value,pattern):
    f=frame();f.loc[1,column]=value
    # A duplicate capture reduces the count before the shape guard.
    if column=='run_key':pattern='capture count'
    with pytest.raises(ValueError,match=pattern):select(f,item())


def test_history_is_preserved_without_manufacturing_sample_size():
    f=frame();history=f.iloc[[0]].copy();history['attempt_current']=False;history['run_success']=False
    all_rows,current=select(pd.concat([f,history],ignore_index=True),item())
    assert len(all_rows)==3 and len(current)==2


def test_integrity_reference_has_no_signature_cost_even_if_raw_zero():
    f=frame();f['boot__authenticity_ms']=0;f['boot__image_signature_used_bytes']=0
    assert metric(f,'auth')['mean'] is None
    assert metric(f,'signature')['value'] is None
    assert metric(f,'auth')['reason']=='not_applicable_integrity_only'


def test_boot_does_not_require_inapplicable_application_transfer_controls():
    f=frame();f['payload_bytes']=None;f['chunk_bytes']=None;f['control__mqtt__qos']=None
    f['transport_mode']='plaintext'
    assert len(select(f,item('secure_boot'))[1])==2


def test_followup_remains_separate_and_requires_matching_case_identity():
    f=frame();a=item();b=dict(item('tls_auth_followup'),baseline_selection='tls_auth')
    tables,details=make_tables({'selections':[a,b]}, {'tls_auth':(f,f),'tls_auth_followup':(f,f)})
    assert len(tables)==2 and [r[0] for r in tables[1]['rows']]==['Original','Follow-up']
    changed=f.copy();changed['configuration_identity']='changed'
    with pytest.raises(ValueError,match='follow-up control mismatch'):
        make_tables({'selections':[a,b]},{'tls_auth':(f,f),'tls_auth_followup':(changed,changed)})


def test_followup_provenance_excludes_other_authentication_cases_and_their_failures():
    original=frame();other=original.iloc[[0]].copy();other['tls_auth']='rsa3072'
    historical=other.copy();historical['attempt_current']=False;historical['run_success']=False
    broad=pd.concat([original,other,historical],ignore_index=True)
    current=broad[broad.attempt_current]
    followup=dict(item('tls_auth_followup'),baseline_selection='tls_auth')
    selected={'tls_auth':(broad,current),'tls_auth_followup':(original,original)}
    scoped_all,scoped_current=contribution_frames(followup,'tls_auth',selected)
    assert len(scoped_all)==len(scoped_current)==2
    assert len(selected['tls_auth'][0])==4  # Preserve the full campaign audit.


def test_latex_escapes_data_and_provenance_can_be_hidden_independently():
    t=dict(id='test',caption='Timing & size',headers=['Case','Mean ms'],rows=[['a_#%','1.00 (0.00)']],
        notes='Keep measurement definitions.')
    text=latex(t,['A provenance note with % and _'])
    assert r'a\_\#\%' in text and r'\label{tab:pqc-test}' in text
    assert text.index('Keep measurement definitions.')<text.index(r'\iftrue')
    assert text.count(r'\iftrue')==1 and text.endswith('\\fi % END PROVENANCE\n')
    assert escape_tex('—')==r'\textemdash{}'


def test_spec_requires_pinned_inputs_and_selection_counts(tmp_path):
    path=tmp_path/'spec.json'
    value=dict(version=1,exports=[dict(path='flat',archive_sha256='1'*64)],selections=[item()])
    path.write_text(json.dumps(value));assert read_spec(path)['exports'][0]['path']==str(tmp_path/'flat')
    invalid=copy.deepcopy(value);invalid['exports'][0]['archive_sha256']=''
    path.write_text(json.dumps(invalid))
    with pytest.raises(ValueError,match='archive_sha256'):read_spec(path)
    invalid=copy.deepcopy(value);invalid['selections'][0]['filters']={}
    path.write_text(json.dumps(invalid))
    with pytest.raises(ValueError,match='filters'):read_spec(path)


def test_boot_identical_note_requires_complete_ten_capture_evidence():
    f=pd.concat([frame().iloc[[0]]]*10,ignore_index=True)
    f['boot__integrity_ms']=165.125
    f['boot__bootloader_flash_bytes']=12345
    f['boot__bootloader_static_ram_bytes']=16512
    f['boot__boot_stack_high_water_bytes']=460
    a=dict(item('secure_boot'),stack_selection='secure_boot_stack')
    b=item('secure_boot_stack')
    def render(g):
        return make_tables({'selections':[a,b]},
            {'secure_boot':(g,g),'secure_boot_stack':(f,f)})[0][0]
    table=render(f)
    assert 'All recorded values were identical across 10 executions' in table['notes']
    assert table['headers'][1:3]==['Integrity verification ms','Auth. ms']
    assert table['rows'][0][1:5]==['165.12','—','12,345','16,512']
    assert not any('Image verify' in h or 'n timing' in h for h in table['headers'])
    varied=f.copy();varied.loc[0,'boot__integrity_ms']=166
    assert 'All recorded values were identical' not in render(varied)['notes']
    assert 'All recorded values were identical' not in render(f.iloc[:9])['notes']


def loss_frame():
    f=frame()
    f['control__network_configured__enabled']=True
    f['control__network_configured__loss_percent']=15.
    f['control__network_configured__rtt_ms']=0
    f['control__network_configured__rate_kbit']=100000
    f['control__network_configured__mtu']=1500
    f['timing__ttlb_us']=[2000000,99000000]
    f.loc[1,'run_success']=False
    f.loc[1,'capture_valid']=False
    return f


def test_loss_grid_keeps_capture_failures_in_denominator_and_out_of_latency():
    f=loss_frame();a=item('network_loss')
    _,current=select(f,a)
    tables,details=make_tables({'selections':[a]},{'network_loss':(f,current)})
    assert tables[0]['rows'][0][-1]=='1/2'
    assert tables[1]['rows'][0][-1]=='2.00'
    assert tables[2]['rows'][0][-1]=='0.00'  # 1000 us in seconds
    completion=next(r for r in details if r['metric']=='completion')
    assert completion['n']==1 and completion['invalid_captures']==1
    assert completion['attempts']==2 and completion['median']==2
    assert completion['sd'] is None
    f['run_success']=False
    tables,_=make_tables({'selections':[a]},{'network_loss':(f,f)})
    assert tables[0]['rows'][0][-1]=='0/2'
    assert tables[1]['rows'][0][-1]=='—'


@pytest.mark.parametrize('col,value',[
    ('control__network_configured__enabled',False),
    ('control__network_configured__loss_percent',101),
    ('control__network_configured__rtt_ms',20),
    ('auth_mode','server'),
])
def test_loss_grid_refuses_incompatible_controls(col,value):
    f=loss_frame();f.loc[1,col]=value
    with pytest.raises(ValueError):select(f,item('network_loss'))


def test_loss_grid_never_rounds_distinct_loss_levels_into_same_heading():
    f=loss_frame();f['control__network_configured__loss_percent']=[0.1,0.3]
    tables,_=make_tables({'selections':[item('network_loss')]},{'network_loss':(f,f)})
    assert tables[0]['headers'][1:]==['0.1%','0.3%']
