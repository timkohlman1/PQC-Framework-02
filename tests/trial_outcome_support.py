"""Synthetic negative-trial captures for offline tests only."""
import json
from timing_dataset_support import logical, make_run, reseal
from framework.trial_outcome import CHECKS, classify
from framework.run_evidence import register_artifact

def outcome(code=-7, **changes):
    fields = dict(schema=1, application='mqtt_ready_metrics_2', status='failed',
                  return_code=code, connection_attempted=1, transfer_complete=0, application_requested=0)
    fields.update(changes)
    return logical('PQC_WORKLOAD_OUTCOME ' + ' '.join(f'{k}={v}' for k,v in fields.items()), context='workload_outcome')


def negative_run(root, binding=None):
    make_run(root, records=[outcome()])
    p = root / 'manifest.json'
    m = json.loads(p.read_text())
    m['run']['return_code'] = 12
    m['execution_outcome'].update(status='failed', result='mqtt_e2e_failed')
    if binding is not None:
        m['configuration']['campaign_execution'] = binding
    trial = classify(root / 'mqtt-reporting-raw.ndjson', m['run']['id'], dict.fromkeys(CHECKS, True))
    (root / 'trial-outcome.json').write_text(json.dumps(trial))
    register_artifact(m, result_dir=root, role='trial_outcome', path=root/'trial-outcome.json', stage='synthetic', tool=__name__)
    p.write_text(json.dumps(m))
    reseal(root)
    return p


