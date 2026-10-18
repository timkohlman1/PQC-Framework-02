"""Responder contracts without gateway/network access."""
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from framework import mqtt_responder as r


def test_chunk_preparation_preserves_tail_and_exact_application_bytes():
    assert [len(line) for line in r.payload_lines(1024,400).splitlines()] == [400,400,224]
    assert b''.join(r.payload_lines(1024,400).splitlines()) == b'A'*1024
    with pytest.raises(ValueError): r.payload_lines(100,101)


def test_all_clients_are_persistent_and_loopback_only():
    config=dict(host='127.0.0.1',port=1884,tls_args=[],oqs=False,timeout=90,
        response_topic='pqc/ready',request_topic='pqc/request',payload_topic='pqc/payload')
    commands=r.client_commands(config)
    assert len(commands)==3
    assert commands['publisher'][1][-1]=='-l'
    assert all('docker' not in c and c[:3]==['stdbuf','-oL','-eL'] for _,c in commands.values())
    with pytest.raises(ValueError): r.client_commands({**config,'host':'10.1.1.18'})


def test_readiness_and_verified_cleanup_are_both_required():
    def output(events):return '\n'.join('PQC_MQTT_RESPONDER_EVENT '+json.dumps(dict(e,
        contract=r.CONTRACT,monotonic_ns=i+1)) for i,e in enumerate(events))
    start=[dict(event='client_started',role=role) for role in ('observer','request','publisher')]
    ready=dict(event='ready',connections=3,payload_prepared=True,endpoint='broker_namespace_loopback',network_namespace='net:[123]')
    clean=dict(event='cleanup',verified=True,return_code=0)
    valid=start+[ready,dict(event='request_received'),dict(event='payload_enqueued'),dict(event='complete'),clean]
    assert r.evidence(output(valid))['verified']
    assert r.evidence(output(start+[ready,{**clean,'return_code':27,'requested':False}]))['verified']
    for events in ([ready], [clean], valid+[clean], valid+[dict(event='failure')],
                   valid[:-1]+[{**clean,'verified':False}], valid[:-1]+[{**clean,'return_code':70}],
                   start+[ready,clean], [ready]+start+valid[4:], valid[:4]+[dict(event='complete')]+valid[4:]):
        assert not r.evidence(output(events))['verified']


def test_loopback_feeder_not_exposed_on_network():
    import yaml
    services=yaml.safe_load((ROOT/'experiment/mqtt-broker/compose.yaml').read_text())['services']
    for name in ('mqtt-classical','mqtt-classical-server-auth','mqtt-oqs','mqtt-oqs-mtls'):
        assert '127.0.0.1:1884:1884' in services[name]['ports']
        assert not any(p.startswith('1884:') or p.startswith('0.0.0.0:1884:') for p in services[name]['ports'])


def test_unverified_cleanup_survives_final_manifest_compaction():
    from framework.run_evidence import compact_final_manifest
    manifest={'execution_safety':{'status':'unverified','reason':'remote completion unverified'},
              'mqtt_e2e':{'transient_diagnostics':'discard'}}
    compact_final_manifest(manifest)
    assert manifest['execution_safety']['status']=='unverified'
    assert manifest['execution_safety']['reason']=='remote completion unverified'
    assert 'mqtt_e2e' not in manifest


def test_legacy_identity_is_preserved_and_impaired_legacy_delivery_is_excluded():
    assert r.delivery_eligible(r.LEGACY_CONTRACT, False)
    assert not r.delivery_eligible(r.LEGACY_CONTRACT, True)
    assert r.delivery_eligible(r.CONTRACT, True)
    assert not r.delivery_eligible('legacy_or_unverified_on_request', False)


def test_safe_cleanup_does_not_promote_incomplete_acquisition():
    events=[dict(event='client_started',role=role) for role in ('observer','request','publisher')]
    events += [dict(event='ready',connections=3,payload_prepared=True,
                  endpoint='broker_namespace_loopback',network_namespace='net:[123]'),
               dict(event='request_received'),dict(event='payload_enqueued'),
               dict(event='cleanup',verified=True,return_code=71,requested=True)]
    def rendered(items, contract=r.CONTRACT):
        return '\n'.join('PQC_MQTT_RESPONDER_EVENT '+json.dumps(dict(e,contract=contract,monotonic_ns=i+1)) for i,e in enumerate(items))
    result=r.evidence(rendered(events))
    assert result['cleanup_verified'] and not result['verified']
    negative=events[:-1]+[dict(event='publisher_complete'),{**events[-1],'return_code':28}]
    assert r.evidence(rendered(negative))['verified']
    assert not r.evidence(rendered(negative,r.LEGACY_CONTRACT))['verified']
    assert not r.evidence(rendered(negative[:-2]+[negative[-1]]))['verified']
    for bad in ({'verified':False},{'return_code':True}):
        assert not r.evidence(rendered(events[:-1]+[{**events[-1],**bad}]))['cleanup_verified']


def test_namespace_launcher_is_bound_to_a_known_broker_and_drops_privilege():
    script=r.namespace_prefix('mqtt-oqs-mtls')
    assert 'mqtt-oqs-mtls' in script and 'State.Pid' in script
    assert 'readlink /proc/self/ns/net' in script
    with pytest.raises(ValueError):r.namespace_prefix('other; touch /tmp/unsafe')
