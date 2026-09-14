from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path


def write_minimal_elf32(path: Path) -> None:
    shstrtab = b"\x00.text\x00.data\x00.bss\x00.rodata\x00.shstrtab\x00"
    name_offsets = {
        ".text": shstrtab.index(b".text"),
        ".data": shstrtab.index(b".data"),
        ".bss": shstrtab.index(b".bss"),
        ".rodata": shstrtab.index(b".rodata"),
        ".shstrtab": shstrtab.index(b".shstrtab"),
    }
    text = b"T" * 11
    data = b"D" * 7
    rodata = b"R" * 3
    header_size = 52
    text_offset = header_size
    data_offset = text_offset + len(text)
    rodata_offset = data_offset + len(data)
    shstrtab_offset = rodata_offset + len(rodata)
    section_header_offset = shstrtab_offset + len(shstrtab)
    elf_ident = b"\x7fELF" + bytes([1, 1, 1]) + b"\x00" * 9
    header = struct.pack("<16sHHIIIIIHHHHHH", elf_ident, 2, 40, 1, 0, 0, section_header_offset, 0, header_size, 0, 0, 40, 6, 5)

    def section_header(name: str, section_type: int, flags: int, offset: int, size: int) -> bytes:
        return struct.pack("<IIIIIIIIII", name_offsets.get(name, 0), section_type, flags, 0, offset, size, 0, 0, 4, 0)

    path.write_bytes(
        header
        + text
        + data
        + rodata
        + shstrtab
        + b"".join(
            [
                section_header("", 0, 0, 0, 0),
                section_header(".text", 1, 0x6, text_offset, len(text)),
                section_header(".data", 1, 0x3, data_offset, len(data)),
                section_header(".bss", 8, 0x3, 0, 5),
                section_header(".rodata", 1, 0x2, rodata_offset, len(rodata)),
                section_header(".shstrtab", 3, 0, shstrtab_offset, len(shstrtab)),
            ]
        )
    )


def load_secure_boot_flash_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "secure_boot_flash.py"
    spec = importlib.util.spec_from_file_location("framework_secure_boot_flash", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_bundle():
    return {
        "experiment": {
            "id": "wolfboot_ecdsa_p256_uart",
            "board": "board_a",
            "host": "gateway",
            "boot": "wolfboot_ecdsa_p256",
            "boot_crypto": "ecdsa_p256",
            "firmware": {
                "mode": "wolfboot_ecdsa_p256",
                "artifact": "build/Release/stm32_basic_hal1_v1_signed.bin",
            },
            "uart": {
                "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
                "expected_tick_message": "tick",
                "expected_secure_boot_message": "stm32-basic_hal1 secure-boot app v0.1.0",
            },
            "secure_boot_benchmark_profile": {
                "profile_model": "configs/benchmarks/classical_signing_profiles.yaml",
                "profile_id": "ecc256_reference",
                "algorithm": "ECC256",
                "wolfboot_sign": "ECC256",
                "signature_algorithm": "ecdsa_p256",
                "curve": "P-256",
                "key_size_bits": 256,
                "signature_size_bytes": 64,
                "image_version": 1,
                "runnable": True,
                "status": "reference_existing_phase_10_11_profile",
                "signing_profile": "configs/secure_boot/ecdsa_p256.yaml",
                "wolfboot_build_profile": "configs/secure_boot/ecdsa_p256.yaml",
                "experiment_profile": "configs/campaigns/secure_boot.yaml",
                "boot_profile": "configs/secure_boot/ecdsa_p256.yaml",
                "minimum_scope_status": "defined_phase_11_5a_minimum_classical_scope",
                "ed25519_status": "planned_phase_11_5b_not_implemented",
                "rsa2048_status": "planned_phase_11_5c_not_implemented",
                "application_payload": "same_relocated_hal_application_payload",
                "board": "board_a",
                
                "measurement_method": "uart_explicit_wolfboot_mailbox_markers",
                "repeated_run_model": "phase_11_2_repeat_count_samples",
                "static_metrics_model": "phase_11_3_elf_and_artifact_metrics",
                "runtime_memory_model": "phase_11_4_firmware_side_stack_high_water_marker",
            },
            "secure_boot_flash": {
                "signature_algorithm": "ecdsa_p256",
                "signature_size_bytes": 64,
                "image_version": 1,
                "wolfboot_artifact": "tools/wolfboot/wolfboot.elf",
                "wolfboot_offset": "0x08000000",
                "wolfboot_pass_offset_to_helper": False,
                "unsigned_application_artifact": "build/Release/stm32_basic_hal1.bin",
                "signed_application_artifact": "build/Release/stm32_basic_hal1_v1_signed.bin",
                "signed_application_offset": "0x08020000",
                "signed_application_pass_offset_to_helper": True,
            },
        },
        "board": {
            "id": "board_a",
            "stlink": {"serial": "066EFF3932504E3043111818"},
        },
        "host": {
            "id": "gateway",
            "alias": "pqc-gateway1",
            "user": "timk",
            "flash": {"helper": "flash-stm32a"},
        },
        "boot": {
            "id": "wolfboot_ecdsa_p256",
            "mode": "wolfboot_ecdsa_p256",
        },
    }


def write_manifest(result_dir: Path):
    result_dir.mkdir(parents=True)
    repo_root = result_dir.parent.parent / "repo"
    from framework.generated_state import build_identity, record_generated_state_success
    wolfboot = repo_root / "tools" / "wolfboot" / "wolfboot.elf"
    signed = repo_root / "build" / "Release" / "stm32_basic_hal1_v1_signed.bin"
    if wolfboot.is_file():
        record_generated_state_success(
            repo_root=repo_root, scope="wolfboot-test",
            identity=build_identity(workflow="wolfboot_build", profile="test", input_fingerprint={"fingerprint":"test"}, toolchain={"command":["make"]}, execution={"host_system":"test"}),
            artifacts=[wolfboot],
        )
    if signed.is_file():
        record_generated_state_success(
            repo_root=repo_root, scope="signing-test",
            identity=build_identity(workflow="application_signing", profile="test", input_fingerprint={"fingerprint":"test"}, toolchain={"command":["sign"]}, execution={"host_system":"test"}),
            artifacts=[signed],
        )
    (result_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": result_dir.name,
                "result": "pending",
                "experiment": "wolfboot_ecdsa_p256_uart",
                "boot_mode": "wolfboot_ecdsa_p256",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_constructs_secure_boot_scp_and_flash_commands(tmp_path):
    secure_flash = load_secure_boot_flash_module()
    artifact = tmp_path / "wolfboot.elf"

    assert secure_flash.construct_scp_command(
        artifact,
        "pqc-gateway1",
        "/tmp/run_wolfboot.elf",
    ) == ["scp", str(artifact), "pqc-gateway1:/tmp/run_wolfboot.elf"]

    assert secure_flash.construct_ssh_flash_command(
        "pqc-gateway1",
        "flash-stm32a",
        "/tmp/wolfboot.elf",
        "0x08000000",
        pass_offset_to_helper=False,
    ) == ["ssh", "pqc-gateway1", "flash-stm32a /tmp/wolfboot.elf"]

    assert secure_flash.construct_ssh_flash_command(
        "pqc-gateway1",
        "flash-stm32a",
        "/tmp/application_signed.bin",
        "0x08020000",
        pass_offset_to_helper=True,
    ) == [
        "ssh",
        "pqc-gateway1",
        "flash-stm32a /tmp/application_signed.bin 0x08020000",
    ]


def test_execute_secure_boot_flash_flashes_wolfboot_then_signed_application_and_updates_manifest(tmp_path):
    secure_flash = load_secure_boot_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-29_001_wolfboot_ecdsa_p256_uart"
    wolfboot_artifact = repo_root / "tools" / "wolfboot" / "wolfboot.elf"
    unsigned_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1.bin"
    signed_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1_v1_signed.bin"
    wolfboot_artifact.parent.mkdir(parents=True)
    signed_artifact.parent.mkdir(parents=True)
    write_minimal_elf32(wolfboot_artifact)
    unsigned_artifact.write_bytes(b"unsigned app")
    signed_artifact.write_bytes(b"unsigned app" + b"S" * 64)
    write_manifest(result_dir)

    calls = []

    def fake_runner(command, cwd):
        assert cwd == repo_root
        calls.append(command)
        return secure_flash.CommandExecution(command, 0, "ok", "", 0.1)

    def fake_git_runner(command, cwd):
        if command == ["git", "rev-parse", "HEAD"]:
            return secure_flash.GitCommandExecution(command, 0, "abc123\n", "", 0.01)
        if command == ["git", "status", "--short"]:
            return secure_flash.GitCommandExecution(command, 0, "", "", 0.01)
        raise AssertionError(f"unexpected git command: {command}")

    result = secure_flash.execute_secure_boot_flash(
        sample_bundle(),
        repo_root,
        result_dir,
        fake_runner,
        fake_git_runner,
    )

    wolfboot_sha = hashlib.sha256(wolfboot_artifact.read_bytes()).hexdigest()
    signed_sha = hashlib.sha256(b"unsigned app" + b"S" * 64).hexdigest()

    assert result.return_code == 0
    assert result.failure_stage == "none"
    assert calls == [
        ["scp", str(wolfboot_artifact), f"timk@pqc-gateway1:/tmp/{result_dir.name}_wolfboot_wolfboot.elf"],
        ["ssh", "timk@pqc-gateway1", f"flash-stm32a /tmp/{result_dir.name}_wolfboot_wolfboot.elf"],
        ["scp", str(signed_artifact), f"timk@pqc-gateway1:/tmp/{result_dir.name}_signed_application_stm32_basic_hal1_v1_signed.bin"],
        ["ssh", "timk@pqc-gateway1", f"flash-stm32a /tmp/{result_dir.name}_signed_application_stm32_basic_hal1_v1_signed.bin 0x08020000"],
    ]

    log = (result_dir / "secure_boot_flash.log").read_text(encoding="utf-8")
    assert "wolfBoot secure-boot flash log" in log
    assert "wolfboot artifact" in log
    assert "signed_application artifact" in log
    assert wolfboot_sha in log
    assert signed_sha in log

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result"] == "secure_boot_flash_passed"
    assert manifest["boot_crypto"] == "ecdsa_p256"
    assert manifest["signature_size"] == 64
    assert manifest["boot_signature"] == {
        "algorithm": "ecdsa_p256",
        "signature_size": 64,
        "signature_size_bytes": 64,
        "image_version": 1,
    }
    assert manifest["firmware"]["sha256"] == signed_sha
    assert manifest["secure_boot_flash"]["return_code"] == 0
    assert manifest["secure_boot_flash"]["wolfboot"]["sha256"] == wolfboot_sha
    assert manifest["secure_boot_flash"]["wolfboot"]["offset"] == "0x08000000"
    assert manifest["secure_boot_flash"]["signed_application"]["sha256"] == signed_sha
    assert manifest["secure_boot_flash"]["negative_test"]["enabled"] is False
    assert manifest["secure_boot_flash"]["negative_test"]["source_image_modified"] is False
    assert manifest["secure_boot_flash"]["signed_application"]["offset"] == "0x08020000"
    assert manifest["secure_boot_flash"]["signed_application"]["pass_offset_to_helper"] is True
    freshness = manifest["secure_boot_flash"]["artifact_freshness"]
    assert freshness["artifact_freshness_status"] == "recorded_not_enforced"
    assert freshness["artifacts"]["wolfboot"]["sha256"] == wolfboot_sha
    assert freshness["artifacts"]["signed_application"]["sha256"] == signed_sha
    assert "scripts/framework/secure_boot_flash.py" in freshness["requested_fingerprint_inputs"]
    assert "scripts/framework/wolfboot_build.py" in freshness["requested_fingerprint_inputs"]
    assert "scripts/framework/signing.py" in freshness["requested_fingerprint_inputs"]
    assert "configs/targets/stm32l4r5_wolfboot.yaml" in freshness["requested_fingerprint_inputs"]
    assert "configs/secure_boot/ecdsa_p256.yaml" in freshness["requested_fingerprint_inputs"]
    assert "STM32L4R5XX_FLASH_RELOCATED.ld" in freshness["requested_fingerprint_inputs"]
    assert list(freshness["fingerprint_file_hashes"]) == freshness["fingerprint_inputs"]
    evidence = manifest["secure_boot_evidence"]
    assert evidence["schema_version"] == 1
    assert evidence["boot_mode"] == "wolfboot_ecdsa_p256"
    assert evidence["boot_crypto"] == "ecdsa_p256"
    assert evidence["signature_algorithm"] == "ecdsa_p256"
    assert evidence["signature_size"] == 64
    assert evidence["build_evidence"]["wolfboot_sha256"] == wolfboot_sha
    assert evidence["signing_evidence"]["signed_application_sha256"] == signed_sha
    assert evidence["artifact_freshness"]["artifact_freshness_status"] == "recorded_not_enforced"
    assert evidence["flash_evidence"]["return_code"] == 0
    assert evidence["uart_evidence"]["skipped"] is True
    assert evidence["boot_timing"]["derived_verification_time_ms"] is None
    benchmark = manifest["secure_boot_benchmark"]
    assert benchmark["schema_version"] == 1
    assert benchmark["model_phase"] == "phase_11_5a_classical_profile_model"
    assert benchmark["benchmark_scope"] == "secure_boot_classical_signing_algorithm"
    assert benchmark["profile_id"] == "wolfboot_ecdsa_p256_uart"
    assert benchmark["signature_algorithm"] == "ecdsa_p256"
    assert benchmark["signature_size_bytes"] == 64
    assert benchmark["classical_profile_metadata"]["profile_id"] == "ecc256_reference"
    assert benchmark["classical_profile_metadata"]["minimum_comparison_scope"]["required_algorithms"] == ["ED25519", "ECC256", "RSA2048"]
    assert benchmark["classical_profile_metadata"]["capability_status"]["ed25519"]["runnable"] is True
    assert benchmark["classical_profile_metadata"]["capability_status"]["rsa2048"]["runnable"] is True
    assert benchmark["classical_profile_metadata"]["capability_status"]["ecc384"]["runnable"] is True
    assert benchmark["classical_profile_metadata"]["capability_status"]["ecc521"]["runnable"] is True
    assert benchmark["classical_profile_metadata"]["capability_status"]["ed448"]["runnable"] is True
    assert benchmark["classical_profile_metadata"]["capability_status"]["rsa3072"]["runnable"] is True
    assert benchmark["classical_profile_metadata"]["capability_status"]["rsa4096"]["runnable"] is True
    assert benchmark["build_time_metrics"]["status"] == "available"
    assert benchmark["build_time_metrics"]["bootloader_text_bytes"] == 11
    assert benchmark["build_time_metrics"]["bootloader_data_bytes"] == 7
    assert benchmark["build_time_metrics"]["bootloader_bss_bytes"] == 5
    assert benchmark["build_time_metrics"]["bootloader_flash_bytes"] == 21
    assert benchmark["build_time_metrics"]["bootloader_static_ram_bytes"] == 12
    assert benchmark["signed_artifact_metrics"]["status"] == "available"
    assert benchmark["signed_artifact_metrics"]["wolfboot_elf_size_bytes"] == wolfboot_artifact.stat().st_size
    assert benchmark["signed_artifact_metrics"]["signed_application_size_bytes"] == len(b"unsigned app" + b"S" * 64)
    assert benchmark["signed_artifact_metrics"]["unsigned_application_size_bytes"] == len(b"unsigned app")
    assert benchmark["signed_artifact_metrics"]["signed_image_overhead_bytes"] == 64
    assert benchmark["signed_artifact_metrics"]["unsigned_application_size_unavailable"] is None
    assert benchmark["runtime_verification_metrics"]["status"] == "unavailable"
    assert benchmark["runtime_verification_metrics"]["derived_verification_time_ms"] is None
    assert benchmark["runtime_memory_metrics"]["status"] == "unavailable"
    assert benchmark["repeated_run_samples"]["status"] == "not_configured"
    assert benchmark["repeated_run_samples"]["samples"] == []
    assert benchmark["aggregate_statistics"]["status"] == "unavailable"
    assert benchmark["aggregate_statistics"]["derived_verification_time_ms"]["median"] is None
    assert manifest["source"] == {
        "git_commit": "abc123",
        "git_dirty": False,
        "git_status_available": True,
    }


def test_execute_secure_boot_flash_refuses_mismatched_local_signing_keys_before_network(tmp_path):
    secure_flash = load_secure_boot_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    wolfboot_artifact = repo_root / "tools" / "wolfboot" / "wolfboot.elf"
    unsigned_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1.bin"
    signed_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1_v1_signed.bin"
    signing_key = repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"
    wolfboot_key = repo_root / "tools" / "wolfboot" / "wolfboot_signing_private_key.der"
    wolfboot_artifact.parent.mkdir(parents=True)
    signed_artifact.parent.mkdir(parents=True)
    signing_key.parent.mkdir(parents=True)
    wolfboot_key.parent.mkdir(parents=True, exist_ok=True)
    write_minimal_elf32(wolfboot_artifact)
    unsigned_artifact.write_bytes(b"unsigned app")
    signed_artifact.write_bytes(b"unsigned app" + b"S" * 64)
    signing_key.write_bytes(b"application signing key")
    wolfboot_key.write_bytes(b"different wolfboot key")
    write_manifest(result_dir)

    bundle = sample_bundle()
    bundle["experiment"]["secure_boot_flash"]["signing_private_key"] = "secrets/wolfboot/ecdsa_p256_private_key.der"
    bundle["experiment"]["secure_boot_flash"]["wolfboot_private_key"] = "tools/wolfboot/wolfboot_signing_private_key.der"

    def forbidden_runner(command, cwd):
        raise AssertionError("network commands must not run when secure-boot key evidence mismatches")

    result = secure_flash.execute_secure_boot_flash(
        bundle,
        repo_root,
        result_dir,
        forbidden_runner,
    )

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    key_consistency = manifest["secure_boot_flash"]["key_consistency"]
    assert result.return_code == secure_flash.SECURE_BOOT_KEY_MISMATCH_RETURN_CODE
    assert result.failure_stage == "signing_key_consistency"
    assert key_consistency["status"] == "mismatch_refused"
    assert key_consistency["signing_private_key_sha256"] != key_consistency["wolfboot_private_key_sha256"]
    assert key_consistency["key_material_copied_to_results"] is False
    assert manifest["secure_boot_evidence"]["signing_evidence"]["key_consistency"]["status"] == "mismatch_refused"


def test_execute_secure_boot_flash_refuses_missing_wolfboot_without_network(tmp_path):
    secure_flash = load_secure_boot_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    signed_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1_v1_signed.bin"
    unsigned_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1.bin"
    signed_artifact.parent.mkdir(parents=True)
    unsigned_artifact.write_bytes(b"unsigned app")
    signed_artifact.write_bytes(b"unsigned app" + b"S" * 64)
    write_manifest(result_dir)

    def forbidden_runner(command, cwd):
        raise AssertionError("network commands must not run when a required artifact is missing")

    result = secure_flash.execute_secure_boot_flash(
        sample_bundle(),
        repo_root,
        result_dir,
        forbidden_runner,
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == secure_flash.SECURE_BOOT_ARTIFACT_MISSING_RETURN_CODE
    assert result.failure_stage == "wolfboot_artifact"
    assert result.wolfboot.scp is None
    assert result.signed_application.scp is None
    assert manifest["result"] == "secure_boot_flash_failed"
    assert manifest["secure_boot_flash"]["failure_stage"] == "wolfboot_artifact"


def test_execute_secure_boot_flash_stops_before_application_when_wolfboot_flash_fails(tmp_path):
    secure_flash = load_secure_boot_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    wolfboot_artifact = repo_root / "tools" / "wolfboot" / "wolfboot.elf"
    unsigned_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1.bin"
    signed_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1_v1_signed.bin"
    wolfboot_artifact.parent.mkdir(parents=True)
    signed_artifact.parent.mkdir(parents=True)
    write_minimal_elf32(wolfboot_artifact)
    unsigned_artifact.write_bytes(b"unsigned app")
    signed_artifact.write_bytes(b"unsigned app" + b"S" * 64)
    write_manifest(result_dir)
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        if len(calls) == 2:
            return secure_flash.CommandExecution(command, 77, "", "flash failed", 0.1)
        return secure_flash.CommandExecution(command, 0, "", "", 0.1)

    result = secure_flash.execute_secure_boot_flash(
        sample_bundle(),
        repo_root,
        result_dir,
        fake_runner,
    )

    assert result.return_code == 77
    assert result.failure_stage == "wolfboot_flash"
    assert len(calls) == 2
    assert result.signed_application.scp is None
    assert result.signed_application.flash is None


def test_execute_secure_boot_flash_negative_test_flashes_corrupted_copy_without_modifying_source(tmp_path):
    secure_flash = load_secure_boot_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "2026-06-30_001_wolfboot_ecdsa_p256_uart"
    wolfboot_artifact = repo_root / "tools" / "wolfboot" / "wolfboot.elf"
    unsigned_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1.bin"
    signed_artifact = repo_root / "build" / "Release" / "stm32_basic_hal1_v1_signed.bin"
    wolfboot_artifact.parent.mkdir(parents=True)
    signed_artifact.parent.mkdir(parents=True)
    write_minimal_elf32(wolfboot_artifact)
    unsigned_artifact.write_bytes(b"unsigned app")
    signed_artifact.write_bytes(b"unsigned app" + b"S" * 64)
    original_signed_bytes = signed_artifact.read_bytes()
    write_manifest(result_dir)

    bundle = sample_bundle()
    bundle["experiment"]["secure_boot_flash"]["negative_test_corrupt_application"] = True
    bundle["experiment"]["secure_boot_flash"]["corruption_method"] = "flip_first_byte"
    bundle["experiment"]["secure_boot_flash"]["corrupted_application_artifact"] = "corrupted_application_signed.bin"

    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        return secure_flash.CommandExecution(command, 0, "ok", "", 0.1)

    result = secure_flash.execute_secure_boot_flash(
        bundle,
        repo_root,
        result_dir,
        fake_runner,
    )

    corrupted_path = result_dir / "corrupted_application_signed.bin"
    assert result.return_code == 0
    assert result.negative_test_enabled is True
    assert corrupted_path.is_file()
    assert signed_artifact.read_bytes() == original_signed_bytes
    assert corrupted_path.read_bytes() != original_signed_bytes
    assert result.corrupted_signed_application_path == corrupted_path
    assert calls[2] == [
        "scp",
        str(corrupted_path),
        f"timk@pqc-gateway1:/tmp/{result_dir.name}_signed_application_corrupted_application_signed.bin",
    ]

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    negative = manifest["secure_boot_flash"]["negative_test"]
    assert negative["enabled"] is True
    assert negative["method"] == "flip_first_byte"
    assert negative["source_image_modified"] is False
    assert negative["original_signed_application_path"] == str(signed_artifact)
    assert negative["corrupted_signed_application_path"] == str(corrupted_path)
    assert negative["original_signed_application_sha256"] != negative["corrupted_signed_application_sha256"]


def load_uart_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "uart.py"
    spec = importlib.util.spec_from_file_location("framework_uart", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_uart_parses_explicit_runtime_stack_high_water_marker_only():
    uart = load_uart_module()

    output = """
    wolfBoot verification cycles: 1360000 cycles
    wolfBoot clock sysclk_hz: 80000000
    wolfBoot clock hclk_hz: 80000000
    wolfBoot clock pclk1_hz: 80000000
    wolfBoot clock pclk2_hz: 80000000
    wolfBoot verification cycles: 1360000 cycles
    wolfBoot verification max stack used: 2048 bytes
    """

    assert uart.parse_max_stack_used_bytes(output) == 2048
    assert uart.parse_max_stack_used_bytes("capture duration: 10 seconds") is None
    assert uart.parse_heap_used_bytes("wolfBoot verification heap used: 512 bytes") == 512
    assert (
        uart.parse_heap_used_bytes(
            "FreeRTOS scheduler starting: heap_bytes=40000 "
            "default_task_stack_words=512"
        )
        is None
    )



def test_classical_profile_metadata_marks_ed25519_runnable_for_phase_11_5b():
    secure_flash = load_secure_boot_flash_module()
    bundle = sample_bundle()
    experiment = bundle["experiment"]
    experiment["id"] = "wolfboot_ed25519_uart"
    experiment["boot"] = "wolfboot_ed25519"
    experiment["boot_crypto"] = "ed25519"
    experiment["firmware"]["mode"] = "wolfboot_ed25519"
    experiment["firmware"]["artifact"] = "build/Release/stm32_basic_hal1_ed25519_v1_signed.bin"
    experiment["secure_boot_benchmark_profile"].update(
        {
            "profile_id": "ed25519_benchmark",
            "algorithm": "ED25519",
            "wolfboot_sign": "ED25519",
            "signature_algorithm": "ed25519",
            "status": "configured_phase_11_5b_ed25519_profile",
            "signing_profile": "configs/secure_boot/ed25519.yaml",
            "wolfboot_build_profile": "configs/secure_boot/ed25519.yaml",
            "experiment_profile": "configs/campaigns/secure_boot.yaml",
            "boot_profile": "configs/secure_boot/ed25519.yaml",
            "ed25519_status": "configured_phase_11_5b_runnable_profile_not_hardware_validated",
        }
    )

    metadata = secure_flash._classical_profile_metadata(experiment)

    assert metadata["model_phase"] == "phase_11_5b_ed25519_profile"
    assert metadata["algorithm"] == "ED25519"
    assert metadata["signature_algorithm"] == "ed25519"
    assert metadata["capability_status"]["ed25519"]["runnable"] is True
    assert metadata["capability_status"]["rsa2048"]["runnable"] is True


def test_classical_profile_metadata_marks_rsa2048_runnable_for_phase_11_5c():
    secure_flash = load_secure_boot_flash_module()
    bundle = sample_bundle()
    experiment = bundle["experiment"]
    experiment["id"] = "wolfboot_rsa2048_uart"
    experiment["boot"] = "wolfboot_rsa2048"
    experiment["boot_crypto"] = "rsa2048"
    experiment["firmware"]["mode"] = "wolfboot_rsa2048"
    experiment["firmware"]["artifact"] = "build/Release/stm32_basic_hal1_rsa2048_v1_signed.bin"
    experiment["secure_boot_benchmark_profile"].update(
        {
            "profile_id": "rsa2048_benchmark",
            "algorithm": "RSA2048",
            "wolfboot_sign": "RSA2048",
            "signature_algorithm": "rsa2048",
            "key_size_bits": 2048,
            "signature_size_bytes": 256,
            "status": "configured_phase_11_5c_rsa2048_profile",
            "signing_profile": "configs/secure_boot/rsa2048.yaml",
            "wolfboot_build_profile": "configs/secure_boot/rsa2048.yaml",
            "experiment_profile": "configs/campaigns/secure_boot.yaml",
            "boot_profile": "configs/secure_boot/rsa2048.yaml",
            "ed25519_status": "configured_phase_11_5b_runnable_profile_not_hardware_validated",
            "rsa2048_status": "configured_phase_11_5c_rsa2048_profile_not_hardware_validated",
        }
    )

    metadata = secure_flash._classical_profile_metadata(experiment)

    assert metadata["model_phase"] == "phase_11_5c_rsa2048_profile"
    assert metadata["algorithm"] == "RSA2048"
    assert metadata["signature_algorithm"] == "rsa2048"
    assert metadata["key_size_bits"] == 2048
    assert metadata["signature_size_bytes"] == 256
    assert metadata["capability_status"]["ed25519"]["runnable"] is True
    assert metadata["capability_status"]["rsa2048"]["runnable"] is True
    assert metadata["capability_status"]["rsa2048"]["unavailable"] is None



def test_classical_profile_metadata_marks_phase_11_5d_expanded_profile_runnable():
    secure_flash = load_secure_boot_flash_module()
    bundle = sample_bundle()
    experiment = bundle["experiment"]
    experiment["id"] = "wolfboot_rsa4096_uart"
    experiment["boot"] = "wolfboot_rsa4096"
    experiment["boot_crypto"] = "rsa4096"
    experiment["firmware"]["mode"] = "wolfboot_rsa4096"
    experiment["firmware"]["artifact"] = "build/Release/stm32_basic_hal1_rsa4096_v1_signed.bin"
    experiment["secure_boot_benchmark_profile"].update(
        {
            "profile_id": "rsa4096_benchmark",
            "algorithm": "RSA4096",
            "wolfboot_sign": "RSA4096",
            "signature_algorithm": "rsa4096",
            "key_size_bits": 4096,
            "signature_size_bytes": 512,
            "status": "configured_phase_11_5d_expanded_classical_profile",
            "signing_profile": "configs/secure_boot/rsa4096.yaml",
            "wolfboot_build_profile": "configs/secure_boot/rsa4096.yaml",
            "experiment_profile": "configs/campaigns/secure_boot.yaml",
            "boot_profile": "configs/secure_boot/rsa4096.yaml",
            "expanded_scope_status": "phase_11_5d_expanded_classical_profile_added",
        }
    )

    metadata = secure_flash._classical_profile_metadata(experiment)

    assert metadata["model_phase"] == "phase_11_5d_expanded_classical_profiles"
    assert metadata["algorithm"] == "RSA4096"
    assert metadata["signature_algorithm"] == "rsa4096"
    assert metadata["key_size_bits"] == 4096
    assert metadata["signature_size_bytes"] == 512
    assert metadata["capability_status"]["rsa4096"]["runnable"] is True
    assert metadata["capability_status"]["rsa4096"]["unavailable"] is None
    assert metadata["expanded_classical_scope"]["active_algorithm"] == "RSA4096"


def test_classical_profile_metadata_marks_mldsa65_and_mldsa87_runnable():
    secure_flash = load_secure_boot_flash_module()
    bundle = sample_bundle()
    experiment = bundle["experiment"]
    experiment["id"] = "wolfboot_mldsa65_uart"
    experiment["boot"] = "wolfboot_mldsa65"
    experiment["boot_crypto"] = "mldsa65"
    experiment["firmware"]["mode"] = "wolfboot_mldsa65"
    experiment["firmware"]["artifact"] = "build/Release/stm32_basic_hal1_mldsa65_v1_signed.bin"
    experiment["secure_boot_benchmark_profile"].update(
        {
            "profile_id": "mldsa65_benchmark",
            "algorithm": "ML-DSA-65",
            "wolfboot_sign": "ML_DSA",
            "signature_algorithm": "mldsa65",
            "mldsa_level": 3,
            "security_category": 3,
            "signature_size_bytes": 3309,
            "status": "configured_post_phase_11_mldsa_profile_not_hardware_validated",
            "signing_profile": "configs/secure_boot/mldsa65.yaml",
            "wolfboot_build_profile": "configs/secure_boot/mldsa65.yaml",
            "experiment_profile": "configs/campaigns/secure_boot.yaml",
            "boot_profile": "configs/secure_boot/mldsa65.yaml",
        }
    )

    metadata = secure_flash._classical_profile_metadata(experiment)

    assert metadata["model_phase"] == "post_phase_11_mldsa_profiles"
    assert metadata["benchmark_scope"] == "secure_boot_mldsa_signing_algorithm"
    assert metadata["algorithm"] == "ML-DSA-65"
    assert metadata["signature_algorithm"] == "mldsa65"
    assert metadata["mldsa_level"] == 3
    assert metadata["security_category"] == 3
    assert metadata["signature_size_bytes"] == 3309
    assert metadata["capability_status"]["mldsa65"]["runnable"] is True
    assert metadata["capability_status"]["mldsa65"]["unavailable"] is None
    assert metadata["capability_status"]["mldsa87"]["runnable"] is True
    assert metadata["capability_status"]["mldsa87"]["unavailable"] is None
    assert metadata["mldsa_scope"]["active_algorithm"] == "ML-DSA-65"
