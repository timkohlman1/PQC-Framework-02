"""A7 offline CLI and clean-kernel notebook equivalence, synthetic inputs."""
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT/'scripts',ROOT/'tests',ROOT/'tests/unit',ROOT/'tests/integration'):
    sys.path.insert(0,str(p))
from test_secure_boot_analysis import fixture
from test_timing_summary_in import invoke
from timing_notebook_support import isolated_notebook
pytestmark=pytest.mark.integration


def test_boot_cli_and_notebook_agree(tmp_path):
    fixture(tmp_path)
    spec=tmp_path/'spec.json';spec.write_text(json.dumps({'conditions':{'base':{}},'baseline':'base'}))
    notebook=isolated_notebook(ROOT/'notebooks/secure_boot_comparison.ipynb',tmp_path/'starter.ipynb')
    for name,extra in [('batch',[]),('notebook',['--execute-notebook','--notebook',notebook])]:
        result=invoke(tmp_path/'dataset',spec,tmp_path/name,'--secure-boot',*extra)
        assert result.returncode==0,result.stderr
        meta=json.loads((tmp_path/name/'summary.json').read_text())
        assert meta['secure_boot']['inputs']
        assert (tmp_path/name/'secure_boot_timing.png').is_file()
    for name in ('observations','resources','outcomes','distributions','differences'):
        assert (tmp_path/'batch'/f'secure_boot_{name}.csv').read_bytes()==(tmp_path/'notebook'/f'secure_boot_{name}.csv').read_bytes()
