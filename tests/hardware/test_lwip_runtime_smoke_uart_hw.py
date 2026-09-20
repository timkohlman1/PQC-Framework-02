"""File-owned, gateway-mediated ST67 T02 network and lwIP UART evidence.

This is a diagnostic UART test: full output is required only for this test's
self-provisioned baseline firmware, not for measurement workloads.
"""
from __future__ import annotations

import ipaddress
import json
import re
import sys
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


def _latest_complete_boot(log_text: str) -> str:
    """Use the latest captured boot only; normalize display ticks for matching."""
    marker_index = log_text.rfind(EXPECTED_BOOT_MARKER)
    assert marker_index >= 0, "missing known-image boot marker in retained UART"
    return "\n".join(
        re.sub(r"^\[tick=\d+\]\s*", "", line)
        for line in log_text[marker_index:].splitlines()
    )


def _indexed_uart(run_dir: Path) -> str:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    outcome = manifest.get("execution_outcome", {})
    assert outcome.get("status") == "completed"
    assert outcome.get("failure_stage") == "none"
    assert outcome.get("result") == "baseline_run_passed"
    assert manifest.get("capture_acceptance", {}).get("accepted") is True
    assert manifest.get("final_index", {}).get("status") == "finalized"
    matches = [item for item in manifest.get("artifacts", [])
               if item.get("role") == "diagnostic_uart"]
    assert len(matches) == 1, "expected precisely one indexed UART artifact"
    name = matches[0].get("path")
    assert isinstance(name, str) and name and not Path(name).is_absolute()
    uart = (run_dir / name).resolve()
    assert uart.is_relative_to(run_dir.resolve()) and uart.is_file(), "retained UART missing or outside run"
    return uart.read_text(encoding="utf-8", errors="replace")


def _live_network_line(boot: str) -> str:
    lines = [line for line in boot.splitlines()
             if line.startswith("lwIP runtime network: context=freertos_task ")]
    assert lines, "missing live lwIP network marker in latest boot"
    live = lines[-1]
    for field in (
        "evidence=stm32-st67-t02-live-state", "network=available", "wifi=connected",
        "link=up", "scheduler=running",
    ):
        assert field in live, f"missing {field} from latest live-state marker"
    match = re.search(r"\bip=((?:\d{1,3}\.){3}\d{1,3})\b", live)
    assert match, "missing live IP address"
    ip = ipaddress.IPv4Address(match.group(1))
    assert not (ip.is_unspecified or ip.is_multicast or ip.is_loopback), "invalid live IP address"
    return live


def _assert_t02_network(boot: str) -> None:
    """Validate SPI, association, DHCP and live network state from the latest boot."""
    assert "ST67 SPI bring-up: complete result=passed" in boot
    assert "ST67 Wi-Fi association: result=passed" in boot
    assert "ST67 DHCP: result=passed" in boot
    assert boot.index("ST67 SPI bring-up: complete result=passed") < boot.index("ST67 Wi-Fi association: result=passed")
    assert boot.index("ST67 Wi-Fi association: result=passed") < boot.index("ST67 DHCP: result=passed")
    live = _live_network_line(boot)
    association = next((line for line in boot.splitlines()
                        if line.startswith("ST67 Wi-Fi association: result=passed ")), None)
    dhcp = next((line for line in boot.splitlines()
                 if line.startswith("ST67 DHCP: result=passed ipv4=")), None)
    assert association is not None and dhcp is not None, "missing association or DHCP evidence"
    dhcp_match = re.search(r"\bipv4=(\S+)", dhcp)
    assert dhcp_match, "missing DHCP IPv4 address"
    dhcp_ip = ipaddress.IPv4Address(dhcp_match.group(1))
    assert not (dhcp_ip.is_unspecified or dhcp_ip.is_multicast or dhcp_ip.is_loopback)
    assert f"ip={dhcp_ip}" in live, "live-state IP differs from latest-boot DHCP"
    assert "[tick=" not in boot, "timestamp normalization failed"
    later_text = boot[boot.index(live):]
    for stale_marker in ("network=unavailable", "wifi=unavailable",
                         "link=unavailable", "ip=unavailable"):
        assert stale_marker not in later_text, f"contradictory state after live marker: {stale_marker}"
    timeout_lines = [line for line in later_text.splitlines()
                     if "waiting for spi txn ready timeouted" in line]
    for line in timeout_lines:
        for field in (
            "ready_level=", "ready_irq_count=", "ready_rising_count=",
            "ready_falling_count=", "last_rising_tick=", "last_falling_tick=",
            "current_tick=", "current_event_bits=", "last_task_wake_bits=",
            "last_selected_event=", "last_do_xfer_flags=", "txbuf_present=",
            "txq_waiting=", "tx_enqueue_count=", "last_tx_enqueue_tick=",
            "xfer_attempt_count=", "xfer_success_count=", "last_xfer_tick=",
            "last_xfer_result=", "last_pre_ready=", "last_post_ready=",
            "ready_before_cs=", "ready_after_cs_assert=", "last_cs_assert_tick=",
            "last_cs_deassert_tick=", "hw_xfer_start_tick=", "hw_xfer_done_tick=",
            "hw_xfer_done_count=", "hw_wait_result=",
        ):
            assert field in line, f"missing SPI timeout diagnostic {field}"
        assert re.search(r"ready_level=[01]\b", line)
        irq = int(re.search(r"ready_irq_count=(\d+)", line).group(1))
        rising = int(re.search(r"ready_rising_count=(\d+)", line).group(1))
        falling = int(re.search(r"ready_falling_count=(\d+)", line).group(1))
        assert irq == rising + falling
        for key in ("current_event_bits", "last_task_wake_bits", "last_selected_event",
                    "last_do_xfer_flags"):
            assert re.search(rf"{key}=0x[0-9a-fA-F]+\b", line)
        for key in ("txbuf_present", "last_pre_ready", "last_post_ready",
                    "ready_before_cs", "ready_after_cs_assert"):
            assert re.search(rf"{key}=[01]\b", line)
        for key in ("last_cs_assert_tick", "last_cs_deassert_tick",
                    "hw_xfer_start_tick", "hw_xfer_done_tick", "hw_xfer_done_count"):
            assert re.search(rf"{key}=\d+\b", line)
        assert re.search(r"hw_wait_result=-?\d+\b", line)


@pytest.mark.long
def test_st67_t02_wifi_link_and_dhcp_live_evidence(pytestconfig, pqc_require_capabilities):
    """Freshly build/flash and validate normal T02 startup on a single STM32."""
    pqc_require_capabilities(
        "local_toolchain", "gateway", "flash_helper", "uart_device", strict_mode="hardware"
    )
    context = HardwareFileRun.create(
        repo_root=ROOT, session_result_dir=session_result_dir(pytestconfig),
        module_name="test_lwip_runtime_smoke_uart_hw",
    )
    resolver = ConfigResolver(ROOT)
    _, campaign = resolver.load_campaign("baseline")
    campaign = dict(campaign)
    campaign["id"] = f"hw_lwip_t02_{context.generated_root.name[:12]}"
    campaign["matrix"] = {"workload.uart_output_mode": ["full"]}
    source_root = context.generated_root / "full_uart"
    source_root.mkdir(parents=True, exist_ok=False)
    source = source_root / "campaign.yaml"
    source.write_text(yaml.safe_dump(campaign, sort_keys=False), encoding="utf-8")
    config_evidence = context.evidence_root / "configuration"
    config_evidence.mkdir(parents=True, exist_ok=False)
    (config_evidence / "campaign.yaml").write_bytes(source.read_bytes())
    resolved = resolver.materialize_campaign(source, source_root / "resolved")
    cases = sorted((resolved / "cases").glob("*.yaml"))
    assert len(cases) == 1, "T02 hardware test requires one resolved baseline case"
    case = cases[0]
    (config_evidence / "resolved-case.yaml").write_bytes(case.read_bytes())
    (config_evidence / "campaign-resolved.yaml").write_bytes(
        (resolved / "campaign-resolved.yaml").read_bytes()
    )
    bundle = resolver.to_legacy_bundle(resolver.load_resolved_case(case), resolve_secrets=False)
    assert bundle["experiment"]["firmware"]["uart_output_mode"] == "full"
    run_dir, _ = context.run_experiment(case=case, name="t02_network")
    uart_text = _indexed_uart(run_dir)
    latest = uart_text[uart_text.rfind(EXPECTED_BOOT_MARKER):]
    assert re.search(r"(?m)^\[tick=\d+\]", latest), "missing live firmware tick diagnostics"
    boot = _latest_complete_boot(uart_text)
    _assert_t02_network(boot)
