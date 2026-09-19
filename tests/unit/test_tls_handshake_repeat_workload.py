from pathlib import Path


def test_repeated_tls_application_is_wired_as_a_distinct_firmware_fixture():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    header = Path("Core/Inc/pqc_mqtt_application.h").read_text(encoding="utf-8")
    application = Path("Core/Src/pqc_mqtt_application_tls_handshake_repeat.c").read_text(encoding="utf-8")

    assert 'PQC_STM32_MQTT_APPLICATION STREQUAL "tls_handshake_repeat"' in cmake
    assert "Core/Src/pqc_mqtt_application_tls_handshake_repeat.c" in cmake
    assert "PQC_TLS_HANDSHAKES_PER_RUN" in cmake
    assert "run_tls_handshake_repeat_workload" in header
    assert "run_network_bringup();" in application
    assert application.count("run_network_bringup();") == 1
    assert "PQC_TLS_HANDSHAKES_PER_RUN" in application


def test_repeated_tls_runtime_uses_fresh_connection_context_and_per_iteration_reporting():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")

    start = source.index("int PQC_WolfMQTT_RunTLSHandshakeRepeatApplication(")
    end = source.index("static int PQC_WolfMQTT_PublishText", start)
    repeat = source[start:end]

    assert "for (iteration = 0U; iteration < handshakes_per_run; ++iteration)" in repeat
    assert "PQC_ResultBufferReset();" in repeat
    assert "PQC_TLS_InstrumentationReset(iteration, iteration);" in repeat
    assert "MqttClient_Init(" in repeat
    assert "MqttClient_NetConnect(" in repeat
    assert "MqttClient_Connect(" not in repeat
    assert "MqttClient_NetDisconnect(" in repeat
    assert "MqttClient_DeInit(" in repeat
    assert "PQC_WolfMQTT_PublishDeferredResults(" in repeat
    assert repeat.index("MqttClient_NetDisconnect(") < repeat.index("PQC_WolfMQTT_PublishDeferredResults(")
    assert "session_resumption=0" in source
    assert "fresh_tcp_connection=1 fresh_tls_context=1" in source


def test_repeat_handshake_timing_uses_existing_tim2_microsecond_snapshot_not_new_dwt_timer():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    instrumentation = Path("Core/Src/pqc_tls_instrumentation.c").read_text(encoding="utf-8")

    assert "timing_source=TIM2_1MHz handshake_elapsed_us=%s" in source
    assert "PQC_WolfMQTT_FormatU64(" in source
    assert "snapshot->handshake_elapsed_us" in source
    assert "%llu" not in source
    assert "PQC_TimebaseNowUs()" in instrumentation
    assert "PQC_TLS_InstrumentationBegin(PQC_TLS_EVENT_HANDSHAKE);" in source
    assert "PQC_TLS_InstrumentationEnd(PQC_TLS_EVENT_HANDSHAKE, result);" in source


def test_repeat_result_record_carries_iteration_negotiation_auth_and_cleanup_evidence():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    for fragment in (
        "PQC_TLS_REPEAT_ITERATION schema=1 iteration=%lu handshake=%lu",
        "selected_kex=%s negotiated_kex=%s kex_match=%u",
        "auth_mode=%s auth_profile=%s configured_signature_scheme=%s",
        "authentication_verified=%u",
        "instrumentation_overflow=%u",
        "instrumentation_truncated=%u",
        "instrumentation_incomplete=%u",
        "disconnect_result=%d cleanup_ok=%u",
    ):
        assert fragment in source


def test_repeat_application_skips_generic_final_buffer_publish_to_avoid_extra_epoch():
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert "#if !PQC_TLS_HANDSHAKE_REPEAT_ENABLED" in main_c
    assert ".run_tls_handshake_repeat_workload = APP_RunTLSHandshakeRepeatWorkload" in main_c


def test_tls_only_broker_evidence_excludes_mqtt_message_checks_without_bypassing_other_workloads():
    """The TLS-only workload never opens an experiment-broker MQTT session."""
    import ast
    from typing import Any

    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_parse_mqtt_broker_message_evidence"
    )
    namespace = {"Any": Any}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "scripts/experiment.py", "exec"), namespace)
    parse = namespace["_parse_mqtt_broker_message_evidence"]
    kwargs = {
        "stm32_client_id": "stm32",
        "publisher_client_id": "host-publisher",
        "subscriber_client_id": "host-subscriber",
        "command_topic": "experiment/command",
        "response_topic": "experiment/response",
    }
    observed_log = "New connection from 192.0.2.2:4000 on port 8883.\nClient unknown disconnected.\n"
    tls_only = parse(observed_log, tls_handshake_repeat=True, **kwargs)
    assert tls_only["status"] == "not_applicable"
    assert tls_only["evidence_contract"] == "tls_handshake_repeat_tls_only"
    assert tls_only["passed"] is True
    assert not any(key.startswith("command_") or key.startswith("response_") for key in tls_only)

    # Existing device-initiated MQTT and command/response workloads still
    # require actual MQTT packet-routing evidence; absent logs must fail.
    assert parse(observed_log, device_initiated=True, **kwargs)["passed"] is False
    assert parse(observed_log, device_initiated=False, **kwargs)["passed"] is False


def test_repeat_runner_keeps_broker_log_and_collector_checks_mandatory():
    source = Path("scripts/experiment.py").read_text(encoding="utf-8")
    assert "tls_handshake_repeat=tls_handshake_repeat_application" in source
    assert '"required_for_pass": not tls_handshake_repeat_application' in source
    assert 'elif passed and not broker_log_integrity.get("passed", False):' in source
    assert 'elif passed and not broker_message_evidence.get("available", False):' in source
    assert '"completion_integrity": collector_result.validation.passed' in source
