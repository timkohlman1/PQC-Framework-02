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


@pytest.mark.parametrize('algorithm', ['mldsa44', 'mldsa65'])
@pytest.mark.parametrize('role,mode', [('server','verify_small'), ('mutual','sign_small'), ('mutual','both_small')])
def test_wizard_memory_choices_are_applicable_and_can_be_unchanged(monkeypatch, role, mode, algorithm):
    calls = []
    original = m.choose
    def choose(title, values, default, **kwargs):
        wanted = {'TLS certificate/signature':algorithm, 'TLS authentication':role,
                  'ML-DSA TLS memory mode':mode}.get(title, default)
        values = list(values)
        options = [default, *[v for v in values if v != default]] if kwargs['unchanged'] and default in values else values
        calls.append((title, values, kwargs['unchanged']))
        return original(title, values, default, **{**kwargs, 'ask':lambda _:str(options.index(wanted)+1)})
    monkeypatch.setattr(m, 'choose', choose)
    result = m.wizard(catalogue(ROOT), ask=lambda _:'', tell=lambda _:None)
    assert result['from'] == result['to']
    assert result['from']['mldsa_memory_mode'] == mode
    prompts = [c for c in calls if c[0] == m.LABELS['mldsa_memory_mode']]
    assert len(prompts) == 2 and prompts[1][2]
    assert prompts[0][1] == (['default','verify_small'] if role=='server' else ['default','verify_small','sign_small','both_small'])


@pytest.mark.parametrize('target', ['server', 'classical', 'plaintext'])
def test_wizard_does_not_inherit_inapplicable_small_signing(monkeypatch, target):
    original = m.choose
    side = -1
    def choose(title, values, default, **kwargs):
        nonlocal side
        if title == m.LABELS['mqtt_transport']: side += 1
        wanted = {m.LABELS['tls_auth']:'mldsa65', m.LABELS['auth_mode']:'mutual',
                  m.LABELS['mldsa_memory_mode']:'both_small'}
        if side == 1:
            wanted = {m.LABELS['auth_mode']:'server'} if target=='server' else {
                m.LABELS['tls_auth']:'ecdsa-p256'} if target=='classical' else {m.LABELS['mqtt_transport']:'plaintext'}
        values = list(values)
        options = [default, *[v for v in values if v != default]] if kwargs['unchanged'] and default in values else values
        reply = str(options.index(wanted[title])+1) if title in wanted else ''
        return original(title, values, default, **{**kwargs, 'ask':lambda _:reply})
    monkeypatch.setattr(m, 'choose', choose)
    result = m.wizard(catalogue(ROOT), ask=lambda _:'', tell=lambda _:None)
    assert result['from']['mldsa_memory_mode'] == 'both_small'
    assert result['to']['mldsa_memory_mode'] == ('default' if target=='server' else None)


@pytest.mark.parametrize('role,modes', [('server',['default','verify_small']),
    ('mutual',['default','verify_small','sign_small','both_small'])])
def test_memory_profiles_resolve_to_selected_build_options(tmp_path, role, modes):
    import yaml
    from framework.config_resolver import ConfigResolver
    from framework.build import _write_tls_algorithm_selection
    cat = catalogue(ROOT)
    base = {**m.DEFAULTS, 'tls_auth':'mldsa65', 'auth_mode':role}
    omitted = dict(base); omitted.pop('mldsa_memory_mode')
    for mode in modes:
        choices = {**base, 'mldsa_memory_mode':mode}
        profile = m.profile(cat['base'], choices, 'memory', 10)
        if mode == 'default':
            assert profile == m.profile(cat['base'], omitted, 'memory', 10)
            assert 'mldsa_memory_mode' not in profile['fixed']
        path = tmp_path/'campaign.yaml'; path.write_text(yaml.safe_dump(profile))
        resolver = ConfigResolver(ROOT)
        cases = resolver.expand_campaign(path)
        assert len(cases) == 1
        _, settings = _write_tls_algorithm_selection(resolver.to_legacy_bundle(cases[0], resolve_secrets=False), tmp_path/mode)
        assert settings['mldsa_verify_small_mem'] == (mode in ('verify_small','both_small'))
        assert settings['mldsa_sign_small_mem'] == (mode in ('sign_small','both_small'))


@pytest.mark.parametrize('choices', [{**m.DEFAULTS,'mldsa_memory_mode':'verify_small'},
    {**m.DEFAULTS,'tls_auth':'mldsa65','mldsa_memory_mode':'sign_small'},
    {**m.DEFAULTS,'mqtt_transport':'plaintext','mldsa_memory_mode':'verify_small'}])
def test_invalid_memory_session_choices_fail_profile_validation(tmp_path, choices):
    with pytest.raises(ValueError, match='ML-DSA|mutual authentication'):
        validate(ROOT, m.profile(catalogue(ROOT)['base'], choices, 'invalid_memory', 1), tmp_path)


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


def test_ram_estimate_absolute_delta_and_flash_build_guard():
    frames={'resource_distributions':[dict(condition=s,metric='peak_based_ram_estimate_bytes',summary_bytes=v,n_observations=30)
        for s,v in [('from',1024),('to',3072)]],
        'resource_differences':[dict(condition='to',metric='peak_based_ram_estimate_bytes',delta_summary_bytes=2048,reason=None)]}
    row=report.project(frames,session())[0]
    assert report.table_rows([row])[0]==['RAM estimate (KiB)','1.000','3.000','+2.000','+200.000']
    frames['resource_distributions'] += [dict(condition=s,metric='flash_section_bytes',median_bytes=v,n_observations=n)
        for s,v,n in [('from',1024,1),('to',3072,2)]]
    frames['resource_differences'].append(dict(condition='to',metric='flash_section_bytes',delta_median_bytes=2048))
    flash=next(r for r in report.project(frames,session()) if r['metric']=='flash_section_bytes')
    assert flash['values']['to'] is None and flash['delta'] is None


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


def test_memory_change_is_a_treatment_but_source_drift_is_not():
    from test_timing_summary import data
    from framework.timing_summary import summarise
    d = data(); s = session()
    for side in m.SIDES:
        s['choices'][side].update(tls_kex='secp256r1', tls_auth='mldsa65', auth_mode='mutual')
    s['choices']['from'].pop('mldsa_memory_mode')  # Legacy default, omitted in capture too.
    s['choices']['to']['mldsa_memory_mode'] = 'both_small'
    for i, r in enumerate(d.runs):
        r.update(campaign_id='a' if i < 2 else 'b', tls_kex='secp256r1')
        tls = {'key_exchange_group':'secp256r1'}
        if i >= 2: tls['mldsa_memory_mode'] = 'both_small'
        r['controls'].update(tls=tls, source={'state_identity':'fixed'})
    spec = report.specification(d,s)
    assert spec['treatment'] == ['controls.tls.mldsa_memory_mode']
    frames,_ = summarise(d,spec)
    delta = frames['differences'].to_dict('records')[0]
    assert delta['reason'] is None and delta['delta_median'] == 20
    d.runs[2]['controls']['source']['state_identity'] = 'drift'
    frames,_ = summarise(d,spec)
    assert 'conflicting_control:controls.source.state_identity' in frames['differences'].iloc[0]['reason']


def test_legacy_choices_are_not_modified_or_added_to_the_selections_report():
    from test_timing_summary import data
    s = session()
    for side in m.SIDES:
        s['choices'][side].pop('mldsa_memory_mode')
        s['choices'][side]['tls_auth'] = 'mldsa65'
    before = deepcopy(s)
    report.specification(data(), s)
    counts={side:dict(completed=10,failed=0,blocked=0,without_capture=0,planned=10) for side in m.SIDES}
    old = report.render(report.project(timing_frames(),s),s,counts)['selections.tex']
    assert 'memory mode' not in old and s == before
    s['choices']['to']['mldsa_memory_mode'] = 'verify_small'
    new = report.render(report.project(timing_frames(),s),s,counts)['selections.tex']
    assert 'ML-DSA TLS memory mode & default & verify small' in new


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
