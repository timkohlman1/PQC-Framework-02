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
    provenance_path = path.parent / "run-provenance.json"
    assert provenance_path.is_file(), f"missing durable run provenance: {provenance_path}"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    ota = (provenance.get("records") or {}).get("ota", {})
    assert ota.get("requested") is True
    assert ota.get("transport") == "reporting_mqtt_plaintext"
    assert ota.get("impairment_exempt") is True
    assert ota.get("delivery", {}).get("return_code") == 0
    return manifest


def _uart_text(manifest_path: Path) -> str:
    path = manifest_path.parent / "uart.log"
    assert path.is_file(), f"missing UART evidence: {path}"
    return path.read_text(encoding="utf-8", errors="replace")


def _emit_ota_uart(manifest_path: Path) -> str:
    text = _uart_text(manifest_path)
    print(f"\n===== Dual-bank OTA UART: {manifest_path.parent.name} =====")
    for line in text.splitlines():
        if "PQC_OTA_" in line or "PQC OTA:" in line:
            print(line)
    print("===== End Dual-bank OTA UART =====\n")
    return text


def _records(text: str, prefix: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for line in text.splitlines():
        marker = line.find(prefix)
        if marker < 0:
            continue
        fields: dict[str, str] = {}
        for token in line[marker + len(prefix):].strip().split():
            if "=" in token:
                key, value = token.split("=", 1)
                fields[key] = value
        records.append(fields)
    return records


def _first_phase(records: list[dict[str, str]], phase: str) -> dict[str, str]:
    for record in records:
        if record.get("phase") == phase:
            return record
    raise AssertionError(f"missing OTA UART phase {phase!r}; records={records}")


@pytest.fixture
def ota_hw_ready(pqc_require_capabilities):
    pqc_require_capabilities("local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware")
    if not _enabled():
        pytest.skip("set PQC_OTA_HW=1 to run destructive dual-bank OTA validation")


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_and_confirmation_hw(ota_hw_ready, tmp_path: Path):
    case = _require_env("PQC_OTA_HW_CASE")
    plan = _require_env("PQC_OTA_HW_APP_PLAN")
    completed, manifest_path = _run(case, plan, tmp_path / "app-update")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _emit_ota_uart(manifest_path)


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_unconfirmed_rollback_hw(ota_hw_ready, tmp_path: Path):
    case = _require_env("PQC_OTA_HW_CASE")
    plan = _require_env("PQC_OTA_HW_ROLLBACK_PLAN")
    completed, manifest_path = _run(case, plan, tmp_path / "rollback")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _emit_ota_uart(manifest_path)
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
    _emit_ota_uart(manifest_path)
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


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_explicit_bank_boot_and_confirmation_state_hw(ota_hw_ready, tmp_path: Path):
    """Prove bank/BFB2 swap, candidate wolfBoot/app execution and confirmation."""
    case = _require_env("PQC_OTA_HW_CASE")
    plan = _require_env("PQC_OTA_HW_APP_PLAN")
    completed, manifest_path = _run(case, plan, tmp_path / "state-proof-update")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    uart = _emit_ota_uart(manifest_path)
    boot = _records(uart, "PQC_OTA_BOOT")
    app = _records(uart, "PQC_OTA_APP")

    starts = [record for record in boot if record.get("phase") == "start"]
    assert len(starts) >= 2, f"expected pre/post-swap wolfBoot starts: {starts}"
    initial_bank = starts[0].get("active_bank")
    initial_bfb2 = starts[0].get("bfb2")
    candidate_start = next(
        (record for record in starts[1:] if record.get("active_bank") != initial_bank),
        None,
    )
    assert candidate_start is not None, f"active physical bank never changed: {starts}"
    candidate_bank = candidate_start.get("active_bank")
    assert candidate_start.get("bfb2") != initial_bfb2, f"BFB2 did not change: {starts}"

    manifest_auth = _first_phase(boot, "candidate_manifest_authenticated")
    image_auth = _first_phase(boot, "candidate_application_authenticated")
    swap = _first_phase(boot, "swap_requested")
    assert manifest_auth.get("target_bank") == candidate_bank
    assert image_auth.get("target_bank") == candidate_bank
    assert swap.get("from_bank") == initial_bank and swap.get("to_bank") == candidate_bank

    candidate_app = next(
        (record for record in app if record.get("phase") == "boot_state" and record.get("active_bank") == candidate_bank and record.get("staged") == "1" and record.get("booted") == "1"),
        None,
    )
    assert candidate_app is not None, f"candidate application execution not observed: {app}"
    confirmed = next(
        (record for record in app if record.get("phase") == "confirmed" and record.get("active_bank") == candidate_bank and record.get("confirmed") == "1"),
        None,
    )
    assert confirmed is not None, f"confirmation marker write not observed: {app}"


@pytest.mark.hardware
@pytest.mark.long
def test_unconfirmed_update_explicitly_returns_to_original_physical_bank_hw(ota_hw_ready, tmp_path: Path):
    """Prove an unconfirmed candidate swaps back to the original physical bank."""
    case = _require_env("PQC_OTA_HW_CASE")
    plan = _require_env("PQC_OTA_HW_ROLLBACK_PLAN")
    completed, manifest_path = _run(case, plan, tmp_path / "state-proof-rollback")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    uart = _emit_ota_uart(manifest_path)
    boot = _records(uart, "PQC_OTA_BOOT")
    app = _records(uart, "PQC_OTA_APP")

    starts = [record for record in boot if record.get("phase") == "start"]
    assert len(starts) >= 3, f"expected baseline, candidate and rollback wolfBoot starts: {starts}"
    original_bank = starts[0].get("active_bank")
    candidate_start = next(
        (record for record in starts[1:] if record.get("active_bank") != original_bank),
        None,
    )
    assert candidate_start is not None, f"candidate bank never became active: {starts}"
    candidate_bank = candidate_start.get("active_bank")

    withheld = next(
        (record for record in app if record.get("phase") == "confirmation_withheld" and record.get("active_bank") == candidate_bank),
        None,
    )
    assert withheld is not None, f"unconfirmed candidate execution not observed: {app}"
    rollback = _first_phase(boot, "rollback_requested")
    assert rollback.get("from_bank") == candidate_bank
    assert rollback.get("to_bank") == original_bank

    rollback_index = boot.index(rollback)
    restored = next(
        (record for record in boot[rollback_index + 1:] if record.get("phase") == "start" and record.get("active_bank") == original_bank),
        None,
    )
    assert restored is not None, f"original physical bank did not resume after rollback: {boot}"
