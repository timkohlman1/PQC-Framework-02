from pathlib import Path
import re


def test_st67_wifi_dhcp_configuration_reaches_generated_build_path():
    experiment_text = Path(
        "configs/experiments/baseline_direct_uart.yaml"
    ).read_text(encoding="utf-8")

    assert re.search(r"(?m)^\s+ssid:\s+\S+\s*$", experiment_text)
    assert re.search(r"(?m)^\s+psk:\s+\S+\s*$", experiment_text)
    assert re.search(r"(?m)^\s+mode:\s+dhcp\s*$", experiment_text)

    build_source = Path("scripts/framework/build.py").read_text(encoding="utf-8")
    assert "_write_wifi_config_header" in build_source
