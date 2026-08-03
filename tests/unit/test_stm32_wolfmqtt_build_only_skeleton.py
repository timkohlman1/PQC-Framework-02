from pathlib import Path


def test_phase_m7_wolfmqtt_sources_and_submodule_are_wired():
    gitmodules = Path(".gitmodules").read_text(encoding="utf-8")
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    assert 'path = Middlewares/Third_Party/wolfMQTT' in gitmodules
    assert 'url = https://github.com/wolfSSL/wolfMQTT.git' in gitmodules
    assert "PQC_WOLFMQTT_SOURCE_DIR" in cmake
    assert "Middlewares/Third_Party/wolfMQTT" in cmake
    for source in ("src/mqtt_client.c", "src/mqtt_packet.c", "src/mqtt_socket.c"):
        assert source in cmake
    assert "add_library(pqc_wolfmqtt_stm32_build_only STATIC" in cmake
    assert "pqc_wolfmqtt_stm32_build_only" in cmake
    assert "Core/Src/pqc_wolfmqtt_build_only.c" in cmake


def test_wolfmqtt_supports_fake_and_real_st67_lwip_transport_boundaries():
    header = Path("Core/Inc/pqc_wolfmqtt_build_only.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    assert "PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK" in header
    assert "PQC_WOLFMQTT_BACKEND_ST67W61M1" in header
    assert "PQC_WolfMQTT_BuildOnly_Initialize" in header
    assert "PQC_WolfMQTT_RunPlaintextExchange" in header
    assert '#include "wolfmqtt/mqtt_client.h"' in source
    assert '#include "lwip/sockets.h"' in source
    assert "MqttNet network;" in source
    assert "network.connect = PQC_WolfMQTT_LwIPConnect;" in source
    assert "network.read = PQC_WolfMQTT_LwIPRead;" in source
    assert "network.write = PQC_WolfMQTT_LwIPWrite;" in source
    assert "network.disconnect = PQC_WolfMQTT_LwIPDisconnect;" in source
    assert "MqttClient_Init(" in source
    assert "MqttClient_DeInit(" in source


def test_real_mqtt_exchange_performs_bounded_mqtt_operations():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    for fragment in (
        "MqttClient_NetConnect(",
        "MqttClient_Connect(",
        "MqttClient_Subscribe(",
        "MqttClient_WaitMessage(",
        "MqttClient_Publish(",
        "MqttClient_Disconnect(",
        "lwip_socket(",
        "lwip_connect(",
        "lwip_recv(",
        "lwip_send(",
        "lwip_close(",
    ):
        assert fragment in source

    assert "PQC_WOLFMQTT_COMMAND_TIMEOUT_MS" in source
    assert "PQC_WolfMQTT_TLSRequested" in source
    assert 'strcmp(PQC_MQTT_TLS_MODE, "classical_tls_server_auth")' in source
    assert "W6X_WiFi_Connect(" not in source
    assert "status->transport_available = (backend == PQC_WOLFMQTT_BACKEND_ST67W61M1);" in source
    assert "status->mqtt_connected = true;" in source
    assert "status->subscribed = true;" in source
    assert "status->message_received = true;" in source
    assert "status->publish_complete = true;" in source

def test_phase_m8_invokes_fake_no_network_initialization_from_freertos_task():
    header = Path("Core/Inc/pqc_wolfmqtt_build_only.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

    assert "PQC_WolfMQTT_RuntimeStatusLine" in header
    assert "PQC_WolfMQTT_RuntimeStatusLine" in source
    assert "PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK" in source
    assert "APP_PrintWolfMQTTRuntimeStatus();" in main_c
    assert main_c.index("FreeRTOS defaultTask started:") < main_c.index("APP_PrintWolfMQTTRuntimeStatus();")


def test_phase_m8_uart_marker_is_initialization_only_and_explicitly_unavailable():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    combined = source + main_c

    assert "wolfMQTT runtime smoke:" in combined
    assert "evidence=stm32-fake-no-network-initialization-only" in combined
    assert "backend=fake_no_network" in combined
    for field in (
        "transport=unavailable",
        "wifi=unavailable",
        "link=unavailable",
        "ip=unavailable",
        "tcp=unavailable",
        "tls_handshake=unavailable",
        "mqtt_connect=unavailable",
        "mqtt_publish=unavailable",
        "reconnect=unavailable",
        "st67w61m1=unavailable",
        "end_to_end=unavailable",
    ):
        assert field in combined


def test_phase_m7_uses_project_user_settings_without_generated_options_header():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    # wolfMQTT's supported embedded/user-config path bypasses the generated
    # wolfmqtt/options.h file and includes the repository's user_settings.h.
    assert cmake.count("WOLFMQTT_USER_SETTINGS") >= 2
    assert cmake.count("WOLFMQTT_NO_STDIO") >= 2
    assert "wolfmqtt/options.h" not in cmake


def test_tls_handshake_result_is_recorded_inside_lwip_connect_function():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    connect = source.index("result = wolfSSL_connect(socket_context->tls);")
    record = source.index("socket_context->tls_connect_result = result;", connect)
    failure_check = source.index("if (result != WOLFSSL_SUCCESS) {", record)

    assert connect < record < failure_check


def test_selected_tls_group_array_matches_mutable_wolfssl_api():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    assert "int groups[] = { PQC_TLS_GROUP_ID };" in source
    assert "const int groups[] = { PQC_TLS_GROUP_ID };" not in source

def test_mlkem_portable_implementation_sources_are_wired_without_arch_assembly():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    assert "wolfcrypt/src/wc_mlkem.c" in cmake
    assert "wolfcrypt/src/wc_mlkem_poly.c" in cmake
    assert "wolfcrypt/src/wc_mlkem_asm.S" not in cmake



def test_mqtt_tls_build_excludes_mldsa_but_retains_pqc_group_status():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    for marker in (
        "PQC_TLS_ENABLE_MLDSA_65",
        "wolfcrypt/src/wc_mldsa.c",
        "wolfcrypt/src/wc_mldsa_asm.S",
    ):
        assert marker not in cmake
    assert "pqc_group_config=%s ca_load=%s pqc_group=%s" in source


def test_handshake_instrumentation_does_not_change_network_task_size():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    mqtt_source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    assert ".stack_size = 2048 * 4" in main_c
    assert "wolfMQTT TLS handshake boundary: stage=%s" in mqtt_source


def test_mlkem_resource_controls_avoid_large_client_key_share_stack_object():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    assert "WOLFSSL_SMALL_STACK" in settings
    assert "WOLFSSL_TLSX_PQC_MLKEM_STORE_OBJ" in settings
    assert "WOLFSSL_MLKEM_MAKEKEY_SMALL_MEM" in settings


def test_clienthello_diagnostics_do_not_log_key_share_payload():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    diagnostic_start = source.index(
        "static void PQC_WolfMQTT_DiagnosticClientHelloSignatureAlgorithms"
    )
    diagnostic_end = source.index(
        "static int PQC_WolfSSL_IOSend", diagnostic_start
    )
    diagnostic = source[diagnostic_start:diagnostic_end]
    assert "0x000dU" in diagnostic
    assert "0x0032U" in diagnostic
    assert "0x0033U" not in diagnostic
    assert "key_share" not in diagnostic


def test_wolfmqtt_runtime_status_buffer_fits_plaintext_evidence_line():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    # The complete plaintext status line is longer than the former 640-byte
    # buffer because the TLS-only fields are rendered as "not_required".
    assert "static char status_line[768];" in main_c

    for field in (
        "mqtt_connect=%s",
        "mqtt_subscribe=%s",
        "mqtt_receive=%s",
        "mqtt_publish=%s",
        "end_to_end=%s",
    ):
        assert field in source
