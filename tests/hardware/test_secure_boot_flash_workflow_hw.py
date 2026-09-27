from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from framework.config_resolver import ConfigResolver
from framework.hardware_test_support import HardwareFileRun, session_result_dir

# Resolve cases only after capability checks and per-test evidence creation.
SECURE_BOOT_PROFILE = "configs/secure_boot/ecdsa_p256.yaml"
WOLFBOOT_ARTIFACT = "tools/wolfboot/wolfboot.elf"
RELOCATED_APPLICATION_ELF = "build/Release/stm32_basic_hal1.elf"
SIGNED_APPLICATION_ARTIFACT = "build/Release/stm32_basic_hal1_v1_signed.bin"
EXPECTED_BOOT_MODE = "wolfboot_ecdsa_p256"
EXPECTED_BOOT_CRYPTO = "ecdsa_p256"

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_command(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    # This is a destructive real-hardware system workflow, not an isolated unit
    # test build. The subprocesses must therefore use normal experiment build
    # provenance so the immediately rebuilt ELF can be signed by the same
    # provenance guard used by the supported experiment-gateway run path.
    env = os.environ.copy()
    env["PQC_BUILD_PURPOSE"] = "experiment"
    env.pop("PQC_TEST_RESULT_DIR", None)
    return subprocess.run(
        args,
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _run_cli(
    repo_root: Path, args: list[str], *, evidence_dir: Path | None = None,
    stage: str = "command",
) -> subprocess.CompletedProcess[str]:
    """Retain subprocess output even when a CLI exits before creating a run manifest."""
    if evidence_dir is not None:
        evidence_dir.mkdir(parents=True, exist_ok=True)
    if evidence_dir is not None:
        (evidence_dir / f"{stage}.command.json").write_text(
            json.dumps({"arguments": ["scripts/experiment.py", *args]}, indent=2) + "\n",
            encoding="utf-8",
        )
    try:
        completed = _run_command(repo_root, [sys.executable, "scripts/experiment.py", *args])
    except OSError as exc:
        if evidence_dir is not None:
            (evidence_dir / f"{stage}.launch-error.log").write_text(
                "".join(traceback.format_exception(exc)), encoding="utf-8"
            )
        raise
    if evidence_dir is not None:
        (evidence_dir / f"{stage}.stdout.log").write_text(
            completed.stdout, encoding="utf-8", errors="replace"
        )
        (evidence_dir / f"{stage}.stderr.log").write_text(
            completed.stderr, encoding="utf-8", errors="replace"
        )
        (evidence_dir / f"{stage}.returncode.json").write_text(
            json.dumps({"return_code": completed.returncode}, indent=2) + "\n",
            encoding="utf-8",
        )
    return completed




def _result_log_context(results_dir: Path, filename: str) -> str:
    """Return the newest matching result log for assertion diagnostics."""

    if not results_dir.exists():
        return f"No {filename} was created under {results_dir}."

    candidates = sorted(
        results_dir.rglob(filename),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not candidates:
        return f"No {filename} was created under {results_dir}."

    log_path = candidates[0]
    try:
        content = log_path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Unable to read {log_path}: {exc}"
    return f"{log_path}:\n{content}"


def _owned_secure_boot_case(context: HardwareFileRun, algorithm: str) -> Path:
    """Resolve one canonical profile without modifying shared campaign state."""
    if algorithm not in ("ecdsa_p256", "integrity_sha256"):
        raise ValueError(f"unsupported hardware-test profile: {algorithm}")
    case_root = context.generated_root / f"secure_boot_{algorithm}"
    case_root.mkdir(parents=True, exist_ok=False)
    evidence = context.evidence_root / "configuration" / f"secure_boot_{algorithm}"
    evidence.mkdir(parents=True, exist_ok=False)
    source = context.repo_root / "configs/campaigns/secure_boot.yaml"
    campaign = yaml.safe_load(source.read_text(encoding="utf-8"))
    campaign["id"] = f"hw_secure_boot_{context.generated_root.name[:12]}_{algorithm}"
    campaign["matrix"] = {}
    campaign["fixed"]["secure_boot"] = algorithm
    campaign_path = case_root / "campaign.yaml"
    campaign_path.write_text(yaml.safe_dump(campaign, sort_keys=False), encoding="utf-8")
    (evidence / "campaign.yaml").write_bytes(campaign_path.read_bytes())
    generated = ConfigResolver(context.repo_root).materialize_campaign(
        campaign_path, case_root / "resolved"
    )
    cases = sorted((generated / "cases").glob("*.yaml"))
    assert len(cases) == 1, f"expected one case for {algorithm}: {cases}"
    resolved = ConfigResolver(context.repo_root).load_resolved_case(cases[0])
    assert resolved["choices"]["secure_boot"] == algorithm
    (evidence / "resolved-case.yaml").write_bytes(cases[0].read_bytes())
    (evidence / "campaign-resolved.yaml").write_bytes(
        (generated / "campaign-resolved.yaml").read_bytes()
    )
    return cases[0]


def _assert_flash_identity(manifest: dict) -> None:
    """Require recorded target identity without assuming a laboratory serial."""
    serial = manifest["secure_boot_flash"]["stlink_serial"]
    assert isinstance(serial, str) and serial.strip(), "missing recorded ST-LINK identity"


def _skip_if_missing(path: Path, reason: str) -> None:
    if not path.exists():
        pytest.skip(f"{reason}: {path}")


def _secure_boot_result_dirs(results_dir: Path, algorithm: str = EXPECTED_BOOT_CRYPTO) -> list[Path]:
    """Return result directories containing secure-boot execution manifests."""

    if not results_dir.exists():
        return []

    result_dirs: list[Path] = []
    for path in results_dir.iterdir():
        if not path.is_dir():
            continue

        manifest_path = path / "manifest.json"
        if not manifest_path.is_file():
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue

        if not isinstance(manifest, dict):
            continue
        if not isinstance(manifest.get("secure_boot_flash"), dict):
            continue
        if manifest.get("boot_mode") != f"wolfboot_{algorithm}":
            continue
        if manifest.get("boot_crypto") != algorithm:
            continue

        result_dirs.append(path)

    return sorted(result_dirs)


def _cli_result_dir(completed: subprocess.CompletedProcess[str], results_dir: Path) -> Path:
    """Use the result directory emitted by this exact CLI invocation.

    An integrity-only run uses wolfboot_integrity (not wolfboot_integrity_sha256).
    Finalized manifests use a compact evidence index. Neither should be
    discarded by a historical boot_mode/boot_crypto directory filter.
    """
    prefix = "Result directory: "
    paths = [line[len(prefix):].strip() for line in completed.stdout.splitlines()
             if line.startswith(prefix)]
    assert len(paths) == 1, (
        f"Expected one CLI result directory, found {paths}. "
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    path = Path(paths[0]).resolve()
    assert path.is_relative_to(results_dir.resolve()), (
        f"CLI result directory escaped requested results root: {path}"
    )
    assert (path / "manifest.json").is_file(), (
        f"Missing manifest for CLI invocation: {path}; stdout:\n{completed.stdout}"
    )
    return path


def _single_secure_boot_result_dir(results_dir: Path) -> Path:
    result_dirs = _secure_boot_result_dirs(results_dir)
    assert len(result_dirs) == 1
    return result_dirs[0]


def _prepare_instrumented_wolfboot(repo_root: Path, results_dir: Path, algorithm: str = EXPECTED_BOOT_CRYPTO, *, evidence_dir: Path | None = None, boot_uart_diagnostics: bool = False) -> None:
    build_completed = _run_cli(
        repo_root,
        [
            "build-wolfboot",
            "--boot-algorithm",
            algorithm,
            "--results-dir",
            str(results_dir),
        ] + (["--boot-uart-diagnostics"] if boot_uart_diagnostics else []),
        evidence_dir=evidence_dir, stage="wolfboot-build",
    )
    assert build_completed.returncode == 0, (
        f"build-wolfboot stdout:\n{build_completed.stdout}\n"
        f"build-wolfboot stderr:\n{build_completed.stderr}\n"
        f"wolfBoot build log:\n"
        f"{_result_log_context(results_dir, 'wolfboot_build.log')}"
    )
    assert (repo_root / WOLFBOOT_ARTIFACT).is_file(), (
        f"wolfBoot artifact absent after framework build; evidence: {results_dir}"
    )


def _prepare_signed_secure_boot_application(repo_root: Path, results_dir: Path, build_case: Path, algorithm: str = EXPECTED_BOOT_CRYPTO, *, evidence_dir: Path | None = None) -> None:
    build_completed = _run_cli(
        repo_root,
        [
            "build",
            "--experiment",
            str(build_case),
            "--results-dir",
            str(results_dir),
            "--configure-preset",
            "Release",
            "--build-preset",
            "Release",
            "--artifact",
            RELOCATED_APPLICATION_ELF,
            "--force",
        ],
        evidence_dir=evidence_dir, stage="application-build",
    )
    assert build_completed.returncode == 0, (
        f"framework build stdout:\n{build_completed.stdout}\n"
        f"framework build stderr:\n{build_completed.stderr}\n"
        f"firmware build log:\n"
        f"{_result_log_context(results_dir, 'build.log')}"
    )
    assert (repo_root / RELOCATED_APPLICATION_ELF).is_file()

    signing_completed = _run_cli(
        repo_root,
        [
            "sign-application",
            "--boot-algorithm",
            algorithm,
            "--results-dir",
            str(results_dir),
        ],
        evidence_dir=evidence_dir, stage="application-sign",
    )
    assert signing_completed.returncode == 0, (
        f"sign-application stdout:\n{signing_completed.stdout}\n"
        f"sign-application stderr:\n{signing_completed.stderr}\n"
        f"signing log:\n"
        f"{_result_log_context(results_dir, 'signing.log')}"
    )
    # The integrity-only profile has its own signed-package filename.
    signed_artifact = (
        SIGNED_APPLICATION_ARTIFACT
        if algorithm == EXPECTED_BOOT_CRYPTO
        else f"build/Release/stm32_basic_hal1_integrity_v1_signed.bin"
    )
    assert (repo_root / signed_artifact).is_file(), (
        f"Missing signed image for {algorithm}: {signed_artifact}\n"
        f"sign-application stdout:\n{signing_completed.stdout}"
    )


def _assert_positive_secure_boot_manifest(manifest: dict) -> None:
    """Check the finalized capture index, not discarded legacy metric sections."""
    assert manifest["run"]["state"] == "finalized"
    assert manifest["run"]["return_code"] == 0
    assert manifest["run"]["failure_stage"] == "none"
    assert manifest["execution_outcome"]["failure_stage"] == "none"
    assert manifest["execution_outcome"]["result"] == "secure_boot_positive_boot_evidence_passed"
    assert manifest["final_index"]["status"] == "finalized"


def _assert_positive_flash_evidence(
    completed: subprocess.CompletedProcess[str], result_dir: Path
) -> None:
    """Require CLI success and independent flash, signature and startup evidence."""
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0, (
        f"flash-secure-boot failed (return code {completed.returncode}): "
        f"{completed.stdout}\n{completed.stderr}"
    )
    _assert_positive_secure_boot_manifest(manifest)
    capture = json.loads(
        (result_dir / "secure-boot-flash-capture.json").read_text(encoding="utf-8")
    )
    assert capture.get("schema") == "pqc-secure-boot-flash-capture-v1"
    assert capture.get("boot_crypto") == EXPECTED_BOOT_CRYPTO
    assert capture.get("flash_return_code") == 0
    assert capture.get("capture_completed") is True
    assert capture.get("negative_requested") is False
    assert capture.get("boot_marker_present") is True
    assert capture.get("secure_boot_marker_present") is True
    assert capture.get("tick_present") is True
    assert capture.get("result") == "secure_boot_positive_boot_evidence_passed"
    uart = (result_dir / "uart.log").read_text(encoding="utf-8", errors="replace")
    for marker in (
        "wolfBoot integrity valid: 1",
        "wolfBoot integrity result: 0",
        "wolfBoot authenticity valid: 1",
        "wolfBoot authenticity result: 0",
        "stm32-basic_hal1 secure-boot app v0.1.0",
        "stm32-basic_hal1 boot v0.1.0",
    ):
        assert marker in uart, f"Missing current-run secure-boot evidence {marker!r}: {uart}"
    assert "[tick=" in uart
    flash_log = (result_dir / "secure_boot_flash.log").read_text(
        encoding="utf-8", errors="replace"
    )
    assert flash_log.count("Download verified successfully") >= 2, (
        "Missing successful bootloader/application flash verification in retained log"
    )
    artifacts = {item.get("artifact_id"): item for item in manifest.get("artifacts", [])}
    for artifact_id in ("wolfboot_image", "signed_application"):
        artifact = artifacts[artifact_id]
        assert artifact.get("acquisition", {}).get("status") == "available"
        digest = artifact.get("sha256")
        assert isinstance(digest, str) and len(digest) == 64
    assert (
        capture["negative_test"]["original_signed_application_sha256"]
        == artifacts["signed_application"]["sha256"]
    )


def _restore_valid_secure_boot_application(repo_root: Path, results_dir: Path, algorithm: str, experiment: Path | str, *, evidence_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        repo_root,
        [
            "flash-secure-boot",
            "--experiment",
            str(experiment),
            "--boot-algorithm",
            algorithm,
            "--results-dir",
            str(results_dir),
            "--uart-duration-seconds",
            "10",
        ],
        evidence_dir=evidence_dir, stage="restoration-flash",
    )


@pytest.mark.hardware
@pytest.mark.short
def test_secure_boot_build_sign_flash_uart_workflow(pytestconfig, pqc_require_capabilities):
    """Build, sign, flash, and UART-check the Phase 10h secure-boot workflow.

    This hardware-dependent system workflow auto-skips unless the local build
    toolchain, SSH gateway, configured flash helper, and configured ST-LINK VCP
    UART device are available. It builds the instrumented wolfBoot ELF, builds
    and signs the relocated HAL application, flashes both artifacts, captures
    UART, and verifies successful secure-boot startup.

    The test validates positive secure-boot evidence by requiring the distinct
    secure-boot application UART marker, the normal boot marker, the tick
    marker, and successful integrity/authenticity results after the two-artifact
    flash workflow. It does not require or claim a valid benchmark timing sample.
    """

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        "uart_device",
        strict_mode="hardware",
    )

    repo_root = _repo_root()
    context = HardwareFileRun.create(
        repo_root=repo_root,
        session_result_dir=session_result_dir(pytestconfig),
        module_name="test_secure_boot_flash_workflow_hw",
    )
    results_dir = context.evidence_root / "secure-boot-cli"
    results_dir.mkdir(parents=True, exist_ok=False)

    _skip_if_missing(repo_root / SECURE_BOOT_PROFILE, "canonical secure-boot profile is missing")

    build_case = context.case(template="baseline", case_name="build_provenance")
    experiment = _owned_secure_boot_case(context, EXPECTED_BOOT_CRYPTO)
    _prepare_instrumented_wolfboot(
        repo_root, results_dir, evidence_dir=context.evidence_root / "preparation"
    )
    _prepare_signed_secure_boot_application(
        repo_root, results_dir, build_case, evidence_dir=context.evidence_root / "preparation"
    )

    flash_completed = _run_cli(
        repo_root,
        [
            "flash-secure-boot",
            "--experiment",
            str(experiment),
            "--boot-algorithm",
            EXPECTED_BOOT_CRYPTO,
            "--results-dir",
            str(results_dir),
            "--uart-duration-seconds",
            "10",
        ],
        evidence_dir=context.evidence_root / "positive", stage="positive-flash",
    )
    result_dir = _cli_result_dir(flash_completed, results_dir)
    manifest_path = result_dir / "manifest.json"
    flash_log_path = result_dir / "secure_boot_flash.log"
    uart_log_path = result_dir / "uart.log"

    assert manifest_path.is_file()
    assert flash_log_path.is_file()
    assert uart_log_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    _assert_positive_flash_evidence(flash_completed, result_dir)

    flash_log = flash_log_path.read_text(encoding="utf-8")
    assert "wolfBoot secure-boot flash log" in flash_log
    assert "signed_application artifact" in flash_log
    assert "0x08020000" in flash_log

    uart_log = uart_log_path.read_text(encoding="utf-8")
    # uart.log is the raw device stream only. Framework-generated capture
    # metadata and interpreted timing/memory summaries must not be prepended.
    assert "UART post-flash capture log" not in uart_log
    assert "Pass/fail detection" not in uart_log
    assert "Boot timing evidence" not in uart_log
    assert "Runtime memory evidence" not in uart_log
    assert "stm32-basic_hal1" in uart_log

@pytest.mark.hardware
@pytest.mark.long
@pytest.mark.parametrize("algorithm", ["ecdsa_p256", "integrity_sha256"])
def test_secure_boot_negative_corrupted_application_then_restore_workflow(
    pytestconfig, pqc_require_capabilities, algorithm: str
):
    """Check that a corrupted application never starts; restore the valid image.

    wolfBoot has no UART output in the maintained measurement configuration.
    A complete, empty UART capture is expected when the corrupted application
    is not handed control; it is not a direct bootloader rejection trace.
    Flash/reset success, differing image hashes, and a fresh boot after restoring
    the matching valid image are required independent controls.

    A rejected application cannot publish MQTT evidence. Restoration requires
    CLI success and explicit application boot markers independently of timing.
    """
    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device",
        strict_mode="hardware",
    )
    repo_root = _repo_root()
    context = HardwareFileRun.create(
        repo_root=repo_root,
        session_result_dir=session_result_dir(pytestconfig),
        module_name="test_secure_boot_flash_workflow_hw",
    )
    results_dir = context.evidence_root / "secure-boot-cli"
    results_dir.mkdir(parents=True, exist_ok=False)
    build_case = context.case(template="baseline", case_name="build_provenance")
    experiment = _owned_secure_boot_case(context, algorithm)
    _skip_if_missing(repo_root / f"configs/secure_boot/{algorithm}.yaml", "secure-boot profile is missing")

    _prepare_instrumented_wolfboot(
        repo_root, results_dir, algorithm,
        evidence_dir=context.evidence_root / "preparation",
    )
    _prepare_signed_secure_boot_application(
        repo_root, results_dir, build_case, algorithm,
        evidence_dir=context.evidence_root / "preparation",
    )
    primary_error: BaseException | None = None
    try:
        negative_completed = _run_cli(
            repo_root,
            [
                "flash-secure-boot", "--experiment", str(experiment),
                "--boot-algorithm", algorithm,
                "--results-dir", str(results_dir),
                "--uart-duration-seconds", "10",
                "--negative-corrupt-application",
            ],
            evidence_dir=context.evidence_root / "negative", stage="negative-flash",
        )
        assert negative_completed.returncode == 0, (
            f"negative flash-secure-boot stdout:\n{negative_completed.stdout}\n"
            f"negative flash-secure-boot stderr:\n{negative_completed.stderr}\n"
            f"flash log:\n{_result_log_context(results_dir, 'secure_boot_flash.log')}"
        )
        result_dir = _cli_result_dir(negative_completed, results_dir)
        manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["execution_outcome"]["result"] == "secure_boot_negative_test_passed"
        capture = json.loads(
            (result_dir / "secure-boot-flash-capture.json").read_text(encoding="utf-8")
        )
        assert capture["result"] == "secure_boot_negative_test_passed"
        assert capture["boot_crypto"] == algorithm
        assert capture["flash_return_code"] == 0
        assert capture["negative_requested"] is True
        assert capture["negative_passed"] is True
        assert capture["capture_completed"] is True
        assert capture["boot_marker_present"] is False
        assert capture["tick_present"] is False
        assert capture["secure_boot_marker_present"] is False
        negative = capture["negative_test"]
        assert negative["enabled"] is True
        assert negative["source_image_modified"] is False
        original_hash = negative["original_signed_application_sha256"]
        corrupted_hash = negative["corrupted_signed_application_sha256"]
        assert isinstance(original_hash, str) and len(original_hash) == 64
        assert isinstance(corrupted_hash, str) and len(corrupted_hash) == 64
        assert original_hash != corrupted_hash
        uart_log = (result_dir / "uart.log").read_text(encoding="utf-8")
        # The bootloader intentionally does not initialise UART: an empty
        # capture is valid negative-path evidence when the flash/reset and
        # subsequent positive-control restoration checks also pass. Do not
        # require a wolfBoot diagnostic that this firmware cannot emit.
        assert "stm32-basic_hal1" not in uart_log, (
            f"Corrupted application emitted an application marker for {algorithm}:\n{uart_log}"
        )
        assert "UART post-flash capture log" not in uart_log
    except BaseException as exc:
        primary_error = exc
        (context.evidence_root / "negative" / "validation_failure.log").write_text(
            "".join(traceback.format_exception(exc)), encoding="utf-8"
        )
    try:
        # The firmware built and signed above belongs to this algorithm. Restore
        # with the matching bootloader and application even when rejection fails.
        restore_completed = _restore_valid_secure_boot_application(
            repo_root, results_dir, algorithm=algorithm, experiment=experiment,
            evidence_dir=context.evidence_root / "restoration",
        )
        restored_dir = _cli_result_dir(restore_completed, results_dir)
        assert restore_completed.returncode == 0, restore_completed.stdout + restore_completed.stderr
        restored_capture = json.loads(
            (restored_dir / "secure-boot-flash-capture.json").read_text(encoding="utf-8")
        )
        assert restored_capture["flash_return_code"] == 0, (
            f"Restoration flash failed: {restore_completed.stdout}\n{restore_completed.stderr}"
        )
        assert restored_capture["boot_crypto"] == algorithm
        restored_uart = (restored_dir / "uart.log").read_text(encoding="utf-8")
        assert "stm32-basic_hal1" in restored_uart, (
            f"No restored application UART boot marker for {algorithm}. "
            f"CLI return code={restore_completed.returncode}; UART:\n{restored_uart}"
        )
        # Verify the restored boot path independently of the CLI verdict.
        assert restored_capture["boot_marker_present"] is True
        assert restored_capture["secure_boot_marker_present"] is True
        assert restored_capture["tick_present"] is True

    except BaseException as restoration_error:
        (context.evidence_root / "restoration" / "validation_failure.log").write_text(
            "".join(traceback.format_exception(restoration_error)), encoding="utf-8"
        )
        if primary_error is not None:
            raise AssertionError(
                "negative-path validation AND restoration failed; "
                f"negative={primary_error!r}; restoration={restoration_error!r}; "
                f"retained evidence: {context.evidence_root}"
            ) from restoration_error
        raise
    if primary_error is not None:
        raise primary_error


@pytest.mark.hardware
@pytest.mark.parametrize("algorithm", ["integrity_sha256", "ecdsa_p256"])
def test_secure_boot_diagnostic_uart_rejected_image_then_restore(
    pytestconfig, pqc_require_capabilities, algorithm: str
):
    """Request 17: retain bootloader rejection diagnostics without an app boot."""
    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware"
    )
    repo_root = _repo_root()
    context = HardwareFileRun.create(
        repo_root=repo_root, session_result_dir=session_result_dir(pytestconfig),
        module_name="test_secure_boot_flash_workflow_hw",
    )
    results_dir = context.evidence_root / f"request17-diag-{algorithm}"
    results_dir.mkdir(parents=True, exist_ok=False)
    build_case = context.case(template="baseline", case_name=f"request17_{algorithm}_build")
    experiment = _owned_secure_boot_case(context, algorithm)

    _prepare_instrumented_wolfboot(
        repo_root, results_dir, algorithm,
        evidence_dir=context.evidence_root / "preparation", boot_uart_diagnostics=True,
    )
    _prepare_signed_secure_boot_application(
        repo_root, results_dir, build_case, algorithm,
        evidence_dir=context.evidence_root / "preparation",
    )
    try:
        completed = _run_cli(
            repo_root, [
                "flash-secure-boot", "--experiment", str(experiment),
                "--boot-algorithm", algorithm, "--results-dir", str(results_dir),
                "--uart-duration-seconds", "10", "--negative-corrupt-application",
                "--negative-corruption-method",
                "payload_byte_flip" if algorithm == "integrity_sha256" else "signature_byte_flip",
            ], evidence_dir=context.evidence_root / "negative", stage="diagnostic-negative",
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        result_dir = _cli_result_dir(completed, results_dir)
        uart = (result_dir / "uart.log").read_text(encoding="utf-8", errors="replace")
        assert "PQC_WOLFBOOT_DIAG event=bootloader_uart_ready" in uart
        assert "PQC_WOLFBOOT_DIAG event=image_selected partition=boot open_result=0" in uart
        assert "PQC_WOLFBOOT_DIAG event=handoff_refused" in uart
        assert "stm32-basic_hal1 secure-boot app" not in uart
        capture = json.loads(
            (result_dir / "secure-boot-flash-capture.json").read_text(encoding="utf-8")
        )
        negative = capture["negative_test"]
        assert isinstance(negative["corruption_offset"], int)
        assert negative["corruption_original_byte"] ^ 0x01 == negative["corruption_modified_byte"]

        if algorithm == "integrity_sha256":
            assert negative["method"] == "payload_byte_flip"
            assert negative["corruption_class"] == "integrity_verification"
            match = re.search(
                r"PQC_WOLFBOOT_DIAG event=verification_complete partition=boot type=integrity "
                r"result=(-?\d+) valid=0 cycles=(\d+) timing_valid=1", uart,
            )
            assert match is not None, uart
            assert int(match.group(1)) < 0
            assert int(match.group(2)) > 0
            assert "type=authenticity" not in uart
        else:
            assert negative["method"] == "signature_byte_flip"
            assert negative["corruption_class"] == "authenticity_verification"
            integrity = re.search(
                r"PQC_WOLFBOOT_DIAG event=verification_complete partition=boot type=integrity "
                r"result=0 valid=1 cycles=(\d+) timing_valid=1", uart,
            )
            authenticity = re.search(
                r"PQC_WOLFBOOT_DIAG event=verification_complete partition=boot type=authenticity "
                r"result=(-?\d+) valid=0 cycles=(\d+) timing_valid=1", uart,
            )
            assert integrity is not None, uart
            assert authenticity is not None, uart
            assert int(integrity.group(1)) > 0
            assert int(authenticity.group(1)) < 0
            assert int(authenticity.group(2)) > 0
    finally:
        restored = _restore_valid_secure_boot_application(
            repo_root, results_dir, algorithm=algorithm, experiment=experiment,
            evidence_dir=context.evidence_root / "restoration",
        )
        restored_dir = _cli_result_dir(restored, results_dir)
        assert restored.returncode == 0, restored.stdout + restored.stderr
        restored_uart = (restored_dir / "uart.log").read_text(encoding="utf-8", errors="replace")
        assert "stm32-basic_hal1 secure-boot app" in restored_uart
