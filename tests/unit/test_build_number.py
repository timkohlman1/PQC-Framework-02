from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_build_number_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "build_number.py"
    spec = importlib.util.spec_from_file_location("framework_build_number", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reserve_next_build_number_starts_at_one(tmp_path):
    build_number = load_build_number_module()

    assert build_number.reserve_next_build_number(tmp_path) == 1
    assert (tmp_path / ".build_number").read_text(encoding="utf-8") == "1\n"


def test_reserve_next_build_number_increments_existing_value(tmp_path):
    build_number = load_build_number_module()
    (tmp_path / ".build_number").write_text("41\n", encoding="utf-8")

    assert build_number.reserve_next_build_number(tmp_path) == 42
    assert (tmp_path / ".build_number").read_text(encoding="utf-8") == "42\n"


def test_reserve_next_build_number_rejects_malformed_file(tmp_path):
    build_number = load_build_number_module()
    (tmp_path / ".build_number").write_text("not an integer\n", encoding="utf-8")

    try:
        build_number.reserve_next_build_number(tmp_path)
    except build_number.BuildNumberError as exc:
        assert "non-integer" in str(exc)
    else:
        raise AssertionError("malformed build number file should fail")
