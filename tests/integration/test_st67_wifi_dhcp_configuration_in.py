from pathlib import Path
import re


def test_st67_wifi_dhcp_configuration_reaches_generated_build_path():
    target_text = Path(
        "configs/targets/stm32l4r5_st67.yaml"
    ).read_text(encoding="utf-8")

    assert re.search(r"(?m)^\s+ssid_ref:\s+env:PQC_WIFI_SSID\s*$", target_text)
    assert re.search(r"(?m)^\s+psk_ref:\s+env:PQC_WIFI_PSK\s*$", target_text)
    assert re.search(r"(?m)^\s+ipv4_mode:\s+dhcp\s*$", target_text)

    build_source = Path("scripts/framework/build.py").read_text(encoding="utf-8")
    assert "_write_wifi_config_header" in build_source
