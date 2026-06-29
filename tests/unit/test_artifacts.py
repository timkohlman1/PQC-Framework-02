from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path


def load_artifacts_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "artifacts.py"
    spec = importlib.util.spec_from_file_location("framework_artifacts", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_calculate_file_sha256_uses_file_content(tmp_path):
    artifacts = load_artifacts_module()
    artifact = tmp_path / "firmware.elf"
    content = b"known firmware artifact bytes\n"
    artifact.write_bytes(content)

    assert artifacts.calculate_file_sha256(artifact) == hashlib.sha256(content).hexdigest()


def test_copy_firmware_artifacts_uses_canonical_names_and_hashes(tmp_path):
    artifacts = load_artifacts_module()
    build_dir = tmp_path / "build" / "Debug"
    result_dir = tmp_path / "results" / "run"
    build_dir.mkdir(parents=True)
    elf = build_dir / "stm32_basic_hal1.elf"
    hex_file = build_dir / "stm32_basic_hal1.hex"
    elf.write_bytes(b"elf bytes")
    hex_file.write_bytes(b"hex bytes")

    copied = artifacts.copy_firmware_artifacts_to_result(elf, result_dir)

    assert (result_dir / "firmware.elf").read_bytes() == b"elf bytes"
    assert (result_dir / "firmware.hex").read_bytes() == b"hex bytes"
    assert not (result_dir / "firmware.bin").exists()
    assert copied["elf"]["path"] == "firmware.elf"
    assert copied["elf"]["copied"] is True
    assert copied["elf"]["sha256"] == hashlib.sha256(b"elf bytes").hexdigest()
    assert copied["hex"]["path"] == "firmware.hex"
    assert copied["hex"]["copied"] is True
    assert copied["bin"]["path"] is None
    assert copied["bin"]["copied"] is False
    assert copied["bin"]["missing_reason"] == "source artifact not generated"
