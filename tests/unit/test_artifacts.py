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
