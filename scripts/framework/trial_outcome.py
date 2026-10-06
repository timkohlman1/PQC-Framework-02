"""Fail-closed recognition of measured negative RM2 trials, distinct from success."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from framework.timing_metrics import decode_epochs

# wolfMQTT mqtt_types.h: TLS connection, timeout and network failures. Argument,
# memory, malformed-packet and other programming/configuration errors still pause.
NETWORK_RESULTS = {-6, -7, -8}
CHECKS = {'reporting', 'capture_complete', 'energy', 'packet_capture', 'broker_log',
          'broker_integrity', 'broker_stop', 'condition_cleanup', 'subscriber', 'responder'}


def reported_outcome(stream: Path, run_id: str) -> dict | None:
    try:
        epochs, errors = decode_epochs(stream, run_id)
        if errors or len(epochs) != 1 or epochs[0].errors:
            return None
        records = [r for r in epochs[0].records if r['marker'] == 'PQC_WORKLOAD_OUTCOME']
        if len(records) != 1:
            return None
        record = records[0]
        fields = record['fields']
        if (record['context'] != 'workload_outcome' or record['iteration'] != 0
                or fields.get('schema') != '1' or fields.get('application') != 'mqtt_ready_metrics_2'
                or fields.get('status') != 'failed' or fields.get('connection_attempted') != '1'
                or fields.get('transfer_complete') not in {'0', '1'}
                or fields.get('application_requested') not in {'0', '1'}):
            return None
        code = int(fields['return_code'])
        if code not in NETWORK_RESULTS:
            return None
        if code == -6:
            # TLS setup/allocation/certificate-loading errors use the same code.
            # Only a measured failed handshake is an experimental negative.
            timings = [r['fields'] for r in epochs[0].records
                       if r['marker'] == 'PQC_TLS_HANDSHAKE_TIMING']
            if (len(timings) != 1 or int(timings[0].get('start_us', '0')) <= 0
                    or int(timings[0].get('result', '1')) == 1):
                return None
        return {'return_code': code, 'logical_sha256': epochs[0].logical_sha256,
                'application': 'mqtt_ready_metrics_2', 'status': 'failed',
                'application_requested': fields['application_requested'] == '1'}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def observer_checks(stream: Path, run_id: str, marker: dict, errors: dict | None = None) -> dict:
    outcome = reported_outcome(stream, run_id)
    # Before any device transfer request, host transfer delivery cannot have
    # caused the measured connection failure. These mosquitto errors concern
    # the same impaired experiment path (no connection/lost/TLS/errno/timeout).
    # Missing tools, rejected credentials, malformed requests and unknown codes
    # still fail closed. After a request, successful host operation is required.
    allowed = {0}
    if outcome is not None and not outcome['application_requested']:
        allowed |= {4, 7, 8, 14, 27}
    checks = {}
    for name, key in [('subscriber', 'subscriber_rc'), ('responder', 'transfer_responder_rc')]:
        code = marker.get(key)
        checks[name] = type(code) is int and code in allowed
        # Some mosquitto CLI paths collapse socket errno to exit 1. Only an
        # isolated, explicit network diagnostic disambiguates that generic code.
        if type(code) is int and code == 1 and outcome is not None and not outcome['application_requested']:
            checks[name] = (errors or {}).get(name, '').strip() in {
                'Error: No route to host', 'Error: Connection timed out',
                'Error: Network is unreachable', 'Error: Connection refused',
            }
    return checks


def classify(stream: Path, run_id: str, checks: dict) -> dict:
    outcome = reported_outcome(stream, run_id)
    eligible = (outcome is not None and isinstance(checks, dict)
                and set(checks) == CHECKS and all(v is True for v in checks.values()))
    return {'schema': 'pqc-trial-outcome', 'version': 1, 'run_id': run_id,
            'kind': 'experimental_failure' if eligible else 'unclassified',
            'eligible': eligible, 'checks': checks, 'workload': outcome}


def verified_failure(manifest_path: Path | None, **identity) -> dict | None:
    """Verify the sealed capture and both consumed artefacts before auto-accepting."""
    from framework.timing_dataset import _verify_header, _has_symlink
    if manifest_path is None or _has_symlink(manifest_path):
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
        _verify_header(manifest)
        if (manifest['capture_acceptance']['accepted'] is not True
                or manifest['run'].get('return_code') != 12
                or manifest['execution_outcome'].get('status') != 'failed'):
            return None
        binding = manifest['configuration'].get('campaign_execution', {})
        if not isinstance(binding, dict) or any(binding.get(k) != v for k, v in identity.items()):
            return None
        contents = {}
        for role, name in [('trial_outcome', 'trial-outcome.json'), ('stm32_result_stream', 'mqtt-reporting-raw.ndjson')]:
            path = manifest_path.parent / name
            items = [a for a in manifest['artifacts'] if a.get('role') == role]
            if len(items) != 1 or items[0].get('path') != name or _has_symlink(path):
                return None
            item = items[0]
            data = path.read_bytes()
            if (item['acquisition'].get('status') != 'available'
                    or item.get('sha256') != hashlib.sha256(data).hexdigest()
                    or item.get('size_bytes') != len(data)):
                return None
            contents[role] = data
        saved = json.loads(contents['trial_outcome'])
        actual = classify(manifest_path.parent / 'mqtt-reporting-raw.ndjson', manifest['run']['id'], saved['checks'])
        if saved != actual or not actual['eligible']:
            return None
        return {'decision': 'policy_record_valid_failure', 'outcome': actual['workload'],
                'trial_outcome_sha256': hashlib.sha256(contents['trial_outcome']).hexdigest()}
    except (OSError, ValueError, TypeError, KeyError):
        return None
