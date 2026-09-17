from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _enabled() -> bool:
    return os.environ.get("PQC_OTA_HW", "").strip().lower() in {"1", "true", "yes", "on"}


def _run(case: str, plan: str | None, results_dir: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    command = [sys.executable, "scripts/experiment.py", "run", "--experiment", case, "--results-dir", str(results_dir)]
    if plan:
        command.extend(["--ota-plan", plan])
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    manifests = sorted(results_dir.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime_ns)
    assert manifests, completed.stdout + "\n" + completed.stderr
    return completed, manifests[-1]


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} must be set for this destructive OTA scenario")
    return value


def _assert_delivery_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    ota = manifest.get("ota", {})
    assert ota.get("requested") is True
    assert ota.get("transport") == "reporting_mqtt_plaintext"
    assert ota.get("impairment_exempt") is True
    assert ota.get("delivery", {}).get("return_code") == 0
    return manifest


@pytest.fixture(scope="module")
def ota_hw_ready(pqc_require_capabilities):
    pqc_require_capabilities("local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware")
    if not _enabled():
        pytest.skip("set PQC_OTA_HW=1 to run destructive Request-5 dual-bank OTA validation")


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_and_confirmation_hw(ota_hw_ready, tmp_path: Path):
    case = _require_env("PQC_OTA_HW_CASE")
    plan = _require_env("PQC_OTA_HW_APP_PLAN")
    completed, manifest_path = _run(case, plan, tmp_path / "app-update")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_unconfirmed_rollback_hw(ota_hw_ready, tmp_path: Path):
    case = _require_env("PQC_OTA_HW_CASE")
    plan = _require_env("PQC_OTA_HW_ROLLBACK_PLAN")
    completed, manifest_path = _run(case, plan, tmp_path / "rollback")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    # A subsequent normal run is the recovery proof: the prior bank must still
    # boot through wolfBoot and complete the normal experiment.
    recovered, _ = _run(case, None, tmp_path / "rollback-recovery")
    assert recovered.returncode == 0, recovered.stdout + "\n" + recovered.stderr


@pytest.mark.hardware
@pytest.mark.long
def test_bootloader_migration_and_recovery_hw(ota_hw_ready, tmp_path: Path):
    case = _require_env("PQC_OTA_HW_CASE")
    plan = _require_env("PQC_OTA_HW_MIGRATION_PLAN")
    completed, manifest_path = _run(case, plan, tmp_path / "migration")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    recovered, _ = _run(case, None, tmp_path / "migration-postswap")
    assert recovered.returncode == 0, recovered.stdout + "\n" + recovered.stderr


@pytest.mark.hardware
@pytest.mark.long
@pytest.mark.parametrize(
    "env_name",
    ("PQC_OTA_HW_INTERRUPTED_PLAN", "PQC_OTA_HW_CORRUPT_APP_PLAN", "PQC_OTA_HW_INVALID_MANIFEST_PLAN"),
)
def test_invalid_candidate_never_breaks_previous_bank_hw(ota_hw_ready, tmp_path: Path, env_name: str):
    case = _require_env("PQC_OTA_HW_CASE")
    plan = _require_env(env_name)
    attempted, _ = _run(case, plan, tmp_path / env_name.lower())
    # Delivery/runtime may fail by design for malformed candidates; the required
    # invariant is that a subsequent normal boot remains recoverable.
    assert attempted.returncode in {0, 10, 20, 30, 40}, attempted.stdout + "\n" + attempted.stderr
    recovered, _ = _run(case, None, tmp_path / f"{env_name.lower()}-recovery")
    assert recovered.returncode == 0, recovered.stdout + "\n" + recovered.stderr
