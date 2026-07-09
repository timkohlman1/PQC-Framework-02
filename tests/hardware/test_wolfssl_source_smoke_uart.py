from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXPERIMENT_CONFIG = "configs/experiments/baseline_direct_uart.yaml"
EXPECTED_SMOKE_MARKER = "wolfSSL build-only smoke:"
EXPECTED_DIGEST = "01b274b19659995cb829a9a925f613109ec02a088f94d9e914a36026cecf00e5"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_cli(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/experiment.py", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def _read_uart_evidence(results_dir: Path) -> str:
    candidates = sorted(results_dir.glob("**/uart*.log"))
    assert candidates, f"No UART logs found under {results_dir}"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in candidates)


def _matching_uart_lines(uart_text: str, marker: str) -> list[str]:
    return [line for line in uart_text.splitlines() if marker in line]


@pytest.mark.hardware
@pytest.mark.long
def test_wolfssl_source_smoke_marker_after_build_flash_uart_capture(tmp_path, pqc_require_capabilities):
    """Build, flash, and capture UART evidence for the Phase M6 wolfSSL smoke.

    This test is capability-gated because it flashes real STM32 hardware through
    the configured gateway and requires UART capture. It verifies only that the
    firmware linked and executed the build-only wolfCrypt SHA-256 smoke path. It
    does not claim TLS handshake, certificate loading, MQTT, Wi-Fi, ST67W61M1, or
    end-to-end network success.
    """

    pqc_require_capabilities("gateway", "flash_helper", "uart_device", strict_mode="hardware")

    repo_root = _repo_root()
    results_dir = tmp_path / "results"

    build_completed = _run_cli(
        repo_root,
        [
            "build",
            "--experiment",
            EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
            "--force",
        ],
    )
    assert build_completed.returncode == 0, (
        f"build stdout:\n{build_completed.stdout}\nbuild stderr:\n{build_completed.stderr}"
    )

    completed = _run_cli(
        repo_root,
        [
            "run",
            "--experiment",
            EXPERIMENT_CONFIG,
            "--results-dir",
            str(results_dir),
        ],
    )
    assert completed.returncode == 0, (
        f"run stdout:\n{completed.stdout}\nrun stderr:\n{completed.stderr}"
    )

    uart_text = _read_uart_evidence(results_dir)
    marker_lines = _matching_uart_lines(uart_text, EXPECTED_SMOKE_MARKER)
    marker_context = "\n".join(marker_lines) or "<no wolfSSL smoke marker lines>"

    assert marker_lines, f"Missing wolfSSL smoke marker. UART evidence:\n{uart_text}"
    assert "source=enabled" in uart_text, marker_context
    assert "sha256=ok" in uart_text, marker_context
    assert f"digest={EXPECTED_DIGEST}" in uart_text, marker_context
    assert "tls_handshake=unavailable" in uart_text
    assert "transport=unavailable" in uart_text
    assert "certs=not-loaded" in uart_text
    assert "secrets=not-compiled-in" in uart_text
    assert "tls_handshake=ok" not in uart_text
    assert "mqtt=connected" not in uart_text
    assert "publish=ok" not in uart_text
