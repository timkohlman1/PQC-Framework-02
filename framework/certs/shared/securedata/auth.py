from __future__ import annotations

import os
from pathlib import Path

import requests

from .errors import VaultRequestError


def _read_secret_file(path: str | Path) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"Credential file is empty: {path}")
    return value


def login_approle(
    *,
    vault_addr: str,
    role_id: str | None = None,
    secret_id: str | None = None,
    role_id_path: str | Path | None = None,
    secret_id_path: str | Path | None = None,
    timeout: float = 10.0,
    session: requests.Session | None = None,
) -> str:
    """Authenticate with Vault AppRole and return a short-lived client token."""
    role_id = role_id or os.getenv("VAULT_ROLE_ID")
    secret_id = secret_id or os.getenv("VAULT_SECRET_ID")

    if not role_id:
        path = role_id_path or os.getenv("VAULT_ROLE_ID_PATH")
        if path:
            role_id = _read_secret_file(path)
    if not secret_id:
        path = secret_id_path or os.getenv("VAULT_SECRET_ID_PATH")
        if path:
            secret_id = _read_secret_file(path)

    if not role_id or not secret_id:
        raise ValueError(
            "AppRole credentials are required through direct values, "
            "VAULT_ROLE_ID/VAULT_SECRET_ID, or credential file paths"
        )

    http = session or requests.Session()
    response = http.post(
        f"{vault_addr.rstrip('/')}/v1/auth/approle/login",
        json={"role_id": role_id, "secret_id": secret_id},
        timeout=timeout,
    )
    if response.status_code != 200:
        raise VaultRequestError(
            f"Vault AppRole login failed with status {response.status_code}"
        )
    try:
        token = response.json()["auth"]["client_token"]
    except (KeyError, TypeError, ValueError) as exc:
        raise VaultRequestError("Vault AppRole response did not contain a token") from exc
    if not token:
        raise VaultRequestError("Vault AppRole returned an empty token")
    return token
