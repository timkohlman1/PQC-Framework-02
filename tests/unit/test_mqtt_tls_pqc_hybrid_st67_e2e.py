from pathlib import Path


def test_pqc_profile_selects_hybrid_tls13_server_auth():
    config = Path("configs/experiments/mqtt_tls_pqc_hybrid_server_auth_st67_e2e.yaml").read_text(encoding="utf-8")
    assert "evidence_class: stm32_st67_pqc_hybrid_tls_e2e" in config
    assert "broker_profile: oqs" in config
    assert "mode: pqc_hybrid_tls_server_auth" in config
    assert "key_exchange_group: SecP256r1MLKEM768" in config
    assert "reconnect_attempts: 1" in config


def test_stm32_wolfssl_enables_tls13_mlkem768_and_strict_group_check():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    for marker in ("WOLFSSL_TLS13", "WOLFSSL_HAVE_MLKEM", "WOLFSSL_PQC_HYBRIDS", "WOLFSSL_NO_ML_KEM_512", "WOLFSSL_NO_ML_KEM_1024", "WOLFSSL_SHA3"):
        assert marker in settings
    assert "WOLFSSL_NO_TLS13" not in settings
    for source_file in ("src/tls13.c", "wolfcrypt/src/sha3.c", "wolfcrypt/src/wc_mlkem.c"):
        assert source_file in cmake
    for marker in ("wolfTLSv1_3_client_method", "WOLFSSL_SECP256R1MLKEM768", "wolfSSL_CTX_set_groups", "wolfSSL_get_curve_name", 'strstr(curve_name, "MLKEM768")', "pqc_group=%s"):
        assert marker in source


def test_oqs_broker_is_server_auth_and_healthcheck_uses_hybrid_group():
    config = Path("experiment/mqtt-broker/config/oqs/mosquitto.conf").read_text(encoding="utf-8")
    compose = Path("experiment/mqtt-broker/compose.yaml").read_text(encoding="utf-8")
    assert "tls_version tlsv1.3" in config
    assert "require_certificate false" in config
    assert "use_identity_as_username false" in config
    assert "allow_anonymous true" in config
    acl = Path("experiment/mqtt-broker/config/oqs/aclfile").read_text(encoding="utf-8")
    assert "topic readwrite pqc/#" in acl
    assert "user pqc-mqtt-client" not in acl
    assert "-groups SecP256r1MLKEM768" in compose
    assert "healthcheck.crt" not in compose
    assert "healthcheck.key" not in compose


def test_config_schema_accepts_pqc_evidence_and_mode():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert '"stm32_st67_pqc_hybrid_tls_e2e"' in source
    assert '"pqc_hybrid_tls_server_auth"' in source
    assert '"st67w61m1_lwip_wolfssl": {"stm32_st67_classical_tls_e2e", "stm32_st67_pqc_hybrid_tls_e2e"}' in source


def test_pqc_profile_uses_extended_uart_hard_limit():
    config = Path("configs/experiments/mqtt_tls_pqc_hybrid_server_auth_st67_e2e.yaml").read_text(encoding="utf-8")
    assert "hard_limit_seconds: 60" in config


def test_hybrid_group_is_guarded_by_enabled_wolfssl_features():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    api = Path("tools/wolfboot/lib/wolfssl/src/ssl_api_ext.c").read_text(encoding="utf-8")
    assert "#define WOLFSSL_HAVE_MLKEM" in settings
    assert "#define WOLFSSL_PQC_HYBRIDS" in settings
    hybrid_case = "case WOLFSSL_SECP256R1MLKEM768:"
    assert hybrid_case in api
    assert api.index("#ifdef WOLFSSL_PQC_HYBRIDS") < api.index(hybrid_case)
