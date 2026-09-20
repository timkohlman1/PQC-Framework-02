from __future__ import annotations

import hashlib
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
from framework.hardware_test_support import HardwareFileRun, session_result_dir


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
    # The enclosing HardwareFileRun owns this directory, even for a failed run.
    # Persist the subprocess verdict before inspecting its result manifest.
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "experiment.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (results_dir / "experiment.stderr.log").write_text(completed.stderr, encoding="utf-8")
    (results_dir / "experiment.returncode.json").write_text(
        json.dumps({"return_code": completed.returncode, "command": command}, indent=2) + "\n",
        encoding="utf-8",
    )
    manifests = sorted(results_dir.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime_ns)
    assert manifests, f"experiment created no manifest; retained command evidence: {results_dir}"
    return completed, manifests[-1]


def _run_setup_command(command: list[str], *, evidence_dir: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_clean_subprocess_env(),
        text=True,
        capture_output=True,
        check=False,
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "command.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (evidence_dir / "command.stderr.log").write_text(completed.stderr, encoding="utf-8")
    (evidence_dir / "command.returncode.json").write_text(
        json.dumps({"return_code": completed.returncode, "command": command}, indent=2) + "\n",
        encoding="utf-8",
    )
    assert completed.returncode == 0, f"setup failed (rc={completed.returncode}); evidence: {evidence_dir}"
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
    evidence_dir: Path,
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
    _run_setup_command(command, evidence_dir=evidence_dir)
    plan = output_dir / "ota-plan.json"
    assert plan.is_file(), f"OTA setup did not create {plan}"
    return plan


def _prepare_fault_plan(*, source_plan: Path, fault: str, output_dir: Path, evidence_dir: Path) -> Path:
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
        ],
        evidence_dir=evidence_dir,
    )
    expected = output_dir / f"ota-plan-{fault}.json"
    assert expected.is_file(), f"OTA fault setup did not create {expected}"
    return expected


def _bootstrap_ota_hardware_context(workspace: Path) -> OtaHardwareContext:
    case = _materialize_dualbank_ota_case()
    (workspace / "resolved-case.yaml").write_bytes(case.read_bytes())

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
        evidence_dir=workspace / "preparation" / "app",
    )
    rollback_plan = _prepare_ota_plan(
        bootloader=bootloader,
        signed_application=signed_application,
        output_dir=plans_root / "rollback",
        evidence_dir=workspace / "preparation" / "rollback",
        test_no_confirm=True,
    )
    migration_plan = _prepare_ota_plan(
        bootloader=bootloader,
        signed_application=signed_application,
        output_dir=plans_root / "migration",
        evidence_dir=workspace / "preparation" / "migration",
        migration=True,
    )
    interrupted_plan = _prepare_fault_plan(
        source_plan=app_plan,
        fault="interrupted",
        output_dir=plans_root / "faults" / "interrupted",
        evidence_dir=workspace / "preparation" / "faults" / "interrupted",
    )
    corrupt_application_plan = _prepare_fault_plan(
        source_plan=app_plan,
        fault="corrupt-application",
        output_dir=plans_root / "faults" / "corrupt-application",
        evidence_dir=workspace / "preparation" / "faults" / "corrupt-application",
    )
    invalid_manifest_plan = _prepare_fault_plan(
        source_plan=app_plan,
        fault="invalid-manifest",
        output_dir=plans_root / "faults" / "invalid-manifest",
        evidence_dir=workspace / "preparation" / "faults" / "invalid-manifest",
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


def _assert_v7_boot_evidence(manifest_path: Path) -> list[dict[str, str]]:
    """Validate each completed STM32 reporting epoch in a successful OTA run.

    This proves that each published secure-boot image identity is attributed to
    the selected image within that epoch. The logical wolfBoot partition ID is
    deliberately not assumed to equal the physical MEMRMP bank number.
    """
    path = manifest_path.parent / "mqtt-reporting-raw.ndjson"
    assert path.is_file(), f"missing MQTT reporting evidence: {path}"
    chunks: dict[int, bytes] = {}
    selected: list[dict[str, str]] = []
    completed = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        envelope = json.loads(line)
        payload = envelope["payload"]
        if isinstance(payload, dict) and "payload" in payload:
            payload = payload["payload"]
        message = json.loads(payload) if isinstance(payload, str) else payload
        assert isinstance(message, dict), f"invalid MQTT payload at {path}:{line_number}"
        if message.get("source") != "stm32":
            continue
        kind = message.get("type")
        if kind == "chunk":
            sequence = int(message["sequence"])
            assert sequence not in chunks, f"duplicate chunk {sequence} in {path}"
            chunks[sequence] = bytes.fromhex(message["data_hex"])
        elif kind == "complete":
            count = int(message["chunk_count"])
            assert set(chunks) == set(range(count)), f"incomplete MQTT epoch in {path}"
            logical = b"".join(chunks[index] for index in range(count))
            assert hashlib.sha256(logical).hexdigest() == message["logical_sha256"], (
                f"MQTT completion hash mismatch in {path}"
            )
            assert len(logical) == int(message["logical_bytes"])
            lines = [item for item in logical.splitlines() if item.strip()]
            assert len(lines) == int(message["record_count"])
            records = [json.loads(item) for item in lines]
            evidence = [record["text"] for record in records if
                        record.get("context") == "secure_boot" and
                        isinstance(record.get("text"), str)]
            if evidence:
                image = _sole_boot_record(evidence, "PQC_SECURE_BOOT_IMAGE")
                verification = _sole_boot_record(evidence, "PQC_SECURE_BOOT_VERIFICATION")
                profile = _sole_boot_record(evidence, "PQC_SECURE_BOOT_PROFILE")
                total = _sole_boot_record(evidence, "PQC_SECURE_BOOT_TOTAL")
                assert profile.get("mailbox_version") == "8"
                assert image.get("mailbox_version") == "8"
                assert verification.get("mailbox_version") == "8"
                assert total.get("mailbox_version") == "8"
                assert verification.get("selected_image_valid") == "1"
                assert verification.get("measurement_valid") == "1"
                assert int(verification.get("cycles", "0")) > 0
                assert total.get("measurement_valid") == "1"
                assert image.get("identity_kind") == "wolfboot_verified_image_content_sha256"
                digest = image.get("image_sha256", "")
                assert len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)
                assert image.get("image_part") == verification.get("selected_image_part")
                assert image.get("image_fw_size_bytes") == verification.get("selected_image_fw_size_bytes")
                assert int(image["image_fw_size_bytes"]) > 0
                integrity = [ _boot_fields(text) for text in evidence if
                    text.startswith("PQC_SECURE_BOOT ") and
                    "verification_type=integrity_sha256 " in text ]
                assert len(integrity) == 1 and integrity[0].get("result") == "0"
                assert integrity[0].get("measurement_valid") == "1"
                assert int(integrity[0].get("cycles", "0")) > 0
                selected.append({**image, "epoch": str(completed)})
            completed += 1
            chunks.clear()
        else:
            raise AssertionError(f"unexpected STM32 result type {kind!r} in {path}")
    assert not chunks, f"unterminated MQTT result epoch in {path}"
    assert completed > 0 and selected, f"missing completed v7 boot evidence in {path}"
    return selected


def _boot_fields(text: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in text.split()[1:] if "=" in token)


def _sole_boot_record(evidence: list[str], prefix: str) -> dict[str, str]:
    matches = [text for text in evidence if text.startswith(prefix + " ")]
    assert len(matches) == 1, f"expected one {prefix}, found {len(matches)}"
    return _boot_fields(matches[0])


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


def _record_line(record: dict[str, str]) -> int:
    return int(record["__line_index"])


@pytest.fixture(scope="module")
def ota_test_workspace(pytestconfig):
    # The framework's persistent pytest session directory owns ALL experiment
    # outputs. Only generated configuration and build payloads are ephemeral.
    context = HardwareFileRun.create(
        repo_root=ROOT,
        session_result_dir=session_result_dir(pytestconfig),
        module_name="test_ota_dualbank_hw",
    )
    root = context.evidence_root / "preparation-and-baseline"
    root.mkdir(parents=True, exist_ok=False)
    holder: dict[str, OtaHardwareContext | None] = {"context": None}
    try:
        yield context, root, holder
    finally:
        # Never delete root or its evidence on success OR failure.
        shutil.rmtree(TEST_GENERATED_ROOT, ignore_errors=True)
        shutil.rmtree(TEST_BUILD_ROOT, ignore_errors=True)


@pytest.fixture
def ota_result_root(ota_test_workspace, request) -> Path:
    context, _, _ = ota_test_workspace
    # Each test (including each parametrized fault case) has its own evidence.
    result_root = context.evidence_root / "cases" / request.node.name
    result_root.mkdir(parents=True, exist_ok=False)
    return result_root


@pytest.fixture
def ota_hw_context(pqc_require_capabilities, ota_test_workspace) -> OtaHardwareContext:
    pqc_require_capabilities("local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware")
    _, root, holder = ota_test_workspace
    if holder["context"] is None:
        holder["context"] = _bootstrap_ota_hardware_context(root)
    assert holder["context"] is not None
    return holder["context"]


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_and_confirmation_hw(ota_hw_context: OtaHardwareContext, ota_result_root: Path):
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.app_plan, ota_result_root / "app-update")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _assert_v7_boot_evidence(manifest_path)
    _emit_ota_uart(manifest_path)


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_unconfirmed_rollback_hw(ota_hw_context: OtaHardwareContext, ota_result_root: Path):
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.rollback_plan, ota_result_root / "rollback")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _assert_v7_boot_evidence(manifest_path)
    _emit_ota_uart(manifest_path)
    recovered, recovered_manifest = _run(ota_hw_context.case, None, ota_result_root / "rollback-recovery")
    assert recovered.returncode == 0, recovered.stdout + "\n" + recovered.stderr
    _assert_v7_boot_evidence(recovered_manifest)


@pytest.mark.hardware
@pytest.mark.long
def test_bootloader_migration_and_recovery_hw(ota_hw_context: OtaHardwareContext, ota_result_root: Path):
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.migration_plan, ota_result_root / "migration")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _assert_v7_boot_evidence(manifest_path)
    _emit_ota_uart(manifest_path)
    recovered, recovered_manifest = _run(ota_hw_context.case, None, ota_result_root / "migration-postswap")
    assert recovered.returncode == 0, recovered.stdout + "\n" + recovered.stderr
    _assert_v7_boot_evidence(recovered_manifest)


@pytest.mark.hardware
@pytest.mark.long
@pytest.mark.parametrize(
    "plan_attribute",
    ("interrupted_plan", "corrupt_application_plan", "invalid_manifest_plan"),
)
def test_invalid_candidate_never_breaks_previous_bank_hw(
    ota_hw_context: OtaHardwareContext,
    ota_result_root: Path,
    plan_attribute: str,
):
    plan = getattr(ota_hw_context, plan_attribute)
    attempted, _ = _run(ota_hw_context.case, plan, ota_result_root / plan_attribute)
    assert attempted.returncode in {0, 10, 20, 30, 40}, attempted.stdout + "\n" + attempted.stderr
    recovered, recovered_manifest = _run(ota_hw_context.case, None, ota_result_root / f"{plan_attribute}-recovery")
    assert recovered.returncode == 0, recovered.stdout + "\n" + recovered.stderr
    _assert_v7_boot_evidence(recovered_manifest)


@pytest.mark.hardware
@pytest.mark.long
def test_application_update_explicit_bank_boot_and_confirmation_state_hw(
    ota_hw_context: OtaHardwareContext,
    ota_result_root: Path,
):
    """Prove physical-bank remap, candidate wolfBoot/app execution and confirmation."""
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.app_plan, ota_result_root / "state-proof-update")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _assert_v7_boot_evidence(manifest_path)
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

    # wolfBoot does not emit verification-result UART diagnostics in the
    # standard measurement build. Require the observable candidate-boot phase
    # here; _assert_v7_boot_evidence above checks verified-image and timing
    # records from completed application MQTT reporting epochs independently.
    boot = _records(uart, "PQC_OTA_BOOT")
    assert any(
        record.get("phase") == "candidate_first_boot"
        and record.get("active_bank") == candidate_bank
        and _record_line(activation) < _record_line(record) < _record_line(candidate_app)
        for record in boot
    ), "candidate first-boot transition was not observed after activation reset"

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
    ota_result_root: Path,
):
    """Prove an unconfirmed candidate swaps back to the original physical bank."""
    completed, manifest_path = _run(ota_hw_context.case, ota_hw_context.rollback_plan, ota_result_root / "state-proof-rollback")
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    _assert_delivery_manifest(manifest_path)
    _assert_v7_boot_evidence(manifest_path)
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

    # The normal wolfBoot build does not print cryptographic verification
    # results on UART. Check OTA transition order here and rely on the v7 MQTT
    # evidence asserted above for completed, successfully booted applications.
    boot = _records(uart, "PQC_OTA_BOOT")
    assert any(
        record.get("phase") == "candidate_first_boot"
        and record.get("active_bank") == candidate_bank
        and _record_line(activation) < _record_line(record) < _record_line(candidate_app)
        for record in boot
    ), "candidate first-boot transition was not observed"
    assert any(
        record.get("phase") == "rollback_requested"
        and record.get("from_bank") == candidate_bank
        and record.get("to_bank") == original_bank
        and _record_line(withheld) < _record_line(record) < _record_line(restored)
        for record in boot
    ), "rollback to the original bank was not observed"
