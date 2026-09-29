"""Real local Docker gate for both mutual-TLS certificate profiles."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
@pytest.mark.docker_runtime
def test_oqs_mtls_staged_permissions_and_health():
    if shutil.which("docker") is None:
        pytest.skip("Run python3 scripts/check_oqs_mtls_broker.py on the Docker host; no nested Docker")
    if subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode:
        pytest.skip("Local Docker daemon unavailable")
    for profile in ("rsa3072", "mldsa65"):
        if not (ROOT / "secrets/certificates" / profile / "healthcheck.key").is_file():
            pytest.skip(f"Pre-provisioned {profile} experiment material unavailable")
    result = subprocess.run([sys.executable, "scripts/check_oqs_mtls_broker.py"],
                            cwd=ROOT, text=True, capture_output=True, timeout=480)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS rsa3072" in result.stdout
    assert "PASS mldsa65" in result.stdout
