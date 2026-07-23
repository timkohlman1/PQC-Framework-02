from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = REPO_ROOT / "experiment" / "mqtt-broker"


def _require_docker_compose() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker command is not available")

    completed = subprocess.run(
        ["docker", "compose", "version"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        pytest.skip(f"docker compose is not available: {detail}")


def _compose_config(*, env: dict[str, str] | None = None) -> dict[str, Any]:
    _require_docker_compose()
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "classical",
            "--profile",
            "oqs",
            "config",
            "--format",
            "json",
        ],
        cwd=BROKER_ROOT,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, (
        "docker compose config failed\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )

    rendered = json.loads(completed.stdout)
    assert isinstance(rendered, dict)
    return rendered


def _service(config: dict[str, Any], name: str) -> dict[str, Any]:
    services = config.get("services")
    assert isinstance(services, dict)
    service = services.get(name)
    assert isinstance(service, dict), f"missing service {name!r}"
    return service


@pytest.mark.integration
@pytest.mark.docker
def test_mqtt_broker_compose_config_renders_classical_and_oqs_services():
    config = _compose_config()

    classical = _service(config, "mqtt-classical")
    oqs = _service(config, "mqtt-oqs")

    assert classical["image"] == "eclipse-mosquitto:2.0"
    assert oqs["image"] == "openquantumsafe/mosquitto:latest"
    assert classical["profiles"] == ["classical"]
    assert oqs["profiles"] == ["oqs"]
    assert classical["user"] == "0:0"
    assert oqs["user"] == "0:0"
    assert classical["entrypoint"][:2] == ["/bin/sh", "-ec"]
    assert oqs["entrypoint"][:2] == ["/bin/sh", "-ec"]

    classical_mount_targets = {volume["target"] for volume in classical["volumes"]}
    oqs_mount_targets = {volume["target"] for volume in oqs["volumes"]}

    assert "/mosquitto/config/mosquitto.conf" in classical_mount_targets
    assert "/mosquitto/config/aclfile.source" in classical_mount_targets
    assert "/mosquitto/config/certs" in classical_mount_targets
    assert "/mosquitto/data" in classical_mount_targets
    assert "/mosquitto/log" in classical_mount_targets

    assert "/mosquitto/config/mosquitto.conf" in oqs_mount_targets
    assert "/mosquitto/config/openssl.cnf" in oqs_mount_targets
    assert "/mosquitto/config/aclfile.source" in oqs_mount_targets
    assert "/mosquitto/config/certs" in oqs_mount_targets
    assert "/mosquitto/data" not in oqs_mount_targets
    assert "/mosquitto/log" not in oqs_mount_targets

    assert oqs["environment"]["OPENSSL_CONF"] == "/mosquitto/config/openssl.cnf"
    assert oqs["environment"]["OPENSSL_MODULES"] == "/opt/oqssa/lib64/ossl-modules"


@pytest.mark.integration
@pytest.mark.docker
def test_mqtt_broker_compose_config_renders_port_overrides_without_gateway():
    config = _compose_config(
        env={
            "MQTT_CLASSICAL_TLS_PORT": "28883",
            "MQTT_OQS_TLS_PORT": "28884",
        }
    )

    classical = _service(config, "mqtt-classical")
    oqs = _service(config, "mqtt-oqs")

    assert classical["ports"][0]["published"] == "28883"
    assert classical["ports"][0]["target"] == 8883
    assert oqs["ports"][0]["published"] == "28884"
    assert oqs["ports"][0]["target"] == 8883
