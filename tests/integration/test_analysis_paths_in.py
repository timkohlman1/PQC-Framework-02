"""Docker-addressed synthetic exports read in a relocated host-style checkout."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

import pytest
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT/'scripts',ROOT/'tests',ROOT/'tests/unit',ROOT/'tests/integration'):
    sys.path.insert(0,str(p))
from framework import analysis_paths, analysis_workspace as workspace
from framework.run_evidence import canonical_sha256
from test_analysis_domains_in import sources
from analysis_notebook_support import analysis_book

pytestmark=pytest.mark.integration


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def docker_addressed_fixture(archive,native):
    """Create a sealed synthetic export with Docker addresses; never touch captures."""
    def remap(raw):return raw.replace(str(native).encode(),b'/workspace')
    dataset=archive/'source-dataset'
    meta=json.loads(remap((dataset/'dataset.json').read_bytes()))
    for name in ('runs','timings','issues'):
        p=dataset/(name+'.csv');p.write_bytes(remap(p.read_bytes()))
        meta['outputs'][name].update(sha256=sha(p),size_bytes=p.stat().st_size)
    meta['dataset_id']=canonical_sha256({k:meta[k] for k in ('selection','inputs','parser','schema')})
    (dataset/'dataset.json').write_text(json.dumps(meta))
    (dataset/'dataset.sha256').write_text(sha(dataset/'dataset.json')+'  dataset.json\n')
    p=archive/'runs.csv';p.write_bytes(remap(p.read_bytes()))
    meta=json.loads(remap((archive/'archive.json').read_bytes()))
    meta.update(files={'runs.csv':sha(p)},source_dataset_id=json.loads((dataset/'dataset.json').read_text())['dataset_id'])
    (archive/'archive.json').write_text(json.dumps(meta))
    (archive/'archive.sha256').write_text(sha(archive/'archive.json')+'\n')


@pytest.mark.parametrize('kind',['timing','resources','tls','network','energy','boot_evidence','baremetal','ota'])
def test_relocated_domain_outputs_match_and_tampering_still_fails(tmp_path,monkeypatch,kind):
    native=tmp_path/'checkout'
    base=native/'results'/('path-test-'+uuid.uuid4().hex)
    selected,notes=sources(base/'sources',kind)
    archive,_=workspace.import_sources(selected,output=base/'archive',annotations=notes)
    request=[dict(id=kind,kind=kind,filters={'campaign_id':'synthetic'})]
    original=workspace.prepare(workspace.draft([archive],request,presentation={'figures':[]}))
    before={p:p.read_bytes() for run in selected for p in run.rglob('*') if p.is_file()}
    docker_addressed_fixture(archive,native)
    sealed={p:p.read_bytes() for p in archive.rglob('*') if p.is_file()}
    monkeypatch.setattr(analysis_paths,'ROOT',native)
    # Simulate the same saved export reference that a Docker notebook records.
    recorded=Path('/workspace')/archive.relative_to(native)
    assert not recorded.exists()
    value=workspace.draft([recorded],request,presentation={'figures':[]})
    actual=workspace.prepare(value)
    assert actual['tables']==original['tables']
    assert actual['metrics']==original['metrics']
    output,report=workspace.publish(value,output=base/'report')
    workspace.verify(output,verify_sources=True)
    assert all(p.read_bytes()==data for p,data in before.items())
    assert all(p.read_bytes()==data for p,data in sealed.items())
    # Publication must still refuse output inside the locally mapped capture.
    with pytest.raises(ValueError,match='outside retained capture'):
        workspace.publish(value,output=selected[0]/'forbidden-report')
    # Archive-side evidence is checked as well as dataset inputs.
    meta=json.loads((archive/'archive.json').read_text())
    external=next((analysis_paths.result_path(i['path']) for i in meta['inputs'] if i.get('sha256')),None)
    if external:
        raw=external.read_bytes();external.write_bytes(raw+b'changed')
        with pytest.raises(ValueError):workspace.prepare(value)
        external.write_bytes(raw)
    raw=selected[0]/'manifest.json';raw.write_bytes(raw.read_bytes()+b'changed')
    workspace.verify(output,verify_sources=False)
    with pytest.raises(ValueError,match='consumed input changed'):workspace.verify(output,verify_sources=True)


def test_actual_notebook_reads_docker_export_from_host_style_checkout(tmp_path,monkeypatch):
    native=tmp_path/'checkout';base=native/'results'/('notebook-test-'+uuid.uuid4().hex)
    selected,notes=sources(base/'sources','energy')
    archive,_=workspace.import_sources(selected,output=base/'archive',annotations=notes)
    docker_addressed_fixture(archive,native)
    monkeypatch.setattr(analysis_paths,'ROOT',native)
    value=workspace.draft([archive],[dict(id='energy',kind='energy',filters={'campaign_id':'synthetic'})])
    _,expected=workspace.publish(value,output=base/'reference-report')
    spec=base/'selection.json';workspace.save_selection(value,spec)
    # Copy executable framework sources, not dependencies or result evidence.
    shutil.copytree(ROOT/'scripts/framework',native/'scripts/framework',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'scripts/benchmark_summary.py',native/'scripts/benchmark_summary.py')
    (native/'notebooks').mkdir()
    book=analysis_book()
    monkeypatch.setenv('PQC_ANALYSIS_SPEC',str(spec));monkeypatch.setenv('PQC_ANALYSIS_PUBLISH','1')
    monkeypatch.setenv('PQC_ANALYSIS_OUTPUT',str(base/'notebook-report'))
    NotebookClient(book,timeout=180,kernel_name='python3',
        resources={'metadata':{'path':str(native/'notebooks')}}).execute()
    report=workspace.verify(base/'notebook-report',verify_sources=True)
    assert report['tables']==expected['tables']
    assert report['figures']
