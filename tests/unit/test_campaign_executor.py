from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.campaign_executor import (
    CampaignError,
    ExecutionPolicy,
    _broker_ctl_command,
    _broker_profile_and_port,
    broker_identity,
    condition_identity,
    group_cases_by_firmware_identity,
    validate_completed_run,
    validate_policy_against_case,
)


def _case(case_id: str, firmware: str, condition: str, config: str) -> dict:
    return {
        "id": case_id,
        "campaign": {"id": "demo", "case_index": 1},
        "selections": {
            "workload": "ready_metrics",
            "services": {"experiment_broker": "experiment_gateway1", "reporting_broker": "reporting_gateway1"},
        },
        "choices": {"network_condition": condition},
        "provenance": {
            "configuration_identity": config,
            "firmware_identity": firmware,
            "profile_hashes": {
                f"network_condition:{condition}": f"hash-{condition}",
                "service:mqtt_broker:experiment_gateway1": "broker-service-hash",
            },
        },
    }


def test_execution_policy_accepts_request_11_contract():
    policy = ExecutionPolicy.from_mapping({
        "repetitions": 5,
        "reset_between_runs": "hardware_reset",
        "build": "once_per_firmware_identity",
        "flash": "once_per_firmware_identity",
        "experiment_broker": "reuse_if_compatible",
        "reporting_broker": "always_available",
        "condition": "retain_within_condition",
        "evidence": "per_run",
    })
    assert policy.repetitions == 5
    assert policy.reset_between_runs == "hardware_reset"


def test_execution_policy_rejects_implicit_or_unsupported_reuse_semantics():
    with pytest.raises(CampaignError, match="execution.build"):
        ExecutionPolicy.from_mapping({
            "repetitions": 1,
            "reset_between_runs": "hardware_reset",
            "build": "per_run",
            "flash": "once_per_firmware_identity",
            "experiment_broker": "reuse_if_compatible",
            "reporting_broker": "always_available",
            "condition": "retain_within_condition",
            "evidence": "per_run",
        })


def test_no_reset_is_rejected_when_workload_requires_fresh_boot():
    class Resolver:
        def load_profile(self, domain, profile_id):
            assert domain == "workload"
            return SimpleNamespace(data={"requires_fresh_boot": True})

    policy = ExecutionPolicy.from_mapping({
        "repetitions": 2,
        "reset_between_runs": "none",
        "build": "once_per_firmware_identity",
        "flash": "once_per_firmware_identity",
        "experiment_broker": "reuse_if_compatible",
        "reporting_broker": "always_available",
        "condition": "retain_within_condition",
        "evidence": "per_run",
    })
    with pytest.raises(CampaignError, match="requires a fresh boot"):
        validate_policy_against_case(policy=policy, case=_case("c1", "fw", "baseline", "cfg"), resolver=Resolver())


def test_grouping_is_stable_and_uses_firmware_identity_not_profile_name():
    cases = [
        _case("c1", "fw-a", "baseline", "cfg-1"),
        _case("c2", "fw-b", "baseline", "cfg-2"),
        _case("c3", "fw-a", "loss", "cfg-3"),
    ]
    groups = group_cases_by_firmware_identity(cases)
    assert [g["firmware_identity"] for g in groups] == ["fw-a", "fw-b"]
    assert [c["id"] for c in groups[0]["cases"]] == ["c1", "c3"]


def test_condition_identity_is_deterministic_and_profile_hash_sensitive():
    first = _case("c1", "fw", "loss", "cfg-1")
    second = _case("c2", "fw", "loss", "cfg-2")
    assert condition_identity(first) == condition_identity(second)
    second["provenance"]["profile_hashes"]["network_condition:loss"] = "changed"
    assert condition_identity(first) != condition_identity(second)


def test_broker_identity_includes_effective_listener_tls_and_service_hash():
    case = _case("c1", "fw", "baseline", "cfg")
    bundle = {"experiment": {"mqtt": {
        "broker_profile": "oqs",
        "broker": {"host": "broker", "port": 8884, "server_name": "broker"},
        "tls": {"mode": "pqc_tls_server_auth", "certificate_profile": "mldsa65", "key_exchange_group": "ML_KEM_768"},
    }}}
    first = broker_identity(bundle, case)
    bundle["experiment"]["mqtt"]["tls"]["certificate_profile"] = "rsa3072"
    assert broker_identity(bundle, case) != first


def test_resume_validation_requires_finalized_accepted_matching_per_run_evidence(tmp_path: Path):
    manifest = {
        "run": {"return_code": 0},
        "final_index": {"status": "finalized"},
        "capture_acceptance": {"accepted": True},
        "configuration": {"campaign_execution": {
            "campaign_id": "demo",
            "case_id": "c1",
            "condition_identity": "cond",
            "repetition_index": 2,
            "firmware_sha256": "abc",
        }},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_completed_run(
        path,
        campaign_id="demo",
        case_id="c1",
        condition_id="cond",
        repetition_index=2,
        firmware_sha256="abc",
    )
    manifest["configuration"]["campaign_execution"]["firmware_sha256"] = "stale"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert not validate_completed_run(
        path,
        campaign_id="demo",
        case_id="c1",
        condition_id="cond",
        repetition_index=2,
        firmware_sha256="abc",
    )


def test_resolver_campaign_case_ids_are_deterministic_for_same_source():
    from framework.config_resolver import ConfigResolver

    root = Path(__file__).resolve().parents[2]
    resolver = ConfigResolver(root)
    first = resolver.expand_campaign("baseline")
    second = resolver.expand_campaign("baseline")
    assert [case["id"] for case in first] == [case["id"] for case in second]
    assert [case["provenance"]["configuration_identity"] for case in first] == [
        case["provenance"]["configuration_identity"] for case in second
    ]


def test_plaintext_campaign_does_not_reinterpret_workload_port_as_tls_override():
    bundle = {
        "experiment": {
            "mqtt": {
                "broker_profile": "classical",
                "broker": {"host": "broker", "port": 1883, "server_name": "broker"},
                "tls": {"mode": "plaintext", "authentication": "server"},
            }
        }
    }

    profile, port_override = _broker_profile_and_port(bundle)

    assert profile == "classical"
    assert port_override is None
    command = _broker_ctl_command(Path("/repo"), "start", profile=profile, broker_port=port_override)
    assert "--classical-port" not in command


def test_tls_campaign_preserves_resolved_tls_port_override():
    bundle = {
        "experiment": {
            "mqtt": {
                "broker_profile": "classical",
                "broker": {"host": "broker", "port": 8883, "server_name": "broker"},
                "tls": {
                    "mode": "classical_tls_mutual",
                    "authentication": "mutual",
                },
            }
        }
    }

    profile, port_override = _broker_profile_and_port(bundle)

    assert profile == "classical"
    assert port_override == 8883
    command = _broker_ctl_command(Path("/repo"), "start", profile=profile, broker_port=port_override)
    assert command[-2:] == ["--classical-port", "8883"]


def test_runtime_repetition_passes_campaign_condition_log(tmp_path: Path, monkeypatch):
    from framework.campaign_executor import CampaignExecutor

    repo_root = Path(__file__).resolve().parents[2]
    executor = CampaignExecutor(repo_root, results_root=tmp_path / "results")

    produced = tmp_path / "run" / "manifest.json"
    produced.parent.mkdir(parents=True)
    produced.write_text(
        json.dumps({
            "run": {"return_code": 0},
            "final_index": {"status": "finalized"},
            "capture_acceptance": {"accepted": True},
            "configuration": {"campaign_execution": {
                "campaign_id": "demo",
                "case_id": "case-1",
                "condition_identity": "condition-1",
                "repetition_index": 1,
                "firmware_sha256": "abc",
            }},
        }),
        encoding="utf-8",
    )

    captured = {}

    def fake_run_experiment(*, repo_root, command, results_dir, runner, log_path):
        captured["command"] = command
        return 0, produced, ""

    monkeypatch.setattr("framework.campaign_executor._run_experiment", fake_run_experiment)

    condition_log = tmp_path / "control" / "gateway-network-degradation.log"
    condition_log.parent.mkdir(parents=True)
    condition_log.write_text("applied-state", encoding="utf-8")

    case = {
        "id": "case-1",
        "execution": {},
    }
    case_path = tmp_path / "case.yaml"
    preparation = tmp_path / "preparation.json"

    result = executor._run_repetition(
        campaign_root=tmp_path,
        campaign_id="demo",
        case=case,
        case_path=case_path,
        preparation_manifest=preparation,
        firmware_sha256="abc",
        cid="condition-1",
        repetition=1,
        policy=ExecutionPolicy.from_mapping({
            "repetitions": 1,
            "reset_between_runs": "hardware_reset",
            "build": "once_per_firmware_identity",
            "flash": "once_per_firmware_identity",
            "experiment_broker": "reuse_if_compatible",
            "reporting_broker": "always_available",
            "condition": "retain_within_condition",
            "evidence": "per_run",
        }),
        condition_log=condition_log,
    )

    assert result == produced
    idx = captured["command"].index("--campaign-condition-log")
    assert captured["command"][idx + 1] == str(condition_log)


def test_runtime_repetition_omits_campaign_condition_log_for_baseline(tmp_path: Path, monkeypatch):
    from framework.campaign_executor import CampaignExecutor

    repo_root = Path(__file__).resolve().parents[2]
    executor = CampaignExecutor(repo_root, results_root=tmp_path / "results")

    produced = tmp_path / "run" / "manifest.json"
    produced.parent.mkdir(parents=True)
    produced.write_text(
        json.dumps({
            "run": {"return_code": 0},
            "final_index": {"status": "finalized"},
            "capture_acceptance": {"accepted": True},
            "configuration": {"campaign_execution": {
                "campaign_id": "demo",
                "case_id": "case-1",
                "condition_identity": "condition-1",
                "repetition_index": 1,
                "firmware_sha256": "abc",
            }},
        }),
        encoding="utf-8",
    )

    captured = {}

    def fake_run_experiment(*, repo_root, command, results_dir, runner, log_path):
        captured["command"] = command
        return 0, produced, ""

    monkeypatch.setattr("framework.campaign_executor._run_experiment", fake_run_experiment)

    executor._run_repetition(
        campaign_root=tmp_path,
        campaign_id="demo",
        case={"id": "case-1", "execution": {}},
        case_path=tmp_path / "case.yaml",
        preparation_manifest=tmp_path / "preparation.json",
        firmware_sha256="abc",
        cid="condition-1",
        repetition=1,
        policy=ExecutionPolicy.from_mapping({
            "repetitions": 1,
            "reset_between_runs": "hardware_reset",
            "build": "once_per_firmware_identity",
            "flash": "once_per_firmware_identity",
            "experiment_broker": "reuse_if_compatible",
            "reporting_broker": "always_available",
            "condition": "retain_within_condition",
            "evidence": "per_run",
        }),
        condition_log=None,
    )

    assert "--campaign-condition-log" not in captured["command"]


@pytest.mark.parametrize("profile,mode,certificate,expected", [
    ("oqs", "pqc_tls_server_auth", "mldsa65", "mldsa65"),
    ("oqs-mtls", "pqc_tls_mutual", "mldsa65", "mldsa65"),
    ("classical-server-auth", "classical_tls_server_auth", "ecdsa_p256", "ecdsa_p256"),
    ("classical", "classical_tls_mutual", "rsa3072", "rsa3072"),
    ("classical", "plaintext", "mldsa65", None),
])
def test_campaign_broker_start_and_reuse_preserve_certificate_selection(
    tmp_path, profile, mode, certificate, expected
):
    from framework.campaign_executor import CampaignExecutor

    calls = []

    def runner(command, cwd):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="Up (healthy)", stderr="")

    bundle = {"experiment": {"mqtt": {
        "broker_profile": profile,
        "broker": {"port": 1883 if mode == "plaintext" else 8883},
        "tls": {"mode": mode, "certificate_profile": certificate},
    }}}
    executor = CampaignExecutor(Path(__file__).resolve().parents[2], runner=runner)
    executor._ensure_broker(bundle=bundle, identity="same", campaign_root=tmp_path)
    executor._ensure_broker(bundle=bundle, identity="same", campaign_root=tmp_path)
    starts = [c for c in calls if c[2] == "start"]
    statuses = [c for c in calls if c[2] == "status"]
    assert len(starts) == 2  # One experiment and one reporting broker, reused.
    assert len(statuses) == 4
    for command in starts + statuses:
        reporting = command[command.index("--profile") + 1] == "reporting"
        if reporting or expected is None:
            assert "--certificate-profile" not in command
        else:
            assert command[command.index("--certificate-profile") + 1] == expected
        if reporting or mode == "plaintext":
            assert "--oqs-port" not in command
            assert "--classical-port" not in command
