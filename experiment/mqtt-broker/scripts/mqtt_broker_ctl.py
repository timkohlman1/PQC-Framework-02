#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BROKER_RELATIVE_DIR = Path("experiment/mqtt-broker")
DEFAULT_HOST_CONFIG = Path("configs/hosts/gateway.yaml")
DEFAULT_REMOTE_DIR = "~/pqc-framework-02/experiment/mqtt-broker"
DEFAULT_PROJECT_NAME = "pqc-framework-mqtt-broker"
DEFAULT_SERVER_NAME = "pqc-gateway1.pqcnet"
DEFAULT_SERVER_ALIAS = "pqc-gateway1"
DEFAULT_CLIENT_NAME = "pqc-mqtt-client"
DEFAULT_HEALTHCHECK_NAME = "pqc-mqtt-server-healthcheck"
CLASSICAL_IMAGE = "eclipse-mosquitto:2.0"
OQS_IMAGE = "openquantumsafe/mosquitto:latest"
OQS_KEM_GROUP = "SecP256r1MLKEM768"
BROKER_PROFILE_SERVICES = {
    "classical": "mqtt-classical",
    "classical-server-auth": "mqtt-classical-server-auth",
    "oqs": "mqtt-oqs",
}
BROKER_PROFILES = tuple(BROKER_PROFILE_SERVICES)
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
    return repo_root() / "secrets" / "mqtt" / profile_id


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


def sync_stepca_certs(args: argparse.Namespace) -> None:
    """Stage the authoritative classical step-ca material for broker workflows."""
    source_root = repo_root() / "framework" / "certs"
    public_ca = source_root / "secrets" / "public" / "ca"
    broker_identity = source_root / "secrets" / "runtime" / "mqtt-broker"
    client_identity = source_root / "secrets" / "runtime" / "stm32"
    required = {
        "ca.crt": public_ca / "root-ca.crt",
        "root-ca.crt": public_ca / "root-ca.crt",
        "intermediate-ca.crt": public_ca / "intermediate-ca.crt",
        "ca-chain.crt": public_ca / "ca-chain.crt",
        "server.crt": broker_identity / "tls.crt",
        "server.key": broker_identity / "tls.key",
    }
    optional = {
        "client.crt": client_identity / "client.crt",
        "client.key": client_identity / "client.key",
        "healthcheck.crt": client_identity / "client.crt",
        "healthcheck.key": client_identity / "client.key",
    }
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise SystemExit(
            "authoritative step-ca material is unavailable; run framework/certs first. Missing: "
            + ", ".join(missing)
        )
    cert_dir = certificate_profile_dir(args.certificate_profile)
    if args.dry_run:
        print(f"sync {display_path(source_root)} -> {display_path(cert_dir)}")
        return
    cert_dir.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name, source in {**required, **optional}.items():
        if source.is_file():
            destination = cert_dir / name
            shutil.copy2(source, destination)
            copied[name] = _sha256(destination)
            if destination.suffix == ".key":
                destination.chmod(0o600)
    provenance = {
        "schema_version": 2,
        "profile_id": args.certificate_profile,
        "profile_kind": "stepca-classical",
        "source": "framework/certs",
        "ca_algorithm": "classical-x509",
        "leaf_algorithm": "classical",
        "ca_sha256": copied["ca.crt"],
        "root_ca_sha256": copied["root-ca.crt"],
        "intermediate_ca_sha256": copied["intermediate-ca.crt"],
        "ca_chain_sha256": copied["ca-chain.crt"],
        "server_certificate_sha256": copied["server.crt"],
        "files": copied,
    }
    (cert_dir / "certificate-provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Synchronized authoritative step-ca MQTT TLS material under {display_path(cert_dir)}")

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
    # Both TLS profiles consume the same repository-root step-ca staging area.
    # The gateway copy is deployment state only and is never authoritative.
    secrets_mqtt_dir = repo_root() / "secrets" / "mqtt"
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
            f"{remote_shell_path(remote_root + '/secrets/mqtt')}"
        ),
    ], dry_run=args.dry_run)
    for source_path, remote_target_dir in file_copies:
        run_command(["scp", str(source_path), f"{target}:{remote_target_dir}"], dry_run=args.dry_run)
    for source_path, remote_target_dir in directory_copies:
        run_command(["scp", "-r", str(source_path), f"{target}:{remote_target_dir}"], dry_run=args.dry_run)

    permission_targets = [f"{remote_dir}/config"]
    if secrets_mqtt_dir.exists():
        permission_targets.append(f"{remote_root}/secrets/mqtt")
    run_command(["ssh", target, "chmod -R a+rX " + " ".join(remote_shell_path(item) for item in permission_targets)], dry_run=args.dry_run)


def remote_cleanup_command(remote_dir: str) -> str:
    remote_path = remote_shell_path(remote_dir)
    return (
        f"docker run --rm -v {remote_path}:/work --entrypoint sh eclipse-mosquitto:2.0 "
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
    if getattr(args, "certificate_profile", None):
        env.append(f"MQTT_CERTIFICATE_PROFILE={args.certificate_profile}")
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
    compose_remote(
        args,
        [
            "--profile",
            "classical",
            "--profile",
            "classical-server-auth",
            "--profile",
            "oqs",
            "down",
            "--remove-orphans",
        ],
    )
    host = load_host_config(repo_root() / args.host_config)
    cleanup_command = (
        "docker rm -f pqc-mqtt-classical pqc-mqtt-classical-server-auth "
        "pqc-mqtt-oqs >/dev/null 2>&1 || true"
    )
    run_command(["ssh", ssh_target(host), cleanup_command], dry_run=args.dry_run)


def status(args: argparse.Namespace) -> None:
    compose_remote(args, ["ps"])


def logs(args: argparse.Namespace) -> None:
    service = BROKER_PROFILE_SERVICES[args.profile]
    compose_remote(args, ["logs", "--tail", str(args.tail), service])


def validate_oqs_tls(args: argparse.Namespace) -> None:
    host = load_host_config(repo_root() / args.host_config)
    target = ssh_target(host)
    cert_dir = f"{remote_repo_root(args.remote_dir)}/secrets/mqtt/{args.certificate_profile}"
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
    host = load_host_config(repo_root() / args.host_config)
    target = ssh_target(host)
    cert_dir = f"{remote_repo_root(args.remote_dir)}/secrets/mqtt/{certificate_profile}"
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
            f"-e OPENSSL_MODULES=/opt/oqssa/lib64/ossl-modules "
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
        certificate_profile=args.certificate_profile or "stepca-classical",
        port=args.classical_port or 8883,
        image=args.image,
        mutual_tls=True,
    )


def validate_classical_server_auth_mqtt(args: argparse.Namespace) -> None:
    """Validate the classical server-authentication-only broker profile."""
    validate_mqtt_pubsub(
        args,
        profile="classical-server-auth",
        certificate_profile=args.certificate_profile or "stepca-classical",
        port=args.classical_port or 8883,
        image=args.image,
        mutual_tls=False,
    )


def validate_oqs_mqtt(args: argparse.Namespace) -> None:
    """Validate hybrid key exchange with classical server authentication."""
    validate_mqtt_pubsub(
        args,
        profile="oqs",
        certificate_profile=args.certificate_profile or "stepca-classical",
        port=args.oqs_port or 8884,
        image=args.image,
        mutual_tls=False,
        oqs_client=True,
    )


def add_common_remote_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--certificate-profile", help="resolved MQTT certificate profile under secrets/mqtt")
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

    provision = sub.add_parser("provision-certs", help="synchronize classical MQTT TLS material from framework/certs")
    provision.add_argument("--certificate-profile", default="stepca-classical")
    provision.add_argument("--server-name", default=DEFAULT_SERVER_NAME)
    provision.add_argument("--extra-dns-name", action="append")
    provision.add_argument("--extra-ip-address", action="append")
    provision.add_argument("--host-config", default=str(DEFAULT_HOST_CONFIG), help="include host-config network.address as an IP SAN when present")
    provision.add_argument("--client-name", default=DEFAULT_CLIENT_NAME)
    provision.add_argument("--healthcheck-name", default=DEFAULT_HEALTHCHECK_NAME)
    provision.add_argument("--days", type=int, default=365)
    provision.add_argument("--dry-run", action="store_true")
    provision.set_defaults(func=sync_stepca_certs)

    oqs_provision = sub.add_parser(
        "provision-oqs-certs",
        help="deprecated alias for provision-certs; synchronizes the same classical step-ca identity material",
    )
    oqs_provision.add_argument("--certificate-profile", default="stepca-classical")
    oqs_provision.add_argument("--dry-run", action="store_true")
    oqs_provision.set_defaults(func=sync_stepca_certs)

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
    status_parser.set_defaults(func=status)

    logs_parser = sub.add_parser("logs", help="show gateway broker logs")
    add_common_remote_options(logs_parser)
    add_port_options(logs_parser)
    logs_parser.add_argument("--profile", choices=BROKER_PROFILES, default="classical")
    logs_parser.add_argument("--tail", type=int, default=100)
    logs_parser.set_defaults(func=logs)

    validate_oqs = sub.add_parser("validate-oqs-tls", help="validate remote OQS server-authenticated hybrid TLS handshake using an OQS-enabled OpenSSL client container")
    add_common_remote_options(validate_oqs)
    add_port_options(validate_oqs)
    validate_oqs.set_defaults(certificate_profile="stepca-classical")
    validate_oqs.add_argument("--oqs-group", default=OQS_KEM_GROUP)
    validate_oqs.add_argument("--image", default=OQS_IMAGE)
    validate_oqs.set_defaults(func=validate_oqs_tls)


    validate_classical_server_auth_parser = sub.add_parser(
        "validate-classical-server-auth-mqtt",
        help="validate classical TLS 1.3 server-authenticated MQTT publish/subscribe without a client certificate",
    )
    add_common_remote_options(validate_classical_server_auth_parser)
    add_port_options(validate_classical_server_auth_parser)
    validate_classical_server_auth_parser.set_defaults(certificate_profile="stepca-classical")
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
    validate_classical_mqtt_parser.set_defaults(certificate_profile="stepca-classical")
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
    validate_oqs_mqtt_parser.set_defaults(certificate_profile="stepca-classical")
    validate_oqs_mqtt_parser.add_argument("--image", default=OQS_IMAGE)
    validate_oqs_mqtt_parser.add_argument("--topic", default="pqc/test/e2e")
    validate_oqs_mqtt_parser.add_argument("--message", default="pqc-oqs-mqtt-e2e")
    validate_oqs_mqtt_parser.set_defaults(func=validate_oqs_mqtt)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
