from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def load_build_records_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "build_records.py"
    spec = importlib.util.spec_from_file_location("framework_build_records", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_bundle() -> dict[str, dict[str, object]]:
    return {
        "experiment": {
            "id": "baseline_direct_uart",
            "description": "Test experiment.",
            "board": "board_a",
            "host": "gateway",
            "firmware": {
                "mode": "direct_flash",
                "artifact": "build/Debug/stm32_basic_hal1.elf",
            },
            "uart": {
                "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
                "expected_tick_message": "tick",
            },
        },
        "board": {
            "id": "board_a",
            "name": "NUCLEO-L4R5ZI-P",
            "mcu": "STM32L4R5",
            "stlink": {"serial": "123"},
            "uart": {"baud": 115200},
        },
        "host": {
            "id": "gateway",
            "alias": "pqc-gateway1",
            "user": "timk",
            "flash": {"helper": "flash-stm32a"},
            "uart": {"device": "/dev/example", "baud": 115200},
        },
    }


def write_build_fingerprint_inputs(repo_root: Path) -> None:
    files = {
        "configs/experiments/baseline_direct_uart.yaml": "id: baseline_direct_uart\nboard: board_a\nhost: gateway\n",
        "configs/boards/board_a.yaml": "id: board_a\n",
        "configs/hosts/gateway.yaml": "id: gateway\n",
        "CMakeLists.txt": "cmake minimum\n",
        "CMakePresets.json": '{"version": 3}\n',
        "STM32L4R5XX_FLASH.ld": "flash linker script\n",
        "startup_stm32l4r5xx.s": "startup assembly\n",
        "stm32_basic_hal1.ioc": "CubeMX project source\n",
        "Core/Src/main.c": "int main(void) { return 0; }\n",
        "Core/Inc/main.h": "#pragma once\n",
        "Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c": "HAL driver source\n",
        "Drivers/CMSIS/Device/ST/STM32L4xx/Include/stm32l4r5xx.h": "CMSIS device header\n",
        "cmake/gcc-arm-none-eabi.cmake": "toolchain config\n",
    }

    for relative_path, content in files.items():
        path = repo_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def write_build_record(build_records, repo_root: Path, results_root: Path, build_number: int = 3) -> tuple[Path, dict[str, object]]:
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"verified firmware")
    fingerprint = build_records.calculate_default_build_fingerprint(sample_bundle(), repo_root)
    firmware_sha256 = hashlib.sha256(b"verified firmware").hexdigest()
    source_run_dir = results_root / "2026-06-25_001_baseline_direct_uart"
    source_run_dir.mkdir(parents=True, exist_ok=True)
    build_log = source_run_dir / "build.log"
    build_log.write_text("build log\n", encoding="utf-8")
    record_dir, manifest = build_records.write_build_record(
        bundle=sample_bundle(),
        result_dir=source_run_dir,
        build_number=build_number,
        firmware_elf_path=artifact,
        firmware_artifact="build/Debug/stm32_basic_hal1.elf",
        firmware_artifact_path=str(artifact),
        firmware_sha256=firmware_sha256,
        source={"git_commit": "abc", "git_dirty": False, "git_status_available": True},
        build={
            "return_code": 0,
            "fingerprint": fingerprint.fingerprint,
            "fingerprint_inputs": fingerprint.inputs,
            "fingerprint_algorithm": fingerprint.algorithm,
            "skipped": False,
            "force": False,
        },
        source_run_id="2026-06-25_001_baseline_direct_uart",
        build_log_path=build_log,
    )
    return record_dir, manifest


def test_resolve_verified_build_record_accepts_valid_reference(tmp_path):
    build_records = load_build_records_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    record_dir, manifest = write_build_record(build_records, repo_root, results_root, 3)

    result = build_records.resolve_verified_build_record(
        results_root=results_root,
        build_number=3,
        bundle=sample_bundle(),
        repo_root=repo_root,
    )

    assert result.return_code == 0
    assert result.status == "verified_build_record"
    assert result.build_number == 3
    assert result.record_dir == record_dir
    assert result.manifest_path == record_dir / "manifest.json"
    assert result.artifact_path == record_dir / "firmware.elf"
    assert result.firmware_sha256 == manifest["firmware"]["sha256"]
    assert result.build_fingerprint == manifest["build"]["fingerprint"]


def test_resolve_verified_build_record_refuses_missing_record(tmp_path):
    build_records = load_build_records_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)

    result = build_records.resolve_verified_build_record(
        results_root=results_root,
        build_number=99,
        bundle=sample_bundle(),
        repo_root=repo_root,
    )

    assert result.return_code == build_records.BUILD_RECORD_MISSING_RETURN_CODE
    assert result.status == "missing_build_record"
    assert "manifest not found" in result.message


def test_resolve_verified_build_record_refuses_missing_artifact(tmp_path):
    build_records = load_build_records_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    record_dir, _ = write_build_record(build_records, repo_root, results_root, 3)
    (record_dir / "firmware.elf").unlink()

    result = build_records.resolve_verified_build_record(
        results_root=results_root,
        build_number=3,
        bundle=sample_bundle(),
        repo_root=repo_root,
    )

    assert result.return_code == build_records.BUILD_RECORD_MISSING_RETURN_CODE
    assert result.status == "missing_build_record"
    assert "firmware artifact not found" in result.message


def test_resolve_verified_build_record_refuses_artifact_hash_mismatch(tmp_path):
    build_records = load_build_records_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    record_dir, _ = write_build_record(build_records, repo_root, results_root, 3)
    (record_dir / "firmware.elf").write_bytes(b"tampered firmware")

    result = build_records.resolve_verified_build_record(
        results_root=results_root,
        build_number=3,
        bundle=sample_bundle(),
        repo_root=repo_root,
    )

    assert result.return_code == build_records.BUILD_RECORD_MISMATCH_RETURN_CODE
    assert result.status == "mismatched_build_record"
    assert "SHA-256 does not match" in result.message


def test_resolve_verified_build_record_refuses_source_hash_mismatch(tmp_path):
    build_records = load_build_records_module()
    repo_root = tmp_path / "repo"
    results_root = tmp_path / "results"
    repo_root.mkdir()
    write_build_fingerprint_inputs(repo_root)
    record_dir, _ = write_build_record(build_records, repo_root, results_root, 3)
    manifest_path = record_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["build"]["fingerprint"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = build_records.resolve_verified_build_record(
        results_root=results_root,
        build_number=3,
        bundle=sample_bundle(),
        repo_root=repo_root,
    )

    assert result.return_code == build_records.BUILD_RECORD_MISMATCH_RETURN_CODE
    assert result.status == "mismatched_build_record"
    assert "fingerprint does not match" in result.message
