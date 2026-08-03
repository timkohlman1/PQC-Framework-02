from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = REPO_ROOT / "experiment" / "mqtt-broker"
SCRIPT_PATH = BROKER_ROOT / "scripts" / "mqtt_broker_ctl.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")




def _service_block(compose: str, service: str) -> str:
    marker = f"  {service}:\n"
    start = compose.index(marker)
    next_service = compose.find("\n  mqtt-", start + len(marker))
    return compose[start:] if next_service == -1 else compose[start:next_service]


def _load_ctl_module():
    spec = importlib.util.spec_from_file_location("mqtt_broker_ctl", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mqtt_broker_compose_declares_classical_and_oqs_profiles():
    compose = _read(BROKER_ROOT / "compose.yaml")

    assert "mqtt-classical:" in compose
    assert "mqtt-oqs:" in compose
    assert 'profiles: ["classical"]' in compose
    assert 'profiles: ["oqs"]' in compose
    assert "eclipse-mosquitto:2.1.2-alpine" in compose
    assert "eclipse-mosquitto" in compose
    assert "${MQTT_CLASSICAL_TLS_PORT:-8883}:8883" in compose
    assert "${MQTT_OQS_TLS_PORT:-8884}:8883" in compose


def test_mqtt_broker_compose_mounts_acl_files_directly_and_copies_private_keys():
    compose = _read(BROKER_ROOT / "compose.yaml")

    assert "user: \"0:0\"" in compose
    assert "entrypoint:" in compose
    assert "- /bin/sh" in compose
    assert "- -ec" in compose
    assert "command: |" not in compose
    assert "aclfile.source" in compose
    assert "cp /mosquitto/config/aclfile.source /tmp/mosquitto-aclfile" not in compose
    assert "cp /mosquitto/config/certs/server.key /tmp/mosquitto-certs/server.key" in compose
    assert "chmod 0640 /tmp/mosquitto-certs/server.key" in compose
    classical = _service_block(compose, "mqtt-classical")
    classical_server_auth = _service_block(compose, "mqtt-classical-server-auth")
    oqs = _service_block(compose, "mqtt-oqs")
    oqs_mtls = _service_block(compose, "mqtt-oqs-mtls")

    for block in (classical, classical_server_auth):
        assert "if id mosquitto >/dev/null 2>&1; then" in block
        assert 'runtime_user="$(id -u mosquitto)"' in block

    for block in (oqs, oqs_mtls):
        assert "if id nobody >/dev/null 2>&1; then" in block
        assert 'runtime_user="$(id -u nobody)"' in block
        assert 'runtime_user="$(id -u mosquitto)"' not in block

    assert compose.count('chown "$$runtime_user:$$runtime_group" /tmp/mosquitto-certs/*') == 4
    assert compose.count("runtime_user=0") == 4
    assert compose.count("runtime_group=0") == 4
    assert "/tmp/mosquitto-aclfile" not in compose
    assert "cp /mosquitto/config/certs/ca-chain.crt /tmp/mosquitto-certs/ca-chain.crt" in compose
    assert "chmod 0644 /tmp/mosquitto-certs/ca.crt /tmp/mosquitto-certs/ca-chain.crt /tmp/mosquitto-certs/server.crt" in compose
    assert "exec mosquitto --tls-keylog /mosquitto/keylog/mqtt-broker-tls-keylog.log -c /mosquitto/config/mosquitto.conf" in compose


def test_mosquitto_configs_use_listener_specific_anonymous_options_without_deprecated_global_switch():
    for relative_path in (
        "config/classical/mosquitto.conf",
        "config/classical-server-auth/mosquitto.conf",
        "config/oqs/mosquitto.conf",
        "config/oqs-mtls/mosquitto.conf",
    ):
        config = _read(BROKER_ROOT / relative_path)
        assert "per_listener_settings" not in config
        assert "\nallow_anonymous " not in config
        assert "listener_allow_anonymous " in config


def test_mqtt_broker_compose_avoids_fixed_container_and_network_names():
    compose = _read(BROKER_ROOT / "compose.yaml")

    assert "container_name:" not in compose
    assert "name: pqc-framework-mqtt-broker" not in compose
    assert "name: pqc-framework-mqtt-broker" not in compose


def test_classical_mosquitto_config_enforces_tls_and_client_certificates():
    config = _read(BROKER_ROOT / "config" / "classical" / "mosquitto.conf")

    assert "listener 8883 0.0.0.0" in config
    assert "tls_version tlsv1.3" in config
    assert "listener_allow_anonymous true" in config
    assert "require_certificate true" in config
    assert "use_identity_as_username true" in config
    assert "cafile /tmp/mosquitto-certs/ca-chain.crt" in config
    assert "certfile /tmp/mosquitto-certs/server.crt" in config
    assert "keyfile /tmp/mosquitto-certs/server.key" in config


def test_mqtt_runtime_paths_are_ignored_by_git():
    gitignore = _read(REPO_ROOT / ".gitignore")

    assert "experiment/mqtt-broker/runtime/" in gitignore
    assert "experiment/mqtt-broker/data/" in gitignore
    assert "experiment/mqtt-broker/log/" in gitignore
    assert "experiment/mqtt-broker/.env" in gitignore


def test_gateway_host_config_records_network_address_for_non_ssh_clients():
    gateway = _read(REPO_ROOT / "configs" / "hosts" / "gateway.yaml")

    assert "alias: pqc-gateway1" in gateway
    assert "user: timk" in gateway
    assert "network:" in gateway
    assert "address: 10.1.1.18" in gateway


def test_mqtt_control_script_has_expected_subcommands_and_defaults():
    module = _load_ctl_module()
    parser = module.build_parser()

    assert parser.parse_args(["deploy", "--dry-run"]).command == "deploy"
    assert parser.parse_args(["start", "--profile", "classical", "--dry-run"]).profile == "classical"
    assert parser.parse_args(["start", "--profile", "oqs", "--dry-run"]).profile == "oqs"
    assert parser.parse_args(["start", "--classical-port", "28883", "--dry-run"]).classical_port == 28883
    assert parser.parse_args(["start", "--project-name", "pytest-mqtt", "--dry-run"]).project_name == "pytest-mqtt"
    assert parser.parse_args(["stop", "--dry-run"]).command == "stop"
    assert parser.parse_args(["status", "--dry-run"]).command == "status"
    assert parser.parse_args(["logs", "--profile", "oqs", "--dry-run"]).profile == "oqs"
    assert parser.parse_args(["validate-classical-server-auth-mqtt", "--dry-run"]).command == "validate-classical-server-auth-mqtt"


def test_mqtt_control_script_reads_gateway_alias_user_and_address_from_host_config(tmp_path):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text(
        "id: gateway\nalias: test-gateway\nuser: timk\nnetwork:\n  address: 10.1.1.18\n",
        encoding="utf-8",
    )

    loaded = module.load_host_config(host_config)

    assert loaded.alias == "test-gateway"
    assert loaded.user == "timk"
    assert loaded.address == "10.1.1.18"
    assert module.ssh_target(loaded) == "timk@test-gateway"
    assert module.tls_host(loaded) == "10.1.1.18"


def test_mqtt_control_script_uses_configured_ssh_user_for_remote_commands(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "broker_root", lambda: tmp_path / "experiment" / "mqtt-broker")
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args(["deploy", "--host-config", str(host_config), "--dry-run"])
    module.deploy(args)

    assert commands
    assert commands[0][:2] == ["ssh", "timk@pqc-gateway1"]
    assert any(command[0:2] == ["scp", "-r"] and "timk@pqc-gateway1:" in command[-1] for command in commands)


def test_mqtt_deploy_copies_script_source_without_python_cache(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    broker_root = tmp_path / "experiment" / "mqtt-broker"
    (broker_root / "scripts" / "__pycache__").mkdir(parents=True)
    (tmp_path / "secrets" / "mqtt" / "stepca-classical").mkdir(parents=True)
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "broker_root", lambda: broker_root)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args(["deploy", "--host-config", str(host_config), "--dry-run"])
    module.deploy(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "$HOME/pqc-framework-02/secrets" in commands[0][-1]
    assert "$HOME/pqc-framework-02/secrets/mqtt" in commands[0][-1]
    assert "__pycache__" not in command_text
    assert "mqtt_broker_ctl.cpython" not in command_text
    assert any(command[0] == "scp" and command[1].endswith("mqtt_broker_ctl.py") for command in commands)
    assert any(command[0:2] == ["scp", "-r"] and command[2].replace("\\", "/").endswith("secrets/mqtt") for command in commands)


def test_mqtt_deploy_sets_remote_config_and_classical_runtime_read_permissions(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    broker_root = tmp_path / "experiment" / "mqtt-broker"
    (tmp_path / "secrets" / "mqtt" / "stepca-classical").mkdir(parents=True)
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "broker_root", lambda: broker_root)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args(["deploy", "--host-config", str(host_config), "--dry-run"])
    module.deploy(args)

    permission_commands = [
        command
        for command in commands
        if command[:2] == ["ssh", "timk@pqc-gateway1"] and "chmod -R a+rX" in command[-1]
    ]
    assert permission_commands
    assert "$HOME/pqc-framework-02/experiment/mqtt-broker/config" in permission_commands[-1][-1]
    assert "$HOME/pqc-framework-02/secrets/mqtt" in permission_commands[-1][-1]
    assert "$HOME/pqc-framework-02/experiment/mqtt-broker/runtime" not in permission_commands[-1][-1]


def test_mqtt_deploy_does_not_chmod_remote_oqs_runtime(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    broker_root = tmp_path / "experiment" / "mqtt-broker"
    (tmp_path / "secrets" / "mqtt" / "stepca-classical").mkdir(parents=True)
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "broker_root", lambda: broker_root)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args(["deploy", "--host-config", str(host_config), "--dry-run"])
    module.deploy(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "secrets/mqtt" in command_text
    assert "chmod -R a+rX $HOME/pqc-framework-02/experiment/mqtt-broker/config $HOME/pqc-framework-02/secrets/mqtt" in command_text
    assert "runtime/oqs" not in command_text


def test_mqtt_start_supports_isolated_project_name_and_port_override(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args([
        "start",
        "--host-config",
        str(host_config),
        "--project-name",
        "pytest-mqtt",
        "--classical-port",
        "28883",
        "--dry-run",
    ])
    module.start(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "MQTT_CLASSICAL_TLS_PORT=28883" in command_text
    assert "docker compose --project-name pytest-mqtt --profile classical up -d" in command_text


def test_mqtt_stop_removes_profiled_and_orphaned_broker_containers(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args(["stop", "--host-config", str(host_config), "--dry-run"])
    module.stop(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert (
        "docker compose --project-name pqc-framework-mqtt-broker "
        "--profile classical --profile classical-server-auth --profile oqs --profile oqs-mtls "
        "down --remove-orphans"
    ) in command_text
    assert (
        "docker rm -f pqc-mqtt-classical pqc-mqtt-classical-server-auth "
        "pqc-mqtt-oqs"
    ) in command_text
    assert "|| true" in command_text


def test_mqtt_docs_record_oqs_as_experimental_not_production():
    readme = _read(BROKER_ROOT / "README.md")
    oqs_readme = _read(BROKER_ROOT / "config" / "oqs" / "README.md")

    assert "experimental" in readme.lower()
    assert "not be treated as production" in readme
    assert "Confirm negotiated algorithms" in oqs_readme


def test_mqtt_cert_provisioning_synchronizes_authoritative_stepca_material(tmp_path, monkeypatch):
    module = _load_ctl_module()
    source_root = tmp_path / "framework" / "certs"
    public_ca = source_root / "secrets" / "public" / "ca"
    broker_identity = source_root / "secrets" / "runtime" / "mqtt-broker"
    client_identity = source_root / "secrets" / "runtime" / "stm32"
    public_ca.mkdir(parents=True)
    broker_identity.mkdir(parents=True)
    client_identity.mkdir(parents=True)

    (public_ca / "root-ca.crt").write_text("root", encoding="utf-8")
    (public_ca / "intermediate-ca.crt").write_text("intermediate", encoding="utf-8")
    (public_ca / "ca-chain.crt").write_text("chain", encoding="utf-8")
    (broker_identity / "tls.crt").write_text("server cert", encoding="utf-8")
    (broker_identity / "tls.key").write_text("server key", encoding="utf-8")
    (client_identity / "client.crt").write_text("client cert", encoding="utf-8")
    (client_identity / "client.key").write_text("client key", encoding="utf-8")

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "broker_root", lambda: tmp_path)
    monkeypatch.setattr(module, "_certificate_valid_for", lambda *_args, **_kwargs: True)

    args = module.build_parser().parse_args([
        "provision-certs",
        "--certificate-profile",
        "stepca-classical",
    ])
    module.sync_stepca_certs(args)

    cert_dir = tmp_path / "secrets" / "mqtt" / "stepca-classical"
    assert (cert_dir / "ca.crt").read_text(encoding="utf-8") == "root"
    assert (cert_dir / "intermediate-ca.crt").read_text(encoding="utf-8") == "intermediate"
    assert (cert_dir / "ca-chain.crt").read_text(encoding="utf-8") == "chain"
    assert (cert_dir / "server.crt").read_text(encoding="utf-8") == "server cert"
    assert (cert_dir / "server.key").read_text(encoding="utf-8") == "server key"
    provenance = json.loads((cert_dir / "certificate-provenance.json").read_text(encoding="utf-8"))
    assert provenance["source"] == "framework/certs"
    assert provenance["profile_kind"] == "stepca-classical"
    assert provenance["ca_algorithm"] == "classical-x509"
    assert provenance["leaf_algorithm"] == "classical"


def test_mqtt_remote_shell_path_preserves_home_directory_expansion():
    module = _load_ctl_module()

    assert module.remote_shell_path("~") == "$HOME"
    assert module.remote_shell_path("~/pqc-framework-02/tmp/test") == "$HOME/pqc-framework-02/tmp/test"
    assert "'~/" not in module.remote_shell_path("~/pqc-framework-02/tmp/test")


def test_mqtt_start_cd_uses_home_expanded_remote_path(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args([
        "start",
        "--host-config",
        str(host_config),
        "--remote-dir",
        "~/pqc-framework-02/experiment/mqtt-broker",
        "--dry-run",
    ])
    module.start(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "cd $HOME/pqc-framework-02/experiment/mqtt-broker" in command_text
    assert "cd '~/" not in command_text


def test_mqtt_remote_cleanup_command_removes_root_owned_mosquitto_paths():
    module = _load_ctl_module()

    command = module.remote_cleanup_command("~/pqc-framework-02/experiment/mqtt-broker")

    assert "docker run --rm" in command
    assert "eclipse-mosquitto:2.1.2-alpine" in command
    assert "-v $HOME/pqc-framework-02/experiment/mqtt-broker:/work" in command
    assert "rm -rf /work/data /work/log" in command
    assert "rm -rf $HOME/pqc-framework-02/experiment/mqtt-broker" in command
    assert "'~/" not in command


def test_oqs_mosquitto_config_enforces_server_authenticated_tls_with_project_certs():
    config = _read(BROKER_ROOT / "config" / "oqs" / "mosquitto.conf")

    assert "listener 8883 0.0.0.0" in config
    assert "tls_version tlsv1.3" in config
    assert "listener_allow_anonymous true" in config
    assert "require_certificate false" in config
    assert "use_identity_as_username false" in config
    assert "cafile /tmp/mosquitto-certs/ca.crt" in config
    assert "certfile /tmp/mosquitto-certs/server.crt" in config
    assert "keyfile /tmp/mosquitto-certs/server.key" in config
    assert "acl_file /mosquitto/config/aclfile.source" in config
    assert "user nobody" in config

def test_oqs_compose_uses_project_managed_hybrid_tls_config_and_strict_healthcheck():
    compose = _read(BROKER_ROOT / "compose.yaml")
    openssl_config = _read(BROKER_ROOT / "config" / "oqs" / "openssl.cnf")

    assert "./config/oqs/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" in compose
    assert "./config/oqs/openssl.cnf:/mosquitto/config/openssl.cnf:ro" in compose
    assert "./config/oqs/aclfile:/mosquitto/config/aclfile.source:ro" in compose
    assert "../../secrets/mqtt/${MQTT_CERTIFICATE_PROFILE:-stepca-classical}:/mosquitto/config/certs:ro" in compose
    assert 'OPENSSL_CONF: "/mosquitto/config/openssl.cnf"' in compose
    assert "OPENSSL_MODULES" not in compose
    assert "Groups = SecP256r1MLKEM768" in openssl_config
    assert "mosquitto_pub -h 127.0.0.1 -p 8883" in compose
    assert "--tls-version tlsv1.3" in compose
    assert "--cafile /tmp/mosquitto-certs/ca.crt" in compose
    assert "Groups = SecP256r1MLKEM768" in openssl_config
    assert "oqsprovider" not in openssl_config
    assert "Groups = SecP256r1MLKEM768" in openssl_config

def test_mqtt_control_script_has_provision_and_validation_subcommands():
    module = _load_ctl_module()
    parser = module.build_parser()

    oqs = parser.parse_args(["provision-oqs-certs", "--dry-run"])
    validate = parser.parse_args(["validate-oqs-tls", "--dry-run"])
    classical_mqtt = parser.parse_args(["validate-classical-mqtt", "--dry-run"])
    oqs_mqtt = parser.parse_args(["validate-oqs-mqtt", "--dry-run"])

    assert oqs.command == "provision-oqs-certs"
    assert oqs.certificate_profile == "stepca-classical"
    assert oqs.func is module.sync_stepca_certs
    assert validate.command == "validate-oqs-tls"
    assert validate.oqs_group == "SecP256r1MLKEM768"
    assert classical_mqtt.command == "validate-classical-mqtt"
    assert classical_mqtt.topic == "pqc/test/e2e"
    assert classical_mqtt.message == "pqc-classical-mqtt-e2e"
    assert classical_mqtt.image == "eclipse-mosquitto:2.1.2-alpine"
    assert callable(classical_mqtt.func)
    assert not isinstance(classical_mqtt.func, type(parser))
    assert oqs_mqtt.command == "validate-oqs-mqtt"
    assert oqs_mqtt.topic == "pqc/test/e2e"
    assert callable(oqs_mqtt.func)
    assert not isinstance(oqs_mqtt.func, type(parser))
    assert module.HOST_BROKER_EVIDENCE_CLASS == "host_side"
    assert module.HOST_BROKER_EVIDENCE_LABEL == "host-side/broker-side MQTT/TLS compatibility evidence"
    assert "does not claim STM32" in module.HOST_BROKER_EVIDENCE_BOUNDARY



def test_validate_classical_mqtt_main_dispatches_to_validation_function(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    result = module.main([
        "validate-classical-mqtt",
        "--host-config",
        str(host_config),
        "--remote-dir",
        "~/pqc-framework-02/experiment/mqtt-broker",
        "--classical-port",
        "28883",
        "--dry-run",
    ])

    assert result == 0
    command_text = "\n".join(" ".join(command) for command in commands)
    assert "mosquitto_sub" in command_text
    assert "mosquitto_pub" in command_text


def test_validate_oqs_mqtt_main_dispatches_to_validation_function(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    result = module.main([
        "validate-oqs-mqtt",
        "--host-config",
        str(host_config),
        "--remote-dir",
        "~/pqc-framework-02/experiment/mqtt-broker",
        "--oqs-port",
        "38884",
        "--dry-run",
    ])

    assert result == 0
    command_text = "\n".join(" ".join(command) for command in commands)
    assert "mosquitto_sub" in command_text
    assert "mosquitto_pub" in command_text


def test_oqs_certificate_provisioning_alias_synchronizes_stepca_profile(tmp_path, monkeypatch):
    module = _load_ctl_module()
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "broker_root", lambda: tmp_path)

    args = module.build_parser().parse_args([
        "provision-oqs-certs",
        "--dry-run",
    ])

    assert args.certificate_profile == "stepca-classical"
    assert args.func is module.sync_stepca_certs


def test_mqtt_oqs_tls_validation_requires_complete_server_authenticated_handshake(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args([
        "validate-oqs-tls",
        "--host-config",
        str(host_config),
        "--remote-dir",
        "~/pqc-framework-02/experiment/mqtt-broker",
        "--oqs-port",
        "28884",
        "--dry-run",
    ])
    module.validate_oqs_tls(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "eclipse-mosquitto:2.1.2-alpine" in command_text
    assert "--network host" in command_text
    assert "-connect 127.0.0.1:28884" in command_text
    assert "-groups SecP256r1MLKEM768" in command_text
    assert "-CAfile /certs/ca.crt" in command_text
    assert "-cert /certs/client.crt" not in command_text
    assert "-key /certs/client.key" not in command_text
    assert "-verify_return_error" in command_text
    assert "New, TLSv1.3" in command_text
    assert "Certificate chain" in command_text
    assert "no peer certificate available" in command_text
    assert "Cipher is (NONE)" in command_text
    assert "Verify return code: 0 (ok)" in command_text


def test_mqtt_classical_mqtt_validation_uses_separate_pubsub_client_containers(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args([
        "validate-classical-mqtt",
        "--host-config",
        str(host_config),
        "--remote-dir",
        "~/pqc-framework-02/experiment/mqtt-broker",
        "--project-name",
        "pytest-mqtt",
        "--classical-port",
        "28883",
        "--topic",
        "pqc/test/e2e",
        "--message",
        "hello-classical",
        "--dry-run",
    ])
    module.validate_classical_mqtt(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "timk@pqc-gateway1" in command_text
    assert "eclipse-mosquitto:2.1.2-alpine" in command_text
    assert "openquantumsafe/mosquitto" not in command_text
    assert "--entrypoint mosquitto_sub" in command_text
    assert "--entrypoint mosquitto_pub" in command_text
    assert "--network host" in command_text
    assert "-p 28883" in command_text
    assert "$HOME/pqc-framework-02/secrets/mqtt/stepca-classical" in command_text
    assert "runtime/classical/certs" not in command_text
    assert "--cafile /certs/ca.crt" in command_text
    assert "--cert /certs/client.crt" in command_text
    assert "--key /certs/client.key" in command_text
    assert "--tls-version tlsv1.3" in command_text
    assert '-t "$topic" -C 1' in command_text
    assert '-t "$topic" -m "$message"' in command_text
    assert 'grep -Fx -- "$message"' in command_text
    assert "Evidence class: host_side" in command_text
    assert "host-side/broker-side MQTT/TLS compatibility evidence" in command_text
    assert "does not claim STM32" in command_text
    assert "Wi-Fi module" in command_text
    assert "wolfMQTT-on-STM32" in command_text


def test_mqtt_oqs_mqtt_validation_uses_separate_pubsub_client_containers(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args([
        "validate-oqs-mqtt",
        "--host-config",
        str(host_config),
        "--remote-dir",
        "~/pqc-framework-02/experiment/mqtt-broker",
        "--project-name",
        "pytest-mqtt",
        "--oqs-port",
        "38884",
        "--topic",
        "pqc/test/e2e",
        "--message",
        "hello-oqs",
        "--dry-run",
    ])
    module.validate_oqs_mqtt(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "timk@pqc-gateway1" in command_text
    assert "eclipse-mosquitto:2.1.2-alpine" in command_text
    assert "--entrypoint mosquitto_sub" in command_text
    assert "--entrypoint mosquitto_pub" in command_text
    assert "--network host" in command_text
    assert "-p 38884" in command_text
    assert "--cafile /certs/ca.crt" in command_text
    assert "--cert /certs/client.crt" not in command_text
    assert "--key /certs/client.key" not in command_text
    assert "--tls-version tlsv1.3" in command_text
    assert "-h localhost" in command_text
    assert "-e OPENSSL_CONF=/mosquitto/config/openssl.cnf" in command_text
    assert "OPENSSL_MODULES" not in command_text
    assert "$HOME/pqc-framework-02/experiment/mqtt-broker/config/oqs/openssl.cnf:/mosquitto/config/openssl.cnf:ro" in command_text
    assert '-t "$topic" -C 1' in command_text
    assert '-t "$topic" -m "$message"' in command_text
    assert 'grep -Fx -- "$message"' in command_text


def test_mqtt_oqs_tls_validation_labels_host_and_broker_side_evidence(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args([
        "validate-oqs-tls",
        "--host-config",
        str(host_config),
        "--remote-dir",
        "~/pqc-framework-02/experiment/mqtt-broker",
        "--oqs-port",
        "28884",
        "--dry-run",
    ])
    module.validate_oqs_tls(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "Evidence class: host_side" in command_text
    assert "host-side/broker-side MQTT/TLS compatibility evidence" in command_text
    assert "does not claim STM32" in command_text
    assert "Wi-Fi module" in command_text
    assert "lwIP-on-STM32" in command_text
    assert "wolfSSL-on-STM32" in command_text
    assert "wolfMQTT-on-STM32" in command_text
    assert "end-to-end wireless success" in command_text


def test_classical_server_auth_mqtt_validation_omits_client_identity(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    commands = []
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))
    args = module.build_parser().parse_args([
        "validate-classical-server-auth-mqtt",
        "--host-config", str(host_config),
        "--remote-dir", "~/pqc-framework-02/experiment/mqtt-broker",
        "--classical-port", "28883",
        "--dry-run",
    ])
    module.validate_classical_server_auth_mqtt(args)
    command_text = "\n".join(" ".join(command) for command in commands)
    assert "Evidence profile: classical-server-auth" in command_text
    assert "--cafile /certs/ca.crt" in command_text
    assert "--cert /certs/client.crt" not in command_text
    assert "--key /certs/client.key" not in command_text
    assert "--tls-version tlsv1.3" in command_text


def test_classical_mtls_acl_matches_stepca_client_common_name():
    acl = _read(BROKER_ROOT / "config" / "classical" / "aclfile")
    assert "user stm32-mqtt-client" in acl
    assert "user pqc-mqtt-client" not in acl
    assert "topic readwrite pqc/#" in acl


def test_mqtt_validator_reports_subscriber_failure_without_blank_polling():
    source = _read(BROKER_ROOT / "scripts" / "mqtt_broker_ctl.py")
    normalized_source = source.replace('\\"', '"')

    assert "subscriber failed before publish" in normalized_source
    assert "subscriber exited before receiving expected message" in normalized_source
    assert "expected MQTT payload was not received" in normalized_source
    assert 'logs=$(docker logs "$subscriber" 2>&1 || true)' in normalized_source
    assert 'grep -Fx -- "$message"' in normalized_source


def test_all_mosquitto_profiles_enable_packet_level_experiment_logging():
    profiles = (
        "classical",
        "classical-server-auth",
        "oqs",
        "oqs-mtls",
    )
    for profile in profiles:
        config = Path(f"experiment/mqtt-broker/config/{profile}/mosquitto.conf").read_text(encoding="utf-8")
        assert "log_type all" in config
        assert "connection_messages true" in config
        assert "log_timestamp true" in config
        assert "log_timestamp_format %Y-%m-%dT%H:%M:%S" in config


def test_all_broker_profiles_use_pinned_mosquitto_212_image_and_tls_keylog():
    compose = _read(BROKER_ROOT / "compose.yaml")
    assert "openquantumsafe/mosquitto" not in compose
    assert "eclipse-mosquitto:latest" not in compose
    assert compose.count("image: eclipse-mosquitto:2.1.2-alpine") == 4
    assert compose.count("--tls-keylog /mosquitto/keylog/mqtt-broker-tls-keylog.log") == 4
    assert compose.count("chmod 0700 /mosquitto/keylog") == 4
    assert compose.count("umask 077") == 4
    assert "./runtime/tls-keylog/" not in compose


def test_native_openssl_hybrid_profiles_do_not_load_oqsprovider():
    for profile in ("oqs", "oqs-mtls"):
        config = _read(BROKER_ROOT / "config" / profile / "openssl.cnf")
        assert "Groups = SecP256r1MLKEM768" in config
        assert "oqsprovider" not in config
