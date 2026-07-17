from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.signing_audit import append_signing_usage_event


def test_signing_usage_log_is_append_only_json_lines(tmp_path):
    tuple_dir = tmp_path / "secrets/wolfboot/tuples/test"
    log_path = append_signing_usage_event(
        tuple_directory=tuple_dir,
        event={"event": "first", "private_key_sha256": "abc"},
    )
    original = log_path.read_bytes()

    append_signing_usage_event(
        tuple_directory=tuple_dir,
        event={"event": "second", "private_key_sha256": "abc"},
    )

    updated = log_path.read_bytes()
    assert updated.startswith(original)
    records = [json.loads(line) for line in updated.decode("utf-8").splitlines()]
    assert [record["event"] for record in records] == ["first", "second"]
    assert all("timestamp_utc" in record for record in records)


def test_signing_usage_log_does_not_contain_private_key_bytes(tmp_path):
    tuple_dir = tmp_path / "tuple"
    log_path = append_signing_usage_event(
        tuple_directory=tuple_dir,
        event={"event": "application_image_signed", "private_key_sha256": "digest"},
    )
    content = log_path.read_text(encoding="utf-8")
    assert "digest" in content
    assert "PRIVATE KEY" not in content
