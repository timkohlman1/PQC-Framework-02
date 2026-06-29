from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_real_wolfboot_build_profile_records_evidence_when_tooling_is_available(tmp_path):
    """Run the real wolfBoot build profile only when local wolfBoot source exists.

    Phase 10f does not vendor wolfBoot source. This test therefore skips unless
    the configured local source directory and basic build command are available.
    """

    repo_root = _repo_root()
    source_dir = repo_root / "tools" / "wolfboot"
    if not source_dir.is_dir():
        pytest.skip("wolfBoot source directory is not available at tools/wolfboot")

    if shutil.which("make") is None:
        pytest.skip("make is not available for the configured wolfBoot build profile")

    results_dir = tmp_path / "results"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/experiment.py",
            "build-wolfboot",
            "--profile",
            "configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml",
            "--results-dir",
            str(results_dir),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, (
        "Expected the real wolfBoot build profile to succeed when local source/tooling are available.\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )

    result_dirs = sorted((results_dir / "wolfboot-builds").iterdir())
    assert len(result_dirs) == 1

    result_dir = result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    build_log = (result_dir / "wolfboot_build.log").read_text(encoding="utf-8")

    assert manifest["record_type"] == "wolfboot_build"
    assert manifest["result"] == "wolfboot_build_passed"
    assert manifest["wolfboot_build"]["signature_algorithm"] == "ecdsa_p256"
    assert manifest["wolfboot_build"]["return_code"] == 0
    assert manifest["artifact"]["exists"] is True
    assert isinstance(manifest["artifact"]["sha256"], str)
    assert len(manifest["artifact"]["sha256"]) == 64
    assert (result_dir / "wolfboot.elf").is_file()
    assert "wolfBoot build log" in build_log
    assert "No signing" not in build_log
