from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def load_flash_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "flash.py"
    spec = importlib.util.spec_from_file_location("framework_flash", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_bundle():
    return {
        "experiment": {
            "id": "baseline_direct_uart",
            "board": "board_a",
            "host": "gateway",
            "firmware": {"artifact": "build/Debug/stm32_basic_hal1.elf"},
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
    }


def write_manifest(result_dir: Path):
    result_dir.mkdir(parents=True)
    (result_dir / "manifest.json").write_text(
        json.dumps({"result": "pending"}) + "\n", encoding="utf-8"
    )


def write_build_fingerprint_inputs(repo_root: Path) -> None:
    files = {
        "configs/experiments/baseline_direct_uart.yaml": "id: baseline_direct_uart\nboard: board_a\nhost: gateway\n",
        "configs/boards/board_a.yaml": "id: board_a\n",
        "configs/hosts/gateway.yaml": "id: gateway\n",
        "CMakeLists.txt": "cmake minimum\n",
        "CMakePresets.json": "{\"version\": 3}\n",
        "STM32L4R5XX_FLASH.ld": "flash linker script\n",
        "startup_stm32l4r5xx.s": "startup assembly\n",
        "Core/Src/main.c": "int main(void) { return 0; }\n",
        "Core/Inc/main.h": "#pragma once\n",
        "cmake/gcc-arm-none-eabi.cmake": "toolchain config\n",
    }

    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def write_build_record(
    flash,
    repo_root: Path,
    results_root: Path,
    build_run_id: str,
    artifact: Path,
    *,
    firmware_sha256: str | None = None,
    build_fingerprint: str | None = None,
    include_required_fields: bool = True,
) -> None:
    build_dir = results_root / build_run_id
    build_dir.mkdir(parents=True)
    if firmware_sha256 is None:
        firmware_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if build_fingerprint is None:
        build_fingerprint = flash.calculate_default_build_fingerprint(
            sample_bundle(), repo_root
        ).fingerprint

    if include_required_fields:
        manifest = {
            "run_id": build_run_id,
            "result": "build_passed",
            "firmware": {
                "artifact": "build/Debug/stm32_basic_hal1.elf",
                "artifact_path": str(artifact),
                "sha256": firmware_sha256,
            },
            "build": {
                "fingerprint": build_fingerprint,
                "fingerprint_algorithm": "sha256-build-inputs-v1",
            },
        }
    else:
        manifest = {
            "run_id": build_run_id,
            "result": "build_passed",
            "firmware": {"artifact_path": str(artifact)},
            "build": {},
        }

    (build_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_constructs_known_good_scp_and_ssh_commands(tmp_path):
    flash = load_flash_module()
    artifact = tmp_path / "build" / "Debug" / "stm32_basic_hal1.elf"
    assert flash.construct_scp_command(artifact, "pqc-gateway1", "/tmp/stm32_basic_hal1.elf") == [
        "scp", str(artifact), "pqc-gateway1:/tmp/stm32_basic_hal1.elf"
    ]
    assert flash.construct_ssh_flash_command("pqc-gateway1", "flash-stm32a", "/tmp/stm32_basic_hal1.elf") == [
        "ssh", "pqc-gateway1", "flash-stm32a /tmp/stm32_basic_hal1.elf"
    ]


def test_execute_flash_captures_both_steps_and_updates_manifest_with_verified_build_record(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    result_dir = results_root / "flash-run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fake elf", encoding="utf-8")
    write_manifest(result_dir)
    write_build_record(flash, repo_root, results_root, "build-run", artifact)
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        return flash.CommandExecution(command, 0, "stdout text", "stderr text", 0.1)

    def fake_git_runner(command, cwd):
        assert cwd == repo_root
        if command == ["git", "rev-parse", "HEAD"]:
            return flash.GitCommandExecution(command, 0, "flash789\n", "", 0.01)
        if command == ["git", "status", "--short"]:
            return flash.GitCommandExecution(command, 0, " M build/Debug/stm32_basic_hal1.elf\n", "", 0.01)
        raise AssertionError(f"unexpected git command: {command}")

    result = flash.execute_flash(
        sample_bundle(),
        repo_root,
        result_dir,
        fake_runner,
        fake_git_runner,
        source_build_run_id="build-run",
    )
    expected_sha256 = hashlib.sha256(b"fake elf").hexdigest()

    assert result.return_code == 0
    assert result.firmware_sha256 == expected_sha256
    assert result.provenance_status == "verified_build_match"
    assert calls == [
        ["scp", str(artifact), "pqc-gateway1:/tmp/stm32_basic_hal1.elf"],
        ["ssh", "pqc-gateway1", "flash-stm32a /tmp/stm32_basic_hal1.elf"],
    ]
    log = (result_dir / "flash.log").read_text(encoding="utf-8")
    assert "SCP step" in log and "Flash step" in log
    assert "stdout text" in log and "stderr text" in log
    assert "Provenance status: verified_build_match" in log
    assert "ST-LINK serial: 066EFF3932504E3043111818" in log
    assert f"Local artifact SHA-256: {expected_sha256}" in log
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result"] == "flash_passed"
    assert manifest["flash"]["return_code"] == 0
    assert manifest["firmware"]["sha256"] == expected_sha256
    assert manifest["flash"]["remote_artifact_path"] == "/tmp/stm32_basic_hal1.elf"
    assert manifest["flash"]["stlink_serial"] == "066EFF3932504E3043111818"
    assert manifest["flash"]["firmware_sha256"] == expected_sha256
    assert manifest["flash"]["source_build_run_id"] == "build-run"
    assert manifest["flash"]["source_build_firmware_sha256"] == expected_sha256
    assert manifest["flash"]["source_build_fingerprint"] == manifest["flash"]["current_build_fingerprint"]
    assert manifest["flash"]["provenance_status"] == "verified_build_match"
    assert manifest["source"] == {
        "git_commit": "flash789",
        "git_dirty": True,
        "git_status_available": True,
    }


def test_execute_flash_refuses_when_elf_hash_differs_from_build_record(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    result_dir = results_root / "flash-run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact.parent.mkdir(parents=True)
    artifact.write_text("flash elf", encoding="utf-8")
    write_manifest(result_dir)
    write_build_record(
        flash,
        repo_root,
        results_root,
        "build-run",
        artifact,
        firmware_sha256=hashlib.sha256(b"different build elf").hexdigest(),
    )

    def forbidden_runner(command, cwd):
        raise AssertionError("network commands must not run after hash mismatch")

    result = flash.execute_flash(
        sample_bundle(),
        repo_root,
        result_dir,
        forbidden_runner,
        source_build_run_id="build-run",
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == flash.PROVENANCE_REFUSED_RETURN_CODE
    assert result.provenance_status == "mismatch_refused"
    assert result.scp is None and result.flash is None
    assert manifest["result"] == "flash_failed"
    assert manifest["flash"]["provenance_status"] == "mismatch_refused"
    assert "ELF SHA-256 does not match" in manifest["flash"]["provenance_message"]


def test_execute_flash_refuses_when_fingerprint_differs_from_build_record(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    result_dir = results_root / "flash-run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fake elf", encoding="utf-8")
    write_manifest(result_dir)
    write_build_record(
        flash,
        repo_root,
        results_root,
        "build-run",
        artifact,
        build_fingerprint="0" * 64,
    )

    def forbidden_runner(command, cwd):
        raise AssertionError("network commands must not run after fingerprint mismatch")

    result = flash.execute_flash(
        sample_bundle(),
        repo_root,
        result_dir,
        forbidden_runner,
        source_build_run_id="build-run",
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == flash.PROVENANCE_REFUSED_RETURN_CODE
    assert result.provenance_status == "mismatch_refused"
    assert result.scp is None and result.flash is None
    assert manifest["flash"]["source_build_fingerprint"] == "0" * 64
    assert manifest["flash"]["source_build_fingerprint"] != manifest["flash"]["current_build_fingerprint"]
    assert "fingerprint does not match" in manifest["flash"]["provenance_message"]


def test_execute_flash_refuses_when_build_run_manifest_is_missing_required_fields(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    result_dir = results_root / "flash-run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fake elf", encoding="utf-8")
    write_manifest(result_dir)
    write_build_record(
        flash,
        repo_root,
        results_root,
        "build-run",
        artifact,
        include_required_fields=False,
    )

    def forbidden_runner(command, cwd):
        raise AssertionError("network commands must not run with invalid build record")

    result = flash.execute_flash(
        sample_bundle(),
        repo_root,
        result_dir,
        forbidden_runner,
        source_build_run_id="build-run",
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == flash.BUILD_RECORD_INVALID_RETURN_CODE
    assert result.provenance_status == "missing_build_record"
    assert result.scp is None and result.flash is None
    assert manifest["flash"]["provenance_status"] == "missing_build_record"
    assert "Build manifest missing required field" in manifest["flash"]["provenance_message"]


def test_execute_flash_refuses_without_build_run_unless_escape_hatch_is_used(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "flash-run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fake elf", encoding="utf-8")
    write_manifest(result_dir)

    def forbidden_runner(command, cwd):
        raise AssertionError("network commands must not run without a build record")

    result = flash.execute_flash(sample_bundle(), repo_root, result_dir, forbidden_runner)
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == flash.BUILD_RECORD_MISSING_RETURN_CODE
    assert result.provenance_status == "missing_build_record"
    assert result.scp is None and result.flash is None
    assert manifest["flash"]["provenance_status"] == "missing_build_record"


def test_execute_flash_escape_hatch_records_untracked_artifact_allowed(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "flash-run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fake elf", encoding="utf-8")
    write_manifest(result_dir)
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        return flash.CommandExecution(command, 0, "", "", 0.1)

    result = flash.execute_flash(
        sample_bundle(),
        repo_root,
        result_dir,
        fake_runner,
        allow_untracked_artifact=True,
    )
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == 0
    assert result.provenance_status == "untracked_artifact_allowed"
    assert len(calls) == 2
    assert manifest["flash"]["provenance_status"] == "untracked_artifact_allowed"
    assert manifest["flash"]["untracked_artifact_allowed"] is True
    assert manifest["flash"]["source_build_run_id"] is None


def test_execute_flash_skips_ssh_when_scp_fails(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    result_dir = results_root / "flash-run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fake elf", encoding="utf-8")
    write_manifest(result_dir)
    write_build_record(flash, repo_root, results_root, "build-run", artifact)
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        return flash.CommandExecution(command, 7, "", "scp failed", 0.1)

    result = flash.execute_flash(
        sample_bundle(), repo_root, result_dir, fake_runner, source_build_run_id="build-run"
    )
    assert result.return_code == 7
    assert len(calls) == 1
    assert result.flash is None
    assert "Skipped because the SCP step failed." in (result_dir / "flash.log").read_text(
        encoding="utf-8"
    )


def test_execute_flash_fails_without_network_when_artifact_missing(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    repo_root.mkdir()
    write_manifest(result_dir)

    def forbidden_runner(command, cwd):
        raise AssertionError("runner must not be called")

    result = flash.execute_flash(sample_bundle(), repo_root, result_dir, forbidden_runner)
    assert result.return_code == flash.ARTIFACT_MISSING_RETURN_CODE
    assert result.firmware_sha256 is None
    assert result.scp is None and result.flash is None


def test_execute_flash_preserves_existing_build_sha256_and_records_flash_sha256(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    artifact.parent.mkdir(parents=True)
    artifact.write_text("flash elf", encoding="utf-8")
    result_dir.mkdir(parents=True)
    flash_sha256 = hashlib.sha256(b"flash elf").hexdigest()
    current_fingerprint = flash.calculate_default_build_fingerprint(sample_bundle(), repo_root).fingerprint
    (result_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run",
                "result": "build_passed",
                "firmware": {
                    "artifact_path": str(artifact),
                    "sha256": flash_sha256,
                },
                "build": {"fingerprint": current_fingerprint},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_runner(command, cwd):
        return flash.CommandExecution(command, 0, "", "", 0.1)

    result = flash.execute_flash(sample_bundle(), repo_root, result_dir, fake_runner, source_build_run_id="run")
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))

    assert result.return_code == 0
    assert manifest["firmware"]["sha256"] == flash_sha256
    assert manifest["flash"]["firmware_sha256"] == flash_sha256
    assert manifest["flash"]["provenance_status"] == "verified_build_match"
