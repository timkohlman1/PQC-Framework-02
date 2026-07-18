from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.wolfboot_build import construct_wolfboot_build_command


def test_wolfboot_command_construction_retains_shlex_support():
    profile = {
        "id": "wolfboot_command_regression",
        "description": "Regression profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "ecdsa_p256",
        "build": {
            "command": "make",
            "args": 'WOLFBOOT_ROOT=. "wolfboot.elf"',
        },
    }

    assert construct_wolfboot_build_command(profile) == [
        "make",
        "WOLFBOOT_ROOT=.",
        "wolfboot.elf",
    ]
