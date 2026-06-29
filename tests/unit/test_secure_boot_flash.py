from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


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
                "artifact": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
            },
            "uart": {
                "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
                "expected_tick_message": "tick",
                "expected_secure_boot_message": "stm32-basic_hal1 secure-boot app v0.1.0",
            },
            "secure_boot_flash": {
                "signature_algorithm": "ecdsa_p256",
                "signature_size_bytes": 64,
                "image_version": 1,
                "wolfboot_artifact": "tools/wolfboot/wolfboot.elf",
                "wolfboot_offset": "0x08000000",
                "wolfboot_pass_offset_to_helper": False,
                "signed_application_artifact": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
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
            "flash": {"helper": "flash-stm32a"},
        },
        "boot": {
            "id": "wolfboot_ecdsa_p256",
            "mode": "wolfboot_ecdsa_p256",
        },
    }


def write_manifest(result_dir: Path):
    result_dir.mkdir(parents=True)
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
    signed_artifact = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_v1_signed.bin"
    wolfboot_artifact.parent.mkdir(parents=True)
    signed_artifact.parent.mkdir(parents=True)
    wolfboot_artifact.write_bytes(b"wolfboot elf")
    signed_artifact.write_bytes(b"signed application")
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

    wolfboot_sha = hashlib.sha256(b"wolfboot elf").hexdigest()
    signed_sha = hashlib.sha256(b"signed application").hexdigest()

    assert result.return_code == 0
    assert result.failure_stage == "none"
    assert calls == [
        ["scp", str(wolfboot_artifact), f"pqc-gateway1:/tmp/{result_dir.name}_wolfboot_wolfboot.elf"],
        ["ssh", "pqc-gateway1", f"flash-stm32a /tmp/{result_dir.name}_wolfboot_wolfboot.elf"],
        ["scp", str(signed_artifact), f"pqc-gateway1:/tmp/{result_dir.name}_signed_application_stm32_basic_hal1_v1_signed.bin"],
        ["ssh", "pqc-gateway1", f"flash-stm32a /tmp/{result_dir.name}_signed_application_stm32_basic_hal1_v1_signed.bin 0x08020000"],
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
    assert manifest["boot_signature"] == {
        "algorithm": "ecdsa_p256",
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
    assert manifest["source"] == {
        "git_commit": "abc123",
        "git_dirty": False,
        "git_status_available": True,
    }


def test_execute_secure_boot_flash_refuses_missing_wolfboot_without_network(tmp_path):
    secure_flash = load_secure_boot_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    signed_artifact = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_v1_signed.bin"
    signed_artifact.parent.mkdir(parents=True)
    signed_artifact.write_bytes(b"signed application")
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
    signed_artifact = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_v1_signed.bin"
    wolfboot_artifact.parent.mkdir(parents=True)
    signed_artifact.parent.mkdir(parents=True)
    wolfboot_artifact.write_bytes(b"wolfboot elf")
    signed_artifact.write_bytes(b"signed application")
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
    signed_artifact = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_v1_signed.bin"
    wolfboot_artifact.parent.mkdir(parents=True)
    signed_artifact.parent.mkdir(parents=True)
    wolfboot_artifact.write_bytes(b"wolfboot elf")
    signed_artifact.write_bytes(b"signed application")
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
        f"pqc-gateway1:/tmp/{result_dir.name}_signed_application_corrupted_application_signed.bin",
    ]

    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    negative = manifest["secure_boot_flash"]["negative_test"]
    assert negative["enabled"] is True
    assert negative["method"] == "flip_first_byte"
    assert negative["source_image_modified"] is False
    assert negative["original_signed_application_path"] == str(signed_artifact)
    assert negative["corrupted_signed_application_path"] == str(corrupted_path)
    assert negative["original_signed_application_sha256"] != negative["corrupted_signed_application_sha256"]
