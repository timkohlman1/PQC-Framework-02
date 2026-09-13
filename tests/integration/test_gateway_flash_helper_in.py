from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from framework.config_resolver import ConfigResolver
_BASELINE_ROOT = ConfigResolver(ROOT).materialize_campaign("baseline")
EXPERIMENT_CONFIG = next(sorted((_BASELINE_ROOT / "cases").glob("*.yaml"))).relative_to(ROOT).as_posix()
EXPECTED_STLINK_SERIAL = "066EFF3932504E3043111818"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_cli(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/experiment.py", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_result_dirs(results_dir: Path) -> list[Path]:
    """Return experiment run result directories, excluding build-record storage."""

    return sorted(
        path
        for path in results_dir.iterdir()
        if path.is_dir() and path.name != "builds"
    )


def _single_result_dir(results_dir: Path) -> Path:
    result_dirs = _run_result_dirs(results_dir)
    assert len(result_dirs) == 1
    return result_dirs[0]


def _build_record_dir(results_dir: Path, build_number: int) -> Path:
    return results_dir / "builds" / str(build_number)


@pytest.mark.integration
def test_gateway_flash_helper_with_verified_build_record(tmp_path, pqc_require_capabilities):
    """Run a real build, then flash that verified build through the gateway.

    This test is hardware-dependent and auto-skips unless the local build
    toolchain, SSH gateway, and configured flash helper are available. It
    intentionally creates the build record inside the same temporary results
    directory used by the flash command, so the flash provenance gate can verify
    the build-run manifest before SCP or SSH are attempted. Use
    --pqc-require-gateway to turn missing capability skips into failures.
    """

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        strict_mode="gateway",
    )

    repo_root = _repo_root()
    results_dir = tmp_path / "results"

    build_completed = _run_cli(
        repo_root,
        [
            "build",
            "--experiment",
            EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
            "--force",
        ],
    )
    assert build_completed.returncode == 0, (
        f"build stdout:\n{build_completed.stdout}\nbuild stderr:\n{build_completed.stderr}"
    )

    build_result_dir = _single_result_dir(results_dir)
    build_manifest = json.loads(
        (build_result_dir / "manifest.json").read_text(encoding="utf-8")
    )
    build_run_id = str(build_manifest["run_id"])
    build_number = build_manifest["build_number"]
    build_record_dir = _build_record_dir(results_dir, build_number)
    build_record_manifest_path = build_record_dir / "manifest.json"

    assert (build_result_dir / "build.log").is_file()
    assert build_manifest["result"] == "build_passed"
    assert isinstance(build_manifest["firmware"]["sha256"], str)
    assert len(build_manifest["firmware"]["sha256"]) == 64
    assert isinstance(build_manifest["build"]["fingerprint"], str)
    assert len(build_manifest["build"]["fingerprint"]) == 64
    assert build_manifest["build"]["record_path"] == str(build_record_dir)
    assert build_manifest["build"]["record_manifest"] == str(build_record_manifest_path)

    assert build_record_dir.is_dir()
    assert build_record_manifest_path.is_file()
    assert (build_record_dir / "build.log").is_file()
    assert (build_record_dir / "firmware.elf").is_file()

    build_record_manifest = json.loads(
        build_record_manifest_path.read_text(encoding="utf-8")
    )
    assert build_record_manifest["record_type"] == "build"
    assert build_record_manifest["build_number"] == build_number
    assert build_record_manifest["result"] == "build_passed"
    assert (
        build_record_manifest["firmware"]["sha256"]
        == build_manifest["firmware"]["sha256"]
    )
    assert (
        build_record_manifest["build"]["fingerprint"]
        == build_manifest["build"]["fingerprint"]
    )
    assert build_record_manifest["compatibility"]["source_run_id"] == build_run_id

    flash_completed = _run_cli(
        repo_root,
        [
            "flash",
            "--experiment",
            EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
            "--build-run",
            build_run_id,
        ],
    )
    assert flash_completed.returncode == 0, (
        f"flash stdout:\n{flash_completed.stdout}\nflash stderr:\n{flash_completed.stderr}"
    )

    result_dirs = _run_result_dirs(results_dir)
    assert len(result_dirs) == 2
    flash_result_dir = next(path for path in result_dirs if path != build_result_dir)
    flash_manifest = json.loads(
        (flash_result_dir / "manifest.json").read_text(encoding="utf-8")
    )

    assert (flash_result_dir / "flash.log").is_file()
    assert flash_manifest["result"] == "flash_passed"
    assert flash_manifest["flash"]["return_code"] == 0
    assert flash_manifest["flash"]["scp_return_code"] == 0
    assert flash_manifest["flash"]["helper_return_code"] == 0
    assert flash_manifest["flash"]["stlink_serial"] == EXPECTED_STLINK_SERIAL
    assert flash_manifest["flash"]["provenance_status"] == "verified_build_match"
    assert flash_manifest["flash"]["source_build_run_id"] == build_run_id
    assert (
        flash_manifest["flash"]["source_build_firmware_sha256"]
        == build_manifest["firmware"]["sha256"]
    )
    assert flash_manifest["flash"]["firmware_sha256"] == build_manifest["firmware"]["sha256"]
    assert (
        flash_manifest["flash"]["source_build_fingerprint"]
        == build_manifest["build"]["fingerprint"]
    )
    assert (
        flash_manifest["flash"]["current_build_fingerprint"]
        == build_manifest["build"]["fingerprint"]
    )
    assert flash_manifest["firmware"]["sha256"] == build_manifest["firmware"]["sha256"]
