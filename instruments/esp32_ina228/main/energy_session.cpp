/* Persistent ESP32 energy evidence service.
 *
 * INA228 acquisition runs from boot, pausing only for post-run collection. Every
 * valid SparkFun sensor snapshot is copied into a large PSRAM circular buffer.
 * STM32 sync GPIO edges delimit candidate intervals by sequence number; MQTT
 * is used only to claim/publish completed intervals after the experiment.
 */
#include "energy_session.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>

#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_random.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "mqtt_client.h"
#include "sdkconfig.h"
#include "mbedtls/sha256.h"
#include "mbedtls/base64.h"

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
#ifndef CONFIG_PQC_ENERGY_WORKER_STACK_BYTES
#define CONFIG_PQC_ENERGY_WORKER_STACK_BYTES 12288
#endif
#ifndef CONFIG_PQC_ENERGY_SYNC_GPIO
#define CONFIG_PQC_ENERGY_SYNC_GPIO 11
#endif

#ifndef CONFIG_PQC_INA228_ALERT_GPIO
#define CONFIG_PQC_INA228_ALERT_GPIO 12
#endif

namespace {

constexpr char kSource[] = "energy";
constexpr char kCollectTopic[] = "pqc/control/instrument/energy/collect";
constexpr char kStatusTopic[] = "pqc/control/instrument/energy/status";
constexpr char kAssociateTopic[] = "pqc/control/instrument/energy/associate";
constexpr size_t kAssociationTokenBytes = 32;
constexpr size_t kRingBytesTarget = CONFIG_PQC_ENERGY_RING_MAX_BYTES;
constexpr size_t kPsramReserveBytes = CONFIG_PQC_ENERGY_PSRAM_RESERVE_BYTES;
constexpr uint32_t kMaxIntervals = 1024;
constexpr size_t kChunkBytes = 4096;
constexpr size_t kCommandPayloadBytes = 512;
constexpr UBaseType_t kCommandQueueLength = 8;
constexpr UBaseType_t kPublishAckQueueLength = 8;
constexpr TickType_t kPublishAckTimeout = pdMS_TO_TICKS(5000);
constexpr UBaseType_t kSyncEdgeQueueLength = 32;
constexpr gpio_num_t kSyncGpio = static_cast<gpio_num_t>(CONFIG_PQC_ENERGY_SYNC_GPIO);

const char *TAG = "pqc_energy_session";

struct AcquisitionCounters {
    uint32_t i2c_errors, alert_timeouts, coalesced_alerts;
    uint32_t timing_errors, saturation_errors, sample_gaps;
};
AcquisitionCounters sampleCounters(const pqc_ina228_snapshot_t &s) {
    return {s.i2c_errors, s.alert_timeouts, s.coalesced_alerts,
            s.timing_errors, s.saturation_errors, s.sample_gaps};
}

typedef struct {
    AcquisitionCounters counters;
    uint64_t sequence;
    int64_t timestamp_us;
    float bus_v;
    float current_a;
    float power_w;
    uint32_t read_duration_us;
    uint32_t status_flags;
    uint16_t diagnostic_flags;
} energy_sample_record_t;

typedef struct {
    uint64_t interval_sequence;
    uint64_t start_sample_sequence;
    uint64_t end_sample_sequence;
    int64_t start_timestamp_us;
    int64_t end_timestamp_us;
    AcquisitionCounters counters_start;
    AcquisitionCounters counters_end;
    uint32_t sync_drops_start;
    uint32_t sync_drops_end;
    bool complete;
    bool claimed;
    bool discarded;
    bool association_valid;
    char association_token[kAssociationTokenBytes + 1];
} energy_interval_record_t;

SemaphoreHandle_t stateMutex = nullptr;
esp_mqtt_client_handle_t mqttClient = nullptr;
QueueHandle_t commandQueue = nullptr;
QueueHandle_t publishAckQueue = nullptr;
TaskHandle_t commandWorkerTask = nullptr;
QueueHandle_t syncEdgeQueue = nullptr;
TaskHandle_t syncEdgeWorkerTask = nullptr;
energy_sample_record_t *sampleRing = nullptr;
uint32_t ringCapacity = 0;
uint32_t ringCount = 0;
uint32_t ringWriteIndex = 0;
uint64_t oldestSequence = 0;
uint64_t newestSequence = 0;
bool ringOverflowed = false;
size_t psramTotalBytes = 0;
volatile bool collectionCancelled = false;
bool collectPending = false;
int64_t collectionStartedUs = 0;
constexpr int64_t kCollectionLimitUs = 300LL * 1000000;

energy_interval_record_t *intervals = nullptr;
uint32_t intervalWriteIndex = 0;
uint32_t intervalCount = 0;
uint64_t nextIntervalSequence = 1;
bool intervalActive = false;
bool intervalDescriptorOverflowed = false;
energy_interval_record_t openInterval = {};
char sessionId[33] = {};
volatile bool physicalIntervalActive = false;

portMUX_TYPE syncDiagnosticMux = portMUX_INITIALIZER_UNLOCKED;
volatile uint32_t syncIsrEdges = 0;
volatile uint32_t syncQueueDrops = 0;
uint32_t syncProcessedRising = 0;
uint32_t syncProcessedFalling = 0;
uint32_t syncUnexpectedRising = 0;
uint32_t syncOrphanFalling = 0;

char associationToken[kAssociationTokenBytes + 1] = {};
bool associationTokenValid = false;
uint32_t associationSyncQueueDropsBaseline = 0;
uint32_t associationSyncFaultsBaseline = 0;

struct ServiceState {
    bool mqttConnected = false;
    bool publishing = false;
    bool lastPublishOk = false;
    char lastRunId[80] = {};
    uint32_t discardedOverwrittenIntervals = 0;
    uint32_t completedIntervals = 0;
};
ServiceState state;

struct SyncEdgeEvent {
    bool rising;
    int64_t timestampUs;
    bool associationValid;
    char token[kAssociationTokenBytes + 1];
};

void recordSyncEdge(bool rising, int64_t esp32TimestampUs, const SyncEdgeEvent *captured = nullptr)
{
    if (stateMutex == nullptr)
        return;

    /*
     * Sync events are scientific boundaries. Once the ISR has queued an edge,
     * never silently discard it because a short metadata operation owns the
     * mutex. ISR queue loss is counted separately and exposed as evidence.
     */
    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return;

    if (rising) {
        syncProcessedRising++;
        if (!intervalActive && ringCount > 0) {
            if (state.publishing || collectPending || pqc_ina228_sparkfun_is_paused()) syncUnexpectedRising++; // overlapping capture is invalid
            openInterval = energy_interval_record_t{};
            openInterval.interval_sequence = nextIntervalSequence++;
            openInterval.start_sample_sequence = newestSequence;
            openInterval.start_timestamp_us = esp32TimestampUs;
            openInterval.sync_drops_start = syncQueueDrops;

            /*
             * Snapshot the per-run association token at the physical rising
             * edge. Preparation and measurement collectors use distinct
             * tokens even if their human-readable run IDs repeat. If the
             * reporting path is unavailable, leave the interval unlabeled.
             */
            if (captured != nullptr ? captured->associationValid : (associationTokenValid && state.mqttConnected)) {
                strlcpy(openInterval.association_token, captured != nullptr ? captured->token : associationToken,
                        sizeof(openInterval.association_token));
                openInterval.association_valid = true;
            }

            intervalActive = true;
            ESP_LOGI(TAG,
                     "STM32 sync rising edge: candidate seq=%" PRIu64
                     " sample=%" PRIu64 " t=%" PRId64 "us association=%s",
                     openInterval.interval_sequence,
                     openInterval.start_sample_sequence,
                     esp32TimestampUs,
                     openInterval.association_valid ? openInterval.association_token : "<unlabeled>");
        } else {
            syncUnexpectedRising++;
            ESP_LOGW(TAG,
                     "Ignoring STM32 sync rising edge: interval_active=%u ring_samples=%" PRIu32,
                     intervalActive ? 1u : 0u, ringCount);
        }
    } else {
        syncProcessedFalling++;
        if (intervalActive) {
            openInterval.end_sample_sequence = newestSequence;
            openInterval.end_timestamp_us = esp32TimestampUs;
            openInterval.sync_drops_end = syncQueueDrops;
            openInterval.complete =
                openInterval.end_sample_sequence >= openInterval.start_sample_sequence;

            if (intervalCount == kMaxIntervals &&
                intervals[intervalWriteIndex].complete &&
                !intervals[intervalWriteIndex].claimed &&
                !intervals[intervalWriteIndex].discarded &&
                openInterval.association_valid && intervals[intervalWriteIndex].association_valid &&
                strcmp(openInterval.association_token, intervals[intervalWriteIndex].association_token) == 0) {
                intervalDescriptorOverflowed = true;
            }

            intervals[intervalWriteIndex] = openInterval;
            intervalWriteIndex = (intervalWriteIndex + 1u) % kMaxIntervals;
            if (intervalCount < kMaxIntervals)
                intervalCount++;
            state.completedIntervals++;
            intervalActive = false;

            ESP_LOGI(TAG,
                     "Captured candidate interval seq=%" PRIu64
                     " samples=%" PRIu64 "..%" PRIu64
                     " t=%" PRId64 "..%" PRId64 "us association=%s",
                     openInterval.interval_sequence,
                     openInterval.start_sample_sequence,
                     openInterval.end_sample_sequence,
                     openInterval.start_timestamp_us,
                     openInterval.end_timestamp_us,
                     openInterval.association_valid ? openInterval.association_token : "<unlabeled>");
        } else {
            syncOrphanFalling++;
            ESP_LOGW(TAG, "Ignoring STM32 sync falling edge without active interval");
        }
    }

    xSemaphoreGive(stateMutex);
}

void syncEdgeWorker(void *)
{
    SyncEdgeEvent event = {};
    for (;;) {
        if (xQueueReceive(syncEdgeQueue, &event, portMAX_DELAY) == pdTRUE)
            recordSyncEdge(event.rising, event.timestampUs, &event);
    }
}

void IRAM_ATTR syncGpioIsr(void *)
{
    if (syncEdgeQueue == nullptr)
        return;

    SyncEdgeEvent event = {};
    event.rising = gpio_get_level(kSyncGpio) != 0;
    event.timestampUs = esp_timer_get_time();
    physicalIntervalActive = event.rising;

    BaseType_t higherPriorityTaskWoken = pdFALSE;
    portENTER_CRITICAL_ISR(&syncDiagnosticMux);
    event.associationValid = associationTokenValid;
    memcpy(event.token, associationToken, sizeof(event.token));
    syncIsrEdges += 1U;
    portEXIT_CRITICAL_ISR(&syncDiagnosticMux);

    if (xQueueSendFromISR(syncEdgeQueue, &event, &higherPriorityTaskWoken) != pdTRUE) {
        portENTER_CRITICAL_ISR(&syncDiagnosticMux);
        syncQueueDrops += 1U;
        portEXIT_CRITICAL_ISR(&syncDiagnosticMux);
    }

    if (higherPriorityTaskWoken == pdTRUE)
        portYIELD_FROM_ISR();
}

void configureSyncGpio()
{
    syncEdgeQueue = xQueueCreate(kSyncEdgeQueueLength, sizeof(SyncEdgeEvent));
    configASSERT(syncEdgeQueue != nullptr);
    const BaseType_t created = xTaskCreate(syncEdgeWorker, "energy_sync_worker", 4096, nullptr, 7, &syncEdgeWorkerTask);
    configASSERT(created == pdPASS);

    gpio_config_t io = {};
    io.pin_bit_mask = 1ULL << static_cast<unsigned>(kSyncGpio);
    io.mode = GPIO_MODE_INPUT;
    io.pull_up_en = GPIO_PULLUP_DISABLE;
    io.pull_down_en = GPIO_PULLDOWN_ENABLE;
    io.intr_type = GPIO_INTR_ANYEDGE;
    ESP_ERROR_CHECK(gpio_config(&io));
    /*
     * The INA228 driver installs the process-wide GPIO ISR service before
     * energy_session starts. Add only the STM32 sync handler here so ESP-IDF
     * does not emit a duplicate-service error.
     */
    ESP_ERROR_CHECK(gpio_isr_handler_add(kSyncGpio, syncGpioIsr, nullptr));
    ESP_LOGI(TAG, "STM32 energy sync input ready: GPIO%d both-edge capture", static_cast<int>(kSyncGpio));
}

bool validAssociationToken(const char *token, size_t length)
{
    if (token == nullptr || length != kAssociationTokenBytes)
        return false;
    for (size_t i = 0; i < length; ++i) {
        const char c = token[i];
        const bool hex =
            (c >= '0' && c <= '9') ||
            (c >= 'a' && c <= 'f') ||
            (c >= 'A' && c <= 'F');
        if (!hex)
            return false;
    }
    return true;
}

void recordAssociationToken(const char *token, size_t length)
{
    if (length == 0 && stateMutex != nullptr) {
        xSemaphoreTake(stateMutex, portMAX_DELAY);
        portENTER_CRITICAL(&syncDiagnosticMux);
        associationTokenValid = false;
        portEXIT_CRITICAL(&syncDiagnosticMux);
        xSemaphoreGive(stateMutex);
        return;
    }
    if (!validAssociationToken(token, length) || stateMutex == nullptr) {
        ESP_LOGW(TAG, "Ignoring invalid energy association token length=%u",
                 static_cast<unsigned>(length));
        return;
    }

    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return;

    if (physicalIntervalActive || intervalActive || state.publishing || collectPending || pqc_ina228_sparkfun_is_paused()) {
        xSemaphoreGive(stateMutex);
        return;
    }
    portENTER_CRITICAL(&syncDiagnosticMux);
    const bool changed = memcmp(associationToken, token, kAssociationTokenBytes) != 0;
    memcpy(associationToken, token, kAssociationTokenBytes);
    associationToken[kAssociationTokenBytes] = '\0';
    associationTokenValid = true;
    if (changed) {
        intervalDescriptorOverflowed = false;
        associationSyncQueueDropsBaseline = syncQueueDrops;
        associationSyncFaultsBaseline = syncUnexpectedRising + syncOrphanFalling;
    }
    portEXIT_CRITICAL(&syncDiagnosticMux);

    ESP_LOGI(TAG,
             "Energy association token updated: token=%s sync_queue_drops=%" PRIu32,
             associationToken, associationSyncQueueDropsBaseline);
    xSemaphoreGive(stateMutex);
}

bool sampleSequenceRetained(uint64_t seq)
{
    return ringCount > 0 && seq >= oldestSequence && seq <= newestSequence;
}

bool copySampleBySequence(uint64_t seq, energy_sample_record_t *out)
{
    if (out == nullptr || stateMutex == nullptr)
        return false;
    if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(100)) != pdTRUE)
        return false;

    bool ok = false;
    if (sampleSequenceRetained(seq) && ringCapacity != 0 && ringCount != 0) {
        /*
         * Stored sample sequences are monotonically increasing but are not
         * required to be numerically dense.  Search logical ring order instead
         * of assuming (seq - oldestSequence) is a physical slot offset.
         */
        const uint32_t oldestIndex = (ringWriteIndex + ringCapacity - ringCount) % ringCapacity;
        uint32_t lo = 0;
        uint32_t hi = ringCount;
        while (lo < hi) {
            const uint32_t mid = lo + (hi - lo) / 2u;
            const uint32_t index = (oldestIndex + mid) % ringCapacity;
            const uint64_t candidate = sampleRing[index].sequence;
            if (candidate < seq)
                lo = mid + 1u;
            else
                hi = mid;
        }
        if (lo < ringCount) {
            const uint32_t index = (oldestIndex + lo) % ringCapacity;
            if (sampleRing[index].sequence == seq) {
                *out = sampleRing[index];
                ok = true;
            }
        }
    }

    xSemaphoreGive(stateMutex);
    return ok;
}

void storeSensorSample(const pqc_ina228_snapshot_t *sensor)
{
    if (sensor == nullptr || sampleRing == nullptr || ringCapacity == 0)
        return;
    /*
     * Do not silently drop a scientific sample because another framework task
     * held the metadata mutex briefly.  The old timed take could create holes
     * in sample_sequence while the ring lookup assumed dense sequences,
     * causing post-run collection to abort before the first MQTT chunk.
     */
    if (xSemaphoreTake(stateMutex, portMAX_DELAY) != pdTRUE)
        return;

    if (!sensor->online || !sensor->valid || sensor->sample_sequence <= newestSequence) {
        xSemaphoreGive(stateMutex);
        return;
    }
    energy_sample_record_t &slot = sampleRing[ringWriteIndex];
    slot.counters = sampleCounters(*sensor);
    slot.sequence = sensor->sample_sequence;
    slot.timestamp_us = sensor->timestamp_us;
    slot.bus_v = static_cast<float>(sensor->bus_v);
    slot.current_a = static_cast<float>(sensor->current_a);
    slot.power_w = static_cast<float>(sensor->power_w);
    slot.read_duration_us = sensor->read_duration_us;
    slot.status_flags = sensor->status_flags;
    slot.diagnostic_flags = sensor->diagnostic_flags;

    ringWriteIndex = (ringWriteIndex + 1u) % ringCapacity;
    newestSequence = sensor->sample_sequence;
    if (ringCount < ringCapacity) {
        ringCount++;
        if (ringCount == 1)
            oldestSequence = newestSequence;
    } else {
        ringOverflowed = true;
        /*
         * ringWriteIndex now points at the oldest retained slot.  Read its
         * actual sequence instead of deriving it arithmetically so historical
         * sequence gaps cannot corrupt retention bounds.
         */
        oldestSequence = sampleRing[ringWriteIndex].sequence;
    }
    xSemaphoreGive(stateMutex);
}

// Caller holds stateMutex, or the acquisition task has acknowledged its pause.
// Raw retained coverage may include an earlier deliberate collection pause.
int64_t retainedSpanUs()
{
    if (ringCount < 2 || ringCapacity == 0) return 0;
    const uint32_t oldest = (ringWriteIndex + ringCapacity - ringCount) % ringCapacity;
    const uint32_t newest = (ringWriteIndex + ringCapacity - 1) % ringCapacity;
    return sampleRing[newest].timestamp_us - sampleRing[oldest].timestamp_us;
}

bool collectionMayContinue()
{
    return !collectionCancelled && !physicalIntervalActive && gpio_get_level(kSyncGpio) == 0 &&
        esp_timer_get_time() - collectionStartedUs < kCollectionLimitUs;
}

void publishStatus(const char *statusText, const char *runId)
{
    if (mqttClient == nullptr)
        return;
    char payload[1536];
    int64_t spanUs = 0;
    char token[33] = {};
    pqc_ina228_snapshot_t sensor = {};
    pqc_ina228_sparkfun_snapshot(&sensor);
    uint32_t used = 0;
    uint64_t oldest = 0;
    uint64_t newest = 0;
    uint32_t unclaimed = 0;
    uint32_t completedIntervals = 0;
    uint32_t processedRising = 0;
    uint32_t processedFalling = 0;
    uint32_t unexpectedRising = 0;
    uint32_t orphanFalling = 0;
    uint32_t isrEdges = 0;
    uint32_t queueDrops = 0;
    bool connected = false;
    if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        used = ringCount;
        spanUs = retainedSpanUs();
        if (associationTokenValid) strlcpy(token, associationToken, sizeof(token));
        oldest = oldestSequence;
        newest = newestSequence;
        connected = state.mqttConnected;
        completedIntervals = state.completedIntervals;
        processedRising = syncProcessedRising;
        processedFalling = syncProcessedFalling;
        unexpectedRising = syncUnexpectedRising;
        orphanFalling = syncOrphanFalling;
        portENTER_CRITICAL(&syncDiagnosticMux);
        isrEdges = syncIsrEdges;
        queueDrops = syncQueueDrops;
        portEXIT_CRITICAL(&syncDiagnosticMux);
        for (uint32_t i = 0; i < intervalCount; ++i) {
            const uint32_t index = (intervalWriteIndex + kMaxIntervals - intervalCount + i) % kMaxIntervals;
            if (intervals[index].complete && !intervals[index].claimed && !intervals[index].discarded)
                unclaimed++;
        }
        xSemaphoreGive(stateMutex);
    }
    if (!connected)
        return;
    snprintf(payload, sizeof(payload),
             "{\"type\":\"status\",\"source\":\"energy\",\"run_id\":\"%s\","
             "\"status\":\"%s\",\"acquisition\":\"%s\","
             "\"association_token\":\"%s\",\"sensor_online\":%s,\"sensor_valid\":%s,"
             "\"sample_timestamp_us\":%" PRId64 ",\"status_timestamp_us\":%" PRId64 ","
             "\"ring_allocated_bytes\":%u,\"sample_record_bytes\":%u,\"psram_total_bytes\":%u,"
             "\"ring_target_bytes\":%u,\"psram_reserve_bytes\":%u,\"retained_span_us\":%" PRId64 ","
             "\"ring_capacity_samples\":%" PRIu32 ",\"ring_used_samples\":%" PRIu32 ","
             "\"oldest_sequence\":%" PRIu64 ",\"newest_sequence\":%" PRIu64 ","
             "\"unclaimed_intervals\":%" PRIu32 ","
             "\"discarded_overwritten_intervals\":%" PRIu32 ","
             "\"sync_isr_edges\":%" PRIu32 ","
             "\"sync_queue_drops\":%" PRIu32 ","
             "\"sync_processed_rising\":%" PRIu32 ","
             "\"sync_processed_falling\":%" PRIu32 ","
             "\"sync_unexpected_rising\":%" PRIu32 ","
             "\"sync_orphan_falling\":%" PRIu32 ","
             "\"completed_intervals\":%" PRIu32 "}",
             runId != nullptr ? runId : "", statusText, sensor.paused ? "paused_for_collection" : "continuous",
             token, sensor.online ? "true" : "false", sensor.valid ? "true" : "false",
             sensor.timestamp_us, esp_timer_get_time(),
             static_cast<unsigned>(ringCapacity * sizeof(energy_sample_record_t)),
             static_cast<unsigned>(sizeof(energy_sample_record_t)), static_cast<unsigned>(psramTotalBytes),
             static_cast<unsigned>(kRingBytesTarget), static_cast<unsigned>(kPsramReserveBytes), spanUs,
             ringCapacity, used, oldest, newest,
             unclaimed, state.discardedOverwrittenIntervals,
             isrEdges, queueDrops, processedRising, processedFalling,
             unexpectedRising, orphanFalling, completedIntervals);
    esp_mqtt_client_publish(mqttClient, kStatusTopic, payload, 0, 1, 1);
}


void publishRunFailure(const char *runId, const char *statusText, uint64_t sequence)
{
    if (mqttClient == nullptr || runId == nullptr || runId[0] == '\0')
        return;

    uint32_t isrEdges = 0;
    uint32_t queueDrops = 0;
    portENTER_CRITICAL(&syncDiagnosticMux);
    isrEdges = syncIsrEdges;
    queueDrops = syncQueueDrops;
    portEXIT_CRITICAL(&syncDiagnosticMux);

    char topic[160];
    char payload[1024];
    xSemaphoreTake(stateMutex, portMAX_DELAY);
    const int64_t span = retainedSpanUs();
    snprintf(topic, sizeof(topic), "pqc/instrument/energy/%s/complete", runId);
    snprintf(payload, sizeof(payload),
             "{\"type\":\"error\",\"source\":\"energy\",\"run_id\":\"%s\","
             "\"status\":\"%s\",\"sequence\":%" PRIu64 ","
             "\"ring_capacity_samples\":%" PRIu32 ",\"ring_used_samples\":%" PRIu32 ","
             "\"sample_record_bytes\":%u,\"ring_allocated_bytes\":%u,"
             "\"oldest_sequence\":%" PRIu64 ",\"newest_sequence\":%" PRIu64 ","
             "\"retained_span_us\":%" PRId64 ",\"sync_isr_edges\":%" PRIu32 ","
             "\"sync_queue_drops\":%" PRIu32 ",\"sync_processed_rising\":%" PRIu32 ","
             "\"sync_processed_falling\":%" PRIu32 ",\"sync_unexpected_rising\":%" PRIu32 ","
             "\"sync_orphan_falling\":%" PRIu32 "}",
             runId, statusText != nullptr ? statusText : "unknown", sequence,
             ringCapacity, ringCount, static_cast<unsigned>(sizeof(energy_sample_record_t)),
             static_cast<unsigned>(ringCapacity * sizeof(energy_sample_record_t)),
             oldestSequence, newestSequence, span, isrEdges, queueDrops,
             syncProcessedRising, syncProcessedFalling, syncUnexpectedRising, syncOrphanFalling);
    xSemaphoreGive(stateMutex);
    (void)esp_mqtt_client_publish(mqttClient, topic, payload, 0, 1, 0);
}

void clearPublishAckBacklog()
{
    if (publishAckQueue != nullptr)
        (void)xQueueReset(publishAckQueue);
}

bool waitForPublishAck(int messageId)
{
    if (messageId < 0 || publishAckQueue == nullptr)
        return false;

    const TickType_t started = xTaskGetTickCount();
    for (;;) {
        const TickType_t elapsed = xTaskGetTickCount() - started;
        if (elapsed >= kPublishAckTimeout) {
            ESP_LOGE(TAG, "Timed out waiting for MQTT PUBACK message_id=%d", messageId);
            return false;
        }

        if (!collectionMayContinue()) return false;
        const TickType_t remaining = kPublishAckTimeout - elapsed;
        const TickType_t slice = remaining < pdMS_TO_TICKS(100) ? remaining : pdMS_TO_TICKS(100);
        int ackedMessageId = -1;
        if (xQueueReceive(publishAckQueue, &ackedMessageId, slice) != pdTRUE)
            continue;

        if (ackedMessageId == messageId)
            return true;

        ESP_LOGD(TAG,
                 "Ignoring stale MQTT PUBACK message_id=%d while waiting for %d",
                 ackedMessageId, messageId);
    }
}

struct TracePublisher {
    mbedtls_sha256_context sha;
    char *chunk = nullptr;
    size_t chunkUsed = 0;
    uint32_t chunkSequence = 0;
    uint32_t recordCount = 0;
    size_t logicalBytes = 0;
    char runId[80] = {};
    bool ok = true;
    uint32_t sampleCount = 0;
    uint32_t intervalCount = 0;
    uint64_t chunkPayloadBytes = 0;
    int64_t chunkPublishUs = 0;

    explicit TracePublisher(const char *id)
    {
        strlcpy(runId, id, sizeof(runId));
        chunk = static_cast<char *>(heap_caps_malloc(kChunkBytes, MALLOC_CAP_8BIT));
        if (chunk == nullptr)
            ok = false;
        mbedtls_sha256_init(&sha);
        if (mbedtls_sha256_starts(&sha, 0) != 0)
            ok = false;
    }

    ~TracePublisher()
    {
        if (chunk != nullptr)
            heap_caps_free(chunk);
        mbedtls_sha256_free(&sha);
    }

    bool publishChunk()
    {
        if (!ok || chunk == nullptr || !collectionMayContinue())
            return false;
        if (chunkUsed == 0)
            return true;
        char topic[160];
        snprintf(topic, sizeof(topic), "pqc/instrument/energy/%s/chunk", runId);
        std::string encoded(4 * ((chunkUsed + 2) / 3) + 1, '\0');
        size_t encodedLength = 0;
        if (mbedtls_base64_encode(reinterpret_cast<unsigned char *>(&encoded[0]), encoded.size(),
                                  &encodedLength, reinterpret_cast<const unsigned char *>(chunk), chunkUsed) != 0)
            return false;
        encoded.resize(encodedLength);
        std::string payload = "{\"type\":\"chunk\",\"source\":\"energy\",\"run_id\":\"";
        payload += runId;
        payload += "\",\"sequence\":" + std::to_string(chunkSequence) + ",\"data_b64\":\"" + encoded + "\"}";
        const int64_t publishStart = esp_timer_get_time();
        clearPublishAckBacklog();
        const int messageId =
            esp_mqtt_client_publish(mqttClient, topic, payload.c_str(), 0, 1, 0);
        if (messageId < 0 || !waitForPublishAck(messageId)) {
            ESP_LOGE(TAG,
                     "Energy chunk publication failed: run_id=%s sequence=%" PRIu32
                     " mqtt_message_id=%d",
                     runId, chunkSequence, messageId);
            return false;
        }
        chunkPublishUs += esp_timer_get_time() - publishStart;
        chunkPayloadBytes += payload.size();
        chunkSequence++;
        chunkUsed = 0;
        return true;
    }

    bool append(const char *line)
    {
        if (!ok || line == nullptr)
            return false;
        const size_t lineLen = strlen(line);
        const size_t total = lineLen + 1u;
        if (mbedtls_sha256_update(&sha, reinterpret_cast<const unsigned char *>(line), lineLen) != 0 ||
            mbedtls_sha256_update(&sha, reinterpret_cast<const unsigned char *>("\n"), 1) != 0)
            return false;
        logicalBytes += total;
        recordCount++;
        size_t offset = 0;
        while (offset < total) {
            const size_t available = kChunkBytes - chunkUsed;
            const size_t remain = total - offset;
            const size_t take = remain < available ? remain : available;
            if (offset < lineLen) {
                const size_t textRemain = lineLen - offset;
                const size_t textTake = take < textRemain ? take : textRemain;
                memcpy(chunk + chunkUsed, line + offset, textTake);
                if (take > textTake)
                    chunk[chunkUsed + textTake] = '\n';
            } else {
                chunk[chunkUsed] = '\n';
            }
            chunkUsed += take;
            offset += take;
            if (chunkUsed == kChunkBytes && !publishChunk())
                return false;
        }
        return true;
    }

    bool finish()
    {
        if (!publishChunk() || !collectionMayContinue())
            return false;
        unsigned char digest[32];
        if (mbedtls_sha256_finish(&sha, digest) != 0)
            return false;
        char hash[65];
        for (size_t i = 0; i < sizeof(digest); ++i)
            snprintf(hash + i * 2u, 3u, "%02x", digest[i]);
        hash[64] = '\0';
        char topic[160];
        char payload[512];
        snprintf(topic, sizeof(topic), "pqc/instrument/energy/%s/complete", runId);
        snprintf(payload, sizeof(payload),
                 "{\"type\":\"complete\",\"source\":\"energy\",\"run_id\":\"%s\","
                 "\"record_count\":%" PRIu32 ",\"chunk_count\":%" PRIu32 ","
                 "\"logical_bytes\":%u,\"logical_sha256\":\"%s\",\"sample_count\":%" PRIu32 ",\"interval_count\":%" PRIu32 ",\"acquisition_status\":\"raw\","
                 "\"chunk_payload_bytes\":%" PRIu64 ",\"chunk_publish_us\":%" PRId64 ","
                 "\"transfer_elapsed_us\":%" PRId64 "}",
                 runId, recordCount, chunkSequence, static_cast<unsigned>(logicalBytes), hash, sampleCount, intervalCount,
                 chunkPayloadBytes, chunkPublishUs, esp_timer_get_time() - collectionStartedUs);
        clearPublishAckBacklog();
        const int messageId = esp_mqtt_client_publish(mqttClient, topic, payload, 0, 1, 0);
        if (messageId < 0 || !waitForPublishAck(messageId)) {
            ESP_LOGE(TAG,
                     "Energy completion publication failed: run_id=%s mqtt_message_id=%d",
                     runId, messageId);
            return false;
        }
        return true;
    }
};

// Called under stateMutex. Preserve one sample on each side for offline
// boundary treatment; relative_us may intentionally be negative.
bool resolveIntervalSamples(energy_interval_record_t &interval)
{
    if (ringCount < 2) return false;
    const uint32_t oldest = (ringWriteIndex + ringCapacity - ringCount) % ringCapacity;
    auto at = [oldest](uint32_t i) -> const energy_sample_record_t & {
        return sampleRing[(oldest + i) % ringCapacity];
    };
    if (at(0).timestamp_us > interval.start_timestamp_us ||
        at(ringCount - 1).timestamp_us < interval.end_timestamp_us) return false;
    uint32_t lo = 0, hi = ringCount;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (at(mid).timestamp_us <= interval.start_timestamp_us) lo = mid + 1;
        else hi = mid;
    }
    interval.start_sample_sequence = at(lo - 1).sequence;
    interval.counters_start = at(lo - 1).counters;
    lo = 0; hi = ringCount;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (at(mid).timestamp_us < interval.end_timestamp_us) lo = mid + 1;
        else hi = mid;
    }
    interval.end_sample_sequence = at(lo).sequence;
    interval.counters_end = at(lo).counters;
    return true;
}

bool publishClaimedIntervalsPaused(const char *runId, const char *associationTokenRequested,
                             uint32_t expectedIntervals)
{
    energy_interval_record_t claimed[32] = {};
    uint32_t claimedCount = 0;
    if (expectedIntervals == 0 || expectedIntervals > 32)
        return false;

    if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(250)) != pdTRUE)
        return false;
    if (intervals == nullptr) {
        xSemaphoreGive(stateMutex);
        publishStatus("interval_storage_unavailable", runId);
        publishRunFailure(runId, "interval_storage_unavailable", 0);
        return false;
    }
    if (intervalActive || physicalIntervalActive || state.publishing) {
        xSemaphoreGive(stateMutex);
        publishStatus("interval_active", runId);
        publishRunFailure(runId, "interval_active", 0);
        return false;
    }
    if (intervalDescriptorOverflowed) {
        xSemaphoreGive(stateMutex);
        publishStatus("interval_descriptor_overflow", runId);
        publishRunFailure(runId, "interval_descriptor_overflow", 0);
        return false;
    }

    /*
     * Retire descriptors whose referenced samples have wrapped out of PSRAM,
     * but preserve still-retained failed intervals for explicit retry.
     */
    uint32_t discardedNow = 0;
    bool runCapacityExceeded = false;
    for (uint32_t i = 0; i < intervalCount; ++i) {
        const uint32_t index =
            (intervalWriteIndex + kMaxIntervals - intervalCount + i) % kMaxIntervals;
        energy_interval_record_t &candidate = intervals[index];
        if (!candidate.complete || candidate.claimed)
            continue;
        if (candidate.discarded) {
            if (candidate.association_valid && strcmp(candidate.association_token, associationTokenRequested) == 0)
                runCapacityExceeded = true;
            continue;
        }
        const uint32_t oldest = ringCapacity ? (ringWriteIndex + ringCapacity - ringCount) % ringCapacity : 0;
        if (ringCount == 0 || sampleRing[oldest].timestamp_us > candidate.start_timestamp_us) {
            candidate.discarded = true;
            if (candidate.association_valid && strcmp(candidate.association_token, associationTokenRequested) == 0)
                runCapacityExceeded = true;
            discardedNow++;
            state.discardedOverwrittenIntervals++;
            ESP_LOGW(TAG,
                     "Retiring overwritten unclaimed energy interval: sequence=%" PRIu64
                     " samples=%" PRIu64 "..%" PRIu64 " association=%s",
                     candidate.interval_sequence,
                     candidate.start_sample_sequence,
                     candidate.end_sample_sequence,
                     candidate.association_valid ? candidate.association_token : "<unlabeled>");
        }
    }

    /*
     * Primary association is the exact per-collector token captured at the
     * physical rising edge. This prevents preparation intervals and repeated
     * human-readable run IDs from being claimed by a later experiment.
     */
    if (validAssociationToken(associationTokenRequested, strlen(associationTokenRequested))) {
        for (uint32_t i = 0; i < intervalCount; ++i) {
            const uint32_t index =
                (intervalWriteIndex + kMaxIntervals - intervalCount + i) % kMaxIntervals;
            const energy_interval_record_t &candidate = intervals[index];
            if (candidate.complete && !candidate.claimed && !candidate.discarded &&
                candidate.association_valid &&
                strcmp(candidate.association_token, associationTokenRequested) == 0) {
                if (claimedCount < 32) claimed[claimedCount] = candidate;
                claimedCount++;
            }
        }
    }

    if (claimedCount != expectedIntervals || runCapacityExceeded) {
        uint32_t currentDrops = 0;
        portENTER_CRITICAL(&syncDiagnosticMux);
        currentDrops = syncQueueDrops;
        portEXIT_CRITICAL(&syncDiagnosticMux);

        const bool syncLossObserved =
            currentDrops > associationSyncQueueDropsBaseline;
        const char *statusText =
            runCapacityExceeded ? "capacity_exceeded" :
            (syncLossObserved ? "sync_edge_loss" : "intervals_unavailable");

        xSemaphoreGive(stateMutex);
        ESP_LOGW(TAG,
                 "Energy collect has insufficient associated intervals: run_id=%s "
                 "expected=%" PRIu32 " associated=%" PRIu32
                 " discarded_now=%" PRIu32 " sync_queue_drops=%" PRIu32,
                 runId, expectedIntervals, claimedCount, discardedNow, currentDrops);
        publishStatus(statusText, runId);
        publishRunFailure(runId, statusText, 0);
        return false;
    }

    if (discardedNow > 0) {
        ESP_LOGI(TAG,
                 "Energy collect recovered after retiring %" PRIu32
                 " overwritten interval descriptor(s): run_id=%s",
                 discardedNow, runId);
    }
    for (uint32_t i = 0; i < claimedCount; ++i) {
        if (!resolveIntervalSamples(claimed[i]) ||
            claimed[i].sync_drops_end != claimed[i].sync_drops_start ||
            syncQueueDrops != associationSyncQueueDropsBaseline ||
            syncUnexpectedRising + syncOrphanFalling != associationSyncFaultsBaseline) {
            xSemaphoreGive(stateMutex);
            publishRunFailure(runId, "boundary_or_samples_incomplete", 0);
            return false;
        }
    }
    state.publishing = true;
    strlcpy(state.lastRunId, runId, sizeof(state.lastRunId));
    xSemaphoreGive(stateMutex);

    ESP_LOGI(TAG,
             "Publishing energy evidence with QoS1 flow control: run_id=%s intervals=%" PRIu32
             " chunk_bytes=%u",
             runId, claimedCount, static_cast<unsigned>(kChunkBytes));
    TracePublisher publisher(runId);
    char line[2048];
    const esp_app_desc_t *app = esp_app_get_description();
    char firmwareHash[65];
    for (size_t i = 0; i < 32; ++i)
        snprintf(firmwareHash + 2 * i, 3, "%02x", app->app_elf_sha256[i]);
    snprintf(line, sizeof(line),
             "{\"record\":\"session\",\"schema\":3,\"source\":\"energy\",\"run_id\":\"%s\","
             "\"session_id\":\"%s\",\"association_token\":\"%s\",\"clock_hz\":1000000,"
             "\"interval_count\":%" PRIu32 ",\"sync_gpio\":%d,\"alert_gpio\":%d,\"ring_capacity_samples\":%" PRIu32 ",\"calibration_id\":\"empirical_dmm_reference_loads_2026-09-25\","
             "\"calibration_status\":\"empirical_two_load_current_scaling\","
             "\"nominal_shunt_ohms\":0.015,\"effective_shunt_ohms\":0.029,"
             "\"firmware_sha256\":\"%s\",\"acquisition_mode\":\"alert_triggered_bus_shunt\","
             "\"bus_conversion_us\":50,\"shunt_conversion_us\":50,\"averaging\":1,\"i2c_hz\":400000,"
             "\"gap_limit_us\":10000,\"analysis\":\"offline_only\","
             "\"sample_encoding\":\"array_v1\",\"collection_acquisition\":\"paused\","
             "\"sample_fields\":[\"interval_index\",\"sample_index\",\"sequence\",\"timestamp_us\",\"relative_us\","
             "\"bus_v\",\"current_a\",\"power_w\",\"read_duration_us\",\"status_flags\",\"diagnostic_flags\"],"
             "\"sample_record_bytes\":%u,\"ring_allocated_bytes\":%u,\"ring_target_bytes\":%u,"
             "\"psram_total_bytes\":%u,\"psram_reserve_bytes\":%u,\"retained_span_us\":%" PRId64 "}",
             runId, sessionId, associationTokenRequested, claimedCount,
             CONFIG_PQC_ENERGY_SYNC_GPIO, CONFIG_PQC_INA228_ALERT_GPIO, ringCapacity, firmwareHash,
             static_cast<unsigned>(sizeof(energy_sample_record_t)),
             static_cast<unsigned>(ringCapacity * sizeof(energy_sample_record_t)),
             static_cast<unsigned>(kRingBytesTarget), static_cast<unsigned>(psramTotalBytes),
             static_cast<unsigned>(kPsramReserveBytes), retainedSpanUs());
    bool ok = publisher.append(line);
    publisher.intervalCount = claimedCount;

    for (uint32_t intervalIndex = 0; ok && intervalIndex < claimedCount; ++intervalIndex) {
        const energy_interval_record_t &interval = claimed[intervalIndex];
        const auto &a = interval.counters_start;
        const auto &b = interval.counters_end;
        snprintf(line, sizeof(line),
                 "{\"record\":\"interval\",\"interval_index\":%" PRIu32 ",\"interval_sequence\":%" PRIu64 ","
                 "\"start_sample_sequence\":%" PRIu64 ",\"end_sample_sequence\":%" PRIu64 ","
                 "\"e0_us\":%" PRId64 ",\"e1_us\":%" PRId64 ","
                 "\"stm32_boundary_source\":\"stm32.energy_boundary\",\"run_association\":\"collector_token\","
                 "\"i2c_errors\":%" PRIu32 ",\"alert_timeouts\":%" PRIu32 ",\"coalesced_alerts\":%" PRIu32 ","
                 "\"timing_errors\":%" PRIu32 ",\"saturation_errors\":%" PRIu32 ",\"sample_gaps\":%" PRIu32 ",\"sync_queue_drops\":%" PRIu32 "}",
                 intervalIndex, interval.interval_sequence, interval.start_sample_sequence,
                 interval.end_sample_sequence, interval.start_timestamp_us, interval.end_timestamp_us,
                 b.i2c_errors - a.i2c_errors, b.alert_timeouts - a.alert_timeouts,
                 b.coalesced_alerts - a.coalesced_alerts, b.timing_errors - a.timing_errors,
                 b.saturation_errors - a.saturation_errors, b.sample_gaps - a.sample_gaps,
                 interval.sync_drops_end - interval.sync_drops_start);
        ok = publisher.append(line);
        uint32_t sampleIndex = 0;
        for (uint64_t seq = interval.start_sample_sequence; ok && seq <= interval.end_sample_sequence; ++seq) {
            energy_sample_record_t sample = {};
            if (!copySampleBySequence(seq, &sample)) {
                publishRunFailure(runId, "sample_unavailable", seq);
                ok = false;
                break;
            }
            snprintf(line, sizeof(line),
                     "[%" PRIu32 ",%" PRIu32 ",%" PRIu64 ",%" PRId64 ",%" PRId64
                     ",%.9g,%.9g,%.9g,%" PRIu32 ",%" PRIu32 ",%u]",
                     intervalIndex, sampleIndex++, sample.sequence, sample.timestamp_us,
                     sample.timestamp_us - interval.start_timestamp_us,
                     static_cast<double>(sample.bus_v), static_cast<double>(sample.current_a),
                     static_cast<double>(sample.power_w), sample.read_duration_us,
                     sample.status_flags, sample.diagnostic_flags);
            ok = publisher.append(line);
            publisher.sampleCount++;
        }
    }

    if (ok)
        ok = publisher.finish();

    if (xSemaphoreTake(stateMutex, portMAX_DELAY) == pdTRUE) {
        if (ok) {
            for (uint32_t c = 0; c < claimedCount; ++c) {
                for (uint32_t i = 0; i < intervalCount; ++i) {
                    const uint32_t index = (intervalWriteIndex + kMaxIntervals - intervalCount + i) % kMaxIntervals;
                    if (intervals[index].interval_sequence == claimed[c].interval_sequence)
                        intervals[index].claimed = true;
                }
            }
        }
        state.lastPublishOk = ok;
        state.publishing = false;
        xSemaphoreGive(stateMutex);
    }
    if (ok) {
        ESP_LOGI(TAG, "Energy evidence publication complete for run_id=%s intervals=%" PRIu32,
                 runId, claimedCount);
    } else {
        ESP_LOGW(TAG, "Energy evidence publication failed for run_id=%s", runId);
        publishRunFailure(runId, collectionCancelled ? "collection_cancelled" :
                          (esp_timer_get_time() - collectionStartedUs >= kCollectionLimitUs ?
                           "collection_timeout" : "publication_failed"), 0);
    }
    return ok;
}

bool publishClaimedIntervals(const char *runId, const char *token, uint32_t expected)
{
    if (stateMutex == nullptr || !validAssociationToken(token, strlen(token))) return false;
    xSemaphoreTake(stateMutex, portMAX_DELAY);
    const bool active = intervalActive || physicalIntervalActive || state.publishing || gpio_get_level(kSyncGpio) != 0;
    xSemaphoreGive(stateMutex);
    if (active) { publishRunFailure(runId, "interval_active", 0); return false; }
    // Do not pause between handshakes: only the post-run collect enters here.
    // Allow a trailing sample after the last falling edge before freezing.
    const TickType_t started = xTaskGetTickCount();
    for (;;) {
        bool trailing = true;
        xSemaphoreTake(stateMutex, portMAX_DELAY);
        for (uint32_t i = 0; i < intervalCount; ++i) {
            const auto &r = intervals[(intervalWriteIndex + kMaxIntervals - intervalCount + i) % kMaxIntervals];
            if (r.complete && !r.claimed && r.association_valid && strcmp(r.association_token, token) == 0 &&
                (ringCount == 0 || sampleRing[(ringWriteIndex + ringCapacity - 1) % ringCapacity].timestamp_us < r.end_timestamp_us))
                trailing = false;
        }
        xSemaphoreGive(stateMutex);
        if (trailing) break;
        if (xTaskGetTickCount() - started >= pdMS_TO_TICKS(2000)) {
            publishRunFailure(runId, "trailing_sample_unavailable", 0); return false;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    struct ResumeAcquisition { ~ResumeAcquisition() { pqc_ina228_sparkfun_resume(); } } resume;
    if (!pqc_ina228_sparkfun_pause(2000)) {
        publishRunFailure(runId, "acquisition_pause_timeout", 0); return false;
    }
    collectionStartedUs = esp_timer_get_time();
    return publishClaimedIntervalsPaused(runId, token, expected);
}

void handleCollect(const char *payload, size_t length)
{
    std::string json(payload, length);
    cJSON *root = cJSON_Parse(json.c_str());
    if (root == nullptr)
        return;
    cJSON *runId = cJSON_GetObjectItemCaseSensitive(root, "run_id");
    cJSON *source = cJSON_GetObjectItemCaseSensitive(root, "source");
    cJSON *expected = cJSON_GetObjectItemCaseSensitive(root, "expected_intervals");
    cJSON *association = cJSON_GetObjectItemCaseSensitive(root, "association_token");
    if (!cJSON_IsString(runId) || runId->valuestring == nullptr || runId->valuestring[0] == '\0' ||
        !cJSON_IsString(association) || association->valuestring == nullptr ||
        !validAssociationToken(association->valuestring, strlen(association->valuestring)) ||
        (cJSON_IsString(source) && strcmp(source->valuestring, kSource) != 0)) {
        if (cJSON_IsString(runId) && runId->valuestring != nullptr)
            publishRunFailure(runId->valuestring, "association_missing_or_invalid", 0);
        cJSON_Delete(root);
        return;
    }
    if (strlen(runId->valuestring) >= 80 ||
        strspn(runId->valuestring, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-") != strlen(runId->valuestring) ||
        !cJSON_IsNumber(expected) || expected->valuedouble < 1 || expected->valuedouble > 32 ||
        expected->valuedouble != static_cast<uint32_t>(expected->valuedouble)) {
        cJSON_Delete(root);
        return;
    }
    const uint32_t expectedIntervals = static_cast<uint32_t>(expected->valuedouble);
    publishClaimedIntervals(runId->valuestring, association->valuestring, expectedIntervals);
    cJSON_Delete(root);
}

enum class WorkerCommandType : uint8_t {
    PublishReadyStatus,
    Collect,
};

struct WorkerCommand {
    WorkerCommandType type = WorkerCommandType::PublishReadyStatus;
    size_t payloadLength = 0;
    char payload[kCommandPayloadBytes] = {};
};

bool enqueueWorkerCommand(const WorkerCommand &command)
{
    if (commandQueue == nullptr)
        return false;
    if (xQueueSend(commandQueue, &command, 0) != pdTRUE) {
        ESP_LOGW(TAG, "Energy MQTT worker queue full; command dropped");
        return false;
    }
    return true;
}

void commandWorker(void *)
{
    WorkerCommand command = {};
    for (;;) {
        if (xQueueReceive(commandQueue, &command, portMAX_DELAY) != pdTRUE)
            continue;
        switch (command.type) {
            case WorkerCommandType::PublishReadyStatus: {
                const TickType_t started = xTaskGetTickCount();
                pqc_ina228_snapshot_t sensor = {};
                bool ready = false;
                do {
                    pqc_ina228_sparkfun_snapshot(&sensor);
                    ready = sensor.online && sensor.valid && !sensor.paused && ringCapacity >= 2 &&
                        intervals != nullptr && esp_timer_get_time() - sensor.timestamp_us < 100000;
                    if (ready) break;
                    vTaskDelay(pdMS_TO_TICKS(10));
                } while (xTaskGetTickCount() - started < pdMS_TO_TICKS(2000));
                publishStatus(ready ? "ready" : "sensor_unavailable", nullptr);
                break;
            }
            case WorkerCommandType::Collect:
                ESP_LOGI(TAG,
                         "Energy collect worker start: stack_high_water=%u bytes",
                         static_cast<unsigned>(uxTaskGetStackHighWaterMark(nullptr)));
                if (!collectionCancelled) handleCollect(command.payload, command.payloadLength);
                xSemaphoreTake(stateMutex, portMAX_DELAY);
                collectPending = false;
                xSemaphoreGive(stateMutex);
                ESP_LOGI(TAG,
                         "Energy collect worker done: stack_high_water=%u bytes",
                         static_cast<unsigned>(uxTaskGetStackHighWaterMark(nullptr)));
                break;
        }
    }
}

void mqttEventHandler(void *, esp_event_base_t, int32_t eventId, void *eventData)
{
    auto *event = static_cast<esp_mqtt_event_handle_t>(eventData);
    switch (static_cast<esp_mqtt_event_id_t>(eventId)) {
        case MQTT_EVENT_CONNECTED: {
            if (xSemaphoreTake(stateMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
                state.mqttConnected = true;
                xSemaphoreGive(stateMutex);
            }
            esp_mqtt_client_subscribe(mqttClient, kCollectTopic, 1);
            esp_mqtt_client_subscribe(mqttClient, kAssociateTopic, 1);
            WorkerCommand command = {};
            command.type = WorkerCommandType::PublishReadyStatus;
            (void)enqueueWorkerCommand(command);
            ESP_LOGI(TAG, "Connected to reporting MQTT broker; acquisition remained continuous while offline");
            break;
        }
        case MQTT_EVENT_DISCONNECTED:
            collectionCancelled = true;
            if (xSemaphoreTake(stateMutex, portMAX_DELAY) == pdTRUE) {
                state.mqttConnected = false;
                portENTER_CRITICAL(&syncDiagnosticMux);
                associationTokenValid = false;
                portEXIT_CRITICAL(&syncDiagnosticMux);
                xSemaphoreGive(stateMutex);
            }
            ESP_LOGW(TAG, "Reporting MQTT disconnected; continuous acquisition continues");
            break;
        case MQTT_EVENT_PUBLISHED:
            if (publishAckQueue != nullptr) {
                const int messageId = event->msg_id;
                if (xQueueSend(publishAckQueue, &messageId, 0) != pdTRUE) {
                    ESP_LOGW(TAG,
                             "Energy MQTT PUBACK queue full; dropping acknowledgement message_id=%d",
                             messageId);
                }
            }
            break;
        case MQTT_EVENT_DATA:
            if (event->topic_len == static_cast<int>(strlen(kAssociateTopic)) &&
                memcmp(event->topic, kAssociateTopic, strlen(kAssociateTopic)) == 0) {
                if (event->current_data_offset != 0 || event->data_len != event->total_data_len) {
                    ESP_LOGW(TAG, "Ignoring fragmented energy association token (%d/%d bytes)",
                             event->data_len, event->total_data_len);
                    break;
                }
                recordAssociationToken(event->data, static_cast<size_t>(event->data_len));
                if (event->data_len > 0) {
                    WorkerCommand command = {};
                    command.type = WorkerCommandType::PublishReadyStatus;
                    (void)enqueueWorkerCommand(command);
                }
                break;
            }
            if (event->topic_len == static_cast<int>(strlen(kCollectTopic)) &&
                memcmp(event->topic, kCollectTopic, strlen(kCollectTopic)) == 0) {
                if (event->current_data_offset != 0 || event->data_len != event->total_data_len) {
                    ESP_LOGW(TAG, "Ignoring fragmented energy collect command (%d/%d bytes)",
                             event->data_len, event->total_data_len);
                    break;
                }
                if (event->data_len == 0) { collectionCancelled = true; break; }
                if (event->data_len < 0 || static_cast<size_t>(event->data_len) >= kCommandPayloadBytes) {
                    ESP_LOGW(TAG, "Ignoring oversized energy collect command: %d bytes", event->data_len);
                    break;
                }
                xSemaphoreTake(stateMutex, portMAX_DELAY);
                if (collectPending) { xSemaphoreGive(stateMutex); break; }
                collectPending = true;
                collectionCancelled = false;
                xSemaphoreGive(stateMutex);
                WorkerCommand command = {};
                command.type = WorkerCommandType::Collect;
                command.payloadLength = static_cast<size_t>(event->data_len);
                memcpy(command.payload, event->data, command.payloadLength);
                command.payload[command.payloadLength] = '\0';
                if (!enqueueWorkerCommand(command)) {
                    xSemaphoreTake(stateMutex, portMAX_DELAY);
                    collectPending = false;
                    xSemaphoreGive(stateMutex);
                }
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
    out->mqtt_connected = state.mqttConnected;
    out->publishing = state.publishing;
    out->last_publish_ok = state.lastPublishOk;
    out->ring_ready = sampleRing != nullptr;
    out->ring_overflowed = ringOverflowed;
    out->interval_active = intervalActive;
    strlcpy(out->run_id, state.lastRunId, sizeof(out->run_id));
    out->ring_capacity_samples = ringCapacity;
    out->ring_used_samples = ringCount;
    out->oldest_sequence = oldestSequence;
    out->newest_sequence = newestSequence;
    out->completed_interval_count = intervalCount;
    uint32_t unclaimed = 0;
    for (uint32_t i = 0; i < intervalCount; ++i) {
        const uint32_t index = (intervalWriteIndex + kMaxIntervals - intervalCount + i) % kMaxIntervals;
        if (intervals[index].complete && !intervals[index].claimed && !intervals[index].discarded)
            unclaimed++;
    }
    out->unclaimed_interval_count = unclaimed;
    out->sync_processed_rising = syncProcessedRising;
    out->sync_processed_falling = syncProcessedFalling;
    out->sync_unexpected_rising = syncUnexpectedRising;
    out->sync_orphan_falling = syncOrphanFalling;
    out->completed_interval_count = state.completedIntervals;
    portENTER_CRITICAL(&syncDiagnosticMux);
    out->sync_isr_edges = syncIsrEdges;
    out->sync_queue_drops = syncQueueDrops;
    portEXIT_CRITICAL(&syncDiagnosticMux);
    xSemaphoreGive(stateMutex);
}

extern "C" void pqc_energy_session_start(void)
{
    uint8_t identity[16];
    esp_fill_random(identity, sizeof(identity));
    for (size_t i = 0; i < sizeof(identity); ++i)
        snprintf(sessionId + 2 * i, 3, "%02x", identity[i]);
    stateMutex = xSemaphoreCreateMutex();
    configASSERT(stateMutex != nullptr);

    commandQueue = xQueueCreate(kCommandQueueLength, sizeof(WorkerCommand));
    configASSERT(commandQueue != nullptr);
    publishAckQueue = xQueueCreate(kPublishAckQueueLength, sizeof(int));
    configASSERT(publishAckQueue != nullptr);
    const BaseType_t workerCreated = xTaskCreate(
        commandWorker, "energy_mqtt_worker", CONFIG_PQC_ENERGY_WORKER_STACK_BYTES, nullptr, 5, &commandWorkerTask);
    configASSERT(workerCreated == pdPASS);

    /*
     * Interval descriptors are persistent appliance metadata and can be large:
     * each descriptor carries the per-run association token. Keeping 1024 of
     * them as a static array consumed roughly 33 KiB of scarce internal DRAM
     * and prevented ESP-MQTT from creating its transport task. Store them in
     * PSRAM beside the sample ring instead.
     */
    intervals = static_cast<energy_interval_record_t *>(
        heap_caps_calloc(kMaxIntervals, sizeof(energy_interval_record_t),
                         MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (intervals == nullptr) {
        ESP_LOGE(TAG,
                 "Failed to allocate PSRAM interval descriptors: count=%" PRIu32
                 " bytes=%u; GPIO interval capture disabled",
                 kMaxIntervals,
                 static_cast<unsigned>(kMaxIntervals * sizeof(energy_interval_record_t)));
    } else {
        ESP_LOGI(TAG,
                 "Energy interval descriptors allocated in PSRAM: count=%" PRIu32
                 " bytes=%u",
                 kMaxIntervals,
                 static_cast<unsigned>(kMaxIntervals * sizeof(energy_interval_record_t)));
    }

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
    if (sampleRing == nullptr) ringCapacity = 0;
    ESP_LOGI(TAG, "Energy PSRAM ring: allocated=%u bytes samples=%" PRIu32 " reserve=%u bytes",
             static_cast<unsigned>(ringCapacity * sizeof(energy_sample_record_t)), ringCapacity,
             static_cast<unsigned>(kPsramReserveBytes));

    pqc_ina228_sparkfun_set_sample_callback(storeSensorSample);
    if (intervals != nullptr)
        configureSyncGpio();

    char uri[192];
    snprintf(uri, sizeof(uri), "mqtt://%s:%d", CONFIG_PQC_ENERGY_REPORTING_HOST, CONFIG_PQC_ENERGY_REPORTING_PORT);
    esp_mqtt_client_config_t config = {};
    config.broker.address.uri = uri;
    config.credentials.client_id = CONFIG_PQC_ENERGY_MQTT_CLIENT_ID;
    config.network.reconnect_timeout_ms = 3000;
    config.task.stack_size = CONFIG_PQC_ENERGY_MQTT_STACK_BYTES;
    config.buffer.size = 1024;
    config.buffer.out_size = 8192; // one complete base64 chunk plus MQTT envelope/topic
    config.network.timeout_ms = 5000;
    mqttClient = esp_mqtt_client_init(&config);
    configASSERT(mqttClient != nullptr);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(
        mqttClient, static_cast<esp_mqtt_event_id_t>(ESP_EVENT_ANY_ID), mqttEventHandler, nullptr));
    const esp_err_t mqttStartRc = esp_mqtt_client_start(mqttClient);
    if (mqttStartRc != ESP_OK) {
        ESP_LOGE(TAG,
                 "Failed to start reporting MQTT client: rc=%s (0x%x); "
                 "continuous INA228 acquisition remains active",
                 esp_err_to_name(mqttStartRc), static_cast<unsigned>(mqttStartRc));
    }
}
