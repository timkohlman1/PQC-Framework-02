"""Self-owned live validation of the matched thesis baseline transports."""
import json
from pathlib import Path

import pytest
import yaml

from framework.config_resolver import ConfigResolver
from framework.energy_analysis import acquisitions, Integral, workload_bounds, map_boundary
from framework.hardware_test_support import HardwareFileRun, session_result_dir

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.hardware, pytest.mark.long]


@pytest.mark.parametrize('mode', ['server', 'mutual', 'plaintext', 'secure_boot', 'secure_boot_stack'])
def test_thesis_baseline(mode, pytestconfig, pqc_require_capabilities):
    pqc_require_capabilities('local_toolchain', 'gateway', 'flash_helper', 'uart_device', strict_mode='hardware')
    context = HardwareFileRun.create(repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig),
        module_name='test_thesis_baselines_hw')
    boot = mode.startswith('secure_boot')
    name = mode if boot else 'thesis_application_plaintext' if mode == 'plaintext' else 'thesis_authentication'
    profile = yaml.safe_load((ROOT/'configs/campaigns'/f'{name}.yaml').read_text())
    profile['id'] = 'qualify_thesis_' + mode
    if boot:
        profile['matrix']['secure_boot'] = ['integrity_sha256']
    elif mode != 'plaintext':
        profile['matrix']['tls_auth'] = ['ecdsa-p256']
        profile['matrix']['auth_mode'] = [mode]
    profile['execution']['repetitions'] = 1
    source = context.generated_root/'campaign.yaml'
    source.write_text(yaml.safe_dump(profile, sort_keys=False))
    resolver = ConfigResolver(ROOT)
    resolved = resolver.materialize_campaign(source, context.generated_root/'resolved')
    cases = list((resolved/'cases').glob('*.yaml'))
    assert len(cases) == 1
    run, _ = context.run_experiment(case=cases[0], name=mode)
    manifest = json.loads((run/'manifest.json').read_text())
    assert manifest['execution_outcome']['status'] == 'completed'
    assert manifest['capture_acceptance']['accepted'] is True
    roles = {a['role']: a for a in manifest['artifacts']}
    snapshot = json.loads((run/roles['resolved_case_snapshot']['path']).read_text())
    mqtt = snapshot['effective_non_secret_parameters']['mqtt']
    if not boot:
        assert mqtt['transfer']['payload_bytes'] == 204800
        assert mqtt['transfer']['chunk_bytes'] == 400
    energy = json.loads((run/'energy-capture.json').read_text())
    assert energy['passed'] and energy['capture_received'] and energy['workload_passed']
    assert energy['sample_count'] > 0
    assert roles['energy_result_stream']['acquisition']['status'] == 'available'
    trace = acquisitions(run/roles['energy_result_stream']['path'])[energy['capture_id']]
    assert trace['reason'] is None
    alignment = energy['alignment']
    pair = (alignment['stm32_start_us'], alignment['stm32_end_us'])
    bounds = workload_bounds(run/roles['stm32_result_stream']['path'], run.name, pair)
    complete = trace['complete']
    mapped = [map_boundary(t, *pair, complete['e0_us'], complete['e1_us']) for t in bounds]
    assert Integral(trace['samples'], complete['gap_limit_us']).interval(*mapped)['duration_s'] > 0
    if mode == 'plaintext':
        assert mqtt['tls'] == {'mode': 'plaintext', 'authentication': 'server'}
        assert roles['tls_key_log']['requirement'] == 'not_applicable'
    else:
        assert mqtt['tls']['certificate_profile'] == 'ecdsa-p256'
        assert mqtt['tls']['tls_version'] == 'tls1.3'
        assert mqtt['tls']['authentication'] == ('server' if boot else mode)
