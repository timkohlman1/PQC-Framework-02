"""Typed CSV loading and an unfiltered notebook-ready timing pivot for A1.

All timestamps/values remain Python integers, including those beyond 2**53.
A2 can construct pandas DataFrames from these typed rows without reparsing evidence.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.analysis_paths import result_path
from framework.run_evidence import sha256_file
from framework.timing_dataset import DatasetError, read_json, verify_source_inputs
from framework.timing_dataset_schema import METRICS, NULL, SCHEMA_NAME, SCHEMA_VERSION, TABLES


def _decode(value: str, dtype: str) -> Any:
    if value == NULL:
        return None
    if dtype == "integer":
        if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value):
            raise DatasetError("invalid integer CSV cell")
        return int(value)
    if dtype == "boolean":
        if value not in ("true", "false"):
            raise DatasetError("invalid boolean CSV cell")
        return value == "true"
    if dtype == "json":
        try:
            return json.loads(value, parse_constant=lambda token: (_ for _ in ()).throw(DatasetError("non-finite JSON cell")))
        except ValueError as exc:
            raise DatasetError("invalid JSON CSV cell") from exc
    if value.startswith("\\\\"):
        return value[1:]
    if value.startswith("\\"):
        raise DatasetError("unescaped leading backslash")
    return value


def _read_table(path: Path, columns: dict[str, str]) -> tuple[dict[str, Any], ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(columns):
            raise DatasetError("CSV column schema mismatch: " + path.name)
        rows = []
        for raw in reader:
            if None in raw or any(raw[key] is None for key in columns):
                raise DatasetError("CSV row width mismatch: " + path.name)
            rows.append({key: _decode(raw[key], dtype) for key, dtype in columns.items()})
        return tuple(rows)


@dataclass(frozen=True)
class TimingDataset:
    """Schema-validated values; identifiers are strings and nulls are None."""
    runs: tuple[dict[str, Any], ...]
    timings: tuple[dict[str, Any], ...]
    issues: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]

    def timing_view(self) -> list[dict[str, Any]]:
        """One row per run/transport-epoch/recorded iteration, including failures.

        No averaging, dropping, eligibility inference, or synthetic iterations.
        Column ``<metric>_reason`` accompanies every nullable ``<metric>_us``.
        Runs without observations have one availability row with null identities.
        """
        view: dict[tuple, dict] = {}
        by_run = {row["run_key"]: row for row in self.runs}

        def base(run: dict, epoch: int | None, iteration: int | None) -> dict:
            result = {key: run[key] for key in (
                "run_key", "run_id", "workload", "tls_kex", "tls_auth", "auth_mode",
                "network_condition", "repetition_index", "execution_outcome", "capture_acceptance",
                "capture_class", "evidence_class",
                "selected_input_status", "timing_policy_exclusion", "configuration_identity", "firmware_sha256")}
            result.update(epoch_index=epoch, iteration_id=iteration, handshake_id=None,
                          comparison_inclusion="not_assessed")
            for metric in METRICS:
                result[metric + "_us"] = None
                result[metric + "_reason"] = "not_recorded_or_not_applicable"
                result[metric + "_policy_exclusion"] = None
            return result

        for timing in self.timings:
            key = (timing["run_key"], timing["epoch_index"], timing["iteration_id"])
            row = view.setdefault(key, base(by_run[key[0]], key[1], key[2]))
            row[timing["metric"] + "_us"] = timing["value_us"]
            row[timing["metric"] + "_reason"] = timing["reason"]
            row[timing["metric"] + "_policy_exclusion"] = timing["timing_policy_exclusion"]
            if timing["metric"] == "tls_handshake":
                row["handshake_id"] = timing["handshake_id"]
        represented = {key[0] for key in view}
        for run in self.runs:
            if run["run_key"] not in represented:
                view[(run["run_key"], None, None)] = base(run, None, None)
        return [view[key] for key in sorted(view, key=lambda item: (item[0], -1 if item[1] is None else item[1], -1 if item[2] is None else item[2]))]


def load_dataset(directory: Path | str, *, verify_inputs: bool = False) -> TimingDataset:
    """Verify metadata/CSV hashes, schema/types/joins and optionally original inputs."""
    root = result_path(directory)
    try:
        for name in ("dataset.json", "dataset.sha256", "runs.csv", "timings.csv", "issues.csv"):
            if (root / name).is_symlink():
                raise DatasetError("dataset symlinks are unsupported")
        seal = (root / "dataset.sha256").read_text(encoding="ascii")
        if seal != sha256_file(root / "dataset.json") + "  dataset.json\n":
            raise DatasetError("dataset metadata hash mismatch")
        meta = read_json((root / "dataset.json").read_bytes())
        if meta.get("schema") != {"name": SCHEMA_NAME, "version": SCHEMA_VERSION}:
            raise DatasetError("unsupported dataset schema")
        if (meta.get("tables") != TABLES or meta.get("null_encoding", {}).get("token") != NULL
                or meta.get("metric_definitions") != METRICS):
            raise DatasetError("unsupported dataset column/null contract")
        tables = {}
        for name, columns in TABLES.items():
            output = meta["outputs"][name]
            filename = name + ".csv"
            path = root / filename
            if (output.get("path") != filename or output.get("sha256") != sha256_file(path)
                    or output.get("size_bytes") != path.stat().st_size):
                raise DatasetError("dataset table hash/size mismatch: " + filename)
            tables[name] = _read_table(path, columns)
            if len(tables[name]) != meta["counts"][name]:
                raise DatasetError("dataset row count mismatch")
        runs = {row["run_key"]: row for row in tables["runs"]}
        if None in runs or len(runs) != len(tables["runs"]):
            raise DatasetError("duplicate/missing run key")
        seen = set()
        seen_ids = set()
        for row in tables["timings"]:
            key = (row["run_key"], row["epoch_index"], row["iteration_id"], row["metric"])
            if key in seen or row["observation_id"] in seen_ids or row["observation_id"] is None:
                raise DatasetError("duplicate/missing observation identity")
            seen.add(key); seen_ids.add(row["observation_id"])
            if row["run_key"] not in runs or row["run_id"] != runs[row["run_key"]]["run_id"]:
                raise DatasetError("observation run identity mismatch")
            if row["metric"] not in METRICS or row["unit"] != "us" or row["metric_version"] != "1":
                raise DatasetError("unsupported metric contract")
            if row["validity"] == "valid":
                if type(row["value_us"]) is not int or row["value_us"] < 0 or row["reason"] is not None:
                    raise DatasetError("valid observation has invalid value/reason")
                if not row["source_records"] or not row["source_sha256"]:
                    raise DatasetError("valid observation lacks source evidence")
                if (type(row["start_us"]) is not int or type(row["end_us"]) is not int
                        or row["end_us"] - row["start_us"] != row["value_us"]):
                    raise DatasetError("observation formula mismatch")
            elif row["validity"] != "unavailable" or row["value_us"] is not None or not row["reason"]:
                raise DatasetError("unavailable observation must have null value and reason")
        if sum(row["validity"] == "valid" for row in tables["timings"]) != meta["counts"]["valid_timings"]:
            raise DatasetError("valid timing count mismatch")
        for issue in tables["issues"]:
            if issue["run_key"] not in runs:
                raise DatasetError("issue has unknown run key")
        if verify_inputs:
            verify_source_inputs(meta)
        return TimingDataset(tables["runs"], tables["timings"], tables["issues"], meta)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        if isinstance(exc, DatasetError):
            raise
        raise DatasetError("dataset unreadable or malformed") from exc
