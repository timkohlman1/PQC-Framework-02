"""First-class build record helpers.

This module creates repository result records for successful firmware builds. It
performs local filesystem work only; it does not invoke build tools, Git, SSH,
UART, gateway helpers, or hardware.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.artifacts import copy_firmware_artifacts_to_result

BUILD_RESULTS_DIRNAME = "builds"
BUILD_RECORD_SCHEMA_VERSION = 1
BUILD_RECORD_TYPE = "build"


def build_records_root(results_root: Path | str) -> Path:
    """Return the build-record root under a results root."""

    return Path(results_root) / BUILD_RESULTS_DIRNAME


def build_record_dir(results_root: Path | str, build_number: int) -> Path:
    """Return the directory for a build number under a results root."""

    if not isinstance(build_number, int) or build_number < 1:
        raise ValueError("build_number must be a positive integer")

    return build_records_root(results_root) / str(build_number)


def build_record_dir_for_result_dir(result_dir: Path | str, build_number: int) -> Path:
    """Return the build-record directory associated with a run result directory."""

    return build_record_dir(Path(result_dir).parent, build_number)


def _format_timestamp(timestamp: datetime | None = None) -> str:
    current = timestamp if timestamp is not None else datetime.now().astimezone()
    return current.isoformat(timespec="seconds")


def _copy_log(source_log_path: Path, record_dir: Path) -> str | None:
    if not source_log_path.is_file():
        return None

    destination = record_dir / source_log_path.name
    shutil.copy2(source_log_path, destination)
    return destination.name


def build_record_manifest(
    *,
    bundle: dict[str, dict[str, Any]],
    build_number: int,
    firmware_artifact: str,
    firmware_artifact_path: str,
    firmware_sha256: str | None,
    source: dict[str, Any],
    build: dict[str, Any],
    firmware_result_artifacts: dict[str, dict[str, Any]],
    source_run_id: str | None,
    source_run_dir: Path | str | None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Create the manifest dictionary for one build record."""

    experiment = bundle["experiment"]
    board = bundle["board"]
    host = bundle["host"]

    return {
        "schema_version": BUILD_RECORD_SCHEMA_VERSION,
        "record_type": BUILD_RECORD_TYPE,
        "build_number": build_number,
        "timestamp": _format_timestamp(timestamp),
        "experiment": experiment["id"],
        "board": board["id"],
        "gateway": host["id"],
        "result": "build_skipped" if build.get("skipped") is True else "build_passed",
        "source": source,
        "build": build,
        "firmware": {
            "artifact": firmware_artifact,
            "artifact_path": firmware_artifact_path,
            "sha256": firmware_sha256,
            "result_artifacts": firmware_result_artifacts,
        },
        "compatibility": {
            "source_run_id": source_run_id,
            "source_run_dir": None if source_run_dir is None else str(source_run_dir),
            "source_run_manifest": None
            if source_run_dir is None
            else str(Path(source_run_dir) / "manifest.json"),
        },
    }


def write_build_record(
    *,
    bundle: dict[str, dict[str, Any]],
    result_dir: Path | str,
    build_number: int,
    firmware_elf_path: Path | str,
    firmware_artifact: str,
    firmware_artifact_path: str,
    firmware_sha256: str | None,
    source: dict[str, Any],
    build: dict[str, Any],
    source_run_id: str | None,
    build_log_path: Path | str,
) -> tuple[Path, dict[str, Any]]:
    """Create or refresh a first-class build record for a successful build.

    The build record lives under ``<results_root>/builds/<build_number>/`` where
    ``results_root`` is inferred from the parent directory of the compatibility
    run result directory.
    """

    result_dir_path = Path(result_dir)
    record_dir = build_record_dir_for_result_dir(result_dir_path, build_number)
    record_dir.mkdir(parents=True, exist_ok=True)

    build_log_name = _copy_log(Path(build_log_path), record_dir)
    build_for_record = dict(build)
    if build_log_name is not None:
        build_for_record["log"] = build_log_name

    firmware_result_artifacts = copy_firmware_artifacts_to_result(firmware_elf_path, record_dir)
    manifest = build_record_manifest(
        bundle=bundle,
        build_number=build_number,
        firmware_artifact=firmware_artifact,
        firmware_artifact_path=firmware_artifact_path,
        firmware_sha256=firmware_sha256,
        source=source,
        build=build_for_record,
        firmware_result_artifacts=firmware_result_artifacts,
        source_run_id=source_run_id,
        source_run_dir=result_dir_path,
    )

    (record_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return record_dir, manifest
