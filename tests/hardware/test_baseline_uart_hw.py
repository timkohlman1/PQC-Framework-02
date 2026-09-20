"""Self-owned baseline UART, ST67 bring-up, and network startup hardware checks.

One resolved, full-UART baseline firmware and one hardware run are shared *only*
within this module. Explicit UART diagnostics are the subject of these tests;
full mode is intentional and is not the default for measurement campaigns.
"""
from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.config_resolver import ConfigResolver
from framework.hardware_test_support import HardwareFileRun, session_result_dir

pytestmark = [pytest.mark.hardware, pytest.mark.long]
EXPECTED_BOOT_MARKER = "stm32-basic_hal1 boot v0.1.0"


@dataclass(frozen=True)
class BaselineEvidence:
    context: HardwareFileRun
    case: Path
    run_dir: Path
    uart_text: str
    manifest: dict
    uart_device: str


def _latest_complete_boot(log_text: str) -> str:
    """Discard the tail of firmware running before the gateway-issued reset."""
    marker_index = log_text.rfind(EXPECTED_BOOT_MARKER)
    assert marker_index >= 0, f"missing boot marker: {EXPECTED_BOOT_MARKER}"
    # Firmware diagnostic lines carry a TIM2 tick prefix. Normalize only that
    # presentation prefix for marker matching; retain the original UART file.
    return "\n".join(
        re.sub(r"^\[tick=\d+\]\s*", "", line)
        for line in log_text[marker_index:].splitlines()
    )


def _indexed_uart(run_dir: Path, manifest: dict) -> Path:
    assert manifest.get("execution_outcome", {}).get("status") == "completed"
    assert manifest["execution_outcome"].get("failure_stage") == "none"
    assert manifest["execution_outcome"].get("result") == "baseline_run_passed"
    assert manifest.get("capture_acceptance", {}).get("accepted") is True
    assert manifest.get("final_index", {}).get("status") == "finalized"
    matches = [item for item in manifest.get("artifacts", []) if item.get("role") == "diagnostic_uart"]
    assert len(matches) == 1, f"expected one indexed diagnostic_uart artifact: {run_dir}"
    name = matches[0].get("path")
    assert isinstance(name, str) and name and not Path(name).is_absolute()
    path = (run_dir / name).resolve()
    assert path.is_relative_to(run_dir.resolve()) and path.is_file(), f"missing retained UART evidence: {path}"
    return path


def _baseline_case_full_uart(context: HardwareFileRun) -> Path:
    """Materialize a fresh baseline with an explicit UART diagnostic override."""
    resolver = ConfigResolver(context.repo_root)
    _, campaign = resolver.load_campaign("baseline")
    campaign = dict(campaign)
    campaign["id"] = f"hw_baseline_uart_{context.generated_root.name[:12]}"
    campaign["matrix"] = {"workload.uart_output_mode": ["full"]}
    root = context.generated_root / "baseline_full_uart"
    root.mkdir(parents=True, exist_ok=False)
    source = root / "campaign.yaml"
    source.write_text(yaml.safe_dump(campaign, sort_keys=False), encoding="utf-8")
    evidence = context.evidence_root / "configuration"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "campaign.yaml").write_bytes(source.read_bytes())
    resolved_root = resolver.materialize_campaign(source, root / "resolved")
    cases = sorted((resolved_root / "cases").glob("*.yaml"))
    assert len(cases) == 1
    (evidence / "resolved-case.yaml").write_bytes(cases[0].read_bytes())
    (evidence / "campaign-resolved.yaml").write_bytes(
        (resolved_root / "campaign-resolved.yaml").read_bytes()
    )
    case = resolver.load_resolved_case(cases[0])
    bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
    assert bundle["experiment"]["firmware"]["uart_output_mode"] == "full"
    return cases[0]


@pytest.fixture(scope="module")
def baseline_evidence(pytestconfig, pqc_capabilities) -> BaselineEvidence:
    missing = [
        capability for name in ("local_toolchain", "gateway", "flash_helper", "uart_device")
        if not (capability := pqc_capabilities.check(name)).available
    ]
    if missing:
        reason = "; ".join(f"{item.name}: {item.reason}" for item in missing)
        if pytestconfig.getoption("--pqc-require-hardware"):
            pytest.fail(f"PQC hardware capability unavailable: {reason}")
        pytest.skip(f"PQC hardware capability unavailable: {reason}")

    context = HardwareFileRun.create(
        repo_root=ROOT,
        session_result_dir=session_result_dir(pytestconfig),
        module_name="test_baseline_uart_hw",
    )
    case = _baseline_case_full_uart(context)
    resolver = ConfigResolver(ROOT)
    bundle = resolver.to_legacy_bundle(resolver.load_resolved_case(case), resolve_secrets=False)
    uart_device = bundle["host"]["uart"]["device"]
    run_dir, _ = context.run_experiment(case=case, name="baseline")
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    log_path = _indexed_uart(run_dir, manifest)
    return BaselineEvidence(
        context, case, run_dir,
        log_path.read_text(encoding="utf-8", errors="replace"),
        manifest, uart_device,
    )


@pytest.mark.short
def test_baseline_uart_monitor(baseline_evidence: BaselineEvidence):
    """Capture live UART from the known image this file has just flashed."""
    results = baseline_evidence.context.evidence_root / "monitor"
    results.mkdir(parents=True, exist_ok=False)
    completed = subprocess.run(
        [sys.executable, "scripts/experiment.py", "monitor", "--experiment",
         str(baseline_evidence.case), "--results-dir", str(results),
         "--duration-seconds", "30", "--restart"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    (results / "experiment.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (results / "experiment.stderr.log").write_text(completed.stderr, encoding="utf-8")
    (results / "experiment.returncode.json").write_text(
        json.dumps({"return_code": completed.returncode}) + "\n", encoding="utf-8"
    )
    assert completed.returncode == 0, f"monitor failed, retained output: {results}"
    logs = sorted((results / "adhoc").glob("uart_monitor_*.log"))
    assert len(logs) == 1, f"expected one retained monitor capture: {results}"
    text = logs[0].read_text(encoding="utf-8", errors="replace")
    assert baseline_evidence.uart_device in text
    assert "Data captured: true" in text
    assert "stdout:" in text
    assert EXPECTED_BOOT_MARKER in text, "monitor did not capture a fresh known-image boot"


def test_baseline_known_image_reports_pre_scheduler_lwip_smoke(baseline_evidence: BaselineEvidence):
    boot = _latest_complete_boot(baseline_evidence.uart_text)
    marker = next(line for line in boot.splitlines()
                  if line.startswith("lwIP runtime smoke: context=pre_scheduler "))
    for field in (
        "scheduler=not_started", "version=", "ip4_format=192.0.2.1",
        "checksum=0x", "network=unavailable", "tls_handshake=unavailable",
        "mqtt_connect=unavailable", "end_to_end=unavailable",
    ):
        assert field in marker, f"missing {field} in {marker}"


def test_baseline_known_image_reports_live_st67_network(baseline_evidence: BaselineEvidence):
    boot = _latest_complete_boot(baseline_evidence.uart_text)
    live = next(line for line in boot.splitlines()
                if line.startswith("lwIP runtime network: context=freertos_task "))
    for field in (
        "scheduler=running", "network=available", "wifi=connected", "link=up",
        "tcp=available", "transport=st67-lwip", "st67w61m1=available",
    ):
        assert field in live, f"missing {field} in {live}"
    _associated_ipv4(boot)


def test_baseline_known_image_reports_st67_spi_bringup(baseline_evidence: BaselineEvidence):
    boot = _latest_complete_boot(baseline_evidence.uart_text)
    markers = (
        "ST67 SPI bring-up: begin", "ST67 SPI bring-up: W6X_Init begin",
        "ST67 SPI bring-up: W6X_Init result=", "ST67 SPI bring-up: complete",
    )
    positions = [boot.index(marker) for marker in markers]
    assert positions == sorted(positions) and len(set(positions)) == len(positions)
    begin = next(line for line in boot.splitlines() if line.startswith(markers[0]))
    complete = next(line for line in boot.splitlines() if line.startswith(markers[-1]))
    assert "evidence=stm32-st67-gpio-spi-bringup-only" in begin
    assert "wifi_association=not-attempted" in begin
    assert "result=passed" in complete
    assert "transport=spi-module-initialized" in complete


def _associated_ipv4(boot: str) -> str:
    """Correlate successful association and DHCP from the *same* retained boot."""
    association = next((line for line in boot.splitlines()
                        if line.startswith("ST67 Wi-Fi association: result=passed ssid=")), None)
    assert association is not None, "missing successful association marker"
    ssid = re.search(r"\bssid=(\S+)", association)
    assert ssid and ssid.group(1), "missing associated SSID"
    dhcp = next((line for line in boot.splitlines()
                 if line.startswith("ST67 DHCP: result=passed ipv4=")), None)
    assert dhcp is not None, "missing successful DHCP marker"
    address = re.search(r"\bipv4=(\S+)", dhcp)
    assert address, "missing DHCP IPv4 address"
    ip = ipaddress.IPv4Address(address.group(1))
    assert not ip.is_unspecified and not ip.is_multicast and not ip.is_loopback
    return str(ip)


def test_baseline_known_image_joins_ap_and_gets_dhcp(baseline_evidence: BaselineEvidence):
    boot = _latest_complete_boot(baseline_evidence.uart_text)
    _associated_ipv4(boot)
