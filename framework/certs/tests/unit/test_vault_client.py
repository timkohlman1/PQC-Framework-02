import pytest

from securedata.errors import VaultRequestError
from securedata.vault import VaultClient


class Response:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


class Session:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def request(self, method, url, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_vault_client_sends_token_without_exposing_it_in_errors():
    session = Session(Response(403, {"X-Vault-Request-Id": "request-1"}))
    client = VaultClient(address="http://vault:8200", token="super-secret", session=session)

    with pytest.raises(VaultRequestError) as exc:
        client.request("GET", "/v1/test")

    assert session.kwargs["headers"]["X-Vault-Token"] == "super-secret"
    assert "super-secret" not in str(exc.value)
    assert "request-1" in str(exc.value)
