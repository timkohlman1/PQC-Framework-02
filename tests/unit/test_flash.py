from __future__ import annotations

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
        "experiment": {"firmware": {"artifact": "build/Debug/stm32_basic_hal1.elf"}},
        "board": {"stlink": {"serial": "066EFF3932504E3043111818"}},
        "host": {"alias": "pqc-gateway1", "flash": {"helper": "flash-stm32a"}},
    }


def write_manifest(result_dir: Path):
    result_dir.mkdir(parents=True)
    (result_dir / "manifest.json").write_text(
        json.dumps({"result": "pending"}) + "\n", encoding="utf-8"
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


def test_execute_flash_captures_both_steps_and_updates_manifest(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fake elf", encoding="utf-8")
    write_manifest(result_dir)
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        return flash.CommandExecution(command, 0, "stdout text", "stderr text", 0.1)

    result = flash.execute_flash(sample_bundle(), repo_root, result_dir, fake_runner)
    assert result.return_code == 0
    assert calls == [
        ["scp", str(artifact), "pqc-gateway1:/tmp/stm32_basic_hal1.elf"],
        ["ssh", "pqc-gateway1", "flash-stm32a /tmp/stm32_basic_hal1.elf"],
    ]
    log = (result_dir / "flash.log").read_text(encoding="utf-8")
    assert "SCP step" in log and "Flash step" in log
    assert "stdout text" in log and "stderr text" in log
    assert "ST-LINK serial: 066EFF3932504E3043111818" in log
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result"] == "flash_passed"
    assert manifest["flash"]["return_code"] == 0
    assert manifest["flash"]["remote_artifact_path"] == "/tmp/stm32_basic_hal1.elf"
    assert manifest["flash"]["stlink_serial"] == "066EFF3932504E3043111818"


def test_execute_flash_skips_ssh_when_scp_fails(tmp_path):
    flash = load_flash_module()
    repo_root = tmp_path / "repo"
    result_dir = tmp_path / "results" / "run"
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("fake elf", encoding="utf-8")
    write_manifest(result_dir)
    calls = []

    def fake_runner(command, cwd):
        calls.append(command)
        return flash.CommandExecution(command, 7, "", "scp failed", 0.1)

    result = flash.execute_flash(sample_bundle(), repo_root, result_dir, fake_runner)
    assert result.return_code == 7
    assert len(calls) == 1
    assert result.flash is None
    assert "Skipped because the SCP step failed." in (result_dir / "flash.log").read_text(encoding="utf-8")


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
    assert result.scp is None and result.flash is None
