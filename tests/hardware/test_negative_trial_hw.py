"""Self-contained negative trial, plaintext reporting isolation and TLS recovery."""
import json
from pathlib import Path

import pytest
import yaml

from framework.campaign_executor import CampaignExecutor
from framework.hardware_test_support import HardwareFileRun, session_result_dir
from framework.trial_outcome import verified_failure

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.hardware, pytest.mark.long]


@pytest.mark.parametrize('transport', ['tls', 'plaintext'])
def test_total_loss_reports_failure_and_next_reference_trial_succeeds(pytestconfig, pqc_require_capabilities, transport):
    pqc_require_capabilities('local_toolchain', 'gateway', 'flash_helper', 'uart_device', strict_mode='hardware')
    context = HardwareFileRun.create(repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig),
                                     module_name='test_negative_trial_hw')
    context.case(template='baseline', workload='ready_metrics_2', repetitions=1, instruments={})
    source = context.generated_root / 'default/campaign.yaml'
    data = yaml.safe_load(source.read_text())
    data['fixed'].pop('network_condition', None)
    if transport == 'plaintext':
        data['fixed']['mqtt_transport'] = 'plaintext'
        for key in ('tls_kex', 'tls_auth', 'auth_mode'):
            data['fixed'].pop(key, None)
    data['matrix'] = {'network_condition': ['trial_loss_100', 'trial_reference']}
    data['execution'].update(energy_monitoring='off', workload_failures='record')
    source.write_text(yaml.safe_dump(data, sort_keys=False))
    (context.evidence_root / 'configuration/default/campaign.yaml').write_bytes(source.read_bytes())
    path = CampaignExecutor(ROOT, results_root=context.evidence_root / 'campaign',
                            stop_on_error=True).execute(source)
    state = json.loads(path.read_text())
    assert state['state'] == 'completed_with_failures', f'evidence: {path}'
    assert state['cleanup']['status'] == 'passed'
    assert state['summary'] == {'planned': 2, 'completed': 1, 'failed': 1, 'blocked': 0}
    negative, success = state['runs']
    assert negative['network_condition'] == 'trial_loss_100' and negative['accepted_failure']
    assert verified_failure(Path(negative['manifest']))
    assert success['network_condition'] == 'trial_reference' and success['state'] == 'completed'
    for run in state['runs']:
        manifest = json.loads(Path(run['manifest']).read_text())
        assert manifest['capture_acceptance']['accepted'] is True
