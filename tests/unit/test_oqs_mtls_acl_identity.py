from pathlib import Path


def test_oqs_mtls_acl_authorises_certificate_identity():
    acl = Path("experiment/mqtt-broker/config/oqs-mtls/aclfile").read_text(encoding="utf-8")
    lines = [line.strip() for line in acl.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert lines[0] == "user stm32-mqtt-client"
    assert "topic readwrite pqc/#" in lines[1:]
    assert "topic read $SYS/#" in lines[1:]
