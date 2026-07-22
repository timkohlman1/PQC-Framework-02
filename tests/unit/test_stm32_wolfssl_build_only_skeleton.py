from pathlib import Path
import re


EXPECTED_SHA256_HEX = "01b274b19659995cb829a9a925f613109ec02a088f94d9e914a36026cecf00e5"


def test_stm32_wolfssl_tls_context_sources_are_wired_into_firmware():
    root_cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    assert "PQC_WOLFSSL_SOURCE_DIR" in root_cmake
    assert "tools/wolfboot/lib/wolfssl" in root_cmake
    for source in (
        "src/internal.c",
        "src/keys.c",
        "src/ssl.c",
        "src/tls.c",
        "src/wolfio.c",
        "wolfcrypt/src/aes.c",
        "wolfcrypt/src/hash.c",
        "wolfcrypt/src/hmac.c",
        "wolfcrypt/src/kdf.c",
        "wolfcrypt/src/memory.c",
        "wolfcrypt/src/random.c",
        "wolfcrypt/src/sha256.c",
        "wolfcrypt/src/sp_int.c",
        "wolfcrypt/src/wc_port.c",
        "wolfcrypt/src/wolfmath.c",
    ):
        assert source in root_cmake
    assert "add_library(pqc_wolfssl_stm32_build_only STATIC" in root_cmake
    assert "pqc_wolfssl_stm32_build_only" in root_cmake
    assert "WOLFSSL_USER_SETTINGS" in root_cmake
    assert "PQC_STM32_APP_WOLFSSL_USER_SETTINGS=1" in root_cmake
    assert "PQC_WOLFSSL_SOURCE_BUILD=1" in root_cmake
    assert "wolfcrypt/src/sp_int.c" in root_cmake
    assert "wolfcrypt/src/wolfmath.c" in root_cmake
    assert "wolfcrypt/src/integer.c" not in root_cmake


def test_stm32_wolfssl_user_settings_enable_context_but_not_network_runtime():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    wrapper = Path("Core/Inc/user_settings.h").read_text(encoding="utf-8")

    defined_macros = {
        match.group(1)
        for match in re.finditer(
            r"^\s*#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)\b",
            settings,
            flags=re.MULTILINE,
        )
    }

    assert "WOLFCRYPT_ONLY" not in defined_macros
    assert "NO_TLS" not in defined_macros
    assert "NO_WOLFSSL_CLIENT" not in settings
    assert "WOLFSSL_NO_MALLOC" not in settings
    assert "NO_WOLFSSL_MEMORY" not in settings
    assert "NO_FILESYSTEM" in settings
    assert "WOLFSSL_USER_IO" in settings
    assert "WOLFSSL_NO_SOCK" in settings
    assert "NO_WOLFSSL_SERVER" in settings
    assert "WOLFSSL_NO_TLS13" in settings
    assert "WOLFSSL_TLS13 0" not in settings
    assert "WOLFSSL_STATIC_PSK" not in settings
    assert "NO_CERTS" not in settings
    assert "NO_ASN" not in defined_macros
    assert "CUSTOM_RAND_GENERATE_SEED" in settings
    assert "WC_NO_RNG" not in settings
    assert "CUSTOM_RAND_GENERATE_SEED" in settings
    assert "PQC_WolfSSL_HardwareSeed" in settings
    assert "NO_SESSION_CACHE" in settings
    assert "WOLFSSL_SP_MATH_ALL" in defined_macros
    assert "NO_ASN_TIME" in settings

    mqtt_source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    hal_conf = Path("Core/Inc/stm32l4xx_hal_conf.h").read_text(encoding="utf-8")
    cmake = Path("cmake/stm32cubemx/CMakeLists.txt").read_text(encoding="utf-8")
    assert "HAL_RNG_GenerateRandomNumber" not in mqtt_source
    assert "HAL_RNG_Init" not in mqtt_source
    assert "PQC_WOLFSSL_RNG_READY_SPIN_LIMIT" in mqtt_source
    assert "RNG_SR_CECS" in mqtt_source
    assert "RNG_SR_SECS" in mqtt_source
    assert "RNG_SR_DRDY" in mqtt_source
    assert "#undef RNG" in mqtt_source
    assert "PQC_STM32_RNG" in mqtt_source
    assert not re.search(r"(?<![A-Za-z0-9_])RNG\s*->", mqtt_source)
    assert not re.search(
        r"(?m)^\s*#\s*define\s+HAL_RNG_MODULE_ENABLED\b",
        hal_conf,
    )
    assert "stm32l4xx_hal_rng.c" not in cmake
    assert "PQC_STM32_APP_WOLFSSL_USER_SETTINGS" in wrapper
    assert '#include "pqc_wolfssl_user_settings.h"' in wrapper


def test_stm32_wolfssl_boundary_runs_sha256_and_tls_context_lifecycle_only():
    header = Path("Core/Inc/pqc_wolfssl_build_only.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfssl_build_only.c").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

    assert "tls_context_lifecycle_available" in header
    assert "tls_context_lifecycle_passed" in header
    assert "PQC_WolfSSL_BuildOnly_RunTLSContextLifecycleSmoke" in header
    assert '#include "wolfssl/options.h"' not in source
    assert '#include "wolfssl/ssl.h"' in source
    assert "wolfSSL_Init()" in source
    assert "wolfTLSv1_2_client_method()" in source
    assert "wolfSSL_CTX_new(" in source
    assert "wolfSSL_CTX_free(" in source
    assert "wolfSSL_Cleanup()" in source
    assert "wc_InitSha256" in source
    assert EXPECTED_SHA256_HEX[:16] not in source
    assert "STM32 wolfSSL TLS context lifecycle evidence only" in source
    assert "wolfSSL TLS context smoke:" in source
    assert "evidence=tls-context-lifecycle-only" in source
    assert "tls_handshake=unavailable" in source
    assert "certs=not-loaded" in source
    assert "transport=unavailable" in source
    assert "mqtt=unavailable" in source
    assert "wifi=unavailable" in source
    assert "st67w61m1=unavailable" in source
    assert '#include "pqc_wolfssl_build_only.h"' in main_c
    assert "PQC_WolfSSL_BuildOnly_RuntimeSmokeLine" in main_c


def test_stm32_wolfssl_context_smoke_does_not_handshake_load_certs_or_use_network():
    paths = (
        Path("Core/Src/pqc_wolfssl_build_only.c"),
        Path("Core/Inc/pqc_wolfssl_user_settings.h"),
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    forbidden_fragments = (
        "wolfSSL_new(",
        "wolfSSL_connect(",
        "wolfSSL_read(",
        "wolfSSL_write(",
        "wolfSSL_CTX_use_PrivateKey",
        "wolfSSL_CTX_load_verify_locations",
        "MQTTConnect",
        "MQTTPublish",
        "mqtt_client_connect(",
        "tcp_connect(",
        "netif_add(",
        "dhcp_start(",
        "W6X_WiFi_Connect(",
    )
    for fragment in forbidden_fragments:
        assert fragment not in combined


def test_stm32_wolfssl_source_smoke_does_not_embed_secret_material():
    paths = (
        Path("Core/Inc/pqc_wolfssl_build_only.h"),
        Path("Core/Src/pqc_wolfssl_build_only.c"),
        Path("Core/Inc/pqc_wolfssl_user_settings.h"),
        Path("Core/Inc/user_settings.h"),
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for fragment in (
        "BEGIN PRIVATE KEY",
        "BEGIN RSA PRIVATE KEY",
        "BEGIN EC PRIVATE KEY",
        "PRIVATE KEY-----",
        "mqtt_password",
        "password=",
        "secrets/",
        ".env",
        "client.key",
        "ca.key",
        "private_key.der",
    ):
        assert fragment not in combined


def test_stm32_wolfssl_unavailable_transport_boundary_is_wired_and_evidence_bound():
    root_cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    header = Path("Core/Inc/pqc_wolfssl_transport.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfssl_transport.c").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

    assert "Core/Src/pqc_wolfssl_transport.c" in root_cmake
    assert "PQC_WolfSSL_Transport_Connect" in header
    assert "PQC_WolfSSL_Transport_Read" in header
    assert "PQC_WolfSSL_Transport_Write" in header
    assert "PQC_WolfSSL_Transport_RecvCallback" in header
    assert "PQC_WolfSSL_Transport_SendCallback" in header
    assert '#include "pqc_network_interface.h"' in source
    assert "PQC_NetworkInterface_GetStatus" in source
    assert "PQC_WOLFSSL_TRANSPORT_RESULT_UNAVAILABLE" in source
    assert "STM32 wolfSSL unavailable-transport evidence only" in source
    assert "wolfSSL transport boundary:" in source
    assert "evidence=unavailable-transport-only" in source
    assert "connect=unavailable" in source
    assert "read=unavailable" in source
    assert "write=unavailable" in source
    assert "socket_io=not-performed" in source
    assert "tls_handshake=unavailable" in source
    assert "mqtt_connect=unavailable" in source
    assert "mqtt_publish=unavailable" in source
    assert "reconnect=unavailable" in source
    assert "wifi=unavailable" in source
    assert "st67w61m1=unavailable" in source
    assert "end_to_end=unavailable" in source
    assert '#include "pqc_wolfssl_transport.h"' in main_c
    assert "PQC_WolfSSL_Transport_StatusLine" in main_c


def test_stm32_wolfssl_transport_boundary_performs_no_network_tls_or_mqtt_work():
    source = Path("Core/Src/pqc_wolfssl_transport.c").read_text(encoding="utf-8")

    forbidden_fragments = (
        "socket(",
        "connect(",
        "recv(",
        "send(",
        "lwip_socket(",
        "lwip_connect(",
        "lwip_recv(",
        "lwip_send(",
        "tcp_connect(",
        "netconn_connect(",
        "wolfSSL_new(",
        "wolfSSL_SetIORecv(",
        "wolfSSL_SetIOSend(",
        "wolfSSL_connect(",
        "wolfSSL_read(",
        "wolfSSL_write(",
        "wolfSSL_CTX_load_verify_locations",
        "wolfSSL_CTX_use_PrivateKey",
        "MQTTConnect",
        "MQTTPublish",
        "W6X_WiFi_Connect(",
    )
    for fragment in forbidden_fragments:
        assert fragment not in source


def test_phase_m6_5_wolfssl_smoke_runs_serialized_in_freertos_task_without_threading_support():
    header = Path("Core/Inc/pqc_wolfssl_build_only.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfssl_build_only.c").read_text(encoding="utf-8")
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

    assert "PQC_WolfSSL_BuildOnly_RuntimeSmokeLineForContext" in header
    assert "context=%s scheduler=%s" in source
    assert "PQC_WolfSSL_BuildOnly_RunSourceSmoke();" in source
    assert "PQC_WolfSSL_BuildOnly_RunTLSContextLifecycleSmoke();" in source
    assert 'APP_PrintWolfSSLRuntimeSmoke("pre_scheduler", false);' in main_c
    assert 'APP_PrintWolfSSLRuntimeSmoke("freertos_task", true);' in main_c
    assert "serialized=true" in main_c
    assert "WOLFSSL_FREERTOS" not in settings
    assert "WOLFSSL_CMSIS_RTOS" not in settings
    assert "#define SINGLE_THREADED" in settings
    for fragment in (
        "tls_handshake=unavailable", "certs=not-loaded",
        "transport=unavailable", "mqtt_connect=unavailable",
        "mqtt_publish=unavailable", "reconnect=unavailable",
        "wifi=unavailable", "link=unavailable", "ip=unavailable",
        "tcp=unavailable", "st67w61m1=unavailable",
        "end_to_end=unavailable",
    ):
        assert fragment in source
