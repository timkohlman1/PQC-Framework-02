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
    cert_dir = REPO_ROOT / "secrets" / "certificates" / "rsa3072"
    required = ("ca.crt", "ca-chain.crt", "server.crt", "server.key", "client.crt", "client.key")
    missing = [name for name in required if not (cert_dir / name).is_file()]
    if missing:
        pytest.skip("pre-provisioned RSA-3072 MQTT material is unavailable: " + ", ".join(missing))
    return cert_dir


def _fresh_tls13_handshake(
    host: str,
    port: int,
    cert_dir: Path,
    *,
    server_name: str,
) -> tuple[str, bool]:
    context = ssl.create_default_context(cafile=str(cert_dir / "ca.crt"))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(
        certfile=str(cert_dir / "client.crt"),
        keyfile=str(cert_dir / "client.key"),
    )

    with socket.create_connection((host, port), timeout=5) as raw_sock:
        with context.wrap_socket(raw_sock, server_hostname=server_name) as tls_sock:
            version = tls_sock.version()
            assert version is not None
            return version, bool(tls_sock.session_reused)


def _assert_success(completed: subprocess.CompletedProcess[str], label: str) -> None:
    assert completed.returncode == 0, (
        f"{label} failed with exit code {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )


@pytest.mark.integration
def test_broker_accepts_multiple_independent_full_tls13_connections(
    tmp_path: Path,
    pqc_require_capabilities,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pqc_require_capabilities("gateway", strict_mode="gateway")

    module = _load_ctl_module()
    host = module.load_host_config(REPO_ROOT / module.DEFAULT_GATEWAY_CONFIG)
    if not host.address:
        pytest.skip("gateway configuration is missing network.address for external TLS validation")

    target = module.ssh_target(host)
    docker_probe = _ssh(
        target,
        "docker info >/dev/null 2>&1 && docker compose version >/dev/null 2>&1",
    )
    if docker_probe.returncode != 0:
        pytest.skip(f"Docker/Compose unavailable on gateway: {docker_probe.stderr or docker_probe.stdout}")

    cert_dir = _require_staged_stepca_material()

    suffix = uuid.uuid4().hex[:10]
    remote_root = f"/tmp/pqc-framework-pytest-tls-repeat-{suffix}"
    remote_dir = f"{remote_root}/experiment/mqtt-broker"
    project_name = f"pqc-tls-repeat-{suffix}"
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
        deploy_args = module.build_parser().parse_args([
            "deploy",
            "--remote-dir",
            remote_dir,
            "--project-name",
            project_name,
        ])
        module.deploy(deploy_args)

        start_args = module.build_parser().parse_args([
            "start",
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
                version, reused = _fresh_tls13_handshake(
                    host.address,
                    port,
                    cert_dir,
                    server_name="localhost",
                )
                assert version == "TLSv1.3"
                assert reused is False
                break
            except (OSError, ssl.SSLError, AssertionError) as exc:
                last_error = exc
                time.sleep(1)
        else:
            logs = _ssh(
                target,
                f"cd {_remote_shell_path(remote_dir)} && "
                f"docker compose --project-name {project_name} logs --tail 100 mqtt-classical",
                timeout_seconds=30,
            )
            raise AssertionError(
                f"TLS endpoint {host.address}:{port} did not become ready: {last_error}\n"
                f"broker logs:\n{logs.stdout}\n{logs.stderr}"
            )

        outcomes: list[tuple[str, bool]] = []
        for _iteration in range(3):
            outcomes.append(
                _fresh_tls13_handshake(
                    host.address,
                    port,
                    cert_dir,
                    server_name="localhost",
                )
            )

        assert len(outcomes) == 3
        assert all(version == "TLSv1.3" for version, _reused in outcomes)
        assert all(reused is False for _version, reused in outcomes)

        status = _ssh(
            target,
            f"cd {_remote_shell_path(remote_dir)} && docker compose "
            f"--project-name {project_name} ps",
            timeout_seconds=30,
        )
        _assert_success(status, "docker compose ps")
        assert "mqtt-classical" in status.stdout
        assert "healthy" in status.stdout.lower() or "up" in status.stdout.lower()
    finally:
        stop = _ssh(
            target,
            f"cd {_remote_shell_path(remote_dir)} && docker compose "
            f"--project-name {project_name} --profile classical --profile oqs "
            f"down --remove-orphans",
            timeout_seconds=60,
        )
        if stop.returncode != 0:
            cleanup_errors.append(f"compose down failed: {stop.stderr or stop.stdout}")

        rm = _ssh(
            target,
            module.remote_cleanup_command(remote_root),
            timeout_seconds=60,
        )
        if rm.returncode != 0:
            cleanup_errors.append(f"remote rm failed: {rm.stderr or rm.stdout}")

    assert not cleanup_errors
