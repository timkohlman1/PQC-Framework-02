"""Broker-only choice, immutable identities and deployed evidence contracts."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml
from framework.config_resolver import ConfigResolver, ResolutionError
from framework.campaign_executor import broker_identity, _broker_ctl_command
from framework.campaign_editor import options
from framework.campaign_menu import fields
from framework.run_evidence import build_run_provenance_snapshot

ROOT = Path(__file__).resolve().parents[2]

def resolve(tmp_path, value=None, **choices):
    data = yaml.safe_load((ROOT/'configs/campaigns/mldsa_memory_mutual.yaml').read_text())
    data['matrix'] = {}
    data['fixed'].update(tls_kex='secp256r1', tls_auth='ecdsa-p256', auth_mode='server')
    data['fixed'].update(choices)
    if value is not None: data['fixed']['broker_tcp_nodelay'] = value
    path=tmp_path/'campaign.yaml'; path.write_text(yaml.safe_dump(data))
    resolver=ConfigResolver(ROOT)
    case,=resolver.expand_campaign(path)
    return case,resolver.to_legacy_bundle(case,resolve_secrets=False)

@pytest.mark.parametrize('choices', [{}, {'auth_mode':'mutual'}, {'tls_kex':'ML_KEM_768'},
    {'tls_kex':'SecP256r1MLKEM768','auth_mode':'mutual'},
    {'mqtt_transport':'plaintext','tls_auth':'rsa3072'}])
def test_identity_resolution_and_reuse(tmp_path,choices):
    original, default=resolve(tmp_path,**choices)
    off, off_bundle=resolve(tmp_path,False,**choices)
    on, on_bundle=resolve(tmp_path,True,**choices)
    assert default['experiment']['mqtt']['broker_tcp_nodelay'] is True
    assert original['choices']['broker_tcp_nodelay'] is True
    assert len({c['provenance']['firmware_identity'] for c in (original,off,on)}) == 1
    assert off['provenance']['configuration_identity'] != on['provenance']['configuration_identity']
    assert broker_identity(off_bundle,off) != broker_identity(on_bundle,on)
    assert broker_identity(default,original) == broker_identity(on_bundle,on)
    assert on_bundle['experiment']['mqtt']['broker_tcp_nodelay'] is True

@pytest.mark.parametrize('value',['true','false',0,1,[],{}])
def test_invalid(tmp_path,value):
    with pytest.raises(ResolutionError,match='must be a boolean'): resolve(tmp_path,value)

def test_editor_and_controller_setting():
    assert any(f[2]==['broker_tcp_nodelay'] and f[4]==[None,False,True] for f in fields(options(ROOT)))
    for value in (False,True):
        command=_broker_ctl_command(ROOT,'start',profile='oqs',broker_tcp_nodelay=value)
        assert command[-2:]==['--tcp-nodelay',str(value).lower()] or command[command.index('--tcp-nodelay')+1]==str(value).lower()
    assert '--tcp-nodelay' not in _broker_ctl_command(ROOT,'start',profile='reporting',broker_tcp_nodelay=True)

def controller():
    spec=importlib.util.spec_from_file_location('nodelay_ctl',ROOT/'experiment/mqtt-broker/scripts/mqtt_broker_ctl.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module

@pytest.mark.parametrize('value',['false','true'])
def test_live_config_is_copied_and_start_targets_only_selected_service(tmp_path,monkeypatch,value):
    ctl=controller(); calls=[]
    args=ctl.build_parser().parse_args(['start','--profile','oqs','--tcp-nodelay',value])
    monkeypatch.setattr(ctl,'compose_remote',lambda args,cmd:calls.append(cmd))
    ctl.start(args)
    assert calls[0][-1]=='mqtt-oqs'
    assert f'MQTT_TCP_NODELAY={value}' in ctl._compose_environment(args)
    output=tmp_path/'effective.conf'
    args=ctl.build_parser().parse_args(['effective-config','--profile','oqs','--tcp-nodelay',value,'--output',str(output)])
    data=f'set_tcp_nodelay {value}\nlistener 8883\n'.encode()
    commands=[]
    def run(cmd,**kwargs):
        commands.append(cmd);return SimpleNamespace(returncode=0,stdout=data)
    monkeypatch.setattr(ctl.subprocess,'run',run)
    ctl.effective_config(args)
    assert output.read_bytes()==data
    assert '/proc/1/cmdline' in commands[0][-1]
    monkeypatch.setattr(ctl.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout=b''))
    with pytest.raises(SystemExit,match='inconsistent'): ctl.effective_config(args)

def test_reporting_has_no_parameter_and_provenance_is_not_backfilled():
    compose=yaml.safe_load((ROOT/'experiment/mqtt-broker/compose.yaml').read_text())
    assert 'MQTT_TCP_NODELAY' not in str(compose['services']['mqtt-reporting'])
    for name,service in compose['services'].items():
        if name=='mqtt-reporting':continue
        assert service['environment']['MQTT_TCP_NODELAY']=='${MQTT_TCP_NODELAY:-true}'
        assert '-c /tmp/mosquitto-runtime.conf' in service['entrypoint'][-1]
    assert 'mqtt_broker' not in build_run_provenance_snapshot({})['records']
    evidence={'tcp_nodelay':{'effective':True,'status':'verified'}}
    assert build_run_provenance_snapshot({'mqtt_broker':evidence})['records']['mqtt_broker']==evidence

@pytest.mark.parametrize('effective', [False, True, None])
def test_analysis_requires_indexed_effective_config(tmp_path,effective):
    import json
    from timing_dataset_support import make_run, reseal
    from framework.run_evidence import register_artifact
    from framework.timing_dataset import export_dataset
    from framework.timing_dataset_loader import load_dataset
    root=make_run(tmp_path/'run')
    snapshot=root/'resolved-case.json'; data=json.loads(snapshot.read_text())
    data['effective_non_secret_parameters']['mqtt']['broker_tcp_nodelay']=True
    snapshot.write_text(json.dumps(data))
    manifest_path=root/'manifest.json';manifest=json.loads(manifest_path.read_text())
    if effective is not None:
        config=root/'mqtt-broker-effective.conf'; config.write_text(f'set_tcp_nodelay {str(effective).lower()}\n')
        register_artifact(manifest,result_dir=root,role='mqtt_broker_effective_config',path=config,stage='synthetic',tool=__name__)
        manifest_path.write_text(json.dumps(manifest))
    reseal(root)
    output=tmp_path/'analysis';export_dataset(run_dirs=[root],output=output)
    run=load_dataset(output).runs[0]
    assert run['controls']['mqtt']['broker_tcp_nodelay_effective'] is (True if effective is True else None)
    if effective is not True:
        assert any('broker_effective_config' in str(i) for i in load_dataset(output).issues)


def test_historical_analysis_does_not_invent_off(tmp_path):
    from timing_dataset_support import make_run
    from framework.timing_dataset import export_dataset
    from framework.timing_dataset_loader import load_dataset
    root=make_run(tmp_path/'old');output=tmp_path/'analysis'
    export_dataset(run_dirs=[root],output=output)
    assert 'broker_tcp_nodelay_effective' not in load_dataset(output).runs[0]['controls']['mqtt']


def test_reuse_reconfiguration_and_failed_cleanup(tmp_path):
    from framework.campaign_executor import CampaignExecutor, CampaignCleanupError
    off,b0=resolve(tmp_path,False);on,b1=resolve(tmp_path,True)
    calls=[]
    def runner(command,cwd):
        calls.append(command)
        return SimpleNamespace(returncode=0,stdout='running healthy',stderr='')
    executor=CampaignExecutor(ROOT,results_root=tmp_path/'results',runner=runner)
    directory=tmp_path/'control';directory.mkdir()
    executor._ensure_broker(bundle=b0,identity=broker_identity(b0,off),campaign_root=directory)
    before=len(calls)
    executor._ensure_broker(bundle=b0,identity=broker_identity(b0,off),campaign_root=directory)
    assert all(cmd[2]=='status' for cmd in calls[before:])
    before=len(calls)
    executor._ensure_broker(bundle=b1,identity=broker_identity(b1,on),campaign_root=directory)
    assert [cmd[2] for cmd in calls[before:]][:4]==['stop','deploy','start','start']
    experiment_start=next(cmd for cmd in calls[before:] if cmd[2]=='start' and 'reporting' not in cmd)
    assert experiment_start[experiment_start.index('--tcp-nodelay')+1]=='true'
    def failed_stop(command,cwd):
        calls.append(command)
        return SimpleNamespace(returncode=1 if command[2]=='stop' else 0,stdout='running',stderr='')
    executor.runner=failed_stop
    before=len(calls)
    with pytest.raises(CampaignCleanupError):
        executor._ensure_broker(bundle=b0,identity=broker_identity(b0,off),campaign_root=directory)
    assert [cmd[2] for cmd in calls[before:]]==['stop']


@pytest.mark.parametrize("value", [False, True])
def test_effective_setting_survives_broker_collection(tmp_path, monkeypatch, value):
    import json
    import experiment

    bundle = {"experiment": {"mqtt": {"broker_profile": "plaintext", "broker_tcp_nodelay": value}}}
    (tmp_path / "manifest.json").write_text("{}")
    def step(**kwargs):
        if kwargs["subcommand"] == "effective-config":
            (tmp_path / "mqtt-broker-effective.conf").write_text(
                f"set_tcp_nodelay {str(value).lower()}\nlistener 1883\n")
        return SimpleNamespace(return_code=0)
    monkeypatch.setattr(experiment, "_run_mqtt_broker_step", step)
    assert experiment._retain_broker_config(bundle=bundle, repo_root=ROOT, result_dir=tmp_path)
    assert experiment._collect_and_stop_managed_mqtt_broker(
        bundle=bundle, repo_root=ROOT, result_dir=tmp_path) == (0, 0)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    record = manifest["broker_tcp_nodelay"]
    assert record["effective"] is value
    assert record["status"] == "verified"
    assert manifest["mqtt_broker"]["cleanup_completed"] is True
    assert build_run_provenance_snapshot(manifest)["records"]["broker_tcp_nodelay"] == record
    assert "broker_tcp_nodelay" not in build_run_provenance_snapshot({})["records"]


def test_historical_resolved_case_keeps_off_execution_without_inventing_observation(tmp_path):
    case, _ = resolve(tmp_path)
    case["choices"].pop("broker_tcp_nodelay")
    bundle = ConfigResolver(ROOT).to_legacy_bundle(case, resolve_secrets=False)
    assert bundle["experiment"]["mqtt"]["broker_tcp_nodelay"] is False
    assert "broker_tcp_nodelay" not in build_run_provenance_snapshot({})["records"]


def test_controller_defaults_on():
    ctl = controller()
    for command in ("start", "status", "effective-config"):
        args = ctl.build_parser().parse_args([command, "--profile", "oqs"])
        assert args.tcp_nodelay == "true"
