"""Configuration safety and notebook-selection coverage; no hardware execution."""
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from framework.config_resolver import ConfigResolver
from framework.campaign_executor import ExecutionPolicy
from framework.run_evidence import build_capture_contract
from framework.timing_summary import matches


def test_matrix_has_twelve_distinct_firmware_conditions_and_120_attempts():
    cases = ConfigResolver(ROOT).expand_campaign('tls_matrix_energy')
    assert len(cases) == 12
    expected = set(itertools.product(['secp256r1', 'SecP256r1MLKEM768', 'ML_KEM_768'], ['ecdsa-p256', 'mldsa65'], ['server','mutual']))
    assert {tuple(c['choices'][k] for k in ('tls_kex','tls_auth','auth_mode')) for c in cases} == expected
    assert len({c['provenance']['firmware_identity'] for c in cases}) == 12
    assert sum(ExecutionPolicy.from_mapping(c['execution']).repetitions for c in cases) == 120


def test_every_condition_keeps_energy_and_timing_controls():
    resolver = ConfigResolver(ROOT)
    for case in resolver.expand_campaign('tls_matrix_energy'):
        assert case['selections']['instruments'] == {'energy':'esp32_ina228'}
        assert case['execution']['reset_between_runs'] == 'hardware_reset'
        assert case['choices']['secure_boot'] == 'integrity_sha256'
        assert case['choices']['firmware_mode'] == 'single_bank'
        assert case['choices']['boot_stack_profiling'] is False
        assert case['choices']['boot_uart_diagnostics'] is False
        bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
        exp = bundle['experiment']
        assert exp['firmware']['application'] == 'mqtt_ready_metrics_2'
        assert exp['firmware']['uart_output_mode'] == 'minimal'
        assert exp['mqtt']['transfer']['payload_bytes'] == 204800
        assert exp['mqtt']['transfer']['chunk_bytes'] == 400
        assert exp['mqtt']['tls']['tls_version'] == 'tls1.3'
        assert exp['mqtt']['tls']['certificate_profile'] == case['choices']['tls_auth']
        assert exp['mqtt']['tls']['authentication'] == case['choices']['auth_mode']
        assert not exp['network']['degradation']['enabled']
        assert exp['instruments']['energy']['profile'] == 'esp32_ina228'
        contract = build_capture_contract(bundle)
        assert contract['features']['energy'] is True
        energy = [item for item in contract['items'] if item['role'] == 'energy_result_stream']
        assert energy and all(item['requirement'] == 'required' for item in energy)


def test_analysis_preset_covers_each_condition_once_without_waiving_controls():
    spec = json.loads((ROOT/'notebooks/tls_matrix_energy.example.json').read_text())
    assert spec['independent_runs'] is False
    assert spec['not_applicable'] == {} and spec['exclude_runs'] == {}
    assert spec['baseline'] == 'secp256r1__ecdsa-p256__server'
    resolver = ConfigResolver(ROOT)
    for case in resolver.expand_campaign('tls_matrix_energy'):
        run = {**case['choices'], 'workload': 'ready_metrics_2'}
        assert matches(run, spec['filters'])
        assert sum(matches(run, selector) for selector in spec['conditions'].values()) == 1
    assert 'evidence_class' not in spec['treatment']


def test_campaign_usage_documents_offline_limits_and_commands():
    doc=(ROOT/'docs/005_remote_flash_workflow.md').read_text()
    section=doc.split('## TLS matrix with energy and notebook analysis',1)[1].split('\n## ',1)[0]
    for text in ('tls_matrix_energy', '120', 'energy', 'independent_runs', 'unknown',
                 './scripts/dev.sh campaign-gateway tls_matrix_energy', '--verify-source-inputs'):
        assert text in section
