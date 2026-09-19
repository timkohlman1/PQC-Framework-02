"""Capability-gated Request-12 repeated TLS workload hardware validation."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.config_resolver import ConfigResolver
from framework.result_collector import _parse_raw_stream


def _enabled() -> bool:
    return os.environ.get("PQC_TLS_REPEAT_HW", "").strip().lower() in {"1", "true", "yes", "on"}


def _latest_run(results_dir: Path) -> Path:
    candidates = [path for path in results_dir.iterdir() if path.is_dir() and (path / "manifest.json").is_file()]
    assert candidates, f"no experiment run produced under {results_dir}"
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _logical_epochs(path: Path, run_id: str) -> list[str]:
    epochs: list[str] = []
    chunks: dict[int, bytes] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        outer = json.loads(line)
        payload = outer.get("payload")
        if isinstance(payload, dict) and "payload" in payload:
            payload = payload["payload"]
        obj = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(obj, dict) or obj.get("run_id") != run_id or obj.get("source") != "stm32":
            continue
        if obj.get("type") == "chunk":
            chunks[int(obj["sequence"])] = bytes.fromhex(str(obj["data_hex"]))
        elif obj.get("type") == "complete":
            epochs.append(b"".join(chunks[index] for index in sorted(chunks)).decode("utf-8", errors="replace"))
            chunks = {}
    assert not chunks, "trailing STM32 result chunks were not completed"
    return epochs


@pytest.mark.hardware
def test_multiple_full_tls_handshakes_are_recorded_within_one_boot(tmp_path: Path):
    if not _enabled():
        pytest.skip("set PQC_TLS_REPEAT_HW=1 to run live Request-12 validation")

    campaign_path = REPO_ROOT / "configs" / "campaigns" / "tls_handshake_repeat.yaml"
    if not campaign_path.is_file():
        pytest.fail("canonical configs/campaigns/tls_handshake_repeat.yaml is required for Request 12")

    resolver = ConfigResolver(REPO_ROOT)
    generated = resolver.materialize_campaign("tls_handshake_repeat", tmp_path / "generated")
    case_path = sorted((generated / "cases").glob("*.yaml"))[0]
    case = resolver.load_resolved_case(case_path)
    bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
    expected = int(bundle["experiment"]["workload"]["iterations"]["handshakes_per_run"])
    assert expected >= 2

    results_dir = tmp_path / "results"
    completed = subprocess.run(
        [sys.executable, "scripts/experiment.py", "run", "--experiment", str(case_path), "--results-dir", str(results_dir)],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr

    run_dir = _latest_run(results_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    collection = manifest["result_collection"]
    assert collection["completion_integrity"] is True
    assert collection["source_integrity"]["stm32"]["completion_count"] == expected

    raw = run_dir / collection["raw_stream"]
    validation = _parse_raw_stream(raw, run_dir.name, ("stm32",), {"stm32": expected})
    assert validation.passed, validation.failure_reasons
    assert len(validation.source_results["stm32"]["streams"]) == expected

    epochs = _logical_epochs(raw, run_dir.name)
    assert len(epochs) == expected
    for iteration, epoch in enumerate(epochs):
        assert f"iteration={iteration} handshake={iteration}" in epoch
        assert "session_resumption=0" in epoch
        assert "fresh_tcp_connection=1 fresh_tls_context=1" in epoch
        assert "PQC_TLS_HANDSHAKE_TIMING" in epoch
        assert "PQC_TLS_EVENT_BUFFER" in epoch

    uart = (run_dir / "uart.log").read_text(encoding="utf-8", errors="replace")
    assert uart.count("FreeRTOS networkTask started: initialization active") == 1
