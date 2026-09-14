from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.wolfboot_build import execute_wolfboot_build


def _profile() -> dict[str, object]:
    return {
        "id": "wolfboot_scope_regression",
        "description": "Regression profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "ecdsa_p256",
        "build": {
            "command": "make",
            "args": "WOLFBOOT_ROOT=. wolfboot.elf",
            "config_template": "testdata/wolfboot/missing.config",
            "generated_config": "tools/wolfboot/.config",
            "signing_key": (
                "secrets/wolfboot/tuples/"
                "ecdsa_p256-development/private_key.der"
            ),
            "wolfboot_private_key": (
                "tools/wolfboot/wolfboot_signing_private_key.der"
            ),
            "generated_keystore": "tools/wolfboot/src/keystore.c",
            "signing_tuple": {
                "tuple_id": "ecdsa_p256-development",
                "directory": (
                    "secrets/wolfboot/tuples/ecdsa_p256-development"
                ),
                "private_key": "private_key.der",
                "keystore": "keystore.c",
                "manifest": "tuple.json",
            },
        },
    }


def test_config_preflight_failure_does_not_reference_unassigned_tuple_state(
    tmp_path,
):
    repo_root = tmp_path / "repo"
    (repo_root / "tools/wolfboot").mkdir(parents=True)

    result = execute_wolfboot_build(
        profile=_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
    )

    assert result.return_code != 0
    assert result.failure_reason is not None
    assert "config" in result.failure_reason.lower()
