from pathlib import Path


EXPECTED_SHA256_HEX = "01b274b19659995cb829a9a925f613109ec02a088f94d9e914a36026cecf00e5"


def test_stm32_wolfssl_source_build_is_wired_into_firmware():
    root_cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    assert "PQC_WOLFSSL_SOURCE_DIR" in root_cmake
    assert "tools/wolfboot/lib/wolfssl" in root_cmake
    assert "wolfcrypt/src/sha256.c" in root_cmake
    assert "add_library(pqc_wolfssl_stm32_build_only STATIC" in root_cmake
    assert "target_link_libraries(${CMAKE_PROJECT_NAME}" in root_cmake
    assert "pqc_wolfssl_stm32_build_only" in root_cmake
    assert "WOLFSSL_USER_SETTINGS" in root_cmake
    assert "PQC_STM32_APP_WOLFSSL_USER_SETTINGS=1" in root_cmake
    assert "PQC_WOLFSSL_SOURCE_BUILD=1" in root_cmake
    assert '"${PQC_WOLFSSL_SOURCE_DIR}"' in root_cmake


def test_stm32_wolfssl_user_settings_keep_phase_m6_scope_narrow():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    wrapper = Path("Core/Inc/user_settings.h").read_text(encoding="utf-8")

    assert "WOLFCRYPT_ONLY" in settings
    assert "NO_FILESYSTEM" in settings
    assert "NO_TLS" in settings
    assert "NO_WOLFSSL_CLIENT" in settings
    assert "NO_WOLFSSL_SERVER" in settings
    assert "WOLFSSL_NO_MALLOC" in settings
    assert "NO_WOLFSSL_MEMORY" in settings
    assert "USE_SLOW_SHA256" in settings
    assert "PQC_STM32_APP_WOLFSSL_USER_SETTINGS" in wrapper
    assert '#include "pqc_wolfssl_user_settings.h"' in wrapper


def test_stm32_wolfssl_boundary_invokes_wolfcrypt_sha256_smoke_without_tls_runtime():
    header = Path("Core/Inc/pqc_wolfssl_build_only.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfssl_build_only.c").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

    assert "PQC_WolfSSLBuildOnlyStatus" in header
    assert "wolfssl_source_build_enabled" in header
    assert "wolfcrypt_sha256_smoke_passed" in header
    assert "PQC_WolfSSL_BuildOnly_RunSourceSmoke" in header
    assert "PQC_WolfSSL_BuildOnly_RuntimeSmokeLine" in header
    assert "__has_include" not in source
    assert '#include "wolfssl/version.h"' in source
    assert '#include "wolfssl/wolfcrypt/sha256.h"' in source
    assert "LIBWOLFSSL_VERSION_STRING" in source
    assert "return WOLFSSL_VERSION" not in source
    assert "wc_InitSha256" in source
    assert "wc_Sha256Update" in source
    assert "wc_Sha256Final" in source
    assert EXPECTED_SHA256_HEX[:16] not in source
    for byte_literal in ("0x01U", "0xb2U", "0x74U", "0xb1U"):
        assert byte_literal in source
    assert "STM32 wolfSSL source build-only smoke evidence" in source
    assert "wolfSSL build-only smoke:" in source
    assert "sha256=%s" in source
    assert '"ok" : "failed"' in source
    assert "tls_handshake=unavailable" in source
    assert "transport=unavailable" in source
    assert "certs=not-loaded" in source
    assert "secrets=not-compiled-in" in source
    assert '#include "pqc_wolfssl_build_only.h"' in main_c
    assert "APP_PrintWolfSSLRuntimeSmoke" in main_c
    assert "PQC_WolfSSL_BuildOnly_RuntimeSmokeLine" in main_c


def test_stm32_wolfssl_source_smoke_does_not_perform_tls_mqtt_network_or_st67_runtime_work():
    source = Path("Core/Src/pqc_wolfssl_build_only.c").read_text(encoding="utf-8")
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    combined = f"{source}\n{settings}"

    forbidden_fragments = (
        "wolfSSL_new(",
        "wolfSSL_CTX_new(",
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

    forbidden_fragments = (
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
    )

    for fragment in forbidden_fragments:
        assert fragment not in combined

    assert "private keys, credentials, and real certificate material must remain outside" in combined
