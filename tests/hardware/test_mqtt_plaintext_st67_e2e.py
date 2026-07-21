from pathlib import Path
import os
import pytest


@pytest.mark.hardware
def test_mqtt_plaintext_st67_e2e_uart_evidence():
    log_path = os.environ.get("PQC_UART_LOG")
    if not log_path:
        pytest.skip("PQC_UART_LOG is required for recorded STM32 MQTT evidence")
    text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    for marker in ("ST67 DHCP: result=passed", "evidence=stm32-st67-plaintext-mqtt-e2e", "mqtt_connect=passed", "mqtt_subscribe=passed", "mqtt_receive=passed", "mqtt_publish=passed", "end_to_end=passed"):
        assert marker in text
