#!/usr/bin/env python3
"""Validate retained STM32 benchmark streams and summarize RAW DWT cycles.

Use on an accepted hardware-test evidence directory, not as substitute for the
framework's manifest/capture-acceptance checks. Never normalize by clock rate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

OPERATIONS = (
    "sha256_hash", "mlkem_keygen", "mlkem_encapsulate", "mlkem_decapsulate",
    "mldsa_keygen", "mldsa_sign", "mldsa_verify",
)


def read_stream(path: Path) -> list[dict]:
    chunks: dict[int, bytes] = {}
    completions: list[dict] = []
    run_id: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        envelope = json.loads(raw_line)
        packet = envelope["payload"]
        if isinstance(packet, dict) and "payload" in packet:
            packet = packet["payload"]
        packet = json.loads(packet) if isinstance(packet, str) else packet
        if packet.get("source") != "stm32":
            raise ValueError(f"{path}: unexpected source")
        if run_id is None:
            run_id = packet["run_id"]
        if packet["run_id"] != run_id:
            raise ValueError(f"{path}: mixed run IDs")
        if packet["type"] == "chunk":
            seq = packet["sequence"]
            if seq in chunks:
                raise ValueError(f"{path}: duplicated sequence {seq}")
            chunks[seq] = bytes.fromhex(packet["data_hex"])
        elif packet["type"] == "complete":
            completions.append(packet)
        else:
            raise ValueError(f"{path}: unexpected packet type")
    if len(completions) != 1:
        raise ValueError(f"{path}: expected one completion, got {len(completions)}")
    complete = completions[0]
    if sorted(chunks) != list(range(complete["chunk_count"])):
        raise ValueError(f"{path}: incomplete or non-contiguous chunks")
    data = b"".join(chunks[i] for i in range(len(chunks)))
    records = [json.loads(line) for line in data.splitlines() if line.strip()]
    if (len(data) != complete["logical_bytes"] or
            len(records) != complete["record_count"] or
            hashlib.sha256(data).hexdigest() != complete["logical_sha256"] or
            complete["dropped_record_count"] != 0 or complete["overflowed"]):
        raise ValueError(f"{path}: result completion or integrity mismatch")
    return records


def summarize(records: list[dict], *, expected_repetitions: int = 10) -> dict:
    benchmark = [json.loads(item["text"]) for item in records
                 if item.get("context") == "baremetal_benchmark"]
    provenance = [r for r in benchmark if r.get("type") == "benchmark_provenance"]
    complete = [r for r in benchmark if r.get("type") == "complete"]
    samples = [r for r in benchmark if "operation" in r]
    if len(provenance) != 1 or len(complete) != 1:
        raise ValueError("missing or duplicate benchmark provenance/completion")
    if (provenance[0]["self_test_status"] != 0 or
            provenance[0]["iterations"] != expected_repetitions or
            complete[0]["dropped"] != 0 or complete[0]["overflowed"] != 0 or
            complete[0]["records"] != len(samples)):
        raise ValueError("benchmark self-test, capacity or iteration check failed")
    if len(samples) != 7 * expected_repetitions + 6:
        raise ValueError(f"missing/duplicate benchmark operation records: {len(samples)}")
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    unavailable: list[dict] = []
    for sample in samples:
        if sample["outcome"] == 1:
            if (sample["cycles"] != 0 or sample["reason"] != "algorithm_not_compiled" or
                    sample["iteration"] != 0):
                raise ValueError("invalid unavailable-operation record")
            unavailable.append(sample)
            continue
        if (sample["outcome"] != 0 or sample["result"] != 0 or
                sample["cycles"] <= 0 or sample["cycles"] > 0x7FFFFFFF or
                sample["interrupts_masked"] != 1):
            raise ValueError(f"invalid measurement: {sample}")
        grouped[(sample["operation"], sample["parameter"])].append(sample)
    selected = {param for name, param in grouped if name == "mlkem_keygen"}
    if len(selected) != 1:
        raise ValueError("missing selected ML-KEM parameter")
    selected_parameter = next(iter(selected))
    expected_unavailable = {(name, parameter) for name in OPERATIONS
                            if name.startswith("mlkem_")
                            for parameter in ("ML_KEM_512", "ML_KEM_768", "ML_KEM_1024")
                            if parameter != selected_parameter}
    if {(r["operation"], r["parameter"]) for r in unavailable} != expected_unavailable:
        raise ValueError("missing/incorrect unavailable ML-KEM records")
    observed = {name for name, _ in grouped}
    if observed != set(OPERATIONS) or len(grouped) != len(OPERATIONS):
        raise ValueError(f"incomplete selected operation set: {sorted(observed)}")
    summary = []
    for (operation, parameter), items in sorted(grouped.items()):
        iterations = sorted(item["iteration"] for item in items)
        if iterations != list(range(expected_repetitions)):
            raise ValueError(f"non-contiguous repetitions: {operation}/{parameter}")
        cycles = [item["cycles"] for item in items]
        summary.append({"operation": operation, "parameter": parameter,
                        "n": len(cycles), "min_cycles": min(cycles),
                        "median_cycles": statistics.median(cycles),
                        "mean_cycles": statistics.mean(cycles),
                        "max_cycles": max(cycles),
                        "stdev_cycles": statistics.stdev(cycles) if len(cycles) > 1 else None})
    return {"hclk_hz": provenance[0]["hclk_hz"], "cycle_counter": "DWT_CYCCNT",
            "statistics": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_dir", type=Path)
    parser.add_argument("--output", type=Path, help="Optional generated JSON summary file")
    args = parser.parse_args()
    paths = sorted(args.evidence_dir.rglob("mqtt-reporting-raw.ndjson"))
    if len(paths) != 3:
        parser.error(f"Expected exactly three benchmark raw streams, found {len(paths)}")
    results = []
    for path in paths:
        summary = summarize(read_stream(path))
        summary["source_path"] = str(path)
        results.append(summary)
    payload = json.dumps({"benchmark_schema": 1, "runs": results}, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
