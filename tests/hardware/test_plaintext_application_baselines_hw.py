"""Self-owned live application qualification; never inferred from build evidence."""
import json
from pathlib import Path
import pytest
from framework.hardware_test_support import HardwareFileRun, session_result_dir
from framework.result_collector import _parse_raw_stream

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.hardware, pytest.mark.long]

@pytest.mark.parametrize('campaign', ['ready_metrics_plaintext', 'ready_metrics_2_plaintext'])
def test_plaintext_application(campaign, pytestconfig, pqc_require_capabilities):
    pqc_require_capabilities('local_toolchain', 'gateway', 'flash_helper', 'uart_device', strict_mode='hardware')
    context = HardwareFileRun.create(repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig),
        module_name='test_plaintext_application_baselines_hw')
    case = context.case(template=campaign)
    run, _ = context.run_experiment(case=case, name=campaign)
    manifest = json.loads((run/'manifest.json').read_text())
    assert manifest['capture_acceptance']['accepted'] is True
    assert manifest['execution_outcome']['status'] == 'completed'
    assert manifest['capture_contract']['experiment_class'] == 'mqtt_plaintext_runtime'
    roles = {a['role']: a for a in manifest['artifacts']}
    assert roles['tls_key_log']['requirement'] == 'not_applicable'
    snapshot = json.loads((run/roles['resolved_case_snapshot']['path']).read_text())
    mqtt = snapshot['effective_non_secret_parameters']['mqtt']
    assert mqtt['tls']['mode'] == 'plaintext' and mqtt['broker']['port'] == 1883
    stream = _parse_raw_stream(run/'mqtt-reporting-raw.ndjson', run.name, ('stm32',), {'stm32':1})
    assert stream.passed and stream.completion_count == 1
    # The experiment runner independently validates Ready Metrics protocol messages,
    # RM2 transfer completion/byte counts/checkpoints and broker evidence before success.
