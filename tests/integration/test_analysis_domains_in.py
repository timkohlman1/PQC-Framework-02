"""Real import/select/preview/publish/rebuild paths for every domain, no hardware."""
import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parents[2]
for path in (ROOT/'scripts', ROOT/'tests', ROOT/'tests/unit', ROOT/'tests/integration'):
    sys.path.insert(0,str(path))
from timing_dataset_support import make_run, reseal, tls_records, logical
from framework import analysis_workspace as workspace
from analysis_notebook_support import analysis_book
from framework.run_evidence import register_artifact
from test_analysis_workspace_in import invoke

pytestmark=pytest.mark.integration


def sources(root, kind):
    if kind == 'energy':
        from test_energy_analysis import energy_run
        return [energy_run(root/'run')], {'energy':{'electrical_boundary':'synthetic supply','evidence_reference':'synthetic constant load'}}
    if kind == 'resources':
        from test_resource_analysis import fixture
        _, runs = fixture(root)
        return runs, {}
    if kind == 'boot_evidence':
        from test_secure_boot_analysis import fixture
        fixture(root)
        return [root/'run'], {}
    if kind == 'tls':
        a = make_run(root/'run',epochs=[tls_records(0,repeat=True),tls_records(1,repeat=True)],application='tls_handshake_repeat')
        b = make_run(root/'second',run_id='synthetic-0002',epochs=[tls_records(0,repeat=True)],application='tls_handshake_repeat')
        return [a,b], {}
    if kind == 'baremetal':
        from test_baremetal_benchmark_summary import records
        return [make_run(root/'run', application='baremetal_benchmark',records=[logical(r['text'],context='baremetal_benchmark') for r in records()])], {}
    run=make_run(root/'run')
    notes={}
    if kind == 'network':
        from framework.packet_analysis import read_pcap
        pcap=run/'gateway-network-capture.pcap';pcap.write_bytes((ROOT/'tests/fixtures/pcap/retransmission.pcap').read_bytes())
        _,packets=read_pcap(pcap);packet=packets[0]
        path=run/'resolved-case.json';s=json.loads(path.read_text())
        s['effective_non_secret_parameters']['mqtt'].update(enabled=True,broker={'port':packet.dst_port},orchestration={'host':packet.dst_ip})
        path.write_text(json.dumps(s))
        path=run/'manifest.json';m=json.loads(path.read_text())
        register_artifact(m,result_dir=run,role='packet_capture',path=pcap,stage='synthetic',tool=__name__)
        path.write_text(json.dumps(m))
        notes={'network':dict(client_ip=packet.src_ip,evidence_reference='synthetic client identity')}
    if kind == 'ota':
        uart=run/'uart.log';uart.write_text('PQC_OTA_APP phase=request_accepted active_bank=1 inactive_bank=2 flags=0\nPQC_OTA_APP phase=transfer_complete app_received=123\nPQC_OTA_APP phase=confirmed active_bank=2 confirmed=1\n')
        path=run/'run-provenance.json';p=json.loads(path.read_text());p['records']['ota']={'requested':True,'delivery':{'return_code':0}}
        path.write_text(json.dumps(p))
        path=run/'manifest.json';m=json.loads(path.read_text())
        register_artifact(m,result_dir=run,role='diagnostic_uart',path=uart,stage='synthetic',tool=__name__)
        path.write_text(json.dumps(m))
    reseal(run)
    return [run], notes


@pytest.mark.parametrize('kind',['timing','resources','tls','network','energy','boot_evidence','baremetal','ota'])
def test_full_domain_workflow_uses_existing_engines_and_rebuilds(tmp_path,monkeypatch,kind):
    selected,notes=sources(tmp_path/'sources',kind)
    archive=tmp_path/'archive';annotations=tmp_path/'annotations.json';annotations.write_text(json.dumps(notes))
    args=['import','--output',archive,'--annotations',annotations]
    for path in selected:args+=['--source',path]
    before={p:p.read_bytes() for source in selected for p in source.rglob('*') if p.is_file()}
    result=invoke(*args);assert result.returncode==0,result.stderr
    result=invoke('catalog','--exports-root',tmp_path);assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)[0]['status']=='outputs_verified'
    result=invoke('inspect','--export',archive,'--campaign','synthetic');assert result.returncode==0,result.stderr
    info=json.loads(result.stdout);assert info['retained_runs']>0 and info['controls']
    selection=tmp_path/'selection.json'
    result=invoke('select','--export',archive,'--campaign','synthetic','--recipe',kind,'--output',selection,'--no-figures')
    assert result.returncode==0,result.stderr
    value=workspace.read_spec(selection)
    assert value['selections'][0]['comparison']['independent_runs'] is False
    result=invoke('preview','--spec',selection);assert result.returncode==0,result.stderr
    out=tmp_path/'report';result=invoke('publish','--spec',selection,'--output',out);assert result.returncode==0,result.stderr
    assert invoke('verify',out,'--verify-sources').returncode==0
    report=json.loads((out/'report.json').read_text())
    assert report['analyses'][kind]['domains']
    assert report['data_files'] and (out/'methods.json').is_file()
    if kind=='ota':
        assert 'unconfirmed' in (out/'ota_ota_outcomes.csv').read_text()
    else:
        with (out/'metrics.csv').open() as stream:metrics=list(csv.DictReader(stream))
        assert any(r['reported_value'] for r in metrics),kind
        if kind=='tls':
            row=next(r for r in metrics if r['metric']=='tls_handshake' and r['source_table']=='tls_run_distributions')
            assert float(row['reported_value'])==150 and int(row['n_runs'])==2 and int(row['n'])==2
        if kind=='baremetal':
            assert {float(r['reported_value']) for r in metrics if r['reported_value']}=={105.5}
        if kind=='energy':
            row=next(r for r in metrics if r['metric'].startswith('tls_handshake.energy_j'))
            assert float(row['reported_value'])==pytest.approx(.000075)
    rebuilt=tmp_path/'rebuilt';result=invoke('rebuild',out,'--output',rebuilt);assert result.returncode==0,result.stderr
    for path in out.iterdir():
        if path.suffix in ('.csv','.tex'):assert path.read_bytes()==(rebuilt/path.name).read_bytes()
    # Every domain uses the same unmodified notebook from a clean kernel.
    source=ROOT/'notebooks/analysis.ipynb';original=source.read_bytes()
    monkeypatch.setenv('PQC_ANALYSIS_SPEC',str(selection))
    monkeypatch.setenv('PQC_ANALYSIS_PUBLISH','1')
    monkeypatch.setenv('PQC_ANALYSIS_OUTPUT',str(tmp_path/'notebook'))
    book=analysis_book()
    NotebookClient(book,timeout=180,kernel_name='python3',
        resources={'metadata':{'path':str(ROOT/'notebooks')}}).execute()
    for path in out.iterdir():
        if path.suffix in ('.csv','.tex'):assert path.read_bytes()==(tmp_path/'notebook'/path.name).read_bytes()
    assert source.read_bytes()==original
    assert all(p.read_bytes()==b for p,b in before.items())


def test_domain_notebook_and_cli_match_with_figures_and_missing_boundary(tmp_path,monkeypatch):
    selected,notes=sources(tmp_path/'source','energy')
    archive,_=workspace.import_sources(selected,output=tmp_path/'archive',annotations=notes)
    value=workspace.draft([archive],[dict(id='energy',kind='energy',filters={'campaign_id':'synthetic'})])
    spec=tmp_path/'selected.json';workspace.save_selection(value,spec)
    out,report=workspace.publish(spec,output=tmp_path/'cli')
    assert report['figures']
    metrics=list(csv.DictReader((out/'metrics.csv').open()))
    figure=list(csv.DictReader((out/'figure-data.csv').open()))
    for row in figure:
        m=next(r for r in metrics if r['table']==row['table'] and r['condition']==row['condition'] and r['metric']==row['metric'])
        assert row['value']==m['reported_value']
    monkeypatch.setenv('PQC_ANALYSIS_SPEC',str(spec));monkeypatch.setenv('PQC_ANALYSIS_PUBLISH','1');monkeypatch.setenv('PQC_ANALYSIS_OUTPUT',str(tmp_path/'notebook'))
    book=analysis_book()
    NotebookClient(book,timeout=180,kernel_name='python3',resources={'metadata':{'path':str(ROOT/'notebooks')}}).execute()
    for p in out.glob('*.csv'):assert p.read_bytes()==(tmp_path/'notebook'/p.name).read_bytes()
    value['selections'][0]['energy']={'boundaries':{}}
    prepared=workspace.prepare(value)
    assert all(r['reported_value'] is None for r in prepared['metrics'])
    raw=selected[0]/'mqtt-reporting-raw.ndjson';raw.write_text(raw.read_text()+'\n')
    assert invoke('verify',out).returncode==0
    assert invoke('verify',out,'--verify-sources').returncode==2
    assert invoke('rebuild',out,'--output',tmp_path/'bad').returncode==2


def test_failed_run_and_recorded_absence_remain_reportable_and_frozen(tmp_path):
    good=make_run(tmp_path/'good')
    failed=make_run(tmp_path/'failed',run_id='synthetic-failed',failed=True)
    archive,_=workspace.import_sources([good,failed],output=tmp_path/'archive')
    value=workspace.draft([archive],[dict(id='tls',kind='tls',filters={'campaign_id':'synthetic'})],presentation={'figures':[]})
    out,report=workspace.publish(value,output=tmp_path/'report')
    assert report['selections'][0]['current_attempts']==2
    assert report['selections'][0]['current_failures']==1
    outcome=next(t for t in report['tables'] if t['id']=='tls_outcomes')
    assert outcome['rows'][0][1:5]==['2','1','1','0']
    absent=failed/'mqtt-reporting-raw.ndjson'
    assert any(d['path']==str(absent) and d['sha256'] is None for d in report['analyses']['tls']['dependencies'])
    assert invoke('verify',out,'--verify-sources').returncode==0
    result=invoke('rebuild',out,'--output',tmp_path/'rebuilt');assert result.returncode==0,result.stderr
    absent.write_text('later unrelated bytes, not a captured result')
    assert invoke('verify',out).returncode==0
    assert invoke('verify',out,'--verify-sources').returncode==2


def test_measurement_choice_across_domains_keeps_detailed_data(tmp_path):
    run=make_run(tmp_path/'run')
    archive,_=workspace.import_sources([run],output=tmp_path/'archive')
    value=workspace.draft([archive],[dict(id='combined',kind='comparison',domains=['timing','tls','resources'],filters={'campaign_id':'synthetic'})],
        presentation={'figures':[], 'measurements':['tls_handshake','flash_section_bytes']})
    prepared=workspace.prepare(value)
    assert {r['metric'] for r in prepared['metrics']}=={'tls_handshake','flash_section_bytes'}
    assert all(r['source_table']!='distributions' for r in prepared['metrics'])
    assert 'ttlb' in prepared['analyses']['combined']['available_measurements']
    assert 'resource_observations' in prepared['analyses']['combined']['frames']
    value['presentation']['measurements']=['typo']
    with pytest.raises(ValueError,match='no matching'):
        workspace.prepare(value)


def test_publication_keeps_exact_nullable_integers_and_literal_null_strings(tmp_path):
    # Exercise detailed CSV serialization on the maintained publication boundary.
    from framework import thesis_tables
    from unittest.mock import patch
    run=make_run(tmp_path/'run')
    archive,_=workspace.import_sources([run],output=tmp_path/'archive')
    value=workspace.draft([archive],[dict(id='timing',kind='timing',filters={'campaign_id':'synthetic'})],presentation={'figures':[]})
    prepared=workspace.prepare(value)
    data=prepared['analyses']['timing']['frames']['observations']
    data['rows'][0]['start_us']=2**53+1
    data['rows'][1]['start_us']=None
    data['rows'][0]['run_id']=r"\N"
    with patch.object(thesis_tables,'prepare',return_value=prepared):
        out,_=workspace.publish(value,output=tmp_path/'report')
    with (out/'data-timing-observations.csv').open() as stream:
        rows=list(csv.DictReader(stream))
    assert rows[0]['start_us']==str(2**53+1)
    assert rows[1]['start_us']==r"\N"
    assert rows[0]['run_id']==r"\\N"
