"""Self-contained repeated TLS workload hardware validation."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.config_resolver import ConfigResolver
from framework.result_collector import _parse_raw_stream
from framework.hardware_test_support import HardwareFileRun, session_result_dir


pytestmark = [pytest.mark.hardware, pytest.mark.long]

def _materialize_case(context: HardwareFileRun) -> Path:
    """Resolve the TLS campaign in this hardware file's private generated state."""
    resolver = ConfigResolver(REPO_ROOT)
    resolved = resolver.materialize_campaign(
        "tls_handshake_repeat", context.generated_root / "tls_handshake_repeat"
    )
    cases = sorted((resolved / "cases").glob("*.yaml"))
    assert len(cases) == 1, f"expected one TLS repeat case, found {len(cases)}"
    evidence = context.evidence_root / "configuration"
    evidence.mkdir(parents=True, exist_ok=False)
    source = REPO_ROOT / "configs" / "campaigns" / "tls_handshake_repeat.yaml"
    (evidence / "campaign.yaml").write_bytes(source.read_bytes())
    (evidence / "resolved-case.yaml").write_bytes(cases[0].read_bytes())
    (evidence / "campaign-resolved.yaml").write_bytes(
        (resolved / "campaign-resolved.yaml").read_bytes()
    )
    return cases[0]


def _assert_tls_repeat_statuses(raw: Path, run_id: str, expected: int) -> None:
    """Inspect firmware outcomes in each independently hash-validated result epoch.

    The caller first validates envelope/source/run-ID/sequence/count/hash through
    the canonical result collector. This step checks the TLS semantics that
    transport integrity alone cannot establish. It is not a timing benchmark.
    """
    assert expected >= 2
    chunks: dict[int, bytes] = {}
    epoch = 0
    for line in raw.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        envelope = json.loads(line)
        payload = envelope["payload"]
        # mosquitto_sub %j adds its own transport metadata around the application
        # JSON payload. Unwrap it exactly as the canonical collector does.
        if isinstance(payload, dict) and "payload" in payload:
            payload = payload["payload"]
        record = json.loads(payload) if isinstance(payload, str) else payload
        assert isinstance(record, dict), "non-object reporting record"
        assert record.get("run_id") == run_id
        assert record["source"] == "stm32"
        kind = record["type"]
        if kind == "chunk":
            sequence = int(record["sequence"])
            assert sequence not in chunks, f"duplicate TLS epoch chunk {sequence}"
            chunks[sequence] = bytes.fromhex(record["data_hex"])
            continue
        assert kind == "complete", f"unexpected reporting record type: {kind}"
        assert set(chunks) == set(range(int(record["chunk_count"]))), (
            f"missing TLS epoch chunks for handshake {epoch}"
        )
        logical = b"".join(chunks[index] for index in range(len(chunks)))
        chunks.clear()
        text = logical.decode("utf-8")
        status_lines = []
        for logical_line in text.splitlines():
            if not logical_line.strip():
                continue
            logical_record = json.loads(logical_line)
            assert isinstance(logical_record, dict), "non-object logical result record"
            # The firmware result-buffer schema uses `context`, not `type`.
            # Require the expected STM32 source and handshake iteration as well.
            if logical_record.get("context") != "tls_handshake_repeat":
                continue
            assert logical_record.get("source") == "stm32", (
                f"TLS handshake {epoch}: invalid logical result source"
            )
            assert logical_record.get("iteration") == epoch, (
                f"TLS handshake {epoch}: mismatched logical result iteration"
            )
            assert logical_record.get("schema_version") == 1, (
                f"TLS handshake {epoch}: unsupported logical result schema"
            )
            status = logical_record.get("text")
            assert isinstance(status, str), f"TLS handshake {epoch}: missing status text"
            if "PQC_TLS_REPEAT_ITERATION schema=1 " in status:
                status_lines.append(status)
        assert len(status_lines) == 1, (
            f"expected exactly one TLS status for handshake {epoch}: {status_lines}"
        )
        match = re.search(r"PQC_TLS_REPEAT_ITERATION schema=1 ([^\"}\r\n]*)", status_lines[0])
        assert match, f"malformed TLS status for handshake {epoch}"
        fields = dict(part.split("=", 1) for part in match.group(1).split() if "=" in part)
        required = {
            "iteration": str(epoch),
            "handshake": str(epoch),
            "tcp_outcome": "connected",
            "tls_outcome": "success",
            "connect_result": "0",
            "failure_stage": "none",
            "kex_match": "1",
            "ca_loaded": "1",
            "peer_identity_configured": "1",
            "authentication_verified": "1",
            "fresh_tcp_connection": "1",
            "fresh_tls_context": "1",
            "session_resumption": "0",
            "timing_source": "TIM2_1MHz",
            "instrumentation_available": "1",
            "cleanup_ok": "1",
        }
        for key, value in required.items():
            assert fields.get(key) == value, (
                f"TLS handshake {epoch}: expected {key}={value}, "
                f"observed {fields.get(key)!r}"
            )
        assert fields.get("negotiated_kex") not in (None, "", "unavailable")
        epoch += 1
    assert not chunks, "TLS result stream ended without a completion record"
    assert epoch == expected, f"expected {expected} TLS status epochs, observed {epoch}"


@pytest.mark.hardware
@pytest.mark.long
def test_multiple_full_tls_handshakes_are_recorded_within_one_boot(
    pytestconfig,
    pqc_require_capabilities,
):
    """Validate retained per-handshake STM32 TLS results in an independent run."""
    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device",
        strict_mode="hardware",
    )
    context = HardwareFileRun.create(
        repo_root=REPO_ROOT,
        session_result_dir=session_result_dir(pytestconfig),
        module_name="test_tls_handshake_repeat_hw",
    )
    case_path = _materialize_case(context)
    resolver = ConfigResolver(REPO_ROOT)
    case = resolver.load_resolved_case(case_path)
    bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
    expected = int(
        bundle["experiment"]["workload"]["iterations"]["handshakes_per_run"]
    )
    assert expected >= 2

    run_dir, _ = context.run_experiment(case=case_path, name="tls_handshake_repeat")
    print(f"TLS handshake repeat retained evidence: {context.evidence_root}", flush=True)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    # The final capture-only manifest is authoritative after run finalization.
    # The operational result_collection section is not retained in that schema.
    assert manifest["capture_acceptance"]["accepted"] is True, (
        f"capture not accepted: {manifest['capture_acceptance']}"
    )
    assert manifest["capture_acceptance"]["scope"] == "capture_integrity_only"
    assert manifest["run"]["return_code"] == 0
    assert manifest["run"]["state"] == "finalized"

    # Require the expected telemetry artifact in the finalized capture inventory
    # and validate the configured number of complete epochs with the existing
    # framework collector. This checks output integrity, not scientific results.
    streams = [
        item for item in manifest["artifacts"]
        if item.get("role") == "stm32_result_stream"
    ]
    assert len(streams) == 1, f"expected one STM32 result artifact: {streams}"
    stream = streams[0]
    assert stream["requirement"] == "required"
    assert stream["acquisition"]["status"] == "available"
    name = stream["path"]
    assert isinstance(name, str) and name and not Path(name).is_absolute()
    raw = (run_dir / name).resolve()
    assert raw.is_relative_to(run_dir.resolve()) and raw.is_file(), (
        f"retained STM32 result stream missing or outside run: {raw}"
    )
    validation = _parse_raw_stream(
        raw,
        manifest["run"]["id"],
        ("stm32",),
        {"stm32": expected},
    )
    assert validation.passed, validation.failure_reasons
    assert validation.source_results["stm32"]["completion_count"] == expected
    _assert_tls_repeat_statuses(raw, manifest["run"]["id"], expected)

    # The firmware outcomes above establish successful TLS and per-iteration
    # cleanup; timing and memory values are not interpreted as benchmarks here.
    # Minimal/suppressed UART is allowed; no optional UART marker is required.
