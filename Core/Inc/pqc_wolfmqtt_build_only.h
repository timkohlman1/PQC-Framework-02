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
    bool broker_connected;
    bool tls_handshake_complete;
    bool publish_complete;
    bool reconnect_complete;
} PQC_WolfMQTTBuildOnlyStatus;

int PQC_WolfMQTT_BuildOnly_Initialize(
    PQC_WolfMQTTBackend backend,
    PQC_WolfMQTTBuildOnlyStatus *status
);

const char *PQC_WolfMQTT_BackendName(PQC_WolfMQTTBackend backend);

#ifdef __cplusplus
}
#endif

#endif
