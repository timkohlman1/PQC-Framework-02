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


def test_oqs_provision_command_is_stepca_sync_alias():
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args(["provision-oqs-certs"])

    assert args.certificate_profile == "stepca-classical"
    assert args.func is module.sync_stepca_certs
    assert not hasattr(args, "ca_algorithm")
    assert not hasattr(args, "leaf_algorithm")


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


def test_provision_defaults_to_long_lived_leaf_policy():
    module = load_module()
    args = module.build_parser().parse_args(["provision-certs"])
    assert args.days == 365
    assert args.renew_before_days == 30
    assert args.reset_pki is False


def test_certificate_lifecycle_skips_compose_when_material_is_fresh(tmp_path, monkeypatch):
    module = load_module()
    args = module.build_parser().parse_args(["provision-certs"])
    for relative in (
        "secrets/public/ca/root-ca.crt",
        "secrets/public/ca/intermediate-ca.crt",
        "secrets/public/ca/ca-chain.crt",
        "secrets/runtime/mqtt-broker/tls.crt",
        "secrets/runtime/mqtt-broker/tls.key",
        "secrets/runtime/stm32/client.crt",
        "secrets/runtime/stm32/client.key",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("material", encoding="utf-8")
    monkeypatch.setattr(module, "_certificate_valid_for", lambda *a, **k: True)
    monkeypatch.setattr(module, "_run_local_compose", lambda *a, **k: (_ for _ in ()).throw(AssertionError("compose should not start")))
    assert module.ensure_framework_certificates(args, tmp_path) is False


def test_certificate_policy_forces_stepca_process_restart() -> None:
    source = Path("experiment/mqtt-broker/scripts/mqtt_broker_ctl.py").read_text(encoding="utf-8")

    policy_position = source.index('"stepca_policy"')
    restart_position = source.index('["restart", "stepca"]', policy_position)
    health_position = source.index('["up", "-d", "--wait", "stepca"]', restart_position)
    issuance_position = source.index('for service in ("mqtt-broker_cert", "stm32_client_cert")', health_position)

    assert policy_position < restart_position < health_position < issuance_position


def test_broker_ctl_uses_pinned_shared_image_and_collects_tls_keylog():
    source = Path("experiment/mqtt-broker/scripts/mqtt_broker_ctl.py").read_text(encoding="utf-8")
    assert 'MOSQUITTO_IMAGE = "eclipse-mosquitto:2.1.2-alpine"' in source
    assert "openquantumsafe/mosquitto" not in source
    assert 'sub.add_parser("collect-tls-keylog"' in source
    assert 'TLS_KEYLOG_FILENAME = "mqtt-broker-tls-keylog.log"' in source
    assert 'docker compose --project-name' in source
    assert 'exec -T' in source
    assert 'test -s /mosquitto/keylog/' in source


def test_broker_start_waits_for_healthy_container():
    source = Path("experiment/mqtt-broker/scripts/mqtt_broker_ctl.py").read_text(encoding="utf-8")
    assert '["--profile", args.profile, "up", "-d", "--wait", "--wait-timeout", "90"]' in source
