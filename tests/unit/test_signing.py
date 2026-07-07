from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_signing_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    return importlib.import_module("framework.signing")


def sample_profile() -> dict[str, object]:
    return {
        "id": "wolfboot_ecdsa_p256_app",
        "description": "Test signing profile.",
        "input_elf": "build/RelocatedDebug/stm32_basic_hal1.elf",
        "input_image": "build/RelocatedDebug/stm32_basic_hal1.bin",
        "signed_image": "build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin",
        "retained_signed_image": "application_signed.bin",
        "signature_algorithm": "ecdsa_p256",
        "signature_size_bytes": 64,
        "image_version": 1,
        "private_key": "secrets/wolfboot/ecdsa_p256_private_key.der",
        "binary_conversion": {
            "enabled": True,
            "command": "arm-none-eabi-objcopy",
            "args": "-O binary {input_elf} {input_image}",
        },
        "keygen": {
            "enabled": True,
            "working_dir": "tools/wolfboot",
            "command": "tools/keytools/keygen",
            "args": "--ecc256 -g {private_key}",
            "stdin": "Yes\n",
        },
        "sign": {
            "working_dir": "tools/wolfboot",
            "environment": {"IMAGE_HEADER_SIZE": "8192"},
            "command": "tools/keytools/sign",
            "args": "--ecc256 {input_image} {private_key} {image_version}",
        },
    }


def test_construct_signing_commands_expand_profile_placeholders(tmp_path):
    signing = load_signing_module()
    repo_root = tmp_path / "repo"
    profile = sample_profile()

    keygen_command = signing.construct_keygen_command(profile, repo_root)
    binary_conversion_command = signing.construct_binary_conversion_command(profile, repo_root)
    sign_command = signing.construct_signing_command(profile, repo_root)

    assert binary_conversion_command == [
        "arm-none-eabi-objcopy",
        "-O",
        "binary",
        str(repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1.elf"),
        str(repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1.bin"),
    ]
    assert keygen_command == [
        "tools/keytools/keygen",
        "--ecc256",
        "-g",
        str(repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"),
    ]
    assert sign_command == [
        "tools/keytools/sign",
        "--ecc256",
        str(repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1.bin"),
        str(repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"),
        "1",
    ]




def test_resolve_relative_keytool_executable_with_exe_suffix(tmp_path):
    signing = load_signing_module()
    cwd = tmp_path / "repo" / "tools" / "wolfboot"
    keytool = cwd / "tools" / "keytools" / "keygen.exe"
    keytool.parent.mkdir(parents=True)
    keytool.write_bytes(b"fake exe")

    resolved = signing._resolve_command_for_cwd(["tools/keytools/keygen", "--ecc256"], cwd)

    assert resolved == [str(keytool), "--ecc256"]



def test_default_signing_runner_times_out_non_interactive_command(tmp_path):
    signing = load_signing_module()
    script = tmp_path / "hang.py"
    script.write_text(
        "import time\n"
        "print('started')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    original_timeout = signing.DEFAULT_SIGNING_COMMAND_TIMEOUT_SECONDS
    signing.DEFAULT_SIGNING_COMMAND_TIMEOUT_SECONDS = 1
    try:
        result = signing.default_signing_runner([sys.executable, str(script)], tmp_path)
    finally:
        signing.DEFAULT_SIGNING_COMMAND_TIMEOUT_SECONDS = original_timeout

    assert result.return_code == signing.SIGNING_COMMAND_TIMEOUT_RETURN_CODE
    assert "timed out after 1 seconds" in result.stderr
    assert result.duration_seconds < 10



def test_keygen_stdin_confirmation_is_expanded_from_profile():
    signing = load_signing_module()
    profile = sample_profile()

    assert signing._section_stdin(profile, "keygen") == "Yes\n"
    assert signing._section_stdin(profile, "sign") is None


def test_signing_environment_overrides_are_temporary(monkeypatch, tmp_path):
    signing = load_signing_module()
    monkeypatch.setenv("IMAGE_HEADER_SIZE", "256")
    observed: dict[str, str | None] = {}

    def fake_runner(command: list[str], cwd: Path, stdin_text: str | None = None):
        observed["during"] = os.environ.get("IMAGE_HEADER_SIZE")
        return signing.SigningCommandExecution(command, 0, "ok", "", 0.1)

    result = signing._run_with_environment(
        fake_runner,
        ["sign"],
        tmp_path,
        None,
        {"IMAGE_HEADER_SIZE": "8192"},
    )

    assert result.return_code == 0
    assert observed["during"] == "8192"
    assert os.environ.get("IMAGE_HEADER_SIZE") == "256"


def test_execute_application_signing_generates_key_signs_and_records_metadata(tmp_path):
    signing = load_signing_module()
    repo_root = tmp_path / "repo"
    input_elf = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1.elf"
    input_image = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1.bin"
    signed_image = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_v1_signed.bin"
    private_key = repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"
    input_elf.parent.mkdir(parents=True)
    input_elf.write_bytes(b"relocated app elf")
    (repo_root / "scripts" / "framework").mkdir(parents=True)
    (repo_root / "scripts" / "framework" / "signing.py").write_text("signing helper\n", encoding="utf-8")
    (repo_root / "configs" / "signing").mkdir(parents=True)
    (repo_root / "configs" / "signing" / "wolfboot_ecdsa_p256_app.yaml").write_text("profile\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path, stdin_text: str | None = None):
        calls.append(command)
        if command[0] == "arm-none-eabi-objcopy":
            assert cwd == repo_root
            input_image.write_bytes(b"relocated app image")
            return signing.SigningCommandExecution(command, 0, "binary converted", "", 0.05)
        if command[0].endswith("keygen"):
            assert cwd == repo_root / "tools" / "wolfboot"
            assert stdin_text == "Yes\n"
            private_key.parent.mkdir(parents=True, exist_ok=True)
            private_key.write_bytes(b"local test private key")
            return signing.SigningCommandExecution(command, 0, "key generated", "", 0.1)
        if command[0].endswith("sign"):
            assert cwd == repo_root / "tools" / "wolfboot"
            assert os.environ.get("IMAGE_HEADER_SIZE") == "8192"
            assert private_key.is_file()
            signed_image.write_bytes(b"signed image bytes")
            return signing.SigningCommandExecution(command, 0, "image signed", "", 0.2)
        raise AssertionError(f"unexpected command: {command}")

    result = signing.execute_application_signing(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
        timestamp=datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc),
    )

    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    log_text = result.log_path.read_text(encoding="utf-8")
    expected_input_sha = hashlib.sha256(b"relocated app image").hexdigest()
    expected_signed_sha = hashlib.sha256(b"signed image bytes").hexdigest()

    assert result.return_code == 0
    assert result.private_key_existed_before is False
    assert result.private_key_present_after is True
    assert result.input_image_sha256 == expected_input_sha
    assert result.signed_image_sha256 == expected_signed_sha
    assert result.signature_algorithm == "ecdsa_p256"
    assert result.signature_size_bytes == 64
    assert result.retained_signed_image_path == result.result_dir / "application_signed.bin"
    assert (result.result_dir / "application_signed.bin").read_bytes() == b"signed image bytes"
    assert len(calls) == 3
    assert calls[0][0] == "arm-none-eabi-objcopy"
    assert manifest["record_type"] == "application_signing"
    assert manifest["result"] == "application_signing_passed"
    assert manifest["signing"]["signature_algorithm"] == "ecdsa_p256"
    assert manifest["signing"]["signature_size"] == 64
    assert manifest["signing"]["signature_size_bytes"] == 64
    assert manifest["signing"]["input_elf"].endswith("stm32_basic_hal1.elf")
    assert manifest["signing"]["input_image_sha256"] == expected_input_sha
    assert manifest["signing"]["binary_conversion_enabled"] is True
    assert manifest["signing"]["binary_conversion_return_code"] == 0
    assert manifest["signing"]["private_key_sha256"] == hashlib.sha256(b"local test private key").hexdigest()
    assert manifest["signing"]["fingerprint_status"] == "available"
    assert len(manifest["signing"]["fingerprint"]) == 64
    assert manifest["signing"]["fingerprint_algorithm"] == "sha256-secure-boot-inputs-v1"
    assert "scripts/framework/signing.py" in manifest["signing"]["requested_fingerprint_inputs"]
    assert manifest["signing"]["signed_image_sha256"] == expected_signed_sha
    assert manifest["signing"]["sign_environment"] == {"IMAGE_HEADER_SIZE": "8192"}
    assert manifest["signing"]["key_material_copied_to_results"] is False
    assert not (result.result_dir / "ecdsa_p256_private_key.der").exists()
    assert "Private signing keys are local-only evidence inputs" in log_text
    assert "Input fingerprint status: available" in log_text


def test_execute_application_signing_uses_existing_private_key_without_keygen(tmp_path):
    signing = load_signing_module()
    repo_root = tmp_path / "repo"
    input_image = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1.bin"
    signed_image = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_v1_signed.bin"
    private_key = repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"
    input_image.parent.mkdir(parents=True)
    private_key.parent.mkdir(parents=True)
    input_image.write_bytes(b"relocated app image")
    private_key.write_bytes(b"existing local private key")
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path, stdin_text: str | None = None):
        calls.append(command)
        assert cwd == repo_root / "tools" / "wolfboot"
        signed_image.write_bytes(b"signed image bytes")
        return signing.SigningCommandExecution(command, 0, "image signed", "", 0.2)

    result = signing.execute_application_signing(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    assert result.return_code == 0
    assert result.private_key_existed_before is True
    assert result.keygen_execution is None
    assert result.sign_execution is not None
    assert len(calls) == 1
    assert calls[0][0].endswith("sign")


def test_execute_application_signing_regenerates_bin_when_configured_elf_exists(tmp_path):
    signing = load_signing_module()
    repo_root = tmp_path / "repo"
    input_elf = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1.elf"
    input_image = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1.bin"
    signed_image = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_v1_signed.bin"
    private_key = repo_root / "secrets" / "wolfboot" / "ecdsa_p256_private_key.der"
    input_elf.parent.mkdir(parents=True)
    private_key.parent.mkdir(parents=True)
    input_elf.write_bytes(b"new relocated app elf")
    input_image.write_bytes(b"stale relocated app image")
    private_key.write_bytes(b"existing local private key")
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path, stdin_text: str | None = None):
        calls.append(command)
        if command[0] == "arm-none-eabi-objcopy":
            assert cwd == repo_root
            input_image.write_bytes(b"fresh relocated app image")
            return signing.SigningCommandExecution(command, 0, "binary converted", "", 0.05)
        if command[0].endswith("sign"):
            assert cwd == repo_root / "tools" / "wolfboot"
            signed_image.write_bytes(b"signed fresh image bytes")
            return signing.SigningCommandExecution(command, 0, "image signed", "", 0.2)
        raise AssertionError(f"unexpected command: {command}")

    result = signing.execute_application_signing(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    assert result.return_code == 0
    assert result.binary_conversion_execution is not None
    assert result.input_image_sha256 == hashlib.sha256(b"fresh relocated app image").hexdigest()
    assert input_image.read_bytes() == b"fresh relocated app image"
    assert len(calls) == 2
    assert calls[0][0] == "arm-none-eabi-objcopy"
    assert calls[1][0].endswith("sign")


def test_execute_application_signing_records_missing_input_without_generating_key(tmp_path):
    signing = load_signing_module()
    repo_root = tmp_path / "repo"
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path, stdin_text: str | None = None):
        calls.append(command)
        raise AssertionError("runner should not be called when input image is missing")

    result = signing.execute_application_signing(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert result.return_code == signing.MISSING_INPUT_IMAGE_RETURN_CODE
    assert "does not exist" in result.failure_reason
    assert calls == []
    assert manifest["result"] == "application_signing_failed"
    assert manifest["signing"]["key_material_copied_to_results"] is False


def test_execute_application_signing_requires_private_key_when_keygen_disabled(tmp_path):
    signing = load_signing_module()
    repo_root = tmp_path / "repo"
    input_image = repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1.bin"
    input_image.parent.mkdir(parents=True)
    input_image.write_bytes(b"relocated app image")
    profile = sample_profile()
    profile["keygen"] = {"enabled": False}

    result = signing.execute_application_signing(
        profile=profile,
        repo_root=repo_root,
        results_root=tmp_path / "results",
    )

    assert result.return_code == signing.PRIVATE_KEY_MISSING_RETURN_CODE
    assert "key generation is disabled" in result.failure_reason


def test_default_application_signing_profile_is_safe_and_phase_10g_scoped():
    repo_root = Path(__file__).resolve().parents[2]
    profile_path = repo_root / "configs" / "signing" / "wolfboot_ecdsa_p256_app.yaml"
    profile_text = profile_path.read_text(encoding="utf-8")

    assert "signature_algorithm: ecdsa_p256" in profile_text
    assert "private_key: secrets/wolfboot/ecdsa_p256_private_key.der" in profile_text
    assert "input_elf: build/RelocatedDebug/stm32_basic_hal1.elf" in profile_text
    assert "input_image: build/RelocatedDebug/stm32_basic_hal1.bin" in profile_text
    assert "binary_conversion:" in profile_text
    assert "working_dir: tools/wolfboot" in profile_text
    assert "command: tools/keytools/keygen" in profile_text
    assert "command: tools/keytools/sign" in profile_text
    assert "signed_image: build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin" in profile_text
    assert "No private" not in profile_text



def test_construct_ed25519_signing_commands_expand_profile_placeholders(tmp_path):
    signing = load_signing_module()
    repo_root = tmp_path / "repo"
    profile = sample_profile()
    profile["id"] = "wolfboot_ed25519_app"
    profile["input_image"] = "build/RelocatedDebug/stm32_basic_hal1_ed25519.bin"
    profile["signed_image"] = "build/RelocatedDebug/stm32_basic_hal1_ed25519_v1_signed.bin"
    profile["signature_algorithm"] = "ed25519"
    profile["private_key"] = "secrets/wolfboot/ed25519_private_key.der"
    profile["keygen"]["args"] = "--ed25519 -g {private_key}"
    profile["sign"]["args"] = "--ed25519 {input_image} {private_key} {image_version}"

    keygen_command = signing.construct_keygen_command(profile, repo_root)
    sign_command = signing.construct_signing_command(profile, repo_root)

    assert keygen_command == [
        "tools/keytools/keygen",
        "--ed25519",
        "-g",
        str(repo_root / "secrets" / "wolfboot" / "ed25519_private_key.der"),
    ]
    assert sign_command == [
        "tools/keytools/sign",
        "--ed25519",
        str(repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_ed25519.bin"),
        str(repo_root / "secrets" / "wolfboot" / "ed25519_private_key.der"),
        "1",
    ]


def test_construct_rsa2048_signing_commands_expand_profile_placeholders(tmp_path):
    signing = load_signing_module()
    repo_root = tmp_path
    profile = sample_profile()
    profile["id"] = "wolfboot_rsa2048_app"
    profile["input_image"] = "build/RelocatedDebug/stm32_basic_hal1_rsa2048.bin"
    profile["signed_image"] = "build/RelocatedDebug/stm32_basic_hal1_rsa2048_v1_signed.bin"
    profile["signature_algorithm"] = "rsa2048"
    profile["private_key"] = "secrets/wolfboot/rsa2048_private_key.der"
    profile["keygen"]["args"] = "--rsa2048 -g {private_key}"
    profile["sign"]["args"] = "--rsa2048 {input_image} {private_key} {image_version}"

    keygen_command = signing.construct_keygen_command(profile, repo_root)
    sign_command = signing.construct_signing_command(profile, repo_root)

    assert keygen_command == [
        "tools/keytools/keygen",
        "--rsa2048",
        "-g",
        str(repo_root / "secrets" / "wolfboot" / "rsa2048_private_key.der"),
    ]
    assert sign_command == [
        "tools/keytools/sign",
        "--rsa2048",
        str(repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_rsa2048.bin"),
        str(repo_root / "secrets" / "wolfboot" / "rsa2048_private_key.der"),
        "1",
    ]



def test_construct_phase_11_5d_expanded_signing_commands_expand_profile_placeholders(tmp_path):
    signing = load_signing_module()
    repo_root = tmp_path
    profile = sample_profile()
    profile["id"] = "wolfboot_rsa4096_app"
    profile["input_image"] = "build/RelocatedDebug/stm32_basic_hal1_rsa4096.bin"
    profile["signed_image"] = "build/RelocatedDebug/stm32_basic_hal1_rsa4096_v1_signed.bin"
    profile["signature_algorithm"] = "rsa4096"
    profile["private_key"] = "secrets/wolfboot/rsa4096_private_key.der"
    profile["keygen"]["args"] = "--rsa4096 -g {private_key}"
    profile["sign"]["args"] = "--rsa4096 {input_image} {private_key} {image_version}"

    keygen_command = signing.construct_keygen_command(profile, repo_root)
    sign_command = signing.construct_signing_command(profile, repo_root)

    assert keygen_command == [
        "tools/keytools/keygen",
        "--rsa4096",
        "-g",
        str(repo_root / "secrets" / "wolfboot" / "rsa4096_private_key.der"),
    ]
    assert sign_command == [
        "tools/keytools/sign",
        "--rsa4096",
        str(repo_root / "build" / "RelocatedDebug" / "stm32_basic_hal1_rsa4096.bin"),
        str(repo_root / "secrets" / "wolfboot" / "rsa4096_private_key.der"),
        "1",
    ]


def test_validate_application_signing_profile_accepts_mldsa65():
    signing = load_signing_module()
    profile = sample_profile()
    profile["id"] = "wolfboot_mldsa65_app"
    profile["signature_algorithm"] = "mldsa65"
    profile["private_key"] = "secrets/wolfboot/mldsa65_private_key.der"
    profile["input_image"] = "build/RelocatedDebug/stm32_basic_hal1_mldsa65.bin"
    profile["signed_image"] = "build/RelocatedDebug/stm32_basic_hal1_mldsa65_v1_signed.bin"
    profile["keygen"]["args"] = "--ml_dsa -g {private_key}"
    profile["sign"]["args"] = "--ml_dsa {input_image} {private_key} {image_version}"

    signing.validate_application_signing_profile(profile)

    keygen_command = signing.construct_keygen_command(profile, Path("/repo"))

    assert keygen_command[-3:-1] == ["--ml_dsa", "-g"]
    assert Path(keygen_command[-1]).as_posix() == "/repo/secrets/wolfboot/mldsa65_private_key.der"


def test_default_signing_runner_builds_missing_wolfboot_keytool(monkeypatch, tmp_path):
    signing = load_signing_module()
    cwd = tmp_path / "repo" / "tools" / "wolfboot"
    keytools_dir = cwd / "tools" / "keytools"
    keytools_dir.mkdir(parents=True)
    (keytools_dir / "Makefile").write_text("all:\n\t@echo build keytools\n", encoding="utf-8")
    (keytools_dir / "sign.o").write_bytes(b"stale host object")
    (keytools_dir / "asn.d").write_text("stale Windows dependency file", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        if command == ["make", "-C", "tools/keytools"]:
            assert kwargs["timeout"] == signing.DEFAULT_KEYTOOLS_BUILD_TIMEOUT_SECONDS
            assert not (keytools_dir / "sign.o").exists()
            assert not (keytools_dir / "asn.d").exists()
            (keytools_dir / "sign").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            return signing.subprocess.CompletedProcess(command, 0, "built keytools", "")
        assert kwargs["timeout"] == signing.DEFAULT_SIGNING_COMMAND_TIMEOUT_SECONDS
        assert Path(command[0]).as_posix().endswith("tools/keytools/sign")
        return signing.subprocess.CompletedProcess(command, 0, "signed", "")

    monkeypatch.setattr(signing.subprocess, "run", fake_run)

    result = signing.default_signing_runner(["tools/keytools/sign", "--ecc256"], cwd)

    assert result.return_code == 0
    assert result.stdout == "signed"
    assert calls[0] == ["make", "-C", "tools/keytools"]
    assert Path(calls[1][0]).as_posix().endswith("tools/keytools/sign")


def test_default_signing_runner_returns_keytool_build_failure(monkeypatch, tmp_path):
    signing = load_signing_module()
    cwd = tmp_path / "repo" / "tools" / "wolfboot"
    keytools_dir = cwd / "tools" / "keytools"
    keytools_dir.mkdir(parents=True)
    (keytools_dir / "Makefile").write_text("all:\n\tfalse\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        return signing.subprocess.CompletedProcess(command, 2, "", "make failed")

    monkeypatch.setattr(signing.subprocess, "run", fake_run)

    result = signing.default_signing_runner(["tools/keytools/sign", "--ecc256"], cwd)

    assert result.return_code == 2
    assert result.command == ["make", "-C", "tools/keytools"]
    assert result.stderr == "make failed"
