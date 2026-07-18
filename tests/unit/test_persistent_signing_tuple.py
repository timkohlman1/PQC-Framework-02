from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def _module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    return importlib.import_module("framework.wolfboot_build")


def _profile() -> dict[str, object]:
    return {
        "id": "wolfboot_test",
        "description": "test",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "test",
        "signature_algorithm": "ecdsa_p256",
        "build": {
            "command": "make",
            "signing_key": "secrets/wolfboot/tuples/ecdsa-p256-development/private_key.der",
            "wolfboot_private_key": "tools/wolfboot/wolfboot_signing_private_key.der",
            "generated_keystore": "tools/wolfboot/src/keystore.c",
            "signing_tuple": {
                "tuple_id": "ecdsa-p256-development",
                "directory": "secrets/wolfboot/tuples/ecdsa-p256-development",
            },
        },
    }


def _write_manifest(module, paths):
    paths["manifest"].write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tuple_id": "ecdsa-p256-development",
                "signature_algorithm": "ecdsa_p256",
                "private_key_sha256": module._tuple_sha256(paths["private_key"]),
                "keystore_sha256": module._tuple_sha256(paths["keystore"]),
            }
        ),
        encoding="utf-8",
    )


def test_complete_persistent_tuple_rematerializes_actual_wolfboot_outputs(tmp_path):
    module = _module()
    repo = tmp_path / "repo"
    source = repo / "tools/wolfboot"
    paths = module._signing_tuple_paths(profile=_profile(), repo_root=repo, source_dir=source)
    assert paths is not None
    assert "public_key" not in paths
    paths["directory"].mkdir(parents=True)
    paths["private_key"].write_bytes(b"private")
    paths["keystore"].write_text("keystore", encoding="utf-8")
    _write_manifest(module, paths)

    resolved, error = module._prepare_persistent_signing_tuple(
        profile=_profile(), repo_root=repo, source_dir=source
    )

    assert error is None
    assert resolved is not None
    assert paths["materialized_private_key"].read_bytes() == b"private"
    assert paths["materialized_keystore"].read_text(encoding="utf-8") == "keystore"


def test_partial_persistent_tuple_fails_without_materializing(tmp_path):
    module = _module()
    repo = tmp_path / "repo"
    source = repo / "tools/wolfboot"
    paths = module._signing_tuple_paths(profile=_profile(), repo_root=repo, source_dir=source)
    assert paths is not None
    paths["directory"].mkdir(parents=True)
    paths["private_key"].write_bytes(b"private")

    _, error = module._prepare_persistent_signing_tuple(
        profile=_profile(), repo_root=repo, source_dir=source
    )

    assert error is not None
    assert "partial" in error
    assert not paths["materialized_private_key"].exists()


def test_absent_tuple_removes_disposable_material_and_creates_parent_on_persist(tmp_path):
    module = _module()
    repo = tmp_path / "repo"
    source = repo / "tools/wolfboot"
    paths = module._signing_tuple_paths(profile=_profile(), repo_root=repo, source_dir=source)
    assert paths is not None
    paths["materialized_private_key"].parent.mkdir(parents=True)
    paths["materialized_private_key"].write_bytes(b"stale")
    paths["materialized_keystore"].parent.mkdir(parents=True)
    paths["materialized_keystore"].write_text("stale", encoding="utf-8")

    _, error = module._prepare_persistent_signing_tuple(
        profile=_profile(), repo_root=repo, source_dir=source
    )

    assert error is None
    assert not paths["materialized_private_key"].exists()
    assert not paths["materialized_keystore"].exists()

    paths["materialized_private_key"].write_bytes(b"generated-private")
    paths["materialized_keystore"].parent.mkdir(parents=True, exist_ok=True)
    paths["materialized_keystore"].write_text("generated-keystore", encoding="utf-8")

    error = module._persist_generated_tuple_atomically(profile=_profile(), paths=paths)

    assert error is None
    assert paths["directory"].is_dir()
    assert paths["private_key"].read_bytes() == b"generated-private"
    assert paths["keystore"].read_text(encoding="utf-8") == "generated-keystore"
    assert paths["manifest"].is_file()
