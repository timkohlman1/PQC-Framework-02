from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import requests

from .errors import VaultRequestError


class VaultClient:
    """Minimal Vault HTTP client that never logs tokens or secret payloads."""

    def __init__(
        self,
        *,
        address: str,
        token: str,
        timeout: float = 10.0,
        verify: bool | str = True,
        session: requests.Session | None = None,
        audit_headers: Mapping[str, str] | None = None,
    ) -> None:
        if not token:
            raise ValueError("Vault token must not be empty")
        self.address = address.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.verify = verify
        self.session = session or requests.Session()
        self.audit_headers = dict(audit_headers or {})

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 204),
    ) -> requests.Response:
        headers = {
            "X-Vault-Token": self.token,
            "Content-Type": "application/json",
            **self.audit_headers,
        }
        response = self.session.request(
            method,
            f"{self.address}{path}",
            headers=headers,
            json=body,
            timeout=self.timeout,
            verify=self.verify,
        )
        if response.status_code not in expected:
            request_id = response.headers.get("X-Vault-Request") or response.headers.get(
                "X-Vault-Request-Id"
            )
            suffix = f" request_id={request_id}" if request_id else ""
            raise VaultRequestError(
                f"Vault {method.upper()} {path} failed with status "
                f"{response.status_code}{suffix}"
            )
        return response
