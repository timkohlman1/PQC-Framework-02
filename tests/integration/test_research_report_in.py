"""A8 offline CLI/notebook/freeze tests with labelled synthetic captures."""
import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest
ROOT=Path(__file__).resolve().parents[2]
for path in (ROOT/'scripts',ROOT/'tests'):sys.path.insert(0,str(path))
from framework.timing_dataset import export_dataset
from timing_dataset_support import make_run

pytestmark=pytest.mark.integration


def invoke(*args):
    return subprocess.run([sys.executable,str(ROOT/'scripts/build_research_report.py'),*map(str,args)],
        cwd=ROOT,text=True,capture_output=True,timeout=180)


def test_clean_command_rebuild_privacy_and_modified_dependency(tmp_path):
    run=make_run(tmp_path/'run')
    # Not selected; the report must never copy these bytes or sweep the raw directory.
    (run/'private-key.pem').write_text('-----BEGIN PRIVATE KEY-----\nSYNTHETIC_SECRET_SENTINEL\n')
    (run/'tls-keylog.log').write_text('CLIENT_RANDOM SYNTHETIC_KEYLOG_SENTINEL\n')
    second=make_run(tmp_path/'second',run_id='synthetic-0002')
    third=make_run(tmp_path/'third',run_id='synthetic-0003')
    export_dataset(run_dirs=[run,second,third],output=tmp_path/'dataset')
    spec=tmp_path/'selection.json';spec.write_text(json.dumps({'version':1,'analyses':[dict(id='test',
        dataset=str(tmp_path/'dataset'),spec={'conditions':{'zeta':{'run_id':'synthetic-0001'},'gamma':{'run_id':'synthetic-0002'},'alpha':{'run_id':'synthetic-0003'}},'baseline':'zeta'},domains=['timing','resources','tls','energy','secure_boot','baremetal','ota'],
        sections=['dataset-summary','kex-timing','ready-metrics2'],security_domain='key_establishment')]}))
    first=tmp_path/'first'
    result=invoke('--spec',spec,'--output',first)
    assert result.returncode==0,result.stderr
    report=first/'report'
    assert (report/'notebook.html').is_file() and (report/'executed.ipynb').is_file()
    for path in report.iterdir():
        if path.suffix not in ('.png',):
            text=path.read_text()
            assert 'SYNTHETIC_SECRET_SENTINEL' not in text
            assert 'SYNTHETIC_KEYLOG_SENTINEL' not in text
            assert str(run) not in text
    with (report/'summaries.csv').open() as f:rows=list(csv.DictReader(f))
    expected=next(r for r in rows if r['metric']=='tls_handshake' and r['table']=='distributions')
    assert float(expected['value'])==150
    with (report/'figure-data.csv').open() as f:figures=list(csv.DictReader(f))
    plotted=next(r for r in figures if r['metric']=='tls_handshake' and r['table']=='distributions')
    assert plotted['value']==expected['value']
    assert '150' in (report/'test.tex').read_text()
    assert r'unique\_captures' in (report/'results-dataset-summary.tex').read_text()
    assert r'tls\_handshake' in (report/'results-cross-domain-summary.tex').read_text()
    assert len(list(report.glob('results-*.tex')))==20
    # Adding an unrelated run must not alter the existing selection.
    make_run(tmp_path/'unrelated',run_id='new-unrelated')
    assert invoke('--verify',first).returncode==0
    rebuilt=tmp_path/'rebuilt';result=invoke('--rebuild',first,'--output',rebuilt)
    assert result.returncode==0,result.stderr
    for path in report.glob('*.csv'):
        assert path.read_bytes()==(rebuilt/'report'/path.name).read_bytes()
    raw=run/'mqtt-reporting-raw.ndjson';raw.write_text(raw.read_text()+'\n')
    result=invoke('--rebuild',first,'--output',tmp_path/'refused')
    assert result.returncode==2 and 'dependency changed' in result.stderr
    assert not (tmp_path/'refused').exists()


def test_failing_notebook_cell_fails_rendering(tmp_path):
    import nbformat
    from framework.research_report import render_notebook
    nb=nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell('raise ValueError("synthetic_failure")')])
    path=tmp_path/'failure.ipynb';nbformat.write(nb,path)
    with pytest.raises(Exception,match='synthetic_failure'):render_notebook(tmp_path,path)


def test_thesis_campaign_cli_materializes_without_hardware(tmp_path):
    import yaml
    names=json.loads((ROOT/'configs/analysis/thesis_campaigns.json').read_text())['campaigns']
    for name,expected in names.items():
        target=tmp_path/name
        result=subprocess.run([sys.executable,str(ROOT/'scripts/resolve_campaign.py'),name,'--output-root',str(target)],
            cwd=ROOT,text=True,capture_output=True,timeout=30)
        assert result.returncode==0,result.stderr
        assert yaml.safe_load((target/'campaign-resolved.yaml').read_text())['case_count']==expected['conditions']
