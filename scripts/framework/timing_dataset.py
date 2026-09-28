"""Offline A1 run inventory/export. Raw files and their permission bits are read-only.

The capture API's mutating finalize/freeze helpers must never be called here.
Dataset lineage uses its existing non-mutating derived-record helper instead.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from framework.run_evidence import (build_derived_record, canonical_sha256,
    evaluate_capture_acceptance, sha256_file, validate_manifest_schema)
from framework.timing_dataset_schema import (ISSUE_COLUMNS, METRICS, NULL, PARSER_VERSION,
    RUN_COLUMNS, SCHEMA_NAME, SCHEMA_VERSION, SUPPORTED_INPUTS, TABLES)
from framework.timing_metrics import decode_epochs, extract_timings

ROLES = {"resolved_case_snapshot": "resolved-case.json", "run_provenance": "run-provenance.json",
         "stm32_result_stream": "mqtt-reporting-raw.ndjson"}
# Discovery never sweeps keys, build/preparation material or earlier derivatives.
PRUNED = {"analysis", "preparations", "prerequisites", "cryptographic-material", "builds",
          "secrets", ".git", ".venv", "__pycache__", ".pqc-generated-state"}


class DatasetError(ValueError):
    """Invalid dataset selection or integrity failure."""


def _reject_constant(value: str) -> None:
    raise DatasetError("non-finite JSON constant")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DatasetError("duplicate JSON object key")
        result[key] = value
    return result


def read_json(data: bytes | str) -> dict:
    value = json.loads(data, object_pairs_hook=_unique_keys, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise DatasetError("JSON root must be an object")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _map(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else None


def _int(value: Any) -> int | None:
    return value if type(value) is int else None


def _bool(value: Any) -> bool | None:
    return value if type(value) is bool else None


def _has_symlink(path: Path) -> bool:
    return any(part.is_symlink() for part in (path, *path.parents))


def _absolute(path: Path | str) -> Path:
    # Unlike resolve(), abspath preserves symlinks for the explicit refusal check.
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def discover_inputs(*, run_dirs: Iterable[Path | str] = (), results_root: Path | str | None = None) -> tuple[list[Path], dict]:
    requested = [_absolute(p) for p in run_dirs]
    if bool(requested) == (results_root is not None):
        raise DatasetError("select explicit --run-dir inputs OR one --results-root")
    selection: dict[str, Any] = {"mode": "explicit_runs", "requested": sorted(str(p) for p in requested)}
    if results_root is not None:
        root = _absolute(results_root)
        if _has_symlink(root) or not root.is_dir():
            raise DatasetError("results root must be an existing non-symlink directory")
        selection = {"mode": "results_root", "root": str(root), "pruned_directory_names": sorted(PRUNED),
                     "excluded_non_run_manifests": []}
        for current, directories, filenames in os.walk(root, followlinks=False):
            base = Path(current)
            directories[:] = sorted(name for name in directories if name not in PRUNED and not (base / name).is_symlink())
            if "manifest.json" not in filenames:
                continue
            manifest = base / "manifest.json"
            candidate = (base / "resolved-case.json").exists()
            if not candidate:
                try:
                    data = read_json(manifest.read_bytes())
                    candidate = bool(_map(data.get("run"))) or _map(data.get("schema")).get("name") == "pqc-run-evidence"
                except (OSError, ValueError, UnicodeError):
                    candidate = True  # unreadable candidates remain visible
            if candidate:
                requested.append(base)
                directories[:] = []  # no nested incidental manifests inside a run
            else:
                selection["excluded_non_run_manifests"].append(str(manifest))
    unique = sorted(set(requested), key=str)
    selection["discovered_inputs"] = [str(p) for p in unique]
    selection["repeated_path_count"] = len(requested) - len(unique)
    if not unique:
        raise DatasetError("no run inputs discovered; no dataset was written")
    return unique, selection


def _new_issue(row: dict, code: str, *, detail: str, artifact: str | None = None,
               metric: dict | None = None, severity: str = "warning") -> dict:
    result = dict.fromkeys(ISSUE_COLUMNS)
    result.update(run_key=row["run_key"], run_id=row["run_id"], severity=severity, code=code,
                  artifact=artifact, detail=detail, source_records=[])
    if metric:
        result.update(metric=metric["metric"], epoch_index=metric["epoch_index"],
                      iteration_id=metric["iteration_id"], source_records=metric["source_records"])
    result["issue_id"] = canonical_sha256({k: v for k, v in result.items() if k != "issue_id"})
    return result


def _verify_header(manifest: dict) -> None:
    ok, reason = validate_manifest_schema(manifest)
    if not ok:
        raise DatasetError(reason or "unsupported_manifest_schema")
    for key in ("run", "configuration", "capture_contract", "execution_outcome", "capture_acceptance", "final_index"):
        if not isinstance(manifest.get(key), dict):
            raise DatasetError("malformed_manifest_" + key)
    if not isinstance(manifest.get("artifacts"), list) or not isinstance(manifest.get("retained_files"), list):
        raise DatasetError("malformed_artifact_inventory")
    for item in manifest["artifacts"]:
        if not isinstance(item, dict) or not isinstance(item.get("acquisition"), dict):
            raise DatasetError("malformed_artifact_record")
    if any(not isinstance(item, dict) for item in manifest["retained_files"]):
        raise DatasetError("malformed_retained_file_record")
    if not isinstance(manifest["run"].get("id"), str) or not manifest["run"]["id"]:
        raise DatasetError("run_identity_missing")
    if manifest["capture_contract"].get("version") != 2:
        raise DatasetError("unsupported_capture_contract")
    if manifest["final_index"].get("status") != "finalized":
        raise DatasetError("manifest_not_finalized")
    index = {"schema": manifest["schema"], "configuration": manifest["configuration"],
             "contract": manifest["capture_contract"], "artifacts": manifest["artifacts"],
             "retained_files": manifest["retained_files"], "execution_outcome": manifest["execution_outcome"],
             "capture_acceptance": manifest["capture_acceptance"]}
    if canonical_sha256(index) != manifest["final_index"].get("sha256"):
        raise DatasetError("capture_index_hash_mismatch")
    evaluated = evaluate_capture_acceptance(manifest)
    for key in ("status", "accepted", "reasons", "contract_version", "scope"):
        if evaluated.get(key) != manifest["capture_acceptance"].get(key):
            raise DatasetError("capture_acceptance_conflict")


def _artifact(root: Path, manifest: dict, role: str, inputs: list[dict]) -> tuple[bytes | None, str]:
    expected_name = ROLES[role]
    record = {"role": role, "path": str(root / expected_name), "consumed": False,
              "sha256": None, "size_bytes": None, "expected_sha256": None, "status": "unavailable"}
    inputs.append(record)
    items = [item for item in manifest["artifacts"] if item.get("role") == role]
    if len(items) != 1:
        record["status"] = "artifact_role_missing_or_ambiguous"
        return None, record["status"]
    item = items[0]
    record["expected_sha256"] = item.get("sha256")
    if item["acquisition"].get("status") != "available":
        record["status"] = "not_acquired"
        return None, record["status"]
    # Current verified format uses fixed run-relative names. Never follow a role
    # redirected into secret material, a different run, or the analysis namespace.
    if item.get("path") != expected_name or _has_symlink(root / expected_name):
        record["status"] = "unsafe_or_unsupported_artifact_path"
        return None, record["status"]
    try:
        content = (root / expected_name).read_bytes()
    except OSError:
        record["status"] = "file_unavailable"
        return None, record["status"]
    record.update(consumed=True, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content))
    if record["sha256"] != item.get("sha256") or len(content) != item.get("size_bytes"):
        record["status"] = "artifact_hash_or_size_mismatch"
        return None, record["status"]
    for retained in manifest["retained_files"]:
        if retained.get("path") == expected_name and (retained.get("sha256") != record["sha256"]
                or retained.get("size_bytes") != len(content)):
            record["status"] = "conflicting_artifact_identity"
            return None, record["status"]
    # Multiple semantic roles may legitimately reference the same physical file.
    for other in manifest["artifacts"]:
        if other.get("path") == expected_name and (other.get("sha256") != record["sha256"]
                or other.get("size_bytes") != len(content)):
            record["status"] = "conflicting_artifact_identity"
            return None, record["status"]
    record["status"] = "verified"
    return content, "verified"


def _inventory_fields(row: dict, manifest: dict, snapshot: dict, provenance: dict) -> list[str]:
    config = manifest["configuration"]
    historical = _map(snapshot.get("configuration"))
    selected, choices = _map(historical.get("selected_profiles")), _map(historical.get("choices"))
    effective = _map(snapshot.get("effective_non_secret_parameters"))
    records = _map(provenance.get("records"))
    firmware = _map(effective.get("firmware"))
    mqtt, network = _map(effective.get("mqtt")), _map(effective.get("network"))
    tls = _map(mqtt.get("tls"))
    campaign = _map(config.get("campaign_execution"))
    prep = _map(records.get("preparation"))
    build = _map(records.get("build_reference"))
    mismatches: list[str] = []
    for key in ("configuration_identity", "firmware_identity"):
        row[key] = _text(config.get(key))
        if historical.get(key) is not None and config.get(key) != historical[key]:
            mismatches.append(key + "_mismatch")
    firmware_hashes = {value for value in (
        _map(records.get("firmware")).get("sha256"), prep.get("firmware_sha256"), campaign.get("firmware_sha256")
    ) if isinstance(value, str) and value}
    if len(firmware_hashes) > 1:
        mismatches.append("firmware_hash_mismatch")
    row.update(firmware_sha256=next(iter(firmware_hashes)) if len(firmware_hashes) == 1 else None,
        build_number=_text(records.get("build_number") if records.get("build_number") is not None else build.get("build_number")),
        source_commit=_text(_map(records.get("source")).get("commit")),
        preparation_run_id=_text(prep.get("run_id") or campaign.get("preparation_run_id")),
        preparation_verified=_bool(prep.get("verified")),
        campaign_id=_text(campaign.get("campaign_id")), case_id=_text(campaign.get("case_id") or effective.get("experiment_id")),
        condition_identity=_text(campaign.get("condition_identity")), repetition_index=_int(campaign.get("repetition_index")),
        attempt_index=_int(config.get("attempt_index")), retry_of_run_id=_text(config.get("retry_of_run_id")),
        workload=_text(selected.get("workload")), application=_text(firmware.get("application")),
        target=_text(selected.get("target")), gateway=_text(selected.get("gateway")),
        network_condition=_text(choices.get("network_condition")), tls_kex=_text(tls.get("key_exchange_group")),
        tls_auth=_text(tls.get("certificate_profile")), auth_mode=_text(tls.get("authentication")),
        secure_boot=_text(choices.get("secure_boot")), firmware_mode=_text(choices.get("firmware_mode")),
        evidence_class=_text(mqtt.get("evidence_class")),
        payload_bytes=_int(_map(mqtt.get("transfer")).get("payload_bytes")),
        chunk_bytes=_int(_map(mqtt.get("transfer")).get("chunk_bytes")),
        boot_stack_profiling=_bool(choices.get("boot_stack_profiling")),
        boot_uart_diagnostics=_bool(choices.get("boot_uart_diagnostics")))
    if choices.get("tls_kex") is not None and tls.get("key_exchange_group") != choices["tls_kex"]:
        mismatches.append("tls_selection_mismatch")
    if choices.get("auth_mode") is not None and tls.get("authentication") != choices["auth_mode"]:
        mismatches.append("authentication_selection_mismatch")
    exclusions = [key for key in ("boot_stack_profiling", "boot_uart_diagnostics") if row[key] is True]
    row["timing_policy_exclusion"] = ";".join(exclusions) or None
    # Explicit allowlists: no payloads, host addresses, secret references, key-log
    # contents, private material or whole configuration/provenance copies exported.
    row["controls"] = {
        "firmware": {key: firmware.get(key) for key in ("application", "firmware_mode", "dual_bank_enabled", "ota_enabled", "standby_signing_keys", "uart_output_mode", "uart_log_level")},
        "choices": {key: choices.get(key) for key in ("secure_boot", "boot_stack_profiling", "boot_uart_diagnostics", "standby_signing_keys")},
        "tls": {key: tls.get(key) for key in ("mode", "tls_version", "authentication", "certificate_profile", "key_exchange_group", "server_signature_algorithm")},
        "network_configured": {key: _map(network.get("degradation")).get(key) for key in ("enabled", "rate_kbit", "rtt_ms", "loss_percent", "mtu")},
        "network_verified_applied": None, "network_observed": None,
        "mqtt": {"qos": mqtt.get("qos"), "reconnect_attempts": mqtt.get("reconnect_attempts")},
        "profile_hashes": {key: value for key, value in _map(historical.get("profile_hashes")).items()
                           if isinstance(key, str) and isinstance(value, str) and len(value) == 64},
        "selected_profiles": {key: selected.get(key) for key in ("target", "gateway", "workload")},
        "services": {key: _map(selected.get("services")).get(key) for key in ("experiment_broker", "reporting_broker")},
    }
    row["build_references"] = {
        "preparation_manifest": _text(prep.get("manifest")), "preparation_verified": _bool(prep.get("verified")),
        "build_manifest": _text(build.get("manifest")),
        "image_identities": [{"role": item.get("role"), "sha256": item.get("sha256")}
                             for item in manifest["artifacts"] if item.get("role") in ("application_elf", "signed_application", "wolfboot_image")],
    }
    row["inventory_reasons"] = [key + "_not_recorded" for key in (
        "build_number", "source_commit", "attempt_index", "retry_of_run_id") if row[key] is None]
    return mismatches


def inspect_run(root: Path) -> tuple[dict, list[dict], list[dict], list[dict]]:
    row = dict.fromkeys(RUN_COLUMNS)
    row.update(run_key=canonical_sha256({"unreadable_input": str(root)}), input_path=str(root), input_paths=[str(root)],
        manifest_status="unavailable", execution_outcome="unknown", capture_acceptance="unknown",
        selected_input_status="unavailable", controls={}, build_references={}, iteration_ids=[],
        capture_reasons=[], inventory_reasons=[])
    timings, issues, inputs = [], [], []
    try:
        if _has_symlink(root) or _has_symlink(root / "manifest.json"):
            raise DatasetError("symlink_input_refused")
        content = (root / "manifest.json").read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        row["manifest_sha256"] = digest
        inputs.append({"role": "manifest", "path": str(root / "manifest.json"), "consumed": True,
                       "sha256": digest, "size_bytes": len(content), "status": "read"})
        manifest = read_json(content)
        row["run_id"] = _text(_map(manifest.get("run")).get("id"))
        row["run_key"] = canonical_sha256({"run_id": row["run_id"], "manifest_sha256": digest})
        _verify_header(manifest)
        row.update(manifest_status="verified", capture_index_sha256=manifest["final_index"]["sha256"],
            execution_outcome=_text(manifest["execution_outcome"].get("status")) or "unknown",
            execution_result=_text(manifest["execution_outcome"].get("result")),
            failure_stage=_text(manifest["execution_outcome"].get("failure_stage")),
            return_code=_int(manifest["run"].get("return_code")),
            capture_acceptance=manifest["capture_acceptance"]["status"],
            capture_reasons=manifest["capture_acceptance"]["reasons"],
            capture_class=_text(manifest["capture_contract"].get("experiment_class")))
        snapshots: dict[str, dict] = {}
        blockers: list[str] = []
        for role, schema_key in (("resolved_case_snapshot", "resolved_case"), ("run_provenance", "provenance")):
            data, state = _artifact(root, manifest, role, inputs)
            if data is None:
                blockers.append(role + ":" + state)
                snapshots[role] = {}
                continue
            try:
                parsed = read_json(data)
                if parsed.get("schema") != SUPPORTED_INPUTS[schema_key] or type(_map(parsed.get("schema")).get("version")) is not int:
                    raise DatasetError("unsupported_snapshot_schema")
                snapshots[role] = parsed
            except (ValueError, UnicodeError):
                blockers.append(role + ":invalid_or_unsupported_snapshot")
                snapshots[role] = {}
        snapshot = snapshots["resolved_case_snapshot"]
        blockers.extend(_inventory_fields(row, manifest, snapshot, snapshots["run_provenance"]))
        raw, state = _artifact(root, manifest, "stm32_result_stream", inputs)
        epochs, decode_errors = [], []
        if raw is None:
            blockers.append("stm32_result_stream:" + state)
        elif not blockers:
            try:
                epochs, decode_errors = decode_epochs(root / ROLES["stm32_result_stream"], row["run_id"])
            except (OSError, UnicodeError, ValueError, TypeError):
                decode_errors = ["reporting_stream_decode_failed"]
        row["selected_input_status"] = "verified" if not blockers else "unavailable_or_invalid"
        timings = extract_timings(epochs, snapshot, global_errors=blockers + decode_errors)
        row["observed_stream_count"] = len(epochs) if raw is not None and not blockers else None
        ids = sorted({t["iteration_id"] for t in timings if t["iteration_id"] is not None})
        row.update(iteration_ids=ids, observed_iteration_count=len(ids) if row["observed_stream_count"] is not None else None)
        for code in blockers + decode_errors:
            issues.append(_new_issue(row, "input_unavailable_or_invalid", detail=code, severity="error"))
        for epoch in epochs:
            for code in epoch.errors:
                issues.append(_new_issue(row, "reporting_epoch_invalid", detail=f"epoch={epoch.index}: {code}", severity="error"))
        if row["execution_outcome"] not in ("completed", "not_applicable"):
            issues.append(_new_issue(row, "execution_not_completed", detail="Recorded outcome retained; no failure stage inferred.", severity="info"))
        if row["capture_acceptance"] != "accepted":
            issues.append(_new_issue(row, "capture_not_accepted", detail="Recorded capture decision retained independently of metric validity."))
        if row["timing_policy_exclusion"]:
            issues.append(_new_issue(row, "timing_policy_exclusion", detail=row["timing_policy_exclusion"]))
        if row["preparation_verified"] is False:
            issues.append(_new_issue(row, "preparation_not_verified", detail="Retained preparation.verified=false; no build/deployment revalidation performed."))
    except (OSError, ValueError, UnicodeError, TypeError, KeyError, AttributeError) as exc:
        # Do not include file content/JSON error excerpts in exported diagnostics.
        reason = str(exc) if isinstance(exc, DatasetError) else "manifest_unreadable_or_malformed"
        row["manifest_status"] = "unavailable_or_invalid"
        row["inventory_reasons"] = [reason]
        issues.append(_new_issue(row, "manifest_unavailable_or_invalid", detail=reason, artifact="manifest.json", severity="error"))
    raw_hash = next((item["sha256"] for item in inputs if item["role"] == "stm32_result_stream"), None)
    for index, timing in enumerate(timings):
        timing.update(run_key=row["run_key"], run_id=row["run_id"], source_sha256=raw_hash,
                      observation_id=canonical_sha256({"run_key": row["run_key"], "metric": timing["metric"],
                          "epoch": timing["epoch_index"], "iteration": timing["iteration_id"], "ordinal": index}))
        exclusions = []
        if row["boot_stack_profiling"] is True:
            exclusions.append("boot_stack_profiling")
        if row["boot_uart_diagnostics"] is True and timing["metric"] in ("rtfb", "rtlb"):
            exclusions.append("boot_uart_diagnostics_reset_relative")
        timing["timing_policy_exclusion"] = ";".join(exclusions) or None
        if timing["reason"]:
            issues.append(_new_issue(row, "metric_unavailable", detail=timing["reason"], metric=timing))
    return row, timings, issues, inputs


def encode_cell(value: Any, dtype: str) -> str:
    if value is None:
        return NULL
    if dtype == "json":
        return _json(value)
    if dtype == "boolean":
        if type(value) is not bool:
            raise DatasetError("non-boolean cell")
        return "true" if value else "false"
    if dtype == "integer":
        if type(value) is not int:
            raise DatasetError("non-integer cell")
        return str(value)
    if not isinstance(value, str):
        raise DatasetError("non-string cell")
    return "\\" + value if value.startswith("\\") else value


def _write_csv(path: Path, rows: list[dict], columns: dict) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: encode_cell(row.get(key), dtype) for key, dtype in columns.items()})


def verify_source_inputs(metadata: dict) -> None:
    """Recheck the exact consumed bytes, not today's directory discovery or YAML."""
    for source in metadata["inputs"]:
        for item in source["artifacts"]:
            if not item.get("consumed"):
                continue
            path = Path(item["path"])
            if (_has_symlink(path) or not path.is_file() or path.stat().st_size != item["size_bytes"]
                    or sha256_file(path) != item["sha256"]):
                raise DatasetError("consumed input changed: " + str(path))


def export_dataset(*, output: Path | str, run_dirs: Iterable[Path | str] = (),
                   results_root: Path | str | None = None) -> dict:
    destinations, selection = discover_inputs(run_dirs=run_dirs, results_root=results_root)
    output = _absolute(output)
    if _has_symlink(output) or output.exists():
        raise DatasetError("output must be a new non-symlink directory; existing datasets are never overwritten")
    for run in destinations:
        if output == run or output.is_relative_to(run) or run.is_relative_to(output):
            raise DatasetError("dataset destination overlaps a selected raw run")
    if results_root is not None and (_absolute(results_root) == output or _absolute(results_root).is_relative_to(output)):
        raise DatasetError("dataset destination overlaps the selected results root")
    runs, timings, issues, sources = [], [], [], []
    by_key: dict[str, dict] = {}
    for directory in destinations:
        row, observed, diagnostics, inputs = inspect_run(directory)
        sources.append({"input_path": str(directory), "run_key": row["run_key"], "artifacts": inputs})
        if row["run_key"] in by_key:
            canonical = by_key[row["run_key"]]
            canonical["input_paths"].append(str(directory))
            issues.extend(diagnostics)
            issues.append(_new_issue(canonical, "duplicate_capture_copy", detail="Identical manifest at an additional selected path; observations not duplicated.", severity="info"))
            if row["selected_input_status"] != canonical["selected_input_status"]:
                canonical["selected_input_status"] = "duplicate_copy_evidence_conflict"
                issues.append(_new_issue(canonical, "duplicate_copy_evidence_conflict", detail="Selected copies of one capture have different required-input availability/integrity.", severity="error"))
                for timing in timings:
                    if timing["run_key"] == canonical["run_key"]:
                        timing.update(value_us=None, validity="unavailable", reason="duplicate_copy_evidence_conflict")
            continue
        by_key[row["run_key"]] = row
        runs.append(row); timings.extend(observed); issues.extend(diagnostics)
    id_to_keys: dict[str, set[str]] = {}
    for row in runs:
        if row["run_id"]:
            id_to_keys.setdefault(row["run_id"], set()).add(row["run_key"])
    for row in runs:
        if row["run_id"] and len(id_to_keys[row["run_id"]]) > 1:
            issues.append(_new_issue(row, "run_id_reused_across_captures", detail="Run IDs are allocated per results root. Distinct capture hashes remain separate; join on run_key, never run_id alone.", severity="warning"))
    runs.sort(key=lambda row: row["run_key"])
    timings.sort(key=lambda row: (row["run_key"], row["epoch_index"] if row["epoch_index"] is not None else -1,
                                 row["iteration_id"] if row["iteration_id"] is not None else -1, row["metric"]))
    issues = sorted({issue["issue_id"]: issue for issue in issues}.values(), key=lambda issue: issue["issue_id"])
    source_files = [Path(__file__), Path(__file__).with_name("timing_metrics.py"),
                    Path(__file__).with_name("timing_dataset_schema.py"), Path(__file__).with_name("timing_dataset_loader.py"),
                    Path(__file__).parents[1] / "export_timing_dataset.py", Path(__file__).with_name("run_evidence.py"),
                    Path(__file__).with_name("result_collector.py"), Path(__file__).with_name("energy_evidence.py"),
                    Path(__file__).with_name("tls_instrumentation.py")]
    metadata = {
        "schema": {"name": SCHEMA_NAME, "version": SCHEMA_VERSION},
        "parser": {"name": "framework.timing_dataset", "version": PARSER_VERSION,
                   "source_hashes": {path.name: sha256_file(path) for path in source_files}},
        "environment": {"python": platform.python_version(), "implementation": sys.implementation.name},
        "selection": selection, "inputs": sources, "supported_inputs": SUPPORTED_INPUTS,
        "metric_definitions": METRICS, "tables": TABLES,
        "null_encoding": {"token": NULL, "string_escape": "double a leading backslash", "missing": "never converted to zero"},
        "parameters": {"comparison_inclusion": "not_assessed", "capture_recheck": "selected_inputs_only",
            "unrelated_artifacts": "not consumed or revalidated; recorded capture acceptance is not a fresh full-capture check",
            "no_inferred_iterations": True, "outlier_removal": False},
        "determinism": "CSV/metadata bytes are stable for the same selected paths, bytes, parser and Python version. Relocation, alias selection and environment changes are declared provenance differences.",
        "counts": {"runs": len(runs), "timings": len(timings), "issues": len(issues),
                   "valid_timings": sum(t["validity"] == "valid" for t in timings)},
    }
    metadata["dataset_id"] = canonical_sha256({"selection": selection, "inputs": sources, "parser": metadata["parser"], "schema": metadata["schema"]})
    verify_source_inputs(metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".timing-dataset-", dir=output.parent))
    try:
        direct_hashes = sorted({artifact["sha256"] for source in sources for artifact in source["artifacts"] if artifact.get("sha256")})
        # Even an all-unreadable input set has explicit selection provenance.
        lineage_hashes = direct_hashes or [canonical_sha256(selection)]
        metadata["lineage_input_kind"] = "file_hashes" if direct_hashes else "selection_hash_only_no_readable_inputs"
        metadata["outputs"] = {}
        for name, rows in (("runs", runs), ("timings", timings), ("issues", issues)):
            path = staging / (name + ".csv")
            _write_csv(path, rows, TABLES[name])
            metadata["outputs"][name] = build_derived_record(result_dir=staging, role=name, path=path,
                tool="framework.timing_dataset", version=PARSER_VERSION, input_sha256=lineage_hashes,
                parameters={"dataset_schema": SCHEMA_VERSION, "metric_version": "1", "dataset_id": metadata["dataset_id"]})
        (staging / "dataset.json").write_text(json.dumps(metadata, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        (staging / "dataset.sha256").write_text(sha256_file(staging / "dataset.json") + "  dataset.json\n", encoding="ascii")
        verify_source_inputs(metadata)
        if output.exists():
            raise DatasetError("output appeared during export; refusing to overwrite")
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return metadata
