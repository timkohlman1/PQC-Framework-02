"""Migration workflow edge cases; no Docker, gateway or hardware."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from framework import migration as m
from framework import migration_report as report
from framework.run_queue import Queue, digest
from migration_workspace import catalogue
from framework.campaign_editor import validate

ROOT = Path(__file__).resolve().parents[2]


def session():
    return dict(id='example', profiles={'from':'a.yaml','to':'b.yaml'},
        choices={'from':dict(m.DEFAULTS), 'to':{**m.DEFAULTS,'tls_kex':'ML_KEM_768'}, 'repetitions':10})


def test_options_and_single_case_profiles_resolve(tmp_path):
    cat = catalogue(ROOT)
    assert 'mldsa65' in cat['options']['tls_auth']
    assert 'stm32l4r5_st67' == cat['base']['target']
    for choices in [dict(m.DEFAULTS), {**m.DEFAULTS,'mqtt_transport':'plaintext','tls_kex':None,'tls_auth':None,'auth_mode':None},
                    {**m.DEFAULTS,'tls_auth':'mldsa65','auth_mode':'mutual','secure_boot':'mldsa65',
                     'firmware_mode':'dual_bank_ota','standby_signing_keys':2}]:
        profile = m.profile(cat['base'], choices, 'migration_fixture', 10)
        result = validate(ROOT, profile, tmp_path)
        assert result['conditions'] == 1 and result['attempts'] == 10
        assert profile['execution']['energy_monitoring'] == 'off'
        assert profile['execution']['workload_failures'] == 'record'
        if choices['mqtt_transport']=='plaintext':
            assert 'tls_kex' not in profile['fixed']


def test_wizard_unchanged_does_not_request_device_constraints():
    messages = []
    choices = m.wizard(catalogue(ROOT), ask=lambda _: '', tell=messages.append)
    assert choices['from'] == choices['to'] == m.DEFAULTS
    assert choices['repetitions'] == 10
    assert any('Unchanged' in s for s in messages)
    assert not any('capacity' in s or 'Device model' in s for s in messages)


def test_choose_validation_and_incompatible_unchanged():
    replies = iter(['0','garbage','3','2'])
    assert m.choose('mode',['server','mutual'],'absent', unchanged=True,
                    ask=lambda _:next(replies),tell=lambda _:None)=='mutual'
    assert m.integer('n',10,1,1000,ask=lambda _:'',tell=lambda _:None)==10


def test_plaintext_wizard_skips_tls_and_prompts_on_migration_to_tls():
    cat = catalogue(ROOT)
    # Current plaintext, then future TLS; pick all remaining defaults.
    count = 0
    def ask(prompt):
        nonlocal count
        count += 1
        if count == 1: return '2'
        if count == 7: return '2'  # Future: unchanged plaintext, TLS, plaintext.
        return ''
    values = m.wizard(cat, ask=ask, tell=lambda _:None)
    assert values['from']['mqtt_transport'] == 'plaintext'
    assert values['from']['tls_kex'] is None
    assert values['to']['mqtt_transport'] == 'tls'
    assert values['to']['tls_kex'] in cat['options']['tls_kex']


def test_session_lock_refuses_concurrent_wizards(tmp_path):
    path = tmp_path/'session.json'
    with m.session_lock(path):
        with pytest.raises(ValueError,match='already open'):
            with m.session_lock(path): pass


def register(q, identifier, profile, position=0, status='queued'):
    q.folder(identifier).mkdir(parents=True)
    with q.connect() as db:
        db.execute('INSERT INTO jobs(id,position,profile,repetitions,conditions,attempts,status,created) VALUES (?,?,?,10,1,10,?,0)',
                   (identifier,position,profile,status))


def test_recover_submission_after_crash_and_do_not_repeat_missing_jobs(tmp_path):
    q = Queue(tmp_path)
    value = session(); value['jobs']={}
    path=tmp_path/'session.json'
    for side,identifier in [('from','a'*12),('to','b'*12)]:
        register(q,identifier,value['profiles'][side])
    assert m.submit(q,path,value)=={'from':'a'*12,'to':'b'*12}
    assert len(q.jobs())==2
    assert m.submit(q,path,value)==value['jobs']
    with q.connect() as db: db.execute('DELETE FROM jobs')
    with pytest.raises(ValueError,match='refusing to repeat'): m.submit(q,path,value)


def test_partial_registration_requires_inspection(tmp_path):
    q=Queue(tmp_path); value=session();value['jobs']={}
    register(q,'a'*12,'a.yaml')
    with pytest.raises(ValueError,match='partial or duplicated'): m.submit(q,tmp_path/'session.json',value)


def test_explicit_queue_export_leaves_other_users_marks_unchanged(tmp_path,monkeypatch):
    q=Queue(tmp_path)
    for i in range(3):
        ident=str(i)*12;register(q,ident,str(i)+'.yaml',i,'completed')
        folder=q.folder(ident)/'campaigns'/'test';folder.mkdir(parents=True)
        manifest=folder/'campaign-manifest.json';manifest.write_text('{}')
        with q.connect() as db: db.execute('UPDATE jobs SET manifest_sha=? WHERE id=?',(digest(manifest),ident))
    q.mark('2'*12)
    requests=[]
    def offline(action,*args):
        requests.append(json.loads((tmp_path/args[1]).read_text()))
        return {'output':args[3]}
    monkeypatch.setattr(q,'offline',offline)
    q.export(identifiers=['0'*12,'1'*12])
    assert [r['id'] for r in requests[0]['jobs']]==['0'*12,'1'*12]
    assert [r['selected'] for r in q.jobs()]==[0,0,1]
    for ids in [[],['0'*12,'0'*12],['9'*12]]:
        with pytest.raises(ValueError):q.export(identifiers=ids)


def test_wait_reports_jobs_ahead_and_external_stop_without_restarting(tmp_path,monkeypatch):
    q=Queue(tmp_path)
    for i in range(3):register(q,str(i)*12,str(i)+'.yaml',i)
    text=[]
    with pytest.raises(ValueError,match='dispatch stopped'):
        m.wait_for_jobs(q,{'from':'1'*12,'to':'2'*12},tell=text.append)
    assert any('waiting for 1 other queue' in s for s in text)
    assert all(r['status']=='queued' for r in q.jobs())


def test_halted_queue_never_accepts_failure_automatically(tmp_path):
    q=Queue(tmp_path)
    register(q,'a'*12,'a.yaml',0,'attention');register(q,'b'*12,'b.yaml',1)
    with q.connect() as db:db.execute("UPDATE settings SET value='halted: cleanup'")
    with pytest.raises(ValueError,match='halted'):
        m.wait_for_jobs(q,{'from':'a'*12,'to':'b'*12},ask=lambda _:pytest.fail('must not ask to waive unsafe cleanup'),tell=lambda _:None)


def timing_frames(from_value=100000,to_value=80000,reason=None):
    return {'distributions':[dict(condition=s,metric='tls_handshake',median=v,n_runs=10,q1=v-100,q3=v+100)
        for s,v in [('from',from_value),('to',to_value)]],
        'differences':[dict(condition='to',metric='tls_handshake',delta_median=None if reason else to_value-from_value,reason=reason)]}


def test_signed_deltas_units_and_zero_baseline():
    rows=report.project(timing_frames(),session())
    row=next(r for r in rows if r['metric']=='tls_handshake')
    assert row['delta']==-20000 and row['percent']==-20
    assert report.table_rows([row])[0][-2:]==['-20.000','-20.000']
    row=next(r for r in report.project(timing_frames(0,1000),session()) if r['metric']=='tls_handshake')
    assert row['delta']==1000 and row['percent'] is None and row['percent_reason']=='zero_baseline'


def test_unknown_controls_keep_absolute_values_but_no_delta():
    row=next(r for r in report.project(timing_frames(reason='unknown_control:target'),session()) if r['metric']=='tls_handshake')
    assert row['values']=={'from':100000,'to':80000}
    assert row['delta'] is None and row['percent'] is None


def test_plaintext_handshake_never_becomes_zero_cost():
    s=session();s['choices']['from']['mqtt_transport']='plaintext'
    row=next(r for r in report.project(timing_frames(),s) if r['metric']=='tls_handshake')
    assert row['values']['from'] is None and row['delta'] is None
    assert row['side_reasons']['from']=='not_applicable_to_plaintext'


def test_resource_absolute_delta_and_multiple_builds_are_not_averaged():
    frames={'resource_distributions':[dict(condition=s,metric='configured_application_ram_bytes',median_bytes=v,n_observations=1)
        for s,v in [('from',1024),('to',3072)]],
        'resource_differences':[dict(condition='to',metric='configured_application_ram_bytes',delta_median_bytes=2048,reason=None)]}
    row=report.project(frames,session())[0]
    assert report.table_rows([row])[0]==['Configured application RAM (KiB)','1.000','3.000','+2.000','+200.000']
    frames['resource_distributions'][1]['n_observations']=2
    row=report.project(frames,session())[0]
    assert row['values']['to'] is None and row['delta'] is None


def test_treatment_is_predeclared_from_user_changes_not_observed_conflicts():
    from test_timing_summary import data
    d=data();s=session()
    for r in d.runs:
        r['controls'].update(tls={'key_exchange_group':'anything','certificate_profile':'unexpected'},
                             source={'state_identity':'different'})
        r['campaign_id']='a' if r['tls_kex']=='base' else 'b'
    spec=report.specification(d,s)
    assert spec['treatment']==['controls.tls.key_exchange_group','tls_kex']
    assert not spec['independent_runs']
    from framework.timing_summary import summarise
    d.runs[2]['controls']['source']['state_identity']='drift'
    frames,_=summarise(d,spec)
    assert all('conflicting_control:controls.source.state_identity' in r['reason'] for r in frames['differences'].to_dict('records'))


def test_tex_escapes_and_outputs_signed_cells():
    s=session();s['choices']['to']['tls_auth']='a_%&#'
    counts={side:dict(completed=10,failed=0,blocked=0,without_capture=0,planned=10) for side in m.SIDES}
    outputs=report.render(report.project(timing_frames(),s),s,counts)
    assert '-20.000' in outputs['comparison.tex']
    assert r'a \%\&\#' in outputs['selections.tex']
    assert 'Change (\\%)' in outputs['comparison.tex']
    assert 'Ten attempts are a pilot' in outputs['comparison.txt']


def test_wait_can_retain_completed_failures_without_replacement_attempts(tmp_path,monkeypatch):
    q=Queue(tmp_path)
    register(q,'a'*12,'a.yaml',0,'attention');register(q,'b'*12,'b.yaml',1,'completed')
    folder=q.folder('a'*12)/'campaigns'/'trial';folder.mkdir(parents=True)
    (folder/'campaign-manifest.json').write_text(json.dumps(dict(state='completed_with_failures',
        cleanup={'status':'passed'},runs=[{'state':'failed'}])))
    with q.connect() as db:db.execute("UPDATE settings SET value='running'")
    monkeypatch.setattr(q,'worker_alive',lambda:True)
    def complete(_):
        assert q.job('a'*12)['mode']=='accept'
        assert len(q.jobs())==2
        q.finish('a'*12,'completed_with_failures','Accepted without replacement')
    m.wait_for_jobs(q,{'from':'a'*12,'to':'b'*12},ask=lambda _:'',tell=lambda _:None,sleep=complete)
    assert len(q.jobs())==2 and q.job('a'*12)['status']=='completed_with_failures'


def test_frozen_profile_rejects_displayed_settings_that_do_not_match_queue(tmp_path,monkeypatch):
    import yaml
    q=Queue(tmp_path);s=session();s.update(queue=q.relative(q.directory),jobs={},profile_hashes={})
    for side in m.SIDES:
        ident=('a' if side=='from' else 'b')*12
        s['jobs'][side]=ident
        folder=q.folder(ident);(folder/'profiles').mkdir(parents=True)
        data=m.profile(catalogue(ROOT)['base'],s['choices'][side],Path(s['profiles'][side]).stem,10)
        path=folder/'profiles/input.yaml';path.write_text(yaml.safe_dump(data))
        s['profile_hashes'][side]=digest(path)
        (folder/'plan.json').write_text(json.dumps({'profile_hashes':{q.relative(path):digest(path)}}))
        (folder/'plan.sha256').write_text(digest(folder/'plan.json'))
    assert report.frozen_profiles(tmp_path,s)
    s['choices']['to']['tls_auth']='mldsa65'
    with pytest.raises(ValueError,match='displayed migration choices'):
        report.frozen_profiles(tmp_path,s)


def test_live_progress_uses_attempt_records_before_final_summary(tmp_path,monkeypatch):
    q=Queue(tmp_path)
    register(q,'a'*12,'a.yaml',0,'running');register(q,'b'*12,'b.yaml',1,'completed')
    folder=q.folder('a'*12)/'campaigns'/'trial';folder.mkdir(parents=True)
    (folder/'campaign-manifest.json').write_text(json.dumps(dict(state='running',summary=None,
        runs=[{'state':'completed'},{'state':'failed','previous_attempts':[{'state':'failed'}]}])))
    with q.connect() as db:db.execute("UPDATE settings SET value='running'")
    monkeypatch.setattr(q,'worker_alive',lambda:True)
    messages=[]
    m.wait_for_jobs(q,{'from':'a'*12,'to':'b'*12},tell=messages.append,
        sleep=lambda _:q.finish('a'*12,'completed_with_failures','finished'))
    assert any('1 completed, 1 failed, 0 blocked / 10 planned' in x for x in messages)
