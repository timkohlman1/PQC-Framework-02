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
from framework.fingerprint import (
    FingerprintInputError,
    calculate_default_build_fingerprint,
)

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


def _calculate_current_build_fingerprint(
    bundle: dict[str, dict[str, Any]],
    repo_root: Path,
) -> tuple[str | None, str | None, str | None]:
    try:
        fingerprint = calculate_default_build_fingerprint(bundle, repo_root)
    except FingerprintInputError as exc:
        return None, None, str(exc)

    return fingerprint.fingerprint, fingerprint.algorithm, None


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
    """Verify a first-class build record is safe for experiment reuse.

    The check is intentionally strict: the build-record manifest must exist,
    identify the requested build number, contain the expected metadata, retain a
    firmware artifact, match the artifact SHA-256, and match the current
    source/build fingerprint for the resolved experiment bundle.
    """

    results_root_path = Path(results_root)
    repo_root_path = Path(repo_root)
    manifest_path, path_error = _manifest_path_for_build_number(results_root_path, build_number)
    current_fingerprint, current_algorithm, fingerprint_error = _calculate_current_build_fingerprint(
        bundle,
        repo_root_path,
    )

    if path_error is not None or manifest_path is None:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_INVALID,
            return_code=BUILD_RECORD_INVALID_RETURN_CODE,
            message=path_error if path_error is not None else "Invalid build number.",
            build_number=build_number,
            record_dir=None,
            manifest_path=None,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=fingerprint_error,
            manifest=None,
        )

    record_dir = manifest_path.parent

    if fingerprint_error is not None:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_MISMATCH,
            return_code=BUILD_RECORD_FINGERPRINT_ERROR_RETURN_CODE,
            message=f"Current build fingerprint could not be calculated: {fingerprint_error}",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=fingerprint_error,
            manifest=None,
        )

    if not manifest_path.is_file():
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_MISSING,
            return_code=BUILD_RECORD_MISSING_RETURN_CODE,
            message=f"Build record manifest not found: {manifest_path}",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=None,
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_INVALID,
            return_code=BUILD_RECORD_INVALID_RETURN_CODE,
            message=f"Build record manifest is not valid JSON: {manifest_path}",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=None,
        )

    if not isinstance(manifest, dict):
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_INVALID,
            return_code=BUILD_RECORD_INVALID_RETURN_CODE,
            message="Build record manifest root must be an object.",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=None,
        )

    if manifest.get("schema_version") != BUILD_RECORD_SCHEMA_VERSION:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_INVALID,
            return_code=BUILD_RECORD_INVALID_RETURN_CODE,
            message="Build record manifest has an unsupported or missing schema_version.",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    if manifest.get("record_type") != BUILD_RECORD_TYPE:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_INVALID,
            return_code=BUILD_RECORD_INVALID_RETURN_CODE,
            message="Build record manifest is not a build record.",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    if manifest.get("build_number") != build_number:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_INVALID,
            return_code=BUILD_RECORD_INVALID_RETURN_CODE,
            message=(
                "Build record number mismatch: "
                f"expected {build_number}, found {manifest.get('build_number')}"
            ),
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    if manifest.get("result") not in {"build_passed", "build_skipped"}:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_INVALID,
            return_code=BUILD_RECORD_INVALID_RETURN_CODE,
            message=f"Build record result is not reusable: {manifest.get('result')}",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    if manifest.get("experiment") != bundle["experiment"].get("id"):
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_MISMATCH,
            return_code=BUILD_RECORD_MISMATCH_RETURN_CODE,
            message="Build record experiment ID does not match the requested experiment.",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    if manifest.get("board") != bundle["board"].get("id"):
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_MISMATCH,
            return_code=BUILD_RECORD_MISMATCH_RETURN_CODE,
            message="Build record board ID does not match the requested experiment board.",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=None,
            build_fingerprint=None,
            build_fingerprint_algorithm=None,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    recorded_sha256, sha_error = _required_string(manifest, "firmware.sha256")
    recorded_fingerprint, fingerprint_field_error = _required_string(manifest, "build.fingerprint")
    recorded_algorithm, algorithm_error = _required_string(manifest, "build.fingerprint_algorithm")
    required_errors = [
        error
        for error in [sha_error, fingerprint_field_error, algorithm_error]
        if error is not None
    ]
    if required_errors:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_INVALID,
            return_code=BUILD_RECORD_INVALID_RETURN_CODE,
            message="; ".join(required_errors),
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=recorded_sha256,
            build_fingerprint=recorded_fingerprint,
            build_fingerprint_algorithm=recorded_algorithm,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    artifact_path, artifact_error = _artifact_path_from_manifest(record_dir, manifest)
    if artifact_error is not None or artifact_path is None:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_INVALID,
            return_code=BUILD_RECORD_INVALID_RETURN_CODE,
            message=artifact_error if artifact_error is not None else "Build record artifact is unavailable.",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=None,
            firmware_sha256=recorded_sha256,
            build_fingerprint=recorded_fingerprint,
            build_fingerprint_algorithm=recorded_algorithm,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    if not artifact_path.is_file():
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_MISSING,
            return_code=BUILD_RECORD_MISSING_RETURN_CODE,
            message=f"Build record firmware artifact not found: {artifact_path}",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=artifact_path,
            firmware_sha256=recorded_sha256,
            build_fingerprint=recorded_fingerprint,
            build_fingerprint_algorithm=recorded_algorithm,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    actual_sha256 = calculate_file_sha256(artifact_path)
    if actual_sha256 != recorded_sha256:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_MISMATCH,
            return_code=BUILD_RECORD_MISMATCH_RETURN_CODE,
            message="Build record firmware artifact SHA-256 does not match the manifest.",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=artifact_path,
            firmware_sha256=recorded_sha256,
            build_fingerprint=recorded_fingerprint,
            build_fingerprint_algorithm=recorded_algorithm,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    if recorded_algorithm != current_algorithm or recorded_fingerprint != current_fingerprint:
        return VerifiedBuildRecord(
            status=BUILD_RECORD_STATUS_MISMATCH,
            return_code=BUILD_RECORD_MISMATCH_RETURN_CODE,
            message="Current source/build fingerprint does not match the referenced build record.",
            build_number=build_number,
            record_dir=record_dir,
            manifest_path=manifest_path,
            artifact_path=artifact_path,
            firmware_sha256=recorded_sha256,
            build_fingerprint=recorded_fingerprint,
            build_fingerprint_algorithm=recorded_algorithm,
            current_build_fingerprint=current_fingerprint,
            current_build_fingerprint_algorithm=current_algorithm,
            current_build_fingerprint_error=None,
            manifest=manifest,
        )

    return VerifiedBuildRecord(
        status=BUILD_RECORD_STATUS_VERIFIED,
        return_code=BUILD_RECORD_OK,
        message="Referenced build record is valid and matches the current source/build fingerprint.",
        build_number=build_number,
        record_dir=record_dir,
        manifest_path=manifest_path,
        artifact_path=artifact_path,
        firmware_sha256=recorded_sha256,
        build_fingerprint=recorded_fingerprint,
        build_fingerprint_algorithm=recorded_algorithm,
        current_build_fingerprint=current_fingerprint,
        current_build_fingerprint_algorithm=current_algorithm,
        current_build_fingerprint_error=None,
        manifest=manifest,
    )


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
