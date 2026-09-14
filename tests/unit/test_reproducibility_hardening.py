from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_source_module():
    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from framework import source
    return source


def test_reproducibility_provenance_records_parent_submodules_and_effective_tools(tmp_path):
    source = _load_source_module()

    def git_runner(command, cwd):
        assert cwd == tmp_path
        outputs = {
            ("git", "rev-parse", "HEAD"): "parent123\n",
            ("git", "status", "--short"): " M README.md\n",
            ("git", "submodule", "status", "--recursive"): (
                " abc111 Middlewares/Third_Party/wolfSSL (heads/main)\n"
                "+def222 tools/wolfboot (v2.9.0)\n"
            ),
            ("git", "-C", "Middlewares/Third_Party/wolfSSL", "status", "--short"): "",
            ("git", "-C", "tools/wolfboot", "status", "--short"): " M Makefile\n",
        }
        key = tuple(command)
        if key not in outputs:
            raise AssertionError(f"unexpected git command: {command}")
        return source.GitCommandExecution(command, 0, outputs[key], "", 0.01)

    versions = {
        "arm-none-eabi-gcc": "arm-none-eabi-gcc (GNU Arm Embedded Toolchain) 13.3.1\n",
        "cmake": "cmake version 3.31.6\n",
        "ninja": "1.12.1\n",
        sys.executable: "Python 3.13.15\n",
        "openssl": "OpenSSL 3.5.2 5 Aug 2025\n",
    }

    def tool_runner(command, cwd):
        assert cwd == tmp_path
        value = versions[command[0]]
        return source.GitCommandExecution(command, 0, value, "", 0.01)

    result = source.capture_reproducibility_provenance(
        tmp_path,
        git_runner=git_runner,
        tool_runner=tool_runner,
    )

    assert result["git_commit"] == "parent123"
    assert result["git_dirty"] is True
    assert result["submodules"]["available"] is True
    assert result["submodules"]["entries"] == [
        {
            "path": "Middlewares/Third_Party/wolfSSL",
            "commit": "abc111",
            "checkout_state": "recorded",
            "dirty": False,
            "status_available": True,
        },
        {
            "path": "tools/wolfboot",
            "commit": "def222",
            "checkout_state": "different_from_recorded",
            "dirty": True,
            "status_available": True,
        },
    ]
    assert result["tools"]["compiler"]["version"].startswith("arm-none-eabi-gcc")
    assert result["tools"]["cmake"]["version"] == "cmake version 3.31.6"
    assert result["tools"]["ninja"]["version"] == "1.12.1"
    assert result["tools"]["python"]["version"] == "Python 3.13.15"
    assert result["tools"]["openssl"]["version"].startswith("OpenSSL 3.5.2")


def test_ci_compose_and_broker_controller_use_one_mosquitto_image():
    expected = "eclipse-mosquitto:2.1.2-alpine@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797"
    compose = (ROOT / "experiment" / "mqtt-broker" / "compose.yaml").read_text(encoding="utf-8")
    ctl = (ROOT / "experiment" / "mqtt-broker" / "scripts" / "mqtt_broker_ctl.py").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert compose.count(f"image: {expected}") == 5
    assert f'MOSQUITTO_IMAGE = "{expected}"' in ctl
    assert f"docker pull {expected}" in ci
    assert "eclipse-mosquitto:2.0" not in ci


def test_development_container_pins_python_patch_and_debian_release():
    dockerfile = (ROOT / "docker" / "python" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285" in dockerfile


def test_gateway_certificate_deploy_never_makes_private_keys_world_readable():
    ctl = (ROOT / "experiment" / "mqtt-broker" / "scripts" / "mqtt_broker_ctl.py").read_text(encoding="utf-8")
    assert "chmod -R a+rX \" + \" \".join" not in ctl
    assert "-name '*.key' -exec chmod 0600" in ctl
    assert "-type d -exec chmod 0700" in ctl
    assert "-type f ! -name '*.key' -exec chmod 0644" in ctl


def test_canonical_yaml_contains_secret_references_not_wifi_secret_values():
    target = yaml.safe_load((ROOT / "configs" / "targets" / "stm32l4r5_st67.yaml").read_text(encoding="utf-8"))
    wifi = target["network"]["wifi"]
    assert wifi == {
        "ssid_ref": "env:PQC_WIFI_SSID",
        "psk_ref": "env:PQC_WIFI_PSK",
    }
    assert "ssid" not in wifi
    assert "psk" not in wifi


def test_broker_controller_exposes_runtime_version_evidence_command():
    ctl_path = ROOT / "experiment" / "mqtt-broker" / "scripts" / "mqtt_broker_ctl.py"
    spec = importlib.util.spec_from_file_location("mqtt_broker_ctl_repro", ctl_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    args = module.build_parser().parse_args(["runtime-version", "--dry-run"])
    assert args.command == "runtime-version"
    assert args.image == "eclipse-mosquitto:2.1.2-alpine@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797"
