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


def test_oqs_certificate_defaults_match_stm32_mldsa65_profile():
    module = load_module()
    parser = module.build_parser()
    args = parser.parse_args(["provision-oqs-certs"])

    assert module.OQS_CA_ALGORITHM == "mldsa65"
    assert module.OQS_LEAF_ALGORITHM == "mldsa65"
    assert args.ca_algorithm == "mldsa65"
    assert args.leaf_algorithm == "mldsa65"


def test_oqs_provisioning_script_verifies_chain_key_match_and_writes_provenance(monkeypatch, tmp_path):
    module = load_module()
    commands: list[list[str]] = []
    input_commands: list[tuple[list[str], str]] = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "broker_root", lambda: tmp_path / "experiment" / "mqtt-broker")
    monkeypatch.setattr(
        module,
        "load_host_config",
        lambda path: module.HostConfig(alias="gateway", user=None, address="10.1.1.18"),
    )
    monkeypatch.setattr(
        module,
        "run_command",
        lambda args, cwd=None, dry_run=False: commands.append(args),
    )
    monkeypatch.setattr(
        module,
        "run_command_with_input",
        lambda args, content, dry_run=False: input_commands.append((args, content)),
    )

    args = module.build_parser().parse_args(["provision-oqs-certs", "--dry-run"])
    module.provision_oqs_certs(args)

    docker_command = next(
        command[2] for command in commands
        if command[:2] == ["ssh", "gateway"] and "docker run" in command[2]
    )
    assert "openssl genpkey -algorithm mldsa65 -out /certs/server.key" in docker_command
    assert "openssl verify -CAfile /certs/ca.crt" in docker_command
    assert "cmp /tmp/server-key.pub /tmp/server-cert.pub" in docker_command
    assert "certificate-provenance.txt" in docker_command
    assert any(command[0] == "scp" and command[1].endswith("/ca.crt") for command in commands)
    assert any(
        command[0] == "scp" and command[1].endswith("/certificate-provenance.txt")
        for command in commands
    )
    assert len(input_commands) == 4
