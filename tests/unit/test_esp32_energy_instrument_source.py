"""Device-only source checks extracted from commit 7a25e8fc507f23a5346dfa6014087be05fab81bd.

Framework profile and STM32 source assertions are intentionally excluded.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_esp32_source_has_live_chart_continuous_psram_ring_and_collect_service():
    main = (ROOT / "instruments/esp32_ina228/main/main.c").read_text(encoding="utf-8")
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")
    cmake = (ROOT / "instruments/esp32_ina228/main/CMakeLists.txt").read_text(encoding="utf-8")

    assert "lv_chart_create" in main
    assert "lv_chart_set_next_value" in main
    assert "pqc_energy_session_start();" in main
    assert "MALLOC_CAP_SPIRAM" in session
    assert "kRingBytesTarget = CONFIG_PQC_ENERGY_RING_MAX_BYTES" in session
    assert "pqc/control/instrument/energy/collect" in session
    assert "pqc/instrument/energy/%s/complete" in session
    assert "recordSyncEdge" in session
    assert "mbedtls_sha256" in session
    assert '"energy_session.cpp"' in cmake
    assert " mqtt " in cmake.replace("\n", " ")


def test_esp32_acquisition_does_not_depend_on_mqtt_connectivity():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")
    assert "pqc_ina228_sparkfun_set_sample_callback(storeSensorSample);" in session
    assert "continuous acquisition continues" in session
    assert "arm" not in session.lower().split("kCollectTopic", 1)[0]
    assert "publishClaimedIntervals" in session


def test_esp32_mqtt_callback_defers_heavy_collection_work_to_worker_task():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")
    kconfig = (ROOT / "instruments/esp32_ina228/main/Kconfig.projbuild").read_text(encoding="utf-8")

    assert 'xTaskCreate(' in session
    assert '"energy_mqtt_worker"' in session
    assert 'xQueueCreate' in session
    assert 'WorkerCommandType::Collect' in session
    assert 'config.task.stack_size = CONFIG_PQC_ENERGY_MQTT_STACK_BYTES;' in session
    assert 'CONFIG_PQC_ENERGY_WORKER_STACK_BYTES' in session
    assert 'config PQC_ENERGY_MQTT_STACK_BYTES' in kconfig
    assert 'default 8192' in kconfig
    assert 'config PQC_ENERGY_WORKER_STACK_BYTES' in kconfig
    assert 'default 12288' in kconfig

    handler = session.split('void mqttEventHandler', 1)[1].split('} // namespace', 1)[0]
    assert 'handleCollect(event->data' not in handler
    assert 'publishClaimedIntervals(' not in handler
    assert 'publishStatus("ready"' not in handler
    assert 'enqueueWorkerCommand' in handler


def test_energy_gpio_and_ina228_alert_defaults_are_wired_into_sources():
    root = ROOT
    session = (root / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")
    ina = (root / "instruments/esp32_ina228/main/ina228_sparkfun.cpp").read_text(encoding="utf-8")
    kconfig = (root / "instruments/esp32_ina228/main/Kconfig.projbuild").read_text(encoding="utf-8")

    assert "config PQC_ENERGY_SYNC_GPIO" in kconfig
    assert 'default 11' in kconfig.split("config PQC_ENERGY_SYNC_GPIO", 1)[1].split("config", 1)[0]
    assert "config PQC_INA228_ALERT_GPIO" in kconfig
    assert 'default 12' in kconfig.split("config PQC_INA228_ALERT_GPIO", 1)[1].split("config", 1)[0]

    assert "GPIO_INTR_ANYEDGE" in session
    assert "STM32 energy sync input ready: GPIO%d both-edge capture" in session
    assert "recordSyncEdge" in session

    assert "setConversionReadyAlert(true)" in ina
    assert "setAlertPolarity(false)" in ina
    assert "setAlertLatch(false)" in ina
    assert "INA2XX_CONV_50US" in ina
    assert "INA2XX_MODE_TRIG_BUS_SHUNT" in ina
    assert "GPIO_INTR_NEGEDGE" in ina
    assert "sensor.isConversionReady" in ina
    assert "ulTaskNotifyTake" in ina
    assert "vTaskNotifyGiveFromISR" in ina
    assert "INA2XX_MODE_SHUTDOWN" in ina
    assert "gpio_intr_disable(kAlertGpio)" in ina
    assert "gpio_intr_enable(kAlertGpio)" in ina
    assert "counters.alert_timeouts++" in ina
    assert "coalesced_alerts" in ina
    assert "alertQueue" not in ina
    assert "xQueueSendFromISR(alertQueue" not in ina




def test_ina228_owns_gpio_isr_service_and_sync_handler_reuses_it():
    ina = (ROOT / "instruments/esp32_ina228/main/ina228_sparkfun.cpp").read_text(encoding="utf-8")
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    assert ina.count("gpio_install_isr_service(0)") == 1
    assert "gpio_install_isr_service(0)" not in session
    assert "gpio_isr_handler_add(kSyncGpio, syncGpioIsr" in session
    assert "gpio_isr_handler_add(kAlertGpio, alertGpioIsr" in ina



def test_energy_trace_publication_is_qos1_ack_paced_and_uses_larger_bounded_chunks():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    assert "constexpr size_t kChunkBytes = 4096;" in session
    assert "kPublishAckQueueLength" in session
    assert "waitForPublishAck" in session
    assert "MQTT_EVENT_PUBLISHED" in session
    assert "event->msg_id" in session
    assert "xQueueSend(publishAckQueue" in session
    assert "xQueueReceive(publishAckQueue" in session
    assert "Timed out waiting for MQTT PUBACK" in session
    assert "Energy chunk publication failed" in session
    assert "Energy completion publication failed" in session


def test_energy_publication_allows_only_one_trace_message_outstanding():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")
    publish_chunk = session.split("bool publishChunk()", 1)[1].split("bool append(", 1)[0]

    publish_pos = publish_chunk.index("esp_mqtt_client_publish")
    ack_pos = publish_chunk.index("waitForPublishAck(messageId)")
    sequence_pos = publish_chunk.index("chunkSequence++;")
    assert publish_pos < ack_pos < sequence_pos



def test_energy_collect_retires_only_overwritten_unclaimed_intervals_before_fifo_selection():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    assert "bool discarded;" in session
    assert "discardedOverwrittenIntervals" in session
    assert "Retiring overwritten unclaimed energy interval" in session
    assert "candidate.discarded = true;" in session
    assert "!candidate.claimed && !candidate.discarded" in session
    assert "sampleRing[oldest].timestamp_us > candidate.start_timestamp_us" in session
    assert "resolveIntervalSamples(claimed[i])" in session
    assert "capacity_exceeded" in session

    publish = session.split("bool publishClaimedIntervals", 1)[1].split("void handleCollect", 1)[0]
    retire_pos = publish.index("Retiring overwritten unclaimed energy interval")
    exact_association_pos = publish.index(
        "Primary association is the exact per-collector token"
    )
    assert retire_pos < exact_association_pos


def test_energy_trace_clears_stale_status_pubacks_before_each_qos1_trace_publish():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    assert "void clearPublishAckBacklog()" in session
    assert "xQueueReset(publishAckQueue)" in session

    publisher = session.split("struct TracePublisher", 1)[1].split(
        "bool publishClaimedIntervals", 1
    )[0]
    assert publisher.count("clearPublishAckBacklog();") >= 2
    assert publisher.count("waitForPublishAck(messageId)") >= 2



def test_energy_ring_storage_cannot_silently_drop_samples_on_mutex_contention():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    store = session.split("void storeSensorSample", 1)[1].split("void publishStatus", 1)[0]
    assert "xSemaphoreTake(stateMutex, portMAX_DELAY)" in store
    assert "oldestSequence = sampleRing[ringWriteIndex].sequence;" in store
    assert "newestSequence - ringCapacity + 1u" not in store


def test_energy_ring_lookup_does_not_assume_dense_sample_sequences():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    lookup = session.split("bool copySampleBySequence", 1)[1].split("void storeSensorSample", 1)[0]
    assert "const uint32_t oldestIndex" in lookup
    assert "uint32_t lo = 0;" in lookup
    assert "uint32_t hi = ringCount;" in lookup
    assert "candidate < seq" in lookup
    assert "const uint64_t offset = seq - oldestSequence;" not in lookup


def test_energy_trace_large_chunk_is_heap_backed_not_worker_stack_backed():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    publisher = session.split("struct TracePublisher", 1)[1].split(
        "bool publishClaimedIntervals", 1
    )[0]
    assert "char *chunk = nullptr;" in publisher
    assert "heap_caps_malloc(kChunkBytes, MALLOC_CAP_8BIT)" in publisher
    assert "heap_caps_free(chunk)" in publisher
    assert "char chunk[kChunkBytes]" not in publisher


def test_failed_energy_collect_emits_run_scoped_remote_diagnostic_without_puback_dependency():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    assert "void publishRunFailure" in session
    assert '"pqc/instrument/energy/%s/complete"' in session
    assert '"sample_unavailable"' in session
    assert '"publication_failed"' in session

    diagnostic = session.split("void publishRunFailure", 1)[1].split(
        "void clearPublishAckBacklog", 1
    )[0]
    assert "esp_mqtt_client_publish" in diagnostic
    assert "payload, 0, 1, 0" in diagnostic


def test_energy_worker_logs_stack_high_water_around_collect():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")
    assert "Energy collect worker start: stack_high_water=%u bytes" in session
    assert "Energy collect worker done: stack_high_water=%u bytes" in session
    assert "uxTaskGetStackHighWaterMark(nullptr)" in session



def test_energy_sync_edges_are_lossless_after_isr_queue_and_queue_loss_is_observable():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")
    header = (ROOT / "instruments/esp32_ina228/main/energy_session.h").read_text(encoding="utf-8")

    record = session.split("void recordSyncEdge", 1)[1].split("void syncEdgeWorker", 1)[0]
    isr = session.split("void IRAM_ATTR syncGpioIsr", 1)[1].split("void configureSyncGpio", 1)[0]
    assert "xSemaphoreTake(stateMutex, portMAX_DELAY)" in record
    assert "xQueueSendFromISR" in isr
    assert "syncQueueDrops += 1U" in isr
    assert "syncIsrEdges += 1U" in isr
    assert "sync_queue_drops" in header
    assert "sync_isr_edges" in header


def test_energy_intervals_snapshot_unique_collector_association_token():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")
    assert 'kAssociateTopic[] = "pqc/control/instrument/energy/associate"' in session
    assert "esp_mqtt_client_subscribe(mqttClient, kAssociateTopic, 1)" in session
    assert "recordAssociationToken" in session
    assert "openInterval.association_token" in session
    assert "openInterval.association_valid = true;" in session
    assert "associationTokenValid = false;" in session


def test_energy_collect_requires_exact_token_without_unlabeled_fallback():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text()
    assert "strcmp(candidate.association_token, associationTokenRequested) == 0" in session
    assert "unique_unlabeled_fallback" not in session
    assert '"sync_edge_loss"' in session


def test_energy_collect_requires_framework_association_token():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")
    collect = session.split("void handleCollect", 1)[1].split("enum class WorkerCommandType", 1)[0]
    assert '"association_token"' in collect
    assert "validAssociationToken" in collect
    assert '"association_missing_or_invalid"' in collect


def test_energy_interval_evidence_records_association_method():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text()
    assert "collector_token" in session
    assert "stm32.energy_boundary" in session
    assert "delta_energy_j" not in session
    assert "cumulative_energy_j" not in session


def test_energy_interval_descriptors_live_in_psram_not_static_internal_dram():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    assert "energy_interval_record_t *intervals = nullptr;" in session
    assert "energy_interval_record_t intervals[kMaxIntervals]" not in session
    assert "heap_caps_calloc(kMaxIntervals, sizeof(energy_interval_record_t)" in session
    assert "MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT" in session
    assert "Energy interval descriptors allocated in PSRAM" in session


def test_energy_mqtt_start_failure_does_not_abort_persistent_acquisition_appliance():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    start = session.split('extern "C" void pqc_energy_session_start', 1)[1]
    assert "const esp_err_t mqttStartRc = esp_mqtt_client_start(mqttClient);" in start
    assert "ESP_ERROR_CHECK(esp_mqtt_client_start(mqttClient))" not in start
    assert "continuous INA228 acquisition remains active" in start


def test_energy_collect_reports_interval_storage_allocation_failure_explicitly():
    session = (ROOT / "instruments/esp32_ina228/main/energy_session.cpp").read_text(encoding="utf-8")

    publish = session.split("bool publishClaimedIntervals", 1)[1].split("void handleCollect", 1)[0]
    assert 'publishStatus("interval_storage_unavailable", runId)' in publish
    assert 'publishRunFailure(runId, "interval_storage_unavailable", 0)' in publish
