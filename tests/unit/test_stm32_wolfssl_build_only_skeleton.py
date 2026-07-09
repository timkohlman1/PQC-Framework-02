from pathlib import Path


def test_stm32_wolfssl_build_only_skeleton_is_compiled_into_firmware():
    root_cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    assert "Core/Src/pqc_wolfssl_build_only.c" in root_cmake
    assert "Core/Inc" in root_cmake
    assert "PQC_WOLFSSL_BUILD_ONLY=1" in root_cmake


def test_stm32_wolfssl_build_only_boundary_declares_unavailable_tls_runtime():
    header = Path("Core/Inc/pqc_wolfssl_build_only.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfssl_build_only.c").read_text(encoding="utf-8")

    assert "PQC_WolfSSLBuildOnlyStatus" in header
    assert "PQC_WolfSSL_BuildOnly_Init" in header
    assert "PQC_WolfSSL_BuildOnly_BuildInfoLine" in header
    assert ".wolfssl_build_boundary_present = true" in source
    assert ".tls_handshake_available = false" in source
    assert ".runtime_transport_available = false" in source
    assert ".certificate_store_configured = false" in source
    assert ".private_key_material_compiled_in = false" in source
    assert ".real_credentials_required = false" in source
    assert "STM32 wolfSSL build-only skeleton evidence" in source
    assert "tls_handshake=unavailable" in source
    assert "transport=unavailable" in source
    assert "certs=path-references-only" in source
    assert "secrets=not-compiled-in" in source


def test_stm32_wolfssl_build_only_skeleton_does_not_perform_tls_or_mqtt_runtime_work():
    source = Path("Core/Src/pqc_wolfssl_build_only.c").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

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
        assert fragment not in source

    assert "PQC_WolfSSL_BuildOnly_Init" not in main_c
    assert "wolfSSL build-only:" not in main_c


def test_stm32_wolfssl_build_only_skeleton_does_not_embed_secret_material():
    header = Path("Core/Inc/pqc_wolfssl_build_only.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfssl_build_only.c").read_text(encoding="utf-8")
    combined = f"{header}\n{source}"

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

    assert "private keys, credentials, and real certificate material must remain outside source" in source
