from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.external_dependencies import ExternalDependencyError, prepare_mqtt_tls_material


def _bundle(*, tls_version: str = "tls1.3", certificate_profile: str = "rsa3072", mutual: bool = False):
    return {
        "experiment": {
            "mqtt": {
                "tls": {
                    "mode": "pqc_hybrid_tls_mutual" if mutual else "pqc_hybrid_tls_server_auth",
                    "authentication": "mutual" if mutual else "server",
                    "tls_version": tls_version,
                    "certificate_profile": certificate_profile,
                }
            }
        }
    }


def _write_profile(repo_root: Path, profile: str = "rsa3072") -> Path:
    canonical = repo_root / "secrets" / "certificates" / profile
    canonical.mkdir(parents=True, exist_ok=True)
    files = {
        "ca.crt": b"root\n",
        "ca-chain.crt": b"chain\n",
        "server.crt": b"server\n",
        "server.key": b"server-key\n",
        "client.crt": b"client\n",
        "client.key": b"client-key\n",
        "healthcheck.crt": b"health\n",
        "healthcheck.key": b"health-key\n",
    }
    inventory = {}
    for name, content in files.items():
        (canonical / name).write_bytes(content)
        inventory[name] = hashlib.sha256(content).hexdigest()
    (canonical / "manifest.json").write_text(
        json.dumps({"schema_version": 2, "profile_id": profile, "files": inventory}),
        encoding="utf-8",
    )
    return canonical


def test_preprovisioned_material_is_resolved_without_generation(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    _write_profile(tmp_path)

    resolved = prepare_mqtt_tls_material(bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir)

    assert resolved is not None
    assert resolved.profile_id == "rsa3072"
    assert resolved.canonical_directory == tmp_path / "secrets" / "certificates" / "rsa3072"
    assert resolved.provisioned is False
    assert (result_dir / "cryptographic-material" / "mqtt" / "rsa3072" / "server.key").is_file()


def test_missing_profile_fails_with_manual_provisioning_command(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    with pytest.raises(ExternalDependencyError, match="scripts/provision_certificates.py"):
        prepare_mqtt_tls_material(bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir)


def test_manifest_integrity_mismatch_is_rejected(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    canonical = _write_profile(tmp_path)
    (canonical / "server.crt").write_text("tampered", encoding="utf-8")
    with pytest.raises(ExternalDependencyError, match="integrity validation"):
        prepare_mqtt_tls_material(bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir)


def test_manifest_profile_id_must_match_selected_profile(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    canonical = _write_profile(tmp_path)
    manifest = json.loads((canonical / "manifest.json").read_text(encoding="utf-8"))
    manifest["profile_id"] = "wrong"
    (canonical / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ExternalDependencyError, match="profile_id"):
        prepare_mqtt_tls_material(bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir)


def test_mutual_tls_requires_client_identity(tmp_path: Path):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    canonical = _write_profile(tmp_path)
    (canonical / "client.key").unlink()
    with pytest.raises(ExternalDependencyError, match="incomplete"):
        prepare_mqtt_tls_material(bundle=_bundle(mutual=True), repo_root=tmp_path, result_dir=result_dir)


@pytest.mark.parametrize("tls_version", ["", "tls1.2", "tlsv1.2"])
def test_mqtt_tls_versions_other_than_tls13_are_rejected(tmp_path: Path, tls_version: str):
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    with pytest.raises(ExternalDependencyError, match="must use TLS 1.3"):
        prepare_mqtt_tls_material(bundle=_bundle(tls_version=tls_version), repo_root=tmp_path, result_dir=result_dir)


@pytest.mark.parametrize("name", ["client.key", "manifest.json"])
def test_permission_error_is_a_prerequisite_failure_without_key_replacement(tmp_path, name):
    import os
    if os.geteuid() == 0:
        pytest.skip("permission denial requires a non-root process")
    canonical = _write_profile(tmp_path)
    blocked = canonical / name
    original = blocked.read_bytes()  # Synthetic test material only.
    blocked.chmod(0)
    try:
        with pytest.raises(ExternalDependencyError, match="access denied for UID") as failure:
            prepare_mqtt_tls_material(bundle=_bundle(), repo_root=tmp_path, result_dir=tmp_path / "result")
        assert name in str(failure.value)
        assert "Preserve existing keys" in str(failure.value)
        assert not (tmp_path / "result").exists()
    finally:
        blocked.chmod(0o600)
    assert blocked.read_bytes() == original
