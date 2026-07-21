from pathlib import Path


def test_server_authenticated_tls_profile_is_separate_from_mutual_tls():
    compose = Path("experiment/mqtt-broker/compose.yaml").read_text(encoding="utf-8")
    server_auth = Path("experiment/mqtt-broker/config/classical-server-auth/mosquitto.conf").read_text(encoding="utf-8")
    mutual = Path("experiment/mqtt-broker/config/classical/mosquitto.conf").read_text(encoding="utf-8")
    assert 'profiles: ["classical-server-auth"]' in compose
    assert "require_certificate false" in server_auth
    assert "tls_version tlsv1.2" in server_auth
    assert "require_certificate true" in mutual


def test_stm32_tls_path_uses_wolfssl_over_lwip_and_hardware_rng():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    for marker in (
        "HAL_RNG_GenerateRandomNumber", "wolfSSL_CTX_load_verify_buffer",
        "wolfSSL_check_domain_name", "wolfSSL_connect", "wolfSSL_read", "wolfSSL_write",
        "tls_handshake=", "reconnect_tls_handshake=", "reconnect_publish=",
        "wolfMQTT plaintext exchange: function entered",
    ):
        assert marker in source


def test_generated_header_embeds_only_public_ca_material():
    source = Path("scripts/framework/build.py").read_text(encoding="utf-8")
    assert "PQC_MQTT_TLS_CA_PEM" in source
    assert "ca_certificate" in source
    assert "Provision the classical broker certificates before building" in source
    assert "client_private_key" not in source


def test_m11_config_selects_server_auth_profile_and_reconnect():
    config = Path("configs/experiments/mqtt_tls_server_auth_st67_e2e.yaml").read_text(encoding="utf-8")
    assert "evidence_class: stm32_st67_classical_tls_e2e" in config
    assert "transport_backend: st67w61m1_lwip_wolfssl" in config
    assert "broker_profile: classical-server-auth" in config
    assert "mode: classical_tls_server_auth" in config
    assert "reconnect_attempts: 1" in config
