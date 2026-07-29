from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .errors import VaultRequestError
from .vault import VaultClient


def _clean_path(path: str) -> str:
    clean = path.strip("/")
    if not clean or any(part in (".", "..") for part in clean.split("/")):
        raise ValueError(f"Invalid Vault secret path: {path!r}")
    return "/".join(quote(part, safe="-_.~") for part in clean.split("/"))


@dataclass(frozen=True)
class SecretVersion:
    data: dict[str, Any]
    version: int
    created_time: str | None = None


class KvV2:
    def __init__(self, client: VaultClient, mount: str = "pqc-secrets") -> None:
        self.client = client
        self.mount = mount.strip("/")
        if not self.mount:
            raise ValueError("KV mount must not be empty")

    def put(self, path: str, values: Mapping[str, Any], *, cas: int | None = None) -> int:
        body: dict[str, Any] = {"data": dict(values)}
        if cas is not None:
            body["options"] = {"cas": cas}
        response = self.client.request(
            "POST", f"/v1/{self.mount}/data/{_clean_path(path)}", body=body
        )
        return int(response.json()["data"]["version"])

    def read(self, path: str, *, version: int | None = None) -> SecretVersion:
        suffix = f"?version={version}" if version is not None else ""
        response = self.client.request(
            "GET", f"/v1/{self.mount}/data/{_clean_path(path)}{suffix}"
        )
        payload = response.json()["data"]
        metadata = payload.get("metadata") or {}
        return SecretVersion(
            data=dict(payload["data"]),
            version=int(metadata.get("version", version or 0)),
            created_time=metadata.get("created_time"),
        )

    def list(self, path: str) -> list[str]:
        response = self.client.request(
            "LIST", f"/v1/{self.mount}/metadata/{_clean_path(path)}"
        )
        return list(response.json()["data"]["keys"])

    def metadata(self, path: str) -> dict[str, Any]:
        response = self.client.request(
            "GET", f"/v1/{self.mount}/metadata/{_clean_path(path)}"
        )
        return dict(response.json()["data"])

    def delete_versions(self, path: str, versions: list[int]) -> None:
        self.client.request(
            "POST",
            f"/v1/{self.mount}/delete/{_clean_path(path)}",
            body={"versions": versions},
        )

    def undelete_versions(self, path: str, versions: list[int]) -> None:
        self.client.request(
            "POST",
            f"/v1/{self.mount}/undelete/{_clean_path(path)}",
            body={"versions": versions},
        )

    def destroy_versions(self, path: str, versions: list[int]) -> None:
        self.client.request(
            "POST",
            f"/v1/{self.mount}/destroy/{_clean_path(path)}",
            body={"versions": versions},
        )
