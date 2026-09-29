#!/usr/bin/env python3
"""Host-side Docker check of staged certificates and oqs-mtls readiness.

Consumes pre-provisioned experiment certificates without displaying their contents.
Uses unique Compose projects and ephemeral loopback ports; never contacts a gateway.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / "experiment/mqtt-broker"


def check_profile(profile: str) -> None:
    project = f"pqc-oqs-check-{uuid.uuid4().hex[:12]}"
    env = {**os.environ, "MQTT_CERTIFICATE_PROFILE": profile,
           "MQTT_OQS_MTLS_PORT": "127.0.0.1:0"}
    base = ["docker", "compose", "--project-name", project, "--profile", "oqs-mtls"]

    def run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
        return subprocess.run([*base, *args], cwd=BROKER, env=env, text=True,
                              capture_output=True, timeout=timeout, check=False)

    def require(result: subprocess.CompletedProcess[str], label: str) -> None:
        if result.returncode:
            raise RuntimeError(f"{profile}: {label} failed\n{result.stdout}\n{result.stderr}")

    try:
        require(run(["up", "-d", "--wait", "--wait-timeout", "60", "mqtt-oqs-mtls"]), "healthy startup")
        # Verify access after privilege drop while the original mount stays protected.
        require(run(["exec", "-T", "--user", "nobody", "mqtt-oqs-mtls", "sh", "-ec",
                     "test -r /tmp/mosquitto-certs/ca-chain.crt && "
                     "test -r /tmp/mosquitto-certs/server.key && "
                     "test ! -r /mosquitto/config/certs/server.key"]), "runtime certificate permissions")
        probe = ["exec", "-T", "mqtt-oqs-mtls", "mosquitto_pub", "-h", "127.0.0.1", "-p", "8883",
                 "--cafile", "/tmp/mosquitto-certs/ca.crt", "--insecure", "--tls-version", "tlsv1.3",
                 "-q", "1", "-t", "pqc/framework/health", "-m", "ready"]
        require(run([*probe, "--cert", "/tmp/mosquitto-certs/healthcheck.crt",
                     "--key", "/tmp/mosquitto-certs/healthcheck.key"], timeout=30), "authenticated health publish")
        if run(probe, timeout=30).returncode == 0:
            raise RuntimeError(f"{profile}: broker unexpectedly accepted a client without a certificate")
        print(f"PASS {profile}: healthy broker, readable staged chain, protected source key, mutual TLS enforced", flush=True)
    except Exception:
        logs = run(["logs", "--no-color", "--tail", "60", "mqtt-oqs-mtls"], timeout=30)
        print(logs.stdout, flush=True)
        raise
    finally:
        require(run(["down", "--remove-orphans"], timeout=60), "cleanup")


if __name__ == "__main__":
    for selected_profile in ("rsa3072", "mldsa65"):
        check_profile(selected_profile)
