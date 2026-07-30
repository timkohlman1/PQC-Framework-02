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
        "stm32_basic_hal1.ioc": "CubeMX project source\n",
        "Core/Src/main.c": "int main(void) { return 0; }\n",
        "Core/Inc/main.h": "#pragma once\n",
        "Drivers/CMSIS/device.h": "CMSIS driver input\n",
        "Drivers/STM32L4xx_HAL_Driver/hal.c": "HAL driver input\n",
        "cmake/gcc-arm-none-eabi.cmake": "toolchain config\n",
    }

    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    nested_cmake = repo_root / "cmake" / "stm32cubemx" / "CMakeLists.txt"
    nested_cmake.parent.mkdir(parents=True, exist_ok=True)
    nested_cmake.write_text(
        "target_sources(stm32cubemx INTERFACE Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c)\n",
        encoding="utf-8",
    )
    hal_source = repo_root / "Drivers" / "STM32L4xx_HAL_Driver" / "Src" / "stm32l4xx_hal.c"
    hal_source.parent.mkdir(parents=True, exist_ok=True)
    hal_source.write_text("void hal_fixture(void) {}\n", encoding="utf-8")


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




def test_flash_provenance_uses_elf_hash_without_source_fingerprint(tmp_path):
    flash = load_flash_module()
    result_dir = tmp_path / "results" / "run"
    record_dir = tmp_path / "results" / "builds" / "1"
    result_dir.mkdir(parents=True)
    record_dir.mkdir(parents=True)
    artifact = tmp_path / "app.elf"
    artifact.write_bytes(b"elf")
    digest = hashlib.sha256(b"elf").hexdigest()
    manifest_path = record_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"firmware": {"sha256": digest, "artifact_path": str(artifact)}}), encoding="utf-8")
    provenance = flash._check_flash_provenance(
        bundle=sample_bundle(), repo_root=tmp_path, result_dir=result_dir,
        artifact_path=artifact, firmware_sha256=digest, source_build_run_id=None,
        source_build_number=1, source_build_manifest_path=manifest_path,
        allow_untracked_artifact=False,
    )
    assert provenance.return_code == 0
    assert provenance.current_build_fingerprint is None
    assert "ELF SHA-256" in provenance.message
