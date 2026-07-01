"""Secure-boot benchmark aggregation helpers.

The aggregation helpers are intentionally read-only. They inspect existing
secure-boot benchmark manifests and write cross-profile summary outputs without
building firmware, flashing hardware, opening UART devices, using SSH, or
requiring STM32 hardware.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SUMMARY_SCHEMA_VERSION = 1
SUMMARY_MODEL_PHASE = "phase_11_6_benchmark_aggregation_output"

CSV_FIELDNAMES = [
    "profile_id",
    "signing_algorithm",
    "curve_or_key_size",
    "sample_count",
    "valid_sample_count",
    "failed_sample_count",
    "median_verification_time_ms",
    "mean_verification_time_ms",
    "minimum_verification_time_ms",
    "maximum_verification_time_ms",
    "verification_time_standard_deviation_ms",
    "median_verification_cycles",
    "mean_verification_cycles",
    "minimum_verification_cycles",
    "maximum_verification_cycles",
    "verification_cycles_standard_deviation",
    "cycles_per_kb",
    "time_ms_per_kb",
    "bootloader_flash_size_bytes",
    "static_ram_size_bytes",
    "maximum_stack_usage_bytes",
    "signed_image_size_bytes",
    "signature_size_bytes",
    "size_overhead_bytes",
    "size_overhead_percentage",
    "final_profile_verdict",
    "limitations",
    "source_manifest",
]


class BenchmarkAggregationError(Exception):
    """Raised when benchmark aggregation input or output handling fails."""


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return None
    return None


def _as_int(value: Any) -> int | None:
    number = _as_number(value)
    if number is None:
        return None
    return int(number)


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _nested(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _listify(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item) != ""]
    return [str(value)]


def _extend_limitations(limitations: list[str], value: Any) -> None:
    for item in _listify(value):
        if item not in limitations:
            limitations.append(item)


def _normalise_verdict(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    lowered = text.lower()
    if "passed" in lowered:
        return "passed"
    if "failed" in lowered or "refused" in lowered:
        return "failed"
    return text


def _manifest_candidate(path: Path) -> Path:
    return path / "manifest.json" if path.is_dir() else path


def read_manifest(path: Path | str) -> dict[str, Any]:
    """Read a JSON manifest file."""

    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BenchmarkAggregationError(f"manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkAggregationError(f"invalid JSON manifest: {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BenchmarkAggregationError(f"manifest is not a JSON object: {manifest_path}")
    return data


def discover_benchmark_manifests(results_dir: Path | str) -> list[Path]:
    """Discover top-level result manifests containing secure-boot benchmark evidence."""

    root = Path(results_dir)
    if not root.exists():
        raise BenchmarkAggregationError(f"results directory not found: {root}")
    if not root.is_dir():
        raise BenchmarkAggregationError(f"results path is not a directory: {root}")

    manifests: list[Path] = []
    for candidate in sorted(root.glob("*/manifest.json")):
        try:
            data = read_manifest(candidate)
        except BenchmarkAggregationError:
            continue
        if isinstance(data.get("secure_boot_benchmark"), dict):
            manifests.append(candidate)
    return manifests


def resolve_manifest_inputs(
    *,
    results_dir: Path | str,
    manifest_paths: Iterable[Path | str] | None = None,
    run_dirs: Iterable[Path | str] | None = None,
) -> list[Path]:
    """Resolve explicit manifest/run-directory inputs or discover benchmark manifests."""

    resolved: list[Path] = []
    for path in manifest_paths or []:
        resolved.append(_manifest_candidate(Path(path)))
    for path in run_dirs or []:
        resolved.append(_manifest_candidate(Path(path)))

    if not resolved:
        resolved = discover_benchmark_manifests(results_dir)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in resolved:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def build_benchmark_summary_row(manifest: dict[str, Any], *, source_manifest: Path | str) -> dict[str, Any]:
    """Build one flat Phase 11.6 summary row from a secure-boot run manifest."""

    benchmark = manifest.get("secure_boot_benchmark")
    if not isinstance(benchmark, dict):
        raise BenchmarkAggregationError(f"manifest does not contain secure_boot_benchmark: {source_manifest}")

    profile_metadata = benchmark.get("classical_profile_metadata")
    if not isinstance(profile_metadata, dict):
        profile_metadata = {}

    aggregate = benchmark.get("aggregate_statistics")
    if not isinstance(aggregate, dict):
        aggregate = {}
    time_stats = aggregate.get("verification_time_ms")
    if not isinstance(time_stats, dict):
        time_stats = {}
    cycle_stats = aggregate.get("verification_cycles")
    if not isinstance(cycle_stats, dict):
        cycle_stats = {}
    derived = aggregate.get("derived_metrics")
    if not isinstance(derived, dict):
        derived = {}

    build_metrics = benchmark.get("build_time_metrics")
    if not isinstance(build_metrics, dict):
        build_metrics = {}
    signed_metrics = benchmark.get("signed_artifact_metrics")
    if not isinstance(signed_metrics, dict):
        signed_metrics = {}
    runtime_memory = benchmark.get("runtime_memory_metrics")
    if not isinstance(runtime_memory, dict):
        runtime_memory = {}

    profile_id = _first_non_empty(
        profile_metadata.get("profile_id"),
        profile_metadata.get("id"),
        benchmark.get("profile_id"),
        _nested(manifest, "experiment", "id"),
        manifest.get("run_id"),
    )
    signing_algorithm = _first_non_empty(
        profile_metadata.get("algorithm"),
        profile_metadata.get("signature_algorithm"),
        benchmark.get("signature_algorithm"),
        manifest.get("boot_crypto"),
    )

    curve = profile_metadata.get("curve")
    key_size_bits = _as_int(profile_metadata.get("key_size_bits"))
    if curve and key_size_bits:
        curve_or_key_size = f"{curve} / {key_size_bits} bits"
    elif curve:
        curve_or_key_size = curve
    elif key_size_bits:
        curve_or_key_size = f"{key_size_bits} bits"
    else:
        curve_or_key_size = None

    sample_count = _as_int(aggregate.get("sample_count"))
    valid_sample_count = _as_int(aggregate.get("valid_sample_count"))
    failed_sample_count = _as_int(aggregate.get("failed_sample_count"))

    signed_image_size = _as_int(signed_metrics.get("signed_application_size_bytes"))
    median_cycles = _as_number(time_stats.get("median"))
    median_verification_cycles = _as_number(cycle_stats.get("median"))
    cycles_per_kb = _as_number(derived.get("cycles_per_kb"))
    time_ms_per_kb = _as_number(derived.get("time_ms_per_kb"))
    if signed_image_size and signed_image_size > 0:
        image_kb = signed_image_size / 1024
        if cycles_per_kb is None and median_verification_cycles is not None:
            cycles_per_kb = median_verification_cycles / image_kb
        if time_ms_per_kb is None and median_cycles is not None:
            time_ms_per_kb = median_cycles / image_kb

    limitations: list[str] = []
    _extend_limitations(limitations, benchmark.get("limitations"))
    _extend_limitations(limitations, aggregate.get("limitations"))
    _extend_limitations(limitations, build_metrics.get("limitations"))
    _extend_limitations(limitations, signed_metrics.get("limitations"))
    _extend_limitations(limitations, runtime_memory.get("runtime_memory_limitations"))
    _extend_limitations(limitations, profile_metadata.get("scope_limitations"))

    final_verdict = _normalise_verdict(_first_non_empty(manifest.get("result"), aggregate.get("status")))

    return {
        "profile_id": profile_id,
        "signing_algorithm": signing_algorithm,
        "curve_or_key_size": curve_or_key_size,
        "sample_count": sample_count,
        "valid_sample_count": valid_sample_count,
        "failed_sample_count": failed_sample_count,
        "median_verification_time_ms": _as_number(time_stats.get("median")),
        "mean_verification_time_ms": _as_number(time_stats.get("mean")),
        "minimum_verification_time_ms": _as_number(time_stats.get("minimum")),
        "maximum_verification_time_ms": _as_number(time_stats.get("maximum")),
        "verification_time_standard_deviation_ms": _as_number(time_stats.get("standard_deviation")),
        "median_verification_cycles": median_verification_cycles,
        "mean_verification_cycles": _as_number(cycle_stats.get("mean")),
        "minimum_verification_cycles": _as_number(cycle_stats.get("minimum")),
        "maximum_verification_cycles": _as_number(cycle_stats.get("maximum")),
        "verification_cycles_standard_deviation": _as_number(cycle_stats.get("standard_deviation")),
        "cycles_per_kb": cycles_per_kb,
        "time_ms_per_kb": time_ms_per_kb,
        "bootloader_flash_size_bytes": _as_int(build_metrics.get("bootloader_flash_bytes")),
        "static_ram_size_bytes": _as_int(_first_non_empty(build_metrics.get("static_ram_bytes"), build_metrics.get("bootloader_static_ram_bytes"))),
        "maximum_stack_usage_bytes": _as_int(runtime_memory.get("max_stack_used_bytes")),
        "signed_image_size_bytes": signed_image_size,
        "signature_size_bytes": _as_int(_first_non_empty(signed_metrics.get("signature_size_bytes"), benchmark.get("signature_size_bytes"), manifest.get("signature_size"))),
        "size_overhead_bytes": _as_int(signed_metrics.get("signed_image_overhead_bytes")),
        "size_overhead_percentage": _as_number(signed_metrics.get("signed_image_overhead_percent")),
        "final_profile_verdict": final_verdict,
        "limitations": limitations,
        "source_manifest": str(source_manifest),
        "run_id": manifest.get("run_id"),
        "timestamp": manifest.get("timestamp"),
    }


def aggregate_benchmark_manifests(manifest_paths: Iterable[Path | str]) -> dict[str, Any]:
    """Aggregate secure-boot benchmark manifest paths into a JSON summary object."""

    paths = [Path(path) for path in manifest_paths]
    rows = []
    skipped = []
    for path in paths:
        try:
            manifest = read_manifest(path)
            rows.append(build_benchmark_summary_row(manifest, source_manifest=path))
        except BenchmarkAggregationError as exc:
            skipped.append({"path": str(path), "reason": str(exc)})

    rows.sort(key=lambda row: (str(row.get("signing_algorithm") or ""), str(row.get("profile_id") or ""), str(row.get("source_manifest") or "")))
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "model_phase": SUMMARY_MODEL_PHASE,
        "generated_at": _now_timestamp(),
        "benchmark_scope": "secure_boot_classical_signing_algorithm",
        "input_manifest_count": len(paths),
        "aggregated_profile_count": len(rows),
        "skipped_manifest_count": len(skipped),
        "skipped_manifests": skipped,
        "profiles": rows,
    }


def _csv_value(value: Any) -> Any:
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    return value


def write_benchmark_summary_outputs(summary: dict[str, Any], output_dir: Path | str) -> dict[str, str]:
    """Write benchmark_summary.json and benchmark_summary.csv."""

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    json_path = output_path / "benchmark_summary.json"
    csv_path = output_path / "benchmark_summary.csv"

    profiles = summary.get("profiles")
    if not isinstance(profiles, list):
        raise BenchmarkAggregationError("summary profiles field must be a list")

    json_summary = dict(summary)
    json_summary["output_files"] = {
        "json": str(json_path),
        "csv": str(csv_path),
    }
    json_path.write_text(json.dumps(json_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in profiles:
            writer.writerow({field: _csv_value(row.get(field)) for field in CSV_FIELDNAMES})

    return {
        "json": str(json_path),
        "csv": str(csv_path),
    }
