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
    assert 'vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(5000U))' in source
    assert 'uxTaskGetStackHighWaterMark(NULL)' in source
    assert 'xPortGetFreeHeapSize()' in source
    assert 'xPortGetMinimumEverFreeHeapSize()' in source
    assert 'metrics_count == 5U' in source
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
        for sequence in range(1, 6)
    )

    evidence = cli._parse_ready_metrics_subscriber_output(
        "\n".join(lines) + "\n", response_topic=topic
    )

    assert evidence["passed"] is True
    assert evidence["message_count"] == 7
    assert evidence["ready_count"] == 1
    assert evidence["timing_count"] == 1
    assert evidence["metrics_count"] == 5
    assert evidence["metric_sequences"] == [1, 2, 3, 4, 5]


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
                for sequence in range(1, 5)
            ],
        ]
    )

    evidence = cli._parse_ready_metrics_subscriber_output(
        output + "\n", response_topic=topic
    )

    assert evidence["passed"] is False
    assert evidence["metrics_count"] == 4
    assert evidence["metrics_valid"] is False


def test_ready_metrics_host_validator_is_device_initiated():
    cli_source = Path("scripts/experiment.py").read_text(encoding="utf-8")

    assert 'expected_response_count = 7 if ready_metrics_application' in cli_source
    assert 'Publisher disabled: mqtt_ready_metrics is device-initiated.' in cli_source
    assert 'Starting MQTT ready/timing/metrics validation' in cli_source
    assert 'ready_connect_timing_five_memory_metrics' in cli_source
    assert 'PQC_APP_METRICS sequence=5' in cli_source
