from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from framework.wolfboot_build import (
    _derive_tuple_public_key,
    _migrate_optional_public_key,
)


def _keystore(public_key: bytes) -> str:
    values = ", ".join(f"0x{value:02x}" for value in public_key)
    return (
        "const struct keystore_slot PubKeys[1] = {\n"
        "  {\n"
        "    .pubkey_size = 64,\n"
        f"    .pubkey = {{ {values} }},\n"
        "  },\n"
        "};\n"
    )


def _profile() -> dict[str, object]:
    return {
        "signature_algorithm": "ecdsa_p256",
        "build": {
            "signing_tuple": {
                "public_key_export_format": "wolfboot_raw_ecc_xy",
                "public_key_size": 64,
            }
        },
    }


def test_raw_ecc_public_key_is_derived_without_rotating_private_key(tmp_path):
    public = bytes(range(64))
    private = public + bytes(range(32))
    private_path = tmp_path / "private_key.der"
    keystore_path = tmp_path / "keystore.c"
    private_path.write_bytes(private)
    keystore_path.write_text(_keystore(public), encoding="utf-8")
    original_private = private_path.read_bytes()
    original_mtime = private_path.stat().st_mtime_ns

    derived, error = _derive_tuple_public_key(
        profile=_profile(),
        private_key_path=private_path,
        keystore_path=keystore_path,
    )

    assert error is None
    assert derived == public
    assert private_path.read_bytes() == original_private
    assert private_path.stat().st_mtime_ns == original_mtime


def test_existing_tuple_is_migrated_with_public_key_and_manifest_hash(tmp_path):
    tuple_dir = tmp_path / "tuple"
    tuple_dir.mkdir()
    public = bytes(range(64))
    private = public + bytes(range(32))
    private_path = tuple_dir / "private_key.der"
    public_path = tuple_dir / "public_key.der"
    keystore_path = tuple_dir / "keystore.c"
    manifest_path = tuple_dir / "tuple.json"
    private_path.write_bytes(private)
    public_path.write_bytes(b"")
    keystore_path.write_text(_keystore(public), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "signature_algorithm": "ecdsa_p256",
                "private_key_sha256": "existing",
                "keystore_sha256": "existing",
            }
        ),
        encoding="utf-8",
    )
    original_private = private_path.read_bytes()
    original_mtime = private_path.stat().st_mtime_ns

    error = _migrate_optional_public_key(
        profile=_profile(),
        paths={
            "directory": tuple_dir,
            "private_key": private_path,
            "public_key": public_path,
            "keystore": keystore_path,
            "manifest": manifest_path,
        },
    )

    assert error is None
    assert public_path.read_bytes() == public
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["public_key_format"] == "wolfboot_raw_ecc_xy"
    assert manifest["public_key_size"] == 64
    assert len(manifest["public_key_sha256"]) == 64
    assert private_path.read_bytes() == original_private
    assert private_path.stat().st_mtime_ns == original_mtime


def test_migration_rejects_public_key_that_does_not_match_keystore(tmp_path):
    private_path = tmp_path / "private_key.der"
    keystore_path = tmp_path / "keystore.c"
    private_path.write_bytes(bytes(range(96)))
    keystore_path.write_text(_keystore(bytes(reversed(range(64)))), encoding="utf-8")

    derived, error = _derive_tuple_public_key(
        profile=_profile(),
        private_key_path=private_path,
        keystore_path=keystore_path,
    )

    assert derived is None
    assert error is not None
    assert "does not match" in error
