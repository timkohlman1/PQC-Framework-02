from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TEST_GENERATED_ROOT = ROOT / ".pqc-generated-state" / "hardware-tests" / "dualbank-ota"
TEST_BUILD_ROOT = ROOT / "build" / "hardware-tests" / "dualbank-ota"
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.config_resolver import ConfigResolver


@dataclass(frozen=True)
class OtaHardwareContext:
    case: Path
    app_plan: Path
    rollback_plan: Path
    migration_plan: Path
    interrupted_plan: Path
    corrupt_application_plan: Path
    invalid_manifest_plan: Path


def _clean_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in list(env):
        if name.startswith("PQC_OTA_HW"):
            env.pop(name, None)
    env["PQC_BUILD_PURPOSE"] = "experiment"
    env.pop("PQC_TEST_RESULT_DIR", None)
    return env


def _run(case: Path | str, plan: Path | str | None, results_dir: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    command = [
        sys.executable,
        "scripts/experiment.py",
        "run",
        "--experiment",
        str(case),
        "--results-dir",
        str(results_dir),
    ]
    if plan is not None:
        command.extend(["--ota-plan", str(plan)])
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_clean_subprocess_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    manifests = sorted(results_dir.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime_ns)
    assert manifests, completed.stdout + "\n" + completed.stderr
    return completed, manifests[-1]


def _run_setup_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_clean_subprocess_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    return completed


def _materialize_dualbank_ota_case() -> Path:
    """Resolve a fresh OTA hardware case into the framework-required generated-state boundary."""
    resolver = ConfigResolver(ROOT)
    _, campaign = resolver.load_campaign("secure_boot")
    choices = dict(campaign["fixed"])
    choices.update(
        {
            "secure_boot": "ecdsa_p256",
            "firmware_mode": "dual_bank_ota",
            "standby_signing_keys": 0,
        }
    )
    selections = {
        "target": campaign["target"],
        "gateway": campaign["gateway"],
        "services": dict(campaign["services"]),
        "workload": campaign["workload"],
    }
    if campaign.get("instruments"):
        selections["instruments"] = campaign["instruments"]
    case = resolver.resolve_case(
        campaign_id="dualbank_ota_hardware",
        case_index=1,
        selections=selections,
        choices=choices,
        workload_overrides={},
        execution=dict(campaign["execution"]),
    )
    cases_dir = TEST_GENERATED_ROOT / "cases"
    shutil.rmtree(TEST_GENERATED_ROOT, ignore_errors=True)
    cases_dir.mkdir(parents=True, exist_ok=True)
    case_path = cases_dir / "0001_dualbank_ota_hardware.yaml"
    case_path.write_text(yaml.safe_dump(case, sort_keys=False), encoding="utf-8")
    return case_path


def _single_created_artifact(run_dir: Path, pattern: str, label: str) -> Path:
    matches = sorted(run_dir.glob(pattern))
    assert len(matches) == 1, f"expected exactly one {label} created by fresh baseline run, got: {matches}"
    return matches[0]


def _prepare_ota_plan(
    *,
    bootloader: Path,
    signed_application: Path,
    output_dir: Path,
    migration: bool = False,
    test_no_confirm: bool = False,
) -> Path:
    command = [
        sys.executable,
        "scripts/experiment.py",
        "ota-prepare",
        "--bootloader",
        str(bootloader),
        "--signed-application",
        str(signed_application),
        "--recovery-boot-algorithm",
        "ecdsa_p256",
        "--output-dir",
        str(output_dir),
    ]
    if migration:
        command.append("--migration")
    if test_no_confirm:
        command.append("--test-no-confirm")
    _run_setup_command(command)
    plan = output_dir / "ota-plan.json"
    assert plan.is_file(), f"OTA setup did not create {plan}"
    return plan


def _prepare_fault_plan(*, source_plan: Path, fault: str, output_dir: Path) -> Path:
    _run_setup_command(
        [
            sys.executable,
            "scripts/experiment.py",
            "ota-fault-plan",
            "--plan",
            str(source_plan),
            "--fault",
            fault,
            "--output-dir",
            str(output_dir),
        ]
    )
    expected = output_dir / f"ota-plan-{fault}.json"
    assert expected.is_file(), f"OTA fault setup did not create {expected}"
    return expected


def _bootstrap_ota_hardware_context(workspace: Path) -> OtaHardwareContext:
    case = _materialize_dualbank_ota_case()

    baseline_results = workspace / "baseline-results"
    baseline, manifest_path = _run(case, None, baseline_results)
    assert baseline.returncode == 0, baseline.stdout + "\n" + baseline.stderr
    run_dir = manifest_path.parent

    # These artifacts are selected only from the fresh baseline run created above;
    # no repository build output, prior results, or generated campaign state is used.
    bootloader = _single_created_artifact(
        run_dir,
        "prerequisites/wolfboot-builds/*/wolfboot.bin",
        "wolfBoot binary",
    )
    signed_application = _single_created_artifact(
        run_dir,
        "prerequisites/signing/*/application_ecdsa_p256.bin",
        "signed application",
    )

    # ota-prepare requires its generated signing payloads to be repository-relative.
    # scripts/dev.sh pytest-hardware overlays /workspace/build with an anonymous
    # Docker volume, so this path is repository-shaped but host-ephemeral.
    shutil.rmtree(TEST_BUILD_ROOT, ignore_errors=True)
    plans_root = TEST_BUILD_ROOT / "ota-plans"
    app_plan = _prepare_ota_plan(
        bootloader=bootloader,
        signed_application=signed_application,
        output_dir=plans_root / "app",
    )
    rollback_plan = _prepare_ota_plan(
        bootloader=bootloader,
        signed_application=signed_application,
        output_dir=plans_root / "rollback",
        test_no_confirm=True,
    )
    migration_plan = _prepare_ota_plan(
        bootloader=bootloader,
        signed_application=signed_application,
        output_dir=plans_root / "migration",
        migration=True,
    )
    interrupted_plan = _prepare_fault_plan(
        source_plan=app_plan,
        fault="interrupted",
        output_dir=plans_root / "faults" / "interrupted",
    )
    corrupt_application_plan = _prepare_fault_plan(
        source_plan=app_plan,
        fault="corrupt-application",
        output_dir=plans_root / "faults" / "corrupt-application",
    )
    invalid_manifest_plan = _prepare_fault_plan(
        source_plan=app_plan,
        fault="invalid-manifest",
        output_dir=plans_root / "faults" / "invalid-manifest",
    )
    return OtaHardwareContext(
        case=case,
        app_plan=app_plan,
        rollback_plan=rollback_plan,
        migration_plan=migration_plan,
        interrupted_plan=interrupted_plan,
        corrupt_application_plan=corrupt_application_plan,
        invalid_manifest_plan=invalid_manifest_plan,
    )


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
        if "PQC_OTA_" in line or "PQC OTA:" in line or "wolfBoot verification" in line:
            print(line)
    print("===== End Dual-bank OTA UART =====\n")
    return text


def _records(text: str, prefix: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for line_index, line in enumerate(text.splitlines()):
        marker = line.find(prefix)
        if marker < 0:
            continue
        fields: dict[str, str] = {}
        for token in line[marker + len(prefix):].strip().split():
            if "=" in token:
                key, value = token.split("=", 1)
                fields[key] = value
        fields["__line_index"] = str(line_index)
        records.append(fields)
    return records


def _first_phase(records: list[dict[str, str]], phase: str) -> dict[str, str]:
    for record in records:
        if record.get("phase") == phase:
            return record
    raise AssertionError(f"missing OTA UART phase {phase!r}; records={records}")


def _verification_result_lines(text: str) -> list[int]:
    return [
        index
        for index, line in enumerate(text.splitlines())
        if "wolfBoot verification result: 0" in line
    ]


def _record_line(record: dict[str, str]) -> int:
    return int(record["__line_index"])


@pytest.fixture(scope="module")
def ota_test_workspace(tmp_path_factory):
    # scripts/dev.sh pytest-hardware mounts anonymous Docker volumes at
    # /workspace/.pqc-generated-state and /workspace/build. The fixture uses
    # those normal framework paths. OTA plan/signing work uses the isolated
    # /workspace/build volume because ota-prepare requires repository-relative
    # generated payloads; run-result work remains under pytest temporary storage.
    # Docker --rm removes the isolated volumes when
    # the hardware-test container exits.
    root = tmp_path_factory.mktemp("dualbank-ota-self-contained")
    holder: dict[str, OtaHardwareContext | None] = {"context": None}
    try:
        yield root, holder
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(TEST_GENERATED_ROOT, ignore_errors=True)
        shutil.rmtree(TEST_BUILD_ROOT, ignore_errors=True)


@pytest.fixture
def ota_hw_context(pqc_require_capabilities, ota_test_workspace) -> OtaHardwareContext:
    pqc_require_capabilities("local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware")
    root, holder = ota_test_workspace
    if holder["context"] is None:
        holder["context"] = _bootstrap_ota_hardware_context(root)
    assert holder["context"] is not None
    return holder["context"]


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_and_confirmation_hw(ota_hw_context: OtaHardwareContext, tmp_path: Path):
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.app_plan, tmp_path / "app-update")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _emit_ota_uart(manifest_path)


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_unconfirmed_rollback_hw(ota_hw_context: OtaHardwareContext, tmp_path: Path):
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.rollback_plan, tmp_path / "rollback")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _emit_ota_uart(manifest_path)
    recovered, _ = _run(ota_hw_context.case, None, tmp_path / "rollback-recovery")
    assert recovered.returncode == 0, recovered.stdout + "\n" + recovered.stderr


@pytest.mark.hardware
@pytest.mark.long
def test_bootloader_migration_and_recovery_hw(ota_hw_context: OtaHardwareContext, tmp_path: Path):
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.migration_plan, tmp_path / "migration")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _emit_ota_uart(manifest_path)
    recovered, _ = _run(ota_hw_context.case, None, tmp_path / "migration-postswap")
    assert recovered.returncode == 0, recovered.stdout + "\n" + recovered.stderr


@pytest.mark.hardware
@pytest.mark.long
@pytest.mark.parametrize(
    "plan_attribute",
    ("interrupted_plan", "corrupt_application_plan", "invalid_manifest_plan"),
)
def test_invalid_candidate_never_breaks_previous_bank_hw(
    ota_hw_context: OtaHardwareContext,
    tmp_path: Path,
    plan_attribute: str,
):
    plan = getattr(ota_hw_context, plan_attribute)
    attempted, _ = _run(ota_hw_context.case, plan, tmp_path / plan_attribute)
    assert attempted.returncode in {0, 10, 20, 30, 40}, attempted.stdout + "\n" + attempted.stderr
    recovered, _ = _run(ota_hw_context.case, None, tmp_path / f"{plan_attribute}-recovery")
    assert recovered.returncode == 0, recovered.stdout + "\n" + recovered.stderr


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_explicit_bank_boot_and_confirmation_state_hw(
    ota_hw_context: OtaHardwareContext,
    tmp_path: Path,
):
    """Prove physical-bank remap, candidate wolfBoot/app execution and confirmation."""
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.app_plan, tmp_path / "state-proof-update")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    uart = _emit_ota_uart(manifest_path)
    app = _records(uart, "PQC_OTA_APP")

    request = _first_phase(app, "request_accepted")
    activation = _first_phase(app, "activation_reset")
    initial_bank = request.get("active_bank")
    initial_bfb2 = request.get("bfb2")
    assert initial_bank in {"1", "2"}
    assert initial_bfb2 in {"0", "1"}

    candidate_app = next(
        (record for record in app
         if record.get("phase") == "boot_state"
         and record.get("active_bank") != initial_bank
         and record.get("staged") == "1"
         and record.get("booted") == "1"),
        None,
    )
    assert candidate_app is not None, f"candidate application execution not observed: {app}"
    candidate_bank = candidate_app.get("active_bank")
    assert candidate_bank in {"1", "2"}
    assert candidate_bank != initial_bank, f"physical bank did not change: {app}"
    # active_bank is the live MEMRMP physical-bank mapping. BFB2 is the raw
    # FLASH option-bit observation and is retained as evidence, but it is not
    # required to differ at each runtime observation.
    assert candidate_app.get("bfb2") in {"0", "1"}

    verification_lines = _verification_result_lines(uart)
    assert any(
        _record_line(activation) < line < _record_line(candidate_app)
        for line in verification_lines
    ), "candidate wolfBoot verification success was not observed after activation reset"

    confirmed = next(
        (record for record in app
         if record.get("phase") == "confirmed"
         and record.get("active_bank") == candidate_bank
         and record.get("confirmed") == "1"),
        None,
    )
    assert confirmed is not None, f"confirmation marker write not observed: {app}"


@pytest.mark.hardware
@pytest.mark.long
def test_unconfirmed_update_explicitly_returns_to_original_physical_bank_hw(
    ota_hw_context: OtaHardwareContext,
    tmp_path: Path,
):
    """Prove an unconfirmed candidate swaps back to the original physical bank."""
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.rollback_plan, tmp_path / "state-proof-rollback")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    uart = _emit_ota_uart(manifest_path)
    app = _records(uart, "PQC_OTA_APP")

    request = _first_phase(app, "request_accepted")
    activation = _first_phase(app, "activation_reset")
    original_bank = request.get("active_bank")
    original_bfb2 = request.get("bfb2")
    assert original_bank in {"1", "2"}
    assert original_bfb2 in {"0", "1"}

    candidate_app = next(
        (record for record in app
         if record.get("phase") == "boot_state"
         and record.get("active_bank") != original_bank
         and record.get("staged") == "1"
         and record.get("booted") == "1"),
        None,
    )
    assert candidate_app is not None, f"candidate bank never became active: {app}"
    candidate_bank = candidate_app.get("active_bank")
    assert candidate_bank in {"1", "2"}
    assert candidate_bank != original_bank, f"candidate physical bank did not become active: {app}"
    assert candidate_app.get("bfb2") in {"0", "1"}

    withheld = next(
        (record for record in app
         if record.get("phase") == "confirmation_withheld"
         and record.get("active_bank") == candidate_bank),
        None,
    )
    assert withheld is not None, f"unconfirmed candidate execution not observed: {app}"

    restored = next(
        (record for record in app
         if record.get("phase") == "boot_state"
         and _record_line(record) > _record_line(withheld)
         and record.get("active_bank") == original_bank),
        None,
    )
    assert restored is not None, f"original physical bank did not resume after rollback: {app}"
    assert restored.get("active_bank") == original_bank
    assert restored.get("bfb2") in {"0", "1"}

    verification_lines = _verification_result_lines(uart)
    assert any(
        _record_line(activation) < line < _record_line(candidate_app)
        for line in verification_lines
    ), "candidate wolfBoot verification success was not observed"
    assert any(
        _record_line(withheld) < line < _record_line(restored)
        for line in verification_lines
    ), "restored-bank wolfBoot verification success was not observed"
