"""One independently retained qualification attempt per memory-option build."""
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from framework.config_resolver import ConfigResolver
from framework.hardware_test_support import HardwareFileRun, session_result_dir
pytestmark=[pytest.mark.hardware,pytest.mark.long]


@pytest.mark.parametrize('role,index',[('server',0),('server',1),('mutual',0),('mutual',1),('mutual',2),('mutual',3)])
def test_memory_option_completes_and_retains_evidence(pytestconfig,pqc_require_capabilities,role,index):
    pqc_require_capabilities('local_toolchain','gateway','flash_helper','uart_device',strict_mode='hardware')
    context=HardwareFileRun.create(repo_root=ROOT,session_result_dir=session_result_dir(pytestconfig),
        module_name='test_mldsa_memory_options_hw')
    resolved=ConfigResolver(ROOT).materialize_campaign('mldsa_memory_'+role,context.generated_root/'cases')
    case=sorted((resolved/'cases').glob('*.yaml'))[index]
    run,_=context.run_experiment(case=case,name=f'{role}_{index}')
    manifest=json.loads((run/'manifest.json').read_text())
    assert manifest['capture_acceptance']['accepted'] is True, str(run)
    assert manifest['execution_outcome']['status']=='completed', str(run)
    assert manifest['run']['return_code']==0, str(run)
    print('ML-DSA memory qualification evidence:',run,flush=True)
