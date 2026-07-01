from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path


def load_benchmark_aggregation_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "framework" / "benchmark_aggregation.py"
    spec = importlib.util.spec_from_file_location("framework_benchmark_aggregation", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    scripts_path = repo_root / "scripts"
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    module_path = scripts_path / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_benchmark_manifest(profile_id="ecc256_reference", algorithm="ECC256", signature_algorithm="ecdsa_p256"):
    return {
        "run_id": f"2026-07-01_001_{profile_id}",
        "timestamp": "2026-07-01T10:00:00+10:00",
        "experiment": {"id": f"wolfboot_{signature_algorithm}_uart"},
        "result": "secure_boot_benchmark_repeated_run_passed",
        "secure_boot_benchmark": {
            "schema_version": 1,
            "profile_id": f"wolfboot_{signature_algorithm}_uart",
            "signature_algorithm": signature_algorithm,
            "signature_size_bytes": 64,
            "classical_profile_metadata": {
                "profile_id": profile_id,
                "algorithm": algorithm,
                "signature_algorithm": signature_algorithm,
                "curve": "P-256" if algorithm == "ECC256" else None,
                "key_size_bits": 256 if algorithm == "ECC256" else None,
                "scope_limitations": "hardware values must come from explicit evidence",
            },
            "aggregate_statistics": {
                "status": "available",
                "sample_count": 5,
                "valid_sample_count": 5,
                "failed_sample_count": 0,
                "verification_time_ms": {
                    "minimum": 10,
                    "mean": 12,
                    "median": 12,
                    "maximum": 15,
                    "standard_deviation": 1.87,
                },
                "verification_cycles": {
                    "minimum": 800000,
                    "mean": 960000,
                    "median": 960000,
                    "maximum": 1200000,
                    "standard_deviation": 1200,
                },
                "derived_metrics": {},
                "limitations": [],
            },
            "build_time_metrics": {
                "bootloader_flash_bytes": 42000,
                "static_ram_bytes": 4096,
                "limitations": [],
            },
            "runtime_memory_metrics": {
                "max_stack_used_bytes": 1408,
                "runtime_memory_limitations": ["heap evidence unavailable"],
            },
            "signed_artifact_metrics": {
                "signed_application_size_bytes": 98304,
                "signature_size_bytes": 64,
                "signed_image_overhead_bytes": 8192,
                "signed_image_overhead_percent": 9.09,
                "limitations": [],
            },
            "limitations": [],
        },
    }


def test_build_benchmark_summary_row_flattens_required_phase_11_6_fields(tmp_path):
    aggregation = load_benchmark_aggregation_module()
    manifest = sample_benchmark_manifest()

    row = aggregation.build_benchmark_summary_row(manifest, source_manifest=tmp_path / "manifest.json")

    assert row["profile_id"] == "ecc256_reference"
    assert row["signing_algorithm"] == "ECC256"
    assert row["curve_or_key_size"] == "P-256 / 256 bits"
    assert row["sample_count"] == 5
    assert row["valid_sample_count"] == 5
    assert row["failed_sample_count"] == 0
    assert row["median_verification_time_ms"] == 12
    assert row["mean_verification_time_ms"] == 12
    assert row["minimum_verification_time_ms"] == 10
    assert row["maximum_verification_time_ms"] == 15
    assert row["verification_time_standard_deviation_ms"] == 1.87
    assert row["median_verification_cycles"] == 960000
    assert row["cycles_per_kb"] == 10000
    assert row["time_ms_per_kb"] == 0.125
    assert row["bootloader_flash_size_bytes"] == 42000
    assert row["static_ram_size_bytes"] == 4096
    assert row["maximum_stack_usage_bytes"] == 1408
    assert row["signed_image_size_bytes"] == 98304
    assert row["signature_size_bytes"] == 64
    assert row["size_overhead_bytes"] == 8192
    assert row["size_overhead_percentage"] == 9.09
    assert row["final_profile_verdict"] == "passed"
    assert "heap evidence unavailable" in row["limitations"]


def test_aggregate_benchmark_manifests_writes_json_and_csv_outputs(tmp_path):
    aggregation = load_benchmark_aggregation_module()
    ecc_dir = tmp_path / "results" / "2026-07-01_001_ecc"
    rsa_dir = tmp_path / "results" / "2026-07-01_002_rsa"
    ecc_dir.mkdir(parents=True)
    rsa_dir.mkdir(parents=True)
    ecc_manifest = ecc_dir / "manifest.json"
    rsa_manifest = rsa_dir / "manifest.json"
    ecc_manifest.write_text(json.dumps(sample_benchmark_manifest()), encoding="utf-8")
    rsa_manifest.write_text(
        json.dumps(sample_benchmark_manifest("rsa2048_benchmark", "RSA2048", "rsa2048")),
        encoding="utf-8",
    )

    discovered = aggregation.discover_benchmark_manifests(tmp_path / "results")
    summary = aggregation.aggregate_benchmark_manifests(discovered)
    output_files = aggregation.write_benchmark_summary_outputs(summary, tmp_path / "summary")

    assert [path.name for path in discovered] == ["manifest.json", "manifest.json"]
    assert summary["model_phase"] == "phase_11_6_benchmark_aggregation_output"
    assert summary["input_manifest_count"] == 2
    assert summary["aggregated_profile_count"] == 2
    assert Path(output_files["json"]).exists()
    assert Path(output_files["csv"]).exists()

    json_summary = json.loads(Path(output_files["json"]).read_text(encoding="utf-8"))
    assert json_summary["profiles"][0]["profile_id"] == "ecc256_reference"

    with Path(output_files["csv"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["profile_id"] == "ecc256_reference"
    assert rows[0]["median_verification_time_ms"] == "12"
    assert rows[0]["signed_image_size_bytes"] == "98304"


def test_aggregate_benchmarks_cli_uses_explicit_manifest_inputs(tmp_path, capsys):
    experiment_cli = load_experiment_module()
    run_dir = tmp_path / "run"
    output_dir = tmp_path / "summary"
    run_dir.mkdir()
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(sample_benchmark_manifest()), encoding="utf-8")

    result = experiment_cli.main(
        [
            "aggregate-benchmarks",
            "--manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Benchmark aggregation completed" in captured.out
    assert (output_dir / "benchmark_summary.json").exists()
    assert (output_dir / "benchmark_summary.csv").exists()
