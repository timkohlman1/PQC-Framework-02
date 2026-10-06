"""Synthetic fail-closed trial classification; no physical claims."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from timing_dataset_support import logical, wire, make_run, reseal
from framework.trial_outcome import CHECKS, classify, verified_failure
from framework.run_evidence import register_artifact


from trial_outcome_support import outcome, negative_run


@pytest.mark.parametrize('code', [-6,-7,-8])
def test_intact_negative_trial_is_eligible(tmp_path, code):
    stream = tmp_path / 'stream'
    records = [outcome(code)]
    if code == -6:
        records.append(logical('PQC_TLS_HANDSHAKE_TIMING start_us=100 end_us=200 result=-1'))
    stream.write_text(wire('trial', [records]))
    result = classify(stream, 'trial', dict.fromkeys(CHECKS, True))
    assert result['eligible'] and result['workload']['return_code'] == code


@pytest.mark.parametrize('check', sorted(CHECKS))
def test_every_infrastructure_check_is_required(tmp_path, check):
    stream = tmp_path / 'stream'
    stream.write_text(wire('trial', [[outcome()]]))
    checks = dict.fromkeys(CHECKS, True); checks[check] = False
    assert not classify(stream, 'trial', checks)['eligible']


@pytest.mark.parametrize('records', [[], [outcome(), outcome()], [outcome(-9)],
    [outcome(0,status='success')], [outcome(connection_attempted=0)]])
def test_ambiguous_nonnetwork_or_unstarted_outcome_is_not_accepted(tmp_path, records):
    stream = tmp_path / 'stream'; stream.write_text(wire('trial', [records]))
    assert not classify(stream, 'trial', dict.fromkeys(CHECKS, True))['eligible']


def test_completion_and_run_identity_are_required(tmp_path):
    stream = tmp_path / 'stream'; stream.write_text(wire('trial', [[outcome()]]))
    assert not classify(stream, 'other', dict.fromkeys(CHECKS, True))['eligible']
    stream.write_text('\n'.join(stream.read_text().splitlines()[:-1]))
    assert not classify(stream, 'trial', dict.fromkeys(CHECKS, True))['eligible']


def test_sealed_capture_binding_and_artifact_hashes(tmp_path):
    path = negative_run(tmp_path/'negative', {'case_id':'case', 'firmware_sha256':'abc'})
    assert verified_failure(path, case_id='case', firmware_sha256='abc')
    assert not verified_failure(path, case_id='other')
    stream = path.parent / 'mqtt-reporting-raw.ndjson'
    stream.write_text(stream.read_text() + '\n')
    assert not verified_failure(path, case_id='case')


@pytest.mark.parametrize('requested,codes,accepted', [
    (0,(14,14),True), (0,(27,27),True), (0,(0,0),True),
    (1,(14,14),False), (1,(0,0),True), (0,(127,127),False),
    (0,(0,41),False), (0,(0,None),False), (0,(5,5),False),
])
def test_observer_network_errors_only_before_a_device_request(tmp_path, requested, codes, accepted):
    from framework.trial_outcome import observer_checks
    stream = tmp_path/'stream'
    stream.write_text(wire('trial', [[outcome(application_requested=requested)]]))
    checks = observer_checks(stream, 'trial', dict(subscriber_rc=codes[0], transfer_responder_rc=codes[1]))
    assert all(checks.values()) is accepted


def test_tls_setup_error_without_measured_handshake_is_not_a_valid_trial(tmp_path):
    stream = tmp_path/'stream'; stream.write_text(wire('trial', [[outcome(-6)]]))
    assert not classify(stream, 'trial', dict.fromkeys(CHECKS, True))['eligible']


@pytest.mark.parametrize('error,accepted', [('Error: No route to host',True),
    ('Error: Connection timed out',True),('Error: Out of memory',False),('',False)])
def test_generic_observer_exit_needs_its_own_network_diagnostic(tmp_path, error, accepted):
    from framework.trial_outcome import observer_checks
    stream = tmp_path/'stream';stream.write_text(wire('trial', [[outcome()]]))
    checks = observer_checks(stream, 'trial', {'subscriber_rc':1,'transfer_responder_rc':1},
                             {'subscriber':error,'responder':'Error: Out of memory'})
    assert checks['subscriber'] is accepted
    assert checks['responder'] is False
