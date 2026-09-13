"""Resolve explicit SSH targets for gateway-mediated workflows."""

from __future__ import annotations

from typing import Any, Mapping


class SshTargetError(ValueError):
    """Raised when a gateway host cannot produce an explicit SSH target."""


def gateway_ssh_target(host: Mapping[str, Any]) -> str:
    """Return ``user@host`` for a legacy or canonical gateway mapping.

    Remote workflows must never rely on the container's local username. The
    legacy execution bundle exposes ``user`` + ``alias`` while canonical
    gateway profiles expose ``identity.ssh_user`` + ``identity.fqdn``.
    """

    identity = host.get("identity")
    if not isinstance(identity, Mapping):
        identity = {}

    username = str(host.get("user") or host.get("ssh_user") or identity.get("ssh_user") or "").strip()
    hostname = str(host.get("alias") or host.get("fqdn") or identity.get("fqdn") or identity.get("alias") or "").strip()

    if not username:
        raise SshTargetError("gateway SSH user is missing; refusing to fall back to the container user")
    if not hostname:
        raise SshTargetError("gateway SSH hostname is missing")

    return f"{username}@{hostname}"
