"""Versioned run-capture provenance and artefact integrity.

The run manifest records execution/capture provenance only. Scientific metrics are
not interpreted here: raw observations are retained as immutable artefacts and later
ingestion/analysis stages operate on those artefacts using their recorded hashes.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

RUN_EVIDENCE_SCHEMA_NAME = "pqc-run-evidence"
RUN_EVIDENCE_SCHEMA_VERSION = 3
CAPTURE_CONTRACT_VERSION = 2
# Compatibility alias for code/tests written against the first Request-16 draft.
EVIDENCE_CONTRACT_VERSION = CAPTURE_CONTRACT_VERSION

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
    """Copy non-secret configuration while retaining named references."""
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
    tls_runtime = mqtt_runtime and ("tls" in evidence_class or tls_mode not in {"", "not_applicable", "plaintext"})
    network_degradation = bool(degradation) and any(
        degradation.get(key) not in (None, 0, 0.0, "", "none")
        for key in ("rate_kbit", "rtt_ms", "loss_percent", "mtu")
    )
    resolved = experiment.get("resolved_configuration") if isinstance(experiment.get("resolved_configuration"), dict) else {}
    resolved_choices = resolved.get("choices") if isinstance(resolved.get("choices"), dict) else {}
    secure_boot_choice = str(resolved_choices.get("secure_boot", "")).strip().lower()
    boot_mode = str(boot.get("mode", "")).strip().lower()
    firmware_mode = str(firmware.get("mode", "")).strip().lower()
    secure_boot = (
        boot_mode.startswith("wolfboot")
        or firmware_mode.startswith("wolfboot")
        or secure_boot_choice not in {"", "none", "not_applicable", "disabled", "false"}
        or "secure_boot" in workload.lower()
    )
    ota = "ota" in workload.lower() or "update" in workload.lower()
    energy = "energy" in instruments and instruments.get("energy") not in (None, {}, "")
    structured_reporting = bool(experiment.get("structured_reporting", {}).get("enabled")) if isinstance(experiment.get("structured_reporting"), dict) else False
    uart_output_mode = str(firmware.get("uart_output_mode", "minimal")).strip().lower()

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
        "uart_output_mode": uart_output_mode,
    }


def _contract_item(role: str, requirement: str, source_class: str, *, reason: str | None = None) -> dict[str, Any]:
    if requirement not in REQUIREMENTS:
        raise ValueError(f"unsupported capture requirement: {requirement}")
    return {"role": role, "requirement": requirement, "source_class": source_class, "reason": reason}


def build_capture_contract(bundle: dict[str, dict[str, Any]], *, operation: str | None = None) -> dict[str, Any]:
    """Build the minimum raw-capture contract for this resolved experiment.

    Contract items describe artefacts that must be retained, not scientific metrics
    that must be parsed from them. Future producers may add roles without changing
    the common artefact envelope.
    """
    features = infer_experiment_features(bundle)
    if operation == "build_only":
        features = {
            **features,
            "primary_class": "build_only",
            "build_only": True,
            "mqtt_runtime": False,
            "tls_runtime": False,
            "network_degradation": False,
            "secure_boot": False,
            "ota": False,
            "energy": False,
        }

    items: list[dict[str, Any]] = [
        _contract_item("resolved_case_snapshot", "required", "configuration"),
        _contract_item("run_provenance", "required", "provenance"),
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
            _contract_item(
                "diagnostic_uart",
                "not_applicable" if features["uart_output_mode"] == "disabled" else "optional",
                "stm32_runtime",
                reason="UART is compile-time disabled for this firmware." if features["uart_output_mode"] == "disabled" else "Diagnostic/fallback evidence only; structured result acceptance does not depend on UART.",
            ),
            _contract_item("experiment_broker_log", "required", "broker"),
            _contract_item("packet_capture", "required", "network"),
            _contract_item("observer_evidence", "required", "broker_observer"),
            _contract_item(
                "stm32_result_stream",
                "required" if features["structured_reporting"] else "optional",
                "stm32_runtime",
                reason=None if features["structured_reporting"] else "Structured reporting is unavailable for this legacy case.",
            ),
        ]
        items.append(
            _contract_item("tls_key_log", "required", "network")
            if features["tls_runtime"]
            else _contract_item("tls_key_log", "not_applicable", "network", reason="Plaintext MQTT runtime.")
        )
    else:
        items += [
            _contract_item("build_log", "optional", "build"),
            _contract_item("application_elf", "optional", "build"),
            _contract_item("diagnostic_uart", "required" if features["secure_boot"] else "optional", "stm32_runtime"),
        ]

    items.append(
        _contract_item("network_condition_record", "required", "network_control")
        if features["network_degradation"]
        else _contract_item("network_condition_record", "not_applicable", "network_control", reason="No controlled network degradation selected.")
    )

    if features["secure_boot"]:
        items += [
            _contract_item("wolfboot_image", "required", "secure_boot"),
            _contract_item("signed_application", "required", "secure_boot"),
            _contract_item("secure_boot_record", "optional", "secure_boot", reason="Legacy structured secure-boot stage record; raw flash/UART artefacts are authoritative capture."),
        ]
    else:
        items += [
            _contract_item(role, "not_applicable", "secure_boot", reason="Secure boot is not selected.")
            for role in ("wolfboot_image", "signed_application", "secure_boot_record")
        ]

    items.append(
        _contract_item("ota_record", "required", "ota")
        if features["ota"]
        else _contract_item("ota_record", "not_applicable", "ota", reason="OTA workload is not selected.")
    )
    items.append(
        _contract_item("energy_result_stream", "required", "energy")
        if features["energy"]
        else _contract_item("energy_result_stream", "not_applicable", "energy", reason="Energy measurement is not enabled.")
    )

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        if item["role"] in seen:
            continue
        seen.add(item["role"])
        unique.append(item)
    return {
        "version": CAPTURE_CONTRACT_VERSION,
        "experiment_class": features["primary_class"],
        "features": features,
        "items": unique,
        "scope": "capture_integrity_only",
    }


# Backwards-compatible function name; semantics are capture-only in schema v2.
def build_evidence_contract(bundle: dict[str, dict[str, Any]], *, operation: str | None = None) -> dict[str, Any]:
    return build_capture_contract(bundle, operation=operation)


def initial_capture_index(contract: dict[str, Any]) -> list[dict[str, Any]]:
    index: list[dict[str, Any]] = []
    for spec in contract.get("items", []):
        requirement = spec["requirement"]
        state = "not_applicable" if requirement == "not_applicable" else "pending"
        index.append({
            "artifact_id": spec["role"],
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


# Compatibility alias used by older tests/helpers.
def initial_evidence_index(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return initial_capture_index(contract)


def initialize_manifest_evidence(manifest: dict[str, Any], bundle: dict[str, dict[str, Any]], *, operation: str | None = None) -> None:
    contract = build_capture_contract(bundle, operation=operation)
    manifest["schema"] = {"name": RUN_EVIDENCE_SCHEMA_NAME, "version": RUN_EVIDENCE_SCHEMA_VERSION}
    manifest["capture_contract"] = contract
    manifest["capture_policy"] = {
        "scientific_interpretation": "offline_ingestion_only",
        "manifest_metric_fields_authoritative": False,
        "legacy_stage_payloads": "compatibility_only",
        "analysis_namespace": "analysis/",
    }
    manifest["artifacts"] = initial_capture_index(contract)
    manifest["retained_files"] = []
    manifest["execution_outcome"] = {"status": "pending", "result": None, "failure_stage": None}
    manifest["capture_acceptance"] = {
        "status": "pending",
        "accepted": False,
        "reasons": [],
        "contract_version": contract["version"],
        "scope": "capture_integrity_only",
    }
    manifest["final_index"] = None
    manifest["preparation"] = {"mode": "in_run", "manifest": None, "firmware_sha256": None, "verified": None}


def _artifact_collection(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(manifest.get("artifacts"), list):
        return manifest["artifacts"]
    if isinstance(manifest.get("evidence"), list):  # schema-v1 helper compatibility
        return manifest["evidence"]
    manifest["artifacts"] = []
    return manifest["artifacts"]


def _entry(manifest: dict[str, Any], role: str) -> dict[str, Any]:
    artifacts = _artifact_collection(manifest)
    for item in artifacts:
        if item.get("role") == role and item.get("artifact_id", role) == role:
            return item
    item = {
        "artifact_id": role,
        "source_class": "extension",
        "role": role,
        "path": None,
        "producer": None,
        "size_bytes": None,
        "sha256": None,
        "requirement": "optional",
        "acquisition": {"status": "pending", "reason": "Extension capture role registered after contract generation."},
    }
    artifacts.append(item)
    return item


def _result_relative(result_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(result_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"captured artefact must be retained beneath result directory: {path}") from exc


def _resolve_artifact_path(result_root: Path, path: Path | str) -> Path:
    artifact = Path(path)
    if artifact.is_absolute():
        return artifact
    # Existing framework stage records sometimes already carry a repository-relative
    # path beginning with results/<run-id>. Prefer it when it exists so we do not
    # accidentally prefix the result directory twice.
    if artifact.is_file():
        return artifact.resolve()
    return (result_root / artifact).resolve()


def register_artifact(
    manifest: dict[str, Any], *, result_dir: Path | str, role: str, path: Path | str,
    stage: str, tool: str, acquisition_result: str = "produced", source_class: str | None = None,
) -> None:
    result_root = Path(result_dir).resolve()
    artifact = _resolve_artifact_path(result_root, path)
    if not artifact.is_file():
        mark_evidence(manifest, role=role, status="unavailable", reason=f"Expected artefact is unavailable: {artifact}", stage=stage, tool=tool)
        return
    relative = _result_relative(result_root, artifact)
    digest = sha256_file(artifact)
    item = _entry(manifest, role)
    previous_digest = item.get("sha256")
    previous_status = (item.get("acquisition") or {}).get("status")
    if previous_status == "available" and previous_digest and previous_digest != digest:
        raise ValueError(f"raw capture role '{role}' is immutable once collected")
    if source_class:
        item["source_class"] = source_class
    item.update({
        "artifact_id": role,
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
        mark_evidence(manifest, role=role, status="unavailable", reason="Capture identity has no SHA-256.", stage=stage, tool=tool)
        return
    previous_digest = item.get("sha256")
    previous_status = (item.get("acquisition") or {}).get("status")
    if previous_status == "available" and previous_digest and previous_digest != sha256:
        raise ValueError(f"raw capture role '{role}' is immutable once collected")
    item.update({
        "artifact_id": role,
        "path": path,
        "producer": {"stage": stage, "tool": tool},
        "size_bytes": size_bytes,
        "sha256": sha256,
        "acquisition": {"status": "available", "result": acquisition_result, "reason": None},
    })


def mark_evidence(manifest: dict[str, Any], *, role: str, status: str, reason: str, stage: str, tool: str) -> None:
    if status not in {"unavailable", "invalid", "not_applicable"}:
        raise ValueError(f"unsupported capture status: {status}")
    item = _entry(manifest, role)
    if item.get("requirement") == "not_applicable" and status != "not_applicable":
        return
    item["producer"] = {"stage": stage, "tool": tool}
    item["acquisition"] = {"status": status, "reason": reason}


def _infer_discovered_metadata(relative: str) -> tuple[str, str]:
    name = Path(relative).name.lower()
    suffix = Path(relative).suffix.lower()
    if name == "resolved-case.json":
        return "configuration", "resolved_case_snapshot"
    if name == "material-inventory.json":
        return "provisioning", "cryptographic_material_inventory"
    if name == "build.log":
        return "build", "build_log"
    if name in {"flash.log", "secure_boot_flash.log"}:
        return "deployment", "flash_log"
    if name.startswith("uart") and suffix == ".log":
        return "stm32_runtime", "diagnostic_uart"
    if suffix in {".pcap", ".pcapng"}:
        return "network", "packet_capture"
    if "keylog" in name:
        return "network", "tls_key_log"
    if name == "mqtt-broker-log.log":
        return "broker", "experiment_broker_log"
    if name == "mqtt-reporting-raw.ndjson":
        return "stm32_runtime", "stm32_result_stream"
    if "reporting" in name and suffix == ".log":
        return "broker", "reporting_broker_log"
    if name == "mqtt-broker-message-evidence.json":
        return "broker_observer", "observer_evidence"
    if suffix == ".elf":
        return "build", "application_elf"
    if suffix in {".bin", ".hex"}:
        return "build", "firmware_image"
    if suffix == ".log":
        return "diagnostic", "diagnostic_log"
    if suffix in {".json", ".jsonl", ".ndjson"}:
        return "structured_record", "structured_record"
    return "retained_file", "retained_artifact"


def discover_retained_artifacts(manifest: dict[str, Any], *, result_dir: Path | str) -> None:
    """Hash every retained run file without turning incidental files into verbose evidence records.

    Contract/semantic artefacts stay in ``artifacts``. Everything else is listed once in
    the compact ``retained_files`` inventory as path, size and SHA-256. No scientific
    content is parsed. ``manifest.json``, mutable manual notes and the later ``analysis/``
    namespace are intentionally excluded.
    """
    root = Path(result_dir).resolve()
    artifacts = _artifact_collection(manifest)
    retained = manifest.setdefault("retained_files", [])
    retained_by_path = {
        item.get("path"): item for item in retained
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    indexed_paths = {
        item.get("path") for item in artifacts
        if isinstance(item.get("path"), str) and item.get("path")
    }
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root).as_posix()
        if relative in {"manifest.json", "notes.md"} or relative.startswith("analysis/"):
            continue
        if relative in indexed_paths:
            continue
        source_class, role = _infer_discovered_metadata(relative)
        declared = next(
            (
                item for item in artifacts
                if item.get("role") == role
                and (item.get("acquisition") or {}).get("status") == "pending"
            ),
            None,
        )
        if declared is not None:
            register_artifact(
                manifest,
                result_dir=root,
                role=role,
                path=candidate,
                stage="final_capture_inventory",
                tool="framework.run_evidence",
                acquisition_result="discovered",
                source_class=source_class,
            )
            indexed_paths.add(relative)
            continue

        record = {
            "path": relative,
            "size_bytes": candidate.stat().st_size,
            "sha256": sha256_file(candidate),
        }
        existing = retained_by_path.get(relative)
        if existing is None:
            retained.append(record)
            retained_by_path[relative] = record
        else:
            existing.update(record)


def build_run_provenance_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return provenance needed to reproduce/deploy the run without scientific results."""
    keep = (
        "source",
        "external_dependencies",
        "build",
        "build_number",
        "build_reference",
        "firmware",
        "preparation",
        "boot_selection",
        "application_signing",
        "wolfboot_build",
        "runtime_services",
        "measurement_instruments",
    )
    payload = {
        "schema": {"name": "pqc-run-provenance", "version": 1},
        "records": {key: deepcopy(manifest[key]) for key in keep if key in manifest},
    }
    return payload


def write_run_provenance_snapshot(manifest: dict[str, Any], *, result_dir: Path | str) -> Path:
    root = Path(result_dir).resolve()
    path = root / "run-provenance.json"
    path.write_text(json.dumps(build_run_provenance_snapshot(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    register_artifact(
        manifest,
        result_dir=root,
        role="run_provenance",
        path=path,
        stage="run_finalization",
        tool="framework.run_evidence",
        acquisition_result="snapshotted",
        source_class="provenance",
    )
    return path


def verify_retained_files(manifest: dict[str, Any], *, result_dir: Path | str) -> None:
    root = Path(result_dir).resolve()
    for item in manifest.get("retained_files", []):
        if not isinstance(item, dict):
            continue
        relative = item.get("path")
        if not isinstance(relative, str) or not relative:
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            item["integrity"] = "invalid_path"
            continue
        if not candidate.is_file():
            item["integrity"] = "missing"
            continue
        actual_size = candidate.stat().st_size
        actual_sha = sha256_file(candidate)
        if actual_size != item.get("size_bytes") or actual_sha != item.get("sha256"):
            item["integrity"] = "mismatch"
            continue
        item.pop("integrity", None)
        try:
            candidate.chmod(candidate.stat().st_mode & ~0o222)
        except OSError:
            pass


def compact_final_manifest(manifest: dict[str, Any]) -> None:
    """Discard runtime/metric payloads after they have served orchestration.

    The finalized manifest is intentionally a small index. Reproducibility detail is
    retained in ``run-provenance.json`` and raw/diagnostic files are retained through
    the compact file inventory. Parsed metrics are not preserved as authoritative run
    state.
    """
    resolved = manifest.get("resolved_configuration") if isinstance(manifest.get("resolved_configuration"), dict) else {}
    configuration = dict(manifest.get("configuration") or {})
    for key in ("configuration_identity", "firmware_identity", "resolver_version", "schema_version"):
        if resolved.get(key) is not None:
            configuration[key] = resolved.get(key)

    run = dict(manifest.get("run") or {})
    # Keep only stable lifecycle fields; verbose step data belongs in logs.
    run = {k: run[k] for k in ("id", "created_at", "state", "return_code", "failure_stage") if k in run}

    compact = {
        "schema": manifest.get("schema"),
        "run": run,
        "configuration": configuration,
        "capture_contract": manifest.get("capture_contract"),
        "execution_outcome": manifest.get("execution_outcome"),
        "capture_acceptance": manifest.get("capture_acceptance"),
        "artifacts": _artifact_collection(manifest),
        "retained_files": manifest.get("retained_files", []),
        "final_index": manifest.get("final_index"),
    }
    manifest.clear()
    manifest.update(compact)

def build_derived_record(
    *, result_dir: Path | str, role: str, path: Path | str, tool: str, version: str,
    input_sha256: Iterable[str], parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build lineage for an offline derived output without mutating the run manifest."""
    root = Path(result_dir).resolve()
    output = _resolve_artifact_path(root, path)
    if not output.is_file():
        raise FileNotFoundError(f"derived output not found: {output}")
    direct_inputs = [value for value in input_sha256 if isinstance(value, str) and value]
    if not direct_inputs:
        raise ValueError("derived output must identify at least one direct input SHA-256")
    return {
        "schema": {"name": "pqc-derived-lineage", "version": 1},
        "role": role,
        "path": _result_relative(root, output),
        "producer": {"tool": tool, "version": version},
        "inputs": [{"sha256": value} for value in direct_inputs],
        "parameters": deepcopy(parameters or {}),
        "size_bytes": output.stat().st_size,
        "sha256": sha256_file(output),
    }


def register_derived(
    manifest: dict[str, Any], *, result_dir: Path | str, role: str, path: Path | str,
    tool: str, version: str, input_sha256: Iterable[str], parameters: dict[str, Any] | None = None,
) -> None:
    """Compatibility helper for old callers.

    New run manifests must not use this path; derived lineage belongs in a separate
    analysis sidecar. It remains available so historical/offline tooling can build
    the same lineage record while it migrates.
    """
    record = build_derived_record(
        result_dir=result_dir,
        role=role,
        path=path,
        tool=tool,
        version=version,
        input_sha256=input_sha256,
        parameters=parameters,
    )
    records = manifest.setdefault("derived", [])
    for index, existing in enumerate(records):
        if existing.get("role") == role:
            records[index] = record
            break
    else:
        records.append(record)


def update_sut_outcome(manifest: dict[str, Any], result: Any, failure_stage: Any = None) -> None:
    """Record orchestration/SUT completion without interpreting scientific metrics."""
    text = str(result) if result is not None else ""
    experiment_class = str((manifest.get("capture_contract") or manifest.get("evidence_contract") or {}).get("experiment_class", ""))
    if experiment_class == "build_only":
        manifest["execution_outcome"] = {"status": "not_applicable", "result": text or None, "failure_stage": failure_stage}
        return
    if not text:
        return

    lowered = text.lower()
    explicit_runtime_result = (
        lowered.startswith("baseline_run_")
        or lowered.startswith("secure_boot_")
        or lowered.startswith("mqtt_run_")
        or lowered.startswith("runtime_")
        or lowered.startswith("build_flash_")
        or lowered.startswith("flash_")
        or lowered.startswith("preparation_")
        or lowered.startswith("fake_mqtt_transport_")
    )
    if not explicit_runtime_result:
        return

    pre_sut_stages = {
        "external_dependencies", "build", "application_build", "wolfboot_build",
        "application_signing", "artifact_copy", "flash", "secure_boot_flash",
        "profile_validation", "broker_start", "broker_readiness",
        "gateway_packet_capture_start", "network_degradation_config", "network_degradation_apply",
    }
    stage = None if failure_stage is None else str(failure_stage)
    if any(token in lowered for token in ("fail", "error", "refused")):
        status = "not_executed" if stage in pre_sut_stages else "failed"
    elif (
        lowered.endswith("_passed")
        or lowered.endswith("_completed")
        or lowered in {"pass", "passed", "success", "succeeded", "completed"}
    ):
        status = "completed"
    else:
        return
    manifest["execution_outcome"] = {"status": status, "result": text, "failure_stage": stage}


def verify_and_freeze_raw_artifacts(manifest: dict[str, Any], *, result_dir: Path | str) -> None:
    root = Path(result_dir).resolve()
    for item in _artifact_collection(manifest):
        if (item.get("acquisition") or {}).get("status") != "available":
            continue
        relative = item.get("path")
        if not isinstance(relative, str) or not relative:
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            item["acquisition"] = {"status": "invalid", "reason": "Retained capture path escapes the result directory."}
            continue
        if not candidate.is_file():
            item["acquisition"] = {"status": "unavailable", "reason": f"Retained capture file is missing at finalization: {relative}"}
            continue
        actual_size = candidate.stat().st_size
        actual_sha256 = sha256_file(candidate)
        if actual_size != item.get("size_bytes") or actual_sha256 != item.get("sha256"):
            item["acquisition"] = {"status": "invalid", "reason": "Retained capture size/SHA-256 changed after collection."}
            item["observed_at_finalization"] = {"size_bytes": actual_size, "sha256": actual_sha256}
            continue
        try:
            candidate.chmod(candidate.stat().st_mode & ~0o222)
            item["immutability"] = {"status": "enforced", "method": "read_only_mode"}
        except OSError as exc:
            item["immutability"] = {"status": "logical_only", "method": "sealed_index", "reason": str(exc)}


def evaluate_capture_acceptance(manifest: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    for item in _artifact_collection(manifest):
        if item.get("requirement") != "required":
            continue
        status = (item.get("acquisition") or {}).get("status")
        if status != "available":
            reason = (item.get("acquisition") or {}).get("reason") or f"required capture is {status or 'missing'}"
            reasons.append(f"{item.get('role')}: {reason}")
    for item in manifest.get("retained_files", []):
        if isinstance(item, dict) and item.get("integrity"):
            reasons.append(f"retained file {item.get('path')}: integrity {item.get('integrity')}")
    accepted = not reasons
    contract = manifest.get("capture_contract") or manifest.get("evidence_contract") or {}
    return {
        "status": "accepted" if accepted else "incomplete",
        "accepted": accepted,
        "reasons": reasons,
        "contract_version": contract.get("version"),
        "scope": "capture_integrity_only",
    }


# Compatibility alias.
def evaluate_acceptance(manifest: dict[str, Any]) -> dict[str, Any]:
    return evaluate_capture_acceptance(manifest)


def finalize_manifest(manifest: dict[str, Any], *, finalized_at: str) -> None:
    acceptance = evaluate_capture_acceptance(manifest)
    manifest["capture_acceptance"] = acceptance
    immutable_index = {
        "schema": manifest.get("schema"),
        "configuration": manifest.get("configuration"),
        "contract": manifest.get("capture_contract"),
        "artifacts": _artifact_collection(manifest),
        "retained_files": manifest.get("retained_files", []),
        "execution_outcome": manifest.get("execution_outcome"),
        "capture_acceptance": acceptance,
    }
    manifest["final_index"] = {
        "status": "finalized",
        "finalized_at": finalized_at,
        "sha256": canonical_sha256(immutable_index),
        "scope": "run_capture_only",
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
