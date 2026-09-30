"""A4 offline TLS attribution. Inclusive spans are never a disjoint crypto total."""
from collections import Counter
from dataclasses import replace
from pathlib import Path
from statistics import median
import hashlib

import pandas as pd

from framework.timing_dataset import (verify_source_inputs, inspect_run, read_json,
                                      _artifact, ROLES)
from framework.timing_metrics import decode_epochs, uint, _clock
from framework.tls_instrumentation import (expected_tls_instrumentation_events,
                                           validate_tls_instrumentation_text)
from framework.timing_summary import summarise, digest

VERSION = "1.0.0"
PHASES = set("server_hello encrypted_extensions certificate certificate_verify finished".split())
OPERATIONS = set("p256_keygen p256_shared_secret p384_keygen p384_shared_secret p521_keygen p521_shared_secret x25519_keygen x25519_shared_secret mlkem512_keygen mlkem512_decapsulate mlkem768_keygen mlkem768_decapsulate mlkem1024_keygen mlkem1024_decapsulate rsa_verify rsa_sign ecdsa_verify ecdsa_sign mldsa65_verify mldsa65_sign sha256 sha384 hkdf_extract hkdf_expand x509_verify".split())
SIGNS = {"rsa_sign", "ecdsa_sign", "mldsa65_sign"}
MARKERS = {"PQC_TLS_EVENT", "PQC_TLS_PHASE", "PQC_TLS_PRIMITIVE"}


def kind(name):
    return ("workload" if name == "handshake" else "protocol_phase" if name in PHASES
            else "security_function" if name == "x509_verify" else "cryptographic_operation")


def decode_attribution(records, snapshot, *, blockers=()):
    """Decode one observed iteration, preserving aggregate/invocation identities.

    Missing requirements are asserted only after an explicit successful handshake.
    Failure/unknown outcomes do not prove an unobserved protocol stage was reached.
    """
    expected = set(expected_tls_instrumentation_events(snapshot))
    tls = snapshot.get("effective_non_secret_parameters", {}).get("mqtt", {}).get("tls", {})
    timing = [r for r in records if r["marker"] == "PQC_TLS_HANDSHAKE_TIMING"]
    success = len(timing) == 1 and timing[0]["fields"].get("result") == "1"
    clock_ok = len(timing) == 1 and timing[0]["fields"].get("timebase_available") == "1"
    text = "\n".join(r["marker"] + " " + " ".join(f"{k}={v}" for k,v in r["fields"].items()) for r in records)
    qualification = validate_tls_instrumentation_text(snapshot, text)
    findings = [dict(code=c, source_records=[]) for c in qualification.reasons if c != "required_event_unavailable"]
    statuses = [r for r in records if r["marker"] == "PQC_TLS_EVENT_BUFFER"]
    events = [r for r in records if r["marker"] == "PQC_TLS_EVENT"]
    common = list(blockers)
    handshake = None
    repeat = [r for r in records if r["marker"] == "PQC_TLS_REPEAT_ITERATION"]
    try:
        if len(statuses) == 1:
            status = statuses[0]["fields"]
            if status.get("schema") != "1":
                raise ValueError("unsupported_event_buffer_schema")
            if uint(status.get("iteration")) != statuses[0]["iteration"]:
                raise ValueError("iteration_identity_mismatch")
            handshake = uint(status.get("handshake"))
            if uint(status.get("count")) != len(events) or len(events) > uint(status.get("capacity")):
                raise ValueError("event_buffer_count_mismatch")
            if uint(status.get("dropped")):
                findings.append(dict(code="dropped_events", source_records=[statuses[0]["ref"]]))
        elif statuses:
            raise ValueError("ambiguous_event_buffer")
        repeat = [r for r in records if r["marker"] == "PQC_TLS_REPEAT_ITERATION"]
        if repeat:
            if len(repeat) != 1 or repeat[0]["fields"].get("schema") != "1":
                raise ValueError("ambiguous_or_unsupported_repeat_status")
            f = repeat[0]["fields"]
            if uint(f.get("iteration")) != repeat[0]["iteration"] or (handshake is not None and uint(f.get("handshake")) != handshake):
                raise ValueError("repeat_identity_mismatch")
            if f.get("timing_source") != "TIM2_1MHz":
                raise ValueError("invalid_clock_provenance")
    except ValueError as exc:
        common.append(str(exc))
    if not clock_ok:
        common.append("application_timebase_unavailable")
    clock = dict(clock_source="application_monotonic_us", counter_hz=None,
                 timestamp_origin="application_timebase_start",
                 clock_provenance={"timebase_available": timing[0]["fields"].get("timebase_available") if len(timing) == 1 else None},
                 source_records=[])
    if any(r["marker"] == "PQC_RM2_TIMEBASE" for r in records):
        try:
            _clock(clock, records)
        except (ValueError, TypeError, KeyError) as exc:
            common.append(str(exc) if isinstance(exc, ValueError) else "invalid_clock_provenance")
    elif len(repeat) == 1 and repeat[0]["fields"].get("timing_source") == "TIM2_1MHz":
        clock.update(clock_source="TIM2", counter_hz=1_000_000)
        clock["clock_provenance"]["timing_source"] = "TIM2_1MHz"
    clock_refs = [r["ref"] for r in timing + statuses + repeat] + clock.pop("source_records")
    ordered_errors = [f["code"] for f in findings]
    rows = []
    for record in records:
        marker, f = record["marker"], record["fields"]
        if marker not in MARKERS:
            continue
        name = f.get("name")
        row = dict(operation=name, kind=kind(name), representation="invocation" if marker == "PQC_TLS_EVENT" else "aggregate",
                   sequence=None, parent_sequence=None, depth=None, count=None, value_us=None,
                   start_us=None, end_us=None, min_us=None, max_us=None, result=None,
                   validity="valid", reason=None, source_records=[record["ref"], *clock_refs],
                   handshake_id=handshake, **clock, recorded_fields=dict(f))
        errors = list(common)
        if record["context"] != "tls":
            errors.append("logical_context_mismatch")
        if name not in PHASES | OPERATIONS | {"handshake"}:
            errors.append("unknown_semantic_event")
        try:
            if row["representation"] == "invocation":
                errors.extend(ordered_errors)
                row.update(sequence=uint(f.get("sequence")), parent_sequence=int(f.get("parent_sequence")),
                           depth=uint(f.get("depth")), count=1)
                if f.get("kind") != row["kind"]:
                    errors.append("semantic_kind_mismatch")
                if f.get("completed") != "1":
                    errors.append("incomplete_span")
                if f.get("result_available") == "1":
                    row["result"] = int(f.get("result"))
                row.update(start_us=uint(f.get("start_us")), end_us=uint(f.get("end_us")), value_us=uint(f.get("elapsed_us")))
                if row["end_us"] - row["start_us"] != row["value_us"]:
                    errors.append("span_duration_mismatch")
            else:
                row.update(count=uint(f.get("count")), value_us=uint(f.get("total_us")),
                           min_us=uint(f.get("min_us")), max_us=uint(f.get("max_us")),
                           start_us=uint(f.get("first_start_us")), end_us=uint(f.get("last_end_us")))
                if not row["count"] or not row["min_us"] * row["count"] <= row["value_us"] <= row["max_us"] * row["count"] or row["end_us"] < row["start_us"]:
                    errors.append("invalid_aggregate")
                if marker == "PQC_TLS_PRIMITIVE" and f.get("elapsed_time_source") != "monotonic_us":
                    errors.append("unsupported_aggregate_clock")
                if marker == "PQC_TLS_PHASE" and name not in PHASES or marker == "PQC_TLS_PRIMITIVE" and name not in OPERATIONS:
                    errors.append("semantic_kind_mismatch")
        except (ValueError, TypeError):
            errors.append("malformed_attribution_record")
        row["reason"] = ";".join(sorted(set(errors))) or None
        rows.append(row)
    # Validate nesting independently of the firmware's own status bits.
    invocations = [r for r in rows if r["representation"] == "invocation"]
    by_sequence = {r["sequence"]: r for r in invocations}
    sequence_counts = Counter(r["sequence"] for r in invocations)
    previous = -1
    for row in invocations:
        if row["sequence"] is None or row["sequence"] <= previous or sequence_counts[row["sequence"]] != 1:
            row["reason"] = "invalid_invocation_sequence"
        if row["sequence"] is not None:
            previous = max(previous, row["sequence"])
    for row in invocations:
        parent = by_sequence.get(row["parent_sequence"])
        if row["parent_sequence"] != -1:
            if parent is None or parent["reason"] or (row["sequence"] is None or parent["sequence"] is None or parent["sequence"] >= row["sequence"]) or any(r[k] is None for r in (row, parent) for k in ("start_us", "end_us", "depth")) or not (parent["start_us"] <= row["start_us"] <= row["end_us"] <= parent["end_us"] and row["depth"] == parent["depth"] + 1):
                row["reason"] = (row["reason"] + ";" if row["reason"] else "") + "invalid_parent_span"
        elif row["operation"] != "handshake" or row["depth"] != 0:
            row["reason"] = "invalid_root_span"
    duplicates = Counter((r["representation"], r["operation"]) for r in rows if r["representation"] == "aggregate")
    for row in rows:
        if duplicates[row["representation"], row["operation"]] > 1:
            row["reason"] = "duplicate_aggregate"
        if tls.get("authentication") == "server" and row["operation"] in SIGNS:
            row["reason"] = "unexpected_client_signing_in_server_mode"
        if row["reason"]:
            row.update(validity="unavailable", value_us=None)
            findings.append(dict(code=row["reason"], source_records=row["source_records"]))
    profile_specific = {n for n in OPERATIONS if n.endswith(("keygen", "shared_secret", "decapsulate", "verify", "sign"))} - {"x509_verify"}
    for row in rows:
        if row["operation"] in profile_specific - expected:
            findings.append(dict(code="unexpected_profile_operation:" + row["operation"], source_records=row["source_records"]))
    present = {r["operation"] for r in rows if r["validity"] == "valid"}
    coverage = []
    for name in sorted(expected | SIGNS | {r["operation"] for r in rows if r["operation"]}):
        if name in SIGNS and tls.get("authentication") == "server":
            status, reason = "not_applicable", "server_only_has_no_client_signing"
        elif name in present:
            status, reason = "observed", None
        elif name in expected:
            status, reason = "unavailable", "required_record_missing" if success else "stage_not_established"
        else:
            status, reason = "not_assessed", "not_required_by_selected_profile"
        coverage.append(dict(operation=name, status=status, reason=reason))
        if reason == "required_record_missing":
            findings.append(dict(code=reason + ":" + name, source_records=[]))
    return rows, coverage, findings


def extract_attribution(dataset):
    verify_source_inputs(dataset.metadata)
    observations, coverage, issues, inputs, iteration_rows = [], [], [], [], []
    for run in dataset.runs:
        base = dict(run_key=run["run_key"], run_id=run["run_id"])
        root = Path(run["input_path"])
        current, _, _, consumed = inspect_run(root)
        inputs.extend(consumed)
        if current["run_key"] != run["run_key"]:
            raise ValueError("run_identity_changed")
        if run["selected_input_status"] != "verified" or current["selected_input_status"] != "verified":
            issues.append({**base, "code": "selected_inputs_unavailable", "source_records": []})
            continue
        manifest = read_json((root / "manifest.json").read_bytes())
        raw, _ = _artifact(root, manifest, "stm32_result_stream", inputs)
        snapshot, _ = _artifact(root, manifest, "resolved_case_snapshot", inputs)
        if raw is None or snapshot is None:
            raise ValueError("verified_input_unavailable")
        snapshot = read_json(snapshot)
        epochs, errors = decode_epochs(root / ROLES["stm32_result_stream"], run["run_id"])
        identities = Counter(r["iteration"] for e in epochs for r in e.records if r["marker"] == "PQC_TLS_HANDSHAKE_TIMING")
        for epoch in epochs:
            iterations = sorted({r["iteration"] for r in epoch.records if r["marker"] in MARKERS | {"PQC_TLS_HANDSHAKE_TIMING", "PQC_TLS_REPEAT_ITERATION"}})
            for iteration in iterations:
                context = {**base, "epoch_index": epoch.index, "iteration_id": iteration,
                           "source_sha256": hashlib.sha256(raw).hexdigest(), "logical_sha256": epoch.logical_sha256}
                blockers = errors + epoch.errors
                if identities[iteration] > 1:
                    blockers = blockers + ["duplicate_iteration_identity"]
                if len(iterations) > 1:
                    blockers = blockers + ["multiple_iterations_in_one_reporting_epoch"]
                selected = [r for r in epoch.records if r["iteration"] == iteration]
                repeat = [r for r in selected if r["marker"] == "PQC_TLS_REPEAT_ITERATION"]
                status = repeat[0]["fields"] if len(repeat) == 1 else {}
                iteration_rows.append({**context, "handshake_observed": any(r["marker"] == "PQC_TLS_HANDSHAKE_TIMING" or r["marker"] == "PQC_TLS_EVENT" and r["fields"].get("name") == "handshake" for r in selected), "tls_outcome": status.get("tls_outcome", "unknown"),
                    "tcp_outcome": status.get("tcp_outcome", "unknown"), "failure_stage": status.get("failure_stage"),
                    "recorded_status": dict(status), "event_buffer_status": [r["fields"] for r in selected if r["marker"] == "PQC_TLS_EVENT_BUFFER"], "source_records": [r["ref"] for r in repeat],
                    "status_reason": None if len(repeat) == 1 else "iteration_status_missing_or_ambiguous"})
                rows, cov, found = decode_attribution([r for r in epoch.records if r["iteration"] == iteration], snapshot, blockers=blockers)
                observations.extend({**context, **r} for r in rows)
                coverage.extend({**context, **r} for r in cov)
                issues.extend({**context, **r} for r in found)
    verify_source_inputs(dataset.metadata)
    return observations, coverage, issues, inputs, iteration_rows



def bounded_views(frames, inventory):
    """Identify one TLS treatment axis; retain refused/mixed comparisons explicitly."""
    axes = {"tls_kex": "kex", "tls_auth": "certificate", "auth_mode": "authentication"}
    combined = []
    inventory = inventory.to_dict("records")
    for table in ("tls_run_differences", "tls_operation_differences"):
        rows = frames[table].to_dict("records")
        for row in rows:
            members = [r for r in inventory if r["condition"] in (row["condition"], row["baseline"]) and r["exclusion_reason"] is None]
            values = {axis: {r.get(axis) for r in members} for axis in axes}
            changed = [axis for axis, vals in values.items() if len(vals) > 1]
            reason = None
            if not members or any(None in vals for vals in values.values()):
                reason = "unknown_tls_comparison_dimension"
            elif len(changed) != 1:
                reason = "comparison_requires_one_tls_dimension"
            # An axis must also be fixed within each named condition.
            elif any(len({r.get(axis) for r in members if r["condition"] == label}) != 1
                     for axis in axes for label in (row["condition"], row["baseline"])):
                reason = "mixed_tls_profiles_within_condition"
            row["comparison_dimension"] = axes[changed[0]] if len(changed) == 1 else None
            if reason:
                row.update(delta_median=None, percent_difference=None,
                           reason=";".join(filter(None, (row["reason"], reason))), percent_reason=reason)
            combined.append({**row, "measurement_scope": "handshake" if table == "tls_run_differences" else "operation"})
        frames[table] = pd.DataFrame(rows, columns=[*frames[table].columns, "comparison_dimension"], dtype=object)
    columns = [*frames["tls_operation_differences"].columns, "measurement_scope"]
    for dimension in axes.values():
        frames["tls_"+dimension+"_comparisons"] = pd.DataFrame(
            [row for row in combined if row["comparison_dimension"] == dimension], columns=columns, dtype=object)


def summarise_tls(dataset, spec):
    observations, coverage, issues, inputs, iterations = extract_attribution(dataset)
    handshakes = [dict(t) for t in dataset.timings if t["metric"] == "tls_handshake"]
    # Attribute-only iterations remain visible even without an outer timing record.
    known = {(t["run_key"], t["epoch_index"], t["iteration_id"]) for t in handshakes}
    by_run = {r["run_key"]: r for r in dataset.runs}
    for iteration in iterations:
        identity = tuple(iteration[k] for k in ("run_key", "epoch_index", "iteration_id"))
        if identity not in known:
            handshakes.append({**iteration, "metric": "tls_handshake", "value_us": None,
                "operation_outcome": "unknown", "validity": "unavailable", "reason": "outer_timing_missing"})
    for timing in handshakes:
        if by_run[timing["run_key"]]["application"] == "tls_handshake_repeat":
            statuses = [i for i in iterations if all(i[k] == timing[k] for k in ("run_key", "epoch_index", "iteration_id"))]
            if len(statuses) != 1 or statuses[0]["tls_outcome"] not in ("success", "failed"):
                timing.update(operation_outcome="unknown", validity="unavailable", value_us=None,
                              reason="iteration_outcome_unknown")
    summaries, derived = [], []
    for run in dataset.runs:
        rows = [t for t in handshakes if t["run_key"] == run["run_key"] and t["epoch_index"] is not None]
        values = [t["value_us"] for t in rows if t["validity"] == "valid" and t["operation_outcome"] == "success"]
        observed = {(i["epoch_index"], i["iteration_id"]) for i in iterations
                    if i["run_key"] == run["run_key"] and i["handshake_observed"]}
        handshake_rows = [t for t in rows if (t["epoch_index"], t["iteration_id"]) in observed]
        counts = Counter(t["operation_outcome"] for t in handshake_rows)
        iteration_counts = Counter(t["operation_outcome"] for t in rows)
        summaries.append(dict(run_key=run["run_key"], run_id=run["run_id"], observed_iterations=len(rows), observed_handshakes=len(handshake_rows),
            successful_iterations=iteration_counts["success"], failed_iterations=iteration_counts["failed"],
            unknown_iterations=len(rows)-iteration_counts["success"]-iteration_counts["failed"],
            successful_handshakes=counts["success"], failed_handshakes=counts["failed"],
            unknown_handshakes=len(handshake_rows)-counts["success"]-counts["failed"], valid_handshakes=len(values),
            within_run_median_us=median(values) if values else None,
            estimand="within-run median of valid successful observed handshakes"))
        derived.append(dict(run_key=run["run_key"], run_id=run["run_id"], metric="tls_handshake",
            value_us=median(values) if values else None, validity="valid" if values else "unavailable",
            reason=None if values else "no_valid_successful_handshakes", epoch_index=None, iteration_id=None,
            timing_policy_exclusion=run["timing_policy_exclusion"], source_records=[t["source_records"] for t in rows]))
    repeated_frames, _ = summarise(replace(dataset, timings=tuple(derived)), spec, metrics={"tls_handshake": {"unit": "us"}})
    frames = {"tls_"+name: pd.DataFrame(rows, dtype=object) for name, rows in
              dict(attribution=observations, coverage=coverage, issues=issues, iterations=iterations, handshakes=handshakes, per_run=summaries).items()}
    for name in ("distributions", "differences", "completeness", "observations"):
        frame = repeated_frames[name]
        frame["estimand"] = "across-run median of within-run successful-handshake medians"
        frames["tls_run_"+name] = frame
    # Compare each operation/representation independently. Never combine levels or
    # combine aggregate and invocation evidence for the same operation.
    op_samples, definitions = [], {}
    operation_groups = {}
    for row in observations:
        key = (row["run_key"], row["representation"], row["operation"])
        operation_groups.setdefault(key, {}).setdefault(
            (row["epoch_index"], row["iteration_id"]), []).append(row)
    valid_handshakes = {(row["run_key"], row["epoch_index"], row["iteration_id"])
                        for row in handshakes if row["validity"] == "valid"}
    for representation, operation in sorted({(r["representation"], r["operation"]) for r in observations if r["operation"]}):
        for measure, unit in (("elapsed", "us"), ("count", "count")):
            metric = representation + ":" + operation + ":" + measure
            definitions[metric] = {"unit": unit}
            for run in dataset.runs:
                groups = operation_groups.get((run["run_key"], representation, operation), {})
                values = []
                refs = []
                for identity, rows in groups.items():
                    successful = (run["run_key"], *identity) in valid_handshakes
                    if not successful or any(r["validity"] != "valid" for r in rows):
                        continue
                    ordered = sorted(rows, key=lambda r: r["start_us"])
                    if representation == "invocation" and any(a["end_us"] > b["start_us"] for a,b in zip(ordered, ordered[1:])):
                        issues.append(dict(run_key=run["run_key"], code="overlapping_same_operation_spans", source_records=[r["source_records"] for r in rows]))
                        continue
                    values.append(sum(r["value_us"] if measure == "elapsed" else r["count"] for r in rows))
                    refs.extend(r["source_records"] for r in rows)
                op_samples.append(dict(run_key=run["run_key"], run_id=run["run_id"], metric=metric,
                    value_us=median(values) if values else None, validity="valid" if values else "unavailable",
                    reason=None if values else "no_eligible_operation_measurements", epoch_index=None, iteration_id=None,
                    timing_policy_exclusion=run["timing_policy_exclusion"], source_records=refs))
    op_frames, _ = summarise(replace(dataset, timings=tuple(op_samples)), spec, metrics=definitions)
    for name in ("distributions", "differences", "observations"):
        op_frames[name]["estimand"] = "across-run median of within-run per-handshake operation totals; inclusive elapsed"
        frames["tls_operation_"+name] = op_frames[name]
    bounded_views(frames, repeated_frames["inventory"])
    frames["tls_issues"] = pd.DataFrame(issues, dtype=object)
    # Even wholly unavailable channels produce readable CSV headers.
    for name, columns in {
        "tls_attribution": ["run_key", "run_id", "epoch_index", "iteration_id", "operation", "representation", "sequence", "parent_sequence", "count", "value_us", "validity", "reason", "source_records"],
        "tls_coverage": ["run_key", "run_id", "epoch_index", "iteration_id", "operation", "status", "reason"],
        "tls_issues": ["run_key", "run_id", "code", "source_records"],
        "tls_iterations": ["run_key", "run_id", "epoch_index", "iteration_id", "tls_outcome", "tcp_outcome", "failure_stage", "status_reason"],
        "tls_operation_distributions": ["condition", "metric", "unit", "median", "n_runs", "estimand"],
    }.items():
        if frames[name].empty:
            frames[name] = pd.DataFrame(columns=columns, dtype=object)
    return frames, dict(schema="pqc-tls-attribution", version=VERSION, inputs=inputs,
        source_sha256={p.name: digest(p) for p in (Path(__file__), Path(__file__).with_name("timing_metrics.py"), Path(__file__).with_name("tls_instrumentation.py"))},
        definitions={"elapsed": "recorded monotonic microseconds in RTOS; inclusive, not isolated CPU time",
                     "count": "recorded aggregate count or observed completed invocation count",
                     "pooled": "A2 observation distributions are descriptive; A4 inference uses one median per run",
                     "coverage": "requirements asserted only after explicit handshake success; failures retain unknown stage",
                     "prohibited": "no Total Crypto sum, exclusive cost or inferred network delay"})
