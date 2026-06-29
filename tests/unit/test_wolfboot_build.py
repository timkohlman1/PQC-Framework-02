from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest


def load_wolfboot_build_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = repo_root / "scripts" / "framework" / "wolfboot_build.py"
    spec = importlib.util.spec_from_file_location("framework_wolfboot_build", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = repo_root / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_profile() -> dict[str, object]:
    return {
        "id": "wolfboot_stm32l4_ecdsa_p256",
        "description": "Test wolfBoot profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "build/wolfboot/stm32l4_ecdsa_p256",
        "artifact": "build/wolfboot/stm32l4_ecdsa_p256/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "ecdsa_p256",
        "boot_profile": "wolfboot_ecdsa_p256",
        "build": {
            "command": "make",
            "args": "TARGET=stm32l4 SIGN=ECC256 wolfboot.elf",
        },
    }


def test_construct_wolfboot_build_command_uses_profile_command_without_shell():
    wolfboot_build = load_wolfboot_build_module()

    assert wolfboot_build.construct_wolfboot_build_command(sample_profile()) == [
        "make",
        "TARGET=stm32l4",
        "SIGN=ECC256",
        "wolfboot.elf",
    ]


def test_execute_wolfboot_build_captures_evidence_without_invoking_real_tooling(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "tools" / "wolfboot").mkdir(parents=True)
    artifact_path = repo_root / "build" / "wolfboot" / "stm32l4_ecdsa_p256" / "wolfboot.elf"
    calls: list[tuple[list[str], Path]] = []

    def fake_runner(command: list[str], cwd: Path):
        calls.append((command, cwd))
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("fake wolfboot elf", encoding="utf-8")
        return wolfboot_build.WolfBootCommandExecution(
            command=command,
            return_code=0,
            stdout="wolfboot stdout",
            stderr="wolfboot stderr",
            duration_seconds=0.25,
        )

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    expected_sha256 = hashlib.sha256(b"fake wolfboot elf").hexdigest()

    assert result.return_code == 0
    assert result.artifact_path == artifact_path
    assert result.artifact_sha256 == expected_sha256
    assert result.retained_artifact_path == result.result_dir / "wolfboot.elf"
    assert calls == [
        (["make", "TARGET=stm32l4", "SIGN=ECC256", "wolfboot.elf"], repo_root / "tools" / "wolfboot")
    ]

    build_log = result.log_path.read_text(encoding="utf-8")
    assert "wolfBoot build log" in build_log
    assert "Command: make TARGET=stm32l4 SIGN=ECC256 wolfboot.elf" in build_log
    assert "wolfboot stdout" in build_log
    assert "wolfboot stderr" in build_log
    assert f"Artifact SHA-256: {expected_sha256}" in build_log

    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["record_type"] == "wolfboot_build"
    assert manifest["result"] == "wolfboot_build_passed"
    assert manifest["wolfboot_build"]["return_code"] == 0
    assert manifest["wolfboot_build"]["signature_algorithm"] == "ecdsa_p256"
    assert manifest["artifact"]["sha256"] == expected_sha256
    assert manifest["artifact"]["retained_path"] == str(result.result_dir / "wolfboot.elf")
    assert (result.result_dir / "wolfboot.elf").read_text(encoding="utf-8") == "fake wolfboot elf"


def test_execute_wolfboot_build_fails_before_runner_when_source_dir_is_missing(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def forbidden_runner(command: list[str], cwd: Path):
        raise AssertionError("wolfBoot build tooling must not run when source_dir is missing")

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=forbidden_runner,
    )

    assert result.return_code == wolfboot_build.MISSING_SOURCE_RETURN_CODE
    assert result.execution is None
    assert result.artifact_sha256 is None
    assert "source directory does not exist" in result.failure_reason
    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result"] == "wolfboot_build_failed"
    assert manifest["wolfboot_build"]["return_code"] == wolfboot_build.MISSING_SOURCE_RETURN_CODE


def test_execute_wolfboot_build_fails_when_command_succeeds_but_artifact_is_missing(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "tools" / "wolfboot").mkdir(parents=True)

    def fake_runner(command: list[str], cwd: Path):
        return wolfboot_build.WolfBootCommandExecution(
            command=command,
            return_code=0,
            stdout="ok",
            stderr="",
            duration_seconds=0.1,
        )

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=fake_runner,
    )

    assert result.return_code == wolfboot_build.WOLFBOOT_BUILD_ARTIFACT_MISSING_RETURN_CODE
    assert "configured artifact was not found" in result.failure_reason
    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact"]["exists"] is False


def test_wolfboot_build_profile_validation_rejects_non_ecdsa_p256():
    wolfboot_build = load_wolfboot_build_module()
    profile = sample_profile()
    profile["signature_algorithm"] = "rsa2048"

    with pytest.raises(wolfboot_build.WolfBootBuildProfileError, match="ecdsa_p256"):
        wolfboot_build.validate_wolfboot_build_profile(profile)


def test_run_wolfboot_build_command_reports_no_flash_or_uart_actions(tmp_path, monkeypatch, capsys):
    experiment_cli = load_experiment_module()
    profile_path = tmp_path / "configs" / "builds" / "wolfboot_stm32l4_ecdsa_p256.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        "\n".join(
            [
                "id: wolfboot_stm32l4_ecdsa_p256",
                "description: Test wolfBoot profile.",
                "source_dir: tools/wolfboot",
                "output_dir: build/wolfboot/stm32l4_ecdsa_p256",
                "artifact: build/wolfboot/stm32l4_ecdsa_p256/wolfboot.elf",
                "target: stm32l4r5_project_local",
                "signature_algorithm: ecdsa_p256",
                "boot_profile: wolfboot_ecdsa_p256",
                "build:",
                "  command: make",
                "  args: TARGET=stm32l4 SIGN=ECC256 wolfboot.elf",
                "",
            ]
        ),
        encoding="utf-8",
    )

    class FakeWolfBootBuildResult:
        return_code = 0
        duration_seconds = 0.25
        profile_id = "wolfboot_stm32l4_ecdsa_p256"
        result_dir = tmp_path / "results" / "wolfboot-builds" / "run"
        log_path = result_dir / "wolfboot_build.log"
        command = ["make", "TARGET=stm32l4", "SIGN=ECC256", "wolfboot.elf"]
        working_directory = tmp_path / "tools" / "wolfboot"
        source_dir = tmp_path / "tools" / "wolfboot"
        output_dir = tmp_path / "build" / "wolfboot" / "stm32l4_ecdsa_p256"
        artifact_path = output_dir / "wolfboot.elf"
        artifact_exists = True
        artifact_sha256 = "a" * 64
        retained_artifact_path = result_dir / "wolfboot.elf"
        execution = None
        failure_reason = None

    def fake_execute_wolfboot_build(**kwargs):
        assert kwargs["repo_root"] == tmp_path
        assert kwargs["results_root"] == tmp_path / "results"
        assert kwargs["profile"]["signature_algorithm"] == "ecdsa_p256"
        return FakeWolfBootBuildResult()

    monkeypatch.setattr(experiment_cli, "execute_wolfboot_build", fake_execute_wolfboot_build)

    exit_code = experiment_cli.run_wolfboot_build_command(
        Namespace(profile=profile_path, results_dir=tmp_path / "results")
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "wolfBoot build completed" in output
    assert "Artifact SHA-256: " + "a" * 64 in output
    assert "No signing key generation, application signing, flash, UART access, SSH, hardware access, or network access was performed." in output


def test_execute_wolfboot_build_records_missing_build_tool_without_traceback(tmp_path):
    wolfboot_build = load_wolfboot_build_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "tools" / "wolfboot").mkdir(parents=True)

    def missing_tool_runner(command: list[str], cwd: Path):
        raise FileNotFoundError("make")

    result = wolfboot_build.execute_wolfboot_build(
        profile=sample_profile(),
        repo_root=repo_root,
        results_root=tmp_path / "results",
        runner=missing_tool_runner,
    )

    assert result.return_code == wolfboot_build.WOLFBOOT_BUILD_TOOL_MISSING_RETURN_CODE
    assert result.execution is not None
    assert result.execution.return_code == wolfboot_build.WOLFBOOT_BUILD_TOOL_MISSING_RETURN_CODE
    assert "executable was not found: make" in result.failure_reason

    build_log = result.log_path.read_text(encoding="utf-8")
    assert "Failure reason" in build_log
    assert "executable was not found: make" in build_log

    manifest = json.loads((result.result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result"] == "wolfboot_build_failed"
    assert manifest["wolfboot_build"]["return_code"] == wolfboot_build.WOLFBOOT_BUILD_TOOL_MISSING_RETURN_CODE
    assert "executable was not found: make" in manifest["wolfboot_build"]["failure_reason"]
