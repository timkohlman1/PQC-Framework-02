"""Real publication and strict replay; synthetic captures remain labelled."""
import csv
import json
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/integration'))
from test_analysis_domains_in import sources
from test_analysis_workspace_in import invoke
from framework import analysis_workspace as workspace
pytestmark=pytest.mark.integration


def test_research_tables_publish_and_replay(tmp_path):
    runs,notes=sources(tmp_path/'sources','tls')
    archive,_=workspace.import_sources(runs,output=tmp_path/'archive',annotations=notes)
    spec=workspace.draft([archive],[dict(id='tls',kind='tls',filters={'campaign_id':'synthetic'})],presentation={'figures':[]})
    condition=next(iter(spec['selections'][0]['comparison']['conditions']))
    spec['presentation']['research_tables']=[dict(id='research-test',kind='summary',caption='Synthetic test',entries=[dict(label='Test',selection='tls',condition=condition)])]
    spec['presentation']['research_tables'].append(dict(id='research-network',kind='network',caption='Synthetic network',scenarios=['baseline'],entries=[dict(label='Test',selection='tls',condition=condition,scenario='baseline')]))
    path=tmp_path/'spec.json';workspace.save_selection(spec,path)
    report=tmp_path/'report';result=invoke('publish','--spec',path,'--output',report)
    assert result.returncode==0,result.stderr
    text=(report/'research-test.tex').read_text()
    assert 'Target (ms)' not in text and '0.15' not in text and r'\textemdash{}' in text
    row=next(csv.DictReader((report/'research-test.csv').open()))
    assert float(row['total_ms'])==0.15 and row['packet_ms']==''
    assert 'explicit_endpoint_not_selected' in (report/'research-handshake-observations.csv').read_text()
    result=invoke('rebuild',report,'--output',tmp_path/'replay')
    assert result.returncode==0,result.stderr
    assert 'completed/current attempts [eligible timing runs]' in (report/'research-network-coverage.tex').read_text()
    for name in ('research-test.tex','research-test.csv','research-handshake-observations.csv','research-network.tex','research-network.csv','research-network-coverage.tex'):
        assert (report/name).read_bytes()==(tmp_path/'replay'/name).read_bytes()
    (report/'research-test.tex').write_text('tampered')
    assert invoke('verify',report).returncode==2
