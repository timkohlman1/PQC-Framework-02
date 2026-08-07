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

int PQC_WolfMQTT_BuildOnly_Initialize(
    PQC_WolfMQTTBackend backend,
    PQC_WolfMQTTBuildOnlyStatus *status
);

void PQC_WolfMQTT_DiagnosticMarker(const char *marker);

int PQC_WolfMQTT_RunPlaintextExchange(PQC_WolfMQTTBuildOnlyStatus *status);

int PQC_WolfMQTT_RunReadyMetricsApplication(void (*mark_complete)(void));

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
