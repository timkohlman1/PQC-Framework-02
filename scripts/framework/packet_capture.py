"""Gateway packet-capture lifecycle for IP-networked firmware experiments."""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from framework.uart import CommandExecution
from framework.ssh_target import gateway_ssh_target

MAC_ADDRESS_PATTERN = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
PACKET_CAPTURE_ARTIFACT_NAME = "gateway-network-capture.pcap"
PACKET_CAPTURE_LOG_NAME = "gateway-network-capture.log"


@dataclass(frozen=True)
class GatewayPacketCapture:
    """Identity and resolved settings for one remote packet-capture process."""

    gateway_alias: str
    gateway_target: str
    remote_capture_path: str
    remote_log_path: str
    pid: int
    interface: str
    capture_filter: str | None
    stm32_mac_address: str | None
    started_at_epoch_seconds: float


@dataclass(frozen=True)
class GatewayPacketCaptureResult:
    """Collected packet-capture artifact and lifecycle evidence."""

    return_code: int
    artifact_path: Path | None
    log_path: Path
    sha256: str | None
    size_bytes: int | None
    stop: CommandExecution
    copy: CommandExecution
    failure_reason: str | None


def _run(command: list[str], *, cwd: Path) -> CommandExecution:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return CommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=time.perf_counter() - started,
    )


def packet_capture_config(bundle: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Resolve packet-capture settings for an experiment with an IP network block."""

    network = bundle.get("experiment", {}).get("network")
    if not isinstance(network, dict):
        return None
    configured = network.get("packet_capture", {})
    if configured is None:
        configured = {}
    if not isinstance(configured, dict):
        raise ValueError("network.packet_capture must be a mapping")
    enabled = configured.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("network.packet_capture.enabled must be a boolean")
    if not enabled:
        return None

    interface = str(configured.get("interface", "any")).strip()
    if not interface or any(character.isspace() for character in interface):
        raise ValueError("network.packet_capture.interface must be a non-empty interface name")

    mac_value = configured.get("stm32_mac_address")
    mac_address = None if mac_value is None else str(mac_value).strip().lower()
    if mac_address and not MAC_ADDRESS_PATTERN.fullmatch(mac_address):
        raise ValueError(
            "network.packet_capture.stm32_mac_address must use six colon-separated hexadecimal octets"
        )

    base_filter = f"ether host {mac_address}" if mac_address else None
    reporting_port = 1886
    capture_filter = (
        f"({base_filter}) and not port {reporting_port}"
        if base_filter
        else f"not port {reporting_port}"
    )
    return {
        "interface": interface,
        "stm32_mac_address": mac_address or None,
        "capture_filter": capture_filter,
        "reporting_port_excluded": reporting_port,
    }


def start_gateway_packet_capture(
    *,
    bundle: dict[str, dict[str, Any]],
    repo_root: Path,
    run_id: str,
    runner: Callable[[list[str], Path], CommandExecution] = _run,
) -> tuple[GatewayPacketCapture | None, CommandExecution | None]:
    """Start tcpdump on the gateway before firmware network activity begins."""

    config = packet_capture_config(bundle)
    if config is None:
        return None, None

    gateway_alias = str(bundle["host"]["alias"])
    gateway_target = gateway_ssh_target(bundle["host"])
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)
    remote_capture_path = f"/tmp/pqc-{safe_run_id}-gateway-network-capture.pcap"
    remote_log_path = f"/tmp/pqc-{safe_run_id}-gateway-network-capture.log"
    interface = str(config["interface"])
    capture_filter = config["capture_filter"]

    tcpdump_parts = [
        "tcpdump",
        "-i",
        interface,
        "-U",
        "-s",
        "0",
        "-w",
        remote_capture_path,
    ]
    if capture_filter:
        tcpdump_parts.append(str(capture_filter))
    tcpdump_command = shlex.join(tcpdump_parts)
    script = (
        "command -v tcpdump >/dev/null 2>&1 || { echo 'tcpdump is not installed' >&2; exit 127; }; "
        f"rm -f {shlex.quote(remote_capture_path)} {shlex.quote(remote_log_path)}; "
        f"nohup {tcpdump_command} >{shlex.quote(remote_log_path)} 2>&1 </dev/null & "
        "capture_pid=$!; sleep 1; "
        "kill -0 \"$capture_pid\" 2>/dev/null || { cat "
        f"{shlex.quote(remote_log_path)} >&2 2>/dev/null || true; exit 1; }}; "
        "printf '%s\\n' \"$capture_pid\""
    )
    command = ["ssh", gateway_target, f"sh -c {shlex.quote(script)}"]
    execution = runner(command, cwd=repo_root)
    if execution.return_code != 0:
        return None, execution
    try:
        pid = int(execution.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        invalid = CommandExecution(
            command=execution.command,
            return_code=1,
            stdout=execution.stdout,
            stderr=execution.stderr + "\nPacket capture start did not return a valid process ID.\n",
            duration_seconds=execution.duration_seconds,
        )
        return None, invalid

    return GatewayPacketCapture(
        gateway_alias=gateway_alias,
        gateway_target=gateway_target,
        remote_capture_path=remote_capture_path,
        remote_log_path=remote_log_path,
        pid=pid,
        interface=interface,
        capture_filter=capture_filter,
        stm32_mac_address=config["stm32_mac_address"],
        started_at_epoch_seconds=time.time(),
    ), execution


def stop_and_collect_gateway_packet_capture(
    *,
    capture: GatewayPacketCapture,
    repo_root: Path,
    result_dir: Path,
    runner: Callable[[list[str], Path], CommandExecution] = _run,
) -> GatewayPacketCaptureResult:
    """Stop only the owned tcpdump process and copy its pcap and diagnostic log."""

    stop_script = (
        f"capture_pid={capture.pid}; "
        "if kill -0 \"$capture_pid\" 2>/dev/null; then kill -INT \"$capture_pid\" 2>/dev/null || true; fi; "
        "attempts=0; while kill -0 \"$capture_pid\" 2>/dev/null && [ \"$attempts\" -lt 20 ]; do "
        "sleep 0.25; attempts=$((attempts + 1)); done; "
        "if kill -0 \"$capture_pid\" 2>/dev/null; then kill -TERM \"$capture_pid\" 2>/dev/null || true; fi; "
        f"test -f {shlex.quote(capture.remote_capture_path)}"
    )
    stop_command = ["ssh", capture.gateway_target, f"sh -c {shlex.quote(stop_script)}"]
    stop_execution = runner(stop_command, cwd=repo_root)

    artifact_path = result_dir / PACKET_CAPTURE_ARTIFACT_NAME
    copy_command = [
        "scp",
        f"{capture.gateway_target}:{capture.remote_capture_path}",
        str(artifact_path),
    ]
    copy_execution = runner(copy_command, cwd=repo_root)

    log_path = result_dir / PACKET_CAPTURE_LOG_NAME
    remote_log_command = [
        "ssh",
        capture.gateway_target,
        f"cat {shlex.quote(capture.remote_log_path)} 2>/dev/null || true",
    ]
    remote_log = runner(remote_log_command, cwd=repo_root)
    log_path.write_text(
        "Stop command: " + shlex.join(stop_command) + "\n"
        + f"Stop return code: {stop_execution.return_code}\n\n"
        + "Copy command: " + shlex.join(copy_command) + "\n"
        + f"Copy return code: {copy_execution.return_code}\n\n"
        + "tcpdump output:\n"
        + remote_log.stdout
        + remote_log.stderr,
        encoding="utf-8",
    )

    cleanup_script = (
        f"rm -f {shlex.quote(capture.remote_capture_path)} {shlex.quote(capture.remote_log_path)}"
    )
    runner(["ssh", capture.gateway_target, f"sh -c {shlex.quote(cleanup_script)}"], cwd=repo_root)

    if stop_execution.return_code != 0:
        failure_reason = "packet capture could not be stopped cleanly or the remote capture file was missing"
    elif copy_execution.return_code != 0:
        failure_reason = "packet capture artifact could not be copied from the gateway"
    elif not artifact_path.is_file() or artifact_path.stat().st_size == 0:
        failure_reason = "packet capture artifact is missing or empty"
    else:
        failure_reason = None

    sha256 = None
    size_bytes = None
    if failure_reason is None:
        payload = artifact_path.read_bytes()
        sha256 = hashlib.sha256(payload).hexdigest()
        size_bytes = len(payload)

    return GatewayPacketCaptureResult(
        return_code=0 if failure_reason is None else 1,
        artifact_path=artifact_path if artifact_path.exists() else None,
        log_path=log_path,
        sha256=sha256,
        size_bytes=size_bytes,
        stop=stop_execution,
        copy=copy_execution,
        failure_reason=failure_reason,
    )
