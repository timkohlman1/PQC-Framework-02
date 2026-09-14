#!/usr/bin/env python3
"""Provision configured offline X.509 research certificate profiles.

Certificate profiles are data under ``configs/tls_auth/*.yaml``.
This script contains only generic provisioning, validation, and manifest logic.
Normal host execution uses a short-lived Alpine/OpenSSL container.  The
``--local-openssl`` switch is reserved for the repository development container.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError as exc:  # pragma: no cover - host path normally uses Docker
    raise SystemExit("PyYAML is required; use the normal Docker-backed invocation") from exc

DOCKER_IMAGE = "alpine:3.23@sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40"
DEFAULT_CONFIG_DIR = Path("configs/tls_auth")
DEFAULT_OUTPUT_DIR = Path("secrets/certificates")


@dataclass(frozen=True)
class Profile:
    profile_id: str
    source_path: Path
    raw: dict[str, Any]

    @property
    def key(self) -> dict[str, Any]:
        return self.raw["key"]

    @property
    def certificate(self) -> dict[str, Any]:
        return self.raw["certificate"]

    @property
    def hierarchy(self) -> dict[str, Any]:
        return self.raw["hierarchy"]

    @property
    def identities(self) -> dict[str, Any]:
        return self.raw["identities"]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip()
        raise SystemExit(f"command failed ({completed.returncode}): {' '.join(command)}\n{details}")
    return completed


def _openssl(args: Iterable[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return _run(["openssl", *args], cwd=cwd)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be a mapping")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SystemExit(f"{label} must be a list")
    return value


def load_profile(path: Path) -> Profile:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = _require_mapping(data, str(path))
    if int(root.get("schema_version", 0)) != 1:
        raise SystemExit(f"{path}: schema_version must be 1")
    profile_id = str(root.get("id", "")).strip()
    if not profile_id:
        raise SystemExit(f"{path}: id is required")
    if profile_id != path.stem:
        raise SystemExit(f"{path}: id '{profile_id}' must match filename '{path.stem}'")
    key = _require_mapping(root.get("key"), f"{path}: key")
    genpkey_args = _require_list(key.get("genpkey_args"), f"{path}: key.genpkey_args")
    if not genpkey_args or not all(isinstance(item, str) and item for item in genpkey_args):
        raise SystemExit(f"{path}: key.genpkey_args must contain non-empty strings")
    certificate = _require_mapping(root.get("certificate"), f"{path}: certificate")
    validity = _require_mapping(certificate.get("validity_days"), f"{path}: certificate.validity_days")
    for name in ("root", "intermediate", "leaf"):
        if int(validity.get(name, 0)) < 1:
            raise SystemExit(f"{path}: certificate.validity_days.{name} must be at least 1")
    _require_mapping(root.get("hierarchy"), f"{path}: hierarchy")
    identities = _require_mapping(root.get("identities"), f"{path}: identities")
    if not identities:
        raise SystemExit(f"{path}: at least one leaf identity is required")
    for role, identity in identities.items():
        identity_map = _require_mapping(identity, f"{path}: identities.{role}")
        if not str(identity_map.get("common_name", "")).strip():
            raise SystemExit(f"{path}: identities.{role}.common_name is required")
        _require_list(identity_map.get("extended_key_usage", []), f"{path}: identities.{role}.extended_key_usage")
        _require_list(identity_map.get("dns_names", []), f"{path}: identities.{role}.dns_names")
        _require_list(identity_map.get("ip_addresses", []), f"{path}: identities.{role}.ip_addresses")
    return Profile(profile_id, path, root)


def load_profiles(config_dir: Path, selected: list[str] | None = None) -> list[Profile]:
    paths = sorted(config_dir.glob("*.yaml"))
    if not paths:
        raise SystemExit(f"no certificate profiles found under {config_dir}")
    profiles = [load_profile(path) for path in paths]
    by_id = {profile.profile_id: profile for profile in profiles}
    if len(by_id) != len(profiles):
        raise SystemExit("certificate profile ids must be unique")
    if selected:
        missing = sorted(set(selected) - set(by_id))
        if missing:
            raise SystemExit("unknown certificate profile(s): " + ", ".join(missing))
        profiles = [by_id[name] for name in selected]
    return profiles


def _digest_args(profile: Profile) -> list[str]:
    digest = profile.certificate.get("digest")
    if digest in (None, "", "none"):
        return []
    return ["-" + str(digest).lower().removeprefix("-")]


def _serial() -> str:
    return "0x" + secrets.token_hex(19)


def _write_extensions(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _generate_key(profile: Profile, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    private_key = directory / "private-key.pem"
    public_key = directory / "public-key.pem"
    _openssl(["genpkey", *[str(v) for v in profile.key["genpkey_args"]], "-out", str(private_key)])
    _openssl(["pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)])
    private_key.chmod(0o600)
    public_key.chmod(0o644)


def _subject(profile: Profile, common_name: str) -> str:
    organization = str(profile.certificate.get("organization", "PQC Framework Research")).strip()
    return f"/CN={common_name}/O={organization}"


def _create_root(profile: Profile, profile_dir: Path) -> None:
    directory = profile_dir / "root"
    _generate_key(profile, directory)
    common_name = str(profile.hierarchy.get("root_common_name", f"PQC Framework {profile.profile_id} Root CA"))
    pathlen = 1 if bool(profile.hierarchy.get("intermediate", True)) else 0
    _openssl([
        "req", "-new", "-x509", "-key", str(directory / "private-key.pem"),
        "-subj", _subject(profile, common_name),
        "-days", str(profile.certificate["validity_days"]["root"]), "-set_serial", _serial(),
        "-addext", f"basicConstraints=critical,CA:TRUE,pathlen:{pathlen}",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        "-addext", "subjectKeyIdentifier=hash",
        *_digest_args(profile), "-out", str(directory / "certificate.pem"),
    ])
    _openssl(["x509", "-in", str(directory / "certificate.pem"), "-outform", "DER", "-out", str(directory / "certificate.der")])


def _create_intermediate(profile: Profile, profile_dir: Path, temp_dir: Path) -> None:
    directory = profile_dir / "intermediate"
    _generate_key(profile, directory)
    common_name = str(profile.hierarchy.get("intermediate_common_name", f"PQC Framework {profile.profile_id} Intermediate CA"))
    csr = temp_dir / f"{profile.profile_id}-intermediate.csr"
    _openssl(["req", "-new", "-key", str(directory / "private-key.pem"), "-subj", _subject(profile, common_name), *_digest_args(profile), "-out", str(csr)])
    ext = temp_dir / f"{profile.profile_id}-intermediate.ext"
    _write_extensions(ext, [
        "basicConstraints=critical,CA:TRUE,pathlen:0",
        "keyUsage=critical,keyCertSign,cRLSign",
        "subjectKeyIdentifier=hash",
        "authorityKeyIdentifier=keyid,issuer",
    ])
    _openssl([
        "x509", "-req", "-in", str(csr), "-CA", str(profile_dir / "root" / "certificate.pem"),
        "-CAkey", str(profile_dir / "root" / "private-key.pem"), "-set_serial", _serial(),
        "-days", str(profile.certificate["validity_days"]["intermediate"]), "-extfile", str(ext),
        *_digest_args(profile), "-out", str(directory / "certificate.pem"),
    ])
    _openssl(["x509", "-in", str(directory / "certificate.pem"), "-outform", "DER", "-out", str(directory / "certificate.der")])


def _san_value(dns_names: Iterable[str], ip_addresses: Iterable[str]) -> str:
    values = [f"DNS:{value}" for value in dns_names if value]
    values.extend(f"IP:{value}" for value in ip_addresses if value)
    return ",".join(dict.fromkeys(values))


def _create_leaf(profile: Profile, profile_dir: Path, temp_dir: Path, role: str, identity: dict[str, Any]) -> None:
    directory = profile_dir / role
    _generate_key(profile, directory)
    csr = temp_dir / f"{profile.profile_id}-{role}.csr"
    _openssl(["req", "-new", "-key", str(directory / "private-key.pem"), "-subj", _subject(profile, str(identity["common_name"])), *_digest_args(profile), "-out", str(csr)])
    extensions = [
        "basicConstraints=critical,CA:FALSE",
        "keyUsage=critical,digitalSignature",
        "subjectKeyIdentifier=hash",
        "authorityKeyIdentifier=keyid,issuer",
    ]
    eku = [str(value) for value in identity.get("extended_key_usage", [])]
    if eku:
        extensions.append("extendedKeyUsage=" + ",".join(eku))
    san = _san_value(identity.get("dns_names", []), identity.get("ip_addresses", []))
    if san:
        extensions.append("subjectAltName=" + san)
    ext = temp_dir / f"{profile.profile_id}-{role}.ext"
    _write_extensions(ext, extensions)
    use_intermediate = bool(profile.hierarchy.get("intermediate", True))
    signer_dir = profile_dir / ("intermediate" if use_intermediate else "root")
    _openssl([
        "x509", "-req", "-in", str(csr), "-CA", str(signer_dir / "certificate.pem"),
        "-CAkey", str(signer_dir / "private-key.pem"), "-set_serial", _serial(),
        "-days", str(profile.certificate["validity_days"]["leaf"]), "-extfile", str(ext),
        *_digest_args(profile), "-out", str(directory / "certificate.pem"),
    ])
    _openssl(["x509", "-in", str(directory / "certificate.pem"), "-outform", "DER", "-out", str(directory / "certificate.der")])
    chain = directory / "chain.pem"
    chain.write_bytes((directory / "certificate.pem").read_bytes() + (signer_dir / "certificate.pem").read_bytes())


def _verify_key_matches(directory: Path, temp_dir: Path, suffix: str) -> None:
    key_public = temp_dir / f"{suffix}-key-public.pem"
    cert_public = temp_dir / f"{suffix}-cert-public.pem"
    key_public.write_text(_openssl(["pkey", "-in", str(directory / "private-key.pem"), "-pubout"]).stdout, encoding="utf-8")
    cert_public.write_text(_openssl(["x509", "-in", str(directory / "certificate.pem"), "-pubkey", "-noout"]).stdout, encoding="utf-8")
    if key_public.read_bytes() != cert_public.read_bytes():
        raise SystemExit(f"private key does not match certificate: {directory}")


def _verify_profile(profile: Profile, profile_dir: Path, temp_dir: Path) -> None:
    root = profile_dir / "root" / "certificate.pem"
    if bool(profile.hierarchy.get("intermediate", True)):
        intermediate = profile_dir / "intermediate" / "certificate.pem"
        _openssl(["verify", "-CAfile", str(root), str(intermediate)])
        for role in profile.identities:
            _openssl(["verify", "-CAfile", str(root), "-untrusted", str(intermediate), str(profile_dir / role / "certificate.pem")])
        roles = ["root", "intermediate", *profile.identities]
    else:
        for role in profile.identities:
            _openssl(["verify", "-CAfile", str(root), str(profile_dir / role / "certificate.pem")])
        roles = ["root", *profile.identities]
    for role in roles:
        _verify_key_matches(profile_dir / role, temp_dir, f"{profile.profile_id}-{role}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_deployment_aliases(profile: Profile, profile_dir: Path) -> None:
    shutil.copy2(profile_dir / "root" / "certificate.pem", profile_dir / "ca.crt")
    shutil.copy2(profile_dir / "root" / "certificate.pem", profile_dir / "root-ca.crt")
    use_intermediate = bool(profile.hierarchy.get("intermediate", True))
    if use_intermediate:
        shutil.copy2(profile_dir / "intermediate" / "certificate.pem", profile_dir / "intermediate-ca.crt")
        (profile_dir / "ca-chain.crt").write_bytes(
            (profile_dir / "intermediate" / "certificate.pem").read_bytes() + (profile_dir / "root" / "certificate.pem").read_bytes()
        )
    else:
        (profile_dir / "ca-chain.crt").write_bytes((profile_dir / "root" / "certificate.pem").read_bytes())
    alias_roles = {"server": ("server.crt", "server.key"), "client": ("client.crt", "client.key"), "healthcheck": ("healthcheck.crt", "healthcheck.key")}
    for role, (cert_name, key_name) in alias_roles.items():
        if role not in profile.identities:
            continue
        shutil.copy2(profile_dir / role / "certificate.pem", profile_dir / cert_name)
        shutil.copy2(profile_dir / role / "private-key.pem", profile_dir / key_name)
        (profile_dir / key_name).chmod(0o600)


def _write_manifest(profile: Profile, profile_dir: Path) -> None:
    files: dict[str, str] = {}
    for path in sorted(item for item in profile_dir.rglob("*") if item.is_file() and item.name != "manifest.json"):
        files[path.relative_to(profile_dir).as_posix()] = _sha256(path)
    manifest = {
        "schema_version": 2,
        "profile_id": profile.profile_id,
        "profile_config": profile.source_path.as_posix(),
        "key_algorithm": profile.key.get("display_name", profile.key.get("algorithm", "")),
        "certificate_signature_algorithm": profile.certificate.get("expected_signature_algorithm", ""),
        "tls_signature_scheme": profile.certificate.get("tls_signature_scheme", ""),
        "hierarchy": profile.hierarchy,
        "identities": profile.identities,
        "validity_days": profile.certificate["validity_days"],
        "files": files,
    }
    (profile_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _check_required_algorithms(profiles: list[Profile]) -> None:
    listed = _openssl(["list", "-public-key-algorithms"]).stdout.lower().replace("-", "")
    for profile in profiles:
        required = str(profile.key.get("openssl_algorithm", "")).lower().replace("-", "")
        if required and required not in listed:
            version = _openssl(["version"]).stdout.strip()
            raise SystemExit(f"OpenSSL runtime does not provide {profile.key.get('openssl_algorithm')}: {version}")


def provision_local(args: argparse.Namespace) -> None:
    config_dir = Path(args.config_dir).resolve()
    output = Path(args.output).resolve()
    profiles = load_profiles(config_dir, args.profile)
    _check_required_algorithms(profiles)
    output.mkdir(parents=True, exist_ok=True)
    for profile in profiles:
        destination = output / profile.profile_id
        if destination.exists():
            if not args.force:
                raise SystemExit(f"certificate profile already exists: {destination}; pass --force to replace selected profile(s)")
            shutil.rmtree(destination)
        staging = output / f".{profile.profile_id}-staging-{secrets.token_hex(6)}"
        staging.mkdir()
        try:
            with tempfile.TemporaryDirectory(prefix=f"pqc-x509-{profile.profile_id}-") as temp_name:
                temp_dir = Path(temp_name)
                _create_root(profile, staging)
                if bool(profile.hierarchy.get("intermediate", True)):
                    _create_intermediate(profile, staging, temp_dir)
                for role, identity in profile.identities.items():
                    _create_leaf(profile, staging, temp_dir, role, identity)
                if bool(profile.hierarchy.get("intermediate", True)):
                    (staging / "ca-chain.pem").write_bytes((staging / "intermediate" / "certificate.pem").read_bytes() + (staging / "root" / "certificate.pem").read_bytes())
                else:
                    (staging / "ca-chain.pem").write_bytes((staging / "root" / "certificate.pem").read_bytes())
                _verify_profile(profile, staging, temp_dir)
                _write_deployment_aliases(profile, staging)
                _write_manifest(profile, staging)
            staging.replace(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    print(f"Provisioned {len(profiles)} certificate profile(s) under {output}")


def provision_with_docker(args: argparse.Namespace) -> None:
    if shutil.which("docker") is None:
        raise SystemExit("Docker CLI is required for host provisioning; use the repository development container for --local-openssl")
    config_dir = Path(args.config_dir).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    command = [
        "docker", "run", "--rm",
        "-v", f"{script}:/work/provision_certificates.py:ro",
        "-v", f"{config_dir}:/work/configs:ro",
        "-v", f"{output.parent}:/output",
        DOCKER_IMAGE, "sh", "-ec",
        "apk add --no-cache python3 py3-yaml openssl >/dev/null && exec python3 /work/provision_certificates.py --local-openssl --config-dir /work/configs --output /output/" + output.name + " \"$@\"",
        "provision-certificates",
    ]
    forwarded: list[str] = []
    for profile in args.profile or []:
        forwarded.extend(["--profile", profile])
    if args.force:
        forwarded.append("--force")
    _run([*command, *forwarded])


def build_parser() -> argparse.ArgumentParser:
    root = repo_root()
    parser = argparse.ArgumentParser(description="Provision offline X.509 certificate profiles declared under configs/tls_auth")
    parser.add_argument("--config-dir", default=str(root / DEFAULT_CONFIG_DIR))
    parser.add_argument("--output", default=str(root / DEFAULT_OUTPUT_DIR))
    parser.add_argument("--profile", action="append", help="provision only the named profile; may be repeated")
    parser.add_argument("--force", action="store_true", help="replace selected existing profile directories")
    parser.add_argument("--local-openssl", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.local_openssl or os.environ.get("PQC_CONTAINER") == "1":
        provision_local(args)
    else:
        provision_with_docker(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
