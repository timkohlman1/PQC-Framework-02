"""A4 offline batch/notebook equivalence using synthetic captures."""
import hashlib
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT/'scripts',ROOT/'tests',ROOT/'tests/integration'):
    sys.path.insert(0,str(p))
from timing_dataset_support import make_run, tls_records
from timing_notebook_support import isolated_notebook
from test_timing_summary_in import invoke
from framework.timing_dataset import export_dataset
pytestmark=pytest.mark.integration


def test_tls_batch_notebook_equivalence(tmp_path):
    run=make_run(tmp_path/'run',epochs=[tls_records(0,repeat=True),tls_records(1,repeat=True)],application='tls_handshake_repeat')
    before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()}
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    spec=tmp_path/'spec.json';spec.write_text(json.dumps({'conditions':{'base':{}},'baseline':'base'}))
    nb=isolated_notebook(ROOT/'notebooks/tls_attribution.ipynb',tmp_path/'starter.ipynb')
    for dest,args in [('batch',[]),('notebook',['--execute-notebook','--notebook',nb])]:
        result=invoke(tmp_path/'dataset',spec,tmp_path/dest,'--tls',*args)
        assert result.returncode==0,result.stderr
        meta=json.loads((tmp_path/dest/'summary.json').read_text())
        assert meta['tls']['inputs'] and meta['tls']['source_sha256']
    for path in (tmp_path/'batch').glob('tls_*.csv'):
        assert path.read_bytes()==(tmp_path/'notebook'/path.name).read_bytes()
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in before.items())
