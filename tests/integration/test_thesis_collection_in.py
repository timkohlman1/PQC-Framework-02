"""Real collection planner/export/report processes; invented captures, no hardware."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT/'scripts',ROOT/'tests'):sys.path.insert(0,str(p))
from timing_dataset_support import make_run

pytestmark=pytest.mark.integration


def invoke(action,output,*extra):
    return subprocess.run([sys.executable,str(ROOT/'scripts/collect_thesis_evidence.py'),'_internal',
        action,'--output',str(output),*extra],cwd=ROOT,text=True,capture_output=True,timeout=240)


def test_planner_to_frozen_report_with_retained_failure_and_bounded_selection():
    output=ROOT/'results/analysis'/('test-collection-'+uuid.uuid4().hex)
    result=invoke('plan',output,'--only','thesis_kex','--skip-ota','--repetitions','1')
    assert result.returncode==0,result.stdout+result.stderr
    assert not (output/'campaigns').exists()
    notes=json.loads((output/'annotations.json').read_text())
    notes['network']=None  # Synthetic captures have no operator-attributed packet endpoint.
    (output/'annotations.json').write_text(json.dumps(notes))
    assert invoke('check',output).returncode==0
    raw=output/'campaigns/thesis_kex/owned/runs'
    make_run(raw/'success',run_id='collection-success')
    make_run(raw/'failed',run_id='collection-failed',failed=True)
    # This deliberately unrelated capture is outside the suite-owned input roots.
    make_run(output/'unrelated',run_id='collection-unrelated')
    result=invoke('report',output)
    assert result.returncode==0,result.stdout+result.stderr
    latest=json.loads((output/'latest-report.json').read_text())
    report=Path(latest['snapshot'])/'report'
    metadata=json.loads((report/'report.json').read_text())
    assert metadata['unique_selected_captures']==2
    inventory=list(csv.DictReader((report/'run-inventory.csv').open()))
    assert {r['run_id'] for r in inventory}=={'collection-success','collection-failed'}
    assert any(r['execution_outcome']=='failed' for r in inventory)
    assert (report/'notebook.html').is_file()
    assert len(list(report.glob('results-*.tex')))==20
    assert 'Device IPv4 attribution unspecified' in ';'.join(latest['limitations'])
    assert json.loads((output/'annotations.json').read_text())['energy']['electrical_boundary'].startswith('E5V')
    source=output/'profiles/thesis_kex.yaml'
    source.write_text(source.read_text()+'\n# deliberately changed fixture\n')
    refused=invoke('check',output)
    assert refused.returncode==2 and 'profile changed' in refused.stdout
