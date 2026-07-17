"""Append-only local audit records for persistent signing tuples."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SIGNING_USAGE_LOG = "signing-usage.jsonl"


def append_signing_usage_event(
    *,
    tuple_directory: Path,
    event: dict[str, Any],
    log_name: str = DEFAULT_SIGNING_USAGE_LOG,
) -> Path:
    """Append one JSON event without rewriting existing audit history."""

    tuple_directory.mkdir(parents=True, exist_ok=True)
    log_path = tuple_directory / log_name
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **event,
    }
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    descriptor = os.open(
        log_path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return log_path


def configured_tuple_directory(
    *,
    profile: dict[str, Any],
    repo_root: Path,
    config_path: str,
) -> Path | None:
    """Resolve a tuple directory from a dotted profile mapping path."""

    value: Any = profile
    for part in config_path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else repo_root / path
