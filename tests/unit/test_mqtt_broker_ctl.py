from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "experiment" / "mqtt-broker" / "scripts" / "mqtt_broker_ctl.py"
    spec = importlib.util.spec_from_file_location("mqtt_broker_ctl", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module




def test_remote_repo_root_is_derived_from_broker_directory():
    module = load_module()

    assert (
        module.remote_repo_root("~/pqc-framework-02/experiment/mqtt-broker")
        == "~/pqc-framework-02"
    )


def test_remote_repo_root_rejects_unrelated_directory():
    module = load_module()

    try:
        module.remote_repo_root("~/custom-broker")
    except SystemExit as exc:
        assert "must end with /experiment/mqtt-broker" in str(exc)
    else:
        raise AssertionError("expected invalid remote directory to be rejected")








def test_broker_ctl_uses_pinned_shared_image_and_collects_tls_keylog():
    source = Path("experiment/mqtt-broker/scripts/mqtt_broker_ctl.py").read_text(encoding="utf-8")
    assert 'MOSQUITTO_IMAGE = "eclipse-mosquitto:2.1.2-alpine@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797"' in source
    assert "openquantumsafe/mosquitto" not in source
    assert 'sub.add_parser("collect-tls-keylog"' in source
    assert 'TLS_KEYLOG_FILENAME = "mqtt-broker-tls-keylog.log"' in source
    assert 'docker compose --project-name' in source
    assert 'exec -T' in source
    assert 'test -s /mosquitto/keylog/' in source


def test_broker_start_waits_for_healthy_container():
    source = Path("experiment/mqtt-broker/scripts/mqtt_broker_ctl.py").read_text(encoding="utf-8")
    assert '["--profile", args.profile, "up", "-d", "--wait", "--wait-timeout", "90"]' in source






def test_certificate_profile_directory_is_root_secrets_certificates(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    assert module.certificate_profile_dir("ecdsa-p256") == tmp_path / "secrets" / "certificates" / "ecdsa-p256"


def test_broker_ctl_has_no_certificate_provisioning_subcommand():
    module = load_module()
    parser = module.build_parser()
    for command in ("provision-certs", "provision-oqs-certs"):
        try:
            parser.parse_args([command])
        except SystemExit:
            pass
        else:
            raise AssertionError(f"legacy certificate provisioning command still exists: {command}")


def test_status_accepts_reporting_profile_and_targets_reporting_service(monkeypatch):
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args(["status", "--profile", "reporting"])
    calls = []

    monkeypatch.setattr(module, "compose_remote", lambda namespace, compose_args: calls.append(compose_args))
    args.func(args)

    assert args.profile == "reporting"
    assert calls == [["ps", "mqtt-reporting"]]


def test_status_defaults_to_classical_profile(monkeypatch):
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args(["status"])
    calls = []

    monkeypatch.setattr(module, "compose_remote", lambda namespace, compose_args: calls.append(compose_args))
    args.func(args)

    assert args.profile == "classical"
    assert calls == [["ps", "mqtt-classical"]]
