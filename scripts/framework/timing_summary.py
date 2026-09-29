"""A2 offline descriptive summaries and deliberately bounded inference.

Consumes only the validated A1 loader; no raw-evidence parsing or execution.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import platform
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from framework.timing_dataset_loader import load_dataset
from framework.timing_dataset_schema import METRICS, RUN_COLUMNS, TIMING_COLUMNS, ISSUE_COLUMNS

VERSION = "1.0.0"
CORE_CONTROLS = ("target", "gateway", "workload", "application", "network_condition",
                 "tls_kex", "tls_auth", "auth_mode", "secure_boot", "firmware_mode",
                 "payload_bytes", "chunk_bytes", "boot_stack_profiling", "boot_uart_diagnostics",
                 "source_commit", "capture_class", "evidence_class")
# These describe measured application of a condition, not a matched configured control.
OBSERVED_CONTROLS = {"controls.network_verified_applied", "controls.network_observed"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def field(run, key):
    value = run
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def leaves(value, prefix="controls"):
    if isinstance(value, dict) and value:
        return {p for key, item in value.items() for p in leaves(item, prefix + "." + key)}
    return {prefix}


def validate_spec(spec, dataset):
    allowed = {"conditions", "baseline", "filters", "controls", "treatment", "not_applicable",
               "exclude_runs", "percentiles", "seed", "resamples", "confidence", "independent_runs"}
    if set(spec) - allowed:
        raise ValueError("unknown analysis specification keys")
    conditions = spec.get("conditions", {})
    if not conditions or spec.get("baseline") not in conditions:
        raise ValueError("provide named conditions and an explicit named baseline")
    known = set(RUN_COLUMNS) | set(CORE_CONTROLS)
    for run in dataset.runs:
        known |= leaves(run.get("controls", {}))
    paths = set(spec.get("controls", [])) | set(spec.get("treatment", [])) | set(spec.get("not_applicable", {}))
    for selector in [spec.get("filters", {}), *conditions.values()]:
        if not isinstance(selector, dict):
            raise ValueError("selectors must be field/value objects")
        paths |= set(selector)
    if paths - known:
        raise ValueError("unknown field paths: " + ", ".join(sorted(paths - known)))
    if not all(isinstance(v, str) and v.strip() for v in spec.get("not_applicable", {}).values()):
        raise ValueError("not-applicable controls require reasons")
    if set(spec.get("treatment", [])) & {"capture_class", "evidence_class", "source_commit"}:
        raise ValueError("capture/evidence class and source revision cannot be treatment fields")
    if set(spec.get("not_applicable", {})) & {"capture_class", "target", "workload"}:
        raise ValueError("capture class, target and workload are required controls")
    exclusions = spec.get("exclude_runs", {})
    if set(exclusions) - {r["run_key"] for r in dataset.runs} or not all(isinstance(v, str) and v.strip() for v in exclusions.values()):
        raise ValueError("exclusions require known run keys and explicit reasons")
    if type(spec.get("independent_runs", False)) is not bool:
        raise ValueError("independent_runs must be boolean")
    if not 0 < spec.get("confidence", .95) < 1:
        raise ValueError("confidence must be between zero and one")
    if type(spec.get("resamples", 2000)) is not int or not 100 <= spec.get("resamples", 2000) <= 100000:
        raise ValueError("resamples must be 100..100000")
    if type(spec.get("seed", 20260928)) is not int or spec.get("seed", 20260928) < 0:
        raise ValueError("seed must be a nonnegative integer")
    if any(not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 100 for p in spec.get("percentiles", [90, 95])):
        raise ValueError("percentiles must be finite and within 0..100")


def matches(run, selector):
    return all(field(run, k) is not None and field(run, k) == v for k, v in selector.items())


def wilson(successes, total, confidence=.95):
    """Two-sided Wilson score interval for independent known binary outcomes."""
    if total < 2:
        return None, None
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = successes / total
    denom = 1 + z*z/total
    center = (p + z*z/(2*total))/denom
    half = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total))/denom
    return max(0., center-half), min(1., center+half)


def bootstrap_median(values, *, seed=20260928, resamples=2000, confidence=.95):
    """Percentile bootstrap of the median, sampling independent runs equally."""
    rng = np.random.default_rng(seed)
    values = np.asarray(values, dtype=float)
    # Bounded memory regardless of number of selected runs.
    draws = [float(np.median(rng.choice(values, size=len(values), replace=True))) for _ in range(resamples)]
    alpha = (1-confidence)/2
    return tuple(float(x) for x in np.quantile(draws, [alpha, 1-alpha], method="linear"))


def independence_reason(runs, spec):
    if not spec.get("independent_runs", False):
        return "independence_not_declared"
    if any(r.get("retry_of_run_id") or (r.get("attempt_index") or 0) > 1 for r in runs):
        return "linked_or_retried_attempts"
    return None


def summarise(dataset, spec, *, metrics=None):
    """Return export-ready frames. Failed/unknown/filter-excluded runs stay visible."""
    metrics = METRICS if metrics is None else metrics
    validate_spec(spec, dataset)
    spec = {"filters": {}, "controls": [], "treatment": [], "not_applicable": {},
            "exclude_runs": {}, "percentiles": [90, 95], "seed": 20260928,
            "resamples": 2000, "confidence": .95, "independent_runs": False, **spec}
    inventory, samples, completeness, distributions, differences = [], [], [], [], []
    groups = {}
    timings = {}
    for observation in dataset.timings:
        timings.setdefault(observation["run_key"], []).append(observation)
    for run in dataset.runs:
        labels = [label for label, selector in spec["conditions"].items() if matches(run, selector)]
        if len(labels) > 1:
            raise ValueError("overlapping conditions for run " + run["run_key"])
        reason = spec["exclude_runs"].get(run["run_key"])
        if not matches(run, spec["filters"]):
            reason = reason or "filter_mismatch_or_unknown"
        if not labels:
            reason = reason or "outside_named_conditions"
        label = labels[0] if labels else None
        inventory.append({**run, "condition": label, "exclusion_reason": reason})
        if label:
            group = (label, run.get("capture_class"), run.get("evidence_class"))
            groups.setdefault(group, []).append((run, reason))
        for obs in timings.get(run["run_key"], []):
            exclusion = reason or obs.get("timing_policy_exclusion")
            if run.get("selected_input_status") != "verified":
                exclusion = exclusion or "selected_inputs_not_valid"
            if run["execution_outcome"] != "completed":
                exclusion = exclusion or "not_successful_execution"
            if obs["validity"] != "valid":
                exclusion = exclusion or obs["reason"] or "measurement_unavailable"
            samples.append({**obs, "condition": label, "capture_class": run.get("capture_class"),
                            "evidence_class": run.get("evidence_class"), "exclusion_reason": exclusion})
    for group, members in sorted(groups.items(), key=lambda x: str(x[0])):
        label, capture, evidence = group
        base = dict(condition=label, capture_class=capture, evidence_class=evidence)
        included = [r for r, reason in members if reason is None]
        completed = sum(r["execution_outcome"] == "completed" for r in included)
        failed = sum(r["execution_outcome"] == "failed" for r in included)
        unknown = len(included)-completed-failed
        inference = independence_reason(included, spec)
        if completed + failed < 2:
            inference = inference or "fewer_than_two_known_outcomes"
        lo, hi = (None, None) if inference else wilson(completed, completed+failed, spec["confidence"])
        for metric in metrics:
            selected = [s for s in samples if (s["condition"], s["capture_class"], s["evidence_class"]) == group and s["metric"] == metric]
            usable = [s for s in selected if not s["exclusion_reason"]]
            contributing = {s["run_key"] for s in usable}
            completeness.append({**base, "metric": metric, "inventory_runs": len(members),
                "excluded_runs": len(members)-len(included), "included_runs": len(included),
                "completed_runs": completed, "failed_runs": failed, "unknown_runs": unknown,
                "known_outcome_denominator": completed+failed,
                "completion_fraction": completed/(completed+failed) if completed+failed else None,
                "completion_ci_low": lo, "completion_ci_high": hi, "completion_ci_reason": inference,
                "capture_accepted_runs": sum(r.get("capture_acceptance") == "accepted" for r in included),
                "valid_observations": sum(s["validity"] == "valid" for s in selected),
                "unavailable_observations": sum(s["validity"] != "valid" for s in selected),
                "contributing_runs": len(contributing), "contributing_observations": len(usable),
                "contributing_iterations": len({(s["run_key"], s["epoch_index"], s["iteration_id"]) for s in usable if s["iteration_id"] is not None}),
                "runs_without_usable_metric": len(included)-len(contributing)})
            values = [s["value_us"] for s in usable]
            stats = {**base, "metric": metric, "unit": metrics[metric]["unit"], "n_runs": len(contributing), "n_observations": len(values)}
            q1, median, q3 = (None, None, None) if not values else (float(v) for v in np.quantile(values, [.25, .5, .75], method="linear"))
            stats.update(q1=q1, median=median, q3=q3, iqr=q3-q1 if values else None)
            for p in spec["percentiles"]:
                stats[f"p{p:g}"] = float(np.percentile(values, p, method="linear")) if values else None
            reason = independence_reason(included, spec)
            # Even unavailable repeated observations prohibit treating remaining samples as independent.
            counts = [sum(s["run_key"] == r["run_key"] for s in selected) for r in included]
            if any(n > 1 for n in counts):
                reason = reason or "repeated_intra_run_observations_descriptive_only"
            if len(values) < 2:
                reason = reason or "fewer_than_two_contributing_runs"
            low, high = (None, None) if reason else bootstrap_median(values, seed=spec["seed"], resamples=spec["resamples"], confidence=spec["confidence"])
            stats.update(median_ci_low=low, median_ci_high=high, median_ci_reason=reason)
            distributions.append(stats)
    # A condition must describe one fixed set of controls, not a mixture hidden by its label.
    by_label = {label: [r for (name, _, _), members in groups.items() if name == label for r, reason in members if reason is None]
                for label in spec["conditions"]}
    baseline = spec["baseline"]
    for label, runs in by_label.items():
        if label == baseline:
            continue
        reference = by_label[baseline]
        controls = set(CORE_CONTROLS) | set(spec["controls"])
        for run in reference + runs:
            controls |= leaves(run.get("controls", {}))
        controls -= OBSERVED_CONTROLS | set(spec["treatment"]) | set(spec["not_applicable"])
        problems = []
        if not runs or not reference:
            problems.append("empty_condition_or_baseline")
        for key in sorted(controls):
            values = [field(r, key) for r in reference + runs]
            if any(v is None or v == {} or v == "" for v in values):
                problems.append("unknown_control:" + key)
            elif len({json.dumps(v, sort_keys=True) for v in values}) > 1:
                problems.append("conflicting_control:" + key)
        for metric in metrics:
            rows = [r for r in distributions if r["metric"] == metric]
            a = [r for r in rows if r["condition"] == baseline]
            b = [r for r in rows if r["condition"] == label]
            reason = ";".join(problems) or None
            if len(a) != 1 or len(b) != 1:
                reason = reason or "mixed_or_missing_capture_evidence_class"
            elif a[0]["median"] is None or b[0]["median"] is None:
                reason = reason or "no_successful_latency_samples"
            delta = None if reason else b[0]["median"]-a[0]["median"]
            percent = None if reason or a[0]["median"] == 0 else 100*delta/a[0]["median"]
            differences.append(dict(condition=label, baseline=baseline, metric=metric, unit=metrics[metric]["unit"], delta_median=delta,
                percent_difference=percent, reason=reason, percent_reason=reason or ("zero_baseline" if a[0]["median"] == 0 else None),
                baseline_runs=a[0]["n_runs"] if len(a)==1 else 0, treatment_runs=b[0]["n_runs"] if len(b)==1 else 0))
    # Object dtype prevents nullable integer identities/timestamps being coerced to floats.
    frames = {name: pd.DataFrame(rows, dtype=object) for name, rows in dict(inventory=inventory, observations=samples,
              completeness=completeness, distributions=distributions, differences=differences).items()}
    if frames["differences"].empty:
        frames["differences"] = pd.DataFrame(columns=["condition", "baseline", "metric", "unit", "delta_median",
            "percent_difference", "reason", "percent_reason", "baseline_runs", "treatment_runs"])
    if frames["observations"].empty:
        frames["observations"] = pd.DataFrame(columns=[*TIMING_COLUMNS, "condition", "capture_class", "evidence_class", "exclusion_reason"])
    frames["issues"] = pd.DataFrame(dataset.issues, columns=list(ISSUE_COLUMNS), dtype=object)
    return frames, spec


def export_summary(dataset_path, spec, output, *, resources=False, tls=False, network=None, energy=None):
    """New output directory only; record direct inputs, selections and output hashes."""
    dataset_path, output = Path(dataset_path).resolve(), Path(output).resolve()
    dataset = load_dataset(dataset_path)
    forbidden = [dataset_path, *[Path(r["input_path"]).resolve() for r in dataset.runs if r.get("input_path")]]
    if any(output == p or output in p.parents or p in output.parents for p in forbidden):
        raise ValueError("summary output must be separate from dataset and raw runs")
    frames, spec = summarise(dataset, spec)
    resource_provenance = None
    if resources:
        from framework.resource_analysis import summarise_resources
        resource_frames, resource_provenance = summarise_resources(dataset, spec)
        frames.update(resource_frames)
        for source in resource_provenance["inputs"]:
            parent = Path(source["path"]).resolve().parent
            if output == parent or parent in output.parents or output in parent.parents:
                raise ValueError("summary output overlaps resource evidence")
    tls_provenance = None
    if tls:
        from framework.tls_analysis import summarise_tls
        tls_frames, tls_provenance = summarise_tls(dataset, spec)
        frames.update(tls_frames)
    network_provenance = None
    if network is not None:
        from framework.network_analysis import summarise_network
        network_frames, network_provenance = summarise_network(dataset, spec, network)
        frames.update(network_frames)
    energy_provenance = None
    if energy is not None:
        from framework.energy_analysis import summarise_energy
        energy_frames, energy_provenance = summarise_energy(dataset, spec, energy)
        frames.update(energy_frames)
    output.mkdir(parents=True, exist_ok=False)
    for name, frame in frames.items():
        exported = frame.copy()
        for col in exported:
            exported[col] = pd.Series([json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else ("\\" + v if isinstance(v, str) and v.startswith("\\") else v)
                                       for v in exported[col]], dtype=object)
        exported.to_csv(output / (name + ".csv"), index=False, na_rep=r"\N")
    plot_summary(frames, spec, output)
    if network is not None:
        from framework.network_analysis import plot_network
        plot_network(frames, output)
    if energy is not None:
        from framework.energy_analysis import plot_energy
        plot_energy(frames, output)
    lineage = dict(schema="pqc-timing-summary", version=VERSION, specification=spec,
        estimands={"latency": "success-conditional observation median; repeated samples descriptive only",
                   "completion": "completed / (completed + failed); unknown and explicit exclusions reported separately",
                   "median_ci": "run-level percentile bootstrap; linear quantiles",
                   "completion_ci": "Wilson score; independent known binary run outcomes"},
        dataset_metadata=dataset.metadata,
        counts={"inventory_runs": len(dataset.runs), "observations": len(dataset.timings), "issues": len(dataset.issues)},
        null_encoding={"token": r"\N", "string_escape": "leading backslash doubled"},
        columns={name: list(frame.columns) for name, frame in frames.items()},
        inputs={name: digest(dataset_path / name) for name in ("dataset.json", "dataset.sha256", "runs.csv", "timings.csv", "issues.csv")},
        sources={p.name: digest(p) for p in (Path(__file__), Path(__file__).with_name("timing_dataset_loader.py"),
                 Path(__file__).with_name("timing_dataset_schema.py"))},
        environment={"python": platform.python_version(), **{p: importlib.metadata.version(p) for p in ("numpy", "pandas", "matplotlib", "nbclient", "nbformat")}},
        outputs={p.name: digest(p) for p in sorted(output.iterdir())})
    if energy_provenance is not None:
        lineage["energy"] = energy_provenance
    if network_provenance is not None:
        lineage['network'] = network_provenance
    if tls_provenance is not None:
        lineage["tls"] = tls_provenance
    if resource_provenance is not None:
        lineage["resources"] = resource_provenance
    (output / "summary.json").write_text(json.dumps(lineage, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return frames


def plot_summary(frames, spec, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(4, 2, figsize=(13, 15), constrained_layout=True)
    samples = frames["observations"].to_dict("records")
    for metric, ax in zip(METRICS, axes.flat):
        groups = {}
        for sample in samples:
            if sample["metric"] == metric and not sample["exclusion_reason"]:
                label = f'{sample["condition"]}\n{sample["capture_class"]}/{sample["evidence_class"]}'
                groups.setdefault(label, []).append(sample)
        for i, (label, rows) in enumerate(sorted(groups.items())):
            ax.scatter([i]*len(rows), [s["value_us"] for s in rows], alpha=.6)
        ax.set_xticks(range(len(groups)), [f'{k}\nruns={len({s["run_key"] for s in v})}, obs={len(v)}' for k,v in sorted(groups.items())], fontsize=7)
        ax.set_title(metric + " (success conditional)"); ax.set_ylabel("µs")
        if not groups: ax.text(.5, .5, "No eligible measurements", ha="center", transform=ax.transAxes)
    fig.savefig(output / "timing-distributions.png", dpi=140); plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 6), constrained_layout=True)
    rows = [r for r in frames["differences"].to_dict("records") if r["reason"] is None]
    if rows:
        ax.barh(range(len(rows)), [r["delta_median"] for r in rows])
        ax.set_yticks(range(len(rows)), [f'{r["condition"]}: {r["metric"]} (n={r["treatment_runs"]}/{r["baseline_runs"]})' for r in rows])
    else:
        ax.text(.5, .5, "No supported matched differences; see differences.csv", ha="center", transform=ax.transAxes)
    ax.set_title("Median difference from baseline: " + spec["baseline"]); ax.set_xlabel("Difference (µs)")
    ax.axvline(0, color="black", linewidth=.5)
    fig.savefig(output / "matched-differences.png", dpi=140); plt.close(fig)
