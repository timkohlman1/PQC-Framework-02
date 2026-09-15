"""First-class build record helpers.

This module creates and validates repository result records for successful
firmware builds. It performs local filesystem work only; it does not invoke
build tools, Git, SSH, UART, gateway helpers, or hardware.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.artifacts import calculate_file_sha256, copy_firmware_artifacts_to_result

BUILD_RESULTS_DIRNAME = "builds"
BUILD_RECORD_SCHEMA_VERSION = 1
BUILD_RECORD_TYPE = "build"

BUILD_RECORD_OK = 0
BUILD_RECORD_MISSING_RETURN_CODE = 6
BUILD_RECORD_INVALID_RETURN_CODE = 7
BUILD_RECORD_MISMATCH_RETURN_CODE = 5
BUILD_RECORD_FINGERPRINT_ERROR_RETURN_CODE = 8

BUILD_RECORD_STATUS_VERIFIED = "verified_build_record"
BUILD_RECORD_STATUS_MISSING = "missing_build_record"
BUILD_RECORD_STATUS_INVALID = "invalid_build_record"
BUILD_RECORD_STATUS_MISMATCH = "mismatched_build_record"


@dataclass(frozen=True)
class VerifiedBuildRecord:
    """Validated first-class build record reference."""

    status: str
    return_code: int
    message: str
    build_number: int | None
    record_dir: Path | None
    manifest_path: Path | None
    artifact_path: Path | None
    firmware_sha256: str | None
    build_fingerprint: str | None
    build_fingerprint_algorithm: str | None
    current_build_fingerprint: str | None
    current_build_fingerprint_algorithm: str | None
    current_build_fingerprint_error: str | None
    manifest: dict[str, Any] | None


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


def _nested_get(mapping: dict[str, Any], dotted_path: str) -> Any:
    current: Any = mapping
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _required_string(mapping: dict[str, Any], dotted_path: str) -> tuple[str | None, str | None]:
    value = _nested_get(mapping, dotted_path)
    if not isinstance(value, str) or value == "":
        return None, f"Build record missing required string field: {dotted_path}"
    return value, None



def _manifest_path_for_build_number(results_root: Path, build_number: int) -> tuple[Path | None, str | None]:
    try:
        return build_record_dir(results_root, build_number) / "manifest.json", None
    except ValueError as exc:
        return None, str(exc)


def _artifact_path_from_manifest(record_dir: Path, manifest: dict[str, Any]) -> tuple[Path | None, str | None]:
    artifact_from_result = _nested_get(manifest, "firmware.result_artifacts.elf.artifact_path")
    if isinstance(artifact_from_result, str) and artifact_from_result:
        return Path(artifact_from_result), None

    artifact_name = _nested_get(manifest, "firmware.result_artifacts.elf.path")
    if isinstance(artifact_name, str) and artifact_name:
        return record_dir / artifact_name, None

    fallback = record_dir / "firmware.elf"
    if fallback.is_file():
        return fallback, None

    return None, "Build record does not identify a retained firmware.elf artifact."


def resolve_verified_build_record(
    *,
    results_root: Path | str,
    build_number: int,
    bundle: dict[str, dict[str, Any]],
    repo_root: Path | str,
) -> VerifiedBuildRecord:
    """Validate an immutable build record by metadata and ELF SHA-256.

    Source/build fingerprints are deliberately not recalculated. A referenced
    record is accepted only when its metadata matches the requested experiment
    context and its retained ELF hashes to the recorded artifact identity.
    """
    del repo_root
    results_root_path = Path(results_root)
    manifest_path, error = _manifest_path_for_build_number(results_root_path, build_number)
    record_dir = build_record_dir(results_root_path, build_number)
    if error is not None or manifest_path is None:
        return VerifiedBuildRecord(BUILD_RECORD_STATUS_MISSING, BUILD_RECORD_MISSING_RETURN_CODE, error or "Build record is unavailable.", build_number, record_dir, manifest_path, None, None, None, None, None, None, None, None)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerifiedBuildRecord(BUILD_RECORD_STATUS_INVALID, BUILD_RECORD_INVALID_RETURN_CODE, f"Build record manifest could not be read: {exc}", build_number, record_dir, manifest_path, None, None, None, None, None, None, None, None)
    if not isinstance(manifest, dict):
        return VerifiedBuildRecord(BUILD_RECORD_STATUS_INVALID, BUILD_RECORD_INVALID_RETURN_CODE, "Build record manifest must be a JSON object.", build_number, record_dir, manifest_path, None, None, None, None, None, None, None, None)

    expected_experiment = str(bundle["experiment"]["id"])
    expected_board = str(bundle["board"]["id"])
    expected_application = str(bundle["experiment"].get("firmware", {}).get("application", "mqtt_validation"))
    if manifest.get("experiment") != expected_experiment or manifest.get("board") != expected_board:
        return VerifiedBuildRecord(BUILD_RECORD_STATUS_MISMATCH, BUILD_RECORD_MISMATCH_RETURN_CODE, "Referenced build record does not match the requested experiment and board.", build_number, record_dir, manifest_path, None, None, None, None, None, None, None, manifest)
    recorded_application = _nested_get(manifest, "firmware.application")
    if recorded_application is not None and recorded_application != expected_application:
        return VerifiedBuildRecord(BUILD_RECORD_STATUS_MISMATCH, BUILD_RECORD_MISMATCH_RETURN_CODE, "Referenced build record does not match the requested firmware application.", build_number, record_dir, manifest_path, None, None, None, None, None, None, None, manifest)

    recorded_sha256, sha_error = _required_string(manifest, "firmware.sha256")
    if sha_error is not None or recorded_sha256 is None:
        return VerifiedBuildRecord(BUILD_RECORD_STATUS_INVALID, BUILD_RECORD_INVALID_RETURN_CODE, sha_error or "Build record firmware SHA-256 is unavailable.", build_number, record_dir, manifest_path, None, None, None, None, None, None, None, manifest)
    artifact_path, artifact_error = _artifact_path_from_manifest(record_dir, manifest)
    if artifact_error is not None or artifact_path is None or not artifact_path.is_file():
        return VerifiedBuildRecord(BUILD_RECORD_STATUS_MISSING, BUILD_RECORD_MISSING_RETURN_CODE, artifact_error or f"Build record firmware artifact not found: {artifact_path}", build_number, record_dir, manifest_path, artifact_path, recorded_sha256, None, None, None, None, None, manifest)
    actual_sha256 = calculate_file_sha256(artifact_path)
    if actual_sha256 != recorded_sha256:
        return VerifiedBuildRecord(BUILD_RECORD_STATUS_MISMATCH, BUILD_RECORD_MISMATCH_RETURN_CODE, "Build record firmware artifact SHA-256 does not match the manifest.", build_number, record_dir, manifest_path, artifact_path, recorded_sha256, None, None, None, None, None, manifest)
    return VerifiedBuildRecord(BUILD_RECORD_STATUS_VERIFIED, BUILD_RECORD_OK, "Referenced build record and retained ELF SHA-256 are valid.", build_number, record_dir, manifest_path, artifact_path, recorded_sha256, None, None, None, None, None, manifest)

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
        "configuration": dict(experiment.get("resolved_configuration", {})) if isinstance(experiment.get("resolved_configuration"), dict) else {},
        "build": build,
        "firmware": {
            "application": str(bundle["experiment"].get("firmware", {}).get("application", "mqtt_validation")),
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
