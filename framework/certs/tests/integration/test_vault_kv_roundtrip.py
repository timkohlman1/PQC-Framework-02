from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from securedata.kv import KvV2
from securedata.models import CertificateIdentity
from securedata.vault import VaultClient

pytestmark = pytest.mark.integration


def _root_token() -> str:
    direct = os.getenv("VAULT_TEST_TOKEN")
    if direct:
        return direct
    path = os.getenv("VAULT_TEST_TOKEN_PATH")
    if path and Path(path).is_file():
        return Path(path).read_text(encoding="utf-8").strip()
    if shutil.which("docker"):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [
                "docker", "compose", "run", "--rm", "--no-deps", "-T",
                "vault-init", "cat", "/state/root.token",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    pytest.skip("Start the Compose stack or set VAULT_TEST_TOKEN/VAULT_TEST_TOKEN_PATH")


def test_vault_kv_v2_certificate_roundtrip():
    client = VaultClient(
        address=os.getenv("VAULT_ADDR", "http://localhost:8200"),
        token=_root_token(),
        verify=os.getenv("VAULT_CACERT") or True,
    )
    kv = KvV2(client, os.getenv("VAULT_KV_MOUNT", "pqc-secrets"))
    path = f"integration-tests/{uuid.uuid4()}"
    identity = CertificateIdentity(
        certificate_pem="-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n",
        private_key=b"integration-test-private-key",
        private_key_encoding="der",
        algorithm="test",
        profile_id="integration",
    )

    version = kv.put(path, identity.to_secret())
    loaded = CertificateIdentity.from_secret(kv.read(path, version=version).data)

    assert loaded == identity
    kv.destroy_versions(path, [version])
