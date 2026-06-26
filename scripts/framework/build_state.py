"""Local last-successful-build state helpers.

This module reads and writes generated repository-local state that records the
latest successful build fingerprint and artifact identity. The state is intended
for future rebuild-skip decisions, but Phase 9b only records the state; it does
not skip builds.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

LOCAL_BUILD_STATE_FILENAME = ".last_successful_build.json"
LOCAL_BUILD_STATE_SCHEMA_VERSION = 1


class BuildHashStateError(Exception):
    """Raised when local build-hash state is malformed or cannot be used."""


def local_build_state_path(repo_root: Path | str) -> Path:
    """Return the repository-local generated build-hash state path."""

    return Path(repo_root) / LOCAL_BUILD_STATE_FILENAME


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BuildHashStateError(f"Local build-hash state field must be an object: {name}")
    return value


def _require_string(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or value == "":
        raise BuildHashStateError(f"Local build-hash state missing required string field: {key}")
    return value


def _require_string_list(mapping: dict[str, Any], key: str) -> list[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BuildHashStateError(f"Local build-hash state field must be a string list: {key}")
    return list(value)


def validate_last_successful_build_state(state: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a local last-successful-build state dictionary."""

    if state.get("schema_version") != LOCAL_BUILD_STATE_SCHEMA_VERSION:
        raise BuildHashStateError(
            "Local build-hash state has an unsupported or missing schema_version"
        )

    _require_string(state, "updated_at")

    run_id = state.get("run_id")
    if run_id is not None and not isinstance(run_id, str):
        raise BuildHashStateError("Local build-hash state field must be a string or null: run_id")

    build_number = state.get("build_number")
    if build_number is not None and not isinstance(build_number, int):
        raise BuildHashStateError(
            "Local build-hash state field must be an integer or null: build_number"
        )

    build = _require_mapping(state.get("build"), "build")
    firmware = _require_mapping(state.get("firmware"), "firmware")

    _require_string(build, "fingerprint")
    _require_string(build, "fingerprint_algorithm")
    _require_string_list(build, "fingerprint_inputs")

    _require_string(firmware, "artifact")
    _require_string(firmware, "artifact_path")
    _require_string(firmware, "sha256")

    result_artifacts = firmware.get("result_artifacts", {})
    if not isinstance(result_artifacts, dict):
        raise BuildHashStateError(
            "Local build-hash state field must be an object: firmware.result_artifacts"
        )

    return state


def read_last_successful_build_state(repo_root: Path | str) -> dict[str, Any] | None:
    """Read generated last-successful-build state.

    Missing state is normal and returns ``None``. Malformed JSON or invalid
    schema raises ``BuildHashStateError`` so future rebuild-skip logic can avoid
    silently trusting corrupted state.
    """

    path = local_build_state_path(repo_root)
    if not path.exists():
        return None

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildHashStateError(f"Local build-hash state is not valid JSON: {path}") from exc

    if not isinstance(state, dict):
        raise BuildHashStateError(f"Local build-hash state root must be an object: {path}")

    return validate_last_successful_build_state(state)


def build_last_successful_build_state(
    *,
    run_id: str | None,
    build_number: int | None,
    build_fingerprint: str,
    build_fingerprint_algorithm: str,
    build_fingerprint_inputs: list[str],
    firmware_artifact: str,
    firmware_artifact_path: str,
    firmware_sha256: str,
    result_artifacts: dict[str, dict[str, Any]],
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    """Create normalized local state for a successful firmware build."""

    timestamp = updated_at if updated_at is not None else datetime.now().astimezone()
    state = {
        "schema_version": LOCAL_BUILD_STATE_SCHEMA_VERSION,
        "updated_at": timestamp.isoformat(timespec="seconds"),
        "run_id": run_id,
        "build_number": build_number,
        "build": {
            "fingerprint": build_fingerprint,
            "fingerprint_algorithm": build_fingerprint_algorithm,
            "fingerprint_inputs": list(build_fingerprint_inputs),
        },
        "firmware": {
            "artifact": firmware_artifact,
            "artifact_path": firmware_artifact_path,
            "sha256": firmware_sha256,
            "result_artifacts": result_artifacts,
        },
    }
    return validate_last_successful_build_state(state)


def write_last_successful_build_state(
    repo_root: Path | str,
    state: dict[str, Any],
) -> Path:
    """Write generated last-successful-build state atomically."""

    normalized_state = validate_last_successful_build_state(state)
    path = local_build_state_path(repo_root)
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    temporary_path.write_text(
        json.dumps(normalized_state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)
    return path


def record_last_successful_build_state(
    *,
    repo_root: Path | str,
    run_id: str | None,
    build_number: int | None,
    build_fingerprint: str,
    build_fingerprint_algorithm: str,
    build_fingerprint_inputs: list[str],
    firmware_artifact: str,
    firmware_artifact_path: str,
    firmware_sha256: str,
    result_artifacts: dict[str, dict[str, Any]],
) -> Path:
    """Record the latest successful build hash and artifact identity."""

    state = build_last_successful_build_state(
        run_id=run_id,
        build_number=build_number,
        build_fingerprint=build_fingerprint,
        build_fingerprint_algorithm=build_fingerprint_algorithm,
        build_fingerprint_inputs=build_fingerprint_inputs,
        firmware_artifact=firmware_artifact,
        firmware_artifact_path=firmware_artifact_path,
        firmware_sha256=firmware_sha256,
        result_artifacts=result_artifacts,
    )
    return write_last_successful_build_state(repo_root, state)
