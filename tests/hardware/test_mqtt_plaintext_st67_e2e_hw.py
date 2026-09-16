from pathlib import Path
import json
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


@pytest.mark.hardware
def test_mqtt_plaintext_st67_e2e_retained_broker_evidence():
    result_dir_value = os.environ.get("PQC_RESULT_DIR")
    if not result_dir_value:
        pytest.skip("PQC_RESULT_DIR is required for retained MQTT end-to-end evidence")
    result_dir = Path(result_dir_value)
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    evidence = manifest["mqtt_e2e"]
    assert evidence["return_code"] == 0
    assert evidence["failure_stage"] == "none"
    assert evidence["broker_response_passed"] is True
    collection = manifest["result_collection"]
    assert collection["status"] == "complete"
    assert collection["completion_integrity"] is True
    assert collection["source_integrity"]["stm32"]["passed"] is True
    assert (result_dir / collection["raw_stream"]).is_file()
    assert (result_dir / collection["collector_log"]).is_file()
    assert (result_dir / evidence["publisher_log"]).is_file()
    assert (result_dir / evidence["subscriber_log"]).is_file()
