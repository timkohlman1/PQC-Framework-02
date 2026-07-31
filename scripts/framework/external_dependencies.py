"""Fail-closed external cryptographic prerequisite preparation.

Canonical private material lives below ``secrets/``. Runtime/build directories
may receive public or deployment copies, but are never authoritative inputs.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from framework.artifacts import copy_material_directory_to_result, write_material_inventory


class ExternalDependencyError(RuntimeError):
    """Raised when a declared external dependency cannot be prepared safely."""


@dataclass(frozen=True)
class ResolvedMqttTlsContext:
    profile_id: str
    profile_kind: str
    ca_algorithm: str
    leaf_algorithm: str
    canonical_directory: Path
    ca_certificate: Path
    provenance_file: Path
    client_certificate: Path | None
    client_private_key: Path | None
    ca_sha256: str
    client_certificate_sha256: str | None
    client_private_key_sha256: str | None
    provenance_sha256: str
    provisioned: bool

    def public_manifest(self, repo_root: Path) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_kind": self.profile_kind,
            "ca_algorithm": self.ca_algorithm,
            "leaf_algorithm": self.leaf_algorithm,
            "canonical_directory": self.canonical_directory.relative_to(repo_root).as_posix(),
            "ca_certificate": self.ca_certificate.relative_to(repo_root).as_posix(),
            "ca_sha256": self.ca_sha256,
            "client_certificate": None if self.client_certificate is None else self.client_certificate.relative_to(repo_root).as_posix(),
            "client_certificate_sha256": self.client_certificate_sha256,
            "client_private_key_present": self.client_private_key is not None,
            "client_private_key_sha256": self.client_private_key_sha256,
            "provenance_file": self.provenance_file.relative_to(repo_root).as_posix(),
            "provenance_sha256": self.provenance_sha256,
            "provisioned": self.provisioned,
        }


@dataclass(frozen=True)
class ResolvedSigningContext:
    tuple_id: str
    canonical_directory: Path
    private_key: Path
    public_key: Path
    tuple_manifest: Path
    private_key_sha256: str
    public_key_sha256: str
    tuple_manifest_sha256: str

    def public_manifest(self, repo_root: Path) -> dict[str, Any]:
        return {
            "tuple_id": self.tuple_id,
            "canonical_directory": self.canonical_directory.relative_to(repo_root).as_posix(),
            "public_key": self.public_key.relative_to(repo_root).as_posix(),
            "public_key_sha256": self.public_key_sha256,
            "tuple_manifest": self.tuple_manifest.relative_to(repo_root).as_posix(),
            "tuple_manifest_sha256": self.tuple_manifest_sha256,
            "private_key_present": True,
            "private_key_sha256": self.private_key_sha256,
        }


@dataclass(frozen=True)
class ExternalDependencyContext:
    mqtt_tls: ResolvedMqttTlsContext | None = None
    secure_boot: ResolvedSigningContext | None = None

    def public_manifest(self, repo_root: Path) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.mqtt_tls is not None:
            result["mqtt_tls"] = self.mqtt_tls.public_manifest(repo_root)
        if self.secure_boot is not None:
            result["secure_boot"] = self.secure_boot.public_manifest(repo_root)
        return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_below(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ExternalDependencyError(f"{label} must resolve below secrets/: {path}") from exc
    return resolved


def _run_logged(command: list[str], repo_root: Path, log_path: Path) -> None:
    completed = subprocess.run(command, cwd=repo_root, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    log_path.write_text(
        "Command: " + " ".join(command) + "\n"
        + f"Return code: {completed.returncode}\n\nstdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise ExternalDependencyError(
            f"certificate prerequisite command failed with return code {completed.returncode}; see {log_path.name}"
        )


def prepare_mqtt_tls_material(*, bundle: dict[str, dict[str, Any]], repo_root: Path, result_dir: Path) -> ResolvedMqttTlsContext | None:
    mqtt = bundle.get("experiment", {}).get("mqtt")
    if not isinstance(mqtt, dict):
        return None
    tls = mqtt.get("tls")
    if not isinstance(tls, dict) or str(tls.get("mode", "")) in {"", "disabled", "plaintext", "not_applicable", "unavailable"}:
        return None
    if str(tls.get("tls_version", "")).strip().lower() not in {"tls1.3", "tlsv1.3"}:
        raise ExternalDependencyError("MQTT TLS experiments must use TLS 1.3")
    profile_id = str(tls.get("certificate_profile", "")).strip()
    if not profile_id:
        raise ExternalDependencyError("TLS experiment must declare mqtt.tls.certificate_profile")
    ca_algorithm = str(tls.get("certificate_authority_algorithm", "")).strip()
    leaf_algorithm = str(tls.get("server_certificate_algorithm", "")).strip()
    if ca_algorithm != "classical-x509" or leaf_algorithm != "classical":
        raise ExternalDependencyError("MQTT identities must use the classical step-ca X.509 hierarchy")
    canonical_dir = _require_below(repo_root / "secrets" / "mqtt" / profile_id, repo_root / "secrets", "MQTT TLS profile")
    ctl = repo_root / "experiment/mqtt-broker/scripts/mqtt_broker_ctl.py"
    command = [sys.executable, str(ctl), "provision-certs", "--certificate-profile", profile_id]
    _run_logged(command, repo_root, result_dir / "certificate-prerequisite.log")
    ca_path = canonical_dir / "ca.crt"
    provenance_path = canonical_dir / "certificate-provenance.json"
    mutual_tls = str(tls.get("authentication", "")).strip().lower() == "mutual" or str(tls.get("mode", "")).endswith("_mutual")
    client_certificate = canonical_dir / "client.crt" if mutual_tls else None
    client_private_key = canonical_dir / "client.key" if mutual_tls else None
    required = [ca_path, canonical_dir / "intermediate-ca.crt", canonical_dir / "ca-chain.crt", canonical_dir / "server.crt", canonical_dir / "server.key", provenance_path]
    if mutual_tls:
        required.extend([client_certificate, client_private_key])
    missing = [str(path) for path in required if path is not None and not path.is_file()]
    if missing:
        raise ExternalDependencyError("step-ca synchronization completed without required material: " + ", ".join(missing))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    actual = _sha256(ca_path)
    if str(provenance.get("ca_sha256", "")) != actual:
        raise ExternalDependencyError("MQTT TLS root CA hash does not match certificate provenance")
    if str(provenance.get("source", "")) != "framework/certs":
        raise ExternalDependencyError("MQTT TLS material was not sourced from framework/certs")
    materials = copy_material_directory_to_result(
        canonical_dir, result_dir, f"cryptographic-material/mqtt/{profile_id}",
        role_prefix="mqtt_tls_material",
        private_names={"server.key", "client.key", "ca.key", "intermediate-ca.key"},
        required_for=["broker_installation", "client_installation", "manual_experiment_orchestration"],
    )
    write_material_inventory(result_dir, materials)
    return ResolvedMqttTlsContext(
        profile_id, "stepca-classical", ca_algorithm, leaf_algorithm,
        canonical_dir, ca_path, provenance_path,
        client_certificate, client_private_key,
        actual,
        _sha256(client_certificate) if client_certificate is not None else None,
        _sha256(client_private_key) if client_private_key is not None else None,
        _sha256(provenance_path), True
    )


def resolve_signing_material(*, profile: dict[str, Any], repo_root: Path) -> ResolvedSigningContext:
    tuple_config = profile.get("signing_tuple")
    if not isinstance(tuple_config, dict):
        raise ExternalDependencyError("signing profile must declare signing_tuple")
    tuple_id = str(tuple_config.get("tuple_id", "")).strip()
    directory = str(tuple_config.get("directory", "")).strip()
    if not tuple_id or not directory:
        raise ExternalDependencyError("signing_tuple.tuple_id and signing_tuple.directory are required")
    canonical = _require_below(repo_root / directory, repo_root / "secrets", "secure-boot signing tuple")
    private_key = canonical / Path(str(profile.get("private_key", ""))).name
    public_key = canonical / str(tuple_config.get("public_key", "public_key.der"))
    manifest = canonical / str(tuple_config.get("manifest", "tuple.json"))
    members = [private_key, public_key, manifest]
    present = [path.is_file() for path in members]
    if any(present) and not all(present):
        raise ExternalDependencyError("secure-boot signing tuple is partial; refusing silent reconstruction")
    if not all(present):
        raise ExternalDependencyError("secure-boot signing tuple is absent; run its owning wolfBoot preparation workflow")
    return ResolvedSigningContext(tuple_id, canonical, private_key, public_key, manifest, _sha256(private_key), _sha256(public_key), _sha256(manifest))


def prepare_external_dependencies(*, bundle: dict[str, dict[str, Any]], repo_root: Path, result_dir: Path) -> ExternalDependencyContext:
    mqtt = prepare_mqtt_tls_material(bundle=bundle, repo_root=repo_root, result_dir=result_dir)
    if mqtt is not None:
        tls = bundle["experiment"]["mqtt"]["tls"]
        tls["certificate_refs"] = {"ca_certificate": mqtt.ca_certificate.relative_to(repo_root).as_posix()}
        if mqtt.client_certificate is not None and mqtt.client_private_key is not None:
            tls["certificate_refs"].update({
                "client_certificate": mqtt.client_certificate.relative_to(repo_root).as_posix(),
                "client_private_key": mqtt.client_private_key.relative_to(repo_root).as_posix(),
            })
        tls["resolved_certificate_context"] = mqtt.public_manifest(repo_root)
    return ExternalDependencyContext(mqtt_tls=mqtt)
