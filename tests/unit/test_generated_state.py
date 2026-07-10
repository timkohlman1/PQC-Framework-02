from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_PATH = REPO_ROOT / "scripts"
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))

from framework.generated_state import (
    GeneratedStateError,
    build_identity,
    fingerprint_paths,
    key_tuple_fingerprint,
    preflight_generated_state,
    record_generated_state_success,
    require_any_recorded_artifact,
    require_recorded_artifact,
)


def _identity(tmp_path: Path, profile: str = "Debug", *, container: bool = False):
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    return build_identity(
        workflow="stm32_cmake",
        profile=profile,
        input_fingerprint=fingerprint_paths([source], repo_root=tmp_path),
        toolchain={"command": ["cmake"], "version": "test"},
        execution={"host_system": "test", "container": container},
    )


def test_same_profile_state_is_reused(tmp_path: Path):
    artifact = tmp_path / "build" / "Debug" / "app.elf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"elf")
    identity = _identity(tmp_path)
    record_generated_state_success(repo_root=tmp_path, scope="cmake-Debug", identity=identity, artifacts=[artifact])

    result = preflight_generated_state(
        repo_root=tmp_path,
        scope="cmake-Debug",
        expected_identity=identity,
        cleanup_paths=[artifact.parent],
        final_artifact_paths=[artifact],
    )

    assert result.compatible is True
    assert artifact.read_bytes() == b"elf"
    assert not result.removed_paths


def test_profile_switch_removes_stale_generated_state_and_final_artifact(tmp_path: Path):
    artifact = tmp_path / "build" / "Debug" / "app.elf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"old")
    record_generated_state_success(repo_root=tmp_path, scope="cmake-Debug", identity=_identity(tmp_path, "Debug"), artifacts=[artifact])

    result = preflight_generated_state(
        repo_root=tmp_path,
        scope="cmake-Debug",
        expected_identity=_identity(tmp_path, "Release"),
        cleanup_paths=[artifact.parent],
        final_artifact_paths=[artifact],
    )

    assert result.compatible is False
    assert not artifact.exists()
    assert artifact.parent in result.removed_paths


def test_host_container_mismatch_invalidates_state(tmp_path: Path):
    artifact = tmp_path / "build" / "Debug" / "app.elf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"old")
    record_generated_state_success(repo_root=tmp_path, scope="cmake-Debug", identity=_identity(tmp_path, container=False), artifacts=[artifact])

    result = preflight_generated_state(
        repo_root=tmp_path,
        scope="cmake-Debug",
        expected_identity=_identity(tmp_path, container=True),
        cleanup_paths=[artifact.parent],
        final_artifact_paths=[artifact],
    )

    assert result.reason == "identity_mismatch"
    assert not artifact.exists()


def test_failed_build_cannot_leave_trusted_stale_artifact(tmp_path: Path):
    artifact = tmp_path / "build" / "Debug" / "app.elf"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"stale")

    preflight_generated_state(
        repo_root=tmp_path,
        scope="cmake-Debug",
        expected_identity=_identity(tmp_path),
        cleanup_paths=[artifact.parent],
        final_artifact_paths=[artifact],
    )

    assert not artifact.exists()
    with pytest.raises(GeneratedStateError, match="No successful"):
        require_recorded_artifact(repo_root=tmp_path, scope="cmake-Debug", artifact_path=artifact)


def test_key_tuple_reports_incomplete_and_changes_on_keystore_mismatch(tmp_path: Path):
    private_key = tmp_path / "private.der"
    public_key = tmp_path / "public.der"
    keystore = tmp_path / "keystore.c"
    private_key.write_bytes(b"private")
    public_key.write_bytes(b"public")

    incomplete = key_tuple_fingerprint(private_key=private_key, public_key=public_key, keystore=keystore)
    assert incomplete["status"] == "incomplete"

    keystore.write_bytes(b"tuple-a")
    first = key_tuple_fingerprint(private_key=private_key, public_key=public_key, keystore=keystore)
    keystore.write_bytes(b"tuple-b")
    second = key_tuple_fingerprint(private_key=private_key, public_key=public_key, keystore=keystore)
    assert first["status"] == "complete"
    assert first["tuple_sha256"] != second["tuple_sha256"]


def test_cleanup_refuses_canonical_secret_paths(tmp_path: Path):
    secret = tmp_path / "secrets" / "wolfboot" / "private.der"
    secret.parent.mkdir(parents=True)
    secret.write_bytes(b"secret")
    with pytest.raises(GeneratedStateError, match="canonical secret"):
        preflight_generated_state(
            repo_root=tmp_path,
            scope="unsafe",
            expected_identity=_identity(tmp_path),
            cleanup_paths=[secret],
        )
    assert secret.exists()


def test_downstream_consumption_requires_success_record_and_current_hash(tmp_path: Path):
    artifact = tmp_path / "signed.bin"
    artifact.write_bytes(b"signed")
    identity = build_identity(
        workflow="application_signing",
        profile="ecc256",
        input_fingerprint={"fingerprint": "input"},
        toolchain={"command": ["sign"]},
        execution={"host_system": "test"},
    )
    record_generated_state_success(repo_root=tmp_path, scope="signing-ecc256", identity=identity, artifacts=[artifact])
    assert require_any_recorded_artifact(repo_root=tmp_path, artifact_path=artifact, workflow="application_signing")["status"] == "success"

    artifact.write_bytes(b"tampered")
    with pytest.raises(GeneratedStateError, match="not backed"):
        require_any_recorded_artifact(repo_root=tmp_path, artifact_path=artifact, workflow="application_signing")
