from pathlib import Path


def test_generated_config_includes_plaintext_mqtt_fields():
    source = Path("scripts/framework/build.py").read_text(encoding="utf-8")
    for marker in ("PQC_MQTT_ENABLED", "PQC_MQTT_BROKER_HOST", "PQC_MQTT_BROKER_PORT", "PQC_MQTT_CLIENT_ID", "PQC_MQTT_COMMAND_TOPIC", "PQC_MQTT_RESPONSE_TOPIC", "PQC_MQTT_CORRELATION_PAYLOAD"):
        assert marker in source


def test_stm32_mqtt_uses_real_lwip_socket_callbacks():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    for marker in ('"lwip/sockets.h"', "lwip_socket", "lwip_connect", "lwip_recv", "lwip_send", "MqttClient_NetConnect", "MqttClient_Subscribe", "MqttClient_WaitMessage", "MqttClient_Publish"):
        assert marker in source


def test_plaintext_broker_listener_is_separate_from_tls_listener():
    config = Path("experiment/mqtt-broker/config/classical/mosquitto.conf").read_text(encoding="utf-8")
    assert "listener 1883 0.0.0.0" in config
    assert "allow_anonymous true" in config
    assert "listener 8883 0.0.0.0" in config
    assert "require_certificate true" in config


def test_network_task_gates_mqtt_on_dhcp_success():
    source = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert "static void APP_RunST67SPIBringup(void)" in source
    assert "app_st67_network_ready = APP_RunST67WiFiDhcp();" in source
    assert "APP_RunST67SPIBringup();" in source
    assert "network_ready = app_st67_network_ready;" in source
    assert "if (network_ready)" in source
    assert "reason=network_not_ready" in source


def test_network_task_has_extra_stack_and_explicit_fault_diagnostics():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    freertos = Path("Core/Inc/FreeRTOSConfig.h").read_text(encoding="utf-8")
    assert ".stack_size = 2048 * 4" in main_c
    assert "networkTask priority=osPriorityNormal stack_words=2048" in main_c
    assert "vApplicationStackOverflowHook" in main_c
    assert "FATAL: FreeRTOS stack overflow task=" in main_c
    assert "vApplicationMallocFailedHook" in main_c
    assert "FATAL: FreeRTOS allocation failed" in main_c
    assert "configCHECK_FOR_STACK_OVERFLOW           2" in freertos
    assert "configUSE_MALLOC_FAILED_HOOK             1" in freertos


def test_plaintext_exchange_emits_progress_markers():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    assert "wolfMQTT plaintext exchange: dispatch begin" in main_c
    for marker in (
        "wolfMQTT plaintext exchange: function entered",
        "wolfMQTT: client init begin",
        "wolfMQTT: TCP connect begin",
        "wolfMQTT: MQTT connect begin",
        "wolfMQTT: subscribe begin",
        "wolfMQTT: wait message begin",
        "wolfMQTT: publish begin",
        "wolfMQTT: cleanup begin",
    ):
        assert marker in source
