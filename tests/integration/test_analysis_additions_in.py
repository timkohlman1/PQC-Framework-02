"""Exercise the CLI, SSH subprocess and pinned-distribution publication boundaries."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
pytestmark=pytest.mark.integration


def test_passive_wireless_cli_retains_unsupported_driver_evidence(tmp_path):
    bindir=tmp_path/'bin';bindir.mkdir()
    ssh=bindir/'ssh'
    ssh.write_text('#!/usr/bin/env python3\nimport sys\nc=sys.argv[-1]\n'
        'if c=="iw dev": print("Interface ath0")\n'
        'elif c.endswith("survey dump"): print("Operation not supported",file=sys.stderr); sys.exit(95)\n'
        'else: print("retained diagnostic")\n')
    ssh.chmod(0o755)
    output=tmp_path/'capture'
    result=subprocess.run([sys.executable,str(ROOT/'scripts/wireless_environment.py'),
        '--ssh-host','test-ap','--samples','2','--interval','1','--output',str(output)],
        env={**os.environ,'PATH':str(bindir)+os.pathsep+os.environ['PATH']},capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    records=[json.loads(x) for x in (output/'samples.ndjson').read_text().splitlines()]
    assert len(records)==2
    assert all(r['survey']['ath0']['status']=='unavailable' and r['survey']['ath0']['busy_fraction'] is None for r in records)
    assert any('Operation not supported' in c.get('stderr','') for r in records for c in r['raw'])
    assert records[1]['host_monotonic_ns']>records[0]['host_monotonic_ns']


def test_authentication_publication_cli_checks_points_and_refuses_tampering(tmp_path):
    import numpy as np
    report=tmp_path/'report';report.mkdir()
    obs=[];inventory=[];published=[]
    for mode in ('server','mutual'):
        for alg in ('rsa3072','ecdsa-p256','ecdsa-p384','mldsa65'):
            condition=f'tls_auth={alg}; auth_mode={mode}'
            values=[1000+i for i in range(29)]+[2000]
            for i,value in enumerate(values):
                key=f'{mode}-{alg}-{i}'
                inventory.append(dict(run_key=key,condition=condition,auth_mode=mode,tls_auth=alg,tls_kex='secp256r1',
                    exclusion_reason='',selected_input_status='verified',execution_outcome='completed'))
                obs.append(dict(run_key=key,condition=condition,observation_id=key+'-tls',metric='tls_handshake',
                    validity='valid',exclusion_reason='',unit='us',scope='framework_run',operation_outcome='success',value_us=value))
            q1,med,q3=np.quantile(values,[.25,.5,.75])
            published.append(dict(condition=condition,metric='tls_handshake',q1=q1,median=med,q3=q3,n_runs=30))
    checks={}
    for suffix,rows in [('observations',obs),('inventory',inventory),('distributions',published)]:
        path=report/f'data-authentication-{suffix}.csv'
        with path.open('w') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        checks[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (report/'checksums.json').write_text(json.dumps(checks))
    output=tmp_path/'plot'
    command=[sys.executable,str(ROOT/'scripts/analyse_results.py'),'authentication-distribution','--report',str(report),'--output',str(output)]
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    rows=list(csv.DictReader((output/'authentication-run-latencies.csv').open()))
    assert len(rows)==240 and len({r['run_key'] for r in rows})==240
    assert max(float(r['latency_ms']) for r in rows)==2
    figure=(output/'authentication-variability.tex').read_text()
    assert figure.count('\\nextgroupplot')==2
    assert 'Deviation from condition median' in figure
    # A 2 ms outlier on the 1.0145 ms median is retained at +97.14%, not +0.9855 ms.
    assert '97.141449' in figure
    provenance=json.loads((output/'authentication-variability-provenance.json').read_text())
    assert all(hashlib.sha256((output/n).read_bytes()).hexdigest()==h for n,h in provenance['files'].items())
    assert subprocess.run(command,cwd=ROOT,capture_output=True).returncode!=0
    path=report/'data-authentication-observations.csv';path.write_text(path.read_text()+'corruption\n')
    command[-1]=str(tmp_path/'tampered')
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    assert result.returncode!=0 and 'checksum mismatch' in result.stderr
    assert not (tmp_path/'tampered').exists()



def test_unifi_cli_retains_target_identity_disabled_fields_and_completion(tmp_path):
    bindir=tmp_path/'bin';bindir.mkdir()
    ssh=bindir/'ssh'
    ssh.write_text("""#!/usr/bin/env python3
import sys
command=sys.argv[-1]
if command=='apstats -r -i wifi0':
    print('Radio Level Stats: wifi0\\nChannel Utilization (0-255) = <DISABLED>\\nRx CRC errors = 7')
elif command=='apstats -s -m 40:82:7b:02:60:0a':
    print('Node Level Stats: 40:82:7b:02:60:0a (under VAP wifi0ap2)\\nRx RSSI = 66\\nTx failures = 0')
elif command=='iwlist wifi0ap2 channel':
    print('Current Frequency:2.437 GHz (Channel 6)')
elif command.startswith('iwconfig') or 'scan' in command or 'clear' in command:
    sys.exit(99)
else:
    print('retained diagnostic')
""")
    ssh.chmod(0o755)
    output=tmp_path/'capture'
    command=[sys.executable,str(ROOT/'scripts/wireless_environment.py'),
        '--ssh-host','test-ap','--samples','2','--interval','1','--output',str(output),
        '--backend','unifi','--radio','wifi0','--interface','wifi0ap2',
        '--station','40:82:7b:02:60:0a']
    result=subprocess.run(command,env={**os.environ,'PATH':str(bindir)+os.pathsep+os.environ['PATH']},capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    metadata=json.loads((output/'collection.json').read_text())
    assert metadata['collection_status']=='completed' and metadata['recorded_samples']==2
    records=[json.loads(x) for x in (output/'samples.ndjson').read_text().splitlines()]
    assert records[0]['channel']['channel']==6
    assert records[0]['station']['vap']=='wifi0ap2'
    assert records[0]['station']['fields']['Rx RSSI']==66
    assert records[0]['radio']['fields']['Channel Utilization (0-255)'] is None
    assert all(r['status']=='available' and r['started_utc'] for item in records for r in item['raw'])
