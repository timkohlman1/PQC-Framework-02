import hashlib
import json
from pathlib import Path

from framework import build_records


def sample_bundle():
    return {
        "experiment": {"id": "baseline", "firmware": {"artifact": "build/Debug/app.elf"}},
        "board": {"id": "board_a"},
        "host": {"id": "gateway"},
    }


def write_record(tmp_path: Path, *, content: bytes = b"elf", experiment: str = "baseline"):
    record_dir = tmp_path / "results" / "builds" / "1"
    record_dir.mkdir(parents=True)
    artifact = record_dir / "firmware.elf"
    artifact.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    manifest = {
        "schema_version": 1,
        "record_type": "build",
        "build_number": 1,
        "experiment": experiment,
        "board": "board_a",
        "build": {"reuse_enabled": False, "artifact_identity_algorithm": "sha256-elf", "artifact_identity": digest},
        "firmware": {"sha256": digest, "result_artifacts": {"elf": {"path": "firmware.elf"}}},
    }
    (record_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return record_dir, artifact, digest


def test_resolve_verified_build_record_accepts_matching_elf(tmp_path):
    _, artifact, digest = write_record(tmp_path)
    result = build_records.resolve_verified_build_record(results_root=tmp_path / "results", build_number=1, bundle=sample_bundle(), repo_root=tmp_path)
    assert result.return_code == 0
    assert result.artifact_path == artifact
    assert result.firmware_sha256 == digest
    assert result.build_fingerprint is None


def test_resolve_verified_build_record_refuses_changed_elf(tmp_path):
    _, artifact, _ = write_record(tmp_path)
    artifact.write_bytes(b"changed")
    result = build_records.resolve_verified_build_record(results_root=tmp_path / "results", build_number=1, bundle=sample_bundle(), repo_root=tmp_path)
    assert result.return_code == build_records.BUILD_RECORD_MISMATCH_RETURN_CODE
    assert "SHA-256" in result.message


def test_resolve_verified_build_record_refuses_wrong_context(tmp_path):
    write_record(tmp_path, experiment="other")
    result = build_records.resolve_verified_build_record(results_root=tmp_path / "results", build_number=1, bundle=sample_bundle(), repo_root=tmp_path)
    assert result.return_code == build_records.BUILD_RECORD_MISMATCH_RETURN_CODE
