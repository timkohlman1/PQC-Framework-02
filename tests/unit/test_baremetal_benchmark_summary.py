"""Validate strict post-run benchmark statistics independently of hardware."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
module_path = ROOT / "scripts/benchmark_summary.py"
spec = importlib.util.spec_from_file_location("benchmark_summary", module_path)
summary = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = summary
spec.loader.exec_module(summary)


def records():
    data = [{"context": "baremetal_benchmark",
             "text": json.dumps({"type": "benchmark_provenance", "iterations": 10,
                                 "hclk_hz": 120000000, "self_test_status": 0})}]
    for i in range(10):
        for operation in summary.OPERATIONS:
            parameter = ("ML_DSA_65" if operation.startswith("mldsa_") else
                         "ML_KEM_512" if operation.startswith("mlkem_") else "32_bytes")
            data.append({"context": "baremetal_benchmark",
                         "text": json.dumps({"operation": operation, "parameter": parameter,
                                             "iteration": i, "cycles": i + 101,
                                             "result": 0, "outcome": 0,
                                             "interrupts_masked": 1})})
    for parameter in ("ML_KEM_768", "ML_KEM_1024"):
        for operation in ("mlkem_keygen", "mlkem_encapsulate", "mlkem_decapsulate"):
            data.append({"context": "baremetal_benchmark",
                         "text": json.dumps({"operation": operation, "parameter": parameter,
                                             "iteration": 0, "cycles": 0,
                                             "result": 0, "outcome": 1,
                                             "reason": "algorithm_not_compiled",
                                             "interrupts_masked": 0})})
    data.append({"context": "baremetal_benchmark",
                 "text": json.dumps({"type": "complete", "records": 76,
                                     "dropped": 0, "overflowed": 0})})
    return data


def test_summary_retains_raw_cycles_and_all_selected_operations():
    result = summary.summarize(records())
    assert len(result["statistics"]) == 7
    assert all(row["n"] == 10 and row["median_cycles"] == 105.5
               for row in result["statistics"])


def test_summary_rejects_failed_missing_or_invalid_measurements():
    example = records()
    example[1]["text"] = json.dumps({**json.loads(example[1]["text"]), "cycles": 0})
    with pytest.raises(ValueError, match="invalid measurement"):
        summary.summarize(example)
    example = records()
    del example[1]
    with pytest.raises(ValueError, match="self-test|non-contiguous repetitions"):
        summary.summarize(example)
    example = records()
    example[0]["text"] = json.dumps({**json.loads(example[0]["text"]), "self_test_status": -2})
    with pytest.raises(ValueError, match="self-test"):
        summary.summarize(example)
