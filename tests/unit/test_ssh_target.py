from __future__ import annotations

import pytest

from framework.ssh_target import SshTargetError, gateway_ssh_target


def test_legacy_gateway_target_is_explicit_user_at_hostname():
    assert gateway_ssh_target({"user": "timk", "alias": "pqc-gateway1.pqcnet"}) == "timk@pqc-gateway1.pqcnet"


def test_canonical_gateway_identity_prefers_fqdn_and_ssh_user():
    assert gateway_ssh_target({"identity": {"alias": "pqc-gateway1", "fqdn": "pqc-gateway1.pqcnet", "ssh_user": "timk"}}) == "timk@pqc-gateway1.pqcnet"


def test_missing_user_is_rejected_instead_of_falling_back_to_container_user():
    with pytest.raises(SshTargetError, match="SSH user is missing"):
        gateway_ssh_target({"alias": "pqc-gateway1.pqcnet"})
