"""A3 CLI/export and clean-kernel notebook boundary, synthetic evidence only."""
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
for directory in (ROOT/'scripts', ROOT/'tests', ROOT/'tests/unit', ROOT/'tests/integration'):
    sys.path.insert(0,str(directory))
from test_resource_analysis import fixture
from test_timing_summary_in import invoke
from timing_notebook_support import isolated_notebook

pytestmark=pytest.mark.integration


def test_resource_batch_and_clean_kernel_agree(tmp_path):
    fixture(tmp_path)
    spec=tmp_path/'spec.json';spec.write_text(json.dumps({'conditions':{'base':{}},'baseline':'base'}))
    notebook=isolated_notebook(ROOT/'notebooks/timing_comparison.ipynb',tmp_path/'starter.ipynb')
    for dest,args in [('batch',[]),('notebook',['--execute-notebook','--notebook',notebook])]:
        result=invoke(tmp_path/'dataset',spec,tmp_path/dest,'--resources',*args)
        assert result.returncode==0,result.stderr
        provenance=json.loads((tmp_path/dest/'summary.json').read_text())
        assert provenance['resources']['inputs'] and provenance['resources']['source_sha256']
    for name in ('resource_builds','resource_observations','resource_distributions','resource_differences'):
        assert (tmp_path/'batch'/f'{name}.csv').read_bytes()==(tmp_path/'notebook'/f'{name}.csv').read_bytes()
