from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from framework import test_provenance
    return test_provenance


def test_test_run_and_build_identities_are_separate_from_normal_numbers(tmp_path):
    provenance = _module()
    run_id = provenance.safe_test_run_id(datetime(2026, 7, 19, tzinfo=timezone.utc), pid=42)
    run_dir = provenance.allocate_test_result_dir(tmp_path, run_id)
    first_id, first_dir = provenance.reserve_test_build_identity(run_dir)
    second_id, second_dir = provenance.reserve_test_build_identity(run_dir)

    assert run_dir == tmp_path / "results" / "automated-tests" / "pytest-2026-07-19T000000Z-42"
    assert first_id.endswith("-build-0001")
    assert second_id.endswith("-build-0002")
    assert first_dir.name == "0001"
    assert second_dir.name == "0002"
    assert not (tmp_path / ".build_number").exists()


def test_atomic_manifest_redacts_secret_fields(tmp_path):
    provenance = _module()
    path = tmp_path / "manifest.json"
    provenance.write_json_atomic(path, {
        "record_type": "automated_test_run",
        "mqtt_password": "do-not-retain",
        "nested": {"api_token": "do-not-retain", "public_hash": "abc"},
    })
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mqtt_password"] == "redacted"
    assert data["nested"]["api_token"] == "redacted"
    assert data["nested"]["public_hash"] == "abc"


def test_build_purpose_defaults_to_normal_and_accepts_pytest_scope(monkeypatch):
    provenance = _module()
    monkeypatch.delenv("PQC_BUILD_PURPOSE", raising=False)
    assert provenance.current_build_purpose() == "experiment"
    monkeypatch.setenv("PQC_BUILD_PURPOSE", "automated_test")
    assert provenance.current_build_purpose() == "automated_test"


def test_build_source_keeps_automated_test_build_identity_separate():
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "scripts" / "framework" / "build.py").read_text(encoding="utf-8")
    assert "build_purpose == TEST_BUILD_PURPOSE" in source
    assert "reserve_test_build_identity(test_result_dir)" in source
    assert "reserve_next_build_number(repo_root_path)" in source
    assert '"record_type": "automated_test_build"' in source
    assert '"reusable_by_normal_workflows": False' in source
    assert '"reuse_enabled": False' in source
