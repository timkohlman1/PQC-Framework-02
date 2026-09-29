"""A5 real local CLI and clean notebook boundary; synthetic retained PCAP."""
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT/'scripts',ROOT/'tests',ROOT/'tests/integration'):
    sys.path.insert(0,str(p))
from timing_dataset_support import make_run, reseal
from timing_notebook_support import isolated_notebook
from test_timing_summary_in import invoke
from framework.run_evidence import register_artifact
from framework.timing_dataset import export_dataset
from framework.timing_dataset_loader import load_dataset
from framework.packet_analysis import read_pcap
pytestmark=pytest.mark.integration


def test_batch_notebook_missing_keylog_and_raw_preservation(tmp_path):
    run=make_run(tmp_path/'run')
    fixture=ROOT/'tests/fixtures/pcap/retransmission.pcap'
    pcap=run/'gateway-network-capture.pcap';pcap.write_bytes(fixture.read_bytes())
    _,packets=read_pcap(pcap);p=packets[0]
    snapshot=run/'resolved-case.json';s=json.loads(snapshot.read_text())
    s['effective_non_secret_parameters']['mqtt'].update(enabled=True,broker={'port':p.dst_port},orchestration={'host':p.dst_ip})
    snapshot.write_text(json.dumps(s))
    path=run/'manifest.json';m=json.loads(path.read_text())
    m['configuration']['snapshot']='resolved-case.json'
    register_artifact(m,result_dir=run,role='packet_capture',path=pcap,stage='synthetic',tool=__name__)
    path.write_text(json.dumps(m));reseal(run)
    export_dataset(run_dirs=[run],output=tmp_path/'dataset')
    dataset=load_dataset(tmp_path/'dataset')
    spec=tmp_path/'spec.json';spec.write_text(json.dumps({'conditions':{'baseline':{}},'baseline':'baseline'}))
    network=tmp_path/'network.json';network.write_text(json.dumps({dataset.runs[0]['run_key']:dict(client_ip=p.src_ip,server_ip=p.dst_ip,server_port=p.dst_port,evidence_reference='synthetic client identity',window={'kind':'retained_flow'})}))
    before={p:p.read_bytes() for p in run.iterdir() if p.is_file()}
    nb=isolated_notebook(ROOT/'notebooks/network_comparison.ipynb',tmp_path/'network.ipynb')
    for dest,args in [('batch',[]),('notebook',['--execute-notebook','--notebook',nb])]:
        result=invoke(tmp_path/'dataset',spec,tmp_path/dest,'--network-spec',network,*args)
        assert result.returncode==0,result.stderr
        meta=json.loads((tmp_path/dest/'summary.json').read_text())
        assert meta['network']['inputs']
        assert (tmp_path/dest/'network-transport-response.png').exists()
        assert 'available' in (tmp_path/dest/'network_availability.csv').read_text()
    for path in (tmp_path/'batch').glob('network_*.csv'):
        assert path.read_bytes()==(tmp_path/'notebook'/path.name).read_bytes()
    assert all(p.read_bytes()==data for p,data in before.items())
