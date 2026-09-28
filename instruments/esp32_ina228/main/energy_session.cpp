/* Lightweight persistent ESP32 energy recorder.
 *
 * The appliance has no experiment command plane. INA228 acquisition starts at
 * boot and fills a PSRAM ring with packed timestamp/voltage/current/power
 * samples. STM32 PF12 -> ESP32 GPIO11 is the only experiment control signal:
 * rising opens one capture window and falling closes it. After the falling edge
 * the acquisition task is paused, the immutable pre-trigger + measured records
 * are published to fixed MQTT topics, then the ring is reset and acquisition
 * resumes to build the next pre-trigger history.
 */
#include "energy_session.h"

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>

#include "driver/gpio.h"
#include "esp_app_desc.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "mbedtls/base64.h"
#include "mbedtls/sha256.h"
#include "mqtt_client.h"
#include "sdkconfig.h"

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#include "ina228_sparkfun.h"

#ifndef CONFIG_PQC_ENERGY_RING_MAX_BYTES
#define CONFIG_PQC_ENERGY_RING_MAX_BYTES (7 * 1024 * 1024)
#endif
#ifndef CONFIG_PQC_ENERGY_PSRAM_RESERVE_BYTES
#define CONFIG_PQC_ENERGY_PSRAM_RESERVE_BYTES (512 * 1024)
#endif
#ifndef CONFIG_PQC_ENERGY_PRETRIGGER_MS
#define CONFIG_PQC_ENERGY_PRETRIGGER_MS 3000
#endif
#ifndef CONFIG_PQC_ENERGY_REPORTING_HOST
#define CONFIG_PQC_ENERGY_REPORTING_HOST "pqc-gateway1.pqcnet"
#endif
#ifndef CONFIG_PQC_ENERGY_REPORTING_PORT
#define CONFIG_PQC_ENERGY_REPORTING_PORT 1886
#endif
#ifndef CONFIG_PQC_ENERGY_MQTT_CLIENT_ID
#define CONFIG_PQC_ENERGY_MQTT_CLIENT_ID "pqc-energy-esp32-ina228"
#endif
#ifndef CONFIG_PQC_ENERGY_MQTT_STACK_BYTES
#define CONFIG_PQC_ENERGY_MQTT_STACK_BYTES 8192
#endif
#ifndef CONFIG_PQC_ENERGY_PUBLISHER_STACK_BYTES
#define CONFIG_PQC_ENERGY_PUBLISHER_STACK_BYTES 12288
#endif
#ifndef CONFIG_PQC_ENERGY_SYNC_GPIO
#define CONFIG_PQC_ENERGY_SYNC_GPIO 11
#endif
#ifndef CONFIG_PQC_INA228_ALERT_GPIO
#define CONFIG_PQC_INA228_ALERT_GPIO 12
#endif

namespace {

constexpr char kChunkTopic[] = "pqc/instrument/energy/capture/chunk";
constexpr char kCompleteTopic[] = "pqc/instrument/energy/capture/complete";
constexpr size_t kRingBytesTarget = CONFIG_PQC_ENERGY_RING_MAX_BYTES;
constexpr size_t kPsramReserveBytes = CONFIG_PQC_ENERGY_PSRAM_RESERVE_BYTES;
constexpr int64_t kPretriggerUs = static_cast<int64_t>(CONFIG_PQC_ENERGY_PRETRIGGER_MS) * 1000LL;
constexpr size_t kChunkBytes = 4000;
constexpr UBaseType_t kSyncQueueLength = 8;
constexpr UBaseType_t kCaptureQueueLength = 2;
constexpr UBaseType_t kPublishAckQueueLength = 8;
constexpr TickType_t kPublishAckTimeout = pdMS_TO_TICKS(5000);
constexpr uint32_t kAcquisitionPauseTimeoutMs = 2000;
constexpr uint32_t kPublicationTimeoutMs = 180000;
constexpr gpio_num_t kSyncGpio = static_cast<gpio_num_t>(CONFIG_PQC_ENERGY_SYNC_GPIO);
constexpr gpio_num_t kAlertGpio = static_cast<gpio_num_t>(CONFIG_PQC_INA228_ALERT_GPIO);
const char *TAG = "pqc_energy_session";

#pragma pack(push, 1)
typedef struct {
    int64_t timestamp_us;
    float bus_v;
    float current_a;
    float power_w;
} energy_sample_record_t;
#pragma pack(pop)
static_assert(sizeof(energy_sample_record_t) == 20, "energy sample wire record must remain 20 bytes");

struct AcquisitionCounters {
    uint32_t i2c_errors;
    uint32_t alert_timeouts;
    uint32_t coalesced_alerts;
    uint32_t timing_errors;
    uint32_t saturation_errors;
    uint32_t sample_gaps;
};

AcquisitionCounters countersFrom(const pqc_ina228_snapshot_t &s)
{
    return {s.i2c_errors, s.alert_timeouts, s.coalesced_alerts,
            s.timing_errors, s.saturation_errors, s.sample_gaps};
}

uint32_t deltaCounter(uint32_t end, uint32_t start)
{
    return end - start;
}

struct CaptureJob {
    char capture_id[17];
    uint64_t generation;
    int64_t e0_us;
    int64_t e1_us;
    uint32_t start_index;
    uint32_t sample_count;
    int64_t first_timestamp_us;
    int64_t last_timestamp_us;
    bool pretrigger_complete;
    AcquisitionCounters counters_start;
    AcquisitionCounters counters_end;
    uint32_t sync_queue_drops_start;
    uint32_t sync_queue_drops_end;
};

struct SyncEdgeEvent {
    bool rising;
    int64_t timestamp_us;
};

struct SessionState {
    bool mqtt_connected = false;
    bool publishing = false;
    bool last_publish_ok = false;
    bool capture_active = false;
    char active_capture_id[17] = {};
    uint32_t completed_captures = 0;
    uint32_t aborted_captures = 0;
};

SemaphoreHandle_t stateMutex = nullptr;
esp_mqtt_client_handle_t mqttClient = nullptr;
QueueHandle_t publishAckQueue = nullptr;
QueueHandle_t syncQueue = nullptr;
QueueHandle_t captureQueue = nullptr;
TaskHandle_t syncTaskHandle = nullptr;
TaskHandle_t publisherTaskHandle = nullptr;

energy_sample_record_t *sampleRing = nullptr;
uint32_t ringCapacity = 0;
uint32_t ringCount = 0;
uint32_t ringWriteIndex = 0;
bool ringOverflowed = false;
size_t psramTotalBytes = 0;

SessionState state;
uint64_t captureGeneration = 0;
int64_t activeE0Us = 0;
AcquisitionCounters activeCountersStart = {};
uint32_t activeSyncDropsStart = 0;
volatile bool physicalHigh = false;

portMUX_TYPE syncMux = portMUX_INITIALIZER_UNLOCKED;
volatile uint32_t syncIsrEdges = 0;
volatile uint32_t syncQueueDrops = 0;

void generateCaptureId(char out[17])
{
    const uint32_t hi = esp_random();
    const uint32_t lo = esp_random();
    snprintf(out, 17, "%08" PRIx32 "%08" PRIx32, hi, lo);
}

void storeSensorSample(const pqc_ina228_snapshot_t *sensor)
{
    if (sensor == nullptr || sampleRing == nullptr || ringCapacity == 0 || !sensor->online || !sensor->valid)
        return;
    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return;

    energy_sample_record_t &slot = sampleRing[ringWriteIndex];
    slot.timestamp_us = sensor->timestamp_us;
    slot.bus_v = static_cast<float>(sensor->bus_v);
    slot.current_a = static_cast<float>(sensor->current_a);
    slot.power_w = static_cast<float>(sensor->power_w);
    ringWriteIndex = (ringWriteIndex + 1u) % ringCapacity;
    if (ringCount < ringCapacity)
        ringCount++;
    else
        ringOverflowed = true;

    xSemaphoreGive(stateMutex);
}

uint32_t oldestRingIndex()
{
    return ringCapacity == 0 ? 0 : (ringWriteIndex + ringCapacity - ringCount) % ringCapacity;
}

const energy_sample_record_t &logicalSample(uint32_t logicalIndex)
{
    return sampleRing[(oldestRingIndex() + logicalIndex) % ringCapacity];
}

bool captureCurrent(uint64_t generation)
{
    if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(50)) != pdTRUE)
        return false;
    const bool current = captureGeneration == generation && !physicalHigh;
    xSemaphoreGive(stateMutex);
    return current;
}

bool publicationCurrent(uint64_t generation, TickType_t publicationStarted)
{
    return captureCurrent(generation) &&
           (xTaskGetTickCount() - publicationStarted) < pdMS_TO_TICKS(kPublicationTimeoutMs);
}

void resetFrozenRing()
{
    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return;
    ringCount = 0;
    ringWriteIndex = 0;
    ringOverflowed = false;
    xSemaphoreGive(stateMutex);
}

void resumeAfterPublication()
{
    resetFrozenRing();
    pqc_ina228_sparkfun_resume();
}

void recordAbortedCapture()
{
    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return;
    state.last_publish_ok = false;
    state.aborted_captures++;
    xSemaphoreGive(stateMutex);
}

void clearAckQueue()
{
    if (publishAckQueue != nullptr)
        (void)xQueueReset(publishAckQueue);
}

bool waitForPublishAck(int messageId, uint64_t generation, TickType_t publicationStarted)
{
    const TickType_t ackStarted = xTaskGetTickCount();
    while (xTaskGetTickCount() - ackStarted < kPublishAckTimeout) {
        if (!publicationCurrent(generation, publicationStarted))
            return false;
        int ack = -1;
        if (xQueueReceive(publishAckQueue, &ack, pdMS_TO_TICKS(100)) == pdTRUE && ack == messageId)
            return true;
    }
    return false;
}

bool waitForMqtt(uint64_t generation, TickType_t publicationStarted)
{
    for (;;) {
        if (!publicationCurrent(generation, publicationStarted))
            return false;
        bool connected = false;
        if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
            connected = state.mqtt_connected;
            xSemaphoreGive(stateMutex);
        }
        if (connected)
            return true;
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

bool publishQos1(const char *topic, const char *payload, uint64_t generation, TickType_t publicationStarted)
{
    while (publicationCurrent(generation, publicationStarted)) {
        if (!waitForMqtt(generation, publicationStarted))
            return false;
        clearAckQueue();
        const int messageId = esp_mqtt_client_publish(mqttClient, topic, payload, 0, 1, 0);
        if (messageId >= 0 && waitForPublishAck(messageId, generation, publicationStarted))
            return true;
        ESP_LOGW(TAG, "MQTT publish not acknowledged; retrying topic=%s", topic);
    }
    return false;
}

bool prepareCaptureRange(CaptureJob *job)
{
    if (job == nullptr || sampleRing == nullptr || ringCapacity == 0)
        return false;
    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return false;

    bool ok = ringCount >= 2;
    uint32_t start = 0;
    uint32_t end = 0;
    if (ok) {
        const uint32_t oldest = oldestRingIndex();
        const int64_t target = job->e0_us - kPretriggerUs;
        while (start < ringCount && logicalSample(start).timestamp_us < target)
            ++start;
        if (start > 0)
            --start; /* retain one sample immediately before the requested pre-trigger boundary */
        end = ringCount - 1u;
        while (end > start && logicalSample(end).timestamp_us > job->e1_us)
            --end;
        ok = logicalSample(start).timestamp_us <= job->e0_us &&
             logicalSample(end).timestamp_us <= job->e1_us &&
             logicalSample(end).timestamp_us >= job->e0_us;
        if (ok) {
            job->start_index = (oldest + start) % ringCapacity;
            job->sample_count = end - start + 1u;
            job->first_timestamp_us = logicalSample(start).timestamp_us;
            job->last_timestamp_us = logicalSample(end).timestamp_us;
            job->pretrigger_complete = logicalSample(start).timestamp_us <= target;
        }
    }
    xSemaphoreGive(stateMutex);
    return ok;
}

bool copyCaptureBytes(const CaptureJob &job, uint32_t sampleOffset, uint8_t *out, size_t bytes)
{
    if (out == nullptr || bytes == 0 || bytes % sizeof(energy_sample_record_t) != 0)
        return false;
    const uint32_t records = static_cast<uint32_t>(bytes / sizeof(energy_sample_record_t));
    if (sampleOffset > job.sample_count || records > job.sample_count - sampleOffset)
        return false;
    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return false;
    for (uint32_t i = 0; i < records; ++i) {
        const uint32_t index = (job.start_index + sampleOffset + i) % ringCapacity;
        const energy_sample_record_t &sample = sampleRing[index];
        memcpy(out + i * sizeof(sample), &sample, sizeof(sample));
    }
    xSemaphoreGive(stateMutex);
    return true;
}

bool publishCapture(const CaptureJob &job)
{
    const TickType_t publicationStarted = xTaskGetTickCount();
    if (job.sample_count == 0) {
        ESP_LOGE(TAG, "Capture has no usable sample range: id=%s", job.capture_id);
        return false;
    }

    const size_t logicalBytes = static_cast<size_t>(job.sample_count) * sizeof(energy_sample_record_t);
    const uint32_t recordsPerChunk = static_cast<uint32_t>(kChunkBytes / sizeof(energy_sample_record_t));
    const uint32_t chunkCount = (job.sample_count + recordsPerChunk - 1u) / recordsPerChunk;
    uint8_t *raw = static_cast<uint8_t *>(heap_caps_malloc(recordsPerChunk * sizeof(energy_sample_record_t), MALLOC_CAP_8BIT));
    const size_t encodedCapacity = 4 * ((recordsPerChunk * sizeof(energy_sample_record_t) + 2) / 3) + 1;
    unsigned char *encoded = static_cast<unsigned char *>(heap_caps_malloc(encodedCapacity, MALLOC_CAP_8BIT));
    char *payload = static_cast<char *>(heap_caps_malloc(encodedCapacity + 256, MALLOC_CAP_8BIT));
    if (raw == nullptr || encoded == nullptr || payload == nullptr) {
        if (raw) heap_caps_free(raw);
        if (encoded) heap_caps_free(encoded);
        if (payload) heap_caps_free(payload);
        return false;
    }

    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    bool ok = mbedtls_sha256_starts(&sha, 0) == 0;
    uint32_t offset = 0;
    for (uint32_t chunk = 0; ok && chunk < chunkCount; ++chunk) {
        if (!publicationCurrent(job.generation, publicationStarted)) {
            ok = false;
            break;
        }
        const uint32_t records = (job.sample_count - offset) < recordsPerChunk ? (job.sample_count - offset) : recordsPerChunk;
        const size_t rawBytes = static_cast<size_t>(records) * sizeof(energy_sample_record_t);
        ok = copyCaptureBytes(job, offset, raw, rawBytes);
        if (ok)
            ok = mbedtls_sha256_update(&sha, raw, rawBytes) == 0;
        size_t encodedLength = 0;
        if (ok)
            ok = mbedtls_base64_encode(encoded, encodedCapacity, &encodedLength, raw, rawBytes) == 0;
        if (ok) {
            encoded[encodedLength] = '\0';
            snprintf(payload, encodedCapacity + 256,
                     "{\"type\":\"chunk\",\"source\":\"energy\",\"schema\":1,"
                     "\"capture_id\":\"%s\",\"sequence\":%" PRIu32 ",\"data_b64\":\"%s\"}",
                     job.capture_id, chunk, reinterpret_cast<char *>(encoded));
            ok = publishQos1(kChunkTopic, payload, job.generation, publicationStarted);
        }
        offset += records;
    }

    unsigned char digest[32] = {};
    if (ok)
        ok = mbedtls_sha256_finish(&sha, digest) == 0;
    mbedtls_sha256_free(&sha);

    if (ok) {
        char hash[65];
        for (size_t i = 0; i < sizeof(digest); ++i)
            snprintf(hash + i * 2u, 3u, "%02x", digest[i]);
        hash[64] = '\0';
        const esp_app_desc_t *app = esp_app_get_description();
        char firmwareHash[65] = {};
        if (app != nullptr) {
            for (size_t i = 0; i < sizeof(app->app_elf_sha256); ++i)
                snprintf(firmwareHash + i * 2u, 3u, "%02x", app->app_elf_sha256[i]);
            firmwareHash[64] = '\0';
        }
        const uint32_t i2cErrors = deltaCounter(job.counters_end.i2c_errors, job.counters_start.i2c_errors);
        const uint32_t alertTimeouts = deltaCounter(job.counters_end.alert_timeouts, job.counters_start.alert_timeouts);
        const uint32_t coalescedAlerts = deltaCounter(job.counters_end.coalesced_alerts, job.counters_start.coalesced_alerts);
        const uint32_t timingErrors = deltaCounter(job.counters_end.timing_errors, job.counters_start.timing_errors);
        const uint32_t saturationErrors = deltaCounter(job.counters_end.saturation_errors, job.counters_start.saturation_errors);
        const uint32_t sampleGaps = deltaCounter(job.counters_end.sample_gaps, job.counters_start.sample_gaps);
        const uint32_t syncDrops = job.sync_queue_drops_end - job.sync_queue_drops_start;
        char completion[2048];
        snprintf(completion, sizeof(completion),
                 "{\"type\":\"complete\",\"source\":\"energy\",\"schema\":1,"
                 "\"capture_id\":\"%s\",\"clock_hz\":1000000,\"e0_us\":%" PRId64 ",\"e1_us\":%" PRId64 ","
                 "\"pretrigger_us\":%" PRId64 ",\"pretrigger_complete\":%s,"
                 "\"first_timestamp_us\":%" PRId64 ",\"last_timestamp_us\":%" PRId64 ","
                 "\"sample_count\":%" PRIu32 ",\"sample_record_bytes\":%u,"
                 "\"sample_encoding\":\"little_endian_ieee754_v1\","
                 "\"sample_fields\":[\"timestamp_us\",\"bus_v\",\"current_a\",\"power_w\"],"
                 "\"chunk_count\":%" PRIu32 ",\"logical_bytes\":%u,\"logical_sha256\":\"%s\","
                 "\"sync_gpio\":%d,\"alert_gpio\":%d,"
                 "\"calibration_id\":\"empirical_dmm_reference_loads_2026-09-25\","
                 "\"calibration_status\":\"empirical_two_load_current_scaling\","
                 "\"nominal_shunt_ohms\":0.015,\"effective_shunt_ohms\":0.029,"
                 "\"acquisition_mode\":\"alert_triggered_bus_shunt\","
                 "\"bus_conversion_us\":50,\"shunt_conversion_us\":50,\"averaging\":1,\"i2c_hz\":400000,"
                 "\"gap_limit_us\":10000,\"i2c_errors\":%" PRIu32 ",\"alert_timeouts\":%" PRIu32 ","
                 "\"coalesced_alerts\":%" PRIu32 ",\"timing_errors\":%" PRIu32 ","
                 "\"saturation_errors\":%" PRIu32 ",\"sample_gaps\":%" PRIu32 ","
                 "\"sync_queue_drops\":%" PRIu32 ",\"ring_capacity_samples\":%" PRIu32 ","
                 "\"ring_allocated_bytes\":%u,\"psram_total_bytes\":%u,\"psram_reserve_bytes\":%u,"
                 "\"firmware_sha256\":\"%s\"}",
                 job.capture_id, job.e0_us, job.e1_us, kPretriggerUs,
                 job.pretrigger_complete ? "true" : "false", job.first_timestamp_us, job.last_timestamp_us,
                 job.sample_count, static_cast<unsigned>(sizeof(energy_sample_record_t)), chunkCount,
                 static_cast<unsigned>(logicalBytes), hash, static_cast<int>(kSyncGpio), static_cast<int>(kAlertGpio),
                 i2cErrors, alertTimeouts, coalescedAlerts, timingErrors, saturationErrors, sampleGaps, syncDrops,
                 ringCapacity, static_cast<unsigned>(ringCapacity * sizeof(energy_sample_record_t)),
                 static_cast<unsigned>(psramTotalBytes), static_cast<unsigned>(kPsramReserveBytes),
                 firmwareHash);
        ok = publishQos1(kCompleteTopic, completion, job.generation, publicationStarted);
    }

    heap_caps_free(payload);
    heap_caps_free(encoded);
    heap_caps_free(raw);
    return ok;
}

void publisherTask(void *)
{
    CaptureJob job = {};
    for (;;) {
        if (xQueueReceive(captureQueue, &job, portMAX_DELAY) != pdTRUE)
            continue;

        const bool ok = publishCapture(job);
        resumeAfterPublication();

        if (xSemaphoreTake(stateMutex, portMAX_DELAY) == pdTRUE) {
            if (captureGeneration == job.generation) {
                state.last_publish_ok = ok;
                if (ok)
                    state.completed_captures++;
                else
                    state.aborted_captures++;
            }
            state.publishing = false;
            xSemaphoreGive(stateMutex);
        }
        if (!ok)
            ESP_LOGW(TAG, "Capture publication aborted or timed out: id=%s", job.capture_id);
    }
}

void processRising(int64_t timestampUs)
{
    pqc_ina228_snapshot_t sensor = {};
    pqc_ina228_sparkfun_snapshot(&sensor);
    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return;

    if (state.publishing) {
        /* This is outside the normal framework lifecycle. Cancel the old transfer;
         * the current HIGH interval is intentionally not accepted as a capture
         * because the requested pre-trigger history was not sampled while paused. */
        captureGeneration++;
        state.aborted_captures++;
        state.last_publish_ok = false;
        state.capture_active = false;
        xSemaphoreGive(stateMutex);
        ESP_LOGW(TAG, "Unexpected rising edge during publication; cancelling old transfer and invalidating this window");
        return;
    }

    captureGeneration++;
    if (state.capture_active)
        state.aborted_captures++;
    generateCaptureId(state.active_capture_id);
    activeE0Us = timestampUs;
    activeCountersStart = countersFrom(sensor);
    portENTER_CRITICAL(&syncMux);
    activeSyncDropsStart = syncQueueDrops;
    portEXIT_CRITICAL(&syncMux);
    state.capture_active = true;
    state.last_publish_ok = false;
    xSemaphoreGive(stateMutex);

    ESP_LOGI(TAG, "Capture start id=%s e0=%" PRId64 "us", state.active_capture_id, timestampUs);
}

void processFalling(int64_t timestampUs)
{
    CaptureJob job = {};

    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return;
    if (!state.capture_active) {
        xSemaphoreGive(stateMutex);
        ESP_LOGW(TAG, "Ignoring falling sync edge without an active capture");
        return;
    }
    strlcpy(job.capture_id, state.active_capture_id, sizeof(job.capture_id));
    job.generation = captureGeneration;
    job.e0_us = activeE0Us;
    job.e1_us = timestampUs;
    job.counters_start = activeCountersStart;
    job.sync_queue_drops_start = activeSyncDropsStart;
    state.capture_active = false;
    xSemaphoreGive(stateMutex);

    if (job.e1_us <= job.e0_us) {
        ESP_LOGE(TAG, "Rejecting non-monotonic capture id=%s", job.capture_id);
        recordAbortedCapture();
        return;
    }
    if (physicalHigh || !captureCurrent(job.generation))
        return;

    /* The falling-edge timestamp closes the measured interval. Pause only after
     * that timestamp has been retained, and wait for any in-flight INA228 sample
     * to finish before freezing the ring for publication. */
    if (!pqc_ina228_sparkfun_pause(kAcquisitionPauseTimeoutMs)) {
        ESP_LOGE(TAG, "Failed to pause INA228 acquisition after capture id=%s", job.capture_id);
        recordAbortedCapture();
        return;
    }

    pqc_ina228_snapshot_t sensor = {};
    pqc_ina228_sparkfun_snapshot(&sensor);
    job.counters_end = countersFrom(sensor);
    portENTER_CRITICAL(&syncMux);
    job.sync_queue_drops_end = syncQueueDrops;
    portEXIT_CRITICAL(&syncMux);

    if (physicalHigh || !captureCurrent(job.generation)) {
        resumeAfterPublication();
        return;
    }
    if (!prepareCaptureRange(&job)) {
        ESP_LOGE(TAG, "Capture has no usable frozen ring range: id=%s", job.capture_id);
        recordAbortedCapture();
        resumeAfterPublication();
        return;
    }

    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE) {
        recordAbortedCapture();
        resumeAfterPublication();
        return;
    }
    state.publishing = true;
    state.last_publish_ok = false;
    xSemaphoreGive(stateMutex);

    if (xQueueSend(captureQueue, &job, pdMS_TO_TICKS(100)) != pdTRUE) {
        ESP_LOGE(TAG, "Capture publisher queue full; dropping id=%s", job.capture_id);
        if (xSemaphoreTake(stateMutex, portMAX_DELAY) == pdTRUE) {
            state.publishing = false;
            state.aborted_captures++;
            xSemaphoreGive(stateMutex);
        }
        resumeAfterPublication();
        return;
    }
    ESP_LOGI(TAG, "Capture end id=%s e1=%" PRId64 "us; acquisition paused for publication",
             job.capture_id, timestampUs);
}

void syncWorker(void *)
{
    SyncEdgeEvent event = {};
    for (;;) {
        if (xQueueReceive(syncQueue, &event, portMAX_DELAY) != pdTRUE)
            continue;
        if (event.rising)
            processRising(event.timestamp_us);
        else
            processFalling(event.timestamp_us);
    }
}

void IRAM_ATTR syncGpioIsr(void *)
{
    if (syncQueue == nullptr)
        return;
    SyncEdgeEvent event = {};
    event.rising = gpio_get_level(kSyncGpio) != 0;
    event.timestamp_us = esp_timer_get_time();
    physicalHigh = event.rising;
    BaseType_t woken = pdFALSE;
    portENTER_CRITICAL_ISR(&syncMux);
    syncIsrEdges++;
    portEXIT_CRITICAL_ISR(&syncMux);
    if (xQueueSendFromISR(syncQueue, &event, &woken) != pdTRUE) {
        portENTER_CRITICAL_ISR(&syncMux);
        syncQueueDrops++;
        portEXIT_CRITICAL_ISR(&syncMux);
    }
    if (woken == pdTRUE)
        portYIELD_FROM_ISR();
}

void configureSyncGpio()
{
    syncQueue = xQueueCreate(kSyncQueueLength, sizeof(SyncEdgeEvent));
    configASSERT(syncQueue != nullptr);
    configASSERT(xTaskCreate(syncWorker, "energy_sync", 4096, nullptr, 7, &syncTaskHandle) == pdPASS);
    gpio_config_t io = {};
    io.pin_bit_mask = 1ULL << static_cast<unsigned>(kSyncGpio);
    io.mode = GPIO_MODE_INPUT;
    io.pull_up_en = GPIO_PULLUP_DISABLE;
    io.pull_down_en = GPIO_PULLDOWN_ENABLE;
    io.intr_type = GPIO_INTR_ANYEDGE;
    ESP_ERROR_CHECK(gpio_config(&io));
    ESP_ERROR_CHECK(gpio_isr_handler_add(kSyncGpio, syncGpioIsr, nullptr));
    physicalHigh = gpio_get_level(kSyncGpio) != 0;
    ESP_LOGI(TAG, "STM32 energy sync input ready on GPIO%d; idle=%s",
             static_cast<int>(kSyncGpio), physicalHigh ? "high" : "low");
}

void mqttEventHandler(void *, esp_event_base_t, int32_t eventId, void *eventData)
{
    esp_mqtt_event_handle_t event = static_cast<esp_mqtt_event_handle_t>(eventData);
    switch (eventId) {
        case MQTT_EVENT_CONNECTED:
            if (xSemaphoreTake(stateMutex, portMAX_DELAY) == pdTRUE) {
                state.mqtt_connected = true;
                xSemaphoreGive(stateMutex);
            }
            ESP_LOGI(TAG, "Reporting MQTT connected; publish-only energy appliance ready");
            break;
        case MQTT_EVENT_DISCONNECTED:
            if (xSemaphoreTake(stateMutex, portMAX_DELAY) == pdTRUE) {
                state.mqtt_connected = false;
                xSemaphoreGive(stateMutex);
            }
            ESP_LOGW(TAG, "Reporting MQTT disconnected");
            break;
        case MQTT_EVENT_PUBLISHED:
            if (publishAckQueue != nullptr) {
                const int messageId = event->msg_id;
                (void)xQueueSend(publishAckQueue, &messageId, 0);
            }
            break;
        default:
            break;
    }
}

} // namespace

extern "C" void pqc_energy_session_snapshot(pqc_energy_session_snapshot_t *out)
{
    if (out == nullptr)
        return;
    memset(out, 0, sizeof(*out));
    if (stateMutex == nullptr || xSemaphoreTake(stateMutex, pdMS_TO_TICKS(20)) != pdTRUE)
        return;
    out->mqtt_connected = state.mqtt_connected;
    out->publishing = state.publishing;
    out->last_publish_ok = state.last_publish_ok;
    out->ring_ready = sampleRing != nullptr;
    out->ring_overflowed = ringOverflowed;
    out->capture_active = state.capture_active;
    strlcpy(out->capture_id, state.active_capture_id, sizeof(out->capture_id));
    out->ring_capacity_samples = ringCapacity;
    out->ring_used_samples = ringCount;
    if (ringCount > 0) {
        out->oldest_timestamp_us = logicalSample(0).timestamp_us;
        out->newest_timestamp_us = logicalSample(ringCount - 1u).timestamp_us;
    }
    out->completed_capture_count = state.completed_captures;
    out->aborted_capture_count = state.aborted_captures;
    portENTER_CRITICAL(&syncMux);
    out->sync_isr_edges = syncIsrEdges;
    out->sync_queue_drops = syncQueueDrops;
    portEXIT_CRITICAL(&syncMux);
    xSemaphoreGive(stateMutex);
}

extern "C" void pqc_energy_session_start(void)
{
    stateMutex = xSemaphoreCreateMutex();
    configASSERT(stateMutex != nullptr);
    publishAckQueue = xQueueCreate(kPublishAckQueueLength, sizeof(int));
    captureQueue = xQueueCreate(kCaptureQueueLength, sizeof(CaptureJob));
    configASSERT(publishAckQueue != nullptr && captureQueue != nullptr);
    configASSERT(xTaskCreate(publisherTask, "energy_publish", CONFIG_PQC_ENERGY_PUBLISHER_STACK_BYTES,
                             nullptr, 5, &publisherTaskHandle) == pdPASS);

    const uint32_t caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
    psramTotalBytes = heap_caps_get_total_size(caps);
    const size_t freeBytes = heap_caps_get_free_size(caps);
    const size_t largest = heap_caps_get_largest_free_block(caps);
    size_t available = freeBytes > kPsramReserveBytes ? freeBytes - kPsramReserveBytes : 0;
    if (available > largest) available = largest;
    if (available > kRingBytesTarget) available = kRingBytesTarget;
    ringCapacity = static_cast<uint32_t>(available / sizeof(energy_sample_record_t));
    sampleRing = ringCapacity >= 2 ? static_cast<energy_sample_record_t *>(
        heap_caps_calloc(ringCapacity, sizeof(energy_sample_record_t), caps)) : nullptr;
    if (sampleRing == nullptr)
        ringCapacity = 0;
    ESP_LOGI(TAG,
             "Energy PSRAM ring: record=%u bytes allocated=%u bytes samples=%" PRIu32
             " pretrigger=%" PRId64 "us reserve=%u bytes",
             static_cast<unsigned>(sizeof(energy_sample_record_t)),
             static_cast<unsigned>(ringCapacity * sizeof(energy_sample_record_t)), ringCapacity,
             kPretriggerUs, static_cast<unsigned>(kPsramReserveBytes));

    pqc_ina228_sparkfun_set_sample_callback(storeSensorSample);
    configureSyncGpio();

    char uri[192];
    snprintf(uri, sizeof(uri), "mqtt://%s:%d", CONFIG_PQC_ENERGY_REPORTING_HOST, CONFIG_PQC_ENERGY_REPORTING_PORT);
    esp_mqtt_client_config_t config = {};
    config.broker.address.uri = uri;
    config.credentials.client_id = CONFIG_PQC_ENERGY_MQTT_CLIENT_ID;
    config.network.reconnect_timeout_ms = 3000;
    config.task.stack_size = CONFIG_PQC_ENERGY_MQTT_STACK_BYTES;
    config.buffer.size = 1024;
    config.buffer.out_size = 8192;
    config.network.timeout_ms = 5000;
    mqttClient = esp_mqtt_client_init(&config);
    configASSERT(mqttClient != nullptr);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(
        mqttClient, static_cast<esp_mqtt_event_id_t>(ESP_EVENT_ANY_ID), mqttEventHandler, nullptr));
    const esp_err_t rc = esp_mqtt_client_start(mqttClient);
    if (rc != ESP_OK)
        ESP_LOGE(TAG, "Failed to start reporting MQTT client: %s; acquisition remains active", esp_err_to_name(rc));
}
