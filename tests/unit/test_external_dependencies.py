from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.framework.external_dependencies import (
    ExternalDependencyError,
    prepare_mqtt_tls_material,
    resolve_signing_material,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prepare_mqtt_tls_material_reuses_complete_canonical_tuple(tmp_path):
    cert_dir = tmp_path / "secrets/mqtt/server-ecdsa-p256"
    cert_dir.mkdir(parents=True)
    for name in ("ca.key", "server.crt", "server.key"):
        (cert_dir / name).write_text(name, encoding="utf-8")
    ca = cert_dir / "ca.crt"
    ca.write_text("public-ca", encoding="utf-8")
    provenance = cert_dir / "certificate-provenance.json"
    provenance.write_text(json.dumps({"profile_id": "server-ecdsa-p256", "ca_algorithm": "ecdsa-p256", "leaf_algorithm": "ecdsa-p256", "ca_sha256": _sha(ca)}), encoding="utf-8")
    result_dir = tmp_path / "results/run"
    result_dir.mkdir(parents=True)
    bundle = {"experiment": {"mqtt": {"tls": {"mode": "classical_tls_server_auth", "certificate_profile": "server-ecdsa-p256", "certificate_authority_algorithm": "ecdsa-p256", "server_certificate_algorithm": "ecdsa-p256"}}}}

    context = prepare_mqtt_tls_material(bundle=bundle, repo_root=tmp_path, result_dir=result_dir)

    assert context is not None
    assert context.provisioned is False
    assert context.ca_certificate == ca
    assert context.ca_sha256 == _sha(ca)


def test_prepare_mqtt_tls_material_rejects_partial_tuple(tmp_path):
    cert_dir = tmp_path / "secrets/mqtt/server-ecdsa-p256"
    cert_dir.mkdir(parents=True)
    (cert_dir / "ca.crt").write_text("public-ca", encoding="utf-8")
    result_dir = tmp_path / "results/run"
    result_dir.mkdir(parents=True)
    bundle = {"experiment": {"mqtt": {"tls": {"mode": "classical_tls_server_auth", "certificate_profile": "server-ecdsa-p256", "certificate_authority_algorithm": "ecdsa-p256", "server_certificate_algorithm": "ecdsa-p256"}}}}

    with pytest.raises(ExternalDependencyError, match="partial"):
        prepare_mqtt_tls_material(bundle=bundle, repo_root=tmp_path, result_dir=result_dir)


def test_prepare_mqtt_tls_material_rejects_provenance_hash_mismatch(tmp_path):
    cert_dir = tmp_path / "secrets/mqtt/server-ecdsa-p256"
    cert_dir.mkdir(parents=True)
    for name in ("ca.key", "server.crt", "server.key"):
        (cert_dir / name).write_text(name, encoding="utf-8")
    (cert_dir / "ca.crt").write_text("public-ca", encoding="utf-8")
    (cert_dir / "certificate-provenance.json").write_text(json.dumps({"profile_id": "server-ecdsa-p256", "ca_algorithm": "ecdsa-p256", "leaf_algorithm": "ecdsa-p256", "ca_sha256": "0" * 64}), encoding="utf-8")
    result_dir = tmp_path / "results/run"
    result_dir.mkdir(parents=True)
    bundle = {"experiment": {"mqtt": {"tls": {"mode": "classical_tls_server_auth", "certificate_profile": "server-ecdsa-p256", "certificate_authority_algorithm": "ecdsa-p256", "server_certificate_algorithm": "ecdsa-p256"}}}}

    with pytest.raises(ExternalDependencyError, match="hash"):
        prepare_mqtt_tls_material(bundle=bundle, repo_root=tmp_path, result_dir=result_dir)


def test_resolve_signing_material_rejects_path_outside_secrets(tmp_path):
    profile = {
        "private_key": "elsewhere/private_key.der",
        "signing_tuple": {"tuple_id": "bad", "directory": "elsewhere", "public_key": "public_key.der", "manifest": "tuple.json"},
    }
    with pytest.raises(ExternalDependencyError, match="below secrets"):
        resolve_signing_material(profile=profile, repo_root=tmp_path)


def test_resolve_signing_material_returns_complete_tuple(tmp_path):
    directory = tmp_path / "secrets/wolfboot/tuples/test"
    directory.mkdir(parents=True)
    for name in ("private_key.der", "public_key.der", "tuple.json"):
        (directory / name).write_text(name, encoding="utf-8")
    profile = {
        "private_key": "secrets/wolfboot/tuples/test/private_key.der",
        "signing_tuple": {"tuple_id": "test", "directory": "secrets/wolfboot/tuples/test", "public_key": "public_key.der", "manifest": "tuple.json"},
    }
    context = resolve_signing_material(profile=profile, repo_root=tmp_path)
    assert context.tuple_id == "test"
    assert context.private_key == directory / "private_key.der"


def test_prepare_mqtt_tls_material_rejects_algorithm_mismatch(tmp_path):
    cert_dir = tmp_path / "secrets/mqtt/server-mldsa65"
    cert_dir.mkdir(parents=True)
    for name in ("ca.key", "server.crt", "server.key"):
        (cert_dir / name).write_text(name, encoding="utf-8")
    ca = cert_dir / "ca.crt"
    ca.write_text("public-ca", encoding="utf-8")
    (cert_dir / "certificate-provenance.json").write_text(json.dumps({
        "profile_id": "server-mldsa65",
        "ca_algorithm": "mldsa44",
        "leaf_algorithm": "mldsa44",
        "ca_sha256": _sha(ca),
    }), encoding="utf-8")
    result_dir = tmp_path / "results/run"
    result_dir.mkdir(parents=True)
    bundle = {"experiment": {"mqtt": {"tls": {
        "mode": "pqc_hybrid_tls_server_auth",
        "certificate_profile": "server-mldsa65",
        "certificate_authority_algorithm": "mldsa65",
        "server_certificate_algorithm": "mldsa65",
        "key_exchange_group": "SecP256r1MLKEM768",
    }}}}
    with pytest.raises(ExternalDependencyError, match="algorithm"):
        prepare_mqtt_tls_material(bundle=bundle, repo_root=tmp_path, result_dir=result_dir)
