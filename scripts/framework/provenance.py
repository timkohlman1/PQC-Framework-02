"""Durable automated-test result and test-build provenance helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TEST_BUILD_PURPOSE = "automated_test"
NORMAL_BUILD_PURPOSE = "experiment"
TEST_RESULTS_DIRNAME = "automated-tests"
_SECRET_KEY_RE = re.compile(r"(?i)(password|passwd|secret|token|private[_-]?key|psk|credential)")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_test_run_id(now: datetime | None = None, pid: int | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H%M%SZ")
    return f"pytest-{stamp}-{pid if pid is not None else os.getpid()}"


def test_results_root(repo_root: Path | str) -> Path:
    return Path(repo_root) / "results" / TEST_RESULTS_DIRNAME


def allocate_test_result_dir(repo_root: Path | str, run_id: str) -> Path:
    root = test_results_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / run_id
    suffix = 1
    while candidate.exists():
        candidate = root / f"{run_id}-{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def redact(value: Any, key: str | None = None) -> Any:
    if key and _SECRET_KEY_RE.search(key):
        return "redacted"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return [redact(v) for v in value]
    return value


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(redact(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reserve_test_build_identity(result_dir: Path | str) -> tuple[str, Path]:
    run_dir = Path(result_dir)
    builds_dir = run_dir / "builds"
    builds_dir.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name) for p in builds_dir.iterdir() if p.is_dir() and p.name.isdigit()]
    sequence = max(existing, default=0) + 1
    identity = f"{run_dir.name}-build-{sequence:04d}"
    target = builds_dir / f"{sequence:04d}"
    target.mkdir(parents=True, exist_ok=False)
    return identity, target


def current_build_purpose() -> str:
    return os.environ.get("PQC_BUILD_PURPOSE", NORMAL_BUILD_PURPOSE).strip() or NORMAL_BUILD_PURPOSE


def current_test_result_dir() -> Path | None:
    value = os.environ.get("PQC_TEST_RESULT_DIR")
    return Path(value) if value else None
