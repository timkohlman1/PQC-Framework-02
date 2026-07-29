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
