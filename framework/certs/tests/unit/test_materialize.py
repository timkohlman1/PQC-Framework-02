import os
from pathlib import Path

import pytest

from securedata.materialize import materialize_identity
from securedata.models import CertificateIdentity


def test_materialize_identity_writes_and_removes_files(tmp_path: Path):
    identity = CertificateIdentity(
        certificate_pem="CERT\n",
        private_key=b"PRIVATE",
        private_key_encoding="pem",
        chain_pem="CHAIN\n",
        root_certificate_pem="ROOT\n",
    )

    with materialize_identity(
        identity,
        runtime_root=tmp_path,
        run_id="run-001",
        identity_name="mqtt-broker",
    ) as files:
        assert files.certificate.read_text() == "CERT\n"
        assert files.private_key.read_bytes() == b"PRIVATE"
        assert files.chain.read_text() == "CHAIN\n"
        assert files.root_certificate.read_text() == "ROOT\n"
        if os.name != "nt":
            assert files.private_key.stat().st_mode & 0o777 == 0o600
            assert files.certificate.stat().st_mode & 0o777 == 0o644
        directory = files.directory

    assert not directory.exists()


def test_materialize_identity_refuses_existing_directory(tmp_path: Path):
    target = tmp_path / "run-001" / "mqtt-broker"
    target.mkdir(parents=True)
    identity = CertificateIdentity("CERT", b"KEY", "pem")
    with pytest.raises(FileExistsError):
        with materialize_identity(
            identity,
            runtime_root=tmp_path,
            run_id="run-001",
            identity_name="mqtt-broker",
        ):
            pass
