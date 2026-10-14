"""Real CLI/queue/helper processes, synthetic captures; no hardware claims."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from framework.run_queue import Queue

pytestmark = pytest.mark.integration


@pytest.fixture
def process_repository(tmp_path):
    for directory in ('scripts','configs'):
        shutil.copytree(ROOT/directory,tmp_path/directory,ignore=shutil.ignore_patterns('__pycache__'))
    (tmp_path/'tests').mkdir()
    shutil.copy2(ROOT/'tests/timing_dataset_support.py',tmp_path/'tests/timing_dataset_support.py')
    shim=tmp_path/'scripts/dev.sh'
    shim.write_text('''#!/usr/bin/env python3
import hashlib,json,pathlib,runpy,sys,time,yaml
root=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'scripts'));sys.path.insert(0,str(root/'tests'))
from framework import thesis_collection as collection
collection.source_identity=lambda:{'synthetic_fixture':True}
a=sys.argv[1:]
if a[0]=='python':
 sys.argv=a[1:];runpy.run_path(str(root/a[1]),run_name='__main__');raise SystemExit()
from framework.campaign_executor import canonical_sha256
from timing_dataset_support import make_run,reseal
out=root/pathlib.Path(a[a.index('--results-root')+1]).relative_to('/workspace')
profile=yaml.safe_load((root/pathlib.Path(a[a.index('--results-root')-1]).relative_to('/workspace')).read_text())
folder=out/profile['id'];folder.mkdir(parents=True)
(root/'campaign-started').touch()
runs=[]
for i in range(profile['execution']['repetitions']):
 if (root/'all-failed').exists():
  runs.append({'case_id':'synthetic-case','repetition_index':i+1,'state':'failed','manifest':None,
               'accepted_failure':{'decision':'policy_record_valid_failure'}})
  continue
 capture=make_run(folder/'runs'/('run-'+str(i)),run_id=profile['id']+'-'+str(i))
 for file,key in [('resolved-case.json','configuration'),('manifest.json','configuration')]:
  path=capture/file;data=json.loads(path.read_text())
  data[key]['campaign_execution']['campaign_id']=profile['id'];path.write_text(json.dumps(data))
 reseal(capture)
 runs.append({'case_id':'synthetic-case','repetition_index':i+1,'state':'completed','manifest':str(capture/'manifest.json')})
 time.sleep(.1)
data={'campaign_id':profile['id'],'state':'completed','cleanup':{'status':'passed'},'runs':runs,
      'summary':{'planned':len(runs),'completed':len(runs),'failed':0,'blocked':0}}
if (root/'all-failed').exists():
 data['state']='completed_with_failures';data['summary'].update(completed=0,failed=len(runs))
data['final_index']={'status':'finalized','sha256':canonical_sha256(data)}
(folder/'campaign-manifest.json').write_text(json.dumps(data))
''')
    shim.chmod(0o755)
    return tmp_path


@pytest.mark.parametrize('failed',[False,True])
def test_real_interactive_process_creates_pair_waits_exports_and_resumes(process_repository,failed):
    root=process_repository
    if failed:(root/'all-failed').touch()
    # 9 fields per TLS side (unsigned boot skips standby keys), repetitions=1,
    # confirm Run, then confirm starting the shared queue.
    answers='\n'*18+'1\n\n\n'
    env=dict(os.environ);env.pop('PQC_CONTAINER',None)
    command=[sys.executable,str(root/'scripts/migration_compare.py')]
    q=Queue(root)
    try:
        result=subprocess.run(command,input=answers,cwd=root,env=env,capture_output=True,text=True,timeout=45)
        assert result.returncode==0,result.stdout+'\n'+result.stderr
        assert 'from: queued' in result.stdout or 'from: running' in result.stdout
        sessions=list((root/'results/migrations').glob('*/session.json'))
        assert len(sessions)==1
        state=json.loads(sessions[0].read_text())
        assert len(q.jobs())==2 and all(j['status']==('completed_with_failures' if failed else 'completed') for j in q.jobs())
        folder=root/state['report']['output']
        assert all((folder/f).is_file() for f in ['comparison.tex','selections.tex','comparison.json','provenance.json'])
        data=json.loads((folder/'comparison.json').read_text())
        assert data['counts']['from']['planned']==data['counts']['to']['planned']==1
        if failed:
            assert data['counts']['from']['without_capture']==1
            assert all(r['values']=={'from':None,'to':None} and r['delta'] is None for r in data['rows'])
        first_bytes=(folder/'comparison.tex').read_bytes()
        again=subprocess.run(command+['--resume',str(sessions[0])],cwd=root,env=env,capture_output=True,text=True,timeout=15)
        assert again.returncode==0,again.stderr
        assert len(q.jobs())==2 and (folder/'comparison.tex').read_bytes()==first_bytes
        # Both comparison sidecars are integrity checked on resume.
        (folder/'selections.tex').write_text('modified')
        tampered=subprocess.run(command+['--resume',str(sessions[0])],cwd=root,env=env,capture_output=True,text=True,timeout=15)
        assert tampered.returncode==2 and 'output changed' in tampered.stderr
    finally:
        q.stop()
        deadline=time.monotonic()+10
        while q.worker_alive() and time.monotonic()<deadline:time.sleep(.05)
        assert not q.worker_alive()


def test_cli_cancel_creates_no_profiles_or_jobs(process_repository):
    root=process_repository; env=dict(os.environ);env.pop('PQC_CONTAINER',None)
    result=subprocess.run([sys.executable,str(root/'scripts/migration_compare.py')],input='\n'*19+'2\n',
        cwd=root,env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
    assert not Queue(root).jobs()
    assert not (root/'results/profiles').exists()
