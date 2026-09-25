"""Offline analysis of retained gateway packet captures.

This module is deliberately read-only with respect to the finalized run capture.
Raw PCAP/key-log/result artefacts remain authoritative. Derived packet observations
and their lineage are written only below the result-local ``analysis/`` namespace.
"""
from __future__ import annotations

import ipaddress
import json
import shutil
import struct
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from framework.run_evidence import build_derived_record, sha256_file

ANALYSER_VERSION = "request7-pcap-2"
OUTPUT_SCHEMA = {"name": "pqc-packet-analysis", "version": 1}


class PacketAnalysisError(ValueError):
    """The retained capture cannot be analysed defensibly."""


@dataclass
class Packet:
    number: int
    timestamp: float
    captured_len: int
    wire_len: int
    src_ip: str | None = None
    dst_ip: str | None = None
    protocol: int | None = None
    ip_id: int | None = None
    ip_more_fragments: bool = False
    ip_fragment_offset: int = 0
    src_port: int | None = None
    dst_port: int | None = None
    tcp_seq: int | None = None
    tcp_ack: int | None = None
    tcp_flags: int = 0
    tcp_payload: bytes = b""


@dataclass
class DirectionState:
    packets: int = 0
    wire_bytes: int = 0
    tcp_payload_bytes: int = 0
    segments: list[tuple[int, bytes, int]] = field(default_factory=list)
    retransmissions: int = 0
    retransmitted_payload_bytes: int = 0
    highest_end: int | None = None


@dataclass
class ConnectionState:
    endpoints: tuple[tuple[str, int], tuple[str, int]]
    first_timestamp: float
    last_timestamp: float
    packets: int = 0
    wire_bytes: int = 0
    syn_packets: int = 0
    fin_packets: int = 0
    rst_packets: int = 0
    directions: dict[str, DirectionState] = field(default_factory=lambda: {"a_to_b": DirectionState(), "b_to_a": DirectionState()})


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("!H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("!I", data, offset)[0]


def _link_payload(frame: bytes, linktype: int) -> tuple[int | None, bytes]:
    if linktype == 1:  # Ethernet
        if len(frame) < 14:
            return None, b""
        ethertype = _u16(frame, 12)
        offset = 14
        while ethertype in {0x8100, 0x88A8} and len(frame) >= offset + 4:
            ethertype = _u16(frame, offset + 2)
            offset += 4
        return ethertype, frame[offset:]
    if linktype == 113:  # Linux cooked capture v1
        if len(frame) < 16:
            return None, b""
        return _u16(frame, 14), frame[16:]
    if linktype == 276:  # Linux cooked capture v2
        if len(frame) < 20:
            return None, b""
        return _u16(frame, 0), frame[20:]
    if linktype == 101:  # Raw IP
        return (0x0800 if frame and frame[0] >> 4 == 4 else 0x86DD if frame and frame[0] >> 4 == 6 else None), frame
    raise PacketAnalysisError(f"unsupported PCAP link type {linktype}")


def _parse_ipv4(packet: Packet, data: bytes) -> None:
    if len(data) < 20 or data[0] >> 4 != 4:
        return
    ihl = (data[0] & 0x0F) * 4
    if ihl < 20 or len(data) < ihl:
        return
    total_len = _u16(data, 2)
    packet.ip_id = _u16(data, 4)
    frag = _u16(data, 6)
    packet.ip_more_fragments = bool(frag & 0x2000)
    packet.ip_fragment_offset = (frag & 0x1FFF) * 8
    packet.protocol = data[9]
    packet.src_ip = str(ipaddress.ip_address(data[12:16]))
    packet.dst_ip = str(ipaddress.ip_address(data[16:20]))
    payload = data[ihl:min(len(data), total_len or len(data))]
    # Only the first fragment contains the transport header.
    if packet.protocol == 6 and packet.ip_fragment_offset == 0 and len(payload) >= 20:
        packet.src_port = _u16(payload, 0)
        packet.dst_port = _u16(payload, 2)
        packet.tcp_seq = _u32(payload, 4)
        packet.tcp_ack = _u32(payload, 8)
        header_len = ((payload[12] >> 4) & 0xF) * 4
        if header_len >= 20 and len(payload) >= header_len:
            packet.tcp_flags = payload[13]
            packet.tcp_payload = payload[header_len:]


def read_pcap(path: Path | str) -> tuple[dict[str, Any], list[Packet]]:
    raw = Path(path).read_bytes()
    if len(raw) < 24:
        raise PacketAnalysisError("PCAP is truncated before its global header")
    magic = raw[:4]
    variants = {
        b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
        b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
        b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),
        b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
    }
    if magic not in variants:
        raise PacketAnalysisError("unsupported capture format; classic PCAP is required by the built-in analyser")
    endian, divisor = variants[magic]
    _, major, minor, _, _, snaplen, linktype = struct.unpack_from(endian + "IHHIIII", raw, 0)
    offset = 24
    packets: list[Packet] = []
    number = 0
    while offset < len(raw):
        if len(raw) - offset < 16:
            raise PacketAnalysisError("PCAP ends inside a packet header")
        ts_sec, ts_frac, incl_len, orig_len = struct.unpack_from(endian + "IIII", raw, offset)
        offset += 16
        end = offset + incl_len
        if end > len(raw):
            raise PacketAnalysisError("PCAP ends inside a packet payload")
        frame = raw[offset:end]
        offset = end
        number += 1
        packet = Packet(number, ts_sec + ts_frac / divisor, incl_len, orig_len)
        ethertype, network = _link_payload(frame, linktype)
        if ethertype == 0x0800:
            _parse_ipv4(packet, network)
        packets.append(packet)
    return {
        "format": "pcap",
        "version": f"{major}.{minor}",
        "snaplen": snaplen,
        "linktype": linktype,
        "timestamp_resolution": "nanoseconds" if divisor == 1_000_000_000 else "microseconds",
    }, packets


def _connection_key(packet: Packet) -> tuple[tuple[str, int], tuple[str, int]] | None:
    if packet.src_ip is None or packet.dst_ip is None or packet.src_port is None or packet.dst_port is None:
        return None
    left = (packet.src_ip, packet.src_port)
    right = (packet.dst_ip, packet.dst_port)
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def _reassemble(segments: list[tuple[int, bytes, int]]) -> bytes:
    if not segments:
        return b""
    ordered = sorted(segments, key=lambda item: (item[0], item[2]))
    base = ordered[0][0]
    output = bytearray()
    for seq, payload, _ in ordered:
        start = seq - base
        if start < 0:
            payload = payload[-start:]
            start = 0
        if start > len(output):
            # A gap means the stream is incomplete; retain an explicit discontinuity
            # by stopping protocol parsing rather than fabricating bytes.
            break
        overlap = len(output) - start
        if overlap < len(payload):
            output.extend(payload[max(overlap, 0):])
    return bytes(output)


def _mqtt_messages(stream: bytes) -> dict[str, Any]:
    offset = 0
    counts: dict[str, int] = defaultdict(int)
    parsed = 0
    payload_bytes = 0
    names = {1:"CONNECT",2:"CONNACK",3:"PUBLISH",4:"PUBACK",8:"SUBSCRIBE",9:"SUBACK",12:"PINGREQ",13:"PINGRESP",14:"DISCONNECT"}
    while offset + 2 <= len(stream):
        first = stream[offset]
        msg_type = first >> 4
        if msg_type == 0 or msg_type == 15:
            break
        multiplier = 1
        remaining = 0
        cursor = offset + 1
        for _ in range(4):
            if cursor >= len(stream):
                return {"parsed_messages": parsed, "counts": dict(counts), "publish_wire_payload_bytes": payload_bytes}
            encoded = stream[cursor]
            cursor += 1
            remaining += (encoded & 0x7F) * multiplier
            if not encoded & 0x80:
                break
            multiplier *= 128
        else:
            break
        end = cursor + remaining
        if end > len(stream):
            break
        counts[names.get(msg_type, f"TYPE_{msg_type}")] += 1
        if msg_type == 3:
            payload_bytes += remaining
        parsed += 1
        offset = end
    return {"parsed_messages": parsed, "counts": dict(sorted(counts.items())), "publish_wire_payload_bytes": payload_bytes}


def _tls_records(stream: bytes) -> dict[str, Any]:
    offset = 0
    counts: dict[str, int] = defaultdict(int)
    parsed = 0
    names = {20:"change_cipher_spec",21:"alert",22:"handshake",23:"application_data"}
    while offset + 5 <= len(stream):
        content_type = stream[offset]
        major = stream[offset + 1]
        length = _u16(stream, offset + 3)
        if content_type not in {20, 21, 22, 23} or major != 3 or length > 18432:
            break
        end = offset + 5 + length
        if end > len(stream):
            break
        counts[names[content_type]] += 1
        parsed += 1
        offset = end
    return {"parsed_records": parsed, "counts": dict(sorted(counts.items()))}


def _tshark_decryption(pcap: Path, keylog: Path | None, experiment_flow: dict[str, Any] | None = None) -> dict[str, Any]:
    executable = shutil.which("tshark")
    if keylog is None:
        return {"status": "not_requested", "tshark_available": executable is not None, "reason": "no TLS key log retained"}
    if executable is None:
        return {"status": "unavailable", "tshark_available": False, "reason": "tshark is not installed; TLS key-log decryption was not attempted"}
    command = [
        executable, "-r", str(pcap), "-o", f"tls.keylog_file:{keylog}",
    ]
    if experiment_flow and isinstance(experiment_flow.get("port"), int):
        command += ["-Y", f"tcp.port == {experiment_flow['port']}"]
    command += [
        "-T", "fields", "-E", "separator=,", "-E", "quote=d",
        "-e", "frame.number", "-e", "tcp.stream", "-e", "mqtt.msgtype",
    ]
    completed = subprocess.run(command, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if completed.returncode != 0:
        return {"status": "failed", "tshark_available": True, "return_code": completed.returncode,
                "reason": completed.stderr.strip() or "tshark TLS decryption failed"}
    mqtt_rows = [line for line in completed.stdout.splitlines() if line.strip() and line.rstrip().split(",")[-1].strip('"')]
    return {"status": "completed", "tshark_available": True, "return_code": 0,
            "decrypted_mqtt_rows": len(mqtt_rows)}


def _artifact_by_role(manifest: dict[str, Any], role: str) -> dict[str, Any] | None:
    for item in manifest.get("artifacts", []):
        if isinstance(item, dict) and item.get("role") == role and (item.get("acquisition") or {}).get("status") == "available":
            return item
    return None


def _artifact_path(result_dir: Path, manifest: dict[str, Any], role: str, fallback: str | None = None) -> Path | None:
    item = _artifact_by_role(manifest, role)
    if item and isinstance(item.get("path"), str):
        candidate = (result_dir / item["path"]).resolve()
        try:
            candidate.relative_to(result_dir.resolve())
        except ValueError as exc:
            raise PacketAnalysisError(f"artifact path for {role} escapes the result directory") from exc
        if candidate.is_file():
            return candidate
    if fallback:
        candidate = result_dir / fallback
        if candidate.is_file():
            return candidate
    return None


def _validate_artifact_hash(manifest: dict[str, Any], role: str, path: Path) -> None:
    item = _artifact_by_role(manifest, role)
    expected = item.get("sha256") if item else None
    if expected and sha256_file(path) != expected:
        raise PacketAnalysisError(f"retained {role} SHA-256 does not match finalized manifest")


def _reporting_identity(path: Path | None, run_id: str) -> dict[str, Any]:
    if path is None:
        return {"status": "unavailable", "reason": "STM32 reporting stream was not retained"}
    matching = 0
    mismatched = 0
    parse_errors = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            outer = json.loads(line)
            payload = outer.get("payload") if isinstance(outer, dict) else None
            if isinstance(payload, dict) and "payload" in payload:
                payload = payload["payload"]
            obj = json.loads(payload) if isinstance(payload, str) else payload
            if not isinstance(obj, dict) or obj.get("source") != "stm32":
                continue
            if obj.get("run_id") == run_id:
                matching += 1
            else:
                mismatched += 1
        except Exception:
            parse_errors += 1
    return {"status": "matched" if matching and not mismatched else "invalid" if mismatched else "unavailable",
            "matching_envelopes": matching, "mismatched_envelopes": mismatched, "parse_errors": parse_errors}


def _flow_matches_packet(packet: Packet, experiment_flow: dict[str, Any] | None) -> bool:
    if experiment_flow is None:
        return True
    port = experiment_flow.get("port")
    host_ip = experiment_flow.get("host_ip")
    if not isinstance(port, int):
        return False
    if packet.src_port != port and packet.dst_port != port:
        return False
    if isinstance(host_ip, str) and host_ip:
        return packet.src_ip == host_ip or packet.dst_ip == host_ip
    return True


def _flow_matches_endpoints(endpoints: tuple[tuple[str, int], tuple[str, int]], experiment_flow: dict[str, Any] | None) -> bool:
    if experiment_flow is None:
        return True
    port = experiment_flow.get("port")
    host_ip = experiment_flow.get("host_ip")
    if not isinstance(port, int):
        return False
    for ip, endpoint_port in endpoints:
        if endpoint_port == port and (not host_ip or ip == host_ip):
            return True
    return False


def analyse_packets(packets: list[Packet], *, experiment_flow: dict[str, Any] | None = None) -> dict[str, Any]:
    if not packets:
        raise PacketAnalysisError("capture contains no packets")
    connections: dict[tuple[tuple[str, int], tuple[str, int]], ConnectionState] = {}
    ipv4_packets = 0
    fragment_packets = 0
    fragment_datagrams: set[tuple[str, str, int, int]] = set()
    experiment_fragment_keys: set[tuple[str, str, int, int]] = set()
    tcp_packets = 0
    tcp_payload_bytes = 0

    # Identify fragmented datagrams belonging to the configured experiment flow
    # from their first fragment, where the TCP header/port is still available.
    if experiment_flow is not None:
        for packet in packets:
            if (packet.ip_more_fragments or packet.ip_fragment_offset) and packet.ip_fragment_offset == 0 and _flow_matches_packet(packet, experiment_flow):
                if packet.src_ip and packet.dst_ip and packet.protocol is not None and packet.ip_id is not None:
                    experiment_fragment_keys.add((packet.src_ip, packet.dst_ip, packet.protocol, packet.ip_id))

    for packet in packets:
        if packet.src_ip is not None:
            ipv4_packets += 1
            if packet.ip_more_fragments or packet.ip_fragment_offset:
                fragment_packets += 1
                if packet.ip_id is not None and packet.protocol is not None and packet.dst_ip is not None:
                    fragment_datagrams.add((packet.src_ip, packet.dst_ip, packet.protocol, packet.ip_id))
        key = _connection_key(packet)
        if key is None:
            continue
        tcp_packets += 1
        tcp_payload_bytes += len(packet.tcp_payload)
        state = connections.get(key)
        if state is None:
            state = connections[key] = ConnectionState(key, packet.timestamp, packet.timestamp)
        state.last_timestamp = packet.timestamp
        state.packets += 1
        state.wire_bytes += packet.wire_len
        state.syn_packets += 1 if packet.tcp_flags & 0x02 else 0
        state.fin_packets += 1 if packet.tcp_flags & 0x01 else 0
        state.rst_packets += 1 if packet.tcp_flags & 0x04 else 0
        direction_name = "a_to_b" if (packet.src_ip, packet.src_port) == key[0] else "b_to_a"
        direction = state.directions[direction_name]
        direction.packets += 1
        direction.wire_bytes += packet.wire_len
        direction.tcp_payload_bytes += len(packet.tcp_payload)
        if packet.tcp_seq is not None and packet.tcp_payload:
            end = packet.tcp_seq + len(packet.tcp_payload)
            if direction.highest_end is not None and packet.tcp_seq < direction.highest_end:
                overlap = min(direction.highest_end - packet.tcp_seq, len(packet.tcp_payload))
                direction.retransmissions += 1
                direction.retransmitted_payload_bytes += max(overlap, 0)
            direction.highest_end = max(direction.highest_end or end, end)
            direction.segments.append((packet.tcp_seq, packet.tcp_payload, packet.number))

    connection_records = []
    total_retransmissions = 0
    total_retransmitted_bytes = 0
    experiment_packets = 0
    experiment_wire_bytes = 0
    experiment_payload_bytes = 0
    experiment_retransmissions = 0
    experiment_retransmitted_bytes = 0
    experiment_connection_count = 0
    mqtt_total: dict[str, int] = defaultdict(int)
    tls_total: dict[str, int] = defaultdict(int)
    tls_expected = bool(experiment_flow and experiment_flow.get("tls_enabled"))

    for index, (_, state) in enumerate(sorted(connections.items()), 1):
        is_experiment = _flow_matches_endpoints(state.endpoints, experiment_flow)
        if is_experiment:
            experiment_connection_count += 1
            experiment_packets += state.packets
            experiment_wire_bytes += state.wire_bytes
        directions: dict[str, Any] = {}
        for name, direction in state.directions.items():
            stream = _reassemble(direction.segments)
            if is_experiment:
                if experiment_flow is None:
                    mqtt = _mqtt_messages(stream)
                    tls = _tls_records(stream)
                elif tls_expected:
                    mqtt = {"parsed_messages": 0, "counts": {}, "publish_wire_payload_bytes": 0, "status": "encrypted_transport"}
                    tls = _tls_records(stream)
                else:
                    mqtt = _mqtt_messages(stream)
                    tls = {"parsed_records": 0, "counts": {}}
                for key, value in mqtt["counts"].items():
                    mqtt_total[key] += value
                for key, value in tls["counts"].items():
                    tls_total[key] += value
                experiment_payload_bytes += direction.tcp_payload_bytes
                experiment_retransmissions += direction.retransmissions
                experiment_retransmitted_bytes += direction.retransmitted_payload_bytes
            else:
                mqtt = {"parsed_messages": 0, "counts": {}, "publish_wire_payload_bytes": 0, "status": "not_experiment_flow"}
                tls = {"parsed_records": 0, "counts": {}, "status": "not_experiment_flow"}
            total_retransmissions += direction.retransmissions
            total_retransmitted_bytes += direction.retransmitted_payload_bytes
            directions[name] = {
                "packets": direction.packets,
                "wire_bytes": direction.wire_bytes,
                "tcp_payload_bytes": direction.tcp_payload_bytes,
                "retransmission_segments": direction.retransmissions,
                "retransmitted_payload_bytes": direction.retransmitted_payload_bytes,
                "reassembled_prefix_bytes": len(stream),
                "mqtt": mqtt,
                "tls": tls,
            }
        connection_records.append({
            "connection_index": index,
            "classification": "experiment_broker" if is_experiment else "other_tcp",
            "endpoint_a": {"ip": state.endpoints[0][0], "port": state.endpoints[0][1]},
            "endpoint_b": {"ip": state.endpoints[1][0], "port": state.endpoints[1][1]},
            "first_packet_epoch_seconds": state.first_timestamp,
            "last_packet_epoch_seconds": state.last_timestamp,
            "duration_seconds": max(0.0, state.last_timestamp - state.first_timestamp),
            "packets": state.packets,
            "wire_bytes": state.wire_bytes,
            "syn_packets": state.syn_packets,
            "fin_packets": state.fin_packets,
            "rst_packets": state.rst_packets,
            "directions": directions,
        })

    experiment_fragment_packets = 0
    experiment_fragment_datagrams: set[tuple[str, str, int, int]] = set()
    if experiment_fragment_keys:
        for packet in packets:
            if packet.src_ip and packet.dst_ip and packet.protocol is not None and packet.ip_id is not None:
                frag_key = (packet.src_ip, packet.dst_ip, packet.protocol, packet.ip_id)
                if frag_key in experiment_fragment_keys and (packet.ip_more_fragments or packet.ip_fragment_offset):
                    experiment_fragment_packets += 1
                    experiment_fragment_datagrams.add(frag_key)

    return {
        "capture": {
            "packet_count": len(packets),
            "wire_bytes": sum(packet.wire_len for packet in packets),
            "captured_bytes": sum(packet.captured_len for packet in packets),
            "first_packet_epoch_seconds": packets[0].timestamp,
            "last_packet_epoch_seconds": packets[-1].timestamp,
            "duration_seconds": max(0.0, packets[-1].timestamp - packets[0].timestamp),
        },
        "network": {
            "scope": "entire_capture",
            "ipv4_packets": ipv4_packets,
            "fragment_packets": fragment_packets,
            "fragmented_datagrams": len(fragment_datagrams),
        },
        "tcp": {
            "scope": "entire_capture",
            "packets": tcp_packets,
            "payload_bytes": tcp_payload_bytes,
            "connection_count": len(connection_records),
            "retransmission_segments": total_retransmissions,
            "retransmitted_payload_bytes": total_retransmitted_bytes,
            "connections": connection_records,
        },
        "experiment_flow": {
            "selection": experiment_flow or {"status": "unscoped_fixture_or_legacy_analysis"},
            "matched_connection_count": experiment_connection_count,
            "packets": experiment_packets,
            "wire_bytes": experiment_wire_bytes,
            "tcp_payload_bytes": experiment_payload_bytes,
            "retransmission_segments": experiment_retransmissions,
            "retransmitted_payload_bytes": experiment_retransmitted_bytes,
            "fragment_packets": experiment_fragment_packets,
            "fragmented_datagrams": len(experiment_fragment_datagrams),
        },
        "protocol_observations": {
            "scope": "configured_experiment_broker_flow" if experiment_flow is not None else "all_tcp_fixture_scope",
            "plaintext_mqtt_counts": dict(sorted(mqtt_total.items())),
            "tls_record_counts": dict(sorted(tls_total.items())),
        },
    }


def _resolved_case_and_flow(result_dir: Path, manifest: dict[str, Any]) -> tuple[Path | None, dict[str, Any] | None]:
    configuration = manifest.get("configuration")
    if not isinstance(configuration, dict):
        return None, None
    snapshot = configuration.get("snapshot")
    if not isinstance(snapshot, str) or not snapshot:
        return None, None
    resolved_path = (result_dir / snapshot).resolve()
    try:
        resolved_path.relative_to(result_dir.resolve())
    except ValueError as exc:
        raise PacketAnalysisError("resolved-case snapshot path escapes the result directory") from exc
    if not resolved_path.is_file():
        return None, None
    expected = configuration.get("sha256")
    if isinstance(expected, str) and expected and sha256_file(resolved_path) != expected:
        raise PacketAnalysisError("resolved-case SHA-256 does not match finalized manifest")
    try:
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PacketAnalysisError(f"resolved-case snapshot is not valid JSON: {exc}") from exc
    params = resolved.get("effective_non_secret_parameters") if isinstance(resolved, dict) else None
    mqtt = params.get("mqtt") if isinstance(params, dict) else None
    if not isinstance(mqtt, dict) or not mqtt.get("enabled"):
        return resolved_path, None
    broker = mqtt.get("broker") if isinstance(mqtt.get("broker"), dict) else {}
    orchestration = mqtt.get("orchestration") if isinstance(mqtt.get("orchestration"), dict) else {}
    tls = mqtt.get("tls") if isinstance(mqtt.get("tls"), dict) else {}
    port = broker.get("port")
    if not isinstance(port, int):
        return resolved_path, None
    host_ip = orchestration.get("host") if isinstance(orchestration.get("host"), str) else None
    mode = tls.get("mode") if isinstance(tls.get("mode"), str) else None
    tls_enabled = bool(mode and mode not in {"plaintext", "none", "disabled"})
    return resolved_path, {
        "host": broker.get("host"),
        "host_ip": host_ip,
        "port": port,
        "tls_enabled": tls_enabled,
        "tls_mode": mode,
        "source": "resolved-case.json",
    }


def analyse_run(manifest_path: Path | str, *, use_tshark: bool = True) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise PacketAnalysisError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise PacketAnalysisError("manifest must be an object")
    if (manifest.get("final_index") or {}).get("status") != "finalized":
        raise PacketAnalysisError("packet analysis requires a finalized run manifest")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        run = manifest.get("run")
        run_id = run.get("id") if isinstance(run, dict) else None
    if not isinstance(run_id, str) or not run_id:
        raise PacketAnalysisError("finalized manifest has no run ID")
    result_dir = manifest_path.parent
    pcap = _artifact_path(result_dir, manifest, "packet_capture", "gateway-network-capture.pcap")
    if pcap is None:
        raise PacketAnalysisError("finalized run has no retained packet capture")
    _validate_artifact_hash(manifest, "packet_capture", pcap)
    keylog = _artifact_path(result_dir, manifest, "tls_key_log")
    if keylog is not None:
        _validate_artifact_hash(manifest, "tls_key_log", keylog)
    reporting = _artifact_path(result_dir, manifest, "stm32_result_stream", "mqtt-reporting-raw.ndjson")
    if reporting is not None:
        _validate_artifact_hash(manifest, "stm32_result_stream", reporting)

    resolved_case, experiment_flow = _resolved_case_and_flow(result_dir, manifest)
    pcap_meta, packets = read_pcap(pcap)
    observations = analyse_packets(packets, experiment_flow=experiment_flow)
    decryption = _tshark_decryption(pcap, keylog, experiment_flow) if use_tshark else {
        "status": "disabled", "tshark_available": shutil.which("tshark") is not None,
        "reason": "disabled by analysis parameter",
    }
    inputs = {
        "manifest": {"path": manifest_path.name, "sha256": sha256_file(manifest_path), "size_bytes": manifest_path.stat().st_size},
        "packet_capture": {"path": pcap.relative_to(result_dir).as_posix(), "sha256": sha256_file(pcap), "size_bytes": pcap.stat().st_size},
    }
    if keylog is not None:
        inputs["tls_key_log"] = {"path": keylog.relative_to(result_dir).as_posix(), "sha256": sha256_file(keylog), "size_bytes": keylog.stat().st_size}
    if reporting is not None:
        inputs["stm32_result_stream"] = {"path": reporting.relative_to(result_dir).as_posix(), "sha256": sha256_file(reporting), "size_bytes": reporting.stat().st_size}
    if resolved_case is not None:
        inputs["resolved_case"] = {"path": resolved_case.relative_to(result_dir).as_posix(), "sha256": sha256_file(resolved_case), "size_bytes": resolved_case.stat().st_size}

    return {
        "schema": OUTPUT_SCHEMA,
        "analyser_version": ANALYSER_VERSION,
        "run_id": run_id,
        "inputs": inputs,
        "pcap": pcap_meta,
        **observations,
        "tls_keylog_analysis": decryption,
        "correlation": {
            "stm32_reporting": _reporting_identity(reporting, run_id),
            "manifest_binding": "packet capture, optional key log, structured STM32 stream, and resolved-case snapshot were re-hashed against the finalized run manifest where authoritative hashes were available",
            "experiment_flow_selection": experiment_flow or {"status": "unavailable", "reason": "resolved experiment MQTT endpoint was not available"},
            "mqtt_reporting_priority": "primary structured STM32 runtime source when retained",
            "uart_role": "secondary_diagnostic_only",
            "time_domains": {
                "packet_capture": "gateway packet-capture epoch timestamps",
                "stm32": "independent firmware timebase contained in raw STM32 records when present",
                "broker_observer": "independent broker/observer timestamps when present",
            },
            "precise_cross_clock_alignment": False,
            "limitations": [
                "No cross-clock offset or drift is invented between gateway packet timestamps and firmware/broker clocks.",
                "Firmware-internal state is not inferred from packet traffic alone.",
                "Connection boundaries and packet-level observations are in the PCAP time domain; firmware timings remain in their original source domain.",
            ],
        },
    }


def write_analysis(manifest_path: Path | str, *, use_tshark: bool = True) -> tuple[Path, Path]:
    manifest_path = Path(manifest_path).resolve()
    result_dir = manifest_path.parent
    analysis_dir = result_dir / "analysis" / "packet_capture"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    summary = analyse_run(manifest_path, use_tshark=use_tshark)
    output = analysis_dir / "packet_analysis.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    direct_inputs = [item["sha256"] for item in summary["inputs"].values()]
    lineage = build_derived_record(
        result_dir=result_dir,
        role="packet_analysis",
        path=output,
        tool="framework.packet_analysis",
        version=ANALYSER_VERSION,
        input_sha256=direct_inputs,
        parameters={"use_tshark": use_tshark, "cross_clock_alignment": "none"},
    )
    lineage["named_inputs"] = summary["inputs"]
    lineage_path = analysis_dir / "packet_analysis_lineage.json"
    lineage_path.write_text(json.dumps(lineage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output, lineage_path
