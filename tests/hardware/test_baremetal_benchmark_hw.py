"""Capability-gated, self-contained STM32 cryptographic benchmark evidence test."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from framework.config_resolver import ConfigResolver
from framework.hardware_test_support import HardwareFileRun, session_result_dir
from framework.result_collector import _parse_raw_stream

pytestmark = [pytest.mark.hardware, pytest.mark.long]


def _logical_records(raw: Path) -> list[dict]:
    chunks: dict[int, bytes] = {}
    records: list[dict] = []
    completed = 0
    for line in raw.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        envelope = json.loads(line)
        payload = envelope["payload"]
        if isinstance(payload, dict) and "payload" in payload:
            payload = payload["payload"]
        message = json.loads(payload) if isinstance(payload, str) else payload
        if message["source"] != "stm32":
            continue
        if message["type"] == "chunk":
            sequence = int(message["sequence"])
            assert sequence not in chunks, "duplicate benchmark reporting chunk"
            chunks[sequence] = bytes.fromhex(message["data_hex"])
        elif message["type"] == "complete":
            assert set(chunks) == set(range(int(message["chunk_count"])))
            logical = b"".join(chunks[n] for n in range(len(chunks)))
            chunks.clear()
            records.extend(json.loads(item) for item in logical.splitlines() if item.strip())
            completed += 1
        else:
            pytest.fail(f"unexpected message type: {message['type']}")
    assert not chunks and completed == 1, "incomplete benchmark reporting epoch"
    return records


@pytest.mark.hardware
@pytest.mark.long
def test_baremetal_crypto_cycles_and_reporting(pytestconfig, pqc_require_capabilities):
    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device",
        strict_mode="hardware",
    )
    context = HardwareFileRun.create(
        repo_root=ROOT,
        session_result_dir=session_result_dir(pytestconfig),
        module_name="test_baremetal_benchmark_hw",
    )
    resolver = ConfigResolver(ROOT)
    resolved = resolver.materialize_campaign(
        "baremetal_benchmark", context.generated_root / "baremetal_benchmark"
    )
    cases = sorted((resolved / "cases").glob("*.yaml"))
    assert len(cases) == 3, "expected ML-KEM-512, 768 and 1024 cases"
    for index, case_path in enumerate(cases):
        run_dir, _ = context.run_experiment(case=case_path, name=f"baremetal_benchmark_{index}")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["capture_acceptance"]["accepted"] is True
        assert manifest["run"]["return_code"] == 0
        streams = [a for a in manifest["artifacts"] if a.get("role") == "stm32_result_stream"]
        assert len(streams) == 1
        raw = run_dir / streams[0]["path"]
        assert raw.is_file()
        validation = _parse_raw_stream(raw, manifest["run"]["id"], ("stm32",), {"stm32": 1})
        assert validation.passed, validation.failure_reasons
        logical = _logical_records(raw)
        data = [json.loads(rec["text"]) for rec in logical
                if rec.get("context") == "baremetal_benchmark"]
        provenance = [r for r in data if r.get("type") == "benchmark_provenance"]
        assert len(provenance) == 1
        assert provenance[0]["hclk_hz"] > 0
        assert provenance[0]["self_test_status"] == 0
        complete = [r for r in data if r.get("type") == "complete"]
        assert len(complete) == 1 and complete[0]["dropped"] == 0
        assert complete[0]["overflowed"] == 0
        measured = [r for r in data if "operation" in r]
        assert len(measured) == complete[0]["records"]
        case = resolver.load_resolved_case(case_path)
        selected = case["choices"]["tls_kex"]
        for iteration in range(10):
            for operation in ("mlkem_keygen", "mlkem_encapsulate", "mlkem_decapsulate"):
                entries = [r for r in measured if r["operation"] == operation
                           and r["parameter"] == selected and r["iteration"] == iteration]
                assert len(entries) == 1, (selected, operation, iteration)
                assert entries[0]["outcome"] == 0 and entries[0]["cycles"] > 0
                assert entries[0]["interrupts_masked"] == 1
            for operation in ("mldsa_keygen", "mldsa_sign", "mldsa_verify"):
                entries = [r for r in measured if r["operation"] == operation
                           and r["parameter"] == "ML_DSA_65" and r["iteration"] == iteration]
                assert len(entries) == 1, (operation, iteration)
                assert entries[0]["outcome"] == 0 and entries[0]["cycles"] > 0
                assert entries[0]["result"] == 0 and entries[0]["interrupts_masked"] == 1
            sha = [r for r in measured if r["operation"] == "sha256_hash"
                   and r["parameter"] == "32_bytes" and r["iteration"] == iteration]
            assert len(sha) == 1 and sha[0]["outcome"] == 0 and sha[0]["cycles"] > 0
        assert len(measured) == 76, "10 x (SHA256 + 3 ML-KEM + 3 ML-DSA) + 6 unavailable"
        assert all(r["outcome"] == 0 for r in measured if r["parameter"] in (selected, "ML_DSA_65", "32_bytes"))
        assert sum(r["outcome"] == 1 for r in measured) == 6
    print(f"STM32 benchmark hardware evidence: {context.evidence_root}", flush=True)
