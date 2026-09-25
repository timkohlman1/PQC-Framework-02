from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from framework.packet_analysis import Packet, PacketAnalysisError, analyse_packets, analyse_run, read_pcap, write_analysis

FIXTURES = Path(__file__).parents[1] / "fixtures" / "pcap"


def _manifest(tmp_path: Path, pcap_name: str, *, keylog: bool = False, reporting: bool = False) -> Path:
    pcap = tmp_path / "gateway-network-capture.pcap"
    pcap.write_bytes((FIXTURES / pcap_name).read_bytes())
    artifacts = [{
        "role": "packet_capture", "path": pcap.name, "sha256": hashlib.sha256(pcap.read_bytes()).hexdigest(),
        "acquisition": {"status": "available"},
    }]
    if keylog:
        key = tmp_path / "mqtt-broker-tls-keylog.log"
        key.write_text("CLIENT_RANDOM " + "00" * 32 + " " + "11" * 48 + "\n", encoding="utf-8")
        artifacts.append({"role":"tls_key_log","path":key.name,"sha256":hashlib.sha256(key.read_bytes()).hexdigest(),"acquisition":{"status":"available"}})
    if reporting:
        raw = tmp_path / "mqtt-reporting-raw.ndjson"
        raw.write_text(json.dumps({"topic":"pqc/result/stm32/run-1/data","payload":json.dumps({"source":"stm32","run_id":"run-1","type":"complete","chunk_count":0})}) + "\n", encoding="utf-8")
        artifacts.append({"role":"stm32_result_stream","path":raw.name,"sha256":hashlib.sha256(raw.read_bytes()).hexdigest(),"acquisition":{"status":"available"}})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"run":{"id":"run-1","state":"finalized"},"artifacts":artifacts,"final_index":{"status":"finalized"}}), encoding="utf-8")
    return manifest



def test_precompact_manifest_run_id_remains_accepted(tmp_path: Path):
    manifest = _manifest(tmp_path, "mqtt_plaintext.pcap")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["run_id"] = data["run"]["id"]
    del data["run"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    summary = analyse_run(manifest, use_tshark=False)
    assert summary["run_id"] == "run-1"


def test_retransmission_fixture_counts_overlapping_tcp_payload(tmp_path: Path):
    summary = analyse_run(_manifest(tmp_path, "retransmission.pcap"), use_tshark=False)
    assert summary["tcp"]["connection_count"] == 1
    assert summary["tcp"]["retransmission_segments"] == 1
    assert summary["tcp"]["retransmitted_payload_bytes"] == 5


def test_fragmentation_fixture_reports_fragmented_datagram(tmp_path: Path):
    summary = analyse_run(_manifest(tmp_path, "fragmentation.pcap"), use_tshark=False)
    assert summary["network"]["fragment_packets"] == 2
    assert summary["network"]["fragmented_datagrams"] == 1


def test_plaintext_mqtt_and_tls_records_are_distinguished(tmp_path: Path):
    mqtt = analyse_run(_manifest(tmp_path, "mqtt_plaintext.pcap"), use_tshark=False)
    assert mqtt["protocol_observations"]["plaintext_mqtt_counts"]["CONNECT"] == 1
    assert mqtt["protocol_observations"]["plaintext_mqtt_counts"]["CONNACK"] == 1
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    tls = analyse_run(_manifest(tls_dir, "tls_records.pcap", keylog=True), use_tshark=False)
    assert tls["protocol_observations"]["tls_record_counts"]["handshake"] == 1
    assert tls["protocol_observations"]["tls_record_counts"]["application_data"] == 1
    assert tls["tls_keylog_analysis"]["status"] == "disabled"


def test_reporting_stream_is_primary_identity_correlation_and_uart_is_secondary(tmp_path: Path):
    summary = analyse_run(_manifest(tmp_path, "mqtt_plaintext.pcap", reporting=True), use_tshark=False)
    assert summary["correlation"]["stm32_reporting"]["status"] == "matched"
    assert summary["correlation"]["mqtt_reporting_priority"].startswith("primary structured")
    assert summary["correlation"]["uart_role"] == "secondary_diagnostic_only"
    assert summary["correlation"]["precise_cross_clock_alignment"] is False


def test_analysis_writes_under_analysis_and_leaves_manifest_unchanged(tmp_path: Path):
    manifest = _manifest(tmp_path, "mqtt_plaintext.pcap")
    before = manifest.read_bytes()
    output, lineage = write_analysis(manifest, use_tshark=False)
    assert output == tmp_path / "analysis" / "packet_capture" / "packet_analysis.json"
    assert lineage == tmp_path / "analysis" / "packet_capture" / "packet_analysis_lineage.json"
    assert manifest.read_bytes() == before
    record = json.loads(lineage.read_text(encoding="utf-8"))
    assert record["schema"] == {"name":"pqc-derived-lineage","version":1}
    assert record["producer"]["version"] == "request7-pcap-2"
    assert record["named_inputs"]["packet_capture"]["sha256"]
    assert record["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_hash_mismatch_fails_closed(tmp_path: Path):
    manifest = _manifest(tmp_path, "mqtt_plaintext.pcap")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["artifacts"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PacketAnalysisError, match="SHA-256"):
        analyse_run(manifest, use_tshark=False)


def test_corrupt_capture_is_rejected(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    pcap = tmp_path / "gateway-network-capture.pcap"
    pcap.write_bytes(b"not-a-pcap")
    manifest.write_text(json.dumps({"run":{"id":"run-1","state":"finalized"},"final_index":{"status":"finalized"},"artifacts":[{"role":"packet_capture","path":pcap.name,"sha256":hashlib.sha256(pcap.read_bytes()).hexdigest(),"acquisition":{"status":"available"}}]}), encoding="utf-8")
    with pytest.raises(PacketAnalysisError, match="truncated"):
        analyse_run(manifest, use_tshark=False)


def test_fixture_is_classic_pcap():
    meta, packets = read_pcap(FIXTURES / "mqtt_plaintext.pcap")
    assert meta["format"] == "pcap"
    assert len(packets) >= 2


def test_configured_experiment_flow_excludes_control_plane_protocol_false_positives():
    # SSH-looking control traffic contains bytes that the generic MQTT decoder could
    # otherwise mistake for valid fixed headers. Only the configured broker flow
    # may contribute protocol-level experiment observations.
    packets = [
        Packet(1, 1.0, 60, 60, "10.1.1.163", "10.1.1.18", 6, src_port=50000, dst_port=22, tcp_seq=1, tcp_flags=0x18, tcp_payload=b"\x10\x00\x20\x00"),
        Packet(2, 2.0, 80, 80, "10.1.7.126", "10.1.1.18", 6, src_port=52000, dst_port=8883, tcp_seq=1, tcp_flags=0x18, tcp_payload=b"\x16\x03\x03\x00\x00"),
    ]
    summary = analyse_packets(packets, experiment_flow={
        "host_ip": "10.1.1.18", "port": 8883, "tls_enabled": True, "tls_mode": "classical-server-auth"
    })
    assert summary["tcp"]["connection_count"] == 2
    assert summary["experiment_flow"]["matched_connection_count"] == 1
    assert summary["protocol_observations"]["plaintext_mqtt_counts"] == {}
    assert summary["protocol_observations"]["tls_record_counts"] == {"handshake": 1}
    classes = {tuple(sorted((c["endpoint_a"]["port"], c["endpoint_b"]["port"]))): c["classification"] for c in summary["tcp"]["connections"]}
    assert classes[(22, 50000)] == "other_tcp"
    assert classes[(8883, 52000)] == "experiment_broker"
