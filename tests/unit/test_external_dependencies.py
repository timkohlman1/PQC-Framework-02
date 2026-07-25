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


def _bundle() -> dict[str, dict[str, object]]:
    return {
        "experiment": {
            "mqtt": {
                "tls": {
                    "mode": "pqc_hybrid_server_auth",
                    "certificate_profile": "server-mldsa65",
                    "certificate_authority_algorithm": "mldsa65",
                    "server_certificate_algorithm": "mldsa65",
                }
            }
        }
    }


def _write_public_oqs_tuple(
    repo_root: Path,
    *,
    ca_algorithm: str | None = "mldsa65",
    leaf_algorithm: str | None = "mldsa65",
) -> Path:
    canonical = repo_root / "secrets" / "mqtt" / "server-mldsa65"
    canonical.mkdir(parents=True)
    ca = canonical / "ca.crt"
    ca.write_text("test oqs ca\n", encoding="utf-8")
    provenance = {
        "schema_version": 1,
        "profile_id": "server-mldsa65",
        "profile_kind": "oqs",
        "ca_sha256": hashlib.sha256(ca.read_bytes()).hexdigest(),
        "remote_provenance_sha256": "a" * 64,
    }
    if ca_algorithm is not None:
        provenance["ca_algorithm"] = ca_algorithm
    if leaf_algorithm is not None:
        provenance["leaf_algorithm"] = leaf_algorithm
    (canonical / "certificate-provenance.json").write_text(
        json.dumps(provenance), encoding="utf-8"
    )
    return canonical


def test_oqs_public_only_local_tuple_is_complete(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    canonical = _write_public_oqs_tuple(tmp_path)

    resolved = prepare_mqtt_tls_material(
        bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
    )

    assert resolved is not None
    assert resolved.profile_kind == "oqs"
    assert resolved.canonical_directory == canonical.resolve()
    assert resolved.provisioned is False



def test_oqs_public_summary_without_algorithm_fields_is_accepted(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    _write_public_oqs_tuple(
        tmp_path, ca_algorithm=None, leaf_algorithm=None
    )

    resolved = prepare_mqtt_tls_material(
        bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
    )

    assert resolved is not None
    assert resolved.ca_algorithm == "mldsa65"
    assert resolved.leaf_algorithm == "mldsa65"

def test_oqs_absent_tuple_runs_provisioner_and_accepts_public_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    commands: list[list[str]] = []

    def fake_run(command: list[str], repo_root: Path, log_path: Path) -> None:
        commands.append(command)
        _write_public_oqs_tuple(repo_root)
        log_path.write_text("provisioned", encoding="utf-8")

    monkeypatch.setattr(
        "framework.external_dependencies._run_logged", fake_run
    )

    resolved = prepare_mqtt_tls_material(
        bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
    )

    assert resolved is not None
    assert resolved.provisioned is True
    assert commands
    assert "provision-oqs-certs" in commands[0]
    assert commands[0][-4:] == [
        "--ca-algorithm",
        "mldsa65",
        "--leaf-algorithm",
        "mldsa65",
    ]


@pytest.mark.parametrize("present_name", ["ca.crt", "certificate-provenance.json"])
def test_oqs_partial_public_tuple_is_rejected(
    tmp_path: Path, present_name: str
) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    canonical = tmp_path / "secrets" / "mqtt" / "server-mldsa65"
    canonical.mkdir(parents=True)
    (canonical / present_name).write_text("partial", encoding="utf-8")

    with pytest.raises(ExternalDependencyError, match="tuple is partial"):
        prepare_mqtt_tls_material(
            bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
        )


def test_oqs_provenance_algorithm_mismatch_is_rejected(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    _write_public_oqs_tuple(tmp_path, ca_algorithm="mldsa44")

    with pytest.raises(ExternalDependencyError, match="CA algorithm"):
        prepare_mqtt_tls_material(
            bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
        )


def test_oqs_present_leaf_algorithm_mismatch_is_rejected(tmp_path: Path) -> None:
    result_dir = tmp_path / "results"
    result_dir.mkdir()
    _write_public_oqs_tuple(tmp_path, leaf_algorithm="mldsa44")

    with pytest.raises(ExternalDependencyError, match="leaf algorithm"):
        prepare_mqtt_tls_material(
            bundle=_bundle(), repo_root=tmp_path, result_dir=result_dir
        )
