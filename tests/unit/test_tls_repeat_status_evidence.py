"""Unit regressions for TLS repeat hardware evidence; no gateway or key material."""
from __future__ import annotations

import ast
import re
import types
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    """Load the actual parser function without invoking hardware module imports."""
    path = ROOT / "tests/hardware/test_tls_handshake_repeat_hw.py"
    syntax = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = [
        node for node in syntax.body
        if isinstance(node, ast.FunctionDef) and node.name == "_assert_tls_repeat_statuses"
    ]
    assert len(functions) == 1
    module = types.ModuleType("tls_repeat_hardware_evidence_contract")
    module.__dict__.update(json=json, re=re, Path=Path)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), module.__dict__)
    return module


def _status(index: int, **override):
    fields = dict(
        iteration=index, handshake=index, tcp_outcome="connected", tls_outcome="success",
        connect_result=0, failure_stage="none", selected_kex="secp256r1",
        negotiated_kex="secp256r1", kex_match=1, ca_loaded=1,
        peer_identity_configured=1, authentication_verified=1,
        fresh_tcp_connection=1, fresh_tls_context=1, session_resumption=0,
        timing_source="TIM2_1MHz", instrumentation_available=1, cleanup_ok=1,
    )
    fields.update(override)
    return "PQC_TLS_REPEAT_ITERATION schema=1 " + " ".join(
        f"{key}={value}" for key, value in fields.items()
    )


def _stream(tmp_path, *, statuses=None, run_id="unit-run", truncated=False):
    if statuses is None:
        statuses = (_status(0), _status(1))
    records = []
    for status in statuses:
        data = (json.dumps({"type": "tls_handshake_repeat", "text": status}) + "\n").encode()
        base = {"run_id": run_id, "source": "stm32"}
        records.append({"topic": f"pqc/result/stm32/{run_id}/chunk", "payload": {
            "payload": json.dumps({**base, "type": "chunk", "sequence": 0, "data_hex": data.hex()}),
            "qos": 0,
        }})
        if not truncated:
            records.append({"topic": f"pqc/result/stm32/{run_id}/complete", "payload": {
                "payload": json.dumps({**base, "type": "complete", "chunk_count": 1}),
                "qos": 0,
            }})
    path = tmp_path / "mqtt-reporting-raw.ndjson"
    path.write_text("\n".join(json.dumps(rec) for rec in records) + "\n")
    return path


def test_accepts_fresh_completed_authenticated_tls_epochs(tmp_path):
    _module()._assert_tls_repeat_statuses(_stream(tmp_path), "unit-run", 2)


@pytest.mark.parametrize("change", [
    {"tls_outcome": "failed"}, {"authentication_verified": 0},
    {"fresh_tls_context": 0}, {"session_resumption": 1},
    {"cleanup_ok": 0}, {"kex_match": 0}, {"negotiated_kex": "unavailable"},
])
def test_rejects_invalid_tls_outcome(tmp_path, change):
    path = _stream(tmp_path, statuses=(_status(0), _status(1, **change)))
    with pytest.raises(AssertionError):
        _module()._assert_tls_repeat_statuses(path, "unit-run", 2)


def test_rejects_incomplete_epoch(tmp_path):
    with pytest.raises(AssertionError):
        _module()._assert_tls_repeat_statuses(_stream(tmp_path, truncated=True), "unit-run", 2)


def test_rejects_wrong_epoch_identity(tmp_path):
    with pytest.raises(AssertionError):
        _module()._assert_tls_repeat_statuses(
            _stream(tmp_path, statuses=(_status(0), _status(0))), "unit-run", 2
        )


def test_rejects_wrong_run_id(tmp_path):
    with pytest.raises(AssertionError):
        _module()._assert_tls_repeat_statuses(_stream(tmp_path), "different-run", 2)


def test_rejects_malformed_inner_mqtt_payload(tmp_path):
    path = _stream(tmp_path)
    lines = path.read_text().splitlines()
    broken = json.loads(lines[0])
    broken["payload"]["payload"] = json.dumps({"type": "chunk"})
    lines[0] = json.dumps(broken)
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises((AssertionError, KeyError)):
        _module()._assert_tls_repeat_statuses(path, "unit-run", 2)


def test_retained_path_is_file_owned_and_has_no_request_identifier():
    source = (ROOT / "tests/hardware/test_tls_handshake_repeat_hw.py").read_text()
    assert "HardwareFileRun.create(" in source
    assert 'module_name="test_tls_handshake_repeat_hw"' in source
    assert "request12" not in source.lower()
    assert "request-12" not in source.lower()
    assert 'context.run_experiment(case=case_path, name="tls_handshake_repeat")' in source
