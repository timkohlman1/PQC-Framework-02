"""Synthetic A1 fixture producer shared by unit and local-process integration tests.

These invented values are hand-checkable test data, not hardware evidence. The
optional real-record excerpt receives new synthetic capture/identity envelopes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from framework.run_evidence import (canonical_sha256, finalize_manifest,
    register_artifact, initial_capture_index)

EXPECTED = {"tls_handshake": 150, "mqtt_readiness": 300, "rtfb": 2100,
            "rtlb": 2600, "ttfb": 900, "ttlb": 1400, "req_tfb": 500, "req_tlb": 1000}


def logical(text: str, iteration: int = 0, context: str = "tls") -> dict:
    return {"schema_version": 1, "source": "stm32", "iteration": iteration,
            "context": context, "text": text}


def rm2_records() -> list[dict]:
    return [
        logical("PQC_RM2_TIMEBASE schema=3 source=TIM2 timer_input_clock_hz=120000000 prescaler=119 counter_hz=1000000 counter_bits=32 wrap_handling=update_irq_64bit_extension reset_origin=operational_wolfboot_entry reset_origin_valid=1 reset_origin_kind=1 reset_origin_to_application_timebase_us=200 handoff_bridge=LPTIM2_HSI16_DIV16", context="rm2_timebase"),
        logical("PQC_RM2_CHECKPOINTS schema=3 reset_origin=operational_wolfboot_entry reset_origin_valid=1 reset_origin_to_application_timebase_us=200 tcp_connect_start_us=1000 mqtt_readiness_checkpoint_us=1300 mqtt_readiness_definition=tcp_connect_start_to_first_mqtt_connack_plaintext_byte mqtt_readiness_us=300 mqtt_readiness_valid=1 application_request_us=1400 application_first_byte_us=1900 application_last_byte_us=2400", context="rm2_checkpoints"),
        logical("PQC_RM2_METRICS schema=3 metric_contract=ready_metrics_2_canonical_v3 payload_bytes=20 received_bytes=20 chunk_bytes=10 rtfb_us=2100 rtlb_us=2600 ttfb_us=900 ttlb_us=1400 req_tfb_us=500 req_tlb_us=1000 application_transfer_us=500 reset_metrics_valid=1 complete_valid=1", context="rm2_metrics"),
        logical("PQC_RM2_COMPLETE schema=3 status=success record_count=4 measurement_complete_us=2400", context="rm2_complete"),
        *tls_records(),
    ]


def tls_records(iteration: int = 0, *, repeat: bool = False) -> list[dict]:
    records = [
        logical("PQC_TLS_HANDSHAKE_TIMING result=1 cycle_counter_available=1 timebase_available=1 start_cycle=10 end_cycle=20 elapsed_cycles=10 start_us=1100 end_us=1250 elapsed_us=150", iteration),
        logical(f"PQC_TLS_EVENT_BUFFER schema=1 iteration={iteration} handshake={iteration} count=1 capacity=64 dropped=0 overflow=0 truncated=0 incomplete=0 invalid_sequence_count=0", iteration),
        logical("PQC_TLS_EVENT sequence=0 parent_sequence=-1 level=2 depth=0 kind=workload name=handshake completed=1 result_available=1 result=1 start_us=1100 end_us=1250 elapsed_us=150", iteration),
    ]
    if repeat:
        records.append(logical(f"PQC_TLS_REPEAT_ITERATION schema=1 iteration={iteration} handshake={iteration} tcp_outcome=connected tls_outcome=success connect_result=0 failure_stage=none timing_source=TIM2_1MHz handshake_elapsed_us=150 instrumentation_available=1 fresh_tcp_connection=1 fresh_tls_context=1 session_resumption=0", iteration, "tls_handshake_repeat"))
    return records


def wire(run_id: str, epochs: list[list[dict]]) -> str:
    output = []
    for records in epochs:
        body = ("\n".join(json.dumps(r, separators=(",", ":")) for r in records) + "\n").encode()
        chunks = [body[index:index + 96] for index in range(0, len(body), 96)]
        base = {"schema_version": 1, "source": "stm32", "run_id": run_id}
        for index, data in enumerate(chunks):
            payload = {**base, "type": "chunk", "sequence": index, "data_hex": data.hex()}
            output.append({"topic": f"pqc/result/stm32/{run_id}/chunk", "payload": {"payload": json.dumps(payload), "qos": 0}})
        payload = {**base, "type": "complete", "chunk_count": len(chunks), "record_count": len(records),
                   "logical_bytes": len(body), "logical_sha256": hashlib.sha256(body).hexdigest(),
                   "overflowed": False, "dropped_record_count": 0}
        output.append({"topic": f"pqc/result/stm32/{run_id}/complete", "payload": json.dumps(payload)})
    return "\n".join(json.dumps(row) for row in output) + "\n"


def make_run(root: Path, *, run_id: str = "synthetic-0001", records: list[dict] | None = None,
             epochs: list[list[dict]] | None = None, application: str = "mqtt_ready_metrics_2",
             failed: bool = False, choices: dict | None = None, transfer: dict | None = None) -> Path:
    root.mkdir(parents=True)
    transfer = transfer or {"payload_bytes": 20, "chunk_bytes": 10}
    selection = {"tls_kex": "secp256r1", "auth_mode": "server", "secure_boot": "integrity_sha256",
                 "firmware_mode": "single_bank", "network_condition": "baseline",
                 "boot_stack_profiling": False, "boot_uart_diagnostics": False, **(choices or {})}
    identity = canonical_sha256(selection)
    config = {"configuration_identity": identity, "firmware_identity": "b" * 64,
              "campaign_execution": {"campaign_id": "synthetic", "case_id": "synthetic-case",
                                     "repetition_index": 3, "condition_identity": "c" * 64}}
    snapshot = {"schema": {"name": "pqc-resolved-case-snapshot", "version": 1},
        "configuration": {**config, "schema_version": 1, "resolver_version": 1, "choices": selection,
                          "selected_profiles": {"workload": application, "target": "synthetic-target", "gateway": "synthetic-gateway"}},
        "effective_non_secret_parameters": {"firmware": {"application": application},
            "mqtt": {"tls": {"mode": "classical_tls_server_auth", "authentication": "server", "key_exchange_group": "secp256r1", "certificate_profile": "rsa3072"}, "transfer": transfer}, "network": {}}}
    provenance = {"schema": {"name": "pqc-run-provenance", "version": 1}, "records": {
        "build_number": "00042", "firmware": {"sha256": "d" * 64}, "source": {"commit": "e" * 40}}}
    (root / "resolved-case.json").write_text(json.dumps(snapshot), encoding="utf-8")
    (root / "run-provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    if not failed:
        (root / "mqtt-reporting-raw.ndjson").write_text(wire(run_id, epochs if epochs is not None else [records if records is not None else rm2_records()]), encoding="utf-8")
    contract = {"version": 2, "experiment_class": "tls_runtime", "features": {"tls_runtime": True},
        "items": [{"role": role, "requirement": "required", "source_class": "synthetic_fixture"}
                  for role in ("resolved_case_snapshot", "run_provenance", "stm32_result_stream")]}
    manifest = {"schema": {"name": "pqc-run-evidence", "version": 3},
        "run": {"id": run_id, "state": "finalized", "return_code": 13 if failed else 0},
        "configuration": config, "capture_contract": contract, "artifacts": initial_capture_index(contract),
        "retained_files": [], "execution_outcome": {"status": "failed" if failed else "completed",
             "result": "synthetic_failure" if failed else "synthetic_success", "failure_stage": "broker_readiness" if failed else None}}
    for role, name in (("resolved_case_snapshot", "resolved-case.json"), ("run_provenance", "run-provenance.json"), ("stm32_result_stream", "mqtt-reporting-raw.ndjson")):
        if (root / name).exists():
            register_artifact(manifest, result_dir=root, role=role, path=root / name, stage="synthetic_fixture", tool=__name__)
    finalize_manifest(manifest, finalized_at="synthetic-test-time")
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def reseal(root: Path, *, refresh_files: bool = True) -> None:
    """Intentionally reseal SYNTHETIC tests only; never use this on real captures."""
    p = root / "manifest.json"
    manifest = json.loads(p.read_text())
    if refresh_files:
        for item in manifest["artifacts"]:
            name = item.get("path")
            if name and (root / name).is_file():
                data = (root / name).read_bytes()
                item.update(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
    finalize_manifest(manifest, finalized_at="synthetic-test-time")
    p.write_text(json.dumps(manifest), encoding="utf-8")
