"""Self-contained Request-12 repeated TLS workload hardware validation."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.config_resolver import ConfigResolver
from framework.result_collector import _parse_raw_stream


pytestmark = [pytest.mark.hardware, pytest.mark.long]

TEST_GENERATED_ROOT = (
    REPO_ROOT
    / ".pqc-generated-state"
    / "hardware-tests"
    / "request12-tls-handshake-repeat"
)


def _clean_subprocess_env() -> dict[str, str]:
    """Return deterministic environment for the self-contained hardware run."""
    env = os.environ.copy()
    # This hardware test owns resolution/build/runtime evidence. Do not allow
    # retained-result selectors or the superseded Request-12 opt-in flag to
    # alter the run.
    env.pop("PQC_TEST_RESULT_DIR", None)
    env.pop("PQC_TLS_REPEAT_HW", None)
    env["PQC_BUILD_PURPOSE"] = "experiment"
    return env


def _latest_run(results_dir: Path) -> Path:
    candidates = [
        path
        for path in results_dir.iterdir()
        if path.is_dir() and (path / "manifest.json").is_file()
    ]
    assert candidates, f"no experiment run produced under {results_dir}"
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def _materialize_case() -> Path:
    """Resolve Request 12 into the isolated framework generated-state volume."""
    resolver = ConfigResolver(REPO_ROOT)
    shutil.rmtree(TEST_GENERATED_ROOT, ignore_errors=True)
    generated = resolver.materialize_campaign(
        "tls_handshake_repeat",
        TEST_GENERATED_ROOT,
    )
    cases = sorted((generated / "cases").glob("*.yaml"))
    assert cases, "Request-12 campaign resolution produced no cases"
    return cases[0]


def _run_hardware_case(
    case_path: Path,
    results_dir: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/experiment.py",
            "run",
            "--experiment",
            str(case_path),
            "--results-dir",
            str(results_dir),
        ],
        cwd=REPO_ROOT,
        env=_clean_subprocess_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


@pytest.fixture(scope="module")
def tls_repeat_test_workspace(tmp_path_factory):
    # scripts/dev.sh pytest-hardware overlays /workspace/build and
    # /workspace/.pqc-generated-state with anonymous Docker volumes. This test
    # therefore owns fresh build/generated state without modifying host state.
    root = tmp_path_factory.mktemp("request12-tls-repeat-self-contained")
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(TEST_GENERATED_ROOT, ignore_errors=True)


@pytest.mark.hardware
@pytest.mark.long
def test_multiple_full_tls_handshakes_are_recorded_within_one_boot(
    pqc_require_capabilities,
    tls_repeat_test_workspace: Path,
):
    """Check normal experiment execution and required raw-capture completeness."""
    pqc_require_capabilities(
        "local_toolchain",
        "gateway",
        "flash_helper",
        "uart_device",
        strict_mode="hardware",
    )

    case_path = _materialize_case()
    resolver = ConfigResolver(REPO_ROOT)
    case = resolver.load_resolved_case(case_path)
    bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
    expected = int(
        bundle["experiment"]["workload"]["iterations"]["handshakes_per_run"]
    )
    assert expected >= 2

    # /workspace/results is host bind-mounted by scripts/dev.sh pytest-hardware.
    # Unlike build and .pqc-generated-state, it survives container teardown.
    # Write the normal experiment result tree here from the beginning so that
    # both successful runs and partially completed failed runs are retained.
    results_dir = (
        REPO_ROOT
        / "results"
        / "automated-tests"
        / "request12-tls-handshake-repeat"
        / uuid.uuid4().hex
        / "experiment-results"
    )
    results_dir.mkdir(parents=True, exist_ok=False)
    print(f"Request-12 retained experiment results: {results_dir}", flush=True)
    completed = _run_hardware_case(case_path, results_dir)
    assert completed.returncode == 0, (
        f"Experiment results retained at: {results_dir}\n"
        + completed.stdout
        + "\n"
        + completed.stderr
    )

    run_dir = _latest_run(results_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    # The final capture-only manifest is authoritative after run finalization.
    # The operational result_collection section is not retained in that schema.
    assert manifest["capture_acceptance"]["accepted"] is True, (
        f"capture not accepted: {manifest['capture_acceptance']}"
    )
    assert manifest["capture_acceptance"]["scope"] == "capture_integrity_only"
    assert manifest["run"]["return_code"] == 0
    assert manifest["run"]["state"] == "finalized"

    # Require the expected telemetry artifact in the finalized capture inventory
    # and validate the configured number of complete epochs with the existing
    # framework collector. This checks output integrity, not scientific results.
    streams = [
        item for item in manifest["artifacts"]
        if item.get("role") == "stm32_result_stream"
    ]
    assert len(streams) == 1, f"expected one STM32 result artifact: {streams}"
    stream = streams[0]
    assert stream["requirement"] == "required"
    assert stream["acquisition"]["status"] == "available"
    assert stream["path"] is not None
    raw = run_dir / stream["path"]
    assert raw.is_file(), f"retained STM32 result stream is missing: {raw}"
    validation = _parse_raw_stream(
        raw,
        manifest["run"]["id"],
        ("stm32",),
        {"stm32": expected},
    )
    assert validation.passed, validation.failure_reasons
    assert validation.source_results["stm32"]["completion_count"] == expected

    # Check the framework capture contract, not the scientific interpretation
    # of individual TLS timing or instrumentation records. Those observations
    # remain in the complete retained result package for later ingestion.
    # Minimal/suppressed UART is allowed; no optional UART marker is required.
