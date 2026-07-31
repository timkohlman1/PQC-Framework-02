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


def test_stepca_policy_uses_mounted_script_not_embedded_heredoc():
    root = Path(__file__).resolve().parents[2]
    compose_text = (root / "compose.certs.yml").read_text(encoding="utf-8")
    policy_script = root / "services" / "stepca-policy" / "update_policy.py"

    assert policy_script.is_file()
    assert '["python", "/app/update_policy.py"]' in compose_text
    assert "services/stepca-policy/update_policy.py:/app/update_policy.py:ro" in compose_text
    assert 'python - <<"PY"' not in compose_text


def test_stepca_policy_sets_authority_and_provisioner_duration_limits() -> None:
    policy_script = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "stepca-policy"
        / "update_policy.py"
    ).read_text(encoding="utf-8")

    assert 'authority.setdefault("claims", {})' in policy_script
    assert 'DEFAULT_LEAF_DURATION = "8760h"' in policy_script
    assert 'DEFAULT_MAXIMUM_DURATION = "8784h"' in policy_script
    assert '_apply_claims(' in policy_script
