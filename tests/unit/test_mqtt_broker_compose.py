from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = REPO_ROOT / "experiment" / "mqtt-broker"
SCRIPT_PATH = BROKER_ROOT / "scripts" / "mqtt_broker_ctl.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    assert "eclipse-mosquitto:2.0" in compose
    assert "openquantumsafe/mosquitto" in compose
    assert "${MQTT_CLASSICAL_TLS_PORT:-8883}:8883" in compose
    assert "${MQTT_OQS_TLS_PORT:-8884}:8883" in compose


def test_mqtt_broker_compose_copies_acl_files_to_container_local_paths():
    compose = _read(BROKER_ROOT / "compose.yaml")

    assert "user: \"0:0\"" in compose
    assert "entrypoint:" in compose
    assert "- /bin/sh" in compose
    assert "- -ec" in compose
    assert "command: |" not in compose
    assert "aclfile.source" in compose
    assert "cp /mosquitto/config/aclfile.source /tmp/mosquitto-aclfile" in compose
    assert "if id mosquitto >/dev/null 2>&1; then" in compose
    assert 'chown "$(id -u mosquitto):$(id -g mosquitto)" /tmp/mosquitto-aclfile' in compose
    assert "elif id nobody >/dev/null 2>&1; then" in compose
    assert 'chown "$(id -u nobody):$(id -g nobody)" /tmp/mosquitto-aclfile' in compose
    assert "chown 0:0 /tmp/mosquitto-aclfile" in compose
    assert "chmod 0640 /tmp/mosquitto-aclfile" in compose
    assert "chmod 0644 /tmp/mosquitto-aclfile" in compose
    assert "exec mosquitto -c /mosquitto/config/mosquitto.conf" in compose


def test_mqtt_broker_compose_avoids_fixed_container_and_network_names():
    compose = _read(BROKER_ROOT / "compose.yaml")

    assert "container_name:" not in compose
    assert "name: pqc-framework-mqtt-broker" not in compose
    assert "name: pqc-framework-mqtt-broker" not in compose


def test_classical_mosquitto_config_enforces_tls_and_client_certificates():
    config = _read(BROKER_ROOT / "config" / "classical" / "mosquitto.conf")

    assert "listener 8883 0.0.0.0" in config
    assert "tls_version tlsv1.3" in config
    assert "allow_anonymous true" in config
    assert "require_certificate true" in config
    assert "use_identity_as_username true" in config
    assert "cafile /mosquitto/config/certs/ca.crt" in config
    assert "certfile /mosquitto/config/certs/server.crt" in config
    assert "keyfile /mosquitto/config/certs/server.key" in config


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
    (broker_root / "runtime" / "classical").mkdir(parents=True)
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "broker_root", lambda: broker_root)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args(["deploy", "--host-config", str(host_config), "--dry-run"])
    module.deploy(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "__pycache__" not in command_text
    assert "mqtt_broker_ctl.cpython" not in command_text
    assert any(command[0] == "scp" and command[1].endswith("mqtt_broker_ctl.py") for command in commands)
    assert any(command[0:2] == ["scp", "-r"] and command[2].replace("\\", "/").endswith("runtime/classical") for command in commands)


def test_mqtt_deploy_sets_remote_config_and_classical_runtime_read_permissions(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    broker_root = tmp_path / "experiment" / "mqtt-broker"
    (broker_root / "runtime" / "classical").mkdir(parents=True)
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
    assert "$HOME/pqc-framework-02/experiment/mqtt-broker/runtime/classical" in permission_commands[-1][-1]
    assert "$HOME/pqc-framework-02/experiment/mqtt-broker/runtime/oqs" not in permission_commands[-1][-1]


def test_mqtt_deploy_does_not_chmod_remote_oqs_runtime(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text("id: gateway\nalias: pqc-gateway1\nuser: timk\n", encoding="utf-8")
    broker_root = tmp_path / "experiment" / "mqtt-broker"
    (broker_root / "runtime" / "classical").mkdir(parents=True)
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "broker_root", lambda: broker_root)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args(["deploy", "--host-config", str(host_config), "--dry-run"])
    module.deploy(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "runtime/classical" in command_text
    assert "chmod -R a+rX $HOME/pqc-framework-02/experiment/mqtt-broker/config $HOME/pqc-framework-02/experiment/mqtt-broker/runtime/classical" in command_text
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
        "--profile classical --profile classical-server-auth --profile oqs "
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


def test_mqtt_cert_provisioning_uses_explicit_openssl_configs_and_host_ip_san(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text(
        "id: gateway\nalias: pqc-gateway1\nuser: timk\nnetwork:\n  address: 10.1.1.18\n",
        encoding="utf-8",
    )
    commands = []

    monkeypatch.setattr(module, "ensure_openssl", lambda: None)
    monkeypatch.setattr(module, "broker_root", lambda: tmp_path)
    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))

    args = module.build_parser().parse_args([
        "provision-certs",
        "--server-name",
        "pqc-gateway1",
        "--host-config",
        str(host_config),
    ])
    module.provision_classical_certs(args)

    flat_commands = [" ".join(command) for command in commands]
    req_commands = [command for command in flat_commands if command.startswith("openssl req ")]
    server_conf = tmp_path / "runtime" / "classical" / "certs" / "server-openssl.cnf"
    server_conf_text = server_conf.read_text(encoding="utf-8")

    assert req_commands
    assert all(" -config " in command for command in req_commands)
    assert any("ca-openssl.cnf" in command for command in req_commands)
    assert any("client-openssl.cnf" in command for command in req_commands)
    assert any("healthcheck-openssl.cnf" in command for command in req_commands)
    assert "DNS.1 = pqc-gateway1" in server_conf_text
    assert "IP.1 = 127.0.0.1" in server_conf_text
    assert "IP.2 = 10.1.1.18" in server_conf_text


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
        "~/pqc-framework-02/tmp/pytest-mqtt-broker-test",
        "--dry-run",
    ])
    module.start(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "cd $HOME/pqc-framework-02/tmp/pytest-mqtt-broker-test" in command_text
    assert "cd '~/" not in command_text


def test_mqtt_remote_cleanup_command_removes_root_owned_mosquitto_paths():
    module = _load_ctl_module()

    command = module.remote_cleanup_command("~/pqc-framework-02/tmp/pytest-mqtt-broker-test")

    assert "docker run --rm" in command
    assert "eclipse-mosquitto:2.0" in command
    assert "-v $HOME/pqc-framework-02/tmp/pytest-mqtt-broker-test:/work" in command
    assert "rm -rf /work/data /work/log" in command
    assert "rm -rf $HOME/pqc-framework-02/tmp/pytest-mqtt-broker-test" in command
    assert "'~/" not in command


def test_oqs_mosquitto_config_enforces_server_authenticated_tls_with_project_certs():
    config = _read(BROKER_ROOT / "config" / "oqs" / "mosquitto.conf")

    assert "listener 8883 0.0.0.0" in config
    assert "tls_version tlsv1.3" in config
    assert "allow_anonymous true" in config
    assert "require_certificate false" in config
    assert "use_identity_as_username false" in config
    assert "cafile /mosquitto/config/certs/ca.crt" in config
    assert "certfile /mosquitto/config/certs/server.crt" in config
    assert "keyfile /mosquitto/config/certs/server.key" in config
    assert "acl_file /tmp/mosquitto-aclfile" in config
    assert "user nobody" in config

def test_oqs_compose_uses_project_managed_hybrid_tls_config_and_strict_healthcheck():
    compose = _read(BROKER_ROOT / "compose.yaml")
    openssl_config = _read(BROKER_ROOT / "config" / "oqs" / "openssl.cnf")

    assert "./config/oqs/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" in compose
    assert "./config/oqs/openssl.cnf:/mosquitto/config/openssl.cnf:ro" in compose
    assert "./config/oqs/aclfile:/mosquitto/config/aclfile.source:ro" in compose
    assert "./runtime/oqs/certs:/mosquitto/config/certs:ro" in compose
    assert 'OPENSSL_CONF: "/mosquitto/config/openssl.cnf"' in compose
    assert "OPENSSL_MODULES" in compose
    assert "-groups SecP256r1MLKEM768" in compose
    assert "New, TLSv1.3" in compose
    assert "Certificate chain" in compose
    assert "Cipher is (NONE)" in compose
    assert "Verify return code: 0 (ok)" in compose
    assert "Groups = SecP256r1MLKEM768" in openssl_config
    assert "oqsprovider = oqsprovider_sect" in openssl_config

def test_mqtt_control_script_has_provision_and_validation_subcommands():
    module = _load_ctl_module()
    parser = module.build_parser()

    oqs = parser.parse_args(["provision-oqs-certs", "--dry-run"])
    validate = parser.parse_args(["validate-oqs-tls", "--dry-run"])
    classical_mqtt = parser.parse_args(["validate-classical-mqtt", "--dry-run"])
    oqs_mqtt = parser.parse_args(["validate-oqs-mqtt", "--dry-run"])

    assert oqs.command == "provision-oqs-certs"
    assert oqs.ca_algorithm == "mldsa65"
    assert oqs.leaf_algorithm == "mldsa65"
    assert validate.command == "validate-oqs-tls"
    assert validate.oqs_group == "SecP256r1MLKEM768"
    assert classical_mqtt.command == "validate-classical-mqtt"
    assert classical_mqtt.topic == "pqc/test/e2e"
    assert classical_mqtt.message == "pqc-classical-mqtt-e2e"
    assert classical_mqtt.image == "eclipse-mosquitto:2.0"
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
        "~/pqc-framework-02/tmp/pytest-mqtt-broker-test",
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
        "~/pqc-framework-02/tmp/pytest-mqtt-broker-test",
        "--oqs-port",
        "38884",
        "--dry-run",
    ])

    assert result == 0
    command_text = "\n".join(" ".join(command) for command in commands)
    assert "mosquitto_sub" in command_text
    assert "mosquitto_pub" in command_text


def test_mqtt_oqs_cert_provisioning_runs_on_gateway_with_oqs_provider_image(tmp_path, monkeypatch):
    module = _load_ctl_module()
    host_config = tmp_path / "gateway.yaml"
    host_config.write_text(
        "id: gateway\nalias: pqc-gateway1\nuser: timk\nnetwork:\n  address: 10.1.1.18\n",
        encoding="utf-8",
    )
    commands = []

    monkeypatch.setattr(module, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(module, "run_command", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(module, "run_command_with_input", lambda command, input_text, **kwargs: commands.append(command + [input_text]))

    args = module.build_parser().parse_args([
        "provision-oqs-certs",
        "--host-config",
        str(host_config),
        "--remote-dir",
        "~/pqc-framework-02/tmp/pytest-mqtt-broker-test",
        "--dry-run",
    ])
    module.provision_oqs_certs(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "timk@pqc-gateway1" in command_text
    assert "openquantumsafe/mosquitto:latest" in command_text
    assert "openssl genpkey -algorithm mldsa65 -out /certs/ca.key" in command_text
    assert "openssl genpkey -algorithm mldsa65 -out /certs/server.key" in command_text
    assert "openssl genpkey -algorithm mldsa65 -out /certs/client.key" in command_text
    assert "IP.2 = 10.1.1.18" in command_text
    assert "$HOME/pqc-framework-02/tmp/pytest-mqtt-broker-test/runtime/oqs/certs" in command_text
    assert "scp timk@pqc-gateway1:~/pqc-framework-02/tmp/pytest-mqtt-broker-test/runtime/oqs/certs/ca.crt" in command_text
    assert "experiment/mqtt-broker/runtime/oqs/certs/ca.crt" in command_text.replace("\\", "/")


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
        "~/pqc-framework-02/tmp/pytest-mqtt-broker-test",
        "--oqs-port",
        "28884",
        "--dry-run",
    ])
    module.validate_oqs_tls(args)

    command_text = "\n".join(" ".join(command) for command in commands)
    assert "openquantumsafe/mosquitto:latest" in command_text
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
        "~/pqc-framework-02/tmp/pytest-mqtt-broker-test",
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
    assert "eclipse-mosquitto:2.0" in command_text
    assert "openquantumsafe/mosquitto:latest" not in command_text
    assert "--entrypoint mosquitto_sub" in command_text
    assert "--entrypoint mosquitto_pub" in command_text
    assert "--network host" in command_text
    assert "-p 28883" in command_text
    assert "runtime/classical/certs" in command_text
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
        "~/pqc-framework-02/tmp/pytest-mqtt-broker-test",
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
    assert "openquantumsafe/mosquitto:latest" in command_text
    assert "--entrypoint mosquitto_sub" in command_text
    assert "--entrypoint mosquitto_pub" in command_text
    assert "--network host" in command_text
    assert "-p 38884" in command_text
    assert "--cafile /certs/ca.crt" in command_text
    assert "--cert /certs/client.crt" in command_text
    assert "--key /certs/client.key" in command_text
    assert "--tls-version tlsv1.3" in command_text
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
        "~/pqc-framework-02/tmp/pytest-mqtt-broker-test",
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
