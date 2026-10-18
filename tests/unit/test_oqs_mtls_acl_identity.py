from pathlib import Path


def test_oqs_mtls_acl_authorises_certificate_identity():
    acl = Path("experiment/mqtt-broker/config/oqs-mtls/aclfile").read_text(encoding="utf-8")
    lines = [line.strip() for line in acl.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert lines[0] == "topic readwrite pqc/experiments/#"
    assert lines[1] == "user stm32-mqtt-client"
    config = Path("experiment/mqtt-broker/config/oqs-mtls/mosquitto.conf").read_text()
    assert "require_certificate true" in config
    assert "use_identity_as_username true" in config
    assert "topic readwrite pqc/#" in lines[1:]
    assert "topic read $SYS/#" in lines[1:]
