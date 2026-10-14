"""Fresh plaintext-to-PQC comparison; bounded gateway-mediated qualification."""
import json
from pathlib import Path
import sys

import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from framework import migration, migration_report, campaign_editor
from framework.run_queue import Queue
from framework.campaign_executor import CampaignExecutor
from framework.hardware_test_support import HardwareFileRun, session_result_dir
from migration_workspace import catalogue
import queue_workspace

pytestmark=[pytest.mark.hardware,pytest.mark.long]


def test_fresh_migration_profiles_capture_and_publish(pytestconfig,pqc_require_capabilities,monkeypatch):
    pqc_require_capabilities('local_toolchain','gateway','flash_helper','uart_device',strict_mode='hardware')
    context=HardwareFileRun.create(repo_root=ROOT,session_result_dir=session_result_dir(pytestconfig),
                                  module_name='test_migration_hw')
    queue=Queue(ROOT,context.evidence_root/'queue')
    # pytest-hardware already owns the Docker/gateway boundary. Run the same
    # helpers in this process rather than trying to launch nested Docker.
    def offline(action,*args):
        opts=dict(zip(args[::2],args[1::2]))
        if action=='campaign-editor':
            return campaign_editor.operate(ROOT,json.loads((ROOT/opts['--request']).read_text()))
        if action=='prepare':
            return queue_workspace.prepare(opts['--job'],opts['--profile'])
        if action=='export':
            return queue_workspace.export_selection(opts['--selection'],opts['--output'])
        raise AssertionError(action)
    monkeypatch.setattr(queue,'offline',offline)
    choices={'from':{**migration.DEFAULTS,'mqtt_transport':'plaintext','tls_kex':None,'tls_auth':None,'auth_mode':None},
             'to':{**migration.DEFAULTS,'tls_kex':'ML_KEM_768','tls_auth':'mldsa65','auth_mode':'mutual'},
             'repetitions':1}
    path,state=migration.new_session(queue,catalogue(ROOT),choices)
    (context.evidence_root/'migration-session.txt').write_text(str(path)+'\n')
    ids=migration.submit(queue,path,state)
    for side in migration.SIDES:
        ident=ids[side]
        folder=queue.folder(ident)
        campaign=CampaignExecutor(ROOT,results_root=folder/'campaigns',defer_failed=True,
                                 preserve_completed=True).execute(folder/'profiles/campaign.yaml')
        data=json.loads(campaign.read_text())
        assert data['state']=='completed',str(campaign)
        assert data['summary']['completed']==1 and data['cleanup']['status']=='passed'
        queue.finish(ident,'completed','Hardware migration qualification complete.')
    state['export']=queue.export(identifiers=[ids[s] for s in migration.SIDES])['output']
    state['report']=migration_report.publish(ROOT,state)
    migration.atomic_json(path,state)
    report=ROOT/state['report']['output']
    data=json.loads((report/'comparison.json').read_text())
    by_metric={r['metric']:r for r in data['rows']}
    for metric in ('configured_application_ram_bytes','flash_section_bytes','ttfb','ttlb','rtfb','rtlb'):
        assert by_metric[metric]['delta'] is not None,(metric,by_metric[metric],str(report))
    assert by_metric['tls_handshake']['values']['from'] is None
    assert by_metric['tls_handshake']['values']['to']>0
    assert migration_report.verify(ROOT,state)==state['report']
    print('Migration hardware evidence:',path,flush=True)
