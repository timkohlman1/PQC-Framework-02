from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RUN_GATEWAY_FLASH_ENV = "PQC_RUN_GATEWAY_FLASH_INTEGRATION"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_gateway_flash_helper_with_real_artifact(tmp_path):
    """Run the real SCP and gateway flash helper only when explicitly enabled."""

    if os.environ.get(RUN_GATEWAY_FLASH_ENV) != "1":
        pytest.skip(f"Set {RUN_GATEWAY_FLASH_ENV}=1 to run the gateway flash integration test.")

    repo_root = _repo_root()
    artifact = repo_root / "build" / "Debug" / "stm32_basic_hal1.elf"
    if not artifact.is_file():
        pytest.skip(f"Build artifact not found: {artifact}")

    results_dir = tmp_path / "results"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/experiment.py",
            "flash",
            "--experiment",
            "configs/experiments/baseline_direct_uart.yaml",
            "--results-dir",
            str(results_dir),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    result_dirs = [path for path in results_dir.iterdir() if path.is_dir()]
    assert len(result_dirs) == 1
    result_dir = result_dirs[0]
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    assert (result_dir / "flash.log").is_file()
    assert manifest["result"] == "flash_passed"
    assert manifest["flash"]["return_code"] == 0
    assert manifest["flash"]["scp_return_code"] == 0
    assert manifest["flash"]["helper_return_code"] == 0
    assert manifest["flash"]["stlink_serial"] == "066EFF3932504E3043111818"
