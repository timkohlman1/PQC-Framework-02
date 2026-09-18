from pathlib import Path
import json

def test_ready_metrics_application_is_profile_selected_and_returns_for_deferred_reporting():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    app = Path("Core/Src/pqc_mqtt_application_ready_metrics.c").read_text(encoding="utf-8")
    main = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert 'PQC_STM32_MQTT_APPLICATION STREQUAL "mqtt_ready_metrics"' in cmake
    assert 'run_ready_metrics_workload' in app
    assert 'before_tcp_connect' in source
    assert '"ready"' in source
    assert 'connect_timing' in source
    assert 'vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000U))' not in source
    assert 'metrics_count == 2U' not in source
    assert 'PQC_ResultBufferAppendText(0U, "memory", line)' in main
    assert 'PQC_WolfMQTT_PublishDeferredResults' in main


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


def test_ready_metrics_host_validator_uses_workload_ready_plus_reporting_collector():
    cli_source = Path("scripts/experiment.py").read_text(encoding="utf-8")

    assert 'expected_response_count = 1 if ready_metrics_application' in cli_source
    assert 'scientific evidence is deferred to the reporting broker' in cli_source
    assert 'reporting_completion_topic = f"pqc/result/stm32/{result_dir.name}/complete"' in cli_source
    assert 'stop_and_collect_gateway_result_collector(' in cli_source
    pass_predicate = cli_source[cli_source.index('broker_response_passed = ('):cli_source.index('passed = broker_response_passed')]
    assert 'missing_uart_markers' not in pass_predicate



def test_ready_metrics_2_application_uses_microsecond_timebase_and_deferred_reporting():
    cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text(encoding="utf-8")
    header = Path("Core/Inc/pqc_wolfmqtt_build_only.h").read_text(encoding="utf-8")

    assert 'PQC_STM32_MQTT_APPLICATION STREQUAL "mqtt_ready_metrics_2"' in cmake
    assert "Core/Src/pqc_timebase.c" in cmake
    assert "PQC_WolfMQTTReadyMetrics2Snapshot" in header
    assert "tcp_connect_start_us = PQC_TimebaseNowUs();" in source
    assert "mqtt_readiness_checkpoint_us" in source
    assert "application_request_us = PQC_TimebaseNowUs();" in source
    assert "transfer_first_byte_us = PQC_TimebaseNowUs();" in source
    assert "transfer_last_byte_us = PQC_TimebaseNowUs();" in source
    assert "HAL_GetTick()" not in source
    assert "xTaskGetTickCount()" not in source[source.index("int PQC_WolfMQTT_RunReadyMetrics2Application("):]
    assert 'application_timebase' in source
    assert '"schema_version\\":3' in source
    for field in ("rtfb_us", "rtlb_us", "ttfb_us", "ttlb_us", "req_tfb_us", "req_tlb_us"):
        assert field in source
    assert "application_ttfb_us" not in source
    assert "request_to_first_byte_us" not in source
    assert "ttfb_ms_legacy" not in source
    assert "mqtt_readiness_definition" in source
    assert "application_timing_checkpoints" in source
    assert "PQC_RM2_METRICS schema=3 ttfb_us=" in source
    assert "PQC_RM2_RESET schema=3 reset_origin=operational_wolfboot_entry" in source
    assert "PQC_RM2_MQTT_READINESS schema=3" in source
    main = Path("Core/Src/main.c").read_text(encoding="utf-8")
    assert "APP_BufferReadyMetrics2Evidence();" in main
    assert 'PQC_ResultBufferAppendText(0U, "rm2_timebase", line)' in main
    assert 'PQC_ResultBufferAppendText(0U, "rm2_checkpoints", line)' in main
    assert 'PQC_ResultBufferAppendText(0U, "rm2_metrics", line)' in main
    assert 'PQC_ResultBufferAppendText(0U, "rm2_complete", line)' in main
    assert "PQC_RM2_TIMEBASE schema=3" in main
    assert "PQC_RM2_CHECKPOINTS schema=3" in main
    assert "PQC_RM2_METRICS schema=3 metric_contract=ready_metrics_2_canonical_v3" in main
    assert "mqtt_readiness_definition=tcp_connect_start_to_first_mqtt_connack_plaintext_byte" in main
    assert "application_ttfb_us" not in main
    network_task = main[main.index("void StartNetworkTask(void *argument)"):]
    assert network_task.index("app_measurement_active = false;") < network_task.index(
        "APP_BufferReadyMetrics2Evidence();"
    ) < network_task.index("PQC_WolfMQTT_PublishDeferredResults(")
    assert "transfer_chunk_bytes" in header
    assert "s_ready_metrics_2_snapshot.transfer_chunk_bytes" in source
    rm2_source = source[source.index("int PQC_WolfMQTT_RunReadyMetrics2Application("):]
    assert rm2_source.index("while (!message_context.transfer_complete)") < rm2_source.index(
        'result = PQC_WolfMQTT_PublishText(&client, "ready", 4U);'
    )


def _rm2_bundle(*, tls: bool, reset_origin: bool) -> list[str]:
    phase = [1, 1, 1, 1, 1, 1, 10, 20] if tls else [0] * 8
    primitive_ranges = [(1, 0, 3), (2, 4, 7), (3, 8, 11), (4, 12, 15), (5, 16, 19), (6, 20, 24)]
    if tls:
        tcp_start = 100_000
        mqtt_ready_checkpoint = 3_120_000
        app_request = 3_200_000
        app_first = 3_400_000
        app_last = 5_100_000
        reset_offset = 1_000_000 if reset_origin else 0
    else:
        tcp_start = 10_000
        mqtt_ready_checkpoint = 45_000
        app_request = 50_000
        app_first = 60_000
        app_last = 510_000
        reset_offset = 0

    ttfb = app_first - tcp_start
    ttlb = app_last - tcp_start
    req_tfb = app_first - app_request
    req_tlb = app_last - app_request
    application_transfer = app_last - app_first
    rtfb = reset_offset + app_first if reset_origin else 0
    rtlb = reset_offset + app_last if reset_origin else 0

    messages: list[dict] = [
        {"type": "connect_timing", "milliseconds": 3200 if tls else 40, "tls_mode": "classical_tls_server_auth" if tls else "plaintext"},
        {"type": "memory_metrics", "sequence": 1, "stack_high_water_words": 900, "heap_free_bytes": 8000, "heap_min_ever_bytes": 7000},
        {"type": "memory_metrics", "sequence": 2, "stack_high_water_words": 890, "heap_free_bytes": 7900, "heap_min_ever_bytes": 6900},
        {
            "type": "application_timebase", "schema_version": 3, "source": "TIM2",
            "timer_input_clock_hz": 120000000, "prescaler": 119,
            "counter_hz": 1000000, "counter_bits": 32,
            "wrap_handling": "update_irq_64bit_extension",
            "reset_origin": "operational_wolfboot_entry",
            "reset_origin_valid": 1 if reset_origin else 0,
            "reset_origin_kind": 1 if reset_origin else 0,
            "reset_origin_to_application_timebase_us": reset_offset,
            "handoff_bridge": "LPTIM2_HSI16_DIV16",
            "firmware_elf_sha256_source": "run_manifest",
        },
        {
            "type": "experiment_timing", "schema_version": 3,
            "mqtt_readiness_definition": "tcp_connect_start_to_first_mqtt_connack_plaintext_byte",
            "dns_included": False, "tcp_connect_us": 20000 if tls else 6000,
            "mqtt_readiness_us": mqtt_ready_checkpoint - tcp_start,
            "mqtt_connect_us": 3030000 if tls else 35000,
            "legacy_connect_timing_us": 3200000 if tls else 40000,
            "tcp_connect_ms_legacy": 20 if tls else 6,
            "mqtt_readiness_ms_legacy": (mqtt_ready_checkpoint - tcp_start) // 1000,
            "mqtt_connect_ms_legacy": 3030 if tls else 35,
            "legacy_connect_timing_ms": 3200 if tls else 40,
            "tls_timing_valid": 1 if tls else 0, "mqtt_readiness_valid": 1,
        },
    ]
    if reset_origin:
        boot = {
            "reset_to_tcp_connect_us": reset_offset + tcp_start,
            "reset_to_tls_complete_us": 4_000_000 if tls else 0,
            "reset_to_mqtt_readiness_us": reset_offset + mqtt_ready_checkpoint,
            "reset_to_mqtt_connected_us": 4_130_000 if tls else reset_offset + mqtt_ready_checkpoint,
            "rtfb_us": rtfb,
            "rtlb_us": rtlb,
            "reset_to_ready_publish_us": rtlb + 10_000,
        }
    else:
        boot = {key: 0 for key in (
            "reset_to_tcp_connect_us", "reset_to_tls_complete_us",
            "reset_to_mqtt_readiness_us", "reset_to_mqtt_connected_us",
            "rtfb_us", "rtlb_us", "reset_to_ready_publish_us",
        )}
    messages.append({"type": "boot_timing", "schema_version": 3, "reset_origin": "operational_wolfboot_entry", "reset_origin_valid": 1 if reset_origin else 0, **boot})
    messages.extend([
        {
            "type": "tls_handshake_timing", "schema_version": 2,
            "available": 1 if tls else 0, "result": 1 if tls else 0,
            "cycle_counter_available": 1 if tls else 0,
            "elapsed_cycles": 100 if tls else 0, "elapsed_us": 3000000 if tls else 0,
            "elapsed_ms_legacy": 3000 if tls else 0,
            "timing_sources": "dwt_cycles+application_timebase_us",
            "stack_before_min_free_bytes": 1000 if tls else 0,
            "stack_after_min_free_bytes": 900 if tls else 0,
            "heap_before_free_bytes": 8000 if tls else 0,
            "heap_after_free_bytes": 7000 if tls else 0,
            "heap_before_min_ever_free_bytes": 7500 if tls else 0,
            "heap_after_min_ever_free_bytes": 6900 if tls else 0,
        },
        {"type": "tls_phase_timing", "schema_version": 2,
         "record_layout": "count,total_cycles,min_cycles,max_cycles,first_start_cycle,last_end_cycle,first_start_us,last_end_us",
         "values": [phase] * 5},
    ])
    for part, first_index, last_index in primitive_ranges:
        messages.append({
            "type": "tls_primitive_timing", "schema_version": 2,
            "timing_source": "dwt_cycles", "part": part,
            "first_index": first_index, "last_index": last_index,
            "values": [[0, 0, 0, 0, 0, 0] for _ in range(last_index - first_index + 1)],
        })
    messages.extend([
        {"type": "tls_x509_verify_timing", "schema_version": 2,
         "timing_source": "dwt_cycles", "count": 2 if tls else 0,
         "overflow": 0, "elapsed_cycles": [1, 2, 0, 0] if tls else [0, 0, 0, 0]},
        {
            "type": "application_timing_checkpoints", "schema_version": 3,
            "reset_origin": "operational_wolfboot_entry",
            "reset_origin_valid": 1 if reset_origin else 0,
            "reset_origin_to_application_timebase_us": reset_offset,
            "tcp_connect_start_us": tcp_start,
            "mqtt_readiness_checkpoint_us": mqtt_ready_checkpoint,
            "application_request_us": app_request,
            "application_first_byte_us": app_first,
            "application_last_byte_us": app_last,
        },
        {
            "type": "application_transfer_timing", "schema_version": 3,
            "metric_contract": "ready_metrics_2_canonical_v3",
            "payload_bytes": 204800, "received_bytes": 204800, "chunk_bytes": 400,
            "rtfb_us": rtfb, "rtlb_us": rtlb,
            "ttfb_us": ttfb, "ttlb_us": ttlb,
            "req_tfb_us": req_tfb, "req_tlb_us": req_tlb,
            "application_transfer_us": application_transfer,
            "reset_metrics_valid": 1 if reset_origin else 0,
            "complete_valid": 1,
        },
        {"type": "ready_metrics_2_complete", "schema_version": 3, "status": "success", "message_count": 19},
    ])
    return ["ready", *(json.dumps(message, separators=(",", ":")) for message in messages)]


def test_ready_metrics_2_subscriber_contract_accepts_complete_result_bundle():
    cli = _load_experiment_cli()
    topic = "pqc/test/response"
    output = "\n".join(f"{topic} {message}" for message in _rm2_bundle(tls=True, reset_origin=True)) + "\n"

    evidence = cli._parse_ready_metrics_2_subscriber_output(output, response_topic=topic)

    assert evidence["passed"] is True
    assert evidence["message_count"] == 19
    assert evidence["timebase_valid"] is True
    assert evidence["timing_valid"] is True
    assert evidence["boot_timing_valid"] is True
    assert evidence["primitive_parts"] == [1, 2, 3, 4, 5, 6]
    assert evidence["complete_valid"] is True
    assert evidence["experiment_timing"]["mqtt_readiness_us"] == 3020000
    assert evidence["checkpoints_valid"] is True
    assert evidence["application_transfer_timing"]["ttfb_us"] == 3300000
    assert evidence["application_transfer_timing"]["ttlb_us"] == 5000000
    assert evidence["application_transfer_timing"]["req_tfb_us"] == 200000
    assert evidence["application_transfer_timing"]["req_tlb_us"] == 1900000
    assert evidence["application_transfer_timing"]["rtfb_us"] == 4400000
    assert evidence["application_transfer_timing"]["rtlb_us"] == 6100000


def test_ready_metrics_2_subscriber_contract_rejects_wrong_first_response_definition():
    cli = _load_experiment_cli()
    topic = "pqc/test/response"
    messages = _rm2_bundle(tls=True, reset_origin=True)
    decoded = json.loads(messages[5])
    decoded["mqtt_readiness_definition"] = "before_dns_to_connack"
    decoded["dns_included"] = True
    messages[5] = json.dumps(decoded, separators=(",", ":"))
    output = "\n".join(f"{topic} {message}" for message in messages) + "\n"
    evidence = cli._parse_ready_metrics_2_subscriber_output(output, response_topic=topic)
    assert evidence["passed"] is False
    assert evidence["timing_valid"] is False



def test_ready_metrics_2_subscriber_contract_rejects_ambiguous_legacy_metric_names():
    cli = _load_experiment_cli()
    topic = "pqc/test/response"
    messages = _rm2_bundle(tls=True, reset_origin=True)
    transfer_index = next(
        index for index, item in enumerate(messages)
        if item != "ready" and json.loads(item).get("type") == "application_transfer_timing"
    )
    decoded = json.loads(messages[transfer_index])
    decoded["application_ttfb_us"] = decoded.pop("ttfb_us")
    messages[transfer_index] = json.dumps(decoded, separators=(",", ":"))
    output = "\n".join(f"{topic} {message}" for message in messages) + "\n"
    evidence = cli._parse_ready_metrics_2_subscriber_output(output, response_topic=topic)
    assert evidence["passed"] is False
    assert evidence["transfer_valid"] is False

def test_ready_metrics_2_subscriber_contract_accepts_plaintext_without_reset_origin():
    cli = _load_experiment_cli()
    topic = "pqc/test/plaintext/response"
    output = "\n".join(
        f"{topic} {message}" for message in _rm2_bundle(tls=False, reset_origin=False)
    ) + "\n"

    evidence = cli._parse_ready_metrics_2_subscriber_output(output, response_topic=topic)

    assert evidence["passed"] is True
    assert evidence["timebase_valid"] is True
    assert evidence["boot_timing_valid"] is True
    assert evidence["experiment_timing"]["tls_timing_valid"] == 0
    assert evidence["boot_timing"]["reset_origin_valid"] == 0
    assert evidence["application_transfer_timing"]["received_bytes"] == 204800

