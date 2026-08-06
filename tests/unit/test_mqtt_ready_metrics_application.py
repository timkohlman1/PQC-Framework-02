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
