"""Network pilot configuration and per-axis comparison constraints."""
import json
from pathlib import Path
from framework.config_resolver import ConfigResolver
from framework.network_analysis import comparison_axis, matched_comparisons
from prepare_network_selection import broker_clients
ROOT=Path(__file__).parents[2]


def test_trial_has_fifteen_attempts_and_one_firmware():
    resolver=ConfigResolver(ROOT);cases=resolver.expand_campaign('network_trial')
    assert len(cases)==5
    assert len({c['provenance']['firmware_identity'] for c in cases})==1
    assert sum(c['execution']['repetitions'] for c in cases)==15
    for c in cases:
        assert not c['selections'].get('instruments')
        assert c['choices']['tls_kex']=='SecP256r1MLKEM768'
        assert c['choices']['tls_auth']=='ecdsa-p256' and c['choices']['auth_mode']=='server'
        assert c['execution']['reset_between_runs']=='hardware_reset'
        assert not c['choices']['boot_uart_diagnostics'] and not c['choices']['boot_stack_profiling']
        bundle=resolver.to_legacy_bundle(c,resolve_secrets=False)
        assert bundle['experiment']['network']['degradation']['enabled'] is True
        assert bundle['experiment']['mqtt']['transfer']['payload_bytes']==204800


def test_each_preset_changes_one_axis_and_accepts_actual_profile_hash_paths():
    resolver=ConfigResolver(ROOT)
    cases={c['choices']['network_condition']:c for c in resolver.expand_campaign('network_trial')}
    for axis,key in [('rate','rate_kbit'),('rtt','rtt_ms'),('loss','loss_percent'),('mtu','mtu')]:
        spec=json.loads((ROOT/f'notebooks/network_trial_{axis}.json').read_text())
        assert spec['not_applicable']=={} and spec['independent_runs'] is False
        runs=[]
        for label,name in [('reference','trial_reference'),(axis,'validation_'+axis)]:
            condition=resolver.to_legacy_bundle(cases[name],resolve_secrets=False)['experiment']['network']['degradation']
            runs.append(dict(condition=label,run_key=name,network_condition=name,exclusion_reason=None,
                controls={'network_configured':{k:condition[k] for k in ['enabled','rate_kbit','rtt_ms','loss_percent','mtu']}}))
        assert comparison_axis(runs[:1],runs[1:])==(key,None)
        diff=dict(condition=axis,metric='tls_handshake',unit='us',reason=None,delta_median=1,percent_difference=10)
        selections={r['run_key']:{'window':{'kind':'retained_flow'}} for r in runs}
        result=matched_comparisons(runs,[diff],spec,selections)[0]
        assert result['reason'] is None and result['delta_median']==1
        spec['treatment'].append('controls.profile_hashes.tls_auth:rsa3072')
        assert matched_comparisons(runs,[diff],spec,selections)[0]['reason']=='non_network_treatment'


def test_exact_broker_client_identity_excludes_other_clients():
    text='\n'.join(f'New client connected from 10.0.0.2:{port} as {client} (p4, c1, k30).' for port,client in [(1,'pqc-stm32-a'),(2,'pqc-stm32-a-extra'),(3,'health'),(4,'responder')])
    assert broker_clients(text,'pqc-stm32-a')=={('10.0.0.2',1)}
