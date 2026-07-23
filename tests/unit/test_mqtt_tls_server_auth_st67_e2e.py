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
        "RCC_CRRCR_HSI48ON", "RNG_SR_CECS", "RNG_SR_SECS", "RNG_SR_DRDY",
        "PQC_WOLFSSL_RNG_READY_SPIN_LIMIT", "wolfSSL_CTX_load_verify_buffer",
        "wolfSSL_check_ip_address", "wolfSSL_connect", "wolfSSL_read", "wolfSSL_write",
        "tls_handshake=", "reconnect_tls_handshake=", "reconnect_publish=",
        "wolfMQTT runtime: context=%s scheduler=%s",
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


def test_managed_broker_cleanup_receives_bundle_and_uses_selected_profile():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert "def _collect_and_stop_managed_mqtt_broker(" in source
    assert "bundle: dict[str, dict[str, Any]]" in source
    assert source.count(
        "_collect_and_stop_managed_mqtt_broker(bundle=bundle, repo_root=repo_root, result_dir=result_dir)"
    ) == 2
    assert 'extra_args=[*common, "--profile", profile, "--tail", "100000"]' in source
    assert 'extra_args=[*common, "--profile", "classical", "--tail", "100000"]' not in source


def test_broker_controller_accepts_server_auth_profile_and_selects_matching_service():
    source = Path("experiment/mqtt-broker/scripts/mqtt_broker_ctl.py").read_text(encoding="utf-8")
    assert '"classical-server-auth": "mqtt-classical-server-auth"' in source
    assert 'choices=BROKER_PROFILES' in source
    assert 'service = BROKER_PROFILE_SERVICES[args.profile]' in source
    assert '"--profile",\n            "classical-server-auth"' in source
    assert 'MQTT_CLASSICAL_SERVER_AUTH_TLS_PORT' in source


def test_tls_diagnostics_distinguish_tcp_tls_and_mqtt_state():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    header = Path("Core/Inc/pqc_wolfmqtt_build_only.h").read_text(encoding="utf-8")
    for marker in (
        "WOLFSSL_CBIO_ERR_WANT_READ",
        "WOLFSSL_CBIO_ERR_WANT_WRITE",
        'PQC_WolfMQTT_DiagnosticCode("ca_load"',
        'PQC_WolfMQTT_DiagnosticCode("peer_ip_check"',
        'PQC_WolfMQTT_DiagnosticCode("handshake"',
        "tls_connect_result=",
        "tls_error=",
        "tls_io_error=",
        "first.tcp_connected",
        "first.mqtt_connected",
    ):
        assert marker in source
    assert "bool tcp_connected;" in header
    assert "bool mqtt_connected;" in header
    assert "bool broker_connected;" not in header


def test_tls_peer_ip_setup_precedes_ca_load_and_cannot_report_mqtt_success_on_failure():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    peer_ip = source.index("wolfSSL_check_ip_address")
    ca_load = source.index("wolfSSL_CTX_load_verify_buffer")
    assert peer_ip < ca_load
    assert 'PQC_WolfMQTT_DiagnosticCode("peer_ip_check"' in source
    assert 'return MQTT_CODE_ERROR_TLS_CONNECT;' in source
    assert 'result = MQTT_CODE_SUCCESS;\n    PQC_WolfMQTT_DiagnosticCode("tcp_connect"' in source
    assert 'wolfSSL_check_domain_name(socket_context->tls, PQC_MQTT_TLS_SERVER_NAME)' in source
    assert 'PQC_WolfMQTT_CloseTransport(socket_context); return result;' not in source



def test_m11_config_uses_experiment_selected_fqdn_and_requires_dns():
    config = Path("configs/experiments/mqtt_tls_server_auth_st67_e2e.yaml").read_text(encoding="utf-8")
    assert "host: pqc-gateway1.pqcnet" in config
    assert "server_name: pqc-gateway1.pqcnet" in config
    assert "dns_required: true" in config


def test_firmware_reports_dns_server_and_resolution_and_selects_tls_identity_type():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    for marker in (
        '"ST67 DNS: required=%s server0=%s',
        '"ST67 DNS lookup: result=passed hostname=%s ipv4=%s',
        '"ST67 DNS lookup: result=failed hostname=%s error=%d required=%s',
        "dns_getserver(0)",
        "lwip_getaddrinfo(host",
        "PQC_MQTT_TLS_SERVER_NAME",
        "wolfSSL_check_domain_name",
        "wolfSSL_check_ip_address",
    ):
        assert marker in source


def test_dns_required_controls_uart_pass_markers():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'bool(broker.get("dns_required", False))' in source
    assert '"ST67 DNS: required=true"' in source
    assert '"ST67 DNS lookup: result=passed"' in source


def test_gateway_orchestration_uses_explicit_transport_host_not_firmware_fqdn():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    config = Path("configs/experiments/mqtt_tls_server_auth_st67_e2e.yaml").read_text(encoding="utf-8")
    assert "def _mqtt_orchestration_host(" in source
    assert source.count("shlex.quote(_mqtt_orchestration_host(bundle))") == 2
    assert 'configured = str(orchestration.get("host", "")).strip()' in source
    assert "orchestration:\n    host: 10.1.1.18" in config


def test_classical_certificate_provisioning_defaults_to_selected_fqdn():
    source = Path(
        "experiment/mqtt-broker/scripts/mqtt_broker_ctl.py"
    ).read_text(encoding="utf-8")

    assert 'DEFAULT_SERVER_NAME = "pqc-gateway1.pqcnet"' in source
    assert 'DEFAULT_SERVER_ALIAS = "pqc-gateway1"' in source
    assert (
        "[server_name, DEFAULT_SERVER_ALIAS, "
        '"localhost", *extra_names]'
        in source
    )


def test_runtime_server_certificate_profile_contains_selected_fqdn_san():
    profile = Path(
        "experiment/mqtt-broker/runtime/classical/certs/server-openssl.cnf"
    ).read_text(encoding="utf-8")
    assert "pqc-gateway1.pqcnet" in profile


def test_orchestration_host_validation_is_optional_but_non_empty_when_present():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'mqtt_config.get("orchestration", {})' in source
    assert 'mqtt.orchestration.host must be a non-empty hostname or IP address' in source


def test_classical_server_auth_profile_and_stm32_share_explicit_ecdsa_gcm_suite():
    settings = Path("Core/Inc/pqc_wolfssl_user_settings.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    broker = Path(
        "experiment/mqtt-broker/config/classical-server-auth/mosquitto.conf"
    ).read_text(encoding="utf-8")

    for marker in (
        "#define HAVE_TLS_EXTENSIONS",
        "#define HAVE_SUPPORTED_CURVES",
        "#define HAVE_AESGCM",
    ):
        assert marker in settings

    suite = "ECDHE-ECDSA-AES128-GCM-SHA256"
    assert f'"{suite}"' in source
    assert 'wolfSSL_CTX_set_cipher_list(' in source
    assert 'PQC_WolfMQTT_DiagnosticCode("cipher_list"' in source
    assert f"ciphers {suite}" in broker


def test_gateway_reconnect_orchestration_waits_for_two_exact_responses():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'expected_response_count = 2 if reconnect_attempts > 0 else 1' in source
    assert '-C {expected_response_count}' in source
    assert 'response_count=$(grep -c . "$response_file" || true)' in source
    assert 'matched_count=$(grep -Fxc "$expected" "$response_file" || true)' in source
    assert 'marker.get("response_count") == expected_response_count' in source
    assert 'marker.get("expected_response_count") == expected_response_count' in source


def test_gateway_reconnect_orchestration_keeps_publishing_until_all_responses_arrive():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    subscriber = source.index("mqtt_sub =")
    subscriber_command = source.index("f'{mqtt_sub} -h {client_host}", subscriber)
    publisher_loop = source.index('while kill -0 "$capture_pid"', subscriber_command)
    response_validation = source.index('response_count=$(grep -c .', publisher_loop)
    assert subscriber < publisher_loop < response_validation


def test_firmware_reports_attempted_reconnect_failure_as_failed_not_not_run():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    assert 'bool reconnect_attempted=false;' in source
    assert 'reconnect_attempted=true;' in source
    assert 'reconnect_attempted?(reconnect_result==MQTT_CODE_SUCCESS?"passed":"failed"):"not_run"' in source
    assert 'reconnect_attempted?(second.tls_handshake_complete?"passed":"failed"):"not_run"' in source
    assert 'reconnect_attempted?(second.publish_complete?"passed":"failed"):"not_run"' in source

def test_broker_readiness_waits_for_subscriber_and_captures_return_code():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    publish = source.index("mqtt_pub =")
    publish_command = source.index("f'{mqtt_pub} -h {client_host}", publish)
    wait = source.index('wait "$sub_pid"; sub_rc=$?;', publish_command)
    response = source.index('response=$(paste -sd, "$response_file")', wait)
    readiness_check = source.index('if [ "$sub_rc" -eq 0 ]', response)
    assert publish < publish_command < wait < response < readiness_check



def test_mqtt_uart_capture_uses_completion_marker_grace_and_hard_limit():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    config = Path("configs/experiments/mqtt_tls_server_auth_st67_e2e.yaml").read_text(encoding="utf-8")
    assert 'MQTT_COMPLETION_MARKER = "PQC_EXPERIMENT_COMPLETE experiment=mqtt_tls_server_auth status=done"' in source
    assert 'grep -Fq "$completion_marker" "$uart_file"' in source
    assert 'termination_reason=completion_marker' in source
    assert 'termination_reason=hard_timeout' in source
    assert 'exit "$normalized_capture_rc"' in source
    assert '"capture_termination_reason"' in source
    assert "completion_grace_seconds: 3" in config

def test_mqtt_uart_default_output_is_concise_and_emits_terminal_marker():
    main = Path("Core/Src/main.c").read_text(encoding="utf-8")
    mqtt = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    assert '#define PQC_WIFI_SCAN_VERBOSE 0' in main
    assert '#define PQC_WOLFMQTT_TLS_IO_TRACE 0' in mqtt
    assert 'PQC_EXPERIMENT_COMPLETE experiment=mqtt_tls_server_auth status=done' in main
    assert 'if ((!app_experiment_complete) && ((heartbeat_seconds % 5U) == 0U))' in main
    assert 'wolfMQTT plaintext exchange:' not in main + mqtt
