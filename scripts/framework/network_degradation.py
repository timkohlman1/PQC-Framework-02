"""Gateway-controlled network degradation for STM32 MQTT experiments.

The impairment is applied only to an explicitly configured experiment-facing
interface.  Egress and ingress use separate netem instances so packet loss is
sampled independently in each direction.  Requested RTT is split evenly across
the two directions.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from framework.uart import CommandExecution
from framework.ssh_target import gateway_ssh_target

NETWORK_DEGRADATION_LOG_NAME = "gateway-network-degradation.log"


def _remote_command_resolution_script() -> str:
    return (
        "resolve_cmd() { "
        "name=$1; found=$(command -v \"$name\" 2>/dev/null || true); "
        "if [ -n \"$found\" ]; then printf \"%s\" \"$found\"; return 0; fi; "
        "for candidate in /usr/sbin/$name /usr/bin/$name /sbin/$name /bin/$name; do "
        "if [ -x \"$candidate\" ]; then printf \"%s\" \"$candidate\"; return 0; fi; done; "
        "return 1; }; "
        "TC=$(resolve_cmd tc) || { echo PQC_NETDEG_ERROR=missing_tc; exit 127; }; "
        "IP=$(resolve_cmd ip) || { echo PQC_NETDEG_ERROR=missing_ip; exit 127; }; "
        "MODPROBE=$(resolve_cmd modprobe) || { echo PQC_NETDEG_ERROR=missing_modprobe; exit 127; }; "
        "echo PQC_TC_PATH=$TC; echo PQC_IP_PATH=$IP; echo PQC_MODPROBE_PATH=$MODPROBE; "
    )


def gateway_network_degradation_preflight_script(interface: str) -> str:
    iface = shlex.quote(interface)
    return (
        "set -eu; " + _remote_command_resolution_script()
        + f"iface={iface}; "
        + "[ -e /sys/class/net/$iface ] || { echo PQC_NETDEG_ERROR=missing_interface; exit 2; }; "
        + "sudo -n \"$TC\" qdisc show dev $iface >/dev/null 2>&1 || { echo PQC_NETDEG_ERROR=sudo_tc_required; exit 126; }; "
        + "sudo -n \"$IP\" link show dev $iface >/dev/null 2>&1 || { echo PQC_NETDEG_ERROR=sudo_ip_required; exit 126; }; "
        + "sudo -n \"$MODPROBE\" -n ifb >/dev/null 2>&1 || { echo PQC_NETDEG_ERROR=sudo_modprobe_required; exit 126; }; "
        + "echo PQC_NETDEG_PREFLIGHT=passed"
    )


@dataclass(frozen=True)
class NetworkDegradationConfig:
    interface: str
    ifb_interface: str
    rate_kbit: int
    rtt_ms: int
    loss_percent: float
    mtu: int
    management_safe: bool

    @property
    def one_way_delay_ms(self) -> float:
        return self.rtt_ms / 2.0


@dataclass(frozen=True)
class GatewayNetworkDegradation:
    gateway_alias: str
    gateway_target: str
    config: NetworkDegradationConfig
    original_mtu: int
    apply: CommandExecution
    log_path: Path


@dataclass(frozen=True)
class GatewayNetworkDegradationResult:
    return_code: int
    cleanup: CommandExecution
    log_path: Path
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


def network_degradation_config(bundle: dict[str, dict[str, Any]]) -> NetworkDegradationConfig | None:
    network = bundle.get("experiment", {}).get("network")
    if not isinstance(network, dict):
        return None
    raw = network.get("degradation")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("network.degradation must be a mapping")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("network.degradation.enabled must be a boolean")
    if not enabled:
        return None

    interface = str(raw.get("interface", "")).strip()
    if not interface or any(character.isspace() for character in interface):
        raise ValueError("network.degradation.interface must be a non-empty interface name")
    ifb_interface = str(raw.get("ifb_interface", "ifb-pqc0")).strip()
    if not ifb_interface or any(character.isspace() for character in ifb_interface):
        raise ValueError("network.degradation.ifb_interface must be a non-empty interface name")

    rate_kbit = raw.get("rate_kbit")
    rtt_ms = raw.get("rtt_ms")
    loss_percent = raw.get("loss_percent")
    mtu = raw.get("mtu")
    management_safe = raw.get("management_safe", False)

    if not isinstance(rate_kbit, int) or isinstance(rate_kbit, bool) or rate_kbit <= 0:
        raise ValueError("network.degradation.rate_kbit must be a positive integer")
    if not isinstance(rtt_ms, int) or isinstance(rtt_ms, bool) or rtt_ms < 0:
        raise ValueError("network.degradation.rtt_ms must be a non-negative integer")
    if not isinstance(loss_percent, (int, float)) or isinstance(loss_percent, bool):
        raise ValueError("network.degradation.loss_percent must be numeric")
    if not 0 <= float(loss_percent) <= 100:
        raise ValueError("network.degradation.loss_percent must be between 0 and 100")
    if not isinstance(mtu, int) or isinstance(mtu, bool) or mtu < 576 or mtu > 9000:
        raise ValueError("network.degradation.mtu must be an integer between 576 and 9000")
    if management_safe is not True:
        raise ValueError(
            "network.degradation.management_safe must be true to acknowledge that the configured interface is not the SSH/VPN control path"
        )

    return NetworkDegradationConfig(
        interface=interface,
        ifb_interface=ifb_interface,
        rate_kbit=rate_kbit,
        rtt_ms=rtt_ms,
        loss_percent=float(loss_percent),
        mtu=mtu,
        management_safe=True,
    )


def _remote_script(config: NetworkDegradationConfig) -> str:
    delay = f"{config.one_way_delay_ms:g}ms"
    loss = f"{config.loss_percent:g}%"
    rate = f"{config.rate_kbit}kbit"
    interface = shlex.quote(config.interface)
    ifb = shlex.quote(config.ifb_interface)
    return (
        "set -eu; " + _remote_command_resolution_script()
        + f"iface={interface}; ifb={ifb}; "
        + "original_mtu=$(cat /sys/class/net/$iface/mtu); echo PQC_ORIGINAL_MTU=$original_mtu; "
        + "sudo -n \"$MODPROBE\" ifb numifbs=1 >/dev/null 2>&1 || true; "
        + "sudo -n \"$IP\" link add $ifb type ifb 2>/dev/null || true; "
        + "sudo -n \"$IP\" link set dev $ifb up; "
        + "sudo -n \"$TC\" qdisc del dev $iface root 2>/dev/null || true; "
        + "sudo -n \"$TC\" qdisc del dev $iface ingress 2>/dev/null || true; "
        + "sudo -n \"$TC\" qdisc del dev $ifb root 2>/dev/null || true; "
        + f"sudo -n \"$IP\" link set dev $iface mtu {config.mtu}; "
        + f"sudo -n \"$TC\" qdisc add dev $iface root netem delay {delay} loss {loss} rate {rate}; "
        + "sudo -n \"$TC\" qdisc add dev $iface handle ffff: ingress; "
        + "sudo -n \"$TC\" filter add dev $iface parent ffff: protocol all u32 match u32 0 0 action mirred egress redirect dev $ifb; "
        + f"sudo -n \"$TC\" qdisc add dev $ifb root netem delay {delay} loss {loss} rate {rate}; "
        + "echo PQC_APPLIED_STATE_BEGIN; "
        + "\"$IP\" -details link show dev $iface; \"$TC\" -s qdisc show dev $iface; \"$TC\" -s qdisc show dev $ifb; "
        + "echo PQC_APPLIED_STATE_END"
    )


def apply_gateway_network_degradation(
    *,
    bundle: dict[str, dict[str, Any]],
    repo_root: Path,
    result_dir: Path,
    runner: Callable[[list[str], Path], CommandExecution] = _run,
) -> tuple[GatewayNetworkDegradation | None, CommandExecution | None]:
    config = network_degradation_config(bundle)
    if config is None:
        return None, None
    gateway_alias = str(bundle["host"]["alias"])
    gateway_target = gateway_ssh_target(bundle["host"])
    command = ["ssh", gateway_target, f"sh -c {shlex.quote(_remote_script(config))}"]
    execution = runner(command, cwd=repo_root)
    log_path = result_dir / NETWORK_DEGRADATION_LOG_NAME
    log_path.write_text(
        "Apply command: " + shlex.join(command) + "\n"
        + f"Return code: {execution.return_code}\n\n"
        + execution.stdout
        + execution.stderr,
        encoding="utf-8",
    )
    if execution.return_code != 0:
        return None, execution
    original_mtu = None
    for line in execution.stdout.splitlines():
        if line.startswith("PQC_ORIGINAL_MTU="):
            try:
                original_mtu = int(line.split("=", 1)[1])
            except ValueError:
                pass
    if original_mtu is None:
        invalid = CommandExecution(
            command=execution.command,
            return_code=1,
            stdout=execution.stdout,
            stderr=execution.stderr + "\nNetwork degradation apply did not report the original MTU.\n",
            duration_seconds=execution.duration_seconds,
        )
        return None, invalid
    return GatewayNetworkDegradation(
        gateway_alias=gateway_alias,
        gateway_target=gateway_target,
        config=config,
        original_mtu=original_mtu,
        apply=execution,
        log_path=log_path,
    ), execution


def remove_gateway_network_degradation(
    *,
    degradation: GatewayNetworkDegradation,
    repo_root: Path,
    runner: Callable[[list[str], Path], CommandExecution] = _run,
) -> GatewayNetworkDegradationResult:
    config = degradation.config
    script = (
        "set +e; " + _remote_command_resolution_script()
        + f"iface={shlex.quote(config.interface)}; ifb={shlex.quote(config.ifb_interface)}; "
        + "sudo -n \"$TC\" qdisc del dev $iface root 2>/dev/null; "
        + "sudo -n \"$TC\" qdisc del dev $iface ingress 2>/dev/null; "
        + "sudo -n \"$TC\" qdisc del dev $ifb root 2>/dev/null; "
        + f"sudo -n \"$IP\" link set dev $iface mtu {degradation.original_mtu}; "
        + "sudo -n \"$IP\" link set dev $ifb down 2>/dev/null; "
        + "sudo -n \"$IP\" link del dev $ifb type ifb 2>/dev/null; "
        + "actual_mtu=$(cat /sys/class/net/$iface/mtu 2>/dev/null); "
        + f"[ \"$actual_mtu\" = \"{degradation.original_mtu}\" ]"
    )
    command = ["ssh", degradation.gateway_target, f"sh -c {shlex.quote(script)}"]
    execution = runner(command, cwd=repo_root)
    with degradation.log_path.open("a", encoding="utf-8") as stream:
        stream.write("\nCleanup command: " + shlex.join(command) + "\n")
        stream.write(f"Cleanup return code: {execution.return_code}\n\n")
        stream.write(execution.stdout)
        stream.write(execution.stderr)
    failure_reason = None if execution.return_code == 0 else "network degradation cleanup or MTU restoration failed"
    return GatewayNetworkDegradationResult(
        return_code=execution.return_code,
        cleanup=execution,
        log_path=degradation.log_path,
        failure_reason=failure_reason,
    )


def degradation_manifest(config: NetworkDegradationConfig) -> dict[str, Any]:
    return {
        "enabled": True,
        "interface": config.interface,
        "ifb_interface": config.ifb_interface,
        "rate_kbit": config.rate_kbit,
        "rtt_ms": config.rtt_ms,
        "one_way_delay_ms": config.one_way_delay_ms,
        "loss_percent": config.loss_percent,
        "loss_model": "independent_per_direction_netem",
        "mtu": config.mtu,
        "management_safe_acknowledged": config.management_safe,
    }
