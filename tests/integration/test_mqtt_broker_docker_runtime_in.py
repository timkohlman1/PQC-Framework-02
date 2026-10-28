from __future__ import annotations

import importlib.util
import os
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


def _run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _assert_success(completed: subprocess.CompletedProcess[str], label: str) -> None:
    assert completed.returncode == 0, (
        f"{label} failed with exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


def _require_docker_runtime() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker command is not available")

    compose = _run(["docker", "compose", "version"], cwd=REPO_ROOT, timeout=30)
    if compose.returncode != 0:
        detail = (compose.stderr or compose.stdout or "").strip()
        pytest.skip(f"docker compose is not available: {detail}")

    info = _run(["docker", "info"], cwd=REPO_ROOT, timeout=30)
    if info.returncode != 0:
        detail = (info.stderr or info.stdout or "").strip()
        pytest.skip(f"docker daemon is not available: {detail}")


@pytest.fixture(scope="session")
def _docker_runtime_available() -> None:
    _require_docker_runtime()


def _load_ctl_module():
    spec = importlib.util.spec_from_file_location("mqtt_broker_ctl", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy_broker_project(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        ignored = {"__pycache__", ".pytest_cache", "runtime", "data", "log", ".env"}
        return {name for name in names if name in ignored or name.endswith(".pyc")}

    shutil.copytree(source, destination, ignore=ignore)




def _require_staged_stepca_material() -> Path:
    cert_dir = REPO_ROOT / "secrets" / "certificates" / "rsa3072"
    required = ("ca.crt", "ca-chain.crt", "server.crt", "server.key", "client.crt", "client.key")
    missing = [name for name in required if not (cert_dir / name).is_file()]
    if missing:
        pytest.skip("pre-provisioned RSA-3072 MQTT material is unavailable: " + ", ".join(missing))
    return cert_dir


def _copy_staged_material(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.is_file():
            shutil.copy2(path, destination / path.name)


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def classical_broker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _docker_runtime_available: None):
    if shutil.which("openssl") is None:
        pytest.skip("openssl command is not available")

    source_cert_dir = _require_staged_stepca_material()
    workspace_root = tmp_path / "workspace"
    broker_root = workspace_root / "experiment" / "mqtt-broker"
    cert_dir = workspace_root / "secrets" / "certificates" / "rsa3072"
    broker_root.parent.mkdir(parents=True, exist_ok=True)
    _copy_broker_project(BROKER_ROOT, broker_root)
    _copy_staged_material(source_cert_dir, cert_dir)

    project_name = f"pqc-mqtt-runtime-{uuid.uuid4().hex[:10]}"
    host_port = _free_local_port()
    port_env = {
        "MQTT_CLASSICAL_TLS_PORT": str(host_port),
        "MQTT_CERTIFICATE_PROFILE": "rsa3072",
    }
    env = {**os.environ, **port_env}

    up = _run(
        ["docker", "compose", "--project-name", project_name, "--profile", "classical", "up", "-d", "mqtt-classical"],
        cwd=broker_root,
        env=env,
        timeout=180,
    )
    _assert_success(up, "docker compose up mqtt-classical")

    try:
        yield broker_root, project_name, host_port, env
    finally:
        down = _run(
            ["docker", "compose", "--project-name", project_name, "--profile", "classical", "down", "--volumes", "--remove-orphans"],
            cwd=broker_root,
            env=env,
            timeout=120,
        )
        assert down.returncode == 0, (
            "docker compose down failed\n"
            f"stdout:\n{down.stdout}\n"
            f"stderr:\n{down.stderr}"
        )


def _tls_handshake(host_port: int, cert_dir: Path) -> tuple[str, tuple[str, str, int]]:
    context = ssl.create_default_context(cafile=str(cert_dir / "ca.crt"))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(certfile=str(cert_dir / "client.crt"), keyfile=str(cert_dir / "client.key"))

    with socket.create_connection(("127.0.0.1", host_port), timeout=5) as raw_sock:
        with context.wrap_socket(raw_sock, server_hostname="localhost") as tls_sock:
            version = tls_sock.version()
            cipher = tls_sock.cipher()
            assert version is not None
            assert cipher is not None
            return version, cipher


def _wait_for_tls(host_port: int, cert_dir: Path, broker_root: Path, project_name: str, env: dict[str, str]) -> None:
    last_error: Exception | None = None
    for _attempt in range(40):
        try:
            version, cipher = _tls_handshake(host_port, cert_dir)
            assert version == "TLSv1.3"
            assert cipher[0].startswith("TLS_")
            return
        except (OSError, ssl.SSLError, AssertionError) as exc:
            last_error = exc
            time.sleep(1)

    logs = _run(
        ["docker", "compose", "--project-name", project_name, "logs", "--tail", "120", "mqtt-classical"],
        cwd=broker_root,
        env=env,
        timeout=30,
    )
    raise AssertionError(
        f"classical MQTT broker TLS endpoint did not become ready: {last_error}\n"
        f"broker logs stdout:\n{logs.stdout}\n"
        f"broker logs stderr:\n{logs.stderr}"
    )


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.docker_runtime
def test_mqtt_classical_container_starts_and_accepts_mutual_tls(classical_broker):
    broker_root, project_name, host_port, env = classical_broker
    cert_dir = broker_root.parents[1] / "secrets" / "certificates" / "rsa3072"

    _wait_for_tls(host_port, cert_dir, broker_root, project_name, env)

    ps = _run(
        ["docker", "compose", "--project-name", project_name, "ps", "mqtt-classical"],
        cwd=broker_root,
        env=env,
        timeout=30,
    )
    _assert_success(ps, "docker compose ps mqtt-classical")
    assert "mqtt-classical" in ps.stdout


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.docker_runtime
def test_mqtt_classical_container_supports_client_certificate_pubsub(classical_broker):
    broker_root, project_name, host_port, env = classical_broker
    cert_dir = broker_root.parents[1] / "secrets" / "certificates" / "rsa3072"
    _wait_for_tls(host_port, cert_dir, broker_root, project_name, env)

    suffix = uuid.uuid4().hex[:10]
    topic = f"pqc/ci/runtime/{suffix}"
    message = f"pqc-mqtt-runtime-{suffix}"
    common_args = [
        "-h",
        "127.0.0.1",
        "-p",
        "8883",
        "--cafile",
        "/mosquitto/config/certs/ca.crt",
        "--cert",
        "/mosquitto/config/certs/client.crt",
        "--key",
        "/mosquitto/config/certs/client.key",
        "--tls-version",
        "tlsv1.3",
    ]

    subscriber = subprocess.Popen(
        [
            "docker",
            "compose",
            "--project-name",
            project_name,
            "exec",
            "-T",
            "mqtt-classical",
            "mosquitto_sub",
            *common_args,
            "-t",
            topic,
            "-C",
            "1",
            "-W",
            "20",
        ],
        cwd=broker_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(2)
        publish = _run(
            [
                "docker",
                "compose",
                "--project-name",
                project_name,
                "exec",
                "-T",
                "mqtt-classical",
                "mosquitto_pub",
                *common_args,
                "-t",
                topic,
                "-m",
                message,
            ],
            cwd=broker_root,
            env=env,
            timeout=30,
        )
        _assert_success(publish, "mosquitto_pub client container command")

        stdout, stderr = subscriber.communicate(timeout=30)
        assert subscriber.returncode == 0, (
            "mosquitto_sub client container command failed\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )
        assert message in stdout.splitlines()
    finally:
        if subscriber.poll() is None:
            subscriber.terminate()
            try:
                subscriber.wait(timeout=5)
            except subprocess.TimeoutExpired:
                subscriber.kill()


@pytest.mark.integration
@pytest.mark.docker
@pytest.mark.docker_runtime
def test_tcp_nodelay_recreates_broker_and_retains_generated_config(classical_broker):
    """Real Compose reconciliation, loaded config and mTLS readiness in both arms."""
    broker_root, project_name, host_port, env = classical_broker
    cert_dir = broker_root.parents[1] / 'secrets/certificates/rsa3072'
    base = ['docker', 'compose', '--project-name', project_name]
    ids = []
    original = (broker_root/'config/classical/mosquitto.conf').read_bytes()
    for value in ('false', 'true', 'false'):
        selected = {**env, 'MQTT_TCP_NODELAY': value}
        result = _run(base + ['--profile','classical','up','-d','--wait','mqtt-classical'],
                      cwd=broker_root, env=selected, timeout=180)
        _assert_success(result, 'reconfigure broker')
        _wait_for_tls(host_port, cert_dir, broker_root, project_name, selected)
        ids.append(_run(base+['ps','-q','mqtt-classical'],cwd=broker_root,env=selected,timeout=30).stdout.strip())
        result = _run(base+['exec','-T','mqtt-classical','sh','-ec',
            'grep -q /tmp/mosquitto-runtime.conf /proc/1/cmdline && cat /tmp/mosquitto-runtime.conf'],
            cwd=broker_root,env=selected,timeout=30)
        _assert_success(result,'read loaded config')
        assert result.stdout.encode() == f'set_tcp_nodelay {value}\n'.encode() + original
        assert (broker_root/'config/classical/mosquitto.conf').read_bytes() == original
    assert len(set(ids)) == 3
