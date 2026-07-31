from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_LEAF_DURATION = "8760h"
DEFAULT_MAXIMUM_DURATION = "8784h"


def _apply_claims(claims: dict[str, object], *, default_duration: str, maximum_duration: str) -> None:
    claims["minTLSCertDuration"] = "5m"
    claims["defaultTLSCertDuration"] = default_duration
    claims["maxTLSCertDuration"] = maximum_duration


def main() -> int:
    config_path = Path(os.environ.get("STEPCA_CONFIG", "/stepca/config/ca.json"))
    default_duration = os.environ.get("CERT_NOT_AFTER", DEFAULT_LEAF_DURATION)
    maximum_duration = os.environ.get("CERT_MAX_NOT_AFTER", DEFAULT_MAXIMUM_DURATION)

    if not config_path.is_file():
        raise SystemExit(f"step-ca configuration not found: {config_path}")

    data = json.loads(config_path.read_text(encoding="utf-8"))
    authority = data.setdefault("authority", {})
    if not isinstance(authority, dict):
        raise SystemExit("step-ca authority configuration is not an object")

    authority_claims = authority.setdefault("claims", {})
    if not isinstance(authority_claims, dict):
        raise SystemExit("step-ca authority claims configuration is not an object")
    _apply_claims(
        authority_claims,
        default_duration=default_duration,
        maximum_duration=maximum_duration,
    )

    provisioners = authority.get("provisioners", [])
    if not isinstance(provisioners, list):
        raise SystemExit("step-ca provisioners configuration is not a list")

    changed = 0
    for provisioner in provisioners:
        if not isinstance(provisioner, dict) or provisioner.get("type") != "JWK":
            continue
        claims = provisioner.setdefault("claims", {})
        if not isinstance(claims, dict):
            raise SystemExit("JWK provisioner claims configuration is not an object")
        _apply_claims(
            claims,
            default_duration=default_duration,
            maximum_duration=maximum_duration,
        )
        changed += 1

    if changed == 0:
        raise SystemExit("no JWK provisioner found in step-ca configuration")

    temporary = config_path.with_name(f"{config_path.name}.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_path)
    print(
        "[stepca-policy] updated authority and "
        f"{changed} JWK provisioner(s); default={default_duration}; maximum={maximum_duration}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
