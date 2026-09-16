#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BROKER_RELATIVE_DIR = Path("experiment/mqtt-broker")
DEFAULT_GATEWAY_CONFIG = Path("configs/gateways/pqc_gateway1.yaml")
DEFAULT_REMOTE_DIR = "~/pqc-framework-02/experiment/mqtt-broker"
DEFAULT_PROJECT_NAME = "pqc-framework-mqtt-broker"
DEFAULT_SERVER_NAME = "pqc-gateway1.pqcnet"
DEFAULT_SERVER_ALIAS = "pqc-gateway1"
DEFAULT_CLIENT_NAME = "stm32-mqtt-client"
DEFAULT_HEALTHCHECK_NAME = "pqc-mqtt-server-healthcheck"
MOSQUITTO_IMAGE = "eclipse-mosquitto:2.1.2-alpine@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797"
CLASSICAL_IMAGE = MOSQUITTO_IMAGE
OQS_IMAGE = MOSQUITTO_IMAGE
OQS_KEM_GROUP = "SecP256r1MLKEM768"
CLASSICAL_CERTIFICATE_PROFILE = "rsa3072"
MLDSA65_CERTIFICATE_PROFILE = "mldsa65"
BROKER_PROFILE_SERVICES = {
    "classical": "mqtt-classical",
    "classical-server-auth": "mqtt-classical-server-auth",
    "oqs": "mqtt-oqs",
    "oqs-mtls": "mqtt-oqs-mtls",
    "reporting": "mqtt-reporting",
}
BROKER_PROFILES = tuple(BROKER_PROFILE_SERVICES)
TLS_KEYLOG_FILENAME = "mqtt-broker-tls-keylog.log"
HOST_BROKER_EVIDENCE_CLASS = "host_side"
HOST_BROKER_EVIDENCE_LABEL = "host-side/broker-side MQTT/TLS compatibility evidence"
HOST_BROKER_EVIDENCE_BOUNDARY = (
    "host-side client container and broker-side Docker validation only; "
    "does not claim STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, "
    "wolfMQTT-on-STM32, or end-to-end wireless success"
)


@dataclass(frozen=True)
class HostConfig:
    alias: str
    user: str | None
    address: str | None = None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def broker_root() -> Path:
    return repo_root() / BROKER_RELATIVE_DIR


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(repo_root()))
    except ValueError:
        return str(path)


def certificate_profile_dir(profile_id: str) -> Path:
    return repo_root() / "secrets" / "certificates" / profile_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    """Load the canonical gateway profile into the broker's SSH view."""
    if not path.is_file():
        raise SystemExit(f"gateway config not found: {path}")
    data = load_simple_yaml(path)
    alias = _nested(data, "identity", "fqdn") or _nested(data, "identity", "alias")
    user = _nested(data, "identity", "ssh_user")
    address = _nested(data, "network", "address") or _nested(data, "identity", "address")
    if not isinstance(alias, str) or not alias:
        raise SystemExit(f"gateway config is missing identity.fqdn/identity.alias: {path}")
    if not isinstance(user, str) or not user:
        raise SystemExit(f"gateway config is missing identity.ssh_user: {path}")
    return HostConfig(
        alias=alias,
        user=user,
        address=address if isinstance(address, str) and address else None,
    )


def _display_command(args: list[str]) -> str:
    return " ".join(args)


def run_command(args: list[str], *, cwd: Path | None = None, dry_run: bool = False) -> None:
    display = _display_command(args)
    if dry_run:
        print(display)
        return
    completed = subprocess.run(args, cwd=cwd, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"command failed with exit code {completed.returncode}: {display}")


def run_command_with_input(args: list[str], input_text: str, *, dry_run: bool = False) -> None:
    display = _display_command(args)
    if dry_run:
        print(display)
        print(input_text)
        return
    completed = subprocess.run(args, input=input_text, text=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"command failed with exit code {completed.returncode}: {display}")


def ssh_target(host: HostConfig) -> str:
    if host.user:
        return f"{host.user}@{host.alias}"
    return host.alias


def tls_host(host: HostConfig) -> str:
    return host.address or host.alias


def remote_shell_path(path: str) -> str:
    """Return a shell-safe remote path while preserving leading ~/ expansion."""
    if path == "~":
        return "$HOME"
    if path.startswith("~/"):
        remainder = path[2:]
        return "$HOME/" + shlex.quote(remainder)
    return shlex.quote(path)




def remote_repo_root(remote_dir: str) -> str:
    normalized = remote_dir.rstrip("/")
    suffix = "/experiment/mqtt-broker"
    if not normalized.endswith(suffix):
        raise SystemExit(
            "remote broker directory must end with /experiment/mqtt-broker "
            "so repository-root certificate deployment can be derived"
        )
    return normalized[: -len(suffix)]


def deploy(args: argparse.Namespace) -> None:
    host = load_host_config(repo_root() / args.gateway_config)
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
    # TLS profiles consume repository-root certificate-profile staging directories.
    # The gateway copy is deployment state only and is never authoritative.
    secrets_mqtt_dir = repo_root() / "secrets" / "certificates"
    remote_root = remote_repo_root(remote_dir)
    if secrets_mqtt_dir.exists():
        directory_copies.append((secrets_mqtt_dir, f"{remote_root}/secrets/"))

    target = ssh_target(host)
    run_command([
        "ssh",
        target,
        (
            f"mkdir -p {remote_shell_path(remote_dir)} "
            f"{remote_shell_path(remote_dir + '/scripts')} "
            f"{remote_shell_path(remote_dir + '/runtime')} "
            f"{remote_shell_path(remote_root + '/secrets')} "
            f"{remote_shell_path(remote_root + '/secrets/certificates')}"
        ),
    ], dry_run=args.dry_run)
    for source_path, remote_target_dir in file_copies:
        run_command(["scp", str(source_path), f"{target}:{remote_target_dir}"], dry_run=args.dry_run)
    for source_path, remote_target_dir in directory_copies:
        run_command(["scp", "-r", str(source_path), f"{target}:{remote_target_dir}"], dry_run=args.dry_run)

    # Configuration is public deployment state, but staged certificate trees can
    # contain private keys. Never apply a broad world-readable mode to them.
    permission_commands = [
        f"chmod -R a+rX {remote_shell_path(remote_dir + '/config')}"
    ]
    if secrets_mqtt_dir.exists():
        certificate_root = remote_shell_path(f"{remote_root}/secrets/certificates")
        permission_commands.extend([
            f"find {certificate_root} -type d -exec chmod 0700 {{}} \\;",
            f"find {certificate_root} -type f -name '*.key' -exec chmod 0600 {{}} \\;",
            f"find {certificate_root} -type f ! -name '*.key' -exec chmod 0644 {{}} \\;",
        ])
    run_command(["ssh", target, " && ".join(permission_commands)], dry_run=args.dry_run)


def remote_cleanup_command(remote_dir: str) -> str:
    remote_path = remote_shell_path(remote_dir)
    return (
        f"docker run --rm -v {remote_path}:/work --entrypoint sh {MOSQUITTO_IMAGE} "
        "-c 'rm -rf "
        "/work/data /work/log "
        "/work/experiment/mqtt-broker/data "
        "/work/experiment/mqtt-broker/log' >/dev/null 2>&1 || true; "
        f"rm -rf {remote_path}"
    )


def _compose_environment(args: argparse.Namespace) -> list[str]:
    env: list[str] = []
    if getattr(args, "classical_port", None):
        env.append(f"MQTT_CLASSICAL_TLS_PORT={args.classical_port}")
        env.append(f"MQTT_CLASSICAL_SERVER_AUTH_TLS_PORT={args.classical_port}")
    if getattr(args, "oqs_port", None):
        env.append(f"MQTT_OQS_TLS_PORT={args.oqs_port}")
        env.append(f"MQTT_OQS_MTLS_PORT={args.oqs_port}")
    if getattr(args, "certificate_profile", None):
        env.append(f"MQTT_CERTIFICATE_PROFILE={args.certificate_profile}")
    return env


def compose_remote(args: argparse.Namespace, compose_args: list[str]) -> None:
    host = load_host_config(repo_root() / args.gateway_config)
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
    compose_remote(
        args,
        ["--profile", args.profile, "up", "-d", "--wait", "--wait-timeout", "90"],
    )


def stop(args: argparse.Namespace) -> None:
    compose_remote(
        args,
        [
            "--profile",
            "classical",
            "--profile",
            "classical-server-auth",
            "--profile",
            "oqs",
            "--profile",
            "oqs-mtls",
            "--profile",
            "reporting",
            "down",
            "--remove-orphans",
        ],
    )
    host = load_host_config(repo_root() / args.gateway_config)
    cleanup_command = (
        "docker rm -f pqc-mqtt-classical pqc-mqtt-classical-server-auth "
        "pqc-mqtt-oqs pqc-mqtt-oqs-mtls pqc-mqtt-reporting >/dev/null 2>&1 || true"
    )
    run_command(["ssh", ssh_target(host), cleanup_command], dry_run=args.dry_run)


def status(args: argparse.Namespace) -> None:
    service = BROKER_PROFILE_SERVICES[args.profile]
    compose_remote(args, ["ps", service])


def logs(args: argparse.Namespace) -> None:
    service = BROKER_PROFILE_SERVICES[args.profile]
    compose_remote(args, ["logs", "--tail", str(args.tail), service])


def collect_tls_keylog(args: argparse.Namespace) -> None:
    """Copy the selected broker profile TLS key log from the live container."""
    host = load_host_config(repo_root() / args.gateway_config)
    target = ssh_target(host)
    service = BROKER_PROFILE_SERVICES[args.profile]
    remote_command = (
        f"cd {remote_shell_path(args.remote_dir)} && "
        f"docker compose --project-name {shlex.quote(args.project_name)} "
        f"exec -T {shlex.quote(service)} sh -c "
        f"{shlex.quote('test -s /mosquitto/keylog/' + TLS_KEYLOG_FILENAME + ' && cat /mosquitto/keylog/' + TLS_KEYLOG_FILENAME)}"
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ["ssh", target, remote_command]
    if args.dry_run:
        print("DRY RUN: " + shlex.join(command))
        return
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode != 0:
        if output.exists():
            output.unlink()
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(detail or "TLS key log collection failed")
    if not completed.stdout:
        if output.exists():
            output.unlink()
        raise SystemExit("TLS key log is missing or empty")
    output.write_bytes(completed.stdout)
    print(f"TLS key log copied: {output}")

def validate_oqs_tls(args: argparse.Namespace) -> None:
    host = load_host_config(repo_root() / args.gateway_config)
    target = ssh_target(host)
    cert_dir = f"{remote_repo_root(args.remote_dir)}/secrets/certificates/{args.certificate_profile}"
    port = str(args.oqs_port or 8884)
    validation_script = "\n".join([
        "set -eu",
        f"echo 'Evidence class: {HOST_BROKER_EVIDENCE_CLASS}'",
        f"echo 'Evidence label: {HOST_BROKER_EVIDENCE_LABEL}'",
        "echo 'Evidence profile: oqs'",
        f"echo 'Evidence boundary: {HOST_BROKER_EVIDENCE_BOUNDARY}'",
        f"echo 'Requested TLS group: {args.oqs_group}'",
        "rm -f /tmp/pqc-oqs-tls-validate.log",
        (
            "if ! output=$(echo | openssl s_client "
            f"-connect 127.0.0.1:{port} "
            "-tls1_3 "
            f"-groups {shlex.quote(args.oqs_group)} "
            "-CAfile /certs/ca.crt "
            "-verify_return_error 2>&1); then "
            "printf '%s\\n' \"$output\" | tee /tmp/pqc-oqs-tls-validate.log; exit 1; fi"
        ),
        "printf '%s\\n' \"$output\" | tee /tmp/pqc-oqs-tls-validate.log",
        "grep -q 'New, TLSv1.3' /tmp/pqc-oqs-tls-validate.log",
        "grep -q 'Certificate chain' /tmp/pqc-oqs-tls-validate.log",
        "! grep -q 'no peer certificate available' /tmp/pqc-oqs-tls-validate.log",
        "! grep -q 'Cipher is (NONE)' /tmp/pqc-oqs-tls-validate.log",
        "grep -q 'Verify return code: 0 (ok)' /tmp/pqc-oqs-tls-validate.log",
        f"echo 'Negotiated forced TLS group: {args.oqs_group}'",
    ])
    command = (
        f"docker run --rm --network host -v {remote_shell_path(cert_dir)}:/certs:ro --entrypoint sh {shlex.quote(args.image)} "
        f"-lc {shlex.quote('timeout 20 sh -lc ' + shlex.quote(validation_script))}"
    )
    run_command(["ssh", target, command], dry_run=args.dry_run)


def docker_safe_name(value: str) -> str:
    safe = []
    for char in value.lower():
        if char.isalnum() or char in ("-", "_"):
            safe.append(char)
        else:
            safe.append("-")
    return "".join(safe).strip("-_") or "pqc-mqtt"


def host_broker_evidence_preamble(profile: str) -> list[str]:
    return [
        f"echo 'Evidence class: {HOST_BROKER_EVIDENCE_CLASS}'",
        f"echo 'Evidence label: {HOST_BROKER_EVIDENCE_LABEL}'",
        f"echo 'Evidence profile: {profile}'",
        f"echo 'Evidence boundary: {HOST_BROKER_EVIDENCE_BOUNDARY}'",
    ]


def validate_mqtt_pubsub(
    args: argparse.Namespace,
    *,
    profile: str,
    certificate_profile: str,
    port: int,
    image: str,
    mutual_tls: bool,
    oqs_client: bool = False,
) -> None:
    host = load_host_config(repo_root() / args.gateway_config)
    target = ssh_target(host)
    cert_dir = f"{remote_repo_root(args.remote_dir)}/secrets/certificates/{certificate_profile}"
    topic = args.topic
    message = args.message
    subscriber_name = docker_safe_name(f"{args.project_name}-{profile}-sub")[:63]
    cert_mount = remote_shell_path(cert_dir)
    common_client_parts = [
        "-h localhost",
        f"-p {shlex.quote(str(port))}",
        "--cafile /certs/ca.crt",
        "--tls-version tlsv1.3",
    ]
    if mutual_tls:
        common_client_parts.extend([
            "--cert /certs/client.crt",
            "--key /certs/client.key",
        ])
    common_client_args = " ".join(common_client_parts)
    oqs_config = f"{remote_repo_root(args.remote_dir)}/experiment/mqtt-broker/config/oqs/openssl.cnf"
    client_container_options = ""
    if oqs_client:
        client_container_options = (
            f"-e OPENSSL_CONF=/mosquitto/config/openssl.cnf "
            f"-v {remote_shell_path(oqs_config)}:/mosquitto/config/openssl.cnf:ro "
        )
    validation_script = "\n".join([
        "set -eu",
        *host_broker_evidence_preamble(profile),
        f"subscriber={shlex.quote(subscriber_name)}",
        f"topic={shlex.quote(topic)}",
        f"message={shlex.quote(message)}",
        "docker rm -f \"$subscriber\" >/dev/null 2>&1 || true",
        (
            f"docker run -d --network host --name \"$subscriber\" "
            f"{client_container_options}-v {cert_mount}:/certs:ro "
            f"--entrypoint mosquitto_sub {shlex.quote(image)} "
            f"{common_client_args} -t \"$topic\" -C 1 >/dev/null"
        ),
        "cleanup() { docker rm -f \"$subscriber\" >/dev/null 2>&1 || true; }",
        "trap cleanup EXIT",
        "sleep 2",
        "subscriber_state=$(docker inspect -f '{{.State.Status}}' \"$subscriber\" 2>/dev/null || true)",
        "if [ \"$subscriber_state\" != running ]; then",
        "  echo 'subscriber failed before publish' >&2",
        "  docker logs \"$subscriber\" 2>&1 || true",
        "  exit 1",
        "fi",
        (
            f"docker run --rm --network host {client_container_options}"
            f"-v {cert_mount}:/certs:ro --entrypoint mosquitto_pub {shlex.quote(image)} "
            f"{common_client_args} -t \"$topic\" -m \"$message\""
        ),
        "found=0",
        "for _attempt in $(seq 1 20); do",
        "  logs=$(docker logs \"$subscriber\" 2>&1 || true)",
        "  if [ -n \"$logs\" ]; then printf '%s\n' \"$logs\"; fi",
        "  if printf '%s\n' \"$logs\" | grep -Fx -- \"$message\" >/dev/null; then found=1; break; fi",
        "  subscriber_state=$(docker inspect -f '{{.State.Status}}' \"$subscriber\" 2>/dev/null || true)",
        "  if [ \"$subscriber_state\" != running ]; then",
        "    echo 'subscriber exited before receiving expected message' >&2",
        "    exit 1",
        "  fi",
        "  sleep 1",
        "done",
        "if [ \"$found\" != 1 ]; then echo 'expected MQTT payload was not received' >&2; exit 1; fi",
    ])
    command = f"timeout 45 sh -lc {shlex.quote(validation_script)}"
    run_command(["ssh", target, command], dry_run=args.dry_run)


def validate_classical_mqtt(args: argparse.Namespace) -> None:
    """Validate the classical mutual-TLS broker profile."""
    validate_mqtt_pubsub(
        args,
        profile="classical",
        certificate_profile=args.certificate_profile or "rsa3072",
        port=args.classical_port or 8883,
        image=args.image,
        mutual_tls=True,
    )


def validate_classical_server_auth_mqtt(args: argparse.Namespace) -> None:
    """Validate the classical server-authentication-only broker profile."""
    validate_mqtt_pubsub(
        args,
        profile="classical-server-auth",
        certificate_profile=args.certificate_profile or "rsa3072",
        port=args.classical_port or 8883,
        image=args.image,
        mutual_tls=False,
    )


def validate_oqs_mqtt(args: argparse.Namespace) -> None:
    """Validate hybrid key exchange with classical server authentication."""
    validate_mqtt_pubsub(
        args,
        profile="oqs",
        certificate_profile=args.certificate_profile or "rsa3072",
        port=args.oqs_port or 8884,
        image=args.image,
        mutual_tls=False,
        oqs_client=True,
    )

def validate_oqs_mtls_mqtt(args: argparse.Namespace) -> None:
    """Validate hybrid key exchange with classical mutual authentication."""
    validate_mqtt_pubsub(
        args,
        profile="oqs-mtls",
        certificate_profile=args.certificate_profile or "rsa3072",
        port=args.oqs_port or 8885,
        image=args.image,
        mutual_tls=True,
        oqs_client=True,
    )



def runtime_version(args: argparse.Namespace) -> None:
    """Print the effective Mosquitto version from the configured runtime image on the gateway."""
    host = load_host_config(repo_root() / args.gateway_config)
    target = ssh_target(host)
    command = (
        f"docker run --rm --entrypoint mosquitto {shlex.quote(args.image)} -h 2>&1 "
        "| sed -n '1p'"
    )
    run_command(["ssh", target, command], dry_run=args.dry_run)

def add_common_remote_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--certificate-profile", help="resolved MQTT certificate profile under secrets/certificates")
    parser.add_argument("--gateway-config", default=str(DEFAULT_GATEWAY_CONFIG), help="repository-relative canonical gateway config path")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="remote gateway directory for the broker compose project")
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME, help="Docker Compose project name")
    parser.add_argument("--dry-run", action="store_true", help="print commands without executing them")


def add_port_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--classical-port", type=int, help="host TLS port for the classical profile")
    parser.add_argument("--oqs-port", type=int, help="host TLS port for the OQS profile")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the PQC Framework MQTT broker compose project")
    sub = parser.add_subparsers(dest="command", required=True)

    deploy_parser = sub.add_parser("deploy", help="copy compose project and generated runtime material to the gateway")
    add_common_remote_options(deploy_parser)
    deploy_parser.set_defaults(func=deploy)

    start_parser = sub.add_parser("start", help="start a broker profile on the gateway")
    add_common_remote_options(start_parser)
    add_port_options(start_parser)
    start_parser.add_argument("--profile", choices=BROKER_PROFILES, default="classical")
    start_parser.set_defaults(func=start)

    stop_parser = sub.add_parser("stop", help="stop broker services on the gateway")
    add_common_remote_options(stop_parser)
    add_port_options(stop_parser)
    stop_parser.set_defaults(func=stop)

    status_parser = sub.add_parser("status", help="show gateway compose service status")
    add_common_remote_options(status_parser)
    add_port_options(status_parser)
    status_parser.add_argument("--profile", choices=BROKER_PROFILES, default="classical")
    status_parser.set_defaults(func=status)

    version_parser = sub.add_parser("runtime-version", help="report the effective Mosquitto version from the gateway runtime image")
    add_common_remote_options(version_parser)
    version_parser.add_argument("--image", default=MOSQUITTO_IMAGE)
    version_parser.set_defaults(func=runtime_version)

    logs_parser = sub.add_parser("logs", help="show gateway broker logs")
    add_common_remote_options(logs_parser)
    add_port_options(logs_parser)
    logs_parser.add_argument("--profile", choices=BROKER_PROFILES, default="classical")
    logs_parser.add_argument("--tail", type=int, default=100)
    logs_parser.set_defaults(func=logs)

    keylog_parser = sub.add_parser("collect-tls-keylog", help="copy a broker TLS key log from the gateway")
    add_common_remote_options(keylog_parser)
    keylog_parser.add_argument("--profile", choices=BROKER_PROFILES, required=True)
    keylog_parser.add_argument("--output", required=True)
    keylog_parser.set_defaults(func=collect_tls_keylog)

    validate_oqs = sub.add_parser("validate-oqs-tls", help="validate remote OQS server-authenticated hybrid TLS handshake using an OQS-enabled OpenSSL client container")
    add_common_remote_options(validate_oqs)
    add_port_options(validate_oqs)
    validate_oqs.set_defaults(certificate_profile="rsa3072")
    validate_oqs.add_argument("--oqs-group", default=OQS_KEM_GROUP)
    validate_oqs.add_argument("--image", default=OQS_IMAGE)
    validate_oqs.set_defaults(func=validate_oqs_tls)


    validate_classical_server_auth_parser = sub.add_parser(
        "validate-classical-server-auth-mqtt",
        help="validate classical TLS 1.3 server-authenticated MQTT publish/subscribe without a client certificate",
    )
    add_common_remote_options(validate_classical_server_auth_parser)
    add_port_options(validate_classical_server_auth_parser)
    validate_classical_server_auth_parser.set_defaults(certificate_profile="rsa3072")
    validate_classical_server_auth_parser.add_argument("--image", default=CLASSICAL_IMAGE)
    validate_classical_server_auth_parser.add_argument("--topic", default="pqc/test/e2e")
    validate_classical_server_auth_parser.add_argument("--message", default="pqc-classical-server-auth-mqtt-e2e")
    validate_classical_server_auth_parser.set_defaults(func=validate_classical_server_auth_mqtt)

    validate_classical_mqtt_parser = sub.add_parser(
        "validate-classical-mqtt",
        help="validate classical MQTT publish/subscribe using separate client containers",
    )
    add_common_remote_options(validate_classical_mqtt_parser)
    add_port_options(validate_classical_mqtt_parser)
    validate_classical_mqtt_parser.set_defaults(certificate_profile="rsa3072")
    validate_classical_mqtt_parser.add_argument("--image", default=CLASSICAL_IMAGE)
    validate_classical_mqtt_parser.add_argument("--topic", default="pqc/test/e2e")
    validate_classical_mqtt_parser.add_argument("--message", default="pqc-classical-mqtt-e2e")
    validate_classical_mqtt_parser.set_defaults(func=validate_classical_mqtt)

    validate_oqs_mqtt_parser = sub.add_parser(
        "validate-oqs-mqtt",
        help="validate OQS MQTT publish/subscribe using separate OQS client containers",
    )
    add_common_remote_options(validate_oqs_mqtt_parser)
    add_port_options(validate_oqs_mqtt_parser)
    validate_oqs_mqtt_parser.set_defaults(certificate_profile="rsa3072")
    validate_oqs_mqtt_parser.add_argument("--image", default=OQS_IMAGE)
    validate_oqs_mqtt_parser.add_argument("--topic", default="pqc/test/e2e")
    validate_oqs_mqtt_parser.add_argument("--message", default="pqc-oqs-mqtt-e2e")
    validate_oqs_mqtt_parser.set_defaults(func=validate_oqs_mqtt)

    validate_oqs_mtls_mqtt_parser = sub.add_parser(
        "validate-oqs-mtls-mqtt",
        help="validate OQS hybrid MQTT mutual TLS using classical client credentials",
    )
    add_common_remote_options(validate_oqs_mtls_mqtt_parser)
    add_port_options(validate_oqs_mtls_mqtt_parser)
    validate_oqs_mtls_mqtt_parser.set_defaults(certificate_profile="rsa3072")
    validate_oqs_mtls_mqtt_parser.add_argument("--image", default=OQS_IMAGE)
    validate_oqs_mtls_mqtt_parser.add_argument("--topic", default="pqc/test/e2e")
    validate_oqs_mtls_mqtt_parser.add_argument("--message", default="pqc-oqs-mtls-mqtt-e2e")
    validate_oqs_mtls_mqtt_parser.set_defaults(func=validate_oqs_mtls_mqtt)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
