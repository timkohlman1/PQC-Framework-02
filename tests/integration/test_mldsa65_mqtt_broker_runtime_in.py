from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = REPO_ROOT / "experiment" / "mqtt-broker"
BROKER_CTL = BROKER_ROOT / "scripts" / "mqtt_broker_ctl.py"
PROFILE_ID = "mldsa65"


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _require_docker_runtime() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker command is not available")
    compose = _run(["docker", "compose", "version"], cwd=REPO_ROOT, timeout=30)
    if compose.returncode != 0:
        pytest.skip("docker compose is not available")
    info = _run(["docker", "info"], cwd=REPO_ROOT, timeout=30)
    if info.returncode != 0:
        pytest.skip("docker daemon is not available")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _assert_success(completed: subprocess.CompletedProcess[str], label: str) -> None:
    assert completed.returncode == 0, (
        f"{label} failed with exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.docker_runtime
def test_mldsa65_profile_accepts_hybrid_mutual_tls_when_preprovisioned() -> None:
    """Exercise the real ML-DSA certificate family with the maintained hybrid broker."""
    _require_docker_runtime()

    cert_dir = REPO_ROOT / "secrets" / "certificates" / PROFILE_ID
    if not cert_dir.is_dir():
        pytest.skip("pre-provisioned ML-DSA-65 certificate profile is unavailable")

    required = (
        "ca.crt",
        "intermediate-ca.crt",
        "ca-chain.crt",
        "server.crt",
        "server.key",
        "client.crt",
        "client.key",
        "healthcheck.crt",
        "healthcheck.key",
    )
    missing = [name for name in required if not (cert_dir / name).is_file()]
    assert not missing, "ML-DSA-65 certificate profile is incomplete: " + ", ".join(missing)

    project_name = f"pqc-mldsa65-runtime-{uuid.uuid4().hex[:10]}"
    host_port = _free_port()
    env = {
        **os.environ,
        "MQTT_CERTIFICATE_PROFILE": PROFILE_ID,
        "MQTT_OQS_MTLS_PORT": str(host_port),
    }
    up = _run(
        [
            "docker",
            "compose",
            "--project-name",
            project_name,
            "--profile",
            "oqs-mtls",
            "up",
            "-d",
            "mqtt-oqs-mtls",
        ],
        cwd=BROKER_ROOT,
        env=env,
        timeout=180,
    )
    _assert_success(up, "docker compose up mqtt-oqs-mtls with ML-DSA-65 material")

    try:
        last: subprocess.CompletedProcess[str] | None = None
        for _attempt in range(30):
            last = _run(
                [
                    "docker",
                    "compose",
                    "--project-name",
                    project_name,
                    "exec",
                    "-T",
                    "mqtt-oqs-mtls",
                    "mosquitto_pub",
                    "-h",
                    "127.0.0.1",
                    "-p",
                    "8883",
                    "--cafile",
                    "/tmp/mosquitto-certs/ca.crt",
                    "--cert",
                    "/tmp/mosquitto-certs/healthcheck.crt",
                    "--key",
                    "/tmp/mosquitto-certs/healthcheck.key",
                    "--tls-version",
                    "tlsv1.3",
                    "-t",
                    "pqc/framework/ml-dsa-65-runtime",
                    "-m",
                    "ready",
                ],
                cwd=BROKER_ROOT,
                env=env,
                timeout=30,
            )
            if last.returncode == 0:
                break
            time.sleep(1)
        assert last is not None
        _assert_success(last, "ML-DSA-65 hybrid mutual-TLS publish")
    finally:
        down = _run(
            [
                "docker",
                "compose",
                "--project-name",
                project_name,
                "--profile",
                "oqs-mtls",
                "down",
                "--remove-orphans",
            ],
            cwd=BROKER_ROOT,
            env=env,
            timeout=120,
        )
        assert down.returncode == 0, (
            "docker compose cleanup failed\n"
            f"stdout:\n{down.stdout}\n"
            f"stderr:\n{down.stderr}"
        )
