from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def test_signing_audit_hash_is_assigned_before_usage_event():
    source = (
        REPO_ROOT / "scripts/framework/signing.py"
    ).read_text(encoding="utf-8")

    hash_assignment = source.index(
        "private_key_sha256 = (\n"
        "        calculate_file_sha256(private_key_path)"
    )
    audit_event = source.index(
        '"event": "application_image_signed"'
    )

    assert hash_assignment < audit_event


def test_signing_audit_event_records_computed_key_hash():
    source = (
        REPO_ROOT / "scripts/framework/signing.py"
    ).read_text(encoding="utf-8")

    audit_start = source.index(
        '"event": "application_image_signed"'
    )
    audit_end = source.index(
        "record_generated_state_success(",
        audit_start,
    )
    audit_block = source[audit_start:audit_end]

    assert '"private_key_sha256": private_key_sha256' in audit_block
    assert '"private_key_modified": not private_key_existed_before' in audit_block
