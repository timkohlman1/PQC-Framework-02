from pathlib import Path

import pytest

from securedata.auth import login_approle
from securedata.errors import VaultRequestError


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_login_approle_reads_credentials_from_files(tmp_path: Path):
    role = tmp_path / "role"
    secret = tmp_path / "secret"
    role.write_text("role-id\n", encoding="utf-8")
    secret.write_text("secret-id\n", encoding="utf-8")
    session = Session(Response(payload={"auth": {"client_token": "token"}}))

    token = login_approle(
        vault_addr="http://vault:8200",
        role_id_path=role,
        secret_id_path=secret,
        session=session,
    )

    assert token == "token"
    assert session.calls[0][1]["json"] == {
        "role_id": "role-id",
        "secret_id": "secret-id",
    }


def test_login_approle_rejects_failed_login():
    with pytest.raises(VaultRequestError, match="status 403"):
        login_approle(
            vault_addr="http://vault:8200",
            role_id="role",
            secret_id="secret",
            session=Session(Response(status_code=403)),
        )
