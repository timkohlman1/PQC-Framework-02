"""Source-level contracts for the persistent passive ESP32/INA228 appliance."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "instruments/esp32_ina228/main/energy_session.cpp"
HEADER = ROOT / "instruments/esp32_ina228/main/energy_session.h"
KCONFIG = ROOT / "instruments/esp32_ina228/main/Kconfig.projbuild"


def _session() -> str:
    return SESSION.read_text(encoding="utf-8")


def test_appliance_is_gpio_triggered_publish_only_and_has_no_mqtt_command_plane():
    session = _session()
    assert 'kChunkTopic[] = "pqc/instrument/energy/capture/chunk"' in session
    assert 'kCompleteTopic[] = "pqc/instrument/energy/capture/complete"' in session
    assert "GPIO_INTR_ANYEDGE" in session
    assert "esp_mqtt_client_publish" in session
    assert "esp_mqtt_client_subscribe" not in session
    assert "MQTT_EVENT_DATA" not in session
    assert "pqc/control/instrument/energy" not in session
    assert "association_token" not in session
    assert "run_id" not in session
    assert "measurement_name" not in session
    assert "cJSON" not in session


def test_ring_record_is_packed_20_byte_timestamp_voltage_current_power_only():
    session = _session()
    record = session.split("#pragma pack(push, 1)", 1)[1].split("#pragma pack(pop)", 1)[0]
    assert "int64_t timestamp_us;" in record
    assert "float bus_v;" in record
    assert "float current_a;" in record
    assert "float power_w;" in record
    for retired in (
        "sequence", "read_duration", "status_flags", "diagnostic_flags",
        "i2c_errors", "alert_timeouts", "sample_gaps",
    ):
        assert retired not in record
    assert 'static_assert(sizeof(energy_sample_record_t) == 20' in session
    assert "MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT" in session
    assert "CONFIG_PQC_ENERGY_RING_MAX_BYTES" in session


def test_capture_retains_pretrigger_then_pauses_only_after_falling_edge():
    session = _session()
    kconfig = KCONFIG.read_text(encoding="utf-8")
    assert "config PQC_ENERGY_PRETRIGGER_MS" in kconfig
    assert "default 1000" in kconfig.split("config PQC_ENERGY_PRETRIGGER_MS", 1)[1].split("config", 1)[0]
    assert "job->e0_us - kPretriggerUs" in session
    assert "pretrigger_complete" in session
    falling = session.split("void processFalling", 1)[1].split("void syncWorker", 1)[0]
    assert "job.e1_us = timestampUs;" in falling
    assert "pqc_ina228_sparkfun_pause(kAcquisitionPauseTimeoutMs)" in falling
    assert falling.index("job.e1_us = timestampUs;") < falling.index("pqc_ina228_sparkfun_pause")
    assert falling.index("pqc_ina228_sparkfun_pause") < falling.index("prepareCaptureRange(&job)")
    assert "xQueueSend(captureQueue" in falling
    assert "ringTotalWrites" not in session
    assert "overwrite_at_write_count" not in session


def test_publication_uses_immutable_ring_then_resets_and_resumes_sampling():
    session = _session()
    publisher = session.split("void publisherTask", 1)[1].split("void processRising", 1)[0]
    helper = session.split("void resumeAfterPublication", 1)[1].split("void recordAbortedCapture", 1)[0]
    assert "const bool ok = publishCapture(job);" in publisher
    assert "resumeAfterPublication();" in publisher
    assert "resetFrozenRing();" in helper
    assert "pqc_ina228_sparkfun_resume();" in helper
    assert "ringCount = 0;" in session
    assert "ringWriteIndex = 0;" in session


def test_unexpected_rising_edge_cancels_old_publication_and_invalidates_new_window():
    session = _session()
    rising = session.split("void processRising", 1)[1].split("void processFalling", 1)[0]
    assert "state.publishing" in rising
    assert "captureGeneration++;" in rising
    assert "state.aborted_captures++" in rising
    assert "invalidating this window" in rising
    assert "pqc_ina228_sparkfun_resume" not in rising
    assert "publicationCurrent(job.generation" in session


def test_publication_is_qos1_ack_paced_and_completion_carries_integrity_metadata():
    session = _session()
    assert "waitForPublishAck" in session
    assert "MQTT_EVENT_PUBLISHED" in session
    assert "event->msg_id" in session
    assert "esp_mqtt_client_publish(mqttClient, topic, payload, 0, 1, 0)" in session
    assert "mbedtls_sha256" in session
    assert 'logical_sha256' in session
    assert 'logical_bytes' in session
    assert 'chunk_count' in session
    assert 'firmware_sha256' in session
    assert "app->app_elf_sha256[i]" in session


def test_acquisition_fault_counters_are_capture_metadata_not_per_sample():
    session = _session()
    record = session.split("#pragma pack(push, 1)", 1)[1].split("#pragma pack(pop)", 1)[0]
    completion = session.split('char completion[2048]', 1)[1].split('publishQos1(kCompleteTopic', 1)[0]
    for field in (
        "i2c_errors", "alert_timeouts", "coalesced_alerts", "timing_errors",
        "saturation_errors", "sample_gaps", "sync_queue_drops",
    ):
        assert field not in record
        assert field in completion


def test_gpio_and_alert_defaults_remain_11_and_12():
    session = _session()
    kconfig = KCONFIG.read_text(encoding="utf-8")
    assert "config PQC_ENERGY_SYNC_GPIO" in kconfig
    assert "default 11" in kconfig.split("config PQC_ENERGY_SYNC_GPIO", 1)[1].split("config", 1)[0]
    assert "config PQC_INA228_ALERT_GPIO" in kconfig
    assert "default 12" in kconfig.split("config PQC_INA228_ALERT_GPIO", 1)[1].split("config", 1)[0]
    assert "CONFIG_PQC_ENERGY_SYNC_GPIO" in session
    assert "CONFIG_PQC_INA228_ALERT_GPIO" in session


def test_ina228_acquisition_remains_alert_triggered_and_calibrated():
    ina = (ROOT / "instruments/esp32_ina228/main/ina228_sparkfun.cpp").read_text(encoding="utf-8")
    assert "setConversionReadyAlert(true)" in ina
    assert "setAlertPolarity(false)" in ina
    assert "setAlertLatch(false)" in ina
    assert "INA2XX_CONV_50US" in ina
    assert "INA2XX_MODE_TRIG_BUS_SHUNT" in ina
    assert "GPIO_INTR_NEGEDGE" in ina
    assert "sensor.isConversionReady" in ina
    assert "0.029" in ina


def test_startup_mqtt_failure_does_not_abort_idle_sensor_acquisition():
    session = _session()
    start = session.split('extern "C" void pqc_energy_session_start', 1)[1]
    assert "const esp_err_t rc = esp_mqtt_client_start(mqttClient);" in start
    assert "ESP_ERROR_CHECK(esp_mqtt_client_start(mqttClient))" not in start
    assert "acquisition remains active" in start


def test_ui_exposes_capture_state_without_experiment_semantics():
    main = (ROOT / "instruments/esp32_ina228/main/main.c").read_text(encoding="utf-8")
    header = HEADER.read_text(encoding="utf-8")
    assert '"GPIO CAPTURE"' in main
    assert '"Capture: %s"' in main
    assert "completed_capture_count" in header
    assert "aborted_capture_count" in header
    assert "run_id" not in header
    assert "association" not in header
