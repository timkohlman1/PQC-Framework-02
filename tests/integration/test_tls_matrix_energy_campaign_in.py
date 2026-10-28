"""Local resolver, broker dry-run and synthetic notebook exercise; no lab access."""
import csv
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT/'scripts', ROOT/'tests'):
    sys.path.insert(0, str(directory))
from framework.config_resolver import ConfigResolver
from framework.campaign_executor import CampaignExecutor
from framework.run_evidence import build_resolved_case_snapshot, register_artifact
from framework.timing_dataset import export_dataset
from framework.timing_dataset_loader import load_dataset
from timing_dataset_support import make_run, reseal, rm2_records
from framework import analysis_workspace as workspace
from test_analysis_workspace_in import invoke

pytestmark = pytest.mark.integration


def test_real_resolver_cli_materialises_twelve_energy_cases(tmp_path):
    output=tmp_path/'resolved'
    result=subprocess.run([sys.executable, str(ROOT/'scripts/resolve_campaign.py'), 'tls_matrix_energy',
        '--output-root', str(output)], cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    summary=yaml.safe_load((output/'campaign-resolved.yaml').read_text())
    assert summary['case_count'] == 12
    for entry in summary['cases']:
        case=ConfigResolver(ROOT).load_resolved_case(output/entry['path'])
        assert case['selections']['instruments'] == {'energy':'esp32_ina228'}
        assert case['execution']['repetitions'] == 10


def test_each_broker_command_preserves_certificate_and_auth_selection(tmp_path):
    resolver=ConfigResolver(ROOT)
    for index, case in enumerate(resolver.expand_campaign('tls_matrix_energy')):
        calls=[]
        def runner(command, cwd):
            calls.append(command)
            return SimpleNamespace(returncode=0, stdout='Up (healthy)', stderr='')
        bundle=resolver.to_legacy_bundle(case, resolve_secrets=False)
        executor=CampaignExecutor(ROOT, runner=runner)
        executor._ensure_broker(bundle=bundle, identity=str(index), campaign_root=tmp_path/str(index))
        checked=0
        for command in calls:
            if command[2] != 'start':
                continue
            result=subprocess.run([*command, '--dry-run'], cwd=ROOT, text=True, capture_output=True, timeout=30)
            assert result.returncode == 0, result.stderr
            profile=command[command.index('--profile')+1]
            if profile == 'reporting':
                assert 'MQTT_CERTIFICATE_PROFILE=' not in result.stdout
            else:
                assert profile == bundle['experiment']['mqtt']['broker_profile']
                assert 'MQTT_CERTIFICATE_PROFILE='+case['choices']['tls_auth'] in result.stdout
            checked+=1
        assert checked == 2


def test_synthetic_matrix_reaches_dataset_and_shared_publication(tmp_path):
    resolver=ConfigResolver(ROOT)
    cases=resolver.expand_campaign('tls_matrix_energy')
    runs=[]
    # Invented timing values: this is pipeline coverage, never hardware evidence.
    for index, case in enumerate([*cases, cases[0]]):
        records=rm2_records()
        for record in records:
            record['text']=record['text'].replace('payload_bytes=20 received_bytes=20 chunk_bytes=10',
                'payload_bytes=204800 received_bytes=204800 chunk_bytes=400')
        run=make_run(tmp_path/f'run-{index}', run_id=f'synthetic-matrix-{index}',
                     records=records, failed=index==12)
        bundle=resolver.to_legacy_bundle(case, resolve_secrets=False)
        snapshot=build_resolved_case_snapshot(bundle)
        manifest=json.loads((run/'manifest.json').read_text())
        snapshot['configuration']['campaign_execution']={'campaign_id':'synthetic-matrix','case_id':case['id'], 'repetition_index':1}
        manifest['configuration']=snapshot['configuration']
        config=run/'mqtt-broker-effective.conf'
        config.write_text(f"set_tcp_nodelay {str(bundle['experiment']['mqtt']['broker_tcp_nodelay']).lower()}\n")  # Synthetic deployed evidence.
        register_artifact(manifest,result_dir=run,role='mqtt_broker_effective_config',path=config,stage='synthetic',tool=__name__)
        (run/'manifest.json').write_text(json.dumps(manifest))
        (run/'resolved-case.json').write_text(json.dumps(snapshot))
        reseal(run)  # Synthetic envelopes only.
        runs.append(run)
    dataset=tmp_path/'dataset'
    export_dataset(run_dirs=runs, output=dataset)
    loaded=load_dataset(dataset, verify_inputs=True)
    assert sum(t['validity']=='valid' for t in loaded.timings) == 12*8
    archive,_=workspace.import_sources(runs,output=tmp_path/'archive')
    comparison=json.loads((ROOT/'configs/analysis/comparisons/tls_matrix_energy.example.json').read_text())
    value=workspace.draft([archive],[dict(id='matrix',kind='timing',filters={'campaign_id':'synthetic-matrix'},comparison=comparison)],presentation={'figures':[]})
    selection=tmp_path/'selection.json';workspace.save_selection(value,selection)
    output=tmp_path/'report'
    result=invoke('publish','--spec',selection,'--output',output)
    assert result.returncode==0,result.stderr
    with (output/'data-matrix-completeness.csv').open() as handle:
        rows=list(csv.DictReader(handle))
    assert len(rows)==12*8
    assert {r['contributing_runs'] for r in rows} == {'1'}
    baseline=[r for r in rows if r['condition']=='secp256r1__ecdsa-p256__server']
    assert all(r['completed_runs']=='1' and r['failed_runs']=='1' for r in baseline)
    with (output/'data-matrix-differences.csv').open() as handle:
        differences=list(csv.DictReader(handle))
    # Cross-evidence-family matching must remain refused, not silently relabelled.
    assert all('conflicting_control:evidence_class' in r['reason'] for r in differences
               if r['condition'].startswith(('SecP256r1MLKEM768', 'ML_KEM_768')))
