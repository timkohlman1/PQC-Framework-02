from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def _modules():
    repo_root = Path(__file__).resolve().parents[2]
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from framework import manifest, run_evidence
    return manifest, run_evidence


def _bundle(*, evidence_class: str = "stm32_build_only", tls_mode: str = "not_applicable") -> dict:
    return {
        "experiment": {
            "id": "case-1",
            "firmware": {"application": "mqtt_validation", "artifact": "build/Release/app.elf"},
            "mqtt": {
                "evidence_class": evidence_class,
                "transport_backend": "stm32_build_only" if evidence_class == "stm32_build_only" else "st67w61m1_lwip_wolfssl",
                "tls": {"mode": tls_mode},
            },
            "network": {},
            "services": {},
            "resolved_configuration": {
                "schema_version": 1,
                "resolver_version": 1,
                "configuration_identity": "config-sha",
                "firmware_identity": "fw-sha",
                "selected_profiles": {"target": "target-a", "workload": "mqtt_validation"},
                "choices": {"tls_kex": "x25519"},
                "profile_hashes": {"target:target-a": "a" * 64},
                "secret_references": {"wifi_ssid": "env:PQC_WIFI_SSID", "wifi_psk": "env:PQC_WIFI_PSK"},
            },
        },
        "board": {"id": "board"},
        "host": {"id": "gateway"},
        "boot": {"mode": "direct_flash"},
    }


def test_versioned_manifest_and_contract_use_requirement_states():
    manifest, _ = _modules()
    data = manifest.build_manifest(_bundle(), "2026-09-14_001_case")
    assert data["schema"]["name"] == "pqc-run-evidence"
    assert data["schema"]["version"] == 3
    requirements = {item["role"]: item["requirement"] for item in data["artifacts"]}
    assert requirements["resolved_case_snapshot"] == "required"
    assert requirements["network_condition_record"] == "not_applicable"
    assert requirements["energy_result_stream"] == "not_applicable"


def test_required_missing_evidence_rejects_without_changing_sut_outcome(tmp_path):
    manifest, _ = _modules()
    bundle = _bundle(evidence_class="stm32_st67_plaintext_e2e")
    result_dir, _ = manifest.create_result_folder(bundle, tmp_path / "results")
    manifest.update_manifest(
        result_dir / "manifest.json",
        {"result": "baseline_run_passed", "run": {"failure_stage": "none"}},
    )
    final = manifest.finalize_run_evidence(result_dir / "manifest.json")
    assert final["execution_outcome"]["status"] == "completed"
    assert final["capture_acceptance"]["accepted"] is False
    assert any("experiment_broker_log" in reason for reason in final["capture_acceptance"]["reasons"])


def test_hash_mismatch_cannot_replace_collected_raw_evidence(tmp_path):
    _, evidence = _modules()
    result_dir = tmp_path / "run"
    result_dir.mkdir()
    artifact = result_dir / "uart.log"
    artifact.write_text("first", encoding="utf-8")
    manifest = {"artifacts": evidence.initial_capture_index({"items": [{"role": "diagnostic_uart", "requirement": "required", "source_class": "stm32_runtime", "reason": None}]})}
    evidence.register_artifact(manifest, result_dir=result_dir, role="diagnostic_uart", path=artifact, stage="uart", tool="collector")
    artifact.write_text("second", encoding="utf-8")
    with pytest.raises(ValueError, match="immutable"):
        evidence.register_artifact(manifest, result_dir=result_dir, role="diagnostic_uart", path=artifact, stage="uart", tool="collector")


def test_derived_output_records_direct_inputs_parameters_and_output_hash(tmp_path):
    _, evidence = _modules()
    result_dir = tmp_path / "run"
    result_dir.mkdir()
    raw = result_dir / "capture.pcap"
    raw.write_bytes(b"raw")
    derived = result_dir / "packet-analysis.json"
    derived.write_text('{"packets": 1}\n', encoding="utf-8")
    record = evidence.build_derived_record(
        result_dir=result_dir,
        role="packet_analysis",
        path=derived,
        tool="packet-analyser",
        version="1.2.3",
        input_sha256=[evidence.sha256_file(raw)],
        parameters={"window": "handshake"},
    )
    assert record["producer"] == {"tool": "packet-analyser", "version": "1.2.3"}
    assert record["inputs"][0]["sha256"] == evidence.sha256_file(raw)
    assert record["parameters"] == {"window": "handshake"}
    assert record["sha256"] == evidence.sha256_file(derived)


def test_legacy_manifest_is_not_silently_accepted_under_current_contract(tmp_path):
    manifest, _ = _modules()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"run_id": "legacy", "result": "pass"}), encoding="utf-8")
    data = manifest.read_manifest(path)
    assert data["compatibility"]["legacy_manifest"] is True
    assert data["compatibility"]["accepted_under_current_contract"] is False
    with pytest.raises(ValueError, match="legacy manifest"):
        manifest.finalize_run_evidence(path)


def test_resolved_case_snapshot_excludes_secret_values_and_retains_references():
    _, evidence = _modules()
    bundle = _bundle()
    bundle["experiment"]["network"] = {"wifi": {"ssid": "real-ssid", "psk": "real-psk"}}
    snapshot = evidence.build_resolved_case_snapshot(bundle)
    encoded = json.dumps(snapshot)
    assert "real-ssid" not in encoded
    assert "real-psk" not in encoded
    assert "env:PQC_WIFI_SSID" in encoded
    assert "env:PQC_WIFI_PSK" in encoded


def test_reused_preparation_linkage_keeps_exact_manifest_and_firmware_identity(tmp_path):
    manifest, _ = _modules()
    result_dir, _ = manifest.create_result_folder(_bundle(evidence_class="stm32_st67_plaintext_e2e"), tmp_path / "results")
    preparation = tmp_path / "results" / "builds" / "41" / "manifest.json"
    manifest.update_manifest(result_dir / "manifest.json", {
        "build_reference": {
            "build_number": 41,
            "status": "verified",
            "record_manifest": str(preparation),
            "artifact_sha256": "f" * 64,
        }
    })
    data = manifest.read_manifest(result_dir / "manifest.json")
    assert data["preparation"]["mode"] == "reused"
    assert data["preparation"]["manifest"] == str(preparation)
    assert data["preparation"]["firmware_sha256"] == "f" * 64
    assert data["preparation"]["verified"] is True


def test_runtime_only_preparation_reuses_required_secure_boot_artifact_identities(tmp_path):
    manifest, evidence = _modules()
    bundle = _bundle(evidence_class="stm32_st67_plaintext_e2e")
    bundle["boot"] = {"mode": "wolfboot"}
    result_dir, _ = manifest.create_result_folder(bundle, tmp_path / "results")

    manifest.update_manifest(result_dir / "manifest.json", {
        "profile_preparation_reference": {
            "manifest": str(tmp_path / "preparation" / "manifest.json"),
            "run_id": "prep-001",
            "result": "passed",
            "firmware_sha256": "f" * 64,
            "reused_artifact_identities": {
                "wolfboot_image": "a" * 64,
                "signed_application": "b" * 64,
            },
        }
    })

    data = manifest.read_manifest(result_dir / "manifest.json")
    by_role = {item["role"]: item for item in data["artifacts"]}
    assert by_role["wolfboot_image"]["requirement"] == "required"
    assert by_role["wolfboot_image"]["sha256"] == "a" * 64
    assert by_role["wolfboot_image"]["acquisition"] == {
        "status": "available", "result": "reused", "reason": None
    }
    assert by_role["signed_application"]["requirement"] == "required"
    assert by_role["signed_application"]["sha256"] == "b" * 64
    assert by_role["signed_application"]["acquisition"] == {
        "status": "available", "result": "reused", "reason": None
    }

    acceptance = evidence.evaluate_capture_acceptance(data)
    reasons = " ".join(acceptance["reasons"])
    assert "wolfboot_image" not in reasons
    assert "signed_application" not in reasons


@pytest.mark.parametrize(
    ("bundle_mutator", "required_role"),
    [
        (lambda b: b, "application_elf"),
        (lambda b: b.update({"experiment": {**b["experiment"], "mqtt": {"evidence_class": "stm32_st67_plaintext_e2e", "transport_backend": "st67w61m1_lwip_wolfssl", "tls": {"mode": "not_applicable"}}}}), "experiment_broker_log"),
        (lambda b: b.update({"experiment": {**b["experiment"], "mqtt": {"evidence_class": "stm32_st67_classical_tls_e2e", "transport_backend": "st67w61m1_lwip_wolfssl", "tls": {"mode": "classical_tls_server_auth"}}}}), "tls_key_log"),
        (lambda b: b["experiment"].update({"network": {"degradation": {"rtt_ms": 40}}}), "network_condition_record"),
        (lambda b: (b.update({"boot": {"mode": "wolfboot"}}), b["experiment"].update({"mqtt": {"evidence_class": "secure_boot", "transport_backend": "not_applicable", "tls": {"mode": "not_applicable"}}})), "wolfboot_image"),
        (lambda b: b["experiment"]["firmware"].update({"application": "ota_update"}), "ota_record"),
        (lambda b: b["experiment"].update({"instruments": {"energy": {"profile": "esp32_ina228"}}}), "energy_result_stream"),
    ],
)
def test_minimum_contracts_expand_by_resolved_experiment_features(bundle_mutator, required_role):
    _, evidence = _modules()
    bundle = _bundle()
    bundle_mutator(bundle)
    contract = evidence.build_capture_contract(bundle)
    requirements = {item["role"]: item["requirement"] for item in contract["items"]}
    assert requirements[required_role] == "required"
    if required_role == "wolfboot_image":
        assert requirements["diagnostic_uart"] == "required"
        assert requirements["secure_boot_record"] == "optional"


def test_dirty_and_recursive_submodule_provenance_are_recorded_without_rejection(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from framework import source

    def runner(command, cwd):
        joined = " ".join(command)
        stdout = ""
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            stdout = "abc123\n"
        elif command[:3] == ["git", "branch", "--show-current"]:
            stdout = "feature/request16\n"
        elif command[:3] == ["git", "status", "--short"]:
            stdout = " M scripts/framework/manifest.py\n"
        elif command[:4] == ["git", "diff", "--binary", "HEAD"]:
            stdout = "diff --git a/a b/a\n"
        elif command[:4] == ["git", "ls-files", "--others", "--exclude-standard"]:
            stdout = ""
        elif command[:4] == ["git", "submodule", "status", "--recursive"]:
            stdout = "+deadbeef Middlewares/Third_Party/wolfSSL\n"
        elif command[:3] == ["git", "-C", "Middlewares/Third_Party/wolfSSL"]:
            stdout = " M wolfcrypt/src/x.c\n"
        return source.GitCommandExecution(command=list(command), return_code=0, stdout=stdout, stderr="", duration_seconds=0.0)

    provenance = source.capture_reproducibility_provenance(tmp_path, git_runner=runner, tool_runner=runner)
    assert provenance["git_commit"] == "abc123"
    assert provenance["git_branch"] == "feature/request16"
    assert provenance["git_dirty"] is True
    assert provenance["source_state_sha256"]
    entry = provenance["submodules"]["entries"][0]
    assert entry["checkout_state"] == "different_from_recorded"
    assert entry["dirty"] is True

def test_derived_lineage_sidecar_does_not_mutate_finalized_run_manifest(tmp_path):
    manifest_module, evidence = _modules()
    result_dir, _ = manifest_module.create_result_folder(_bundle(), tmp_path / "results", operation="build_only")
    build_log = result_dir / "build.log"
    build_log.write_text("build\n", encoding="utf-8")
    elf = result_dir / "firmware.elf"
    elf.write_bytes(b"elf")
    manifest_module.update_manifest(result_dir / "manifest.json", {
        "result": "build_passed",
        "build": {"log": "build.log"},
        "firmware": {"result_artifacts": {"elf": {"copied": True, "path": "firmware.elf"}}},
    })
    final = manifest_module.finalize_run_evidence(result_dir / "manifest.json")
    manifest_before = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    derived = result_dir / "summary.json"
    derived.write_text('{"value": 1}\n', encoding="utf-8")
    lineage = manifest_module.register_derived_output(
        result_dir / "manifest.json",
        role="summary",
        path=derived,
        tool="summary-parser",
        version="1",
        input_sha256=[evidence.sha256_file(elf)],
        parameters={"mode": "test"},
    )
    manifest_after = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_after == manifest_before
    assert final["final_index"]["status"] == "finalized"
    assert lineage["sha256"] == evidence.sha256_file(derived)
    assert (result_dir / lineage["lineage_path"]).is_file()


def test_finalization_discovers_unregistered_retained_files_without_parsing_them(tmp_path):
    manifest_module, evidence = _modules()
    result_dir, _ = manifest_module.create_result_folder(_bundle(), tmp_path / "results", operation="build_only")
    (result_dir / "build.log").write_text("build\n", encoding="utf-8")
    (result_dir / "firmware.elf").write_bytes(b"elf")
    extra = result_dir / "custom-device-records.jsonl"
    extra.write_text('{"raw": true}\n', encoding="utf-8")
    manifest_module.update_manifest(result_dir / "manifest.json", {
        "result": "build_passed",
        "build": {"log": "build.log"},
        "firmware": {"result_artifacts": {"elf": {"copied": True, "path": "firmware.elf"}}},
    })
    final = manifest_module.finalize_run_evidence(result_dir / "manifest.json")
    item = next(item for item in final["retained_files"] if item.get("path") == "custom-device-records.jsonl")
    assert item["sha256"] == evidence.sha256_file(extra)
    assert set(item) == {"path", "size_bytes", "sha256"}
    assert final["capture_acceptance"]["accepted"] is True


def test_result_relative_path_already_prefixed_with_results_is_not_doubled(tmp_path, monkeypatch):
    _, evidence = _modules()
    monkeypatch.chdir(tmp_path)
    result_dir = Path("results/run")
    result_dir.mkdir(parents=True)
    artifact = result_dir / "resolved-case.json"
    artifact.write_text("{}\n", encoding="utf-8")
    manifest = {"artifacts": evidence.initial_capture_index({"items": [{"role": "resolved_case_snapshot", "requirement": "required", "source_class": "configuration", "reason": None}]})}
    evidence.register_artifact(
        manifest, result_dir=result_dir, role="resolved_case_snapshot", path=artifact,
        stage="configuration_resolution", tool="resolver",
    )
    item = manifest["artifacts"][0]
    assert item["path"] == "resolved-case.json"
    assert item["acquisition"]["status"] == "available"

def test_finalization_rehashes_raw_files_and_rejects_post_collection_mutation(tmp_path):
    manifest_module, _ = _modules()
    result_dir, _ = manifest_module.create_result_folder(
        _bundle(), tmp_path / "results", operation="build_only"
    )
    build_log = result_dir / "build.log"
    build_log.write_text("build\n", encoding="utf-8")
    elf = result_dir / "firmware.elf"
    elf.write_bytes(b"elf-v1")
    manifest_module.update_manifest(
        result_dir / "manifest.json",
        {
            "result": "build_passed",
            "build": {"log": "build.log"},
            "firmware": {
                "result_artifacts": {
                    "elf": {"copied": True, "path": "firmware.elf"}
                }
            },
        },
    )
    elf.write_bytes(b"elf-v2")
    final = manifest_module.finalize_run_evidence(result_dir / "manifest.json")
    elf_evidence = next(item for item in final["artifacts"] if item["role"] == "application_elf")
    assert elf_evidence["acquisition"]["status"] == "invalid"
    assert final["execution_outcome"]["status"] == "not_applicable"
    assert final["capture_acceptance"]["accepted"] is False


def test_container_runtime_identity_retains_immutable_digest_when_available():
    repo_root = Path(__file__).resolve().parents[2]
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from framework import source

    identity = source.capture_container_runtime_identity(
        {
            "PQC_CONTAINER": "1",
            "PQC_DEV_IMAGE": "example/pqc-dev@sha256:" + "a" * 64,
        }
    )
    assert identity["container"] is True
    assert identity["digest"] == "sha256:" + "a" * 64
    assert identity["immutable_identity_available"] is True


def test_stage_run_updates_preserve_run_identity_metadata(tmp_path):
    manifest_module, _ = _modules()
    bundle = _bundle(evidence_class="stm32_st67_plaintext_e2e")
    result_dir, created = manifest_module.create_result_folder(bundle, tmp_path / "results")
    manifest_module.update_manifest(
        result_dir / "manifest.json",
        {
            "result": "baseline_run_failed",
            "run": {"return_code": 9, "failure_stage": "uart"},
        },
    )
    updated = manifest_module.read_manifest(result_dir / "manifest.json")
    assert updated["run"]["id"] == created["run_id"]
    assert updated["run"]["created_at"]
    assert updated["run"]["return_code"] == 9
    assert updated["run"]["state"] == "running"
    assert updated["execution_outcome"]["status"] == "failed"


def test_finalized_manifest_is_compact_index_and_moves_provenance_to_sidecar(tmp_path):
    manifest_module, evidence = _modules()
    bundle = _bundle()
    result_dir, _ = manifest_module.create_result_folder(bundle, tmp_path / "results", operation="build_only")
    (result_dir / "build.log").write_text("build\n", encoding="utf-8")
    (result_dir / "firmware.elf").write_bytes(b"elf")
    manifest_module.update_manifest(result_dir / "manifest.json", {
        "result": "build_passed",
        "build": {"log": "build.log", "duration_seconds": 12.3, "return_code": 0},
        "firmware": {"result_artifacts": {"elf": {"copied": True, "path": "firmware.elf"}}},
        "uart": {"log": "uart.log", "application_clock_hz": {"hclk_hz": 120000000}},
        "runtime_memory": {"application_checkpoints": [{"heap_peak_used_bytes": 99}]},
        "secure_boot_benchmark": {"samples": [{"verification_time_ms": 1.23}]},
    })
    final = manifest_module.finalize_run_evidence(result_dir / "manifest.json")
    assert final["schema"]["version"] == 3
    assert "build" not in final
    assert "firmware" not in final
    assert "uart" not in final
    assert "runtime_memory" not in final
    assert "secure_boot_benchmark" not in final
    assert "resolved_configuration" not in final
    assert final["configuration"]["configuration_identity"] == "config-sha"
    provenance = json.loads((result_dir / "run-provenance.json").read_text(encoding="utf-8"))
    assert provenance["records"]["build"]["return_code"] == 0
    prov_item = next(item for item in final["artifacts"] if item["role"] == "run_provenance")
    assert prov_item["sha256"] == evidence.sha256_file(result_dir / "run-provenance.json")
    assert final["final_index"]["scope"] == "run_capture_only"
    recomputed = evidence.canonical_sha256({
        "schema": final["schema"],
        "configuration": final["configuration"],
        "contract": final["capture_contract"],
        "artifacts": final["artifacts"],
        "retained_files": final["retained_files"],
        "execution_outcome": final["execution_outcome"],
        "capture_acceptance": final["capture_acceptance"],
    })
    assert final["final_index"]["sha256"] == recomputed


def test_schema_v2_manifest_is_explicitly_legacy_under_schema_v3(tmp_path):
    manifest_module, _ = _modules()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "schema": {"name": "pqc-run-evidence", "version": 2},
        "capture_acceptance": {"accepted": True},
    }), encoding="utf-8")
    data = manifest_module.read_manifest(path)
    assert data["compatibility"]["legacy_manifest"] is True
    assert data["compatibility"]["accepted_under_current_contract"] is False
    with pytest.raises(ValueError, match="unsupported run-evidence schema version"):
        manifest_module.finalize_run_evidence(path)


def test_build_flash_terminal_result_survives_compaction_as_execution_outcome(tmp_path):
    manifest, _ = _modules()
    result_dir, _ = manifest.create_result_folder(_bundle(evidence_class="generic"), tmp_path / "results")
    manifest.update_manifest(
        result_dir / "manifest.json",
        {
            "result": "build_flash_failed",
            "build_flash": {"return_code": 7, "failure_stage": "flash"},
        },
    )
    final = manifest.finalize_run_evidence(result_dir / "manifest.json")
    assert final["execution_outcome"] == {
        "status": "not_executed",
        "result": "build_flash_failed",
        "failure_stage": "flash",
    }
    assert final["run"]["return_code"] == 7
    assert final["run"]["failure_stage"] == "flash"
    assert "build_flash" not in final
    assert "result" not in final


def test_secure_boot_feature_is_detected_from_resolved_choice_and_wolfboot_firmware_mode():
    _, evidence = _modules()
    bundle = _bundle(
        evidence_class="stm32_st67_classical_tls_e2e",
        tls_mode="classical_tls_server_auth",
    )
    bundle["experiment"]["firmware"]["mode"] = "wolfboot_integrity"
    bundle["experiment"]["resolved_configuration"]["choices"]["secure_boot"] = "integrity_sha256"
    # The runtime bundle's legacy boot section can still describe direct flash; the
    # resolved choice/firmware mode are the authoritative signals for this case.
    bundle["boot"] = {"mode": "direct_flash"}

    features = evidence.infer_experiment_features(bundle)
    assert features["secure_boot"] is True

    contract = evidence.build_capture_contract(bundle)
    requirements = {item["role"]: item["requirement"] for item in contract["items"]}
    assert requirements["wolfboot_image"] == "required"
    assert requirements["signed_application"] == "required"
    assert requirements["secure_boot_record"] == "optional"


def test_secure_boot_registration_keeps_deployment_identity_separate_from_flash_log_and_elf(tmp_path):
    manifest_module, evidence = _modules()
    bundle = _bundle(
        evidence_class="stm32_st67_classical_tls_e2e",
        tls_mode="classical_tls_server_auth",
    )
    bundle["experiment"]["firmware"]["mode"] = "wolfboot_integrity"
    bundle["experiment"]["resolved_configuration"]["choices"]["secure_boot"] = "integrity_sha256"

    result_dir, _ = manifest_module.create_result_folder(bundle, tmp_path / "results")
    elf = result_dir / "firmware.elf"
    elf.write_bytes(b"elf")
    flash_log = result_dir / "secure_boot_flash.log"
    flash_log.write_text("flash complete\n", encoding="utf-8")
    signed_dir = result_dir / "prerequisites" / "signing" / "run"
    signed_dir.mkdir(parents=True)
    signed = signed_dir / "application_integrity.bin"
    signed.write_bytes(b"signed application")
    signed_sha = evidence.sha256_file(signed)

    manifest_module.update_manifest(
        result_dir / "manifest.json",
        {
            "firmware": {
                "result_artifacts": {
                    "elf": {"copied": True, "path": "firmware.elf"},
                }
            }
        },
    )
    manifest_module.update_manifest(
        result_dir / "manifest.json",
        {
            "firmware": {
                "result_artifact": "application_integrity.bin",
                "result_artifact_path": signed.as_posix(),
            },
            "secure_boot_evidence": {
                "build_evidence": {
                    "wolfboot_artifact_path": "/outside/wolfboot.elf",
                    "wolfboot_sha256": "a" * 64,
                },
                "signing_evidence": {
                    "signed_application_artifact_path": "/outside/signed.bin",
                    "signed_application_sha256": signed_sha,
                },
                "flash_evidence": {"log": "secure_boot_flash.log"},
            },
        },
    )

    current = manifest_module.read_manifest(result_dir / "manifest.json")
    by_role = {item["role"]: item for item in current["artifacts"]}

    assert by_role["application_elf"]["path"] == "firmware.elf"
    assert by_role["application_elf"]["acquisition"]["status"] == "available"
    assert by_role["application_binary"]["path"].endswith("application_integrity.bin")
    assert by_role["application_binary"]["acquisition"]["status"] == "available"

    assert by_role["flash_log"]["path"] == "secure_boot_flash.log"
    assert by_role["flash_log"]["sha256"] == evidence.sha256_file(flash_log)
    assert by_role["deployment_provenance"]["path"] is None
    assert by_role["deployment_provenance"]["sha256"] == signed_sha
    assert by_role["deployment_provenance"]["acquisition"]["status"] == "available"

    assert by_role["wolfboot_image"]["requirement"] == "required"
    assert by_role["wolfboot_image"]["acquisition"]["status"] == "available"
    assert by_role["signed_application"]["requirement"] == "required"
    assert by_role["signed_application"]["acquisition"]["status"] == "available"
