"""Versioned run-evidence contracts, artefact integrity, and derived lineage.

The run manifest is intentionally an index and acceptance record. Raw evidence and
verbose stage records remain in dedicated result artefacts and are referenced here by
result-relative path and SHA-256 identity.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

RUN_EVIDENCE_SCHEMA_NAME = "pqc-run-evidence"
RUN_EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_CONTRACT_VERSION = 1

REQUIREMENTS = {"required", "optional", "not_applicable"}
ACQUISITION_STATES = {"pending", "available", "unavailable", "invalid", "not_applicable"}
_SECRET_KEY_RE = re.compile(r"(?i)(password|passwd|secret|token|private[_-]?key|psk|credential)")
_REFERENCE_KEY_RE = re.compile(r"(?i)(_ref|_refs|reference|references)$")


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _nonsecret(value: Any, *, key: str | None = None) -> Any:
    """Copy non-secret configuration while retaining named references.

    Secret-bearing keys are omitted unless they are explicit references. This is a
    conservative boundary for result snapshots; callers should still prefer public
    resolver output over raw runtime bundles.
    """
    if key == "secret_references":
        return deepcopy(value)
    if key and _SECRET_KEY_RE.search(key) and not _REFERENCE_KEY_RE.search(key):
        return None
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child_value in value.items():
            copied = _nonsecret(child_value, key=str(child_key))
            if copied is not None:
                result[str(child_key)] = copied
        return result
    if isinstance(value, list):
        return [_nonsecret(item) for item in value]
    if isinstance(value, tuple):
        return [_nonsecret(item) for item in value]
    return deepcopy(value)


def build_resolved_case_snapshot(bundle: dict[str, dict[str, Any]]) -> dict[str, Any]:
    experiment = bundle["experiment"]
    resolved = experiment.get("resolved_configuration")
    if isinstance(resolved, dict):
        configuration = _nonsecret(resolved)
    else:
        configuration = {
            "schema_version": None,
            "resolver_version": None,
            "selected_profiles": {},
            "choices": {},
            "legacy_experiment_id": experiment.get("id"),
        }

    effective: dict[str, Any] = {
        "experiment_id": experiment.get("id"),
        "firmware": _nonsecret(experiment.get("firmware", {})),
        "transport": _nonsecret(experiment.get("transport", {})),
        "services": _nonsecret(experiment.get("services", {})),
        "instruments": _nonsecret(experiment.get("instruments", {})),
        "network": _nonsecret({
            key: value for key, value in experiment.get("network", {}).items()
            if key != "wifi"
        }) if isinstance(experiment.get("network"), dict) else {},
    }
    mqtt = experiment.get("mqtt")
    if isinstance(mqtt, dict):
        effective["mqtt"] = _nonsecret(mqtt)

    return {
        "schema": {"name": "pqc-resolved-case-snapshot", "version": 1},
        "configuration": configuration,
        "effective_non_secret_parameters": effective,
    }


def infer_experiment_features(bundle: dict[str, dict[str, Any]]) -> dict[str, bool | str]:
    experiment = bundle["experiment"]
    mqtt = experiment.get("mqtt") if isinstance(experiment.get("mqtt"), dict) else {}
    evidence_class = str(mqtt.get("evidence_class", ""))
    tls = mqtt.get("tls") if isinstance(mqtt.get("tls"), dict) else {}
    tls_mode = str(tls.get("mode", ""))
    network = experiment.get("network") if isinstance(experiment.get("network"), dict) else {}
    degradation = network.get("degradation") if isinstance(network.get("degradation"), dict) else {}
    instruments = experiment.get("instruments") if isinstance(experiment.get("instruments"), dict) else {}
    firmware = experiment.get("firmware") if isinstance(experiment.get("firmware"), dict) else {}
    boot = bundle.get("boot") if isinstance(bundle.get("boot"), dict) else {}
    workload = str(firmware.get("application", ""))

    build_only = evidence_class == "stm32_build_only" or str(mqtt.get("transport_backend", "")) == "stm32_build_only"
    mqtt_runtime = evidence_class.startswith("stm32_st67_") and not build_only
    tls_runtime = mqtt_runtime and ("tls" in evidence_class or (tls_mode not in {"", "not_applicable", "plaintext"}))
    network_degradation = bool(degradation) and any(
        degradation.get(key) not in (None, 0, 0.0, "", "none")
        for key in ("rate_kbit", "rtt_ms", "loss_percent", "mtu")
    )
    secure_boot = str(boot.get("mode", firmware.get("mode", ""))) == "wolfboot" or "secure_boot" in workload
    ota = "ota" in workload.lower() or "update" in workload.lower()
    energy = "energy" in instruments and instruments.get("energy") not in (None, {}, "")
    structured_reporting = bool(experiment.get("structured_reporting", {}).get("enabled")) if isinstance(experiment.get("structured_reporting"), dict) else False

    primary = "build_only" if build_only else "tls_runtime" if tls_runtime else "mqtt_plaintext_runtime" if mqtt_runtime else "secure_boot" if secure_boot else "generic_runtime"
    return {
        "primary_class": primary,
        "build_only": build_only,
        "mqtt_runtime": mqtt_runtime,
        "tls_runtime": tls_runtime,
        "network_degradation": network_degradation,
        "secure_boot": secure_boot,
        "ota": ota,
        "energy": energy,
        "structured_reporting": structured_reporting,
    }


def _contract_item(role: str, requirement: str, source_class: str, *, reason: str | None = None) -> dict[str, Any]:
    if requirement not in REQUIREMENTS:
        raise ValueError(f"unsupported evidence requirement: {requirement}")
    return {
        "role": role,
        "requirement": requirement,
        "source_class": source_class,
        "reason": reason,
    }


def build_evidence_contract(bundle: dict[str, dict[str, Any]], *, operation: str | None = None) -> dict[str, Any]:
    features = infer_experiment_features(bundle)
    if operation == "build_only":
        features = {**features, "primary_class": "build_only", "build_only": True, "mqtt_runtime": False, "tls_runtime": False, "network_degradation": False, "secure_boot": False, "ota": False, "energy": False}
    items: list[dict[str, Any]] = [
        _contract_item("resolved_case_snapshot", "required", "configuration"),
        _contract_item("cryptographic_material_inventory", "optional", "provisioning"),
    ]

    if features["build_only"]:
        items += [
            _contract_item("build_log", "required", "build"),
            _contract_item("application_elf", "required", "build"),
        ]
    elif features["mqtt_runtime"]:
        items += [
            _contract_item("deployment_provenance", "required", "deployment"),
            _contract_item("flash_log", "optional", "deployment"),
            _contract_item("diagnostic_uart", "required", "stm32_runtime"),
            _contract_item("experiment_broker_log", "required", "broker"),
            _contract_item("packet_capture", "required", "network"),
            _contract_item("observer_evidence", "required", "broker_observer"),
            _contract_item(
                "stm32_result_stream",
                "required" if features["structured_reporting"] else "optional",
                "stm32_runtime",
                reason=None if features["structured_reporting"] else "Structured reporting is introduced by the reporting-broker implementation request.",
            ),
        ]
        if features["tls_runtime"]:
            items.append(_contract_item("tls_key_log", "required", "network"))
        else:
            items.append(_contract_item("tls_key_log", "not_applicable", "network", reason="Plaintext MQTT runtime."))
    else:
        items += [
            _contract_item("build_log", "optional", "build"),
            _contract_item("application_elf", "optional", "build"),
            _contract_item(
                "diagnostic_uart",
                "required" if features["secure_boot"] else "optional",
                "stm32_runtime",
                reason=None if features["secure_boot"] else "Diagnostic UART is supplemental for this experiment class.",
            ),
        ]

    if features["network_degradation"]:
        items.append(_contract_item("network_condition_record", "required", "network_control"))
    else:
        items.append(_contract_item("network_condition_record", "not_applicable", "network_control", reason="No controlled network degradation selected."))

    if features["secure_boot"]:
        items += [
            _contract_item("wolfboot_image", "required", "secure_boot"),
            _contract_item("signed_application", "required", "secure_boot"),
            _contract_item("secure_boot_record", "required", "secure_boot"),
        ]
    else:
        for role in ("wolfboot_image", "signed_application", "secure_boot_record"):
            items.append(_contract_item(role, "not_applicable", "secure_boot", reason="Secure boot is not selected."))

    if features["ota"]:
        items.append(_contract_item("ota_record", "required", "ota"))
    else:
        items.append(_contract_item("ota_record", "not_applicable", "ota", reason="OTA workload is not selected."))

    if features["energy"]:
        items.append(_contract_item("energy_result_stream", "required", "energy"))
    else:
        items.append(_contract_item("energy_result_stream", "not_applicable", "energy", reason="Energy measurement is not enabled."))

    # Preserve declaration order while rejecting accidental duplicate roles.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        if item["role"] in seen:
            continue
        seen.add(item["role"])
        unique.append(item)
    return {
        "version": EVIDENCE_CONTRACT_VERSION,
        "experiment_class": features["primary_class"],
        "features": features,
        "items": unique,
    }


def initial_evidence_index(contract: dict[str, Any]) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    for spec in contract.get("items", []):
        requirement = spec["requirement"]
        state = "not_applicable" if requirement == "not_applicable" else "pending"
        index.append({
            "source_class": spec["source_class"],
            "role": spec["role"],
            "path": None,
            "producer": None,
            "size_bytes": None,
            "sha256": None,
            "requirement": requirement,
            "acquisition": {"status": state, "reason": spec.get("reason")},
        })
    return index


def initialize_manifest_evidence(manifest: dict[str, Any], bundle: dict[str, dict[str, Any]], *, operation: str | None = None) -> None:
    contract = build_evidence_contract(bundle, operation=operation)
    manifest["schema"] = {"name": RUN_EVIDENCE_SCHEMA_NAME, "version": RUN_EVIDENCE_SCHEMA_VERSION}
    manifest["evidence_contract"] = contract
    manifest["evidence"] = initial_evidence_index(contract)
    manifest["derived"] = []
    manifest["sut_outcome"] = {"status": "pending", "result": None, "failure_stage": None}
    manifest["evidence_acceptance"] = {"status": "pending", "accepted": False, "reasons": [], "contract_version": contract["version"]}
    manifest["final_index"] = None
    manifest["preparation"] = {
        "mode": "in_run",
        "manifest": None,
        "firmware_sha256": None,
        "verified": None,
    }


def _entry(manifest: dict[str, Any], role: str) -> dict[str, Any]:
    evidence = manifest.setdefault("evidence", [])
    for item in evidence:
        if item.get("role") == role:
            return item
    item = {
        "source_class": "extension",
        "role": role,
        "path": None,
        "producer": None,
        "size_bytes": None,
        "sha256": None,
        "requirement": "optional",
        "acquisition": {"status": "pending", "reason": "Extension evidence role registered after contract generation."},
    }
    evidence.append(item)
    return item


def _result_relative(result_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(result_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"evidence artefact must be retained beneath result directory: {path}") from exc


def register_artifact(
    manifest: dict[str, Any], *, result_dir: Path | str, role: str, path: Path | str,
    stage: str, tool: str, acquisition_result: str = "produced", source_class: str | None = None,
) -> None:
    result_root = Path(result_dir)
    artifact = Path(path)
    if not artifact.is_absolute():
        artifact = result_root / artifact
    if not artifact.is_file():
        mark_evidence(manifest, role=role, status="unavailable", reason=f"Expected artefact is unavailable: {artifact}", stage=stage, tool=tool)
        return
    relative = _result_relative(result_root, artifact)
    digest = sha256_file(artifact)
    item = _entry(manifest, role)
    previous_digest = item.get("sha256")
    previous_status = (item.get("acquisition") or {}).get("status")
    if previous_status == "available" and previous_digest and previous_digest != digest:
        raise ValueError(f"raw evidence role '{role}' is immutable once collected")
    if source_class:
        item["source_class"] = source_class
    item.update({
        "path": relative,
        "producer": {"stage": stage, "tool": tool},
        "size_bytes": artifact.stat().st_size,
        "sha256": digest,
        "acquisition": {"status": "available", "result": acquisition_result, "reason": None},
    })


def register_identity(
    manifest: dict[str, Any], *, role: str, sha256: str | None, stage: str, tool: str,
    acquisition_result: str, path: str | None = None, size_bytes: int | None = None,
    source_class: str | None = None,
) -> None:
    item = _entry(manifest, role)
    if source_class:
        item["source_class"] = source_class
    if sha256 is None:
        mark_evidence(manifest, role=role, status="unavailable", reason="Evidence identity has no SHA-256.", stage=stage, tool=tool)
        return
    previous_digest = item.get("sha256")
    previous_status = (item.get("acquisition") or {}).get("status")
    if previous_status == "available" and previous_digest and previous_digest != sha256:
        raise ValueError(f"raw evidence role '{role}' is immutable once collected")
    item.update({
        "path": path,
        "producer": {"stage": stage, "tool": tool},
        "size_bytes": size_bytes,
        "sha256": sha256,
        "acquisition": {"status": "available", "result": acquisition_result, "reason": None},
    })


def mark_evidence(manifest: dict[str, Any], *, role: str, status: str, reason: str, stage: str, tool: str) -> None:
    if status not in {"unavailable", "invalid", "not_applicable"}:
        raise ValueError(f"unsupported evidence status: {status}")
    item = _entry(manifest, role)
    if item.get("requirement") == "not_applicable" and status != "not_applicable":
        return
    item["producer"] = {"stage": stage, "tool": tool}
    item["acquisition"] = {"status": status, "reason": reason}


def register_derived(
    manifest: dict[str, Any], *, result_dir: Path | str, role: str, path: Path | str,
    tool: str, version: str, input_sha256: Iterable[str], parameters: dict[str, Any] | None = None,
) -> None:
    output = Path(path)
    root = Path(result_dir)
    if not output.is_absolute():
        output = root / output
    if not output.is_file():
        raise FileNotFoundError(f"derived output not found: {output}")
    direct_inputs = [value for value in input_sha256 if isinstance(value, str) and value]
    if not direct_inputs:
        raise ValueError("derived output must identify at least one direct input SHA-256")
    record = {
        "role": role,
        "path": _result_relative(root, output),
        "producer": {"tool": tool, "version": version},
        "inputs": [{"sha256": value} for value in direct_inputs],
        "parameters": deepcopy(parameters or {}),
        "size_bytes": output.stat().st_size,
        "sha256": sha256_file(output),
    }
    records = manifest.setdefault("derived", [])
    for index, existing in enumerate(records):
        if existing.get("role") == role:
            records[index] = record
            break
    else:
        records.append(record)


def update_sut_outcome(manifest: dict[str, Any], result: Any, failure_stage: Any = None) -> None:
    """Update only the system-under-test outcome, not generic framework stages.

    Build/flash/preparation commands can succeed or fail without the SUT workload
    having executed.  The outcome therefore changes only for a build-only contract
    (where SUT execution is not applicable) or an explicit runtime/secure-boot
    experiment result.
    """

    text = str(result) if result is not None else ""
    experiment_class = str((manifest.get("evidence_contract") or {}).get("experiment_class", ""))
    if experiment_class == "build_only":
        manifest["sut_outcome"] = {
            "status": "not_applicable",
            "result": text or None,
            "failure_stage": failure_stage,
        }
        return
    if not text:
        return

    lowered = text.lower()
    explicit_runtime_result = (
        lowered.startswith("baseline_run_")
        or lowered.startswith("secure_boot_")
        or lowered.startswith("mqtt_run_")
        or lowered.startswith("runtime_")
    )
    if not explicit_runtime_result:
        return

    pre_sut_stages = {
        "external_dependencies", "build", "application_build", "wolfboot_build",
        "application_signing", "artifact_copy", "flash", "secure_boot_flash",
        "profile_validation", "broker_start", "broker_readiness",
        "gateway_packet_capture_start", "network_degradation_config",
        "network_degradation_apply",
    }
    stage = None if failure_stage is None else str(failure_stage)
    if any(token in lowered for token in ("fail", "error", "refused")):
        status = "not_executed" if stage in pre_sut_stages else "failed"
    elif lowered.endswith("_passed") or lowered in {"pass", "passed", "success", "succeeded"}:
        status = "succeeded"
    else:
        return
    manifest["sut_outcome"] = {"status": status, "result": text, "failure_stage": stage}


def verify_and_freeze_raw_artifacts(manifest: dict[str, Any], *, result_dir: Path | str) -> None:
    """Re-hash retained raw files and make them read-only before acceptance.

    Logical immutability is enforced by the evidence registration API and sealed
    final index.  Filesystem write bits are also removed on a best-effort basis so
    normal framework/analysis paths cannot accidentally overwrite collected raw
    evidence.
    """

    root = Path(result_dir).resolve()
    for item in manifest.get("evidence", []):
        if (item.get("acquisition") or {}).get("status") != "available":
            continue
        relative = item.get("path")
        if not isinstance(relative, str) or not relative:
            # Identity-only evidence is bound by SHA-256 but has no retained file
            # to freeze in this run directory.
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            item["acquisition"] = {
                "status": "invalid",
                "reason": "Retained evidence path escapes the result directory.",
            }
            continue
        if not candidate.is_file():
            item["acquisition"] = {
                "status": "unavailable",
                "reason": f"Retained evidence file is missing at finalization: {relative}",
            }
            continue
        actual_size = candidate.stat().st_size
        actual_sha256 = sha256_file(candidate)
        if actual_size != item.get("size_bytes") or actual_sha256 != item.get("sha256"):
            item["acquisition"] = {
                "status": "invalid",
                "reason": "Retained evidence size/SHA-256 changed after collection.",
            }
            item["observed_at_finalization"] = {
                "size_bytes": actual_size,
                "sha256": actual_sha256,
            }
            continue
        try:
            candidate.chmod(candidate.stat().st_mode & ~0o222)
            item["immutability"] = {"status": "enforced", "method": "read_only_mode"}
        except OSError as exc:
            # The sealed hash/index and registration rules still provide logical
            # immutability on filesystems that do not support mode changes.
            item["immutability"] = {
                "status": "logical_only",
                "method": "sealed_index",
                "reason": str(exc),
            }

def evaluate_acceptance(manifest: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    for item in manifest.get("evidence", []):
        if item.get("requirement") != "required":
            continue
        status = (item.get("acquisition") or {}).get("status")
        if status != "available":
            reason = (item.get("acquisition") or {}).get("reason") or f"required evidence is {status or 'missing'}"
            reasons.append(f"{item.get('role')}: {reason}")
    accepted = not reasons
    return {
        "status": "accepted" if accepted else "rejected_incomplete",
        "accepted": accepted,
        "reasons": reasons,
        "contract_version": (manifest.get("evidence_contract") or {}).get("version"),
    }


def finalize_manifest(manifest: dict[str, Any], *, finalized_at: str) -> None:
    acceptance = evaluate_acceptance(manifest)
    manifest["evidence_acceptance"] = acceptance
    immutable_index = {
        "schema": manifest.get("schema"),
        "configuration": manifest.get("configuration"),
        "preparation": manifest.get("preparation"),
        "contract": manifest.get("evidence_contract"),
        "evidence": manifest.get("evidence", []),
        "derived": manifest.get("derived", []),
        "sut_outcome": manifest.get("sut_outcome"),
        "evidence_acceptance": acceptance,
    }
    manifest["final_index"] = {
        "status": "finalized",
        "finalized_at": finalized_at,
        "sha256": canonical_sha256(immutable_index),
    }


def validate_manifest_schema(manifest: dict[str, Any]) -> tuple[bool, str | None]:
    schema = manifest.get("schema")
    if not isinstance(schema, dict):
        return False, "legacy manifest has no versioned run-evidence schema"
    if schema.get("name") != RUN_EVIDENCE_SCHEMA_NAME:
        return False, "unsupported run-evidence schema name"
    version = schema.get("version")
    if version != RUN_EVIDENCE_SCHEMA_VERSION:
        return False, f"unsupported run-evidence schema version: {version!r}"
    return True, None
