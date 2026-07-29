from securedata.kv import KvV2


class Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class Client:
    def __init__(self):
        self.calls = []
        self.responses = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.responses.pop(0)


def test_put_and_read_kv_v2_secret():
    client = Client()
    client.responses = [
        Response({"data": {"version": 3}}),
        Response({
            "data": {
                "data": {"certificate_pem": "cert"},
                "metadata": {"version": 3, "created_time": "now"},
            }
        }),
    ]
    kv = KvV2(client, "pqc-secrets")

    assert kv.put("mqtt/brokers/test", {"certificate_pem": "cert"}, cas=2) == 3
    secret = kv.read("mqtt/brokers/test", version=3)

    assert secret.data == {"certificate_pem": "cert"}
    assert secret.version == 3
    assert client.calls[0] == (
        "POST",
        "/v1/pqc-secrets/data/mqtt/brokers/test",
        {"body": {"data": {"certificate_pem": "cert"}, "options": {"cas": 2}}},
    )
    assert client.calls[1][1].endswith("?version=3")


def test_destroy_versions_uses_kv_v2_destroy_endpoint():
    client = Client()
    client.responses = [Response({})]
    KvV2(client).destroy_versions("wolfboot/mldsa65/key-1", [1, 2])
    assert client.calls[0][1] == "/v1/pqc-secrets/destroy/wolfboot/mldsa65/key-1"
