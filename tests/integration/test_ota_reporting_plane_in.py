from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_ota_reporting_plane_gateway_prerequisites(pqc_require_capabilities):
    """Live gateway smoke test for the impairment-exempt OTA transport.

    This deliberately does not publish an OTA request: it verifies the gateway
    and reporting broker tooling without leaving retained activation state that
    could later be consumed by a board.
    """
    pqc_require_capabilities("gateway", strict_mode="gateway")
    if os.environ.get("PQC_OTA_GATEWAY", "").strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip("set PQC_OTA_GATEWAY=1 for live Request-5 reporting-plane validation")
    target = os.environ.get("PQC_OTA_GATEWAY_TARGET", "timk@pqc-gateway1.pqcnet")
    completed = subprocess.run(
        ["ssh", target, "sh -c 'command -v mosquitto_pub >/dev/null && command -v mosquitto_sub >/dev/null'"],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
