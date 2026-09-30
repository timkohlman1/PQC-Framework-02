"""Offline thesis pilot configuration design checks, not hardware qualification."""
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from framework.config_resolver import ConfigResolver

CATALOG=json.loads((ROOT/'configs/analysis/thesis_campaigns.json').read_text())['campaigns']

@pytest.mark.parametrize('name',sorted(CATALOG))
def test_profiles_resolve_and_keep_measurement_modes_separate(name):
    cases=ConfigResolver(ROOT).expand_campaign(name)
    assert len(cases)==CATALOG[name]['conditions']
    for case in cases:
        assert case['execution']['repetitions']==10
        assert case['choices']['boot_stack_profiling'] is False
        assert case['choices']['boot_uart_diagnostics'] is False
        assert ('energy' in case['selections'].get('instruments',{}))==CATALOG[name]['energy']

@pytest.mark.parametrize('axis,field',[('rate','rate_kbit'),('rtt','rtt_ms'),('loss','loss_percent'),('mtu','mtu')])
def test_network_sweeps_have_classical_hybrid_and_one_factor(axis,field):
    resolver=ConfigResolver(ROOT)
    cases=resolver.expand_campaign('thesis_network_'+axis)
    assert {c['choices']['tls_kex'] for c in cases}=={'secp256r1','SecP256r1MLKEM768'}
    reference=resolver.load_profile('network_condition','trial_reference').data['impairment']
    for case in cases:
        values=resolver.load_profile('network_condition',case['choices']['network_condition']).data['impairment']
        assert {k for k in values if values[k]!=reference[k]} <= {field}


def test_ota_overhead_holds_bank_layout_fixed_and_has_no_energy():
    cases=ConfigResolver(ROOT).expand_campaign('thesis_ota_overhead')
    assert {c['choices']['firmware_mode'] for c in cases}=={'dual_bank_no_ota','dual_bank_ota'}
    assert all(not c['selections'].get('instruments') for c in cases)


def test_resolved_snapshot_records_actual_experiment_qos():
    from framework.run_evidence import build_resolved_case_snapshot
    resolver=ConfigResolver(ROOT)
    for case in resolver.expand_campaign('thesis_kex'):
        bundle=resolver.to_legacy_bundle(case,resolve_secrets=False)
        assert bundle['experiment']['mqtt']['qos']==0
        assert build_resolved_case_snapshot(bundle)['effective_non_secret_parameters']['mqtt']['qos']==0
