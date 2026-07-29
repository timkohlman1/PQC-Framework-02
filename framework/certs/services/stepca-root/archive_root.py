#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import requests

VAULT_ADDR = os.getenv("VAULT_ADDR", "http://vault:8200").rstrip("/")
VAULT_MOUNT = os.getenv("VAULT_KV_MOUNT", "pqc-secrets").strip("/")
VAULT_PATH = os.getenv("VAULT_ROOT_CA_PATH", "ca/root/classical").strip("/")
ROOT_TOKEN_FILE = Path(os.getenv("ROOT_TOKEN_FILE", "/state/root.token"))
STEPCA_DIR = Path(os.getenv("STEPCA_DIR", "/stepca"))
PUBLIC_DIR = Path(os.getenv("PUBLIC_DIR", "/public"))

ROOT_CERT = STEPCA_DIR / "certs/root_ca.crt"
ROOT_KEY = STEPCA_DIR / "secrets/root_ca_key"
INTERMEDIATE_CERT = STEPCA_DIR / "certs/intermediate_ca.crt"


def log(message: str) -> None:
    print(f"[stepca-root] {message}", flush=True)


def wait_for_file(path: Path, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            return
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {path}")


def vault_request(method: str, path: str, token: str, body: dict | None = None) -> requests.Response:
    response = requests.request(
        method,
        f"{VAULT_ADDR}{path}",
        headers={"X-Vault-Token": token, "Content-Type": "application/json"},
        json=body,
        timeout=15,
    )
    return response


def read_existing(token: str) -> dict | None:
    response = vault_request("GET", f"/v1/{VAULT_MOUNT}/data/{VAULT_PATH}", token)
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise RuntimeError(f"Vault read failed: {response.status_code} {response.text}")
    return response.json()["data"]["data"]


def write_root_record(token: str, root_cert: str, root_key: str, intermediate_cert: str) -> None:
    record = {
        "certificate_pem": root_cert,
        "private_key_pem": root_key,
        "intermediate_certificate_pem": intermediate_cert,
        "algorithm_family": "classical",
        "authority_role": "offline-root",
        "source": "step-ca-bootstrap",
    }
    response = vault_request(
        "POST",
        f"/v1/{VAULT_MOUNT}/data/{VAULT_PATH}",
        token,
        {"data": record},
    )
    if response.status_code not in (200, 204):
        raise RuntimeError(f"Vault write failed: {response.status_code} {response.text}")


def publish_public_material(root_cert: str, intermediate_cert: str) -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "root-ca.crt": root_cert,
        "intermediate-ca.crt": intermediate_cert,
        "ca.crt": root_cert,
        "ca-chain.crt": intermediate_cert + ("" if intermediate_cert.endswith("\n") else "\n") + root_cert,
    }
    for name, contents in files.items():
        destination = PUBLIC_DIR / name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(contents, encoding="utf-8")
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)


def main() -> int:
    try:
        wait_for_file(ROOT_TOKEN_FILE)
        wait_for_file(ROOT_CERT)
        wait_for_file(INTERMEDIATE_CERT)
        token = ROOT_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("Vault root token file is empty")

        root_cert = ROOT_CERT.read_text(encoding="utf-8")
        intermediate_cert = INTERMEDIATE_CERT.read_text(encoding="utf-8")
        existing = read_existing(token)

        if ROOT_KEY.is_file() and ROOT_KEY.stat().st_size > 0:
            root_key = ROOT_KEY.read_text(encoding="utf-8")
            write_root_record(token, root_cert, root_key, intermediate_cert)
            log(f"Archived root CA private key at {VAULT_MOUNT}/{VAULT_PATH}")
        elif not existing or not existing.get("private_key_pem"):
            raise RuntimeError("Root key is absent from step-ca and no archived Vault copy exists")
        else:
            log("Root CA private key is already archived in Vault")

        publish_public_material(root_cert, intermediate_cert)
        log(f"Published public CA material to {PUBLIC_DIR}")

        if ROOT_KEY.exists():
            ROOT_KEY.unlink()
            log(f"Removed online root CA private key {ROOT_KEY}")

        if ROOT_KEY.exists():
            raise RuntimeError("Root CA private key still exists after removal")
        log("Offline-root separation complete")
        return 0
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
