from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_build_state_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "build_state.py"
    spec = importlib.util.spec_from_file_location("framework_build_state", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_state(build_state):
    return build_state.build_last_successful_build_state(
        run_id="2026-06-25_001_baseline_direct_uart",
        build_number=1,
        build_fingerprint="a" * 64,
        build_fingerprint_algorithm="sha256-build-inputs-v1",
        build_fingerprint_inputs=["CMakeLists.txt", "Core/Src/main.c"],
        firmware_artifact="build/Debug/stm32_basic_hal1.elf",
        firmware_artifact_path="/repo/build/Debug/stm32_basic_hal1.elf",
        firmware_sha256="b" * 64,
        result_artifacts={
            "elf": {
                "source_path": "/repo/build/Debug/stm32_basic_hal1.elf",
                "path": "firmware.elf",
                "artifact_path": "/repo/results/run/firmware.elf",
                "sha256": "b" * 64,
                "copied": True,
                "missing_reason": None,
            }
        },
        updated_at=datetime(2026, 6, 25, 10, 30, tzinfo=timezone.utc),
    )


def test_missing_last_successful_build_state_returns_none(tmp_path):
    build_state = load_build_state_module()

    assert build_state.read_last_successful_build_state(tmp_path) is None


def test_write_and_read_last_successful_build_state(tmp_path):
    build_state = load_build_state_module()
    state = sample_state(build_state)

    path = build_state.write_last_successful_build_state(tmp_path, state)
    read_back = build_state.read_last_successful_build_state(tmp_path)

    assert path == tmp_path / ".last_successful_build.json"
    assert read_back == state
    assert json.loads(path.read_text(encoding="utf-8"))["build"]["fingerprint"] == "a" * 64


def test_invalid_json_last_successful_build_state_fails_clearly(tmp_path):
    build_state = load_build_state_module()
    (tmp_path / ".last_successful_build.json").write_text("not json\n", encoding="utf-8")

    try:
        build_state.read_last_successful_build_state(tmp_path)
    except build_state.BuildHashStateError as exc:
        assert "not valid JSON" in str(exc)
    else:
        raise AssertionError("invalid JSON state must raise BuildHashStateError")


def test_invalid_schema_last_successful_build_state_fails_clearly(tmp_path):
    build_state = load_build_state_module()
    (tmp_path / ".last_successful_build.json").write_text(
        json.dumps({"schema_version": 1, "updated_at": "2026-06-25T10:30:00+00:00"}) + "\n",
        encoding="utf-8",
    )

    try:
        build_state.read_last_successful_build_state(tmp_path)
    except build_state.BuildHashStateError as exc:
        assert "build" in str(exc)
    else:
        raise AssertionError("invalid schema state must raise BuildHashStateError")
