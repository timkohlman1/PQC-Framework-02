from pathlib import Path

def test_ready_metrics_application_is_profile_selected_and_persistent():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    app = Path("Core/Src/pqc_mqtt_application_ready_metrics.c").read_text(encoding="utf-8")
    assert 'PQC_STM32_MQTT_APPLICATION STREQUAL "mqtt_ready_metrics"' in cmake
    assert 'run_ready_metrics_workload' in app
    assert 'before_tcp_connect' in source
    assert '"ready"' in source
    assert 'connect_timing' in source
    assert 'vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000U))' in source
    assert 'uxTaskGetStackHighWaterMark(NULL)' in source
    assert 'xPortGetFreeHeapSize()' in source
    assert 'xPortGetMinimumEverFreeHeapSize()' in source
    assert 'metrics_count == 2U' in source
    assert 'for (;;) {' in source


def test_application_entry_point_is_owned_only_by_root_cmake():
    root_cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    cubemx_cmake = Path("cmake/stm32cubemx/CMakeLists.txt").read_text(encoding="utf-8")

    assert "${PQC_STM32_MQTT_APPLICATION_SOURCE}" in root_cmake
    assert "Core/App/mqtt_validation/pqc_mqtt_validation_application.c" not in cubemx_cmake
    assert "PQC_STM32_MQTT_APPLICATION_SOURCE" not in cubemx_cmake
    assert "target_sources(${CMAKE_PROJECT_NAME} PRIVATE ${PQC_STM32_MQTT_APPLICATION_SOURCE})" not in cubemx_cmake


def _load_experiment_cli():
    import importlib.util
    import sys

    scripts = str(Path("scripts").resolve())
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location(
        "experiment_cli_ready_metrics_host", Path("scripts/experiment.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ready_metrics_subscriber_contract_accepts_expected_messages():
    cli = _load_experiment_cli()
    topic = "pqc/experiments/stm32/secp256r1/mutual_auth/response"
    lines = [
        f"{topic} ready",
        f'{topic} {{"type":"connect_timing","milliseconds":5368,"tls_mode":"classical_tls_mutual"}}',
    ]
    lines.extend(
        f'{topic} {{"type":"memory_metrics","sequence":{sequence},'
        f'"stack_high_water_words":926,"heap_free_bytes":8640,'
        f'"heap_min_ever_bytes":5280}}'
        for sequence in range(1, 3)
    )

    evidence = cli._parse_ready_metrics_subscriber_output(
        "\n".join(lines) + "\n", response_topic=topic
    )

    assert evidence["passed"] is True
    assert evidence["message_count"] == 4
    assert evidence["ready_count"] == 1
    assert evidence["timing_count"] == 1
    assert evidence["metrics_count"] == 2
    assert evidence["metric_sequences"] == [1, 2]


def test_ready_metrics_subscriber_contract_rejects_missing_metric():
    cli = _load_experiment_cli()
    topic = "pqc/test/response"
    output = "\n".join(
        [
            f"{topic} ready",
            f'{topic} {{"type":"connect_timing","milliseconds":10,"tls_mode":"plaintext"}}',
            *[
                f'{topic} {{"type":"memory_metrics","sequence":{sequence},'
                f'"stack_high_water_words":1,"heap_free_bytes":2,'
                f'"heap_min_ever_bytes":2}}'
                for sequence in range(1, 2)
            ],
        ]
    )

    evidence = cli._parse_ready_metrics_subscriber_output(
        output + "\n", response_topic=topic
    )

    assert evidence["passed"] is False
    assert evidence["metrics_count"] == 1
    assert evidence["metrics_valid"] is False


def test_ready_metrics_host_validator_is_device_initiated():
    cli_source = Path("scripts/experiment.py").read_text(encoding="utf-8")

    assert 'expected_response_count = 17 if ready_metrics_2_application' in cli_source
    assert 'Publisher disabled: selected ready-metrics application is device-initiated.' in cli_source
    assert 'Starting MQTT ready/timing/metrics validation' in cli_source
    assert 'ready_connect_timing_two_memory_metrics' in cli_source
    assert 'PQC_APP_METRICS sequence=2' in cli_source



def test_ready_metrics_2_application_defines_paper_comparable_ttfb_boundary():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    app = Path("Core/Src/pqc_mqtt_application_ready_metrics_2.c").read_text(encoding="utf-8")
    header = Path("Core/Inc/pqc_wolfmqtt_build_only.h").read_text(encoding="utf-8")

    assert 'PQC_STM32_MQTT_APPLICATION STREQUAL "mqtt_ready_metrics_2"' in cmake
    assert "run_ready_metrics_2_workload" in app
    assert "PQC_WolfMQTTReadyMetrics2Snapshot" in header
    assert "actual lwip_connect() call" in source
    assert "mqtt_first_response_armed = true" in source
    assert "mqtt_first_response_tick_ms = first_byte_tick" in source
    assert "tcp_connect_start_to_first_mqtt_connack_plaintext_byte" in source
    assert '\\"dns_included\\":false' in source
    assert "PQC_TLS_InstrumentationReport(PQC_WolfMQTT_DiagnosticMarker);" in source
    rm2_source = source[source.index("int PQC_WolfMQTT_RunReadyMetrics2Application("):]
    assert "PQC_MQTT_TRANSFER_RESPONSE_TOPIC" in rm2_source
    assert "PQC_MQTT_TRANSFER_REQUEST_TOPIC" in rm2_source
    assert "tcp_connect_start_to_last_byte_of_requested_application_payload" in rm2_source
    assert "message_context.transfer_received_bytes" in rm2_source
    assert rm2_source.index("while (!message_context.transfer_complete)") < rm2_source.index(
        'result = PQC_WolfMQTT_PublishText(&client, "ready", 4U);'
    )


def test_ready_metrics_2_subscriber_contract_accepts_complete_result_bundle():
    cli = _load_experiment_cli()
    topic = "pqc/test/response"
    messages = [
        "ready",
        '{"type":"connect_timing","milliseconds":3200,"tls_mode":"classical_tls_server_auth"}',
        '{"type":"memory_metrics","sequence":1,"stack_high_water_words":900,"heap_free_bytes":8000,"heap_min_ever_bytes":7000}',
        '{"type":"memory_metrics","sequence":2,"stack_high_water_words":890,"heap_free_bytes":7900,"heap_min_ever_bytes":6900}',
        '{"type":"experiment_timing","schema_version":1,"ttfb_definition":"tcp_connect_start_to_first_mqtt_connack_plaintext_byte","dns_included":false,"tcp_connect_ms":20,"ttfb_ms":3020,"mqtt_connect_ms":3030,"legacy_connect_timing_ms":3200,"tls_timing_valid":1,"first_response_valid":1}',
        '{"type":"boot_timing","schema_version":1,"firmware_boot_origin":"post_hal_init","boot_to_tcp_connect_ms":1100,"boot_to_tls_complete_ms":4000,"boot_to_mqtt_first_response_ms":4100,"boot_to_mqtt_connected_ms":4110,"boot_to_application_first_byte_ms":4300,"boot_to_application_last_byte_ms":6000,"boot_to_ready_publish_ms":6010}',
        '{"type":"tls_handshake_timing","schema_version":1,"available":1,"result":1,"cycle_counter_available":1,"elapsed_cycles":100,"elapsed_ms":3000,"stack_before_min_free_bytes":1000,"stack_after_min_free_bytes":900,"heap_before_free_bytes":8000,"heap_after_free_bytes":7000,"heap_before_min_ever_free_bytes":7500,"heap_after_min_ever_free_bytes":6900}',
        '{"type":"tls_phase_timing","schema_version":1,"values":[[1,1,1,1,1,1],[1,1,1,1,1,1],[1,1,1,1,1,1],[1,1,1,1,1,1],[1,1,1,1,1,1]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":1,"first_index":0,"last_index":3,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":2,"first_index":4,"last_index":7,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":3,"first_index":8,"last_index":11,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":4,"first_index":12,"last_index":15,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":5,"first_index":16,"last_index":19,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":6,"first_index":20,"last_index":22,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_x509_verify_timing","schema_version":1,"count":2,"overflow":0,"elapsed_cycles":[1,2,0,0]}',
        '{"type":"application_transfer_timing","schema_version":1,"ttlb_definition":"tcp_connect_start_to_last_byte_of_requested_application_payload","direction":"broker_to_stm32","payload_bytes":204800,"received_bytes":204800,"message_count":512,"chunk_bytes":400,"application_ttfb_ms":3300,"ttlb_ms":5000,"request_to_first_byte_ms":100,"application_transfer_ms":1700,"first_byte_valid":1,"last_byte_valid":1,"complete_valid":1}',
        '{"type":"ready_metrics_2_complete","schema_version":1,"status":"success","message_count":17}',
    ]
    output = "\n".join(f"{topic} {message}" for message in messages) + "\n"

    evidence = cli._parse_ready_metrics_2_subscriber_output(output, response_topic=topic)

    assert evidence["passed"] is True
    assert evidence["message_count"] == 17
    assert evidence["timing_valid"] is True
    assert evidence["primitive_parts"] == [1, 2, 3, 4, 5, 6]
    assert evidence["complete_valid"] is True
    assert evidence["experiment_timing"]["ttfb_ms"] == 3020
    assert evidence["application_transfer_timing"]["ttlb_ms"] == 5000


def test_ready_metrics_2_subscriber_contract_rejects_wrong_ttfb_definition():
    cli = _load_experiment_cli()
    topic = "pqc/test/response"
    output = (
        f'{topic} {{"type":"experiment_timing","schema_version":1,'
        '"ttfb_definition":"before_dns_to_connack","dns_included":true,'
        '"firmware_boot_origin":"post_hal_init","tcp_connect_ms":1,"ttfb_ms":2,'
        '"mqtt_connect_ms":3,"legacy_connect_timing_ms":4,"boot_to_tcp_connect_ms":5,'
        '"boot_to_tls_complete_ms":6,"boot_to_mqtt_first_response_ms":7,'
        '"boot_to_mqtt_connected_ms":8,"boot_to_application_first_byte_ms":9,"boot_to_application_last_byte_ms":10,"boot_to_ready_publish_ms":11,'
        '"tls_timing_valid":1,"first_response_valid":1}\n'
    )
    evidence = cli._parse_ready_metrics_2_subscriber_output(output, response_topic=topic)
    assert evidence["passed"] is False
    assert evidence["timing_valid"] is False


def test_ready_metrics_2_subscriber_contract_accepts_plaintext_result_bundle():
    cli = _load_experiment_cli()
    topic = "pqc/test/plaintext/response"
    messages = [
        "ready",
        '{"type":"connect_timing","milliseconds":40,"tls_mode":"plaintext"}',
        '{"type":"memory_metrics","sequence":1,"stack_high_water_words":900,"heap_free_bytes":8000,"heap_min_ever_bytes":7000}',
        '{"type":"memory_metrics","sequence":2,"stack_high_water_words":890,"heap_free_bytes":7900,"heap_min_ever_bytes":6900}',
        '{"type":"experiment_timing","schema_version":1,"ttfb_definition":"tcp_connect_start_to_first_mqtt_connack_plaintext_byte","dns_included":false,"tcp_connect_ms":6,"ttfb_ms":35,"mqtt_connect_ms":35,"legacy_connect_timing_ms":40,"tls_timing_valid":0,"first_response_valid":1}',
        '{"type":"boot_timing","schema_version":1,"firmware_boot_origin":"post_hal_init","boot_to_tcp_connect_ms":6100,"boot_to_tls_complete_ms":0,"boot_to_mqtt_first_response_ms":6129,"boot_to_mqtt_connected_ms":6129,"boot_to_application_first_byte_ms":6144,"boot_to_application_last_byte_ms":6594,"boot_to_ready_publish_ms":6595}',
        '{"type":"tls_handshake_timing","schema_version":1,"available":0,"result":0,"cycle_counter_available":0,"elapsed_cycles":0,"elapsed_ms":0,"stack_before_min_free_bytes":0,"stack_after_min_free_bytes":0,"heap_before_free_bytes":0,"heap_after_free_bytes":0,"heap_before_min_ever_free_bytes":0,"heap_after_min_ever_free_bytes":0}',
        '{"type":"tls_phase_timing","schema_version":1,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":1,"first_index":0,"last_index":3,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":2,"first_index":4,"last_index":7,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":3,"first_index":8,"last_index":11,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":4,"first_index":12,"last_index":15,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":5,"first_index":16,"last_index":19,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_primitive_timing","schema_version":1,"part":6,"first_index":20,"last_index":22,"values":[[0,0,0,0,0,0],[0,0,0,0,0,0],[0,0,0,0,0,0]]}',
        '{"type":"tls_x509_verify_timing","schema_version":1,"count":0,"overflow":0,"elapsed_cycles":[0,0,0,0]}',
        '{"type":"application_transfer_timing","schema_version":1,"ttlb_definition":"tcp_connect_start_to_last_byte_of_requested_application_payload","direction":"broker_to_stm32","payload_bytes":204800,"received_bytes":204800,"message_count":512,"chunk_bytes":400,"application_ttfb_ms":50,"ttlb_ms":500,"request_to_first_byte_ms":10,"application_transfer_ms":450,"first_byte_valid":1,"last_byte_valid":1,"complete_valid":1}',
        '{"type":"ready_metrics_2_complete","schema_version":1,"status":"success","message_count":17}',
    ]
    output = "\n".join(f"{topic} {message}" for message in messages) + "\n"

    evidence = cli._parse_ready_metrics_2_subscriber_output(output, response_topic=topic)

    assert evidence["passed"] is True
    assert evidence["timing_valid"] is True
    assert evidence["boot_timing_valid"] is True
    assert evidence["experiment_timing"]["tls_timing_valid"] == 0
    assert evidence["boot_timing"]["boot_to_tls_complete_ms"] == 0
    assert evidence["application_transfer_timing"]["received_bytes"] == 204800
