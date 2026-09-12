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
def test_real_wolfboot_build_profile_records_evidence_when_tooling_is_available(
    tmp_path,
    pqc_require_capabilities,
):
    """Run the real wolfBoot build profile when local tooling is available.

    The test is capability-gated rather than hidden behind an additional
    opt-in environment variable. A plain ``python -m pytest`` run exercises this
    local-toolchain-only wolfBoot build when the submodule and build tools are
    available, and skips cleanly when they are unavailable.
    """

    pqc_require_capabilities("local_toolchain", strict_mode="local_build")

    repo_root = _repo_root()
    source_dir = repo_root / "tools" / "wolfboot"
    if not source_dir.is_dir():
        pytest.skip("wolfBoot source directory is not available at tools/wolfboot")

    if shutil.which("make") is None:
        pytest.skip("make is not available for the configured wolfBoot build profile")

    # The ECDSA-P256 benchmark profile is explicitly disposable. The framework
    # must self-heal an incomplete or mismatched local tuple by rotating the
    # complete experimental tuple before invoking make.

    results_dir = tmp_path / "results"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/experiment.py",
            "build-wolfboot",
            "--boot-algorithm",
            "ecdsa_p256",
            "--results-dir",
            str(results_dir),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, (
        "Expected the real wolfBoot build profile to succeed when explicitly enabled "
        "and local source/tooling/target adaptation are available.\n"
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
