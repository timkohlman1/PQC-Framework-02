#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

BROKER_RELATIVE_DIR = Path("experiment/mqtt-broker")
DEFAULT_HOST_CONFIG = Path("configs/hosts/gateway.yaml")
DEFAULT_REMOTE_DIR = "~/pqc-framework-02/experiment/mqtt-broker"
DEFAULT_PROJECT_NAME = "pqc-framework-mqtt-broker"
DEFAULT_SERVER_NAME = "pqc-gateway1"
DEFAULT_CLIENT_NAME = "pqc-mqtt-client"
DEFAULT_HEALTHCHECK_NAME = "pqc-mqtt-server-healthcheck"


@dataclass(frozen=True)
class HostConfig:
    alias: str
    user: str | None
    address: str | None = None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def broker_root() -> Path:
    return repo_root() / BROKER_RELATIVE_DIR


def load_simple_yaml(path: Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value:
            parent[key] = value
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
    return root


def _nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def load_host_config(path: Path) -> HostConfig:
    if not path.is_file():
        raise SystemExit(f"host config not found: {path}")
    data = load_simple_yaml(path)
    alias = data.get("alias")
    if not isinstance(alias, str) or not alias:
        raise SystemExit(f"host config is missing alias: {path}")
    user = data.get("user")
    address = _nested(data, "network", "address") or data.get("address")
    return HostConfig(
        alias=alias,
        user=user if isinstance(user, str) and user else None,
        address=address if isinstance(address, str) and address else None,
    )


def run_command(args: list[str], *, cwd: Path | None = None, dry_run: bool = False) -> None:
    display = " ".join(args)
    if dry_run:
        print(display)
        return
    completed = subprocess.run(args, cwd=cwd, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"command failed with exit code {completed.returncode}: {display}")


def ssh_target(host: HostConfig) -> str:
    if host.user:
        return f"{host.user}@{host.alias}"
    return host.alias


def tls_host(host: HostConfig) -> str:
    return host.address or host.alias


def remote_shell_path(path: str) -> str:
    """Return a shell-safe remote path while preserving leading ~/ expansion.

    shlex.quote("~/path") produces '"'~/path'"', which prevents tilde
    expansion on the remote shell. Use $HOME for user-home paths so compose
    commands can cd into temporary gateway directories reliably.
    """
    if path == "~":
        return "$HOME"
    if path.startswith("~/"):
        remainder = path[2:]
        return "$HOME/" + shlex.quote(remainder)
    return shlex.quote(path)


def ensure_openssl() -> None:
    if shutil.which("openssl") is None:
        raise SystemExit("openssl is required to provision local MQTT TLS material")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(repo_root()))
    except ValueError:
        return str(path)


def write_server_openssl_config(path: Path, server_names: Iterable[str], ip_addresses: Iterable[str]) -> None:
    alt_names = [name for name in dict.fromkeys(server_names) if name]
    ips = [ip for ip in dict.fromkeys(ip_addresses) if ip]
    dns_lines = [f"DNS.{index + 1} = {name}" for index, name in enumerate(alt_names)]
    ip_lines = [f"IP.{index + 1} = {ip}" for index, ip in enumerate(ips)]
    path.write_text(
        "\n".join(
            [
                "[req]",
                "default_bits = 256",
                "prompt = no",
                "default_md = sha256",
                "distinguished_name = dn",
                "req_extensions = req_ext",
                "",
                "[dn]",
                f"CN = {alt_names[0] if alt_names else DEFAULT_SERVER_NAME}",
                "",
                "[req_ext]",
                "subjectAltName = @alt_names",
                "extendedKeyUsage = serverAuth",
                "",
                "[alt_names]",
                *dns_lines,
                *ip_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_ca_openssl_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "[req]",
                "prompt = no",
                "default_md = sha256",
                "distinguished_name = dn",
                "x509_extensions = v3_ca",
                "",
                "[dn]",
                "CN = pqc-framework-mqtt-local-ca",
                "",
                "[v3_ca]",
                "subjectKeyIdentifier = hash",
                "authorityKeyIdentifier = keyid:always,issuer",
                "basicConstraints = critical,CA:true,pathlen:0",
                "keyUsage = critical,keyCertSign,cRLSign",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_client_openssl_config(path: Path, common_name: str) -> None:
    path.write_text(
        "\n".join(
            [
                "[req]",
                "prompt = no",
                "default_md = sha256",
                "distinguished_name = dn",
                "req_extensions = req_ext",
                "",
                "[dn]",
                f"CN = {common_name}",
                "",
                "[req_ext]",
                "extendedKeyUsage = clientAuth",
                "keyUsage = digitalSignature",
                "",
            ]
        ),
        encoding="utf-8",
    )


def provision_classical_certs(args: argparse.Namespace) -> None:
    ensure_openssl()
    cert_dir = broker_root() / "runtime/classical/certs"
    cert_dir.mkdir(parents=True, exist_ok=True)

    host_address = None
    if getattr(args, "host_config", None):
        host_address = load_host_config(repo_root() / args.host_config).address

    server_name = args.server_name
    extra_names = args.extra_dns_name or []
    extra_ips = args.extra_ip_address or []
    ip_addresses = ["127.0.0.1", *( [host_address] if host_address else [] ), *extra_ips]
    client_name = args.client_name
    healthcheck_name = args.healthcheck_name
    days = str(args.days)

    ca_conf = cert_dir / "ca-openssl.cnf"
    server_conf = cert_dir / "server-openssl.cnf"
    client_conf = cert_dir / "client-openssl.cnf"
    healthcheck_conf = cert_dir / "healthcheck-openssl.cnf"
    write_ca_openssl_config(ca_conf)
    write_server_openssl_config(server_conf, [server_name, "localhost", *extra_names], ip_addresses)
    write_client_openssl_config(client_conf, client_name)
    write_client_openssl_config(healthcheck_conf, healthcheck_name)

    commands = [
        ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(cert_dir / "ca.key")],
        ["openssl", "req", "-x509", "-new", "-nodes", "-key", str(cert_dir / "ca.key"), "-sha256", "-days", days, "-config", str(ca_conf), "-out", str(cert_dir / "ca.crt")],
        ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(cert_dir / "server.key")],
        ["openssl", "req", "-new", "-key", str(cert_dir / "server.key"), "-out", str(cert_dir / "server.csr"), "-config", str(server_conf)],
        ["openssl", "x509", "-req", "-in", str(cert_dir / "server.csr"), "-CA", str(cert_dir / "ca.crt"), "-CAkey", str(cert_dir / "ca.key"), "-CAcreateserial", "-out", str(cert_dir / "server.crt"), "-days", days, "-sha256", "-extensions", "req_ext", "-extfile", str(server_conf)],
        ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(cert_dir / "client.key")],
        ["openssl", "req", "-new", "-key", str(cert_dir / "client.key"), "-out", str(cert_dir / "client.csr"), "-config", str(client_conf)],
        ["openssl", "x509", "-req", "-in", str(cert_dir / "client.csr"), "-CA", str(cert_dir / "ca.crt"), "-CAkey", str(cert_dir / "ca.key"), "-CAcreateserial", "-out", str(cert_dir / "client.crt"), "-days", days, "-sha256", "-extensions", "req_ext", "-extfile", str(client_conf)],
        ["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(cert_dir / "healthcheck.key")],
        ["openssl", "req", "-new", "-key", str(cert_dir / "healthcheck.key"), "-out", str(cert_dir / "healthcheck.csr"), "-config", str(healthcheck_conf)],
        ["openssl", "x509", "-req", "-in", str(cert_dir / "healthcheck.csr"), "-CA", str(cert_dir / "ca.crt"), "-CAkey", str(cert_dir / "ca.key"), "-CAcreateserial", "-out", str(cert_dir / "healthcheck.crt"), "-days", days, "-sha256", "-extensions", "req_ext", "-extfile", str(healthcheck_conf)],
    ]

    for command in commands:
        run_command(command, dry_run=args.dry_run)

    if not args.dry_run:
        for path in cert_dir.glob("*.key"):
            path.chmod(0o600)
        print(f"Provisioned local classical MQTT TLS material under {display_path(cert_dir)}")


def deploy(args: argparse.Namespace) -> None:
    host = load_host_config(repo_root() / args.host_config)
    remote_dir = args.remote_dir
    source_root = broker_root()
    file_copies = [
        (source_root / "compose.yaml", f"{remote_dir}/"),
        (source_root / "env.example", f"{remote_dir}/"),
        (source_root / "scripts" / "mqtt_broker_ctl.py", f"{remote_dir}/scripts/"),
    ]
    directory_copies = [
        (source_root / "config", f"{remote_dir}/"),
    ]
    runtime_dir = source_root / "runtime"
    if runtime_dir.exists():
        directory_copies.append((runtime_dir, f"{remote_dir}/"))

    target = ssh_target(host)
    run_command(["ssh", target, f"mkdir -p {remote_dir} {remote_dir}/scripts"], dry_run=args.dry_run)
    for source_path, remote_target_dir in file_copies:
        run_command(["scp", str(source_path), f"{target}:{remote_target_dir}"], dry_run=args.dry_run)
    for source_path, remote_target_dir in directory_copies:
        run_command(["scp", "-r", str(source_path), f"{target}:{remote_target_dir}"], dry_run=args.dry_run)

    permission_targets = [f"{remote_dir}/config"]
    if runtime_dir.exists():
        permission_targets.append(f"{remote_dir}/runtime")
    run_command(["ssh", target, "chmod -R a+rX " + " ".join(permission_targets)], dry_run=args.dry_run)



def remote_cleanup_command(remote_dir: str) -> str:
    remote_path = remote_shell_path(remote_dir)
    return (
        f"docker run --rm -v {remote_path}:/work --entrypoint sh eclipse-mosquitto:2.0 "
        "-c 'rm -rf /work/data /work/log' >/dev/null 2>&1 || true; "
        f"rm -rf {remote_path}"
    )

def _compose_environment(args: argparse.Namespace) -> list[str]:
    env: list[str] = []
    if getattr(args, "classical_port", None):
        env.append(f"MQTT_CLASSICAL_TLS_PORT={args.classical_port}")
    if getattr(args, "oqs_port", None):
        env.append(f"MQTT_OQS_TLS_PORT={args.oqs_port}")
    return env


def compose_remote(args: argparse.Namespace, compose_args: list[str]) -> None:
    host = load_host_config(repo_root() / args.host_config)
    env = _compose_environment(args)
    env_prefix = " ".join(shlex.quote(item) for item in env)
    compose = ["docker", "compose", "--project-name", args.project_name, *compose_args]
    compose_text = " ".join(shlex.quote(item) for item in compose)
    command = f"cd {remote_shell_path(args.remote_dir)} && "
    if env_prefix:
        command += f"{env_prefix} "
    command += compose_text
    run_command(["ssh", ssh_target(host), command], dry_run=args.dry_run)


def start(args: argparse.Namespace) -> None:
    compose_remote(args, ["--profile", args.profile, "up", "-d"])


def stop(args: argparse.Namespace) -> None:
    compose_remote(args, ["--profile", "classical", "--profile", "oqs", "down", "--remove-orphans"])
    host = load_host_config(repo_root() / args.host_config)
    cleanup_command = "docker rm -f pqc-mqtt-classical pqc-mqtt-oqs >/dev/null 2>&1 || true"
    run_command(["ssh", ssh_target(host), cleanup_command], dry_run=args.dry_run)


def status(args: argparse.Namespace) -> None:
    compose_remote(args, ["ps"])


def logs(args: argparse.Namespace) -> None:
    service = "mqtt-oqs" if args.profile == "oqs" else "mqtt-classical"
    compose_remote(args, ["logs", "--tail", str(args.tail), service])


def add_common_remote_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host-config", default=str(DEFAULT_HOST_CONFIG), help="repository-relative host config path")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="remote gateway directory for the broker compose project")
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME, help="Docker Compose project name")
    parser.add_argument("--dry-run", action="store_true", help="print commands without executing them")


def add_port_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--classical-port", type=int, help="host TLS port for the classical profile")
    parser.add_argument("--oqs-port", type=int, help="host TLS port for the OQS profile")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the PQC Framework MQTT broker compose project")
    sub = parser.add_subparsers(dest="command", required=True)

    provision = sub.add_parser("provision-certs", help="generate local classical MQTT TLS material")
    provision.add_argument("--server-name", default=DEFAULT_SERVER_NAME)
    provision.add_argument("--extra-dns-name", action="append")
    provision.add_argument("--extra-ip-address", action="append")
    provision.add_argument("--host-config", default=str(DEFAULT_HOST_CONFIG), help="include host-config network.address as an IP SAN when present")
    provision.add_argument("--client-name", default=DEFAULT_CLIENT_NAME)
    provision.add_argument("--healthcheck-name", default=DEFAULT_HEALTHCHECK_NAME)
    provision.add_argument("--days", type=int, default=365)
    provision.add_argument("--dry-run", action="store_true")
    provision.set_defaults(func=provision_classical_certs)

    deploy_parser = sub.add_parser("deploy", help="copy compose project and generated runtime material to the gateway")
    add_common_remote_options(deploy_parser)
    deploy_parser.set_defaults(func=deploy)

    start_parser = sub.add_parser("start", help="start a broker profile on the gateway")
    add_common_remote_options(start_parser)
    add_port_options(start_parser)
    start_parser.add_argument("--profile", choices=("classical", "oqs"), default="classical")
    start_parser.set_defaults(func=start)

    stop_parser = sub.add_parser("stop", help="stop broker services on the gateway")
    add_common_remote_options(stop_parser)
    add_port_options(stop_parser)
    stop_parser.set_defaults(func=stop)

    status_parser = sub.add_parser("status", help="show gateway compose service status")
    add_common_remote_options(status_parser)
    add_port_options(status_parser)
    status_parser.set_defaults(func=status)

    logs_parser = sub.add_parser("logs", help="show gateway broker logs")
    add_common_remote_options(logs_parser)
    add_port_options(logs_parser)
    logs_parser.add_argument("--profile", choices=("classical", "oqs"), default="classical")
    logs_parser.add_argument("--tail", type=int, default=100)
    logs_parser.set_defaults(func=logs)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
