#ifndef PQC_WOLFMQTT_BUILD_ONLY_H
#define PQC_WOLFMQTT_BUILD_ONLY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK = 0,
    PQC_WOLFMQTT_BACKEND_ST67W61M1 = 1
} PQC_WolfMQTTBackend;

typedef struct
{
    PQC_WolfMQTTBackend backend;
    bool client_initialized;
    bool transport_callbacks_present;
    bool transport_available;
    bool tcp_connected;
    bool mqtt_connected;
    bool subscribed;
    bool message_received;
    bool publish_complete;
    bool tls_handshake_complete;
    bool tls_context_created;
    bool tls_session_created;
    bool tls_peer_identity_configured;
    bool ca_load_attempted;
    bool pqc_group_configured;
    bool ca_loaded;
    bool pqc_group_negotiated;
    bool reconnect_complete;
    int tls_connect_result;
    int tls_error;
    int tls_io_error;
    int last_result;
} PQC_WolfMQTTBuildOnlyStatus;

/* Ready Metrics 2 stores research timing in microseconds from the dedicated
 * 1 MHz application timebase. Millisecond compatibility fields are derived
 * only when serializing legacy output; HAL/FreeRTOS ticks remain OS timing. */
typedef struct
{
    uint32_t schema_version;
    uint64_t tcp_connect_start_us;
    uint64_t tcp_connected_us;
    uint64_t tls_complete_us;
    uint64_t mqtt_readiness_checkpoint_us;
    uint64_t mqtt_connected_us;
    uint64_t application_request_us;
    uint64_t application_first_byte_us;
    uint64_t application_last_byte_us;
    uint64_t ready_published_us;
    uint64_t measurement_complete_us;
    uint64_t tcp_connect_us;
    uint64_t mqtt_readiness_us;
    uint64_t mqtt_connect_us;
    uint64_t rtfb_us;
    uint64_t rtlb_us;
    uint64_t ttfb_us;
    uint64_t ttlb_us;
    uint64_t req_tfb_us;
    uint64_t req_tlb_us;
    uint64_t application_transfer_us;
    uint64_t legacy_connect_timing_us;
    uint64_t reset_to_tcp_connect_us;
    uint64_t reset_to_tls_complete_us;
    uint64_t reset_to_mqtt_readiness_us;
    uint64_t reset_to_mqtt_connected_us;
    uint64_t reset_to_ready_publish_us;
    uint32_t transfer_payload_bytes;
    uint32_t transfer_received_bytes;
    uint32_t transfer_message_count;
    uint32_t transfer_chunk_bytes;
    uint8_t reset_origin_valid;
    uint8_t tcp_timing_valid;
    uint8_t tls_timing_valid;
    uint8_t mqtt_readiness_valid;
    uint8_t mqtt_connected_valid;
    uint8_t application_first_byte_valid;
    uint8_t application_last_byte_valid;
    uint8_t transfer_complete_valid;
    uint8_t ready_publish_valid;
} PQC_WolfMQTTReadyMetrics2Snapshot;

int PQC_WolfMQTT_BuildOnly_Initialize(
    PQC_WolfMQTTBackend backend,
    PQC_WolfMQTTBuildOnlyStatus *status
);

void PQC_WolfMQTT_DiagnosticMarker(const char *marker);

int PQC_WolfMQTT_RunPlaintextExchange(PQC_WolfMQTTBuildOnlyStatus *status);

int PQC_WolfMQTT_RunReadyMetricsApplication(void (*mark_complete)(void));

int PQC_WolfMQTT_RunReadyMetrics2Application(void (*mark_complete)(void));

int PQC_WolfMQTT_PublishDeferredResults(
    const uint8_t *data,
    size_t length,
    const char *logical_sha256,
    uint32_t record_count,
    uint32_t dropped_record_count,
    bool overflowed);

#ifndef PQC_OTA_ENABLED
#define PQC_OTA_ENABLED 0
#endif

#if PQC_OTA_ENABLED
#define PQC_OTA_SCHEMA_VERSION 1U
#define PQC_OTA_FLAG_BOOTLOADER_MIGRATION 0x00000001UL

typedef struct
{
    uint32_t schema_version;
    uint32_t flags;
    uint32_t active_physical_bank;
    uint32_t inactive_physical_bank;
    uint32_t expected_bootloader_bytes;
    uint32_t expected_manifest_bytes;
    uint32_t expected_application_bytes;
    uint32_t received_bootloader_bytes;
    uint32_t received_manifest_bytes;
    uint32_t received_application_bytes;
    uint8_t staged_hashes_valid;
    uint8_t activation_requested;
} PQC_OtaStatus;

/* OTA transport is carried only on the impairment-exempt plaintext reporting
 * broker. The service consumes retained, bounded chunks after deferred result
 * publication, verifies complete-bank hashes, and only then resets for wolfBoot
 * candidate-bank authentication/activation. */
int PQC_WolfMQTT_ServiceRetainedOta(PQC_OtaStatus *status);
#endif /* PQC_OTA_ENABLED */

const PQC_WolfMQTTReadyMetrics2Snapshot *PQC_WolfMQTT_ReadyMetrics2Snapshot(void);

const char *PQC_WolfMQTT_BackendName(PQC_WolfMQTTBackend backend);

bool PQC_WolfMQTT_RuntimeStatusLine(
    char *buffer,
    size_t buffer_size,
    const char *context,
    bool scheduler_running
);

#ifdef __cplusplus
}
#endif

#endif
