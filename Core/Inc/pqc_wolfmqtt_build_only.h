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

/* Ready Metrics 2 stores end-to-end application timing in RAM while the
 * benchmark-critical path is active. All fields are HAL/FreeRTOS millisecond
 * ticks or durations derived from those ticks. The firmware boot origin is the
 * first reliable HAL tick captured immediately after HAL_Init(). */
typedef struct
{
    uint32_t schema_version;
    uint32_t firmware_boot_origin_tick_ms;
    uint32_t ttfb_start_tick_ms;
    uint32_t tcp_connected_tick_ms;
    uint32_t tls_complete_tick_ms;
    uint32_t mqtt_first_response_tick_ms;
    uint32_t mqtt_connected_tick_ms;
    uint32_t ready_published_tick_ms;
    uint32_t measurement_complete_tick_ms;
    uint32_t tcp_connect_ms;
    uint32_t ttfb_ms;
    uint32_t mqtt_connect_ms;
    uint32_t firmware_boot_to_tcp_connect_ms;
    uint32_t firmware_boot_to_tls_complete_ms;
    uint32_t firmware_boot_to_mqtt_first_response_ms;
    uint32_t firmware_boot_to_mqtt_connected_ms;
    uint32_t firmware_boot_to_ready_publish_ms;
    uint32_t legacy_connect_timing_ms;
    uint8_t tcp_timing_valid;
    uint8_t tls_timing_valid;
    uint8_t mqtt_first_response_valid;
    uint8_t mqtt_connected_valid;
    uint8_t ready_publish_valid;
} PQC_WolfMQTTReadyMetrics2Snapshot;

int PQC_WolfMQTT_BuildOnly_Initialize(
    PQC_WolfMQTTBackend backend,
    PQC_WolfMQTTBuildOnlyStatus *status
);

void PQC_WolfMQTT_DiagnosticMarker(const char *marker);

int PQC_WolfMQTT_RunPlaintextExchange(PQC_WolfMQTTBuildOnlyStatus *status);

int PQC_WolfMQTT_RunReadyMetricsApplication(void (*mark_complete)(void));

int PQC_WolfMQTT_RunReadyMetrics2Application(
    void (*mark_complete)(void),
    uint32_t firmware_boot_origin_tick_ms);

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
