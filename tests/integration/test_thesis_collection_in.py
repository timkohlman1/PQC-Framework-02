"""Real collection planner/export/report processes; invented captures, no hardware."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

ROOT=Path(__file__).resolve().parents[2]
for p in (ROOT/'scripts',ROOT/'tests'):sys.path.insert(0,str(p))
from timing_dataset_support import make_run

pytestmark=pytest.mark.integration


def invoke(action,output,*extra):
    return subprocess.run([sys.executable,str(ROOT/'scripts/collect_thesis_evidence.py'),'_internal',
        action,'--output',str(output),*extra],cwd=ROOT,text=True,capture_output=True,timeout=240)


def test_planner_to_frozen_report_with_retained_failure_and_bounded_selection():
    output=ROOT/'results/analysis'/('test-collection-'+uuid.uuid4().hex)
    result=invoke('plan',output,'--only','thesis_kex','--skip-ota','--repetitions','1')
    assert result.returncode==0,result.stdout+result.stderr
    assert not (output/'campaigns').exists()
    notes=json.loads((output/'annotations.json').read_text())
    notes['network']=None  # Synthetic captures have no operator-attributed packet endpoint.
    (output/'annotations.json').write_text(json.dumps(notes))
    assert invoke('check',output).returncode==0
    raw=output/'campaigns/thesis_kex/owned/runs'
    make_run(raw/'success',run_id='collection-success')
    make_run(raw/'failed',run_id='collection-failed',failed=True)
    # This deliberately unrelated capture is outside the suite-owned input roots.
    make_run(output/'unrelated',run_id='collection-unrelated')
    result=invoke('report',output)
    assert result.returncode==0,result.stdout+result.stderr
    latest=json.loads((output/'latest-report.json').read_text())
    report=Path(latest['snapshot'])/'report'
    metadata=json.loads((report/'report.json').read_text())
    assert metadata['unique_selected_captures']==2
    inventory=list(csv.DictReader((report/'run-inventory.csv').open()))
    assert {r['run_id'] for r in inventory}=={'collection-success','collection-failed'}
    assert any(r['execution_outcome']=='failed' for r in inventory)
    assert (report/'notebook.html').is_file()
    assert len(list(report.glob('results-*.tex')))==20
    assert 'Device IPv4 attribution unspecified' in ';'.join(latest['limitations'])
    assert json.loads((output/'annotations.json').read_text())['energy']['electrical_boundary'].startswith('E5V')
    source=output/'profiles/thesis_kex.yaml'
    source.write_text(source.read_text()+'\n# deliberately changed fixture\n')
    refused=invoke('check',output)
    assert refused.returncode==2 and 'profile changed' in refused.stdout


def test_plaintext_transition_report_uses_only_owned_matching_workload():
    from timing_dataset_support import reseal, rm2_records
    from framework.timing_dataset_loader import load_dataset
    output = ROOT/'results/analysis'/('test-plaintext-'+uuid.uuid4().hex)
    result = invoke('plan', output, '--only', 'thesis_kex', 'thesis_application_plaintext', '--skip-ota', '--repetitions', '1')
    assert result.returncode == 0, result.stdout + result.stderr
    make_run(output/'campaigns/thesis_kex/owned/secure', run_id='secure', transfer={'payload_bytes':204800, 'chunk_bytes':400})
    plain = make_run(output/'campaigns/thesis_application_plaintext/owned/plain', run_id='plain',
        choices={'mqtt_transport':'plaintext', 'tls_auth':'rsa3072'},
        records=[{**r, 'text': r['text'].replace('payload_bytes=20 received_bytes=20 chunk_bytes=10',
            'payload_bytes=204800 received_bytes=204800 chunk_bytes=400')}
            for r in rm2_records() if not r['text'].startswith('PQC_TLS_')],
        transfer={'payload_bytes':204800, 'chunk_bytes':400})
    path = plain/'resolved-case.json'
    snapshot = json.loads(path.read_text())
    snapshot['effective_non_secret_parameters']['mqtt'].update(
        tls={'mode':'plaintext','authentication':'server'}, evidence_class='stm32_st67_plaintext_e2e')
    path.write_text(json.dumps(snapshot))
    manifest = json.loads((plain/'manifest.json').read_text())
    manifest['capture_contract'].update(experiment_class='mqtt_plaintext_runtime', features={'tls_runtime':False})
    (plain/'manifest.json').write_text(json.dumps(manifest))
    reseal(plain)
    make_run(output/'unrelated',run_id='unrelated')
    result = invoke('report', output)
    assert result.returncode == 0, result.stdout + result.stderr
    destination = output/'reports/0001'
    data = load_dataset(destination/'datasets/thesis_kex_transport', verify_inputs=True)
    assert {r['run_id'] for r in data.runs} == {'plain','secure'}
    run = next(r for r in data.runs if r['run_id']=='plain')
    assert run['tls_kex'] == run['tls_auth'] == run['auth_mode'] == 'not_applicable'
    assert run['selected_input_status'] == 'verified'
    assert not any(t['run_key']==run['run_key'] and t['metric']=='tls_handshake' and t['validity']=='valid' for t in data.timings)
    assert any(t['run_key']==run['run_key'] and t['metric']=='req_tfb' and t['validity']=='valid' for t in data.timings)
    selection = json.loads((destination/'selection.json').read_text())
    transition = next(a for a in selection['analyses'] if a['id']=='thesis_kex_transport_1')
    assert transition['spec']['baseline'] == 'plaintext_no_tls'
    assert any('ML_KEM_768' in name for name in transition['spec']['conditions'])
    assert transition['spec']['filters'] == {'network_condition':'baseline','payload_bytes':204800,'chunk_bytes':400}
