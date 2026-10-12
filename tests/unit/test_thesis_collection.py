"""Collection control flow uses synthetic subprocess verdicts, never hardware."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from framework import thesis_collection as collection
from framework.campaign_executor import canonical_sha256

spec = importlib.util.spec_from_file_location('thesis_driver', ROOT/'scripts/collect_thesis_evidence.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    shutil.copytree(ROOT/'configs',tmp_path/'configs')
    monkeypatch.setattr(collection,'ROOT',tmp_path)
    monkeypatch.setattr(collection,'source_identity',lambda:{'synthetic':'fixed_source'})
    monkeypatch.setattr(driver,'ROOT',tmp_path)
    return tmp_path/'results'/'thesis'


def manifest(output,name,state='completed',cleanup='passed'):
    path=output/'campaigns'/name/'owned'/'campaign-manifest.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    planned=next((s['attempts'] for s in driver.read(output/'plan.json')['steps'] if s['id']==name),1) if (output/'plan.json').exists() else 1
    data={'state':state,'cleanup':{'status':cleanup},'summary':{'planned':planned,'completed':planned*int(state=='completed'),'failed':planned*int(state!='completed'),'blocked':0}}
    data['final_index']={'status':'finalized','sha256':canonical_sha256(data)}
    driver.write(path,data)
    return path


def test_full_plan_resolves_all_profiles_without_hardware(workspace):
    plan=collection.plan(workspace)
    assert plan['planned_campaign_attempts']==430
    assert len(plan['steps'])==5
    assert sum(s.get('conditions',0) for s in plan['steps'])==43
    assert [s['id'] for s in plan['steps']] == list(collection.DEFAULT_CAMPAIGNS)
    assert all(s['kind'] == 'campaign' for s in plan['steps'])
    resolver=collection.ConfigResolver(collection.ROOT)
    for step in plan['steps']:
        assert not step['energy_requested']
        for case in resolver.expand_campaign(collection.ROOT/step['source']):
            assert case['selections'].get('instruments', {})=={}
    assert collection.check(workspace)==plan
    assert not (workspace/'campaigns').exists()
    with pytest.raises(ValueError,match='new collection'):
        collection.plan(workspace)


def test_plan_and_source_drift_are_refused(workspace,monkeypatch):
    collection.plan(workspace,only=['thesis_kex'],include_ota=False)
    monkeypatch.setattr(collection,'source_identity',lambda:{'synthetic':'changed'})
    with pytest.raises(ValueError,match='source/submodule'):
        collection.check(workspace)
    monkeypatch.setattr(collection,'source_identity',lambda:{'synthetic':'fixed_source'})
    with (workspace/'profiles/thesis_kex.yaml').open('a') as f:f.write('\n# changed\n')
    with pytest.raises(ValueError,match='profile changed'):
        collection.check(workspace)


@pytest.mark.parametrize('count',[0,-1,1001])
def test_invalid_repetitions_fail_before_writes(workspace,count):
    with pytest.raises(ValueError,match='repetitions'):
        collection.plan(workspace,repetitions=count)
    assert not workspace.exists()


def test_failure_is_retained_and_not_retried_implicitly(workspace):
    collection.plan(workspace,only=['thesis_kex','thesis_application'],include_ota=False)
    calls=[]
    def runner(command,log=None):
        calls.append(command)
        if 'campaign-gateway' not in command:return 0
        name=Path(command[2]).stem
        manifest(workspace,name,'completed_with_failures' if name=='thesis_kex' else 'completed')
        return int(name=='thesis_kex')
    assert driver.execute(workspace,runner=runner)==1
    assert len([c for c in calls if 'campaign-gateway' in c])==2
    calls.clear()
    assert driver.execute(workspace,runner=runner)==1
    assert not any('campaign-gateway' in c for c in calls)
    assert driver.read(workspace/'state.json')['steps']['thesis_kex']['status']=='completed_with_failures'


def test_cleanup_failure_stops_next_campaign(workspace):
    collection.plan(workspace,only=['thesis_kex','thesis_application'],include_ota=False)
    hardware=[]
    def runner(command,log=None):
        if 'campaign-gateway' in command:
            hardware.append(command)
            manifest(workspace,'thesis_kex',cleanup='failed')
            return 1
        return 0
    assert driver.execute(workspace,runner=runner)==1
    assert len(hardware)==1


def test_interruption_resumes_owned_campaign_and_keeps_history(workspace):
    collection.plan(workspace,only=['thesis_kex'],include_ota=False)
    def interrupted(command,log=None):
        if 'campaign-gateway' in command:
            manifest(workspace,'thesis_kex',state='failed')
            raise KeyboardInterrupt
        return 0
    with pytest.raises(KeyboardInterrupt):driver.execute(workspace,runner=interrupted)
    state=driver.read(workspace/'state.json')
    assert state['steps']['thesis_kex']['status']=='interrupted'
    calls=[]
    def resumed(command,log=None):
        calls.append(command)
        if 'campaign-gateway' in command:
            assert '--resume' in command
            manifest(workspace,'thesis_kex')
        return 0
    assert driver.execute(workspace,runner=resumed)==0
    assert len(driver.read(workspace/'state.json')['history'])==2


@pytest.mark.parametrize('body,rc,status',[
    ('<testcase/> '*8,0,'completed'),
    ('<testcase><skipped/></testcase>'+'<testcase/> '*7,0,'completed_with_failures'),
    ('<testcase/> '*7,0,'completed_with_failures'),
    ('<testcase/> '*8,1,'completed_with_failures'),
])
def test_ota_skips_and_missing_cases_are_not_success(tmp_path,body,rc,status):
    path=tmp_path/'junit.xml';path.write_text('<testsuites><testsuite>'+body+'</testsuite></testsuites>')
    assert driver.ota_verdict(path,rc)[0]==status


def test_campaign_seal_tampering_is_not_success(workspace):
    path=manifest(workspace,'thesis_kex')
    value=driver.read(path);value['summary']['completed']=99;driver.write(path,value)
    assert driver.campaign_verdict(path,0)[:2]==('blocked',False)


def test_valid_manifest_with_wrong_planned_count_is_refused(workspace):
    path=manifest(workspace,'thesis_kex')
    assert driver.campaign_verdict(path,0,expected_attempts=100)[:2]==('blocked',False)


def test_resume_does_not_skip_a_missing_retained_verdict(workspace):
    collection.plan(workspace,only=['thesis_kex'],include_ota=False)
    def runner(command,log=None):
        if 'campaign-gateway' in command:manifest(workspace,'thesis_kex')
        return 0
    assert driver.execute(workspace,runner=runner)==0
    driver.campaign_manifest(workspace,'thesis_kex').unlink()
    with pytest.raises(ValueError,match='verdict changed or disappeared'):
        driver.execute(workspace,runner=runner)


def test_annotations_remain_explicit():
    assert collection.annotations({'energy':None,'network':None})['energy'] is None
    with pytest.raises(ValueError):collection.annotations({'energy':{'electrical_boundary':'board'}})
    with pytest.raises(ValueError):collection.annotations({'network':{'client_ip':'not-an-address','evidence_reference':'lease'}})


def test_one_factor_designs_do_not_pool_authentication_or_network_axes():
    import yaml
    from types import SimpleNamespace
    from framework.timing_summary import leaves
    from framework.timing_dataset_loader import load_dataset
    for name in collection.CAMPAIGNS:
        profile=yaml.safe_load((ROOT/'configs/campaigns'/(name+'.yaml')).read_text())
        designs=collection.analysis_specs(name,profile)
        assert designs and all(d['baseline'] in d['values'] for d in designs)
        for d in designs:
            assert len(d['id'])<=80
            if name=='thesis_authentication':
                assert d['filters']['tls_kex']=='secp256r1'
                assert ('auth_mode' in d['filters']) != ('tls_auth' in d['filters'])
            if name.startswith('thesis_network_') and not name.endswith('_plaintext'):
                assert d['filters']['tls_kex'] in ('secp256r1','SecP256r1MLKEM768')
                data=SimpleNamespace(runs=[{'controls':{'network_configured':dict(rate_kbit=1,rtt_ms=0,loss_percent=0,mtu=1500)}}])
                treatment=collection.make_spec(d,data)['treatment']
                assert len([v for v in treatment if v.startswith('controls.network_configured.')])==1


def test_reanalysis_keeps_plan_hash_checks_and_run_source_guard(workspace, monkeypatch):
    collection.plan(workspace, only=['thesis_repeated_tls'], include_ota=False)
    monkeypatch.setattr(collection, 'source_identity', lambda: {'new': 'analysis_revision'})
    with pytest.raises(ValueError, match='source/submodule'):
        collection.check(workspace)
    assert collection.check(workspace, verify_source=False)['steps'][0]['id'] == 'thesis_repeated_tls'
    with (workspace/'profiles/thesis_repeated_tls.yaml').open('a') as f:
        f.write('\n# tampered\n')
    with pytest.raises(ValueError, match='profile changed'):
        collection.check(workspace, verify_source=False)


def test_repeated_tls_payload_controls_are_inapplicable():
    from types import SimpleNamespace
    design = {'id':'thesis_repeated_tls_cert_secp256r1_server', 'field':'tls_auth',
        'values':['rsa3072','mldsa65'], 'baseline':'rsa3072', 'filters':{}}
    result = collection.make_spec(design, SimpleNamespace(runs=[]))
    assert set(result['not_applicable']) == {'payload_bytes', 'chunk_bytes'}


def test_ota_lifecycle_requires_explicit_opt_in(workspace):
    plan = collection.plan(workspace, only=['thesis_kex'], include_ota=True)
    assert plan['steps'][-1]['id'] == 'ota_lifecycle'
    assert plan['steps'][-1]['scenario_tests'] == 8


def test_comparison_workloads_and_tls_reference_are_matched(workspace):
    collection.plan(workspace)
    resolver = collection.ConfigResolver(collection.ROOT)
    for name in ('thesis_kex', 'thesis_authentication', 'thesis_application_plaintext'):
        cases = resolver.expand_campaign(workspace/'profiles'/f'{name}.yaml')
        assert all(c['selections']['instruments'] == {'energy': 'esp32_ina228'} for c in resolver.expand_campaign(name))
        for case in cases:
            mqtt = resolver.to_legacy_bundle(case, resolve_secrets=False)['experiment']['mqtt']
            assert mqtt['transfer']['payload_bytes'] == 204800
            assert mqtt['transfer']['chunk_bytes'] == 400
            if name == 'thesis_application_plaintext':
                assert mqtt['tls'] == {'mode':'plaintext', 'authentication':'server'}
            else:
                assert mqtt['tls']['tls_version'] == 'tls1.3'
        if name == 'thesis_kex':
            assert all(c['choices']['tls_auth'] == 'ecdsa-p256' and c['choices']['auth_mode'] == 'server' for c in cases)
            assert any(c['choices']['tls_kex'] == 'secp256r1' for c in cases)
        elif name == 'thesis_authentication':
            assert all(c['choices']['tls_kex'] == 'secp256r1' for c in cases)
            assert {c['choices']['auth_mode'] for c in cases if c['choices']['tls_auth'] == 'ecdsa-p256'} == {'server', 'mutual'}
        else:
            assert len(cases) == 1


def test_certificate_report_reference_follows_frozen_design():
    import yaml
    profile = yaml.safe_load((ROOT/'configs/campaigns/thesis_authentication.yaml').read_text())
    specs = collection.analysis_specs('thesis_authentication', profile)
    assert all(s['baseline'] == 'ecdsa-p256' for s in specs if s['field'] == 'tls_auth')
    profile.pop('analysis_baselines')
    # Historical authentication matrices also contained ECDSA but used RSA as reference.
    assert 'ecdsa-p256' in profile['matrix']['tls_auth']
    specs = collection.analysis_specs('thesis_authentication', profile)
    assert all(s['baseline'] == 'rsa3072' for s in specs if s['field'] == 'tls_auth')


def test_explicit_energy_off_overrides_auto_instrumentation(workspace):
    resolver = collection.ConfigResolver(collection.ROOT)
    _, data = resolver.load_campaign('thesis_network_loss')
    data['execution']['energy_monitoring'] = 'off'
    data['instruments'] = {'energy': 'esp32_ina228'}
    assert collection.instrument_campaign(resolver, data) is False
    assert data['instruments'] == {}
    data['execution']['energy_monitoring'] = 'invalid'
    with pytest.raises(ValueError, match='energy_monitoring'):
        collection.instrument_campaign(resolver, data)


def test_energy_is_opt_in_and_policy_ui_agree(workspace):
    from framework.campaign_executor import ExecutionPolicy
    from framework.campaign_menu import value_for
    resolver = collection.ConfigResolver(collection.ROOT)
    _, data = resolver.load_campaign('thesis_kex')
    assert ExecutionPolicy.from_mapping(data['execution']).energy_monitoring == 'off'
    assert value_for(data, ('Execution', 'Energy monitoring', ['execution', 'energy_monitoring'], 'single', [])) == 'off'
    assert collection.instrument_campaign(resolver, data) is False
    assert data['execution']['energy_monitoring'] == 'off' and not data['instruments']
    data['execution']['energy_monitoring'] = 'auto'
    assert collection.instrument_campaign(resolver, data) is True
    assert ExecutionPolicy.from_mapping(data['execution']).as_dict()['energy_monitoring'] == 'auto'
    for name in ('thesis_energy', 'thesis_energy_plaintext', 'ready_metrics_2_energy', 'tls_matrix_energy', 'secure_boot_energy'):
        _, explicit = resolver.load_campaign(name)
        assert collection.instrument_campaign(resolver, explicit) is True
