from pathlib import Path


def test_pqc_profile_selects_hybrid_tls13_server_auth():
    config = Path("configs/experiments/mqtt_tls_SecP256r1MLKEM768_server_auth_st67_e2e.yaml").read_text(encoding="utf-8")
    assert "evidence_class: stm32_st67_pqc_hybrid_tls_e2e" in config
    assert "broker_profile: oqs" in config
    assert "mode: pqc_hybrid_tls_server_auth" in config
    assert "key_exchange_group: SecP256r1MLKEM768" in config
    assert "reconnect_attempts: 1" in config


def test_stm32_wolfssl_enables_tls13_mlkem768_and_strict_group_check():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    for marker in ("WOLFSSL_TLS13", "WOLFSSL_HAVE_MLKEM", "WOLFSSL_PQC_HYBRIDS", "WOLFSSL_NO_ML_KEM_512", "WOLFSSL_NO_ML_KEM_1024", "WOLFSSL_SHA3", "WOLFSSL_SHAKE128", "WOLFSSL_SHAKE256"):
        assert marker in settings
    assert "WOLFSSL_NO_TLS13" not in settings
    for source_file in (
        "src/tls13.c",
        "wolfcrypt/src/sha3.c",
        "wolfcrypt/src/wc_mlkem.c",
        "wolfcrypt/src/wc_mlkem_poly.c",
    ):
        assert source_file in cmake
    assert "wolfcrypt/src/wc_mlkem_asm.S" not in cmake
    for marker in (
        "wolfTLSv1_3_client_method",
        "PQC_TLS_GROUP_ID",
        "PQC_TLS_GROUP_NAME",
        "wolfSSL_CTX_set_groups",
        "wolfSSL_get_curve_name",
        "PQC_WolfMQTT_TLSGroupNamesMatch",
        "configured_group=%s negotiated_group=%s key_exchange_group=%s",
    ):
        assert marker in source


def test_oqs_broker_is_server_auth_and_healthcheck_uses_hybrid_group():
    config = Path("experiment/mqtt-broker/config/oqs/mosquitto.conf").read_text(encoding="utf-8")
    openssl_config = Path("experiment/mqtt-broker/config/oqs/openssl.cnf").read_text(encoding="utf-8")
    compose = Path("experiment/mqtt-broker/compose.yaml").read_text(encoding="utf-8")
    oqs_service = compose[compose.index("  mqtt-oqs:"):compose.index("  mqtt-oqs-mtls:")]
    assert "tls_version tlsv1.3" in config
    assert "require_certificate false" in config
    assert "use_identity_as_username false" in config
    assert "listener_allow_anonymous true" in config
    acl = Path("experiment/mqtt-broker/config/oqs/aclfile").read_text(encoding="utf-8")
    assert "topic readwrite pqc/#" in acl
    assert "user pqc-mqtt-client" not in acl
    configured_groups = {
        group
        for line in openssl_config.splitlines()
        if line.strip().startswith("Groups =")
        for group in line.split("=", 1)[1].strip().split(":")
    }
    assert "SecP256r1MLKEM768" in configured_groups
    assert "X25519MLKEM768" in configured_groups
    assert "SecP384r1MLKEM1024" in configured_groups
    assert 'OPENSSL_CONF: "/mosquitto/config/openssl.cnf"' in compose
    assert "./config/oqs/openssl.cnf:/mosquitto/config/openssl.cnf:ro" in compose
    assert "mosquitto_pub -h 127.0.0.1 -p 8883" in oqs_service
    assert "--tls-version tlsv1.3" in oqs_service
    assert "healthcheck.crt" not in oqs_service
    assert "healthcheck.key" not in oqs_service


def test_config_schema_accepts_pqc_evidence_and_mode():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert '"stm32_st67_pqc_hybrid_tls_e2e"' in source
    assert '"pqc_hybrid_tls_server_auth"' in source
    assert '"st67w61m1_lwip_wolfssl": {"stm32_st67_classical_tls_e2e", "stm32_st67_pqc_hybrid_tls_e2e"}' in source


def test_pqc_profile_uses_extended_uart_hard_limit():
    config = Path("configs/experiments/mqtt_tls_SecP256r1MLKEM768_server_auth_st67_e2e.yaml").read_text(encoding="utf-8")
    assert "hard_limit_seconds: 180" in config


def test_hybrid_group_is_guarded_by_enabled_wolfssl_features():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    api = Path("tools/wolfboot/lib/wolfssl/src/ssl_api_ext.c").read_text(encoding="utf-8")
    assert "#define WOLFSSL_HAVE_MLKEM" in settings
    assert "#define WOLFSSL_PQC_HYBRIDS" in settings
    hybrid_case = "case WOLFSSL_SECP256R1MLKEM768:"
    assert hybrid_case in api
    assert api.index("#ifdef WOLFSSL_PQC_HYBRIDS") < api.index(hybrid_case)


def test_tls_build_excludes_mldsa_verification_support():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    for marker in (
        "PQC_TLS_ENABLE_MLDSA_65",
        "WOLFSSL_HAVE_MLDSA",
        "WOLFSSL_MLDSA_VERIFY_ONLY",
        "WOLFSSL_NO_ML_DSA_44",
        "WOLFSSL_NO_ML_DSA_87",
        "wolfcrypt/src/wc_mldsa.c",
        "wolfcrypt/src/wc_mldsa_asm.S",
    ):
        assert marker not in settings + cmake


def test_tls_handshake_boundary_instrumentation_is_wired():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    assert 'PQC_WolfMQTT_DiagnosticHandshakeBoundary("before_connect"' in source
    assert 'PQC_WolfMQTT_DiagnosticHandshakeBoundary("after_connect"' in source
    assert "uxTaskGetStackHighWaterMark(NULL)" in source
    assert "xPortGetFreeHeapSize()" in source
    assert "xPortGetMinimumEverFreeHeapSize()" in source
    assert "direction=send stage=first_callback_entry" in source
    assert "direction=recv stage=first_callback_entry" in source


def test_mlkem_client_key_share_uses_bounded_stack_and_scratch_memory():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    experiment = Path(
        "configs/experiments/mqtt_tls_SecP256r1MLKEM768_server_auth_st67_e2e.yaml"
    ).read_text(encoding="utf-8")

    assert "#define WOLFSSL_SMALL_STACK" in settings
    assert "#define WOLFSSL_TLSX_PQC_MLKEM_STORE_OBJ" in settings
    assert "#define WOLFSSL_MLKEM_MAKEKEY_SMALL_MEM" in settings
    assert "hard_limit_seconds: 180" in experiment


def test_clienthello_signature_algorithm_diagnostics_are_wired():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    assert "PQC_WolfMQTT_DiagnosticClientHelloSignatureAlgorithms" in source
    assert 'extension="signature_algorithms"' not in source
    assert '"signature_algorithms"' in source
    assert '"signature_algorithms_cert"' in source
    assert "0x000dU" in source
    assert "0x0032U" in source
    assert "0x%04x" in source
