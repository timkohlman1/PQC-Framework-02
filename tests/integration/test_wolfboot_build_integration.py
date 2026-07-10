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
    request,
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

    canonical_key = repo_root / "secrets/wolfboot/ecdsa_p256_private_key.der"
    wolfboot_private_key = source_dir / "wolfboot_signing_private_key.der"
    wolfboot_public_key = source_dir / "wolfboot_signing_public_key.der"
    generated_keystore = source_dir / "src/keystore.c"
    tuple_paths = (
        canonical_key,
        wolfboot_private_key,
        wolfboot_public_key,
        generated_keystore,
    )
    tuple_exists = tuple(path.is_file() for path in tuple_paths)
    if any(tuple_exists) and not all(tuple_exists):
        missing = ", ".join(
            str(path.relative_to(repo_root))
            for path, exists in zip(tuple_paths, tuple_exists, strict=True)
            if not exists
        )
        message = (
            "PQC capability unavailable: wolfBoot local signing tuple is incomplete; "
            f"missing {missing}. Restore the matching local tuple or rotate it outside "
            "the test workflow. The integration test must not reconstruct or delete "
            "canonical signing material."
        )
        if request.config.getoption("--pqc-require-local-build"):
            pytest.fail(message)
        pytest.skip(message)

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
