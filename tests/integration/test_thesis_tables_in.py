"""Real CLI, nullable loader, Jupyter and TeX boundaries using synthetic archives."""
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/unit'))
from test_thesis_tables import frame, item, loss_frame
from framework.archive_table import NULL
from framework.thesis_tables import METRICS

pytestmark=pytest.mark.integration


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path, network=False):
    """Write explicitly synthetic scalar rows, not manufactured hardware results."""
    out=tmp_path/'archive';out.mkdir()
    raw=tmp_path/'synthetic-source.txt';raw.write_text('synthetic retained input\n')
    f=loss_frame() if network else frame()
    if network:
        f['network_condition']='synthetic_loss'
        f['execution_outcome']=['completed','failed']
        f['control__network_verified_applied']=None
        f['control__network_observed']=None
    f['run_id']=['synthetic-1','synthetic-2'];f['manifest_sha256']='b'*64
    f['attempt_index']=1;f['created_at']='2026-10-01T00:00:00+00:00'
    f['case_id']='synthetic-case';f['campaign_slot_index']=[0,1]
    f['firmware_sha256']='d'*64;f['failure_stage']='none'
    rows=json.loads(f.to_json(orient='records'))
    columns={}
    numeric={x[0] for x in METRICS.values()} | {'control__network_configured__loss_percent'}
    for col in f:
        present=[r[col] for r in rows if r[col] is not None]
        columns[col]='number' if col in numeric else 'boolean' if present and type(present[0]) is bool else 'integer' if present and type(present[0]) is int else 'string'
    with (out/'runs.csv').open('w',newline='') as target:
        w=csv.DictWriter(target,fieldnames=list(columns));w.writeheader()
        for row in rows:w.writerow({k:NULL if v is None else str(v).lower() if type(v) is bool else v for k,v in row.items()})
    meta=dict(schema='pqc-flat-archive',version=2,files={'runs.csv':sha(out/'runs.csv')},
        source_dataset_id=None,inputs=[dict(path=str(raw),sha256=sha(raw))],columns=columns,column_order=list(columns),rows=2)
    (out/'archive.json').write_text(json.dumps(meta));(out/'archive.sha256').write_text(sha(out/'archive.json')+'\n')
    spec=tmp_path/'selection.json'
    spec.write_text(json.dumps(dict(version=1,exports=[dict(path=str(out),archive_sha256=sha(out/'archive.json'))],selections=[item('network_loss') if network else item()])))
    return spec,raw


def invoke(*args):
    return subprocess.run([sys.executable,str(ROOT/'scripts/analyse_results.py'),*map(str,args)],
        cwd=ROOT,capture_output=True,text=True,timeout=120)


@pytest.mark.parametrize('network',[False,True])
def test_latex_fragments_compile_with_and_without_draft_provenance(tmp_path,network):
    tool=shutil.which('xelatex')
    if not tool and not os.environ.get('PQC_CONTAINER'):pytest.skip('maintained Docker TeX environment required')
    assert tool,'Rebuild the maintained image: xelatex missing'
    spec,_=fixture(tmp_path,network);output=tmp_path/'report'
    result=invoke('publish','--spec',spec,'--output',output);assert result.returncode==0,result.stderr
    fragment=(output/('network_loss_completion.tex' if network else 'tls_auth.tex')).read_text()
    for visible in [True,False]:
        target=tmp_path/('visible' if visible else 'hidden');target.mkdir()
        text=fragment if visible else fragment.replace('\\iftrue % PROVENANCE','\\iffalse % PROVENANCE')
        (target/'table.tex').write_text(text)
        (target/'main.tex').write_text('\\documentclass{article}\n\\usepackage{booktabs,graphicx}\n\\begin{document}\n\\input{table.tex}\n\\end{document}\n')
        result=subprocess.run([tool,'-interaction=nonstopmode','-halt-on-error','main.tex'],cwd=target,text=True,capture_output=True,timeout=90)
        assert result.returncode==0,result.stdout+result.stderr
        assert (target/'main.pdf').read_bytes().startswith(b'%PDF')
    # Also compile the generated standalone preamble, not only thesis insertions.
    target=tmp_path/'standalone';target.mkdir()
    (target/'preview.tex').write_bytes((output/'preview.tex').read_bytes())
    result=subprocess.run([tool,'-interaction=nonstopmode','-halt-on-error','preview.tex'],cwd=target,text=True,capture_output=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    assert (target/'preview.pdf').read_bytes().startswith(b'%PDF')
    assert invoke('verify',output,'--verify-sources').returncode==0  # Compile only working copies.


def test_overlapping_exports_and_changed_output_are_rejected(tmp_path):
    spec,_=fixture(tmp_path);selection=json.loads(spec.read_text())
    selection['exports']*=2;spec.write_text(json.dumps(selection))
    result=invoke('publish','--spec',spec,'--output',tmp_path/'refused')
    assert result.returncode==2 and 'double-count' in result.stderr
    selection['exports']=selection['exports'][:1];spec.write_text(json.dumps(selection))
    output=tmp_path/'report';assert invoke('publish','--spec',spec,'--output',output).returncode==0
    (output/'tls_auth.tex').write_text('changed')
    result=invoke('verify',output,'--verify-sources')
    assert result.returncode==2 and 'output changed' in result.stderr
