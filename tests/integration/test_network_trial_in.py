"""Offline campaign -> retained fixtures -> selection -> A5 notebook boundary."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
import yaml
ROOT=Path(__file__).parents[2]
for p in (ROOT/'scripts',ROOT/'tests',ROOT/'tests/integration'):
    sys.path.insert(0,str(p))
from framework.config_resolver import ConfigResolver
from framework.run_evidence import build_resolved_case_snapshot,register_artifact
from framework.packet_analysis import read_pcap
from framework.timing_dataset import export_dataset
from framework.timing_dataset_loader import load_dataset
from framework.timing_summary import export_summary
from timing_dataset_support import make_run,reseal
from prepare_network_selection import prepare
pytestmark=pytest.mark.integration


def test_trial_resolves_and_drives_notebook(tmp_path):
    proc=subprocess.run([sys.executable,str(ROOT/'scripts/resolve_campaign.py'),'network_trial','--output-root',str(tmp_path/'cases')],capture_output=True,text=True,timeout=30)
    assert proc.returncode==0,proc.stderr
    assert yaml.safe_load((tmp_path/'cases/campaign-resolved.yaml').read_text())['case_count']==5
    resolver=ConfigResolver(ROOT);runs=[]
    for i,case in enumerate(resolver.expand_campaign('network_trial')):
        run=make_run(tmp_path/f'run-{i}',run_id=f'synthetic-network-{i}')
        pcap=run/'gateway-network-capture.pcap';pcap.write_bytes((ROOT/'tests/fixtures/pcap/retransmission.pcap').read_bytes())
        _,packets=read_pcap(pcap);packet=packets[0]
        snapshot=build_resolved_case_snapshot(resolver.to_legacy_bundle(case,resolve_secrets=False))
        mqtt=snapshot['effective_non_secret_parameters']['mqtt']
        mqtt['orchestration']['host']=packet.dst_ip;mqtt['broker']['port']=packet.dst_port
        (run/'resolved-case.json').write_text(json.dumps(snapshot))
        log=run/'mqtt-broker-log.log'
        log.write_text(f"New client connected from {packet.src_ip}:{packet.src_port} as {mqtt['client_id']} (p4, c1, k30).\n")
        path=run/'manifest.json';manifest=json.loads(path.read_text());manifest['configuration']=snapshot['configuration']
        for role,p in [('packet_capture',pcap),('experiment_broker_log',log)]:
            register_artifact(manifest,result_dir=run,role=role,path=p,stage='synthetic',tool=__name__)
        path.write_text(json.dumps(manifest));reseal(run);runs.append(run)
    dataset=tmp_path/'dataset';export_dataset(run_dirs=runs,output=dataset)
    before={p:p.read_bytes() for run in runs for p in run.iterdir() if p.is_file()}
    result=prepare(dataset,tmp_path/'selections')
    assert result['selected']==5 and result['unselected']==0
    selections=json.loads((tmp_path/'selections/network-selection.json').read_text())
    for axis in ('rate','rtt','loss','mtu'):
        spec=json.loads((ROOT/f'notebooks/network_trial_{axis}.json').read_text())
        frames=export_summary(dataset,spec,tmp_path/axis,network=selections)
        reasons=frames['network_comparisons']['reason'].tolist()
        assert not any(r and ('non_network_treatment' in r or 'unknown_control:controls.profile_hashes.network_condition:' in r) for r in reasons)
    cmd=[sys.executable,str(ROOT/'scripts/summarise_timing_dataset.py'),'--dataset',str(dataset),'--spec',str(ROOT/'notebooks/network_trial_rate.json'),'--network-spec',str(tmp_path/'selections/network-selection.json'),'--output',str(tmp_path/'notebook'),'--execute-notebook']
    proc=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=180)
    assert proc.returncode==0,proc.stderr
    assert (tmp_path/'notebook/network_flows.csv').read_bytes()==(tmp_path/'rate/network_flows.csv').read_bytes()
    assert all(p.read_bytes()==data for p,data in before.items())
    # An unassociated extra port on the same address must not be swept in.
    log=runs[0]/'mqtt-broker-log.log';log.write_text('No completed STM32 client connection\n');reseal(runs[0])
    # Old dataset rejects changed raw evidence; it must not be silently refreshed.
    with pytest.raises(ValueError):prepare(dataset,tmp_path/'stale')
