from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "results"


@dataclass(frozen=True)
class HardwareExperimentCase:
    id: str
    experiment: str
    expected_mode: str
    expected_group: str | None = None

    @property
    def expected_completion_marker(self) -> str:
        return f"PQC_EXPERIMENT_COMPLETE experiment={self.expected_mode} status=done"


CASES = (
    HardwareExperimentCase(
        "plaintext",
        "configs/experiments/mqtt_plaintext_st67_e2e.yaml",
        "plaintext",
    ),
    HardwareExperimentCase(
        "x25519-server-auth",
        "configs/experiments/mqtt_tls_x25519_server_auth_st67_e2e.yaml",
        "classical_tls_server_auth",
        "x25519",
    ),
    HardwareExperimentCase(
        "x25519-mutual-auth",
        "configs/experiments/mqtt_tls_x25519_mutual_auth_st67_e2e.yaml",
        "classical_tls_mutual",
        "x25519",
    ),
    HardwareExperimentCase(
        "secp256r1-server-auth",
        "configs/experiments/mqtt_tls_secp256r1_server_auth_st67_e2e.yaml",
        "classical_tls_server_auth",
        "secp256r1",
    ),
    HardwareExperimentCase(
        "secp256r1-mutual-auth",
        "configs/experiments/mqtt_tls_secp256r1_mutual_auth_st67_e2e.yaml",
        "classical_tls_mutual",
        "secp256r1",
    ),
    HardwareExperimentCase(
        "secp384r1-server-auth",
        "configs/experiments/mqtt_tls_secp384r1_server_auth_st67_e2e.yaml",
        "classical_tls_server_auth",
        "secp384r1",
    ),
    HardwareExperimentCase(
        "secp384r1-mutual-auth",
        "configs/experiments/mqtt_tls_secp384r1_mutual_auth_st67_e2e.yaml",
        "classical_tls_mutual",
        "secp384r1",
    ),
    HardwareExperimentCase(
        "secp521r1-server-auth",
        "configs/experiments/mqtt_tls_secp521r1_server_auth_st67_e2e.yaml",
        "classical_tls_server_auth",
        "secp521r1",
    ),
    HardwareExperimentCase(
        "secp521r1-mutual-auth",
        "configs/experiments/mqtt_tls_secp521r1_mutual_auth_st67_e2e.yaml",
        "classical_tls_mutual",
        "secp521r1",
    ),
    HardwareExperimentCase(
        "X25519MLKEM768-server-auth",
        "configs/experiments/mqtt_tls_X25519MLKEM768_server_auth_st67_e2e.yaml",
        "pqc_hybrid_tls_server_auth",
        "X25519MLKEM768",
    ),
    HardwareExperimentCase(
        "X25519MLKEM768-mutual-auth",
        "configs/experiments/mqtt_tls_X25519MLKEM768_mutual_auth_st67_e2e.yaml",
        "pqc_hybrid_tls_mutual",
        "X25519MLKEM768",
    ),
    HardwareExperimentCase(
        "SecP256r1MLKEM768-server-auth",
        "configs/experiments/mqtt_tls_SecP256r1MLKEM768_server_auth_st67_e2e.yaml",
        "pqc_hybrid_tls_server_auth",
        "SecP256r1MLKEM768",
    ),
    HardwareExperimentCase(
        "SecP256r1MLKEM768-mutual-auth",
        "configs/experiments/mqtt_tls_SecP256r1MLKEM768_mutual_auth_st67_e2e.yaml",
        "pqc_hybrid_tls_mutual",
        "SecP256r1MLKEM768",
    ),
    HardwareExperimentCase(
        "SecP384r1MLKEM1024-server-auth",
        "configs/experiments/mqtt_tls_SecP384r1MLKEM1024_server_auth_st67_e2e.yaml",
        "pqc_hybrid_tls_server_auth",
        "SecP384r1MLKEM1024",
    ),
    HardwareExperimentCase(
        "SecP384r1MLKEM1024-mutual-auth",
        "configs/experiments/mqtt_tls_SecP384r1MLKEM1024_mutual_auth_st67_e2e.yaml",
        "pqc_hybrid_tls_mutual",
        "SecP384r1MLKEM1024",
    ),
)


def _manifest_paths() -> set[Path]:
    if not RESULTS_ROOT.exists():
        return set()
    return {path.resolve() for path in RESULTS_ROOT.glob("*/manifest.json")}


def _new_result_dir(before: set[Path]) -> Path:
    created = _manifest_paths() - before
    assert len(created) == 1, (
        "expected exactly one new result manifest, found "
        f"{len(created)}: {sorted(str(path) for path in created)}"
    )
    return next(iter(created)).parent


@pytest.mark.hardware
@pytest.mark.long
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_all_mqtt_profiles_end_to_end(
    case: HardwareExperimentCase,
    request: pytest.FixtureRequest,
    pqc_require_capabilities,
):
    """Run each maintained MQTT profile through the normal hardware workflow."""
    if not request.config.getoption("--pqc-hardware-experiment-matrix"):
        pytest.skip(
            "full MQTT hardware matrix is opt-in; "
            "pass --pqc-hardware-experiment-matrix"
        )

    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        "uart_device",
        strict_mode="hardware",
    )

    before = _manifest_paths()
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/experiment.py",
            "run",
            "--experiment",
            case.experiment,
            "--force",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        created = _manifest_paths() - before
        result_details = ""
        if len(created) == 1:
            failed_result_dir = next(iter(created)).parent
            manifest_path = failed_result_dir / "manifest.json"
            uart_path = failed_result_dir / "uart.log"
            manifest_summary = "unavailable"
            uart_tail = "unavailable"
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    mqtt_e2e = manifest.get("mqtt_e2e", {})
                    manifest_summary = json.dumps(
                        {
                            "result": manifest.get("result"),
                            "return_code": mqtt_e2e.get("return_code"),
                            "failure_stage": mqtt_e2e.get("failure_stage"),
                            "missing_uart_markers": mqtt_e2e.get("missing_uart_markers"),
                        },
                        sort_keys=True,
                    )
                except (OSError, ValueError, TypeError):
                    manifest_summary = "unreadable"
            if uart_path.is_file():
                uart_lines = uart_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                uart_tail = "\n".join(uart_lines[-60:])
            result_details = (
                f"\nresult_dir: {failed_result_dir}"
                f"\nmanifest_summary: {manifest_summary}"
                f"\nuart_tail:\n{uart_tail}\n"
            )
        pytest.fail(
            f"command failed for {case.experiment}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
            f"{result_details}"
        )

    result_dir = _new_result_dir(before)
    manifest_path = result_dir / "manifest.json"
    uart_path = result_dir / "uart.log"
    broker_path = result_dir / "mqtt-broker-log.log"

    assert manifest_path.is_file()
    assert uart_path.is_file()
    assert broker_path.is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    uart_text = uart_path.read_text(encoding="utf-8", errors="replace")
    evidence = manifest["mqtt_e2e"]

    assert manifest["result"] == "baseline_run_passed"
    assert evidence["return_code"] == 0
    assert evidence["failure_stage"] == "none"
    assert evidence["broker_response_passed"] is True
    assert evidence["missing_uart_markers"] == []
    assert evidence["completion_marker_present"] is True
    assert case.expected_completion_marker in uart_text
    assert (result_dir / evidence["publisher_log"]).is_file()
    assert (result_dir / evidence["subscriber_log"]).is_file()
    assert (result_dir / evidence["broker_message_evidence_log"]).is_file()

    if case.expected_group is not None:
        assert f"key_exchange_group={case.expected_group}" in uart_text
