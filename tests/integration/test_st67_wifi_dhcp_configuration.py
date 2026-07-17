from pathlib import Path
import pytest
@pytest.mark.integration
def test_st67_wifi_dhcp_configuration_reaches_generated_build_path():
    assert "ssid: hiphopopotamus" in Path("configs/experiments/baseline_direct_uart.yaml").read_text()
    assert "_write_wifi_config_header" in Path("scripts/framework/build.py").read_text()
    assert "pqc_generated" in Path("cmake/stm32cubemx/CMakeLists.txt").read_text()
