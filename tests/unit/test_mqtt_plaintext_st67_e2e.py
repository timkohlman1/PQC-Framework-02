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
    assert "listener_allow_anonymous true" in config
    assert "listener 8883 0.0.0.0" in config
    assert "require_certificate true" in config


def test_selected_application_gates_mqtt_on_shared_fixture_network_readiness():
    main = Path("Core/Src/main.c").read_text(encoding="utf-8")
    application = Path(
        "Core/App/mqtt_validation/pqc_mqtt_validation_application.c"
    ).read_text(encoding="utf-8")

    assert "static void APP_RunST67SPIBringup(void)" in main
    assert "app_st67_network_ready = APP_RunST67WiFiDhcp();" in main
    assert ".run_network_bringup = APP_RunST67SPIBringup" in main
    assert ".is_network_ready = APP_IsNetworkReady" in main
    assert "PQC_MQTT_ApplicationRun(&fixture);" in main
    assert "fixture->run_network_bringup();" in application
    assert "network_ready = fixture->is_network_ready();" in application
    assert "if (network_ready && (fixture->print_wolfmqtt_runtime != 0))" in application
    assert "reason=network_not_ready" in application


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
    assert 'PQC_EXPERIMENT_COMPLETE experiment=" PQC_MQTT_TLS_MODE " status=done' in main_c
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


def test_mqtt_reconnect_locals_are_scoped_to_enabled_builds():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    function = source.split("bool PQC_WolfMQTT_RuntimeStatusLine", 1)[1]
    disabled_guard = function.index("#if (PQC_MQTT_ENABLED != 0)")

    for declaration in (
        "PQC_WolfMQTTBuildOnlyStatus second;",
        "int reconnect_result=MQTT_CODE_SUCCESS;",
        "bool reconnect_attempted=false;",
    ):
        assert function.index(declaration) > disabled_guard


def test_plaintext_build_excludes_wolfssl_tls_sources_and_link_target():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    assert 'if(PQC_TLS_ALGORITHM_MODE STREQUAL "plaintext")' in cmake
    assert "set(PQC_TLS_COMPILED 0)" in cmake
    assert "if(PQC_TLS_COMPILED)" in cmake
    assert "Core/Src/pqc_wolfssl_build_only.c" in cmake
    assert "Core/Src/pqc_wolfssl_transport.c" in cmake
    assert "pqc_wolfssl_stm32_build_only" in cmake

    source_block = cmake.split("target_sources(${CMAKE_PROJECT_NAME} PRIVATE", 1)[1]
    unconditional_sources = source_block.split("if(PQC_TLS_COMPILED)", 1)[0]
    assert "pqc_wolfssl_build_only.c" not in unconditional_sources
    assert "pqc_wolfssl_transport.c" not in unconditional_sources


def test_plaintext_wolfmqtt_transport_compiles_without_wolfssl_headers_or_calls():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    include_guard = source.index("#if PQC_TLS_COMPILED")
    wolfssl_include = source.index('#include "wolfssl/ssl.h"')
    include_guard_end = source.index("#endif", wolfssl_include)
    assert include_guard < wolfssl_include < include_guard_end
    assert "#if PQC_TLS_COMPILED\n    if (c->tls_requested) return wolfSSL_read" in source
    assert "#if PQC_TLS_COMPILED\n    if (c->tls_requested) return wolfSSL_write" in source
    assert "#if PQC_TLS_COMPILED\n    if ((c != NULL) && (c->tls != NULL))" in source




def test_plaintext_wolfmqtt_shared_network_helpers_are_not_tls_guarded():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    diagnostic = source.index("static void PQC_WolfMQTT_DiagnosticCode")
    dns = source.index("static void PQC_WolfMQTT_DiagnosticDnsServer")
    resolve = source.index("static int PQC_WolfMQTT_ResolveBroker")
    rng_guard = source.index(
        "#if PQC_TLS_COMPILED\nstatic int PQC_WolfSSL_WaitForRegisterBit"
    )

    assert diagnostic < dns < resolve < rng_guard
    assert (
        "#if PQC_TLS_COMPILED\nstatic bool PQC_WolfMQTT_MutualTLSRequested"
        in source
    )

def test_plaintext_main_omits_tls_smoke_and_transport_diagnostics():
    source = Path("Core/Src/main.c").read_text(encoding="utf-8")

    assert "APP_PrintWolfSSLRuntimeSmoke" not in source
    assert "APP_PrintWolfSSLTransportStatus" not in source
    assert "wolfSSL TLS startup self-test:" not in source
    assert "wolfSSL transport startup self-test:" not in source
