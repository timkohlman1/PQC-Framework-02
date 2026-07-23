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


def test_mqtt_exchange_uses_concise_structured_runtime_evidence():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    combined = main_c + source

    assert "wolfMQTT runtime: context=%s scheduler=%s" in source
    assert "mqtt_connect=%s" in source
    assert "mqtt_publish=%s" in source
    assert "end_to_end=%s" in source
    assert "PQC_EXPERIMENT_COMPLETE experiment=mqtt_tls_server_auth status=done" in main_c
    assert "wolfMQTT plaintext exchange:" not in combined
    for removed_phase_marker in (
        "wolfMQTT: client init begin",
        "wolfMQTT: TCP connect begin",
        "wolfMQTT: MQTT connect begin",
        "wolfMQTT: subscribe begin",
        "wolfMQTT: wait message begin",
        "wolfMQTT: publish begin",
        "wolfMQTT: cleanup begin",
    ):
        assert removed_phase_marker not in source


def test_experiment_run_orchestrates_and_verdicts_mqtt_e2e():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    for marker in (
        "_execute_mqtt_e2e_uart_capture",
        "mosquitto_sub",
        "mosquitto_pub",
        "mqtt-publisher.log",
        "mqtt-subscriber.log",
        "broker_response_passed",
        "missing_uart_markers",
        "MQTT end-to-end run passed",
    ):
        assert marker in source


def test_mqtt_plaintext_port_is_declared_once():
    compose = Path("experiment/mqtt-broker/compose.yaml").read_text(encoding="utf-8")
    assert compose.count('${MQTT_PLAINTEXT_PORT:-1883}:1883') == 1


def test_mqtt_e2e_marker_parser_tolerates_ansi_prefixes():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert "marker_index = line.find(marker_prefix)" in source
    assert "marker_line = line[marker_index:].strip()" in source


def test_mqtt_e2e_run_manages_broker_lifecycle_and_retains_logs():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    for marker in (
        "_start_managed_mqtt_broker",
        "_wait_for_plaintext_mqtt_broker",
        "_collect_and_stop_managed_mqtt_broker",
        '("stop-existing", "stop"',
        '("deploy", "deploy"',
        '("start", "start"',
        "mqtt-broker-readiness.log",
        "mqtt-broker-log.log",
        "mqtt-broker-stop.log",
        "cleanup_completed",
        "broker_log_collection",
        "broker_stop",
    ):
        assert marker in source
