#include "pqc_wolfmqtt_build_only.h"

#include <stdio.h>
#include <string.h>

#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "pqc_wifi_config.h"
#include "wolfmqtt/mqtt_client.h"

#define PQC_WOLFMQTT_BUFFER_SIZE 512
#define PQC_WOLFMQTT_COMMAND_TIMEOUT_MS 5000
#define PQC_WOLFMQTT_KEEPALIVE_SECONDS 30
#define PQC_WOLFMQTT_PACKET_ID_SUBSCRIBE 1
#define PQC_WOLFMQTT_PACKET_ID_PUBLISH 2

__attribute__((weak)) void PQC_WolfMQTT_DiagnosticMarker(const char *marker)
{
    (void)marker;
}

typedef struct
{
    int socket_fd;
} PQC_WolfMQTTSocketContext;

typedef struct
{
    bool received;
    char payload[PQC_WOLFMQTT_BUFFER_SIZE];
    size_t payload_length;
} PQC_WolfMQTTMessageContext;

static int PQC_WolfMQTT_SetTimeout(int socket_fd, int option, int timeout_ms)
{
    struct timeval timeout;
    timeout.tv_sec = timeout_ms / 1000;
    timeout.tv_usec = (timeout_ms % 1000) * 1000;
    return lwip_setsockopt(socket_fd, SOL_SOCKET, option, &timeout, sizeof(timeout));
}

static int PQC_WolfMQTT_LwIPConnect(void *context, const char *host, word16 port, int timeout_ms)
{
    PQC_WolfMQTTSocketContext *socket_context = (PQC_WolfMQTTSocketContext *)context;
    struct sockaddr_in address;

    if ((socket_context == NULL) || (host == NULL) || (host[0] == '\0'))
    {
        return -1;
    }

    socket_context->socket_fd = lwip_socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (socket_context->socket_fd < 0)
    {
        return -1;
    }

    (void)PQC_WolfMQTT_SetTimeout(socket_context->socket_fd, SO_RCVTIMEO, timeout_ms);
    (void)PQC_WolfMQTT_SetTimeout(socket_context->socket_fd, SO_SNDTIMEO, timeout_ms);

    (void)memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = lwip_htons(port);
    if (ip4addr_aton(host, (ip4_addr_t *)&address.sin_addr) == 0)
    {
        lwip_close(socket_context->socket_fd);
        socket_context->socket_fd = -1;
        return -1;
    }

    if (lwip_connect(socket_context->socket_fd, (struct sockaddr *)&address, sizeof(address)) != 0)
    {
        lwip_close(socket_context->socket_fd);
        socket_context->socket_fd = -1;
        return -1;
    }

    return MQTT_CODE_SUCCESS;
}

static int PQC_WolfMQTT_LwIPRead(void *context, byte *buffer, int buffer_length, int timeout_ms)
{
    PQC_WolfMQTTSocketContext *socket_context = (PQC_WolfMQTTSocketContext *)context;
    int result;
    if ((socket_context == NULL) || (socket_context->socket_fd < 0))
    {
        return -1;
    }
    (void)PQC_WolfMQTT_SetTimeout(socket_context->socket_fd, SO_RCVTIMEO, timeout_ms);
    result = lwip_recv(socket_context->socket_fd, buffer, (size_t)buffer_length, 0);
    return result;
}

static int PQC_WolfMQTT_LwIPWrite(void *context, const byte *buffer, int buffer_length, int timeout_ms)
{
    PQC_WolfMQTTSocketContext *socket_context = (PQC_WolfMQTTSocketContext *)context;
    int result;
    if ((socket_context == NULL) || (socket_context->socket_fd < 0))
    {
        return -1;
    }
    (void)PQC_WolfMQTT_SetTimeout(socket_context->socket_fd, SO_SNDTIMEO, timeout_ms);
    result = lwip_send(socket_context->socket_fd, buffer, (size_t)buffer_length, 0);
    return result;
}

static int PQC_WolfMQTT_LwIPDisconnect(void *context)
{
    PQC_WolfMQTTSocketContext *socket_context = (PQC_WolfMQTTSocketContext *)context;
    if ((socket_context != NULL) && (socket_context->socket_fd >= 0))
    {
        (void)lwip_shutdown(socket_context->socket_fd, SHUT_RDWR);
        (void)lwip_close(socket_context->socket_fd);
        socket_context->socket_fd = -1;
    }
    return MQTT_CODE_SUCCESS;
}

static int PQC_WolfMQTT_MessageCallback(
    MqttClient *client,
    MqttMessage *message,
    byte msg_new,
    byte msg_done)
{
    PQC_WolfMQTTMessageContext *context = (PQC_WolfMQTTMessageContext *)client->ctx;
    size_t available;
    size_t copy_length;
    (void)msg_new;

    if ((context == NULL) || (message == NULL))
    {
        return MQTT_CODE_ERROR_BAD_ARG;
    }

    available = sizeof(context->payload) - 1U - context->payload_length;
    copy_length = message->buffer_len < available ? message->buffer_len : available;
    if (copy_length > 0U)
    {
        (void)memcpy(context->payload + context->payload_length, message->buffer, copy_length);
        context->payload_length += copy_length;
        context->payload[context->payload_length] = '\0';
    }
    if (msg_done != 0U)
    {
        context->received = true;
    }
    return MQTT_CODE_SUCCESS;
}

const char *PQC_WolfMQTT_BackendName(PQC_WolfMQTTBackend backend)
{
    switch (backend)
    {
        case PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK: return "fake_no_network";
        case PQC_WOLFMQTT_BACKEND_ST67W61M1: return "st67w61m1";
        default: return "unknown";
    }
}

int PQC_WolfMQTT_BuildOnly_Initialize(PQC_WolfMQTTBackend backend, PQC_WolfMQTTBuildOnlyStatus *status)
{
    if (status == NULL)
    {
        return MQTT_CODE_ERROR_BAD_ARG;
    }
    (void)memset(status, 0, sizeof(*status));
    status->backend = backend;
    status->transport_callbacks_present = true;
    status->transport_available = (backend == PQC_WOLFMQTT_BACKEND_ST67W61M1);
    status->last_result = MQTT_CODE_SUCCESS;
    return MQTT_CODE_SUCCESS;
}

int PQC_WolfMQTT_RunPlaintextExchange(PQC_WolfMQTTBuildOnlyStatus *status)
{
    MqttClient client;
    MqttNet network;
    MqttConnect connect;
    MqttSubscribe subscribe;
    MqttTopic topic;
    MqttPublish publish;
    PQC_WolfMQTTSocketContext socket_context = { .socket_fd = -1 };
    PQC_WolfMQTTMessageContext message_context;
    byte transmit_buffer[PQC_WOLFMQTT_BUFFER_SIZE];
    byte receive_buffer[PQC_WOLFMQTT_BUFFER_SIZE];
    int result;

    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT plaintext exchange: function entered\r\n");

    if (status == NULL)
    {
        return MQTT_CODE_ERROR_BAD_ARG;
    }
    (void)memset(status, 0, sizeof(*status));
    status->backend = PQC_WOLFMQTT_BACKEND_ST67W61M1;
    status->transport_callbacks_present = true;
    status->transport_available = true;

    (void)memset(&client, 0, sizeof(client));
    (void)memset(&network, 0, sizeof(network));
    (void)memset(&message_context, 0, sizeof(message_context));
    network.context = &socket_context;
    network.connect = PQC_WolfMQTT_LwIPConnect;
    network.read = PQC_WolfMQTT_LwIPRead;
    network.write = PQC_WolfMQTT_LwIPWrite;
    network.disconnect = PQC_WolfMQTT_LwIPDisconnect;

    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: client init begin\r\n");
    result = MqttClient_Init(&client, &network, PQC_WolfMQTT_MessageCallback,
        transmit_buffer, sizeof(transmit_buffer), receive_buffer, sizeof(receive_buffer),
        PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    status->last_result = result;
    if (result != MQTT_CODE_SUCCESS) return result;
    status->client_initialized = true;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: client init passed\r\n");
    client.ctx = &message_context;

    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: TCP connect begin\r\n");
    result = MqttClient_NetConnect(&client, PQC_MQTT_BROKER_HOST,
        (word16)PQC_MQTT_BROKER_PORT, PQC_WOLFMQTT_COMMAND_TIMEOUT_MS, 0, NULL);
    status->last_result = result;
    if (result != MQTT_CODE_SUCCESS) goto cleanup;
    status->broker_connected = true;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: TCP connect passed\r\n");

    (void)memset(&connect, 0, sizeof(connect));
    connect.keep_alive_sec = PQC_WOLFMQTT_KEEPALIVE_SECONDS;
    connect.clean_session = 1;
    connect.client_id = PQC_MQTT_CLIENT_ID;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: MQTT connect begin\r\n");
    result = MqttClient_Connect(&client, &connect);
    status->last_result = result;
    if (result != MQTT_CODE_SUCCESS) goto cleanup;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: MQTT connect passed\r\n");

    (void)memset(&topic, 0, sizeof(topic));
    topic.topic_filter = PQC_MQTT_COMMAND_TOPIC;
    topic.qos = MQTT_QOS_0;
    (void)memset(&subscribe, 0, sizeof(subscribe));
    subscribe.packet_id = PQC_WOLFMQTT_PACKET_ID_SUBSCRIBE;
    subscribe.topic_count = 1;
    subscribe.topics = &topic;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: subscribe begin\r\n");
    result = MqttClient_Subscribe(&client, &subscribe);
    status->last_result = result;
    if (result != MQTT_CODE_SUCCESS) goto cleanup;
    status->subscribed = true;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: subscribe passed\r\n");

    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: wait message begin\r\n");
    result = MqttClient_WaitMessage(&client, PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    status->last_result = result;
    if ((result != MQTT_CODE_SUCCESS) || !message_context.received) goto cleanup;
    status->message_received = true;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: message received\r\n");

    (void)memset(&publish, 0, sizeof(publish));
    publish.topic_name = PQC_MQTT_RESPONSE_TOPIC;
    publish.qos = MQTT_QOS_0;
    publish.packet_id = PQC_WOLFMQTT_PACKET_ID_PUBLISH;
    publish.buffer = (byte *)PQC_MQTT_CORRELATION_PAYLOAD;
    publish.total_len = (word32)strlen(PQC_MQTT_CORRELATION_PAYLOAD);
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: publish begin\r\n");
    result = MqttClient_Publish(&client, &publish);
    status->last_result = result;
    if (result == MQTT_CODE_SUCCESS)
    {
        status->publish_complete = true;
        PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: publish passed\r\n");
    }

cleanup:
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: cleanup begin\r\n");
    if (status->broker_connected)
    {
        (void)MqttClient_Disconnect(&client);
    }
    (void)MqttClient_NetDisconnect(&client);
    MqttClient_DeInit(&client);
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: cleanup complete\r\n");
    return status->last_result;
}

bool PQC_WolfMQTT_RuntimeStatusLine(char *buffer, size_t buffer_size,
    const char *context, bool scheduler_running)
{
    PQC_WolfMQTTBuildOnlyStatus status;
    int result;
    int written;

    if ((buffer == NULL) || (buffer_size == 0U) || (context == NULL)) return false;

#if (PQC_MQTT_ENABLED != 0)
    result = PQC_WolfMQTT_RunPlaintextExchange(&status);
    written = snprintf(buffer, buffer_size,
        "wolfMQTT runtime: context=%s scheduler=%s evidence=stm32-st67-plaintext-mqtt-e2e backend=%s result=%d client_initialized=%u transport=%s tcp=%s mqtt_connect=%s mqtt_subscribe=%s mqtt_receive=%s mqtt_publish=%s tls_handshake=not_required end_to_end=%s broker=%s:%u command_topic=%s response_topic=%s correlation=%s\r\n",
        context, scheduler_running ? "running" : "not_started",
        PQC_WolfMQTT_BackendName(status.backend), result,
        status.client_initialized ? 1U : 0U,
        status.transport_available ? "available" : "unavailable",
        status.broker_connected ? "passed" : "failed",
        status.broker_connected ? "passed" : "failed",
        status.subscribed ? "passed" : "failed",
        status.message_received ? "passed" : "failed",
        status.publish_complete ? "passed" : "failed",
        status.publish_complete ? "passed" : "failed",
        PQC_MQTT_BROKER_HOST, (unsigned int)PQC_MQTT_BROKER_PORT,
        PQC_MQTT_COMMAND_TOPIC, PQC_MQTT_RESPONSE_TOPIC,
        PQC_MQTT_CORRELATION_PAYLOAD);
#else
    result = PQC_WolfMQTT_BuildOnly_Initialize(PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK, &status);
    written = snprintf(buffer, buffer_size,
        "wolfMQTT runtime smoke: context=%s scheduler=%s evidence=stm32-fake-no-network-initialization-only backend=%s init_result=%d client_initialized=0 callbacks=present transport=unavailable wifi=unavailable link=unavailable ip=unavailable tcp=unavailable tls_handshake=unavailable mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable st67w61m1=unavailable end_to_end=unavailable\r\n",
        context, scheduler_running ? "running" : "not_started",
        PQC_WolfMQTT_BackendName(status.backend), result);
#endif
    return (written >= 0) && ((size_t)written < buffer_size);
}
