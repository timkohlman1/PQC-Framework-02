from __future__ import annotations

from pathlib import Path

import pytest

import conftest


def test_gateway_capability_requires_explicit_container_enablement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(conftest.CONTAINER_ENV, "1")
    monkeypatch.delenv(conftest.CONTAINER_GATEWAY_ENABLE_ENV, raising=False)
    monkeypatch.setattr(conftest, "_host_config", lambda: {
        "identity": {
            "alias": "pqc-gateway1",
            "fqdn": "pqc-gateway1.pqcnet",
            "ssh_user": "timk",
        }
    })
    monkeypatch.setattr(Path, "exists", lambda self: False)

    checker = conftest.PqcCapabilityChecker()

    result = checker.check("gateway")

    assert not result.available
    assert conftest.CONTAINER_GATEWAY_ENABLE_ENV in result.reason
    assert "runtime-provided SSH" in result.reason


def test_gateway_capability_uses_runtime_ssh_when_container_gateway_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(conftest.CONTAINER_ENV, "1")
    monkeypatch.setenv(conftest.CONTAINER_GATEWAY_ENABLE_ENV, "1")
    monkeypatch.setattr(conftest, "_host_config", lambda: {
        "identity": {
            "alias": "pqc-gateway1",
            "fqdn": "pqc-gateway1.pqcnet",
            "ssh_user": "timk",
        }
    })
    monkeypatch.setattr(Path, "exists", lambda self: False)

    probes: list[tuple[str, str]] = []

    def fake_ssh_probe(host_alias: str, command: str) -> conftest.CapabilityResult:
        probes.append((host_alias, command))
        return conftest.CapabilityResult("ssh probe", True, "available")

    monkeypatch.setattr(conftest, "_ssh_probe", fake_ssh_probe)

    checker = conftest.PqcCapabilityChecker()

    result = checker.check("gateway")

    assert result.available
    assert probes == [("timk@pqc-gateway1.pqcnet", "true")]
