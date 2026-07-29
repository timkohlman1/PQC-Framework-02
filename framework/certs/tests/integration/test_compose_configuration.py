from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _compose_config() -> str:
    if not shutil.which("docker"):
        pytest.skip("Docker is not installed")
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["docker", "compose", "config"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_compose_configuration_renders():
    _compose_config()


def test_compose_declares_mqtt_and_offline_root_services():
    rendered = _compose_config()
    assert "mqtt-broker_cert:" in rendered
    assert "stm32_client_cert:" in rendered
    assert "stepca_secure_root:" in rendered
    assert "web_cert:" not in rendered
    assert "web_client_cert:" not in rendered
    assert "secrets/public/ca" in rendered.replace("\\", "/")
