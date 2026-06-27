"""Result manifest helpers for experiment runs.

This module creates deterministic result-directory metadata without building
firmware, flashing hardware, opening UART devices, using SSH, or touching
network resources.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

RUN_ID_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<sequence>\d{3})_(?P<experiment>[A-Za-z0-9_.-]+)$")
DEFAULT_RESULT_STATUS = "pending"
DEFAULT_TRANSPORT_MODE = "direct_uart"
DEFAULT_NETWORK_PROFILE = "none"


def _coerce_timestamp(timestamp: datetime | None) -> datetime:
    """Return a timestamp, using local time when one is not supplied."""

    if timestamp is None:
        return datetime.now().astimezone()
    return timestamp


def format_manifest_timestamp(timestamp: datetime | None = None) -> str:
    """Format a manifest timestamp as ISO 8601 text."""

    return _coerce_timestamp(timestamp).isoformat(timespec="seconds")


def _safe_run_id_component(value: str) -> str:
    """Convert a value into a conservative run-id component."""

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    safe = safe.strip("_.-")

    if not safe:
        raise ValueError("run ID component must contain at least one safe character")

    return safe


def next_run_id(
    experiment_id: str,
    results_root: Path | str = "results",
    timestamp: datetime | None = None,
) -> str:
    """Generate the next run ID for a results root.

    The format is:

        YYYY-MM-DD_NNN_experiment_id

    The numeric sequence is allocated per date across all existing result
    directories under ``results_root``.
    """

    current_timestamp = _coerce_timestamp(timestamp)
    run_date = current_timestamp.date().isoformat()
    safe_experiment_id = _safe_run_id_component(experiment_id)
    root = Path(results_root)

    highest_sequence = 0

    if root.exists():
        for child in root.iterdir():
            if not child.is_dir():
                continue

            match = RUN_ID_PATTERN.match(child.name)
            if match is None or match.group("date") != run_date:
                continue

            highest_sequence = max(highest_sequence, int(match.group("sequence")))

    return f"{run_date}_{highest_sequence + 1:03d}_{safe_experiment_id}"


def build_manifest(
    bundle: dict[str, dict[str, Any]],
    run_id: str,
    timestamp: datetime | None = None,
    result: str = DEFAULT_RESULT_STATUS,
) -> dict[str, Any]:
    """Build the initial manifest dictionary for an experiment bundle."""

    experiment = bundle["experiment"]
    board = bundle["board"]
    host = bundle["host"]
    boot = bundle.get("boot", {})

    firmware = experiment.get("firmware", {})
    transport = experiment.get("transport", {})
    network = experiment.get("network", {})

    return {
        "run_id": run_id,
        "timestamp": format_manifest_timestamp(timestamp),
        "experiment": experiment["id"],
        "board": board["id"],
        "gateway": host["id"],
        "boot_mode": boot.get("mode", firmware.get("mode", "unknown")),
        "transport_mode": transport.get("mode", DEFAULT_TRANSPORT_MODE),
        "network_profile": network.get("profile", DEFAULT_NETWORK_PROFILE),
        "result": result,
    }


def write_manifest(path: Path | str, manifest: dict[str, Any]) -> None:
    """Write a manifest JSON file with stable formatting."""

    manifest_path = Path(path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path | str) -> dict[str, Any]:
    """Read a manifest JSON file."""

    manifest_path = Path(path)
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def update_manifest(path: Path | str, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge top-level updates into a manifest JSON file and rewrite it."""

    manifest_path = Path(path)
    manifest = read_manifest(manifest_path)
    manifest.update(updates)
    write_manifest(manifest_path, manifest)
    return manifest


def create_result_folder(
    bundle: dict[str, dict[str, Any]],
    results_root: Path | str = "results",
    timestamp: datetime | None = None,
    result: str = DEFAULT_RESULT_STATUS,
) -> tuple[Path, dict[str, Any]]:
    """Create results/<run_id>/ with manifest.json and notes.md."""

    current_timestamp = _coerce_timestamp(timestamp)
    root = Path(results_root)
    run_id = next_run_id(bundle["experiment"]["id"], root, current_timestamp)
    result_dir = root / run_id

    result_dir.mkdir(parents=True, exist_ok=False)

    manifest = build_manifest(bundle, run_id, current_timestamp, result=result)
    write_manifest(result_dir / "manifest.json", manifest)
    (result_dir / "notes.md").write_text(
        f"# Notes for {run_id}\n\n"
        "Add manual observations for this experiment run here.\n",
        encoding="utf-8",
    )

    return result_dir, manifest
