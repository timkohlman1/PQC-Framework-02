import pytest

from securedata.errors import SecretFormatError
from securedata.models import CertificateIdentity


def test_certificate_identity_round_trip():
    identity = CertificateIdentity(
        certificate_pem="CERT",
        private_key=b"PRIVATE",
        private_key_encoding="der",
        chain_pem="CHAIN",
        root_certificate_pem="ROOT",
        algorithm="ecdsa-p256",
        profile_id="mqtt-server",
    )
    assert CertificateIdentity.from_secret(identity.to_secret()) == identity


def test_certificate_identity_rejects_invalid_base64():
    with pytest.raises(SecretFormatError, match="Base64"):
        CertificateIdentity.from_secret({
            "certificate_pem": "CERT",
            "private_key_b64": "not base64!",
            "private_key_encoding": "der",
        })
