#include "pqc_wolfmqtt_build_only.h"

#include <string.h>

#include "wolfmqtt/mqtt_client.h"

#define PQC_WOLFMQTT_BUFFER_SIZE 128
#define PQC_WOLFMQTT_COMMAND_TIMEOUT_MS 1000

static int PQC_WolfMQTT_UnavailableConnect(
    void *context,
    const char *host,
    word16 port,
    int timeout_ms
)
{
    (void)context;
    (void)host;
    (void)port;
    (void)timeout_ms;
    return -1;
}

static int PQC_WolfMQTT_UnavailableRead(
    void *context,
    byte *buffer,
    int buffer_length,
    int timeout_ms
)
{
    (void)context;
    (void)buffer;
    (void)buffer_length;
    (void)timeout_ms;
    return -1;
}

static int PQC_WolfMQTT_UnavailableWrite(
    void *context,
    const byte *buffer,
    int buffer_length,
    int timeout_ms
)
{
    (void)context;
    (void)buffer;
    (void)buffer_length;
    (void)timeout_ms;
    return -1;
}

static int PQC_WolfMQTT_UnavailableDisconnect(void *context)
{
    (void)context;
    return -1;
}

const char *PQC_WolfMQTT_BackendName(PQC_WolfMQTTBackend backend)
{
    switch (backend)
    {
        case PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK:
            return "fake_no_network";
        case PQC_WOLFMQTT_BACKEND_ST67W61M1:
            return "st67w61m1";
        default:
            return "unknown";
    }
}

int PQC_WolfMQTT_BuildOnly_Initialize(
    PQC_WolfMQTTBackend backend,
    PQC_WolfMQTTBuildOnlyStatus *status
)
{
    MqttClient client;
    MqttNet network;
    byte transmit_buffer[PQC_WOLFMQTT_BUFFER_SIZE];
    byte receive_buffer[PQC_WOLFMQTT_BUFFER_SIZE];
    int result;

    if (status == NULL)
    {
        return -1;
    }

    (void)memset(status, 0, sizeof(*status));
    status->backend = backend;

    if (backend != PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK)
    {
        return -1;
    }

    (void)memset(&client, 0, sizeof(client));
    (void)memset(&network, 0, sizeof(network));
    network.context = NULL;
    network.connect = PQC_WolfMQTT_UnavailableConnect;
    network.read = PQC_WolfMQTT_UnavailableRead;
    network.write = PQC_WolfMQTT_UnavailableWrite;
    network.disconnect = PQC_WolfMQTT_UnavailableDisconnect;

    status->transport_callbacks_present = true;
    status->transport_available = false;

    result = MqttClient_Init(
        &client,
        &network,
        NULL,
        transmit_buffer,
        (int)sizeof(transmit_buffer),
        receive_buffer,
        (int)sizeof(receive_buffer),
        PQC_WOLFMQTT_COMMAND_TIMEOUT_MS
    );

    if (result == MQTT_CODE_SUCCESS)
    {
        status->client_initialized = true;
        MqttClient_DeInit(&client);
    }

    status->broker_connected = false;
    status->tls_handshake_complete = false;
    status->publish_complete = false;
    status->reconnect_complete = false;

    return result;
}
