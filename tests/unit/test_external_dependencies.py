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

from framework.external_dependencies import (
    ExternalDependencyError,
    prepare_mqtt_tls_material,
)


def _bundle(
    *,
    tls_version: str = "tls1.3",
    certificate_profile: str = "stepca-classical",
    ca_algorithm: str = "classical-x509",
    leaf_algorithm: str = "classical",
    signature_algorithm: str = "classical",
) -> dict[str, dict[str, object]]:
    return {
        "experiment": {
            "mqtt": {
                "tls": {
                    "mode": "pqc_hybrid_server_auth",
                    "tls_version": tls_version,
                    "certificate_profile": certificate_profile,
                    "certificate_authority_algorithm": ca_algorithm,
                    "server_certificate_algorithm": leaf_algorithm,
                    "server_signature_algorithm": signature_algorithm,
                }
            }
        }
    }


def _write_staged_stepca_tuple(
    repo_root: Path,
    *,
    source: str = "framework/certs",
    ca_hash_override: str | None = None,
) -> Path:
    canonical = repo_root / "secrets" / "mqtt" / "stepca-classical"
    canonical.mkdir(parents=True, exist_ok=True)
    files = {
        "ca.crt": b"test root ca\n",
        "root-ca.crt": b"test root ca\n",
        "intermediate-ca.crt": b"test intermediate ca\n",
        "ca-chain.crt": b"test chain\n",
        "server.crt": b"test server certificate\n",
        "server.key": b"test server private key\n",
    }
    hashes: dict[str, str] = {}
    for name, content in files.items():
        path = canonical / name
        path.write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    provenance = {
        "schema_version": 2,
        "profile_id": "stepca-classical",
        "profile_kind": "stepca-classical",
        "source": source,
        "ca_algorithm": "classical-x509",
        "leaf_algorithm": "classical",
        "ca_sha256": ca_hash_override or hashes["ca.crt"],
        "files": hashes,
    }
    (canonical / "certificate-provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    return canonical


def test_stepca_material_is_synchronized_and_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    commands: list[list[str]] = []

    def fake_run(command: list[str], repo_root: Path, log_path: Path) -> None:
        commands.append(command)
        _write_staged_stepca_tuple(repo_root)
        log_path.write_text("synchronized", encoding="utf-8")

    monkeypatch.setattr("framework.external_dependencies._run_logged", fake_run)

    resolved = prepare_mqtt_tls_material(
        bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
    )

    assert resolved is not None
    assert resolved.profile_id == "stepca-classical"
    assert resolved.profile_kind == "stepca-classical"
    assert resolved.ca_algorithm == "classical-x509"
    assert resolved.leaf_algorithm == "classical"
    assert resolved.provisioned is True
    assert commands
    assert commands[0][-3:] == [
        "provision-certs",
        "--certificate-profile",
        "stepca-classical",
    ]
    retained = result_dir / "cryptographic-material/mqtt/stepca-classical"
    assert (retained / "server.key").read_bytes() == b"test server private key\n"
    inventory = json.loads((result_dir / "material-inventory.json").read_text(encoding="utf-8"))
    server_key = next(item for item in inventory["materials"] if item["path"].endswith("server.key"))
    assert server_key["private"] is True
    assert "broker_installation" in server_key["required_for"]


def test_stepca_sync_missing_required_outputs_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    def fake_run(command: list[str], repo_root: Path, log_path: Path) -> None:
        canonical = repo_root / "secrets" / "mqtt" / "stepca-classical"
        canonical.mkdir(parents=True)
        (canonical / "ca.crt").write_text("partial", encoding="utf-8")
        log_path.write_text("partial synchronization", encoding="utf-8")

    monkeypatch.setattr("framework.external_dependencies._run_logged", fake_run)

    with pytest.raises(
        ExternalDependencyError, match="synchronization completed without required material"
    ):
        prepare_mqtt_tls_material(
            bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
        )


def test_stepca_provenance_ca_hash_mismatch_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    def fake_run(command: list[str], repo_root: Path, log_path: Path) -> None:
        _write_staged_stepca_tuple(repo_root, ca_hash_override="0" * 64)
        log_path.write_text("synchronized", encoding="utf-8")

    monkeypatch.setattr("framework.external_dependencies._run_logged", fake_run)

    with pytest.raises(ExternalDependencyError, match="root CA hash"):
        prepare_mqtt_tls_material(
            bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
        )


def test_non_framework_certificate_source_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    def fake_run(command: list[str], repo_root: Path, log_path: Path) -> None:
        _write_staged_stepca_tuple(repo_root, source="local-openssl")
        log_path.write_text("synchronized", encoding="utf-8")

    monkeypatch.setattr("framework.external_dependencies._run_logged", fake_run)

    with pytest.raises(ExternalDependencyError, match="not sourced from framework/certs"):
        prepare_mqtt_tls_material(
            bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
        )


@pytest.mark.parametrize("tls_version", ["", "tls1.2", "tlsv1.2"])
def test_mqtt_tls_versions_other_than_tls13_are_rejected(
    tmp_path: Path, tls_version: str
) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    with pytest.raises(ExternalDependencyError, match="must use TLS 1.3"):
        prepare_mqtt_tls_material(
            bundle=_bundle(tls_version=tls_version),
            repo_root=tmp_path,
            result_dir=result_dir,
        )


def test_mldsa65_material_is_synchronized_and_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()

    def fake_run(command: list[str], repo_root: Path, log_path: Path) -> None:
        canonical = repo_root / "secrets" / "mqtt" / "mldsa65-pqc"
        canonical.mkdir(parents=True, exist_ok=True)
        files = {
            "ca.crt": b"mldsa root\n",
            "root-ca.crt": b"mldsa root\n",
            "intermediate-ca.crt": b"mldsa intermediate\n",
            "ca-chain.crt": b"mldsa chain\n",
            "server.crt": b"mldsa server\n",
            "server.key": b"mldsa server key\n",
        }
        hashes = {}
        for name, content in files.items():
            (canonical / name).write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        (canonical / "certificate-provenance.json").write_text(
            json.dumps({
                "schema_version": 3,
                "profile_id": "mldsa65-pqc",
                "profile_kind": "mldsa65-pqc",
                "source": "framework/certs",
                "ca_algorithm": "mldsa65-x509",
                "leaf_algorithm": "mldsa65",
                "ca_sha256": hashes["ca.crt"],
                "files": hashes,
            }),
            encoding="utf-8",
        )
        log_path.write_text("synchronized", encoding="utf-8")

    monkeypatch.setattr("framework.external_dependencies._run_logged", fake_run)
    resolved = prepare_mqtt_tls_material(
        bundle=_bundle(
            certificate_profile="mldsa65-pqc",
            ca_algorithm="mldsa65-x509",
            leaf_algorithm="mldsa65",
            signature_algorithm="mldsa65",
        ),
        repo_root=tmp_path,
        result_dir=result_dir,
    )
    assert resolved is not None
    assert resolved.profile_kind == "mldsa65-pqc"
    assert resolved.ca_algorithm == "mldsa65-x509"
    assert resolved.leaf_algorithm == "mldsa65"


@pytest.mark.parametrize(
    ("certificate_profile", "ca_algorithm", "leaf_algorithm"),
    [
        ("stepca-classical", "mldsa65-x509", "mldsa65"),
        ("mldsa65-pqc", "classical-x509", "classical"),
        ("unknown-profile", "classical-x509", "classical"),
    ],
)
def test_certificate_profile_algorithm_mismatches_are_rejected(
    tmp_path: Path, certificate_profile: str, ca_algorithm: str, leaf_algorithm: str
) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    with pytest.raises(ExternalDependencyError):
        prepare_mqtt_tls_material(
            bundle=_bundle(
                certificate_profile=certificate_profile,
                ca_algorithm=ca_algorithm,
                leaf_algorithm=leaf_algorithm,
            ),
            repo_root=tmp_path,
            result_dir=result_dir,
        )


def test_mldsa65_certificate_profile_requires_mldsa65_tls_signature(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    with pytest.raises(ExternalDependencyError, match="incompatible with server_signature_algorithm"):
        prepare_mqtt_tls_material(
            bundle=_bundle(
                certificate_profile="mldsa65-pqc",
                ca_algorithm="mldsa65-x509",
                leaf_algorithm="mldsa65",
                signature_algorithm="classical",
            ),
            repo_root=tmp_path,
            result_dir=result_dir,
        )
