from __future__ import annotations

import importlib.util
import shutil
import socket
import ssl
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BROKER_ROOT = REPO_ROOT / "experiment" / "mqtt-broker"
SCRIPT_PATH = BROKER_ROOT / "scripts" / "mqtt_broker_ctl.py"
HOST_CONFIG = REPO_ROOT / "configs" / "hosts" / "gateway.yaml"


def _load_ctl_module():
    spec = importlib.util.spec_from_file_location("mqtt_broker_ctl", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(args: list[str], *, timeout_seconds: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )


def _ssh(target: str, command: str, *, timeout_seconds: int = 30) -> subprocess.CompletedProcess[str]:
    return _run(["ssh", target, command], timeout_seconds=timeout_seconds)


def _remote_shell_path(path: str) -> str:
    if path == "~":
        return "$HOME"
    if path.startswith("~/"):
        return "$HOME/" + path[2:]
    return path


def _copy_broker_project(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        ignored = {"__pycache__", ".pytest_cache", "runtime", "data", "log", ".env"}
        return {name for name in names if name in ignored or name.endswith(".pyc")}

    shutil.copytree(source, destination, ignore=ignore)



def _require_staged_stepca_material() -> Path:
    cert_dir = REPO_ROOT / "secrets" / "mqtt" / "stepca-classical"
    required = ("ca.crt", "ca-chain.crt", "server.crt", "server.key", "client.crt", "client.key")
    missing = [name for name in required if not (cert_dir / name).is_file()]
    if missing:
        pytest.skip("staged step-ca MQTT material is unavailable: " + ", ".join(missing))
    return cert_dir


def _assert_success(completed: subprocess.CompletedProcess[str], label: str) -> None:
    assert completed.returncode == 0, (
        f"{label} failed with exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def _tls_handshake(
    host: str,
    port: int,
    cert_dir: Path,
    *,
    server_name: str,
) -> tuple[str, tuple[str, str, int]]:
    context = ssl.create_default_context(cafile=str(cert_dir / "ca.crt"))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(certfile=str(cert_dir / "client.crt"), keyfile=str(cert_dir / "client.key"))

    with socket.create_connection((host, port), timeout=10) as raw_sock:
        with context.wrap_socket(raw_sock, server_hostname=server_name) as tls_sock:
            assert tls_sock.version() == "TLSv1.3"
            cipher = tls_sock.cipher()
            assert cipher is not None
            return tls_sock.version(), cipher


@pytest.mark.integration
def test_mqtt_broker_gateway_temp_deploy_start_tls_stop_cleanup(tmp_path, pqc_require_capabilities, monkeypatch):
    pqc_require_capabilities("gateway", strict_mode="gateway")

    module = _load_ctl_module()
    host = module.load_host_config(HOST_CONFIG)
    if not host.address:
        pytest.skip("configs/hosts/gateway.yaml is missing network.address for external TLS validation")

    target = module.ssh_target(host)
    docker_probe = _ssh(target, "docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1")
    if docker_probe.returncode != 0:
        pytest.skip(f"Docker/Compose unavailable on gateway: {docker_probe.stderr or docker_probe.stdout}")

    suffix = uuid.uuid4().hex[:10]
    remote_root = f"~/pqc-framework-02/tmp/pytest-mqtt-broker-{suffix}"
    remote_dir = f"{remote_root}/experiment/mqtt-broker"
    project_name = f"pqc-mqtt-pytest-{suffix}"
    port = 28000 + (int(suffix[:4], 16) % 10000)
    local_broker = tmp_path / "mqtt-broker"
    _copy_broker_project(BROKER_ROOT, local_broker)
    classical_config = local_broker / "config" / "classical" / "mosquitto.conf"
    classical_config.write_text(
        "\n".join(
            line
            for line in classical_config.read_text(encoding="utf-8").splitlines()
            if line.strip() != "log_dest file /mosquitto/log/mosquitto.log"
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "broker_root", lambda: local_broker)

    cleanup_errors: list[str] = []
    try:
        cert_dir = _require_staged_stepca_material()

        deploy_args = module.build_parser().parse_args([
            "deploy",
            "--host-config",
            str(HOST_CONFIG),
            "--remote-dir",
            remote_dir,
            "--project-name",
            project_name,
        ])
        module.deploy(deploy_args)

        start_args = module.build_parser().parse_args([
            "start",
            "--host-config",
            str(HOST_CONFIG),
            "--remote-dir",
            remote_dir,
            "--project-name",
            project_name,
            "--profile",
            "classical",
            "--classical-port",
            str(port),
        ])
        module.start(start_args)

        last_error: Exception | None = None
        for _attempt in range(30):
            try:
                tls_version, cipher = _tls_handshake(host.address, port, cert_dir, server_name="localhost")
                assert tls_version == "TLSv1.3"
                assert cipher[0].startswith("TLS_")
                break
            except (OSError, ssl.SSLError, AssertionError) as exc:
                last_error = exc
                time.sleep(1)
        else:
            logs = _ssh(
                target,
                f"cd {_remote_shell_path(remote_dir)} && docker compose --project-name {project_name} logs --tail 100 mqtt-classical",
                timeout_seconds=30,
            )
            raise AssertionError(
                f"TLS handshake to {host.address}:{port} did not succeed: {last_error}\n"
                f"broker logs:\n{logs.stdout}\n{logs.stderr}"
            )

        message = f"pqc-classical-pubsub-{suffix}"
        mqtt_args = module.build_parser().parse_args([
            "validate-classical-mqtt",
            "--host-config",
            str(HOST_CONFIG),
            "--remote-dir",
            remote_dir,
            "--project-name",
            project_name,
            "--classical-port",
            str(port),
            "--topic",
            f"pqc/test/e2e/classical/{suffix}",
            "--message",
            message,
        ])
        module.validate_classical_mqtt(mqtt_args)

        status = _ssh(
            target,
            f"cd {_remote_shell_path(remote_dir)} && docker compose --project-name {project_name} ps",
            timeout_seconds=30,
        )
        _assert_success(status, "docker compose ps")
        assert "mqtt-classical" in status.stdout
        assert "healthy" in status.stdout.lower() or "up" in status.stdout.lower()
    finally:
        stop = _ssh(
            target,
            f"cd {_remote_shell_path(remote_dir)} && docker compose --project-name {project_name} --profile classical --profile oqs down --remove-orphans",
            timeout_seconds=60,
        )
        if stop.returncode != 0:
            cleanup_errors.append(f"compose down failed: {stop.stderr or stop.stdout}")
        rm = _ssh(target, module.remote_cleanup_command(remote_root), timeout_seconds=60)
        if rm.returncode != 0:
            cleanup_errors.append(f"remote rm failed: {rm.stderr or rm.stdout}")

    assert not cleanup_errors


@pytest.mark.integration
def test_mqtt_broker_gateway_oqs_temp_deploy_start_server_auth_tls_stop_cleanup(tmp_path, pqc_require_capabilities, monkeypatch):
    pqc_require_capabilities("gateway", strict_mode="gateway")

    module = _load_ctl_module()
    host = module.load_host_config(HOST_CONFIG)
    target = module.ssh_target(host)
    docker_probe = _ssh(target, "docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1")
    if docker_probe.returncode != 0:
        pytest.skip(f"Docker/Compose unavailable on gateway: {docker_probe.stderr or docker_probe.stdout}")

    suffix = uuid.uuid4().hex[:10]
    remote_root = f"~/pqc-framework-02/tmp/pytest-mqtt-broker-oqs-{suffix}"
    remote_dir = f"{remote_root}/experiment/mqtt-broker"
    project_name = f"pqc-mqtt-oqs-pytest-{suffix}"
    port = 38000 + (int(suffix[:4], 16) % 10000)
    local_broker = tmp_path / "mqtt-broker"
    _copy_broker_project(BROKER_ROOT, local_broker)

    monkeypatch.setattr(module, "broker_root", lambda: local_broker)

    cleanup_errors: list[str] = []
    try:
        deploy_args = module.build_parser().parse_args([
            "deploy",
            "--host-config",
            str(HOST_CONFIG),
            "--remote-dir",
            remote_dir,
            "--project-name",
            project_name,
        ])
        module.deploy(deploy_args)

        _require_staged_stepca_material()

        start_args = module.build_parser().parse_args([
            "start",
            "--host-config",
            str(HOST_CONFIG),
            "--remote-dir",
            remote_dir,
            "--project-name",
            project_name,
            "--profile",
            "oqs",
            "--oqs-port",
            str(port),
        ])
        module.start(start_args)

        last_error: BaseException | None = None
        for _attempt in range(30):
            try:
                validate_args = module.build_parser().parse_args([
                    "validate-oqs-tls",
                    "--host-config",
                    str(HOST_CONFIG),
                    "--remote-dir",
                    remote_dir,
                    "--project-name",
                    project_name,
                    "--oqs-port",
                    str(port),
                ])
                module.validate_oqs_tls(validate_args)
                break
            except (SystemExit, AssertionError, OSError) as exc:
                last_error = exc
                time.sleep(1)
        else:
            logs = _ssh(
                target,
                f"cd {_remote_shell_path(remote_dir)} && docker compose --project-name {project_name} logs --tail 100 mqtt-oqs",
                timeout_seconds=30,
            )
            raise AssertionError(
                f"OQS server-authenticated TLS validation on 127.0.0.1:{port} did not succeed: {last_error}\n"
                f"broker logs:\n{logs.stdout}\n{logs.stderr}"
            )

        message = f"pqc-oqs-pubsub-{suffix}"
        mqtt_args = module.build_parser().parse_args([
            "validate-oqs-mqtt",
            "--host-config",
            str(HOST_CONFIG),
            "--remote-dir",
            remote_dir,
            "--project-name",
            project_name,
            "--oqs-port",
            str(port),
            "--topic",
            f"pqc/test/e2e/{suffix}",
            "--message",
            message,
        ])
        module.validate_oqs_mqtt(mqtt_args)

        status = _ssh(
            target,
            f"cd {_remote_shell_path(remote_dir)} && docker compose --project-name {project_name} ps",
            timeout_seconds=30,
        )
        _assert_success(status, "docker compose ps")
        assert "mqtt-oqs" in status.stdout
        assert "healthy" in status.stdout.lower() or "up" in status.stdout.lower()
    finally:
        stop = _ssh(
            target,
            f"cd {_remote_shell_path(remote_dir)} && docker compose --project-name {project_name} --profile classical --profile oqs down --remove-orphans",
            timeout_seconds=60,
        )
        if stop.returncode != 0:
            cleanup_errors.append(f"compose down failed: {stop.stderr or stop.stdout}")
        rm = _ssh(target, module.remote_cleanup_command(remote_root), timeout_seconds=60)
        if rm.returncode != 0:
            cleanup_errors.append(f"remote rm failed: {rm.stderr or rm.stdout}")

    assert not cleanup_errors
