from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    if not shutil.which("docker"):
        pytest.skip("Docker is not installed")
    root = Path(__file__).resolve().parents[2]
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_root_key_archived_and_removed_from_online_ca():
    root = Path(__file__).resolve().parents[2]
    public = root / "secrets" / "public" / "ca"
    for name in ("root-ca.crt", "intermediate-ca.crt", "ca.crt", "ca-chain.crt"):
        path = public / name
        assert path.is_file() and path.stat().st_size > 0, f"missing {path}"

    absent = _compose(
        "run", "--rm", "--no-deps", "-T", "stepca_secure_root",
        "python", "-c",
        "from pathlib import Path; raise SystemExit(1 if Path('/stepca/secrets/root_ca_key').exists() else 0)",
    )
    assert absent.returncode == 0, absent.stderr

    vault = _compose(
        "run", "--rm", "--no-deps", "-T", "vault-init",
        "python", "-c",
        "import json,requests; t=open('/state/root.token').read().strip(); "
        "r=requests.get('http://vault:8200/v1/pqc-secrets/data/ca/root/classical',"
        "headers={'X-Vault-Token':t},timeout=10); r.raise_for_status(); "
        "d=r.json()['data']['data']; "
        "assert d['private_key_pem'].startswith('-----BEGIN'); print('ok')",
    )
    assert vault.returncode == 0, vault.stderr
    assert "ok" in vault.stdout
