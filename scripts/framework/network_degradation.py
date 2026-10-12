"""Impair only the experiment broker's Docker veth data plane.

The gateway's physical/control interfaces and the reporting-broker veth are never
modified. Egress and ingress use distinct netem instances; requested RTT is
split evenly and loss is sampled independently per direction. MTU is changed
only on the experiment broker veth pair.
"""
from __future__ import annotations

import re, shlex, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from framework.bounded_command import run as bounded_run
from framework.uart import CommandExecution
from framework.ssh_target import gateway_ssh_target

NETWORK_DEGRADATION_LOG_NAME="gateway-network-degradation.log"
BROKER_SERVICE_BY_PROFILE={"classical":"mqtt-classical","classical-server-auth":"mqtt-classical-server-auth","oqs":"mqtt-oqs","oqs-mtls":"mqtt-oqs-mtls"}

def _remote_command_resolution_script()->str:
    return (
      'resolve_cmd() { name=$1; found=$(command -v "$name" 2>/dev/null || true); if [ -n "$found" ]; then printf "%s" "$found"; return 0; fi; '
      'for candidate in /usr/sbin/$name /usr/bin/$name /sbin/$name /bin/$name; do if [ -x "$candidate" ]; then printf "%s" "$candidate"; return 0; fi; done; return 1; }; '
      'TC=$(resolve_cmd tc) || { echo PQC_NETDEG_ERROR=missing_tc; exit 127; }; '
      'IP=$(resolve_cmd ip) || { echo PQC_NETDEG_ERROR=missing_ip; exit 127; }; '
      'MODPROBE=$(resolve_cmd modprobe) || { echo PQC_NETDEG_ERROR=missing_modprobe; exit 127; }; '
      'DOCKER=$(resolve_cmd docker) || { echo PQC_NETDEG_ERROR=missing_docker; exit 127; }; '
      'NSENTER=$(resolve_cmd nsenter) || { echo PQC_NETDEG_ERROR=missing_nsenter; exit 127; }; '
      'echo PQC_TC_PATH=$TC; echo PQC_IP_PATH=$IP; echo PQC_MODPROBE_PATH=$MODPROBE; echo PQC_DOCKER_PATH=$DOCKER; echo PQC_NSENTER_PATH=$NSENTER; '
    )

def gateway_network_degradation_preflight_script(interface: str)->str:
    # interface is retained for compatibility/provenance only; it is deliberately
    # not modified by Request 15.
    return ('set -eu; '+_remote_command_resolution_script()+
      f'physical_iface={shlex.quote(interface)}; [ -e /sys/class/net/$physical_iface ] || {{ echo PQC_NETDEG_ERROR=missing_interface; exit 2; }}; '
      'sudo -n "$TC" qdisc show dev $physical_iface >/dev/null 2>&1 || { echo PQC_NETDEG_ERROR=sudo_tc_required; exit 126; }; '
      'sudo -n "$IP" link show dev $physical_iface >/dev/null 2>&1 || { echo PQC_NETDEG_ERROR=sudo_ip_required; exit 126; }; '
      'sudo -n "$MODPROBE" -n ifb >/dev/null 2>&1 || { echo PQC_NETDEG_ERROR=sudo_modprobe_required; exit 126; }; '
      'sudo -n "$NSENTER" --help >/dev/null 2>&1 || { echo PQC_NETDEG_ERROR=sudo_nsenter_required; exit 126; }; echo PQC_NETDEG_PREFLIGHT=passed')

@dataclass(frozen=True)
class NetworkDegradationConfig:
    interface:str; ifb_interface:str; rate_kbit:int; rtt_ms:int; loss_percent:float; mtu:int; management_safe:bool; broker_service:str
    @property
    def one_way_delay_ms(self)->float:return self.rtt_ms/2.0

@dataclass(frozen=True)
class GatewayNetworkDegradation:
    gateway_alias:str; gateway_target:str; config:NetworkDegradationConfig; original_mtu:int; container_original_mtu:int; resolved_interface:str; container_pid:int; apply:CommandExecution; log_path:Path

@dataclass(frozen=True)
class GatewayNetworkDegradationResult:
    return_code:int; cleanup:CommandExecution; log_path:Path; failure_reason:str|None

def _run(command:list[str],*,cwd:Path)->CommandExecution:
    started=time.perf_counter(); c=bounded_run(command,cwd=cwd)
    return CommandExecution(command,c.returncode,c.stdout,c.stderr,time.perf_counter()-started)

def network_degradation_config(bundle:dict[str,dict[str,Any]])->NetworkDegradationConfig|None:
    network=bundle.get('experiment',{}).get('network'); raw=network.get('degradation') if isinstance(network,dict) else None
    if raw is None:return None
    if not isinstance(raw,dict):raise ValueError('network.degradation must be a mapping')
    if raw.get('enabled',False) is False:return None
    interface = str(raw.get('interface', '')).strip()
    if not interface:
        raise ValueError('network.degradation.interface must be non-empty')
    ifb = str(raw.get('ifb_interface', 'ifb-pqc0')).strip()
    rate = raw.get('rate_kbit')
    rtt = raw.get('rtt_ms')
    loss = raw.get('loss_percent')
    mtu = raw.get('mtu')
    safe = raw.get('management_safe', False)
    if not isinstance(rate,int) or isinstance(rate,bool) or rate<=0:raise ValueError('network.degradation.rate_kbit must be a positive integer')
    if not isinstance(rtt,int) or isinstance(rtt,bool) or rtt<0:raise ValueError('network.degradation.rtt_ms must be a non-negative integer')
    if not isinstance(loss,(int,float)) or isinstance(loss,bool) or not 0<=float(loss)<=100:raise ValueError('network.degradation.loss_percent must be between 0 and 100')
    if not isinstance(mtu,int) or isinstance(mtu,bool) or not 400<=mtu<=9000:raise ValueError('network.degradation.mtu must be an integer between 400 and 9000')
    if safe is not True:raise ValueError('network.degradation.management_safe must be true')
    profile=str(bundle.get('experiment',{}).get('mqtt',{}).get('broker_profile','classical'))
    service=BROKER_SERVICE_BY_PROFILE.get(profile)
    if service is None:raise ValueError(f'unsupported experiment broker profile for isolated impairment: {profile}')
    return NetworkDegradationConfig(interface,ifb,rate,rtt,float(loss),mtu,True,service)

def _resolve_veth_script(config:NetworkDegradationConfig)->str:
    service=shlex.quote(config.broker_service)
    return (
      f'service={service}; compose=$HOME/pqc-framework-02/experiment/mqtt-broker/compose.yaml; '
      'cid=$("$DOCKER" compose -p pqc-framework-mqtt-broker -f "$compose" ps -q "$service"); [ -n "$cid" ] || { echo PQC_NETDEG_ERROR=broker_container_not_running; exit 3; }; '
      'pid=$("$DOCKER" inspect -f "{{.State.Pid}}" "$cid"); [ "$pid" -gt 0 ] || exit 3; '
      'container_iface=eth0; container_link=$(sudo -n "$NSENTER" -t "$pid" -n "$IP" -o link show dev "$container_iface"); '
      'peer_index=$(printf "%s\\n" "$container_link" | sed -n "s/.*@if\\([0-9][0-9]*\\):.*/\\1/p"); '
      '[ -n "$peer_index" ] || { echo PQC_NETDEG_ERROR=container_peer_index_not_found; exit 3; }; '
      'container_mtu=$(printf "%s\\n" "$container_link" | sed -n "s/.* mtu \\([0-9][0-9]*\\) .*/\\1/p"); '
      '[ -n "$container_mtu" ] || { echo PQC_NETDEG_ERROR=container_mtu_not_found; exit 3; }; '
      'iface=$("$IP" -o link show | grep "^$peer_index:" | cut -d: -f2 | cut -d@ -f1 | xargs); '
      '[ -n "$iface" ] || { echo PQC_NETDEG_ERROR=veth_not_found; exit 3; }; '
      'reporting_cid=$("$DOCKER" compose -p pqc-framework-mqtt-broker -f "$compose" ps -q mqtt-reporting); '
      '[ -n "$reporting_cid" ] || { echo PQC_NETDEG_ERROR=reporting_broker_not_running; exit 3; }; '
      'reporting_pid=$("$DOCKER" inspect -f "{{.State.Pid}}" "$reporting_cid"); '
      '[ "$reporting_pid" -gt 0 ] || { echo PQC_NETDEG_ERROR=reporting_broker_invalid_pid; exit 3; }; '
      'reporting_link=$(sudo -n "$NSENTER" -t "$reporting_pid" -n "$IP" -o link show dev eth0); '
      'reporting_peer_index=$(printf "%s\\n" "$reporting_link" | sed -n "s/.*@if\\([0-9][0-9]*\\):.*/\\1/p"); '
      '[ -n "$reporting_peer_index" ] && [ "$reporting_peer_index" != "$peer_index" ] || { echo PQC_NETDEG_ERROR=reporting_interface_not_isolated; exit 3; }; '
      'echo PQC_REPORTING_PEER_INDEX=$reporting_peer_index; echo PQC_EXPERIMENT_PEER_INDEX=$peer_index; echo PQC_EXPERIMENT_VETH=$iface; echo PQC_EXPERIMENT_CONTAINER_IFACE=$container_iface; echo PQC_EXPERIMENT_CONTAINER_PID=$pid; '
    )

def _gateway_state_commands() -> str:
    """Read both qdiscs, the ingress filter and both experiment-veth MTUs."""
    return (
        'echo PQC_APPLIED_STATE_BEGIN; '
        '"$IP" -details link show dev "$iface"; '
        'echo PQC_VETH_QDISC_BEGIN; "$TC" -s qdisc show dev "$iface"; echo PQC_VETH_QDISC_END; '
        'echo PQC_IFB_QDISC_BEGIN; "$TC" -s qdisc show dev "$ifb"; echo PQC_IFB_QDISC_END; '
        'echo PQC_INGRESS_FILTER_BEGIN; "$TC" -s filter show dev "$iface" parent ffff:; echo PQC_INGRESS_FILTER_END; '
        'sudo -n "$NSENTER" -t "$pid" -n "$IP" -details link show dev eth0; '
        'echo PQC_APPLIED_STATE_END; '
    )


def _remote_script(config:NetworkDegradationConfig)->str:
    """Fail closed on occupied resources; rollback partial application in the gateway shell."""
    delay=f'{config.one_way_delay_ms:g}ms'; loss=f'{config.loss_percent:g}%'; rate=f'{config.rate_kbit}kbit'; ifb=shlex.quote(config.ifb_interface)
    return ('set -eu; '+_remote_command_resolution_script()+_resolve_veth_script(config)+f'ifb={ifb}; '
      'original_mtu=$(cat /sys/class/net/$iface/mtu); container_original_mtu=$container_mtu; echo PQC_ORIGINAL_MTU=$original_mtu; echo PQC_CONTAINER_ORIGINAL_MTU=$container_original_mtu; '
      # Existing shaping is not ours to discard or reconstruct.
      'initial_qdisc=$("$TC" qdisc show dev "$iface"); '
      'if printf "%s\\n" "$initial_qdisc" | grep "^qdisc " | grep -Ev "^qdisc noqueue " >/dev/null; then echo PQC_NETDEG_ERROR=occupied_veth_qdisc; exit 4; fi; '
      'if "$IP" link show dev "$ifb" >/dev/null 2>&1; then echo PQC_NETDEG_ERROR=occupied_ifb; exit 4; fi; '
      'touched=0; applied=0; trap \'exit 129\' HUP; trap \'exit 130\' INT; trap \'exit 143\' TERM; '
      'rollback() { rc=$?; trap - EXIT; if [ "$applied" = 1 ] || [ "$touched" = 0 ]; then exit "$rc"; fi; '
      'echo PQC_ROLLBACK_BEGIN; failed=0; '
      'if "$TC" qdisc show dev "$iface" | grep -q "^qdisc netem "; then sudo -n "$TC" qdisc del dev "$iface" root || failed=1; fi; '
      'if "$TC" qdisc show dev "$iface" | grep -q "^qdisc ingress "; then sudo -n "$TC" qdisc del dev "$iface" ingress || failed=1; fi; '
      'sudo -n "$TC" qdisc del dev "$ifb" root 2>/dev/null || true; '
      'sudo -n "$IP" link set dev "$iface" mtu "$original_mtu" || failed=1; '
      'sudo -n "$NSENTER" -t "$pid" -n "$IP" link set dev eth0 mtu "$container_original_mtu" || failed=1; '
      'sudo -n "$IP" link set dev "$ifb" down 2>/dev/null || true; '
      'sudo -n "$IP" link del dev "$ifb" type ifb 2>/dev/null || failed=1; '
      '[ "$(cat /sys/class/net/$iface/mtu)" = "$original_mtu" ] || failed=1; '
      '[ ! -e /sys/class/net/$ifb ] || failed=1; '
      '[ "$(sudo -n "$NSENTER" -t "$pid" -n "$IP" -o link show dev eth0 | sed -n "s/.* mtu \\([0-9][0-9]*\\) .*/\\1/p")" = "$container_original_mtu" ] || failed=1; '
      'echo PQC_ROLLBACK_RESULT=$failed; echo PQC_ROLLBACK_END; exit 1; }; trap rollback EXIT; '
      'sudo -n "$MODPROBE" ifb numifbs=1 >/dev/null 2>&1 || true; '
      'sudo -n "$IP" link add "$ifb" type ifb; touched=1; '
      'sudo -n "$IP" link set dev "$ifb" up; '
      f'sudo -n "$IP" link set dev "$iface" mtu {config.mtu}; sudo -n "$NSENTER" -t "$pid" -n "$IP" link set dev eth0 mtu {config.mtu}; '
      f'sudo -n "$TC" qdisc add dev "$iface" root netem delay {delay} loss {loss} rate {rate}; '
      'sudo -n "$TC" qdisc add dev "$iface" handle ffff: ingress; sudo -n "$TC" filter add dev "$iface" parent ffff: protocol all u32 match u32 0 0 action mirred egress redirect dev "$ifb"; '
      f'sudo -n "$TC" qdisc add dev "$ifb" root netem delay {delay} loss {loss} rate {rate}; '
      +_gateway_state_commands()+
      'applied=1; trap - EXIT')


def _gateway_section(output: str, marker: str) -> str | None:
    begin = f"PQC_{marker}_BEGIN"
    end = f"PQC_{marker}_END"
    if output.count(begin) != 1 or output.count(end) != 1:
        return None
    return output.split(begin, 1)[1].split(end, 1)[0]


def _netem_matches(text: str, config: NetworkDegradationConfig) -> tuple[bool, str]:
    lines = [line for line in text.splitlines() if line.startswith("qdisc netem ")]
    if len(lines) != 1:
        return False, "expected exactly one netem qdisc in this direction"
    line = lines[0]
    rate = re.search(r"\brate ([0-9]+(?:\.[0-9]+)?)([kmg]?bit)\b", line, re.IGNORECASE)
    if rate is None:
        return False, f"missing effective rate in qdisc: {line}"
    rate_scale = {"bit": 0.001, "kbit": 1, "mbit": 1000, "gbit": 1_000_000}
    actual_rate_kbit = float(rate.group(1)) * rate_scale[rate.group(2).lower()]
    if abs(actual_rate_kbit - config.rate_kbit) > max(0.01, config.rate_kbit * 0.00001):
        return False, f"effective rate differs from requested rate: {line}"
    delay = re.search(r"\bdelay ([0-9]+(?:\.[0-9]+)?)(us|ms|s)\b", line, re.IGNORECASE)
    if delay is None and config.one_way_delay_ms != 0:
        return False, f"missing effective directional delay: {line}"
    if delay is not None:
        delay_scale = {"us": 0.001, "ms": 1, "s": 1000}
        actual_delay_ms = float(delay.group(1)) * delay_scale[delay.group(2).lower()]
        if abs(actual_delay_ms - config.one_way_delay_ms) > 0.001:
            return False, f"effective directional delay differs from RTT / 2: {line}"
    loss = re.search(r"\bloss ([0-9]+(?:\.[0-9]+)?)%", line, re.IGNORECASE)
    if loss is None and config.loss_percent != 0:
        return False, f"missing effective directional loss: {line}"
    if loss is not None and abs(float(loss.group(1)) - config.loss_percent) > 0.00001:
        return False, f"effective directional loss differs from requested loss: {line}"
    return True, "verified"

def _verified_state(output: str, config: NetworkDegradationConfig) -> tuple[bool, str]:
    """Accept only independently read, direction-labelled Linux state."""
    state = _gateway_section(output, "APPLIED_STATE")
    veth = _gateway_section(output, "VETH_QDISC")
    ifb = _gateway_section(output, "IFB_QDISC")
    ingress = _gateway_section(output, "INGRESS_FILTER")
    if None in (state, veth, ifb, ingress):
        return False, "missing independently captured directional gateway state"
    identities = dict(re.findall(r"(?m)^(PQC_[A-Z_]+)=([^\n]+)$", output))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", identities.get("PQC_EXPERIMENT_VETH", "")):
        return False, "experiment interface identity is missing"
    if identities.get("PQC_REPORTING_PEER_INDEX") == identities.get("PQC_EXPERIMENT_PEER_INDEX"):
        return False, "experiment and reporting interface peers are not distinct"
    link_lines = [line for line in state.splitlines() if re.search(r"\bmtu \d+\b", line)]
    if len(link_lines) != 2 or any(not re.search(rf"\bmtu {config.mtu}\b", line) for line in link_lines):
        return False, "experiment veth and container-side MTU were not independently verified"
    if "qdisc ingress " not in veth:
        return False, "ingress qdisc is not installed on the experiment interface"
    if not re.search(r"(?:redirect dev|Redirect to device)\s+" + re.escape(config.ifb_interface) + r"(?:\W|$)", ingress, re.IGNORECASE):
        return False, "IFB ingress redirection was not observed"
    for direction, detail in (("egress", veth), ("ingress IFB", ifb)):
        valid, reason = _netem_matches(detail, config)
        if not valid:
            return False, f"{direction}: {reason}"
    return True, "verified"


def _qdisc_packets(output: str, marker: str) -> int | None:
    section = _gateway_section(output, marker)
    if section is None:
        return None
    lines = section.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("qdisc netem "):
            for following in lines[i + 1:]:
                if following.startswith("qdisc "):
                    break
                packets = re.search(r"\bSent \d+ bytes (\d+) pkt\b", following)
                if packets:
                    return int(packets.group(1))
    return None


def gateway_impairment_packet_counts(output: str) -> tuple[int, int] | None:
    """Return observed egress/IFB ingress qdisc packet counters, if available."""
    egress = _qdisc_packets(output, "VETH_QDISC")
    ingress = _qdisc_packets(output, "IFB_QDISC")
    return None if egress is None or ingress is None else (egress, ingress)

def apply_gateway_network_degradation(*,bundle,repo_root:Path,result_dir:Path,runner:Callable[...,CommandExecution]=_run):
    config=network_degradation_config(bundle)
    if config is None:return None,None
    target=gateway_ssh_target(bundle['host']); command=['ssh',target,f'sh -c {shlex.quote(_remote_script(config))}']; execution=runner(command,cwd=repo_root)
    log=result_dir/NETWORK_DEGRADATION_LOG_NAME; log.write_text('Apply command: '+shlex.join(command)+'\n'+f'Return code: {execution.return_code}\n\n'+execution.stdout+execution.stderr,encoding='utf-8')
    if execution.return_code!=0:return None,execution
    values={}
    for line in execution.stdout.splitlines():
        if line.startswith('PQC_') and '=' in line: values[line.split('=',1)[0]]=line.split('=',1)[1]
    try: original=int(values['PQC_ORIGINAL_MTU']); container_original=int(values['PQC_CONTAINER_ORIGINAL_MTU']); iface=values['PQC_EXPERIMENT_VETH']; pid=int(values['PQC_EXPERIMENT_CONTAINER_PID'])
    except (KeyError,ValueError): return None,CommandExecution(execution.command,1,execution.stdout,execution.stderr+'\nmissing isolated-veth identity\n',execution.duration_seconds)
    active=GatewayNetworkDegradation(str(bundle['host']['alias']),target,config,original,container_original,iface,pid,execution,log)
    verified,reason=_verified_state(execution.stdout,config)
    if not verified:
        cleanup=remove_gateway_network_degradation(degradation=active,repo_root=repo_root,runner=runner)
        failed=CommandExecution(execution.command,1,execution.stdout,execution.stderr+'\nPQC_NETDEG_ERROR=state_verification_failed: '+reason+'; cleanup_return_code='+str(cleanup.return_code)+'\n',execution.duration_seconds)
        with log.open('a',encoding='utf-8') as f:f.write('\nState verification failed: '+reason+'\n')
        return None,failed
    return active,execution

def verify_gateway_network_degradation(
    *, degradation: GatewayNetworkDegradation, repo_root: Path,
    runner: Callable[..., CommandExecution] = _run,
) -> CommandExecution:
    """Independently inspect the live retained condition; append the raw state."""
    config = degradation.config
    script = (
        'set -eu; ' + _remote_command_resolution_script() + _resolve_veth_script(config) +
        f'ifb={shlex.quote(config.ifb_interface)}; '
        f'[ "$iface" = {shlex.quote(degradation.resolved_interface)} ] || '
        '{ echo PQC_NETDEG_ERROR=experiment_interface_changed; exit 3; }; '
        f'[ "$pid" = {degradation.container_pid} ] || '
        '{ echo PQC_NETDEG_ERROR=experiment_container_changed; exit 3; }; ' +
        _gateway_state_commands()
    )
    command = ['ssh', degradation.gateway_target, f'sh -c {shlex.quote(script)}']
    execution = runner(command, cwd=repo_root)
    verified, reason = _verified_state(execution.stdout, config) if execution.return_code == 0 else (False, 'gateway state query failed')
    if not verified:
        execution = CommandExecution(
            execution.command, execution.return_code or 1, execution.stdout,
            execution.stderr + '\nPQC_NETDEG_ERROR=retained_state_invalid: ' + reason + '\n',
            execution.duration_seconds,
        )
    with degradation.log_path.open('a', encoding='utf-8') as log:
        log.write(
            '\nRetained-state verification command: ' + shlex.join(command) +
            f'\nRetained-state verification return code: {execution.return_code}\n\n' +
            execution.stdout + execution.stderr
        )
    return execution


def remove_gateway_network_degradation(*,degradation:GatewayNetworkDegradation,repo_root:Path,runner:Callable[...,CommandExecution]=_run)->GatewayNetworkDegradationResult:
    c=degradation.config; script=('set +e; '+_remote_command_resolution_script()+f'iface={shlex.quote(degradation.resolved_interface)}; ifb={shlex.quote(c.ifb_interface)}; pid={degradation.container_pid}; '
      'sudo -n "$TC" qdisc del dev $iface root 2>/dev/null; sudo -n "$TC" qdisc del dev $iface ingress 2>/dev/null; sudo -n "$TC" qdisc del dev $ifb root 2>/dev/null; '
      f'sudo -n "$IP" link set dev $iface mtu {degradation.original_mtu}; sudo -n "$NSENTER" -t "$pid" -n "$IP" link set dev eth0 mtu {degradation.container_original_mtu} 2>/dev/null; '
      'sudo -n "$IP" link set dev $ifb down 2>/dev/null; sudo -n "$IP" link del dev $ifb type ifb 2>/dev/null; '
      'echo PQC_RESTORED_STATE_BEGIN; sudo -n "$IP" -details link show dev "$iface"; sudo -n "$NSENTER" -t "$pid" -n "$IP" -details link show dev eth0; '
      'sudo -n "$TC" qdisc show dev "$iface"; echo PQC_RESTORED_STATE_END; '
      f'actual_mtu=$(cat /sys/class/net/$iface/mtu 2>/dev/null); [ "$actual_mtu" = "{degradation.original_mtu}" ] && '
      f'[ "$(sudo -n "$NSENTER" -t "$pid" -n "$IP" -o link show dev eth0 | sed -n "s/.* mtu \\([0-9][0-9]*\\) .*/\\1/p")" = "{degradation.container_original_mtu}" ] && '
      '[ ! -e /sys/class/net/$ifb ] && '
      'qdiscs=$(sudo -n "$TC" qdisc show dev "$iface") || exit 1; '
      '! printf "%s\\n" "$qdiscs" | grep -Eq "^qdisc (netem|ingress) "')
    command=['ssh',degradation.gateway_target,f'sh -c {shlex.quote(script)}']; execution=runner(command,cwd=repo_root)
    with degradation.log_path.open('a',encoding='utf-8') as f:f.write('\nCleanup command: '+shlex.join(command)+'\n'+f'Cleanup return code: {execution.return_code}\n\n'+execution.stdout+execution.stderr)
    reason=None if execution.return_code==0 else 'network degradation cleanup or isolated-veth MTU restoration failed'
    return GatewayNetworkDegradationResult(execution.return_code,execution,degradation.log_path,reason)

def degradation_manifest(config:NetworkDegradationConfig)->dict[str,Any]:
    return {'enabled':True,'boundary':'experiment_broker_host_veth','physical_interface_unchanged':config.interface,'broker_service':config.broker_service,'ifb_interface':config.ifb_interface,'rate_kbit':config.rate_kbit,'rtt_ms':config.rtt_ms,'one_way_delay_ms':config.one_way_delay_ms,'loss_percent':config.loss_percent,'loss_model':'independent_per_direction_netem','mtu':config.mtu,'mtu_scope':'experiment_broker_veth_pair_only','reporting_plane_impairment_exempt':True,'management_safe_acknowledged':config.management_safe}
