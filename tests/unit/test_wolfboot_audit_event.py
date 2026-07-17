from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.signing_audit import append_signing_usage_event


def test_wolfboot_audit_event_uses_profile_algorithm(tmp_path):
    profile = {"signature_algorithm": "ecdsa_p256"}
    log_path = append_signing_usage_event(
        tuple_directory=tmp_path / "tuple",
        event={
            "event": "wolfboot_verification_key_use",
            "signature_algorithm": profile.get("signature_algorithm"),
        },
    )

    content = log_path.read_text(encoding="utf-8")
    assert '"signature_algorithm":"ecdsa_p256"' in content
