"""Hand-checkable A2 synthetic statistics; no experiment evidence."""
import copy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from framework.timing_dataset_loader import TimingDataset
from framework.timing_summary import summarise, wilson, CORE_CONTROLS


def data(values=(0, 10, 20, 30), outcomes=None):
    runs, timings = [], []
    for i, value in enumerate(values):
        run = dict.fromkeys(CORE_CONTROLS, "fixed")
        run.update(run_key=str(i), run_id=f"synthetic-{i}", controls={"fixed": 1},
                   tls_kex="base" if i < 2 else "new", execution_outcome=(outcomes or ["completed"]*len(values))[i],
                   selected_input_status="verified", capture_acceptance="accepted", firmware_sha256=str(i),
                   configuration_identity=str(i), observed_iteration_count=1)
        runs.append(run)
        timings.append(dict(run_key=str(i), metric="tls_handshake", value_us=value, validity="valid", reason=None,
                            epoch_index=0, iteration_id=0, observation_id=str(i), timing_policy_exclusion=None))
    return TimingDataset(tuple(runs), tuple(timings), (), {})


def spec():
    return dict(conditions={"baseline": {"tls_kex": "base"}, "treatment": {"tls_kex": "new"}},
                baseline="baseline", treatment=["tls_kex"], independent_runs=True, resamples=100, seed=12)


def row(frames, table, condition="baseline"):
    return next(r for r in frames[table].to_dict("records") if r["condition"] == condition and r["metric"] == "tls_handshake")


def test_known_arithmetic_and_seeded_inference():
    frames, _ = summarise(data(), spec())
    r = row(frames, "distributions")
    assert (r["q1"], r["median"], r["q3"], r["iqr"], r["p90"]) == (2.5, 5., 7.5, 5., 9.)
    assert (r["median_ci_low"], r["median_ci_high"]) == (0., 10.)
    diff = row(frames, "differences", "treatment")
    assert diff["delta_median"] == 20 and diff["percent_difference"] == 400
    again, _ = summarise(data(), spec())
    assert frames["distributions"].equals(again["distributions"])
    lo, hi = wilson(1, 2)
    assert lo == pytest.approx(.09453120573423)
    assert hi == pytest.approx(.90546879426577)


def test_denominators_failures_unknown_and_explicit_infrastructure_exclusion():
    d = data((10, 20, 30, 40), ["completed", "failed", "unknown", "failed"])
    s = spec(); s.update(conditions={"baseline": {}}, exclude_runs={"3": "infrastructure failure: operator selection"})
    f, _ = summarise(d, s)
    r = row(f, "completeness")
    assert (r["inventory_runs"],r["excluded_runs"],r["completed_runs"],r["failed_runs"],r["unknown_runs"]) == (4,1,1,1,1)
    assert r["known_outcome_denominator"] == 2 and r["completion_fraction"] == .5
    assert row(f, "distributions")["median"] == 10  # timeout/failure never latency
    assert len(f["inventory"]) == 4


@pytest.mark.parametrize("field,value,reason", [("target", None, "unknown_control:target"), ("target", "different", "conflicting_control:target")])
def test_refuse_invalid_matching_but_keep_absolute(field, value, reason):
    d = data(); d.runs[2][field] = value
    f, _ = summarise(d, spec())
    assert reason in row(f, "differences", "treatment")["reason"]
    assert row(f, "distributions", "treatment")["median"] == 25


def test_zero_baseline_and_missing_measurements():
    d = data((0, 0, 20, 30))
    f, _ = summarise(d, spec())
    r = row(f, "differences", "treatment")
    assert r["delta_median"] == 25 and r["percent_difference"] is None and r["percent_reason"] == "zero_baseline"
    optional = f["completeness"].query('metric == "rtfb"')
    assert all(optional.contributing_runs == 0)


def test_repeated_samples_and_retries_suppress_inference():
    d = data(); extra = {**d.timings[0], "observation_id": "repeat", "iteration_id": 1}
    repeated = TimingDataset(d.runs, (*d.timings, extra), (), {})
    f, _ = summarise(repeated, spec())
    assert row(f, "distributions")["median_ci_reason"] == "repeated_intra_run_observations_descriptive_only"
    assert row(f, "completeness")["contributing_runs"] == 2
    assert row(f, "completeness")["contributing_iterations"] == 3
    d.runs[0]["retry_of_run_id"] = "previous"
    f, _ = summarise(d, spec())
    assert row(f, "completeness")["completion_ci_reason"] == "linked_or_retried_attempts"


def test_default_no_inference_policy_validity_and_class_separation():
    d = data(); d.runs[0]["capture_class"] = "negative_validation"
    d.timings[1]["timing_policy_exclusion"] = "boot_stack_profiling"
    s = spec(); s["independent_runs"] = False
    f, _ = summarise(d, s)
    assert len(f["completeness"].query('condition == "baseline" and metric == "tls_handshake"')) == 2
    assert row(f, "differences", "treatment")["delta_median"] is None
    assert set(f["distributions"].median_ci_reason) == {"independence_not_declared"}


def test_unknown_controls_are_not_matched_and_no_hash_equality_required():
    d = data(); d.runs[0]["controls"]["qos"] = None
    f, _ = summarise(d, spec())
    assert "unknown_control:controls.qos" in row(f, "differences", "treatment")["reason"]
    s = spec(); s["not_applicable"] = {"controls.qos": "Synthetic fixture intentionally has no MQTT"}
    f, _ = summarise(d, s)
    assert row(f, "differences", "treatment")["reason"] is None


def test_overlapping_conditions_and_typo_fail():
    s = spec(); s["conditions"]["all"] = {}
    with pytest.raises(ValueError, match="overlapping"): summarise(data(), s)
    s = spec(); s["controls"] = ["typo"]
    with pytest.raises(ValueError, match="unknown field"): summarise(data(), s)


def test_notebook_wrapper_local_publish_and_no_auth_override():
    import os
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as name:
        directory = Path(name)
        docker = directory / "docker"
        docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        docker.chmod(0o755)
        env = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ["PATH"])
        result = subprocess.run([str(ROOT / "scripts/dev.sh"), "notebook"], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "127.0.0.1:8888:8888" in result.stdout
        assert "--ServerApp.port_retries=0" in result.stdout
        assert "--IdentityProvider.token" not in result.stdout
        refused = subprocess.run([str(ROOT / "scripts/dev.sh"), "notebook", "--ServerApp.token="], env=env, capture_output=True)
        assert refused.returncode == 2


def test_transport_policy_requires_opt_in_and_matching_device_capture():
    from framework.timing_summary import comparison_field
    plain = {'capture_class': 'mqtt_plaintext_runtime', 'evidence_class': 'stm32_st67_plaintext_e2e'}
    secure = {'capture_class': 'tls_runtime', 'evidence_class': 'stm32_st67_classical_tls_e2e'}
    for key in plain:
        assert comparison_field(plain, key, {'evidence_policy': 'stm32_st67_tls'}) != comparison_field(secure, key, {'evidence_policy': 'stm32_st67_tls'})
        assert comparison_field(plain, key, {'evidence_policy': 'stm32_st67_transport'}) == comparison_field(secure, key, {'evidence_policy': 'stm32_st67_transport'})
    assert comparison_field({'capture_class': 'build_only', **{'evidence_class': plain['evidence_class']}}, 'capture_class', {'evidence_policy': 'stm32_st67_transport'}) == 'build_only'
    assert comparison_field({'evidence_class': 'host_plaintext'}, 'evidence_class', {'evidence_policy': 'stm32_st67_transport'}) == 'host_plaintext'


def test_transport_comparison_preserves_non_security_controls():
    d = data((10, 20, 30, 40))
    for i, run in enumerate(d.runs):
        run.update(capture_class='mqtt_plaintext_runtime' if i < 2 else 'tls_runtime',
            evidence_class='stm32_st67_plaintext_e2e' if i < 2 else 'stm32_st67_pqc_tls_e2e',
            controls={'mqtt': {'qos': 0}})
    s = spec(); s['evidence_policy'] = 'stm32_st67_transport'
    f, _ = summarise(d, s)
    assert row(f, 'differences', 'treatment')['delta_median'] == 20
    d.runs[2]['controls']['mqtt']['qos'] = 1
    f, _ = summarise(d, s)
    assert 'conflicting_control:controls.mqtt.qos' in row(f, 'differences', 'treatment')['reason']


def test_excluded_evidence_groups_do_not_block_eligible_comparisons():
    d = data((10, 20, 30, 40))
    extra = copy.deepcopy(d.runs[0]); extra.update(run_key='excluded', target='other', evidence_class='other')
    from dataclasses import replace
    d = replace(d, runs=(*d.runs, extra))
    s = spec(); s['filters'] = {'target': 'fixed'}
    frames, _ = summarise(d, s)
    assert len(frames['inventory']) == 5
    assert row(frames, 'differences', 'treatment')['delta_median'] == 20
    assert set(frames['distributions']['evidence_class']) == {'fixed'}
