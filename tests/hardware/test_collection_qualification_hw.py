"""Fresh gateway qualification for failures seen in the first thesis collection."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
import yaml
from framework.hardware_test_support import HardwareFileRun, session_result_dir
ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.hardware, pytest.mark.long]

@pytest.mark.parametrize('name,repetitions', [('burst_tls',10), ('burst_plaintext',5), ('mutual_repeat',2), ('energy_plaintext',2)])
def test_collection_qualification(name, repetitions, pytestconfig, pqc_require_capabilities):
    pqc_require_capabilities('local_toolchain','gateway','flash_helper','uart_device', strict_mode='hardware')
    ctx = HardwareFileRun.create(repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig), module_name='test_collection_qualification_hw')
    profile = yaml.safe_load((ROOT/'configs/campaigns/thesis_application.yaml').read_text())
    profile.update(id='qualification_'+name, matrix={})
    profile['fixed'].update(tls_kex='secp256r1',tls_auth='rsa3072',auth_mode='server')
    profile['execution']['repetitions'] = repetitions
    profile['matrix'] = {'workload.transfer.payload_bytes':[204800], 'workload.transfer.chunk_bytes':[128]}
    if 'plaintext' in name:
        profile['fixed']['mqtt_transport'] = 'plaintext'
    if name == 'mutual_repeat':
        profile['workload'] = 'tls_handshake_repeat'
        profile['fixed']['auth_mode'] = 'mutual'
        profile['matrix'] = {'workload.iterations.handshakes_per_run':[5]}
    if name == 'energy_plaintext':
        profile['instruments'] = {'energy':'esp32_ina228'}
        profile['matrix']['workload.transfer.chunk_bytes'] = [400]
    source = ctx.generated_root/'campaign.yaml'
    source.write_text(yaml.safe_dump(profile))
    result = ctx.evidence_root/'campaigns'
    proc = subprocess.run([sys.executable,'scripts/run_campaign.py',str(source),'--results-root',str(result)],
        cwd=ROOT, text=True, capture_output=True)
    (ctx.evidence_root/'stdout.log').write_text(proc.stdout)
    (ctx.evidence_root/'stderr.log').write_text(proc.stderr)
    assert proc.returncode == 0, f'qualification failed; evidence: {ctx.evidence_root}'
    manifest = json.loads(next(result.glob('*/campaign-manifest.json')).read_text())
    assert manifest['state'] == 'completed'
    assert manifest['summary']['completed'] == repetitions
    assert manifest['summary']['failed'] == manifest['summary']['blocked'] == 0
    for log in result.glob('*/runs/*/mqtt-broker-log.log'):
        assert 'Outgoing messages are being dropped' not in log.read_text()
