"""A6 offline command/container/notebook boundary using synthetic current-format samples."""
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT/'scripts',ROOT/'tests',ROOT/'tests/unit',ROOT/'tests/integration'):sys.path.insert(0,str(p))
from test_energy_analysis import dataset_for
from test_timing_summary_in import invoke
from timing_notebook_support import isolated_notebook
pytestmark=pytest.mark.integration


def test_energy_batch_notebook_equivalence_and_raw_immutability(tmp_path):
    run,ds=dataset_for(tmp_path)
    before={p:p.read_bytes() for p in run.iterdir() if p.is_file()}
    key=ds.runs[0]['run_key']
    spec=tmp_path/'spec.json';spec.write_text(json.dumps({'conditions':{'b':{}},'baseline':'b'}))
    energy=tmp_path/'energy.json';energy.write_text(json.dumps({'trace_run':key,'boundaries':{key:{'electrical_boundary':'synthetic supply','evidence_reference':'test only'}}}))
    nb=isolated_notebook(ROOT/'notebooks/energy_comparison.ipynb',tmp_path/'energy.ipynb')
    for dest,args in [('batch',[]),('notebook',['--execute-notebook','--notebook',nb])]:
        result=invoke(tmp_path/'dataset',spec,tmp_path/dest,'--energy-spec',energy,*args)
        assert result.returncode==0,result.stderr
        metadata=json.loads((tmp_path/dest/'summary.json').read_text())
        assert metadata['energy']['inputs']
        assert 'energy-trace.png' in metadata['outputs']
        assert (tmp_path/dest/'energy-trace.png').stat().st_size>1000
    for p in (tmp_path/'batch').glob('energy_*.csv'):
        assert p.read_bytes()==(tmp_path/'notebook'/p.name).read_bytes()
    assert all(p.read_bytes()==data for p,data in before.items())
    assert invoke(tmp_path/'dataset',spec,tmp_path/'batch','--energy').returncode!=0
