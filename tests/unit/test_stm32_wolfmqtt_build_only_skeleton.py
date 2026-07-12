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


def test_phase_m7_client_uses_native_mqttnet_transport_boundary():
    header = Path("Core/Inc/pqc_wolfmqtt_build_only.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    assert "PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK" in header
    assert "PQC_WOLFMQTT_BACKEND_ST67W61M1" in header
    assert "PQC_WolfMQTT_BuildOnly_Initialize" in header
    assert '#include "wolfmqtt/mqtt_client.h"' in source
    assert "MqttNet network;" in source
    assert "network.connect = PQC_WolfMQTT_UnavailableConnect;" in source
    assert "network.read = PQC_WolfMQTT_UnavailableRead;" in source
    assert "network.write = PQC_WolfMQTT_UnavailableWrite;" in source
    assert "network.disconnect = PQC_WolfMQTT_UnavailableDisconnect;" in source
    assert "MqttClient_Init(" in source
    assert "MqttClient_DeInit(" in source


def test_phase_m7_performs_no_network_tls_or_mqtt_runtime_operations():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    forbidden = (
        "MqttClient_NetConnect(",
        "MqttClient_Connect(",
        "MqttClient_Publish(",
        "MqttClient_Subscribe(",
        "MqttClient_WaitMessage(",
        "wolfSSL_connect(",
        "socket(",
        "lwip_connect(",
        "W6X_WiFi_Connect(",
    )
    for fragment in forbidden:
        assert fragment not in source

    for field in (
        "transport_available = false",
        "broker_connected = false",
        "tls_handshake_complete = false",
        "publish_complete = false",
        "reconnect_complete = false",
    ):
        assert field in source


def test_phase_m7_is_build_only_and_not_called_from_firmware_runtime():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert "PQC_WolfMQTT_BuildOnly_Initialize" not in main_c
    assert "wolfMQTT build-only" not in main_c


def test_phase_m7_uses_project_user_settings_without_generated_options_header():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    # wolfMQTT's supported embedded/user-config path bypasses the generated
    # wolfmqtt/options.h file and includes the repository's user_settings.h.
    assert cmake.count("WOLFMQTT_USER_SETTINGS") >= 2
    assert cmake.count("WOLFMQTT_NO_STDIO") >= 2
    assert "wolfmqtt/options.h" not in cmake
