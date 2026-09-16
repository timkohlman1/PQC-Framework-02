from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MQTT_BROKER_CTL = REPO_ROOT / "experiment" / "mqtt-broker" / "scripts" / "mqtt_broker_ctl.py"
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from framework.config_resolver import ConfigResolver

def _resolved_experiment():
    resolver = ConfigResolver(REPO_ROOT)
    case = next(c for c in resolver.expand_campaign("tls_key_exchange") if c["choices"]["tls_kex"] == "secp256r1")
    return resolver.to_legacy_bundle(case, resolve_secrets=False)["experiment"]


def _load_mqtt_broker_ctl_module():
    spec = importlib.util.spec_from_file_location("mqtt_broker_ctl_tls_server_auth_test", MQTT_BROKER_CTL)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_server_authenticated_tls_profile_is_separate_from_mutual_tls():
    compose = Path("experiment/mqtt-broker/compose.yaml").read_text(encoding="utf-8")
    server_auth = Path("experiment/mqtt-broker/config/classical-server-auth/mosquitto.conf").read_text(encoding="utf-8")
    mutual = Path("experiment/mqtt-broker/config/classical/mosquitto.conf").read_text(encoding="utf-8")
    assert 'profiles: ["classical-server-auth"]' in compose
    assert "require_certificate false" in server_auth
    assert "tls_version tlsv1.3" in server_auth
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


def test_generated_header_keeps_client_credentials_mutual_tls_only():
    source = Path("scripts/framework/build.py").read_text(encoding="utf-8")
    server_auth = _resolved_experiment()

    assert "PQC_MQTT_TLS_CA_PEM" in source
    assert "ca_certificate" in source
    assert "Provision the selected broker certificates before building" in source
    assert 'authentication = str(tls.get("authentication", "server"))' in source
    assert 'mutual_tls = authentication == "mutual"' in source
    assert "if mutual_tls:" in source
    assert 'client_certificate_pem = ""' in source
    assert 'client_private_key_pem = ""' in source
    assert server_auth["mqtt"]["tls"]["authentication"] == "server"


def test_m11_config_selects_server_auth_profile_and_reconnect():
    mqtt = _resolved_experiment()["mqtt"]
    assert mqtt["evidence_class"] == "stm32_st67_classical_tls_e2e"
    assert mqtt["transport_backend"] == "st67w61m1_lwip_wolfssl"
    assert mqtt["broker_profile"] == "classical-server-auth"
    assert mqtt["tls"]["mode"] == "classical_tls_server_auth"
    assert mqtt["reconnect_attempts"] == 1


def test_managed_broker_cleanup_receives_bundle_and_uses_selected_profile():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert "def _collect_and_stop_managed_mqtt_broker(" in source
    assert "bundle: dict[str, dict[str, Any]]" in source
    assert source.count(
        "_collect_and_stop_managed_mqtt_broker(bundle=bundle, repo_root=repo_root, result_dir=result_dir)"
    ) >= 3
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
        'PQC_WolfMQTT_DiagnosticCode("peer_identity_check"',
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
    assert 'PQC_WolfMQTT_DiagnosticCode("peer_identity_check"' in source
    assert 'return MQTT_CODE_ERROR_TLS_CONNECT;' in source
    assert "result = MQTT_CODE_SUCCESS;" in source
    assert 'if (!socket_context->tls_requested) {' in source
    assert 'PQC_WolfMQTT_DiagnosticCode("tcp_connect", result, 0);' in source
    assert 'wolfSSL_check_domain_name(socket_context->tls, PQC_MQTT_TLS_SERVER_NAME)' in source
    assert 'PQC_WolfMQTT_CloseTransport(socket_context); return result;' not in source



def test_m11_config_uses_experiment_selected_fqdn_and_requires_dns():
    broker = _resolved_experiment()["mqtt"]["broker"]
    assert broker["host"] == "pqc-gateway1.pqcnet"
    assert broker["server_name"] == "pqc-gateway1.pqcnet"
    assert broker["dns_required"] is True


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


def test_dns_required_uart_pass_markers_are_not_mandatory_for_tls():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'bool(broker.get("dns_required", False))' in source
    assert 'and not is_tls' in source
    assert '"ST67 DNS: required=true"' in source
    assert '"ST67 DNS lookup: result=passed"' in source


def test_gateway_orchestration_uses_explicit_transport_host_not_firmware_fqdn():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    config = _resolved_experiment()
    assert "def _mqtt_orchestration_host(" in source
    assert source.count("_mqtt_gateway_client_host(bundle, tls_enabled=tls_enabled)") == 2
    assert 'configured = str(orchestration.get("host", "")).strip()' in source
    assert config["mqtt"]["orchestration"]["host"] == "10.1.1.18"





def test_orchestration_host_validation_is_optional_but_non_empty_when_present():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'mqtt_config.get("orchestration", {})' in source
    assert 'mqtt.orchestration.host must be a non-empty hostname or IP address' in source


def test_classical_server_auth_profile_and_stm32_are_tls13_only_without_tls12_cipher_pin():
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

    assert "wolfTLSv1_3_client_method()" in source
    assert "wolfTLSv1_2_client_method()" not in source
    assert "ECDHE-ECDSA-AES128-GCM-SHA256" not in source
    assert "wolfSSL_CTX_set_cipher_list(" not in source
    assert "tls_version tlsv1.3" in broker
    assert "tls_version tlsv1.2" not in broker
    assert "ciphers ECDHE-ECDSA-AES128-GCM-SHA256" not in broker


def test_gateway_reconnect_orchestration_uses_one_workload_response_for_deferred_metrics():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert 'expected_response_count = 1 if ready_metrics_application else (2 if reconnect_attempts > 0 else 1)' in source
    assert '-C {expected_response_count}' in source
    assert 'response_count=$(grep -c . "$response_file" || true)' in source
    assert 'marker.get("response_count") == expected_response_count' in source
    assert 'marker.get("expected_response_count") == expected_response_count' in source
    assert 'reporting_completion_topic = f"pqc/result/stm32/{result_dir.name}/complete"' in source


def test_gateway_reconnect_orchestration_keeps_publishing_until_all_responses_arrive():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    capture = source[source.index("def _execute_mqtt_e2e_uart_capture"):]
    subscriber = capture.index("mqtt_sub =")
    subscriber_command = capture.index("f'{mqtt_sub} -h {client_host}", subscriber)
    common_suffix = capture.index("common_suffix =", subscriber_command)
    response_validation = capture.index('response_count=$(grep -c .', common_suffix)
    legacy_branch = capture.index("    else:\n        script = (", response_validation)
    publisher_loop = capture.index('while kill -0 "$capture_pid"', legacy_branch)
    suffix_use = capture.index("+ common_suffix", publisher_loop)
    assert subscriber < subscriber_command < common_suffix < response_validation < legacy_branch < publisher_loop < suffix_use


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
    publish_command = source.index("f'{mqtt_pub} -h {host}", publish)
    wait = source.index('wait "$sub_pid"; sub_rc=$?;', publish_command)
    response = source.index('response=$(paste -sd, "$response_file")', wait)
    readiness_check = source.index('if [ "$sub_rc" -eq 0 ]', response)
    assert publish < publish_command < wait < response < readiness_check



def test_mqtt_capture_uses_reporting_completion_grace_and_hard_limit():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    config = _resolved_experiment()
    assert 'reporting_completion_topic = f"pqc/result/stm32/{result_dir.name}/complete"' in source
    assert 'grep -Fq "$reporting_completion_topic"' in source
    assert 'termination_reason=reporting_complete' in source
    assert 'termination_reason=hard_timeout' in source
    assert 'reporting_complete_present=$reporting_complete_seen' in source
    assert 'exit "$normalized_capture_rc"' in source
    assert '"capture_termination_reason"' in source
    assert '"reporting_complete_present"' in source
    assert config["mqtt"]["orchestration"]["completion_grace_seconds"] == 3

def test_mqtt_uart_default_output_is_concise_and_emits_terminal_marker():
    main = Path("Core/Src/main.c").read_text(encoding="utf-8")
    mqtt = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    assert '#define PQC_WIFI_SCAN_VERBOSE 0' in main
    assert '#define PQC_WOLFMQTT_TLS_IO_TRACE 0' in mqtt
    assert 'PQC_EXPERIMENT_COMPLETE experiment=" PQC_MQTT_TLS_MODE " status=done' in main
    assert 'const char tick_msg[] = "tick\\r\\n";' not in main
    assert 'APP_UART_WriteTickPrefix' in main
    assert 'wolfMQTT plaintext exchange:' not in main + mqtt


def test_tls_setup_diagnostics_distinguish_allocation_from_ca_loading():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    header = Path("Core/Inc/pqc_wolfmqtt_build_only.h").read_text(encoding="utf-8")

    for marker in (
        "tls_context=%s",
        "tls_session=%s",
        "tls_peer_identity=%s",
        'first.ca_load_attempted?(first.ca_loaded?"passed":"failed"):"not_run"',
        "PQC_TLS_InstrumentationSetPreMemory(",
        "PQC_TLS_InstrumentationSetPostMemory(",
    ):
        assert marker in source

    for field in (
        "bool tls_context_created;",
        "bool tls_session_created;",
        "bool tls_peer_identity_configured;",
        "bool ca_load_attempted;",
    ):
        assert field in header
def test_classical_tls_profile_keeps_the_pre_diagnostic_freertos_heap_size():
    config = Path("Core/Inc/FreeRTOSConfig.h").read_text(encoding="utf-8")
    assert "#define configTOTAL_HEAP_SIZE                    ((size_t)(96 * 1024))" in config


def test_wolfssl_session_failure_uses_link_safe_diagnostics_and_closes_before_client_hello():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    assert "wolfSSL_ERR_get_error()" not in source
    assert "wolfSSL_ERR_error_string_n" not in source
    assert 'PQC_WolfMQTT_DiagnosticWolfSSLState("session_create")' in source
    assert "error_queue=unavailable" in source
    assert 'PQC_WolfMQTT_DiagnosticCode("wolfssl_init", wolfssl_init_result, 0)' in source
    assert "wolfMQTT TLS: stage=session_create result=null tcp_close_before_clienthello=true" in source
    assert "return MQTT_CODE_ERROR_TLS_CONNECT;" in source
    assert "return MQTT_CODE_ERROR_MEMORY;" not in source


def test_wolfssl_session_creation_uses_link_safe_failure_diagnostics():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    assert "WOLFSSL_METHOD *tls_method;" in source
    assert "tls_method = wolfTLSv1_3_client_method();" in source
    assert "socket_context->tls = wolfSSL_new(socket_context->tls_ctx);" in source
    assert 'PQC_WolfMQTT_DiagnosticCode("session_create", -1, errno);' in source
    assert 'PQC_WolfMQTT_DiagnosticWolfSSLState("session_create");' in source
    assert '"wolfMQTT TLS: stage=session_create result=null tcp_close_before_clienthello=true' in source


def test_all_tls_profiles_validate_the_configured_group_before_session_creation():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    assert 'if (socket_context->tls_requested) {' in source
    group_start = source.index('if (socket_context->tls_requested) {')
    session_start = source.index("socket_context->tls = wolfSSL_new(socket_context->tls_ctx);", group_start)
    group_block = source[group_start:session_start]

    assert 'int groups[] = { PQC_TLS_GROUP_ID };' in group_block
    assert 'PQC_WolfMQTT_DiagnosticCode("pqc_group_config", result, 0);' in group_block
    assert 'if (result != WOLFSSL_SUCCESS)' in group_block
    assert 'return MQTT_CODE_ERROR_TLS_CONNECT;' in group_block


def test_tls_context_and_transport_close_are_reported_directly():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    assert 'PQC_WolfMQTT_DiagnosticCode("context_create", -1, errno);' in source
    assert '"wolfMQTT TLS: stage=context_create result=null tcp_close_before_clienthello=true' in source
    assert '"wolfMQTT transport: stage=close socket_fd=%d tcp_connected=%d tls_context=%p tls_session=%p' in source





def test_dns_server_diagnostic_does_not_issue_a_second_dns_query():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    diagnostic_start = source.index("static void PQC_WolfMQTT_DiagnosticDnsServer")
    resolve_start = source.index("static int PQC_WolfMQTT_ResolveBroker")
    diagnostic_body = source[diagnostic_start:resolve_start]

    assert "dns_getserver(0)" in diagnostic_body
    assert "lwip_getaddrinfo(" not in diagnostic_body
    assert source.count("lwip_getaddrinfo(host") == 1

def test_mldsa_mutual_tls_credentials_are_session_scoped_while_classical_remains_context_scoped():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    session_create = source.index("socket_context->tls = wolfSSL_new(socket_context->tls_ctx);")
    ctx_certificate = source.index("wolfSSL_CTX_use_certificate_buffer")
    ctx_private_key = source.index("wolfSSL_CTX_use_PrivateKey_buffer")
    session_certificate = source.index("wolfSSL_use_certificate_buffer")
    session_private_key = source.index("wolfSSL_use_PrivateKey_buffer")

    assert "#if !PQC_TLS_ENABLE_MLDSA_65_SIGN" in source
    assert "#if PQC_TLS_ENABLE_MLDSA_65_SIGN" in source
    assert ctx_certificate < session_create
    assert ctx_private_key < session_create
    assert session_create < session_certificate
    assert session_create < session_private_key
