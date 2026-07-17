from __future__ import annotations

import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.wolfboot_build import _coordinate_wolfboot_signing_key_after_build


def test_persistent_tuple_key_is_not_rewritten_after_successful_build(tmp_path):
    canonical = tmp_path / "secrets/private_key.der"
    materialized = tmp_path / "tools/wolfboot/wolfboot_signing_private_key.der"
    canonical.parent.mkdir(parents=True)
    materialized.parent.mkdir(parents=True)
    canonical.write_bytes(b"same-key")
    materialized.write_bytes(b"same-key")
    original_mtime = canonical.stat().st_mtime_ns

    message = _coordinate_wolfboot_signing_key_after_build(
        signing_key_path=canonical,
        wolfboot_private_key_path=materialized,
        return_code=0,
        persistent_tuple=True,
    )

    assert canonical.read_bytes() == b"same-key"
    assert canonical.stat().st_mtime_ns == original_mtime
    assert "write-back was skipped" in message


def test_persistent_tuple_mismatch_is_reported_without_overwrite(tmp_path):
    canonical = tmp_path / "secrets/private_key.der"
    materialized = tmp_path / "tools/wolfboot/wolfboot_signing_private_key.der"
    canonical.parent.mkdir(parents=True)
    materialized.parent.mkdir(parents=True)
    canonical.write_bytes(b"canonical")
    materialized.write_bytes(b"different")

    message = _coordinate_wolfboot_signing_key_after_build(
        signing_key_path=canonical,
        wolfboot_private_key_path=materialized,
        return_code=0,
        persistent_tuple=True,
    )

    assert canonical.read_bytes() == b"canonical"
    assert "differ" in message
    assert "no write-back" in message
