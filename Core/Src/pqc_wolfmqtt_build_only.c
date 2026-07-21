#include "pqc_wolfmqtt_build_only.h"

#include <stdio.h>
#include <string.h>

#include "main.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"
#include "pqc_wifi_config.h"

/* wolfSSL uses RNG as a legacy type alias. STM32 CMSIS uses the same name
 * for the hardware peripheral pointer. Drop the CMSIS macro before wolfSSL
 * headers and address the peripheral explicitly through RNG_BASE below. */
#ifdef RNG
#undef RNG
#endif

#include "wolfmqtt/mqtt_client.h"
#include "wolfssl/ssl.h"
#include "wolfssl/wolfcrypt/random.h"

#define PQC_WOLFMQTT_BUFFER_SIZE 512
#define PQC_WOLFMQTT_COMMAND_TIMEOUT_MS 5000
#define PQC_WOLFMQTT_KEEPALIVE_SECONDS 30
#define PQC_WOLFMQTT_PACKET_ID_SUBSCRIBE 1
#define PQC_WOLFMQTT_PACKET_ID_PUBLISH 2

__attribute__((weak)) void PQC_WolfMQTT_DiagnosticMarker(const char *marker) { (void)marker; }

typedef struct {
    int socket_fd;
    WOLFSSL_CTX *tls_ctx;
    WOLFSSL *tls;
    bool tls_requested;
    bool tls_handshake_complete;
} PQC_WolfMQTTSocketContext;

typedef struct {
    bool received;
    char payload[PQC_WOLFMQTT_BUFFER_SIZE];
    size_t payload_length;
} PQC_WolfMQTTMessageContext;

#define PQC_WOLFSSL_RNG_READY_SPIN_LIMIT 1000000UL
#define PQC_STM32_RNG ((RNG_TypeDef *)RNG_BASE)

static bool s_rng_ready;

static int PQC_WolfSSL_WaitForRegisterBit(volatile uint32_t *reg, uint32_t mask)
{
    uint32_t spins = PQC_WOLFSSL_RNG_READY_SPIN_LIMIT;
    while (((*reg) & mask) == 0U) {
        if (spins-- == 0U) return -1;
    }
    return 0;
}

static int PQC_WolfSSL_InitializeHardwareRng(void)
{
    if (s_rng_ready) return 0;

    /* The STM32L4 RNG is clocked from the 48 MHz clock domain. The reset
     * selection uses HSI48, so enable it explicitly and bound the wait. */
    RCC->CRRCR |= RCC_CRRCR_HSI48ON;
    if (PQC_WolfSSL_WaitForRegisterBit(&RCC->CRRCR, RCC_CRRCR_HSI48RDY) != 0) return -1;

    RCC->AHB2ENR |= RCC_AHB2ENR_RNGEN;
    __DSB();
    PQC_STM32_RNG->CR |= RNG_CR_RNGEN;
    s_rng_ready = true;
    return 0;
}

int PQC_WolfSSL_HardwareSeed(unsigned char *output, unsigned int size)
{
    unsigned int offset = 0U;
    if ((output == NULL) && (size != 0U)) return -1;
    if (PQC_WolfSSL_InitializeHardwareRng() != 0) return -1;

    while (offset < size) {
        uint32_t spins = PQC_WOLFSSL_RNG_READY_SPIN_LIMIT;
        uint32_t status;
        uint32_t word;
        unsigned int remaining;
        unsigned int copy_length;

        do {
            status = PQC_STM32_RNG->SR;
            if ((status & (RNG_SR_CECS | RNG_SR_SECS)) != 0U) return -1;
            if ((status & RNG_SR_DRDY) != 0U) break;
        } while (spins-- != 0U);

        if ((status & RNG_SR_DRDY) == 0U) return -1;
        word = PQC_STM32_RNG->DR;
        remaining = size - offset;
        copy_length = remaining < sizeof(word) ? remaining : sizeof(word);
        memcpy(output + offset, &word, copy_length);
        offset += copy_length;
    }
    return 0;
}

static bool PQC_WolfMQTT_TLSRequested(void)
{
    return strcmp(PQC_MQTT_TLS_MODE, "classical_tls_server_auth") == 0;
}

static int PQC_WolfMQTT_SetTimeout(int socket_fd, int option, int timeout_ms)
{
    struct timeval timeout;
    timeout.tv_sec = timeout_ms / 1000;
    timeout.tv_usec = (timeout_ms % 1000) * 1000;
    return lwip_setsockopt(socket_fd, SOL_SOCKET, option, &timeout, sizeof(timeout));
}

static int PQC_WolfSSL_IORecv(WOLFSSL *ssl, char *buffer, int length, void *context)
{
    PQC_WolfMQTTSocketContext *socket_context = context;
    int result;
    (void)ssl;
    result = lwip_recv(socket_context->socket_fd, buffer, (size_t)length, 0);
    if (result > 0) return result;
    if (result == 0) return WOLFSSL_CBIO_ERR_CONN_CLOSE;
    return WOLFSSL_CBIO_ERR_GENERAL;
}

static int PQC_WolfSSL_IOSend(WOLFSSL *ssl, char *buffer, int length, void *context)
{
    PQC_WolfMQTTSocketContext *socket_context = context;
    int result;
    (void)ssl;
    result = lwip_send(socket_context->socket_fd, buffer, (size_t)length, 0);
    return result >= 0 ? result : WOLFSSL_CBIO_ERR_GENERAL;
}

static void PQC_WolfMQTT_CloseTransport(PQC_WolfMQTTSocketContext *context)
{
    if (context == NULL) return;
    if (context->tls != NULL) { wolfSSL_free(context->tls); context->tls = NULL; }
    if (context->tls_ctx != NULL) { wolfSSL_CTX_free(context->tls_ctx); context->tls_ctx = NULL; }
    if (context->socket_fd >= 0) {
        (void)lwip_shutdown(context->socket_fd, SHUT_RDWR);
        (void)lwip_close(context->socket_fd);
        context->socket_fd = -1;
    }
    context->tls_handshake_complete = false;
}

static int PQC_WolfMQTT_LwIPConnect(void *context, const char *host, word16 port, int timeout_ms)
{
    PQC_WolfMQTTSocketContext *socket_context = context;
    struct sockaddr_in address;
    int result;
    if ((socket_context == NULL) || (host == NULL) || (host[0] == '\0')) return -1;
    socket_context->socket_fd = lwip_socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (socket_context->socket_fd < 0) return -1;
    (void)PQC_WolfMQTT_SetTimeout(socket_context->socket_fd, SO_RCVTIMEO, timeout_ms);
    (void)PQC_WolfMQTT_SetTimeout(socket_context->socket_fd, SO_SNDTIMEO, timeout_ms);
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = lwip_htons(port);
    if (ip4addr_aton(host, (ip4_addr_t *)&address.sin_addr) == 0 ||
        lwip_connect(socket_context->socket_fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        PQC_WolfMQTT_CloseTransport(socket_context);
        return -1;
    }
    if (!socket_context->tls_requested) return MQTT_CODE_SUCCESS;

    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT TLS: context create begin\r\n");
    socket_context->tls_ctx = wolfSSL_CTX_new(wolfTLSv1_2_client_method());
    if (socket_context->tls_ctx == NULL) { PQC_WolfMQTT_CloseTransport(socket_context); return -1; }
    wolfSSL_SetIORecv(socket_context->tls_ctx, PQC_WolfSSL_IORecv);
    wolfSSL_SetIOSend(socket_context->tls_ctx, PQC_WolfSSL_IOSend);
    result = wolfSSL_CTX_load_verify_buffer(socket_context->tls_ctx,
        (const unsigned char *)PQC_MQTT_TLS_CA_PEM,
        (long)strlen(PQC_MQTT_TLS_CA_PEM), WOLFSSL_FILETYPE_PEM);
    if (result != WOLFSSL_SUCCESS) { PQC_WolfMQTT_CloseTransport(socket_context); return result; }
    socket_context->tls = wolfSSL_new(socket_context->tls_ctx);
    if (socket_context->tls == NULL) { PQC_WolfMQTT_CloseTransport(socket_context); return -1; }
    wolfSSL_SetIOReadCtx(socket_context->tls, socket_context);
    wolfSSL_SetIOWriteCtx(socket_context->tls, socket_context);
    if (PQC_MQTT_TLS_SERVER_NAME[0] != '\0') {
        result = wolfSSL_check_domain_name(socket_context->tls, PQC_MQTT_TLS_SERVER_NAME);
        if (result != WOLFSSL_SUCCESS) { PQC_WolfMQTT_CloseTransport(socket_context); return result; }
    }
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT TLS: handshake begin\r\n");
    result = wolfSSL_connect(socket_context->tls);
    if (result != WOLFSSL_SUCCESS) {
        int error = wolfSSL_get_error(socket_context->tls, result);
        PQC_WolfMQTT_CloseTransport(socket_context);
        return error == 0 ? -1 : -error;
    }
    socket_context->tls_handshake_complete = true;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT TLS: handshake passed\r\n");
    return MQTT_CODE_SUCCESS;
}

static int PQC_WolfMQTT_LwIPRead(void *context, byte *buffer, int length, int timeout_ms)
{
    PQC_WolfMQTTSocketContext *c = context;
    if ((c == NULL) || (c->socket_fd < 0)) return -1;
    (void)PQC_WolfMQTT_SetTimeout(c->socket_fd, SO_RCVTIMEO, timeout_ms);
    return c->tls_requested ? wolfSSL_read(c->tls, buffer, length) : lwip_recv(c->socket_fd, buffer, (size_t)length, 0);
}

static int PQC_WolfMQTT_LwIPWrite(void *context, const byte *buffer, int length, int timeout_ms)
{
    PQC_WolfMQTTSocketContext *c = context;
    if ((c == NULL) || (c->socket_fd < 0)) return -1;
    (void)PQC_WolfMQTT_SetTimeout(c->socket_fd, SO_SNDTIMEO, timeout_ms);
    return c->tls_requested ? wolfSSL_write(c->tls, buffer, length) : lwip_send(c->socket_fd, buffer, (size_t)length, 0);
}

static int PQC_WolfMQTT_LwIPDisconnect(void *context)
{
    PQC_WolfMQTTSocketContext *c = context;
    if ((c != NULL) && (c->tls != NULL)) (void)wolfSSL_shutdown(c->tls);
    PQC_WolfMQTT_CloseTransport(c);
    return MQTT_CODE_SUCCESS;
}

static int PQC_WolfMQTT_MessageCallback(MqttClient *client, MqttMessage *message, byte msg_new, byte msg_done)
{
    PQC_WolfMQTTMessageContext *context = client == NULL ? NULL : client->ctx;
    size_t available, copy_length;
    (void)msg_new;
    if ((context == NULL) || (message == NULL)) return MQTT_CODE_ERROR_BAD_ARG;
    available = sizeof(context->payload) - 1U - context->payload_length;
    copy_length = message->buffer_len < available ? message->buffer_len : available;
    if (copy_length > 0U) {
        memcpy(context->payload + context->payload_length, message->buffer, copy_length);
        context->payload_length += copy_length;
        context->payload[context->payload_length] = '\0';
    }
    if (msg_done != 0U) context->received = true;
    return MQTT_CODE_SUCCESS;
}

const char *PQC_WolfMQTT_BackendName(PQC_WolfMQTTBackend backend)
{
    return backend == PQC_WOLFMQTT_BACKEND_ST67W61M1 ? "st67w61m1" : "fake_no_network";
}

int PQC_WolfMQTT_BuildOnly_Initialize(PQC_WolfMQTTBackend backend, PQC_WolfMQTTBuildOnlyStatus *status)
{
    if (status == NULL) return MQTT_CODE_ERROR_BAD_ARG;
    memset(status, 0, sizeof(*status));
    status->backend = backend;
    status->transport_callbacks_present = true;
    status->transport_available = (backend == PQC_WOLFMQTT_BACKEND_ST67W61M1);
    return MQTT_CODE_SUCCESS;
}

static int PQC_WolfMQTT_RunExchangeCycle(PQC_WolfMQTTBuildOnlyStatus *status, unsigned int cycle)
{
    MqttClient client; MqttNet network; MqttConnect connect; MqttSubscribe subscribe;
    MqttTopic topic; MqttPublish publish; PQC_WolfMQTTSocketContext socket_context;
    PQC_WolfMQTTMessageContext message_context; byte tx[PQC_WOLFMQTT_BUFFER_SIZE], rx[PQC_WOLFMQTT_BUFFER_SIZE];
    int result;
    memset(status, 0, sizeof(*status)); status->backend = PQC_WOLFMQTT_BACKEND_ST67W61M1;
    status->transport_callbacks_present = true; status->transport_available = true;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT plaintext exchange: function entered\r\n");
    memset(&client,0,sizeof(client)); memset(&network,0,sizeof(network)); memset(&socket_context,0,sizeof(socket_context));
    memset(&message_context,0,sizeof(message_context)); socket_context.socket_fd=-1; socket_context.tls_requested=PQC_WolfMQTT_TLSRequested();
    network.context = &socket_context;
    network.connect = PQC_WolfMQTT_LwIPConnect;
    network.read = PQC_WolfMQTT_LwIPRead;
    network.write = PQC_WolfMQTT_LwIPWrite;
    network.disconnect = PQC_WolfMQTT_LwIPDisconnect;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: client init begin\r\n");
    result=MqttClient_Init(&client,&network,PQC_WolfMQTT_MessageCallback,tx,sizeof(tx),rx,sizeof(rx),PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    status->last_result=result; if(result!=MQTT_CODE_SUCCESS) return result; status->client_initialized=true; client.ctx=&message_context;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: TCP connect begin\r\n");
    result=MqttClient_NetConnect(&client,PQC_MQTT_BROKER_HOST,(word16)PQC_MQTT_BROKER_PORT,PQC_WOLFMQTT_COMMAND_TIMEOUT_MS,0,NULL);
    status->last_result = result;
    if (result != MQTT_CODE_SUCCESS) goto cleanup;
    status->broker_connected = true; status->tls_handshake_complete=socket_context.tls_handshake_complete;
    memset(&connect,0,sizeof(connect)); connect.keep_alive_sec=PQC_WOLFMQTT_KEEPALIVE_SECONDS; connect.clean_session=1; connect.client_id=PQC_MQTT_CLIENT_ID;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: MQTT connect begin\r\n");
    result=MqttClient_Connect(&client,&connect); status->last_result=result; if(result!=MQTT_CODE_SUCCESS) goto cleanup;
    memset(&topic,0,sizeof(topic)); topic.topic_filter=PQC_MQTT_COMMAND_TOPIC; topic.qos=MQTT_QOS_0;
    memset(&subscribe,0,sizeof(subscribe)); subscribe.packet_id=PQC_WOLFMQTT_PACKET_ID_SUBSCRIBE; subscribe.topic_count=1; subscribe.topics=&topic;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: subscribe begin\r\n");
    result=MqttClient_Subscribe(&client,&subscribe); status->last_result = result;
    if (result != MQTT_CODE_SUCCESS) goto cleanup;
    status->subscribed = true;
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: wait message begin\r\n");
    result=MqttClient_WaitMessage(&client,PQC_WOLFMQTT_COMMAND_TIMEOUT_MS); status->last_result=result;
    if ((result != MQTT_CODE_SUCCESS) || !message_context.received) goto cleanup;
    status->message_received = true;
    memset(&publish,0,sizeof(publish)); publish.topic_name=PQC_MQTT_RESPONSE_TOPIC; publish.qos=MQTT_QOS_0;
    publish.packet_id=(word16)(PQC_WOLFMQTT_PACKET_ID_PUBLISH+cycle); publish.buffer=(byte*)PQC_MQTT_CORRELATION_PAYLOAD;
    publish.total_len=(word32)strlen(PQC_MQTT_CORRELATION_PAYLOAD);
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: publish begin\r\n");
    result=MqttClient_Publish(&client,&publish); status->last_result = result;
    if (result == MQTT_CODE_SUCCESS) status->publish_complete = true;
cleanup:
    PQC_WolfMQTT_DiagnosticMarker("wolfMQTT: cleanup begin\r\n");
    if(status->broker_connected) (void)MqttClient_Disconnect(&client);
    (void)MqttClient_NetDisconnect(&client); MqttClient_DeInit(&client); return status->last_result;
}

int PQC_WolfMQTT_RunPlaintextExchange(PQC_WolfMQTTBuildOnlyStatus *status) { return PQC_WolfMQTT_RunExchangeCycle(status,0U); }

bool PQC_WolfMQTT_RuntimeStatusLine(char *buffer,size_t size,const char *context,bool scheduler_running)
{
    PQC_WolfMQTTBuildOnlyStatus first, second; int result, reconnect_result=MQTT_CODE_SUCCESS; int written;
    if((buffer==NULL)||(size==0U)||(context==NULL)) return false;
#if (PQC_MQTT_ENABLED != 0)
    if (PQC_WolfMQTT_TLSRequested()) (void)wolfSSL_Init();
    result=PQC_WolfMQTT_RunExchangeCycle(&first,0U);
    if((result==MQTT_CODE_SUCCESS)&&(PQC_MQTT_RECONNECT_ATTEMPTS>0)) reconnect_result=PQC_WolfMQTT_RunExchangeCycle(&second,1U); else memset(&second,0,sizeof(second));
    if (PQC_WolfMQTT_TLSRequested()) (void)wolfSSL_Cleanup();
    written=snprintf(buffer,size,
      "wolfMQTT runtime: context=%s scheduler=%s evidence=%s backend=%s result=%d transport=%s tcp=%s tls_handshake=%s mqtt_connect=%s mqtt_subscribe=%s mqtt_receive=%s mqtt_publish=%s reconnect=%s reconnect_tls_handshake=%s reconnect_publish=%s end_to_end=%s broker=%s:%u correlation=%s\r\n",
      context,scheduler_running?"running":"not_started",PQC_WolfMQTT_TLSRequested()?"stm32-st67-classical-tls-e2e":"stm32-st67-plaintext-mqtt-e2e",
      PQC_WolfMQTT_BackendName(first.backend),result,first.transport_available?"available":"unavailable",first.broker_connected?"passed":"failed",
      first.tls_handshake_complete?"passed":(PQC_WolfMQTT_TLSRequested()?"failed":"not_required"),first.broker_connected?"passed":"failed",
      first.subscribed?"passed":"failed",first.message_received?"passed":"failed",first.publish_complete?"passed":"failed",
      (PQC_MQTT_RECONNECT_ATTEMPTS>0&&reconnect_result==MQTT_CODE_SUCCESS)?"passed":"not_run",
      second.tls_handshake_complete?"passed":"not_run",second.publish_complete?"passed":"not_run",
      (first.publish_complete&&((PQC_MQTT_RECONNECT_ATTEMPTS==0)||second.publish_complete))?"passed":"failed",
      PQC_MQTT_BROKER_HOST,(unsigned)PQC_MQTT_BROKER_PORT,PQC_MQTT_CORRELATION_PAYLOAD);
#else
    result=PQC_WolfMQTT_BuildOnly_Initialize(PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK,&first);
    written=snprintf(buffer,size,"wolfMQTT runtime smoke: context=%s scheduler=%s evidence=stm32-fake-no-network-initialization-only init_result=%d\r\n",context,scheduler_running?"running":"not_started",result);
#endif
    return written>=0&&(size_t)written<size;
}
