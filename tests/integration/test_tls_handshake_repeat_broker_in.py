from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(
            "set PQC_TLS_REPEAT_BROKER_HOST, PQC_TLS_REPEAT_BROKER_PORT, "
            "PQC_TLS_REPEAT_BROKER_CA and PQC_TLS_REPEAT_BROKER_SERVER_NAME "
            "to run the live broker repeated-handshake integration test"
        )
    return value


def test_broker_accepts_multiple_independent_full_tls13_connections():
    host = _required_env("PQC_TLS_REPEAT_BROKER_HOST")
    port = _required_env("PQC_TLS_REPEAT_BROKER_PORT")
    ca_file = Path(_required_env("PQC_TLS_REPEAT_BROKER_CA"))
    server_name = _required_env("PQC_TLS_REPEAT_BROKER_SERVER_NAME")
    iterations = int(os.environ.get("PQC_TLS_REPEAT_BROKER_ITERATIONS", "3"))
    assert ca_file.is_file()
    assert iterations >= 2

    client_cert = os.environ.get("PQC_TLS_REPEAT_BROKER_CLIENT_CERT", "").strip()
    client_key = os.environ.get("PQC_TLS_REPEAT_BROKER_CLIENT_KEY", "").strip()

    for _ in range(iterations):
        command = [
            "openssl", "s_client", "-brief", "-tls1_3", "-no_ticket",
            "-connect", f"{host}:{port}", "-servername", server_name,
            "-CAfile", str(ca_file),
        ]
        if client_cert or client_key:
            if not (client_cert and client_key):
                pytest.fail("both client certificate and key are required for mutual TLS")
            command += ["-cert", client_cert, "-key", client_key]
        completed = subprocess.run(
            command,
            input="",
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=60,
        )
        output = completed.stdout + completed.stderr
        assert completed.returncode == 0, output
        assert "TLSv1.3" in output, output
