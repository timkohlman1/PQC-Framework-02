"""Preconnected MQTT clients for the gateway-side Ready Metrics 2 workload.

The same native clients use a broker-namespace loopback listener for every target
protocol. Target traffic still uses its selected plaintext or TLS listener. Connections,
subscriptions and payload preparation finish before the STM32 is reset. No
process or broker connection is created in response to its transfer request.
This module is stdlib-only so its exact source can run on the gateway via SSH.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import re
import shlex
import signal
import subprocess
import sys
import time

LEGACY_CONTRACT = 'preconnected_loopback_mosquitto_v1'
CONTRACT = 'preconnected_broker_namespace_mosquitto_v2'
IMAGE = 'eclipse-mosquitto:2.1.2-alpine@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797'


def payload_lines(size, chunk):
    if type(size) is not int or type(chunk) is not int or not 0 < chunk <= size <= 1048576:
        raise ValueError('invalid bounded transfer size')
    count, tail = divmod(size, chunk)
    return (b'A' * chunk + b'\n') * count + (b'A' * tail + b'\n' if tail else b'')


def client_commands(config):
    """One native client stack for all target protocols, connected over broker loopback."""
    if config['host'] != '127.0.0.1' or config.get('tls_args') or config.get('oqs'):
        raise ValueError('responder must use the broker-namespace loopback listener')
    common = ['-h', config['host'], '-p', str(config['port']), '-V', 'mqttv311', '-d']
    result = {}
    for role, client_id, topic in (
        ('observer', 'pqc-host-e2e-subscriber', config['response_topic']),
        ('request', 'pqc-host-rm2-transfer-request', config['request_topic']),
        ('publisher', 'pqc-host-rm2-transfer-publisher', config['payload_topic']),
    ):
        command = ['stdbuf', '-oL', '-eL', 'mosquitto_pub' if role == 'publisher' else 'mosquitto_sub',
                   *common, '-i', client_id, '-q', '0', '-t', topic]
        command += ['-l'] if role == 'publisher' else ['-v', '-C', '1', '-W', str(config['timeout'])]
        result[role] = (client_id, command)
    return result


def probe_loopback(config):
    """Verify anonymous feeder ACLs before target reset, on an owned topic."""
    topic = 'pqc/experiments/framework-probe/' + config['token']
    common = ['-h','127.0.0.1','-p',str(config['port']),'-t',topic]
    try:
        sent = subprocess.run(['mosquitto_pub',*common,'-r','-m',config['token']],
            capture_output=True,timeout=5)
        received = subprocess.run(['mosquitto_sub',*common,'-C','1','-W','5'],
            capture_output=True,timeout=7)
        if sent.returncode or received.returncode or received.stdout.strip() != config['token'].encode():
            raise ValueError('loopback workload publish/subscribe ACL probe failed; target must not reset')
    finally:
        subprocess.run(['mosquitto_pub',*common,'-r','-n'],capture_output=True,timeout=5,check=True)


def delivery_eligible(contract, network_enabled=None):
    """The original host-loopback path is usable only without veth impairment."""
    return contract == CONTRACT or (contract == LEGACY_CONTRACT and network_enabled in (None, False))


def namespace_prefix(service):
    """Enter only the selected broker network namespace, retaining the host user.

    Native clients/binaries and host files stay unchanged; dropping uid/gid lets
    the owning capture shell signal the coordinator normally. The namespace is
    checked before any target reset and again by the coordinator itself.
    """
    allowed = {'mqtt-classical', 'mqtt-classical-server-auth', 'mqtt-oqs', 'mqtt-oqs-mtls'}
    if service not in allowed:
        raise ValueError('unknown experiment broker service')
    return (
        'responder_nsenter=$(command -v nsenter) || exit 72; '
        'responder_compose=$HOME/pqc-framework-02/experiment/mqtt-broker/compose.yaml; '
        'responder_cid=$(docker compose -p pqc-framework-mqtt-broker -f "$responder_compose" ps -q '
        + shlex.quote(service) + '); [ -n "$responder_cid" ] || exit 72; '
        'responder_pid=$(docker inspect -f "{{.State.Pid}}" "$responder_cid"); '
        'case "$responder_pid" in ""|*[!0-9]*) exit 72;; esac; [ "$responder_pid" -gt 0 ] || exit 72; '
        'responder_netns=$(sudo -n "$responder_nsenter" -t "$responder_pid" -n readlink /proc/self/ns/net) || exit 72; '
        '[ "$responder_netns" != "$(readlink /proc/self/ns/net)" ] || exit 72; '
    )


def evidence(text):
    events = []
    for line in text.splitlines():
        if line.startswith('PQC_MQTT_RESPONDER_EVENT '):
            try: events.append(json.loads(line.split(' ', 1)[1]))
            except (ValueError, TypeError): return {'contract': None, 'verified': False, 'cleanup_verified': False, 'reason': 'invalid_event'}
    if not events or any(not isinstance(e, dict) for e in events):
        return {'contract': None, 'verified': False, 'cleanup_verified': False, 'reason': 'invalid_event'}
    contract = events[0].get('contract')
    ready = [e for e in events if e.get('event') == 'ready']
    cleanup = [e for e in events if e.get('event') == 'cleanup']
    names = [e.get('event') for e in events]
    clocks = [e.get('monotonic_ns') for e in events]
    ordered = (contract in {CONTRACT, LEGACY_CONTRACT}
        and all(e.get('contract') == contract for e in events)
        and all(type(v) is int and v > 0 for v in clocks)
        and all(a < b for a,b in zip(clocks,clocks[1:])))
    # Cleanup safety is independent of acquisition/measurement eligibility.
    cleanup_verified = (ordered and len(cleanup) == 1 and names[-1] == 'cleanup'
        and cleanup[0].get('verified') is True and type(cleanup[0].get('return_code')) is int)
    verified = (cleanup_verified and len(ready) == 1 and 'failure' not in names
        and ready[0].get('connections') == 3 and ready[0].get('payload_prepared') is True
        and cleanup[0]['return_code'] in ({0,27,28} if contract == CONTRACT else {0,27}))
    if verified and contract == CONTRACT:
        verified = (ready[0].get('endpoint') == 'broker_namespace_loopback'
            and isinstance(ready[0].get('network_namespace'), str)
            and re.fullmatch(r'net:\[\d+\]', ready[0]['network_namespace']) is not None)
    if verified:
        start = [e for e in events if e['event'] == 'client_started']
        verified = (len(start) == 3 and {e.get('role') for e in start} == {'observer','request','publisher'}
            and all(e['monotonic_ns'] < ready[0]['monotonic_ns'] for e in start))
        code = cleanup[0]['return_code']
        if code == 0:
            required = ['ready','request_received','payload_enqueued','complete','cleanup']
            verified = verified and all(names.count(n) == 1 for n in required)
            if verified: verified = [names.index(n) for n in required] == sorted(names.index(n) for n in required)
        elif code == 27:
            verified = verified and 'request_received' not in names and cleanup[0].get('requested') is False
        else:
            required = ['ready','request_received','payload_enqueued','publisher_complete','cleanup']
            verified = (verified and cleanup[0].get('requested') is True
                and 'workload_ready_observed' not in names and 'complete' not in names
                and all(names.count(n) == 1 for n in required))
            if verified: verified = [names.index(n) for n in required] == sorted(names.index(n) for n in required)
    return dict(contract=contract, verified=bool(verified), cleanup_verified=bool(cleanup_verified), events=events,
        timing_boundary='gateway monotonic diagnostics; not STM32 elapsed times')


def run(config, response_path, ready_path, rc_path, expected_namespace=None):
    payload = payload_lines(config['payload_bytes'], config['chunk_bytes'])
    commands = client_commands(config)
    children, streams, ready, completed = {}, {}, set(), set()
    selector = selectors.DefaultSelector()
    stopping = False
    requested = False
    cursor = 0
    code = 70
    cleanup_ok = True
    started = time.monotonic()
    deadline = started + config['timeout'] + 35

    def event(name, **details):
        print('PQC_MQTT_RESPONDER_EVENT ' + json.dumps(dict(event=name, contract=CONTRACT,
              monotonic_ns=time.monotonic_ns(), **details), sort_keys=True), flush=True)

    def stop(_sig, _frame):
        nonlocal stopping
        stopping = True

    old_signals = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        namespace = os.readlink("/proc/self/ns/net")
        if expected_namespace != namespace:
            raise ValueError("broker network namespace not verified; target must not reset")
        probe_loopback(config)
        event('loopback_probe_passed')
        Path(response_path).write_text('')
        for p in (ready_path, rc_path): Path(p).unlink(missing_ok=True)
        for role, (name, command) in commands.items():
            children[role] = subprocess.Popen(command, stdin=subprocess.PIPE if role == 'publisher' else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
            fd = children[role].stdout.fileno()
            os.set_blocking(fd, False)
            streams[fd] = bytearray()
            selector.register(fd, selectors.EVENT_READ, role)
            event('client_started', role=role, client_id=name)
        while time.monotonic() < deadline:
            if stopping:
                code = (27 if not requested and len(ready) == 3 else
                        0 if completed == set(commands) else
                        28 if requested and 'publisher' in completed and 'observer' not in completed else 71)
                break
            if len(ready) != 3 and time.monotonic() - started > 30:
                raise ValueError('MQTT readiness barrier timed out; target must not reset')
            for key, mask in selector.select(.1):
                role = key.data
                if mask & selectors.EVENT_WRITE:
                    count = os.write(key.fd, payload[cursor:cursor + 32768])
                    cursor += count
                    if cursor == len(payload):
                        selector.unregister(key.fd)
                        children['publisher'].stdin.close()
                        event('payload_enqueued', payload_bytes=config['payload_bytes'], chunk_bytes=config['chunk_bytes'])
                    continue
                block = os.read(key.fd, 65536)
                if not block:
                    selector.unregister(key.fd)
                    continue
                streams[key.fd].extend(block)
                while b'\n' in streams[key.fd]:
                    raw, _, rest = streams[key.fd].partition(b'\n')
                    streams[key.fd][:] = rest
                    line = raw.decode('utf-8', errors='replace').rstrip('\r')
                    if role == 'publisher' and ' received CONNACK (0)' in line:
                        ready.add(role)
                    elif role != 'publisher' and line == 'Subscribed (mid: 1): 0':
                        ready.add(role)
                    elif role == 'observer' and line.startswith(config['response_topic'] + ' '):
                        with Path(response_path).open('a') as stream: stream.write(line + '\n')
                        completed.add(role)
                        event('workload_ready_observed')
                    elif role == 'request' and line.startswith(config['request_topic'] + ' '):
                        if requested or len(ready) != 3 or line != config['request_topic'] + ' ' + config['request_payload']:
                            raise ValueError('unexpected, duplicate or premature transfer request')
                        requested = True
                        completed.add(role)
                        event('request_received')
                        fd = children['publisher'].stdin.fileno()
                        os.set_blocking(fd, False)
                        selector.register(fd, selectors.EVENT_WRITE, 'write')
                    elif not line.startswith('Client '):
                        event('client_diagnostic', role=role, text=line)
            if len(ready) == 3 and not Path(ready_path).exists():
                event('ready', payload_prepared=True, connections=3, endpoint='broker_namespace_loopback', network_namespace=namespace)
                Path(ready_path).write_text(CONTRACT + '\n')
            for role, process in children.items():
                rc = process.poll()
                if rc is None: continue
                if rc == 27 and role != 'publisher':
                    # A missing device message is not a feeder/infrastructure error.
                    # Only firmware outcome evidence may classify it as a valid trial.
                    continue
                if rc != 0: raise ValueError(f'{role} client failed: {rc}')
                if role == 'publisher':
                    if cursor != len(payload): raise ValueError('publisher exited before completing payload input')
                    if role not in completed: event('publisher_complete')
                    completed.add(role)
                elif role not in completed and process.stdout.fileno() not in selector.get_map():
                    raise ValueError(f'{role} exited without its expected message')
            if completed == set(commands) and children['publisher'].poll() == 0:
                code = 0
                event('complete')
                break
        else:
            if not requested and len(ready) == 3:
                code = 27
            elif requested and 'publisher' in completed and 'observer' not in completed:
                code = 28
            else:
                raise ValueError('responder deadline exceeded')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        event('failure', reason=str(exc))
        code = 70
    finally:
        for process in children.values():
            if process.poll() is None: process.terminate()
        for process in children.values():
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
        cleanup_ok = all(p.poll() is not None for p in children.values())
        selector.close()
        if not cleanup_ok: code = 72
        Path(rc_path).write_text(str(code) + '\n')
        event('cleanup', verified=cleanup_ok, return_code=code, requested=requested)
        for sig, handler in old_signals.items(): signal.signal(sig, handler)
    return code


if __name__ == '__main__':
    raise SystemExit(run(json.loads(sys.argv[1]), *sys.argv[2:6]))
