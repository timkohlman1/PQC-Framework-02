from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from .errors import SecretFormatError


@dataclass(frozen=True)
class CertificateIdentity:
    certificate_pem: str
    private_key: bytes
    private_key_encoding: str
    chain_pem: str = ""
    root_certificate_pem: str = ""
    algorithm: str = ""
    profile_id: str = ""

    def to_secret(self) -> dict[str, Any]:
        return {
            "certificate_pem": self.certificate_pem,
            "private_key_b64": base64.b64encode(self.private_key).decode("ascii"),
            "private_key_encoding": self.private_key_encoding,
            "chain_pem": self.chain_pem,
            "root_certificate_pem": self.root_certificate_pem,
            "algorithm": self.algorithm,
            "profile_id": self.profile_id,
        }

    @classmethod
    def from_secret(cls, value: dict[str, Any]) -> "CertificateIdentity":
        required = ("certificate_pem", "private_key_b64", "private_key_encoding")
        missing = [name for name in required if not value.get(name)]
        if missing:
            raise SecretFormatError(f"Certificate identity is missing: {', '.join(missing)}")
        try:
            private_key = base64.b64decode(value["private_key_b64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise SecretFormatError("private_key_b64 is not valid Base64") from exc
        return cls(
            certificate_pem=str(value["certificate_pem"]),
            private_key=private_key,
            private_key_encoding=str(value["private_key_encoding"]),
            chain_pem=str(value.get("chain_pem") or ""),
            root_certificate_pem=str(value.get("root_certificate_pem") or ""),
            algorithm=str(value.get("algorithm") or ""),
            profile_id=str(value.get("profile_id") or ""),
        )
