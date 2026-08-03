from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class HardwareExperimentCase:
    id: str
    experiment: str
    boot_args: tuple[str, ...]
    expected_boot_crypto: str | None
    expected_completion_marker: str

CASES = (
    HardwareExperimentCase("plaintext-direct", "configs/experiments/mqtt_plaintext_st67_e2e.yaml", ("--boot-mode", "direct_flash"), None, "PQC_EXPERIMENT_COMPLETE experiment=plaintext status=done"),
    HardwareExperimentCase("plaintext-integrity", "configs/experiments/mqtt_plaintext_st67_e2e.yaml", ("--boot-mode", "wolfboot", "--boot-algorithm", "integrity_sha256"), "integrity_sha256", "PQC_EXPERIMENT_COMPLETE experiment=plaintext status=done"),
    HardwareExperimentCase("classical-mtls-direct", "configs/experiments/mqtt_tls_secp256r1_mutual_auth_st67_e2e.yaml", ("--boot-mode", "direct_flash"), None, "PQC_EXPERIMENT_COMPLETE experiment=classical_tls_mutual status=done"),
    HardwareExperimentCase("classical-mtls-integrity", "configs/experiments/mqtt_tls_secp256r1_mutual_auth_st67_e2e.yaml", ("--boot-mode", "wolfboot", "--boot-algorithm", "integrity_sha256"), "integrity_sha256", "PQC_EXPERIMENT_COMPLETE experiment=classical_tls_mutual status=done"),
    HardwareExperimentCase("pqc-hybrid-mtls-mldsa65", "configs/experiments/mqtt_tls_SecP256r1MLKEM768_mutual_auth_st67_e2e.yaml", ("--boot-mode", "wolfboot", "--boot-algorithm", "mldsa65"), "mldsa65", "PQC_EXPERIMENT_COMPLETE experiment=pqc_hybrid_tls_mutual status=done"),
)

def _result_dir(results_root: Path) -> Path:
    manifests = sorted(results_root.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime_ns)
    assert len(manifests) == 1
    return manifests[0].parent

@pytest.mark.hardware
@pytest.mark.long
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_mqtt_experiment_matrix(case: HardwareExperimentCase, tmp_path: Path, request: pytest.FixtureRequest, pqc_require_capabilities):
    if not request.config.getoption("--pqc-hardware-experiment-matrix"):
        pytest.skip("full MQTT hardware matrix is opt-in; pass --pqc-hardware-experiment-matrix")
    pqc_require_capabilities("local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware")
    results_root = tmp_path / "results"
    completed = subprocess.run([sys.executable, "scripts/experiment.py", "run", "--experiment", case.experiment, "--results-dir", str(results_root), "--force", *case.boot_args], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    result_dir = _result_dir(results_root)
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    uart_text = (result_dir / "uart.log").read_text(encoding="utf-8", errors="replace")
    assert manifest["result"] == "baseline_run_passed"
    assert manifest["mqtt_e2e"]["return_code"] == 0
    assert manifest["mqtt_e2e"]["failure_stage"] == "none"
    assert manifest["mqtt_e2e"]["broker_response_passed"] is True
    assert manifest["mqtt_e2e"]["missing_uart_markers"] == []
    assert case.expected_completion_marker in uart_text
    if case.expected_boot_crypto is None:
        assert manifest.get("boot_crypto") in {None, "none"}
    else:
        assert manifest["boot_crypto"] == case.expected_boot_crypto
        assert manifest["secure_boot_flash"]["return_code"] == 0
