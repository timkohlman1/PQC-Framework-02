"""Self-contained live pause, intervening campaign and resume qualification."""
from pathlib import Path
import json

import pytest
from framework.campaign_executor import CampaignExecutor
from framework.hardware_test_support import HardwareFileRun, session_result_dir

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.hardware, pytest.mark.long]


def test_pause_cleans_shared_resources_and_resume_keeps_completed_capture(pytestconfig, pqc_require_capabilities):
    pqc_require_capabilities('local_toolchain', 'gateway', 'flash_helper', 'uart_device', strict_mode='hardware')
    context = HardwareFileRun.create(repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig),
                                     module_name='test_run_queue_hw')
    context.case(template='baseline', repetitions=2)
    source = context.generated_root / 'default/campaign.yaml'
    pause = context.evidence_root / 'pause.request'

    class PauseAfterCapture(CampaignExecutor):
        def _record_run(self, **kwargs):
            super()._record_run(**kwargs)
            pause.touch()

    executor = PauseAfterCapture(ROOT, results_root=context.evidence_root / 'first',
                                  pause_file=pause, stop_on_error=True, preserve_completed=True)
    path = executor.execute(source)
    state = json.loads(path.read_text())
    assert state['state'] == 'paused' and state['cleanup']['status'] == 'passed'
    assert state['summary']['completed'] == 1
    original = state['runs'][0]['manifest']
    retained = Path(original).read_bytes()
    # A different queued campaign may use the board before the paused one resumes.
    next_path = CampaignExecutor(ROOT, results_root=context.evidence_root / 'second',
                                 stop_on_error=True).execute(source)
    assert json.loads(next_path.read_text())['state'] == 'completed'
    pause.unlink()
    CampaignExecutor(ROOT, results_root=context.evidence_root / 'first',
                     pause_file=pause, stop_on_error=True, preserve_completed=True).execute(source, resume_manifest=path)
    completed = json.loads(path.read_text())
    assert completed['state'] == 'completed' and completed['cleanup']['status'] == 'passed'
    assert completed['summary']['completed'] == 2
    assert completed['runs'][0]['manifest'] == original
    assert Path(original).read_bytes() == retained
