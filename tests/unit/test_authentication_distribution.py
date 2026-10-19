import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from framework.authentication_distribution import box

def test_tukey_whiskers_do_not_hide_extreme_points():
    s=box([1,2,3,4,5,100])
    assert s['q1']==2.25 and s['median']==3.5 and s['q3']==4.75
    assert s['upper']==5 and s['maximum']==100 and s['n']==6

def test_constant_and_invalid_observations():
    assert box([2,2,2])['lower']==2
    for points in ([],[float('nan')],[-1]):
        with pytest.raises(ValueError):box(points)


@pytest.mark.parametrize("include44", [False, True])
def test_retained_failed_slots_do_not_require_thirty_eligible_points(tmp_path, include44):
    import csv
    import hashlib
    import json
    from framework.authentication_distribution import publish
    report = tmp_path/'report'
    report.mkdir()
    inventory, observations, distributions = [], [], []
    rejected = set()
    algorithms = ['rsa3072','ecdsa-p256','ecdsa-p384','mldsa65']
    if include44: algorithms.insert(-1, 'mldsa44')
    for mode in ('server','mutual'):
        for index, algorithm in enumerate(algorithms):
            condition = f'tls_auth={algorithm}; auth_mode={mode}'
            values = []
            for iteration in range(30):
                key = f'{mode}-{algorithm}-{iteration}'
                failed = index % 2 == 0 and iteration == 29
                if failed:
                    rejected.add(key)
                else:
                    values.append(1000 + iteration)
                inventory.append(dict(run_key=key,condition=condition,tls_kex='secp256r1',
                    tls_auth=algorithm,auth_mode=mode,exclusion_reason='',
                    selected_input_status='verified',execution_outcome='failed' if failed else 'completed'))
                observations.append(dict(run_key=key,condition=condition,metric='tls_handshake',
                    validity='valid',exclusion_reason='',unit='us',scope='framework_run',
                    operation_outcome='success',value_us=(1000+iteration)*1000,observation_id=key))
            stats = box(values)
            distributions.append(dict(condition=condition,metric='tls_handshake',n_runs=stats['n'],
                **{name:stats[name]*1000 for name in ('q1','median','q3')}))
    checks = {}
    for kind, rows in [('inventory',inventory),('observations',observations),('distributions',distributions)]:
        path = report/f'data-authentication-{kind}.csv'
        with path.open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        checks[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (report/'checksums.json').write_text(json.dumps(checks))
    output=tmp_path/'output';publish(report,output)
    points=list(csv.DictReader((output/'authentication-run-latencies.csv').open()))
    assert len(inventory)==60*len(algorithms) and len(points)==len(inventory)-len(rejected)
    plot=(output/"authentication-variability.tex").read_text()
    assert ("ML-DSA-44" in plot) == include44
    assert "@@" not in plot
    assert not rejected & {r['run_key'] for r in points}
    assert '29--30 per condition' in (output/'authentication-variability.tex').read_text()
    assert {r['n'] for r in csv.DictReader((output/'authentication-boxplots.csv').open())}=={'29','30'}
