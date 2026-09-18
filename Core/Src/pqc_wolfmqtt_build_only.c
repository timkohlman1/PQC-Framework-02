#include "pqc_wolfmqtt_build_only.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "main.h"
#include "FreeRTOS.h"
#include "task.h"
#include "lwip/inet.h"
#include "lwip/dns.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#include "pqc_wifi_config.h"
#include "pqc_tls_instrumentation.h"
#include "pqc_result_buffer.h"
#include "pqc_wolfssl_memory.h"

#ifndef PQC_TLS_COMPILED
#define PQC_TLS_COMPILED 1
#endif
#ifndef PQC_WOLFSSL_MEMORY_DIAGNOSTICS
#define PQC_WOLFSSL_MEMORY_DIAGNOSTICS 0
#endif

#include "wolfmqtt/mqtt_client.h"

#if PQC_TLS_COMPILED
/* wolfSSL uses RNG as a legacy type alias. STM32 CMSIS uses the same name
 * for the hardware peripheral pointer. Drop the CMSIS macro before wolfSSL
 * headers and address the peripheral explicitly through RNG_BASE below. */
#ifdef RNG
#undef RNG
#endif

#include "wolfssl/ssl.h"
#include "wolfssl/wolfcrypt/random.h"
#endif

#ifndef PQC_MQTT_TLS_AUTHENTICATION
#define PQC_MQTT_TLS_AUTHENTICATION "server"
#endif
#ifndef PQC_TLS_GROUP_ID
#define PQC_TLS_GROUP_ID WOLFSSL_ECC_SECP256R1
#endif
#ifndef PQC_TLS_GROUP_NAME
#define PQC_TLS_GROUP_NAME "secp256r1"
#endif
#ifndef PQC_MQTT_TLS_CLIENT_CERT_PEM
#define PQC_MQTT_TLS_CLIENT_CERT_PEM ""
#endif
#ifndef PQC_MQTT_TLS_CLIENT_KEY_PEM
#define PQC_MQTT_TLS_CLIENT_KEY_PEM ""
#endif
#ifndef PQC_MQTT_TRANSFER_REQUEST_TOPIC
#define PQC_MQTT_TRANSFER_REQUEST_TOPIC "pqc/stm32/transfer/request"
#endif
#ifndef PQC_MQTT_TRANSFER_RESPONSE_TOPIC
#define PQC_MQTT_TRANSFER_RESPONSE_TOPIC "pqc/stm32/transfer/response"
#endif
#ifndef PQC_MQTT_TRANSFER_REQUEST_PAYLOAD
#define PQC_MQTT_TRANSFER_REQUEST_PAYLOAD "send"
#endif
#ifndef PQC_MQTT_TRANSFER_PAYLOAD_BYTES
#define PQC_MQTT_TRANSFER_PAYLOAD_BYTES 204800U
#endif
#ifndef PQC_MQTT_TRANSFER_CHUNK_BYTES
#define PQC_MQTT_TRANSFER_CHUNK_BYTES 400U
#endif
#define PQC_WOLFMQTT_BUFFER_SIZE 512
#ifndef PQC_WOLFMQTT_COMMAND_TIMEOUT_MS
#define PQC_WOLFMQTT_COMMAND_TIMEOUT_MS 30000
#endif
#define PQC_WOLFMQTT_KEEPALIVE_SECONDS 30
#define PQC_WOLFMQTT_PACKET_ID_SUBSCRIBE 1
#define PQC_WOLFMQTT_PACKET_ID_PUBLISH 2
#ifndef PQC_REPORTING_MQTT_HOST
#define PQC_REPORTING_MQTT_HOST PQC_MQTT_BROKER_HOST
#endif
#ifndef PQC_REPORTING_MQTT_PORT
#define PQC_REPORTING_MQTT_PORT 1886
#endif
#ifndef PQC_REPORTING_RUN_ID_TOPIC
#define PQC_REPORTING_RUN_ID_TOPIC "pqc/control/run-id/current"
#endif
#define PQC_REPORTING_CHUNK_BYTES 96U
#define PQC_REPORTING_RUN_ID_MAX 96U

__attribute__((weak)) void PQC_WolfMQTT_DiagnosticMarker(const char *marker) { (void)marker; }

typedef struct {
    int socket_fd;
#if PQC_TLS_COMPILED
    WOLFSSL_CTX *tls_ctx;
    WOLFSSL *tls;
#else
    void *tls_ctx;
    void *tls;
#endif
    bool tls_requested;
    bool tcp_connected;
    bool tls_handshake_complete;
    bool tls_context_created;
    bool tls_session_created;
    bool tls_peer_identity_configured;
    bool ca_load_attempted;
    bool pqc_group_configured;
    bool ca_loaded;
    bool pqc_group_negotiated;
    int tls_connect_result;
    int tls_error;
    int tls_io_error;
    unsigned int tls_recv_calls;
    unsigned int tls_send_calls;
    unsigned int tls_recv_bytes;
    unsigned int tls_send_bytes;
    PQC_WolfMQTTReadyMetrics2Snapshot *ready_metrics_2;
    bool mqtt_first_response_armed;
    bool suppress_success_diagnostics;
} PQC_WolfMQTTSocketContext;

#ifndef PQC_OTA_ENABLED
#define PQC_OTA_ENABLED 0
#endif
#ifndef PQC_DUAL_BANK_ENABLED
#define PQC_DUAL_BANK_ENABLED 0
#endif

static PQC_WolfMQTTReadyMetrics2Snapshot s_ready_metrics_2_snapshot;

#if PQC_OTA_ENABLED
typedef struct PQC_OtaTransfer PQC_OtaTransfer;
static int PQC_OTA_ParseAndWriteChunk(const char *payload, PQC_OtaTransfer *transfer);
#endif

typedef struct {
    bool received;
    bool transfer_mode;
#if PQC_OTA_ENABLED
    bool ota_transfer_mode;
    bool ota_complete_seen;
    int ota_transfer_error;
    PQC_OtaTransfer *ota_transfer;
#endif
    char payload[PQC_WOLFMQTT_BUFFER_SIZE];
    size_t payload_length;
    uint32_t transfer_expected_bytes;
    uint32_t transfer_received_bytes;
    uint32_t transfer_message_count;
    uint32_t transfer_first_byte_tick_ms;
    uint32_t transfer_last_byte_tick_ms;
    bool transfer_first_byte_valid;
    bool transfer_complete;
} PQC_WolfMQTTMessageContext;

#if PQC_OTA_ENABLED
static int PQC_WolfMQTT_ProcessRetainedOta(
    MqttClient *client, PQC_WolfMQTTMessageContext *message_context, const char *run_id);
static int PQC_OTA_ConfirmActiveCandidateIfPending(void);
#endif

#if PQC_TLS_COMPILED
#define PQC_WOLFSSL_RNG_READY_SPIN_LIMIT 1000000UL
#define PQC_STM32_RNG ((RNG_TypeDef *)RNG_BASE)

static bool s_rng_ready;

static bool PQC_WolfMQTT_TLSGroupNamesMatch(const char *configured, const char *negotiated)
{
    size_t configured_index = 0U;
    size_t negotiated_index = 0U;

    if ((configured == NULL) || (negotiated == NULL)) {
        return false;
    }

    while ((configured[configured_index] != '\0') ||
           (negotiated[negotiated_index] != '\0')) {
        unsigned char configured_character;
        unsigned char negotiated_character;

        while ((configured[configured_index] == '-') ||
               (configured[configured_index] == '_')) {
            configured_index++;
        }
        while ((negotiated[negotiated_index] == '-') ||
               (negotiated[negotiated_index] == '_')) {
            negotiated_index++;
        }

        configured_character = (unsigned char)configured[configured_index];
        negotiated_character = (unsigned char)negotiated[negotiated_index];
        if ((configured_character >= (unsigned char)'A') &&
            (configured_character <= (unsigned char)'Z')) {
            configured_character = (unsigned char)(configured_character -
                (unsigned char)'A' + (unsigned char)'a');
        }
        if ((negotiated_character >= (unsigned char)'A') &&
            (negotiated_character <= (unsigned char)'Z')) {
            negotiated_character = (unsigned char)(negotiated_character -
                (unsigned char)'A' + (unsigned char)'a');
        }
        if (configured_character != negotiated_character) {
            return false;
        }
        if (configured_character == '\0') {
            return true;
        }
        configured_index++;
        negotiated_index++;
    }

    return true;
}

#endif


static void PQC_WolfMQTT_DiagnosticMemory(const char *stage)
{
    char marker[320];

    if (PQC_WolfSSL_MemoryStatusLine(marker, sizeof(marker), stage)) {
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
}

static void PQC_WolfMQTT_DiagnosticCode(const char *stage, int result, int error)
{
    char marker[160];
    int written = snprintf(marker, sizeof(marker),
        "wolfMQTT TLS: stage=%s result=%d error=%d\r\n", stage, result, error);
    if ((written > 0) && ((size_t)written < sizeof(marker))) {
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
}



#if PQC_TLS_COMPILED
static void PQC_WolfMQTT_DiagnosticWolfSSLState(const char *stage)
{
    char marker[192];
    const char *version = wolfSSL_lib_version();
    int written = snprintf(marker, sizeof(marker),
        "wolfMQTT TLS wolfSSL state: stage=%s version=%s errno=%d "
        "error_queue=unavailable\r\n",
        stage,
        version != NULL ? version : "unavailable",
        errno);

    if ((written > 0) && ((size_t)written < sizeof(marker))) {
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
}

#if PQC_WOLFSSL_MEMORY_DIAGNOSTICS
static void PQC_WolfMQTT_DiagnosticHeapBoundary(const char *stage)
{
    char marker[192];
    size_t heap_free_bytes = xPortGetFreeHeapSize();
    size_t heap_min_free_bytes = xPortGetMinimumEverFreeHeapSize();
    int written = snprintf(marker, sizeof(marker),
        "wolfMQTT TLS allocation boundary: stage=%s heap_free_bytes=%lu "
        "heap_min_ever_free_bytes=%lu\r\n",
        stage,
        (unsigned long)heap_free_bytes,
        (unsigned long)heap_min_free_bytes);
    if ((written > 0) && ((size_t)written < sizeof(marker))) {
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
}
#endif

#endif

static void PQC_WolfMQTT_DiagnosticDnsServer(void)
{
    char marker[192];
    char address[IPADDR_STRLEN_MAX];
    const ip_addr_t *server = dns_getserver(0);
    const char *server_text = "unavailable";
    int written;

    if ((server != NULL) && !ip_addr_isany(server)) {
        if (ipaddr_ntoa_r(server, address, (int)sizeof(address)) != NULL) {
            server_text = address;
        }
    }
    written = snprintf(marker, sizeof(marker),
        "ST67 DNS: required=%s server0=%s\r\n",
        (PQC_MQTT_DNS_REQUIRED != 0) ? "true" : "false", server_text);
    if ((written > 0) && ((size_t)written < sizeof(marker))) {
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
}

static int PQC_WolfMQTT_ResolveBroker(const char *host, struct sockaddr_in *address, bool emit_diagnostics)
{
    struct addrinfo hints;
    struct addrinfo *resolved = NULL;
    char marker[224];
    char resolved_text[IP4ADDR_STRLEN_MAX];
    int result;
    int written;

    if ((host == NULL) || (address == NULL)) return EAI_FAIL;
    memset(address, 0, sizeof(*address));
    address->sin_family = AF_INET;

    if (ip4addr_aton(host, (ip4_addr_t *)&address->sin_addr) != 0) {
        if (emit_diagnostics) {
            written = snprintf(marker, sizeof(marker),
                "ST67 DNS lookup: result=not_required hostname=%s ipv4=%s\r\n",
                host, host);
            if ((written > 0) && ((size_t)written < sizeof(marker))) {
                PQC_WolfMQTT_DiagnosticMarker(marker);
            }
        }
        return 0;
    }

    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    result = lwip_getaddrinfo(host, NULL, &hints, &resolved);
    if ((result == 0) && (resolved != NULL) &&
        (resolved->ai_addrlen >= sizeof(struct sockaddr_in))) {
        const struct sockaddr_in *resolved_address =
            (const struct sockaddr_in *)resolved->ai_addr;
        address->sin_addr = resolved_address->sin_addr;
        if (emit_diagnostics) {
            if (ip4addr_ntoa_r((const ip4_addr_t *)&address->sin_addr,
                    resolved_text, (int)sizeof(resolved_text)) == NULL) {
                (void)snprintf(resolved_text, sizeof(resolved_text), "unavailable");
            }
            written = snprintf(marker, sizeof(marker),
                "ST67 DNS lookup: result=passed hostname=%s ipv4=%s\r\n",
                host, resolved_text);
            if ((written > 0) && ((size_t)written < sizeof(marker))) {
                PQC_WolfMQTT_DiagnosticMarker(marker);
            }
        }
    } else if (emit_diagnostics) {
        written = snprintf(marker, sizeof(marker),
            "ST67 DNS lookup: result=failed hostname=%s error=%d required=%s\r\n",
            host, result, (PQC_MQTT_DNS_REQUIRED != 0) ? "true" : "false");
        if ((written > 0) && ((size_t)written < sizeof(marker))) {
            PQC_WolfMQTT_DiagnosticMarker(marker);
        }
    }
    if (resolved != NULL) lwip_freeaddrinfo(resolved);
    return result;
}

#if PQC_TLS_COMPILED
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

#endif

static bool PQC_WolfMQTT_TLSRequested(void)
{
#if PQC_TLS_COMPILED
    return (strcmp(PQC_MQTT_TLS_MODE, "classical_tls_server_auth") == 0) ||
           (strcmp(PQC_MQTT_TLS_MODE, "classical_tls_mutual") == 0) ||
           (strcmp(PQC_MQTT_TLS_MODE, "pqc_hybrid_tls_server_auth") == 0) ||
           (strcmp(PQC_MQTT_TLS_MODE, "pqc_hybrid_tls_mutual") == 0) ||
           (strcmp(PQC_MQTT_TLS_MODE, "pqc_tls_server_auth") == 0) ||
           (strcmp(PQC_MQTT_TLS_MODE, "pqc_tls_mutual") == 0);
#else
    return false;
#endif
}

static bool PQC_WolfMQTT_PQCHybridRequested(void)
{
    return (strcmp(PQC_MQTT_TLS_MODE, "pqc_hybrid_tls_server_auth") == 0) ||
           (strcmp(PQC_MQTT_TLS_MODE, "pqc_hybrid_tls_mutual") == 0);
}

static bool PQC_WolfMQTT_PQCStandaloneRequested(void)
{
    return (strcmp(PQC_MQTT_TLS_MODE, "pqc_tls_server_auth") == 0) ||
           (strcmp(PQC_MQTT_TLS_MODE, "pqc_tls_mutual") == 0);
}

#if PQC_TLS_COMPILED
static bool PQC_WolfMQTT_MutualTLSRequested(void)
{
    return (strcmp(PQC_MQTT_TLS_MODE, "classical_tls_mutual") == 0) ||
           (strcmp(PQC_MQTT_TLS_MODE, "pqc_hybrid_tls_mutual") == 0) ||
           (strcmp(PQC_MQTT_TLS_MODE, "pqc_tls_mutual") == 0);
}
#endif

#ifndef PQC_WOLFMQTT_TLS_IO_TRACE
#define PQC_WOLFMQTT_TLS_IO_TRACE 0
#endif

static int PQC_WolfMQTT_SetTimeout(int socket_fd, int option, int timeout_ms)
{
    struct timeval timeout;
    timeout.tv_sec = timeout_ms / 1000;
    timeout.tv_usec = (timeout_ms % 1000) * 1000;
    return lwip_setsockopt(socket_fd, SOL_SOCKET, option, &timeout, sizeof(timeout));
}

#if PQC_TLS_COMPILED
static int PQC_WolfSSL_IORecv(WOLFSSL *ssl, char *buffer, int length, void *context)
{
    PQC_WolfMQTTSocketContext *socket_context = context;
#if PQC_WOLFMQTT_TLS_IO_TRACE
    char marker[192];
    int written;
#endif
    int result;
    int saved_errno;
    (void)ssl;

    socket_context->tls_recv_calls++;
#if PQC_WOLFMQTT_TLS_IO_TRACE
    if (socket_context->tls_recv_calls == 1U) {
        PQC_WolfMQTT_DiagnosticMarker(
            "wolfMQTT TLS IO: direction=recv stage=first_callback_entry\r\n");
    }
#endif
    errno = 0;
    result = lwip_recv(socket_context->socket_fd, buffer, (size_t)length, 0);
    saved_errno = errno;
    if (result > 0) {
        socket_context->tls_recv_bytes += (unsigned int)result;
    }

#if PQC_WOLFMQTT_TLS_IO_TRACE
    written = snprintf(marker, sizeof(marker),
        "wolfMQTT TLS IO: direction=recv call=%u requested=%d result=%d errno=%d "
        "recv_bytes=%u send_bytes=%u\r\n",
        socket_context->tls_recv_calls, length, result, saved_errno,
        socket_context->tls_recv_bytes, socket_context->tls_send_bytes);
    if ((written > 0) && ((size_t)written < sizeof(marker))) {
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
#endif

    if (result > 0) return result;
    if (result == 0) return WOLFSSL_CBIO_ERR_CONN_CLOSE;
    socket_context->tls_io_error = saved_errno;
    if ((saved_errno == EWOULDBLOCK) || (saved_errno == EAGAIN) ||
        (saved_errno == EINTR)) {
        return WOLFSSL_CBIO_ERR_WANT_READ;
    }
    return WOLFSSL_CBIO_ERR_GENERAL;
}


#if PQC_WOLFMQTT_TLS_IO_TRACE
static unsigned int PQC_WolfMQTT_ReadUint16(const unsigned char *input)
{
    return ((unsigned int)input[0] << 8) | (unsigned int)input[1];
}

static void PQC_WolfMQTT_DiagnosticSignatureExtension(
    const char *name, const unsigned char *data, size_t data_length)
{
    char marker[320];
    size_t offset = 0U;
    int written;

    written = snprintf(marker, sizeof(marker),
        "wolfMQTT TLS ClientHello: extension=%s length=%lu schemes=",
        name, (unsigned long)data_length);
    if ((written <= 0) || ((size_t)written >= sizeof(marker))) {
        return;
    }
    offset = (size_t)written;

    if (data_length < 2U) {
        (void)snprintf(marker + offset, sizeof(marker) - offset, "malformed\r\n");
        PQC_WolfMQTT_DiagnosticMarker(marker);
        return;
    }

    {
        size_t list_length = (size_t)PQC_WolfMQTT_ReadUint16(data);
        size_t index;
        if ((list_length + 2U > data_length) || ((list_length % 2U) != 0U)) {
            (void)snprintf(marker + offset, sizeof(marker) - offset,
                "malformed\r\n");
            PQC_WolfMQTT_DiagnosticMarker(marker);
            return;
        }

        for (index = 0U; index < list_length; index += 2U) {
            unsigned int scheme = PQC_WolfMQTT_ReadUint16(data + 2U + index);
            int appended = snprintf(marker + offset, sizeof(marker) - offset,
                "%s0x%04x", index == 0U ? "" : ",", scheme);
            if ((appended <= 0) ||
                ((size_t)appended >= (sizeof(marker) - offset))) {
                break;
            }
            offset += (size_t)appended;
        }
    }

    if (offset + 3U < sizeof(marker)) {
        marker[offset++] = '\r';
        marker[offset++] = '\n';
        marker[offset] = '\0';
    }
    PQC_WolfMQTT_DiagnosticMarker(marker);
}

static void PQC_WolfMQTT_DiagnosticClientHelloSignatureAlgorithms(
    const unsigned char *record, size_t record_length)
{
    size_t position;
    size_t extensions_end;

    /* TLS record header, ClientHello handshake header and fixed fields. */
    if ((record == NULL) || (record_length < 44U) ||
        (record[0] != 0x16U) || (record[5] != 0x01U)) {
        PQC_WolfMQTT_DiagnosticMarker(
            "wolfMQTT TLS ClientHello: signature_extensions=unavailable reason=not_complete_client_hello\r\n");
        return;
    }

    position = 9U + 2U + 32U;
    if (position >= record_length) return;

    /* Legacy session ID. */
    position += 1U + (size_t)record[position];
    if (position + 2U > record_length) return;

    /* Cipher suites. */
    {
        size_t suites_length = (size_t)PQC_WolfMQTT_ReadUint16(record + position);
        position += 2U + suites_length;
    }
    if (position >= record_length) return;

    /* Legacy compression methods. */
    position += 1U + (size_t)record[position];
    if (position + 2U > record_length) return;

    {
        size_t extensions_length =
            (size_t)PQC_WolfMQTT_ReadUint16(record + position);
        position += 2U;
        if (position + extensions_length > record_length) {
            PQC_WolfMQTT_DiagnosticMarker(
                "wolfMQTT TLS ClientHello: signature_extensions=unavailable reason=fragmented_extensions\r\n");
            return;
        }
        extensions_end = position + extensions_length;
    }

    while (position + 4U <= extensions_end) {
        unsigned int extension_type =
            PQC_WolfMQTT_ReadUint16(record + position);
        size_t extension_length =
            (size_t)PQC_WolfMQTT_ReadUint16(record + position + 2U);
        position += 4U;
        if (position + extension_length > extensions_end) {
            break;
        }

        if (extension_type == 0x000dU) {
            PQC_WolfMQTT_DiagnosticSignatureExtension(
                "signature_algorithms", record + position, extension_length);
        }
        else if (extension_type == 0x0032U) {
            PQC_WolfMQTT_DiagnosticSignatureExtension(
                "signature_algorithms_cert", record + position,
                extension_length);
        }
        position += extension_length;
    }
}

#endif /* PQC_WOLFMQTT_TLS_IO_TRACE */

static int PQC_WolfSSL_IOSend(WOLFSSL *ssl, char *buffer, int length, void *context)
{
    PQC_WolfMQTTSocketContext *socket_context = context;
#if PQC_WOLFMQTT_TLS_IO_TRACE
    char marker[192];
    int written;
#endif
    int result;
    int saved_errno;
    (void)ssl;

    socket_context->tls_send_calls++;
#if PQC_WOLFMQTT_TLS_IO_TRACE
    if (socket_context->tls_send_calls == 1U) {
        PQC_WolfMQTT_DiagnosticClientHelloSignatureAlgorithms(
            (const unsigned char *)buffer, (size_t)length);
        {
            char first_send_marker[160];
            int first_send_written = snprintf(first_send_marker,
                sizeof(first_send_marker),
                "wolfMQTT TLS IO: direction=send stage=first_callback_entry requested=%d\r\n",
                length);
            if ((first_send_written > 0) &&
                ((size_t)first_send_written < sizeof(first_send_marker))) {
                PQC_WolfMQTT_DiagnosticMarker(first_send_marker);
            }
        }
    }
#endif
    errno = 0;
    result = lwip_send(socket_context->socket_fd, buffer, (size_t)length, 0);
    saved_errno = errno;
    if (result > 0) {
        socket_context->tls_send_bytes += (unsigned int)result;
    }

#if PQC_WOLFMQTT_TLS_IO_TRACE
    written = snprintf(marker, sizeof(marker),
        "wolfMQTT TLS IO: direction=send call=%u requested=%d result=%d errno=%d "
        "recv_bytes=%u send_bytes=%u\r\n",
        socket_context->tls_send_calls, length, result, saved_errno,
        socket_context->tls_recv_bytes, socket_context->tls_send_bytes);
    if ((written > 0) && ((size_t)written < sizeof(marker))) {
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
#endif

    if (result >= 0) return result;
    socket_context->tls_io_error = saved_errno;
    if ((saved_errno == EWOULDBLOCK) || (saved_errno == EAGAIN) ||
        (saved_errno == EINTR)) {
        return WOLFSSL_CBIO_ERR_WANT_WRITE;
    }
    return WOLFSSL_CBIO_ERR_GENERAL;
}

#endif

static void PQC_WolfMQTT_CloseTransport(PQC_WolfMQTTSocketContext *context)
{
    char marker[224];
    int written;

    if (context == NULL) return;
    written = snprintf(marker, sizeof(marker),
        "wolfMQTT transport: stage=close socket_fd=%d tcp_connected=%d tls_context=%p tls_session=%p\r\n",
        context->socket_fd,
        context->tcp_connected ? 1 : 0,
        (void *)context->tls_ctx,
        (void *)context->tls);
    if ((written > 0) && ((size_t)written < sizeof(marker))) {
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
#if PQC_TLS_COMPILED
    if (context->tls != NULL) { wolfSSL_free(context->tls); context->tls = NULL; }
    if (context->tls_ctx != NULL) { wolfSSL_CTX_free(context->tls_ctx); context->tls_ctx = NULL; }
#endif
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
    /* DNS is required for hostname-based broker profiles, but successful TLS
     * runs deliberately keep UART/formatting out of the pre-handshake critical
     * path. Plaintext profiles retain explicit DNS diagnostics; TLS success is
     * evidenced by the subsequent TCP/TLS/MQTT outcome and packet capture. */
    if (!socket_context->tls_requested) {
        PQC_WolfMQTT_DiagnosticDnsServer();
    }
    result = PQC_WolfMQTT_ResolveBroker(
        host, &address, !socket_context->tls_requested &&
        !socket_context->suppress_success_diagnostics);
    address.sin_port = lwip_htons(port);
    if ((result == 0) && (socket_context->ready_metrics_2 != NULL)) {
        /* Paper-compatible TTFB starts at the TCP connection attempt. DNS is
         * intentionally excluded so the measured interval is TCP + TLS +
         * MQTT CONNECT request/first CONNACK response byte. */
        socket_context->ready_metrics_2->ttfb_start_tick_ms = HAL_GetTick();
    }
    if ((result != 0) ||
        (lwip_connect(socket_context->socket_fd, (struct sockaddr *)&address, sizeof(address)) != 0)) {
        PQC_WolfMQTT_CloseTransport(socket_context);
        return -1;
    }
    socket_context->tcp_connected = true;
    if (socket_context->ready_metrics_2 != NULL) {
        uint32_t connected_tick = HAL_GetTick();
        PQC_WolfMQTTReadyMetrics2Snapshot *metrics = socket_context->ready_metrics_2;
        metrics->tcp_connected_tick_ms = connected_tick;
        metrics->tcp_connect_ms = connected_tick - metrics->ttfb_start_tick_ms;
        metrics->firmware_boot_to_tcp_connect_ms =
            connected_tick - metrics->firmware_boot_origin_tick_ms;
        metrics->tcp_timing_valid = 1U;
    }
    result = MQTT_CODE_SUCCESS;
    if (!socket_context->tls_requested) {
        if (!socket_context->suppress_success_diagnostics) {
            PQC_WolfMQTT_DiagnosticCode("tcp_connect", result, 0);
        }
        return MQTT_CODE_SUCCESS;
    }

#if PQC_TLS_COMPILED
    WOLFSSL_METHOD *tls_method;

    tls_method = wolfTLSv1_3_client_method();
    if (tls_method == NULL) {
        PQC_WolfMQTT_DiagnosticMarker(
            "wolfMQTT TLS: stage=method_create result=null tcp_close_before_clienthello=true\r\n");
        PQC_WolfMQTT_CloseTransport(socket_context);
        return MQTT_CODE_ERROR_TLS_CONNECT;
    }
    socket_context->tls_ctx = wolfSSL_CTX_new(tls_method);
    if (socket_context->tls_ctx == NULL) {
        PQC_WolfMQTT_DiagnosticCode("context_create", -1, errno);
        PQC_WolfMQTT_DiagnosticMarker(
            "wolfMQTT TLS: stage=context_create result=null tcp_close_before_clienthello=true\r\n");
        PQC_WolfMQTT_CloseTransport(socket_context);
        return MQTT_CODE_ERROR_TLS_CONNECT;
    }
    socket_context->tls_context_created = true;
    wolfSSL_SetIORecv(socket_context->tls_ctx, PQC_WolfSSL_IORecv);
    wolfSSL_SetIOSend(socket_context->tls_ctx, PQC_WolfSSL_IOSend);

    if (PQC_WolfMQTT_MutualTLSRequested()) {
#if !PQC_TLS_ENABLE_MLDSA_65_SIGN
        /* Classical mutual-TLS credentials are retained on WOLFSSL_CTX. This
         * is the established path used by the successful classical mTLS
         * profiles. ML-DSA credentials are deliberately deferred until after
         * wolfSSL_new() so they are scoped to the individual connection. */
        result = wolfSSL_CTX_use_certificate_buffer(socket_context->tls_ctx,
            (const unsigned char *)PQC_MQTT_TLS_CLIENT_CERT_PEM,
            (long)strlen(PQC_MQTT_TLS_CLIENT_CERT_PEM), WOLFSSL_FILETYPE_PEM);
        if (result != WOLFSSL_SUCCESS) {
            PQC_WolfMQTT_DiagnosticCode("client_certificate_load", result, 0);
            PQC_WolfMQTT_DiagnosticMemory("client_certificate_load");
            PQC_WolfMQTT_CloseTransport(socket_context);
            return MQTT_CODE_ERROR_TLS_CONNECT;
        }
        result = wolfSSL_CTX_use_PrivateKey_buffer(socket_context->tls_ctx,
            (const unsigned char *)PQC_MQTT_TLS_CLIENT_KEY_PEM,
            (long)strlen(PQC_MQTT_TLS_CLIENT_KEY_PEM), WOLFSSL_FILETYPE_PEM);
        if (result != WOLFSSL_SUCCESS) {
            PQC_WolfMQTT_DiagnosticCode("client_private_key_load", result, 0);
            PQC_WolfMQTT_DiagnosticMemory("client_private_key_load");
            PQC_WolfMQTT_CloseTransport(socket_context);
            return MQTT_CODE_ERROR_TLS_CONNECT;
        }
#endif
    }

    if (socket_context->tls_requested) {
        int groups[] = { PQC_TLS_GROUP_ID };
        result = wolfSSL_CTX_set_groups(socket_context->tls_ctx, groups, 1);
        socket_context->pqc_group_configured = (result == WOLFSSL_SUCCESS);
        if (result != WOLFSSL_SUCCESS) {
            PQC_WolfMQTT_DiagnosticCode("pqc_group_config", result, 0);
            PQC_WolfMQTT_DiagnosticMarker(
                "wolfMQTT TLS: stage=pqc_group_config result=failed tcp_close_before_clienthello=true\r\n");
            PQC_WolfMQTT_CloseTransport(socket_context);
            return MQTT_CODE_ERROR_TLS_CONNECT;
        }
    }

    /* Register the configured TLS peer identity before loading the CA. Use
     * IP subjectAltName verification for an IPv4 literal and DNS subjectAltName
     * verification for a configured hostname/FQDN. */
    errno = 0;
    socket_context->tls = wolfSSL_new(socket_context->tls_ctx);
    if (socket_context->tls == NULL) {
        PQC_WolfMQTT_DiagnosticCode("session_create", -1, errno);
        PQC_WolfMQTT_DiagnosticWolfSSLState("session_create");
        PQC_WolfMQTT_DiagnosticMemory("session_create");
        PQC_WolfMQTT_DiagnosticMarker(
            "wolfMQTT TLS: stage=session_create result=null tcp_close_before_clienthello=true\r\n");
        PQC_WolfMQTT_CloseTransport(socket_context);
        return MQTT_CODE_ERROR_TLS_CONNECT;
    }
    socket_context->tls_session_created = true;

#if PQC_TLS_ENABLE_MLDSA_65_SIGN
    if (PQC_WolfMQTT_MutualTLSRequested()) {
        /* ML-DSA mutual-TLS credentials are connection-local. A diagnostic
         * A/B run showed that installing the ML-DSA identity on WOLFSSL_CTX
         * changed server-chain verification, while the same mTLS handshake
         * verified normally when the identity was absent. Keep the proven
         * classical WOLFSSL_CTX path unchanged and scope only the ML-DSA
         * identity to this WOLFSSL session. */
        result = wolfSSL_use_certificate_buffer(socket_context->tls,
            (const unsigned char *)PQC_MQTT_TLS_CLIENT_CERT_PEM,
            (long)strlen(PQC_MQTT_TLS_CLIENT_CERT_PEM), WOLFSSL_FILETYPE_PEM);
        if (result != WOLFSSL_SUCCESS) {
            PQC_WolfMQTT_DiagnosticCode("client_certificate_load", result, 0);
            PQC_WolfMQTT_DiagnosticMemory("client_certificate_load");
            PQC_WolfMQTT_CloseTransport(socket_context);
            return MQTT_CODE_ERROR_TLS_CONNECT;
        }
        result = wolfSSL_use_PrivateKey_buffer(socket_context->tls,
            (const unsigned char *)PQC_MQTT_TLS_CLIENT_KEY_PEM,
            (long)strlen(PQC_MQTT_TLS_CLIENT_KEY_PEM), WOLFSSL_FILETYPE_PEM);
        if (result != WOLFSSL_SUCCESS) {
            PQC_WolfMQTT_DiagnosticCode("client_private_key_load", result, 0);
            PQC_WolfMQTT_DiagnosticMemory("client_private_key_load");
            PQC_WolfMQTT_CloseTransport(socket_context);
            return MQTT_CODE_ERROR_TLS_CONNECT;
        }
    }
#endif

    {
        ip4_addr_t peer_ip;
        if (ip4addr_aton(PQC_MQTT_TLS_SERVER_NAME, &peer_ip) != 0) {
            result = wolfSSL_check_ip_address(socket_context->tls, PQC_MQTT_TLS_SERVER_NAME);
        } else {
            result = wolfSSL_check_domain_name(socket_context->tls, PQC_MQTT_TLS_SERVER_NAME);
        }
    }
    if (result != WOLFSSL_SUCCESS) {
        PQC_WolfMQTT_DiagnosticCode("peer_identity_check", result, 0);
        PQC_WolfMQTT_CloseTransport(socket_context);
        return MQTT_CODE_ERROR_TLS_CONNECT;
    }
    socket_context->tls_peer_identity_configured = true;

    socket_context->ca_load_attempted = true;
    result = wolfSSL_CTX_load_verify_buffer(socket_context->tls_ctx,
        (const unsigned char *)PQC_MQTT_TLS_CA_PEM,
        (long)strlen(PQC_MQTT_TLS_CA_PEM), WOLFSSL_FILETYPE_PEM);
    socket_context->ca_loaded = (result == WOLFSSL_SUCCESS);
    if (result != WOLFSSL_SUCCESS) {
        PQC_WolfMQTT_DiagnosticCode("ca_load", result, 0);
        PQC_WolfMQTT_CloseTransport(socket_context);
        return MQTT_CODE_ERROR_TLS_CONNECT;
    }
    wolfSSL_SetIOReadCtx(socket_context->tls, socket_context);
    wolfSSL_SetIOWriteCtx(socket_context->tls, socket_context);

    {
        UBaseType_t stack_before_words = uxTaskGetStackHighWaterMark(NULL);
        size_t heap_before_free = xPortGetFreeHeapSize();
        size_t heap_before_min = xPortGetMinimumEverFreeHeapSize();
        UBaseType_t stack_after_words;
        size_t heap_after_free;
        size_t heap_after_min;

        PQC_TLS_InstrumentationSetPreMemory(
            (uint32_t)stack_before_words * (uint32_t)sizeof(StackType_t),
            (uint32_t)heap_before_free,
            (uint32_t)heap_before_min);

        /* No UART, formatting, stack scanning, or heap queries are permitted
         * between HandshakeBegin and HandshakeEnd. */
        PQC_TLS_InstrumentationHandshakeBegin();
        result = wolfSSL_connect(socket_context->tls);
        PQC_TLS_InstrumentationHandshakeEnd(result);

        stack_after_words = uxTaskGetStackHighWaterMark(NULL);
        heap_after_free = xPortGetFreeHeapSize();
        heap_after_min = xPortGetMinimumEverFreeHeapSize();
        PQC_TLS_InstrumentationSetPostMemory(
            (uint32_t)stack_after_words * (uint32_t)sizeof(StackType_t),
            (uint32_t)heap_after_free,
            (uint32_t)heap_after_min);

        /* Ready Metrics 1 reports here, after the handshake interval. Ready
         * Metrics 2 defers formatting/UART until its broader TTFB and ready
         * publication intervals have both ended. */
        if (!socket_context->suppress_success_diagnostics ||
            (result != WOLFSSL_SUCCESS)) {
            PQC_TLS_InstrumentationReport(PQC_WolfMQTT_DiagnosticMarker);
        }
    }
    socket_context->tls_connect_result = result;
    if ((result == WOLFSSL_SUCCESS) && (socket_context->ready_metrics_2 != NULL)) {
        const PQC_TLSInstrumentationSnapshot *tls_metrics =
            PQC_TLS_InstrumentationSnapshot();
        PQC_WolfMQTTReadyMetrics2Snapshot *metrics = socket_context->ready_metrics_2;
        metrics->tls_complete_tick_ms = tls_metrics->handshake_end_tick_ms;
        metrics->firmware_boot_to_tls_complete_ms =
            metrics->tls_complete_tick_ms - metrics->firmware_boot_origin_tick_ms;
        metrics->tls_timing_valid = 1U;
    }
    if (result != WOLFSSL_SUCCESS) {
        int error = wolfSSL_get_error(socket_context->tls, result);
        char marker[224];
        socket_context->tls_error = error;
        PQC_WolfMQTT_DiagnosticCode("handshake", result, error);
        (void)snprintf(marker, sizeof(marker),
            "wolfMQTT TLS handshake failure: wolfssl_error=%d io_errno=%d "
            "recv_calls=%u send_calls=%u recv_bytes=%u send_bytes=%u "
            "command_timeout_ms=%u\r\n",
            error, socket_context->tls_io_error,
            socket_context->tls_recv_calls, socket_context->tls_send_calls,
            socket_context->tls_recv_bytes, socket_context->tls_send_bytes,
            (unsigned int)PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
        PQC_WolfMQTT_DiagnosticMarker(marker);
        PQC_WolfMQTT_DiagnosticMemory("handshake_failure");
        PQC_WolfMQTT_CloseTransport(socket_context);
        return error == 0 ? -1 : -error;
    }
    if (!socket_context->suppress_success_diagnostics) {
        PQC_WolfMQTT_DiagnosticCode("handshake", result, 0);
    }
    socket_context->tls_handshake_complete = true;
    if (socket_context->tls_requested) {
        const char *curve_name = wolfSSL_get_curve_name(socket_context->tls);
        char marker[224];
        socket_context->pqc_group_negotiated =
            PQC_WolfMQTT_TLSGroupNamesMatch(PQC_TLS_GROUP_NAME, curve_name);
        if (!socket_context->suppress_success_diagnostics) {
            (void)snprintf(marker, sizeof(marker),
                "wolfMQTT TLS: protocol=TLSv1.3 configured_group=%s negotiated_group=%s key_exchange_group=%s\r\n",
                PQC_TLS_GROUP_NAME, curve_name != NULL ? curve_name : "unavailable",
                socket_context->pqc_group_negotiated ? "passed" : "failed");
            PQC_WolfMQTT_DiagnosticMarker(marker);
        }
        if (!socket_context->pqc_group_negotiated) {
            PQC_WolfMQTT_CloseTransport(socket_context);
            return MQTT_CODE_ERROR_TLS_CONNECT;
        }
    }
    if (!socket_context->suppress_success_diagnostics) {
        PQC_WolfMQTT_DiagnosticMarker("wolfMQTT TLS: handshake passed\r\n");
    }
    return MQTT_CODE_SUCCESS;
#else
    PQC_WolfMQTT_CloseTransport(socket_context);
    return MQTT_CODE_ERROR_TLS_CONNECT;
#endif
}

static int PQC_WolfMQTT_LwIPRead(void *context, byte *buffer, int length, int timeout_ms)
{
    PQC_WolfMQTTSocketContext *c = context;
    int result;
    if ((c == NULL) || (c->socket_fd < 0)) return -1;
    (void)PQC_WolfMQTT_SetTimeout(c->socket_fd, SO_RCVTIMEO, timeout_ms);
#if PQC_TLS_COMPILED
    if (c->tls_requested) {
        result = wolfSSL_read(c->tls, buffer, length);
    }
    else
#endif
    {
        result = lwip_recv(c->socket_fd, buffer, (size_t)length, 0);
    }

    if ((result > 0) && c->mqtt_first_response_armed &&
        (c->ready_metrics_2 != NULL) &&
        (c->ready_metrics_2->mqtt_first_response_valid == 0U)) {
        uint32_t first_byte_tick = HAL_GetTick();
        PQC_WolfMQTTReadyMetrics2Snapshot *metrics = c->ready_metrics_2;
        metrics->mqtt_first_response_tick_ms = first_byte_tick;
        metrics->ttfb_ms = first_byte_tick - metrics->ttfb_start_tick_ms;
        metrics->firmware_boot_to_mqtt_first_response_ms =
            first_byte_tick - metrics->firmware_boot_origin_tick_ms;
        metrics->mqtt_first_response_valid = 1U;
    }
    return result;
}

static int PQC_WolfMQTT_LwIPWrite(void *context, const byte *buffer, int length, int timeout_ms)
{
    PQC_WolfMQTTSocketContext *c = context;
    if ((c == NULL) || (c->socket_fd < 0)) return -1;
    (void)PQC_WolfMQTT_SetTimeout(c->socket_fd, SO_SNDTIMEO, timeout_ms);
#if PQC_TLS_COMPILED
    if (c->tls_requested) return wolfSSL_write(c->tls, buffer, length);
#endif
    return lwip_send(c->socket_fd, buffer, (size_t)length, 0);
}

static int PQC_WolfMQTT_LwIPDisconnect(void *context)
{
    PQC_WolfMQTTSocketContext *c = context;
#if PQC_TLS_COMPILED
    if ((c != NULL) && (c->tls != NULL)) (void)wolfSSL_shutdown(c->tls);
#endif
    PQC_WolfMQTT_CloseTransport(c);
    return MQTT_CODE_SUCCESS;
}

static int PQC_WolfMQTT_MessageCallback(MqttClient *client, MqttMessage *message, byte msg_new, byte msg_done)
{
    PQC_WolfMQTTMessageContext *context = client == NULL ? NULL : client->ctx;
    size_t available, copy_length;
    if ((context == NULL) || (message == NULL)) return MQTT_CODE_ERROR_BAD_ARG;

    if (context->transfer_mode) {
        if ((message->buffer_len > 0U) && !context->transfer_first_byte_valid) {
            context->transfer_first_byte_tick_ms = HAL_GetTick();
            context->transfer_first_byte_valid = true;
        }
        if (message->buffer_len > 0U) {
            context->transfer_received_bytes += (uint32_t)message->buffer_len;
            context->transfer_last_byte_tick_ms = HAL_GetTick();
        }
        if (msg_done != 0U) {
            context->transfer_message_count++;
        }
        if (context->transfer_received_bytes >= context->transfer_expected_bytes) {
            context->transfer_complete = true;
        }
        return MQTT_CODE_SUCCESS;
    }

#if PQC_OTA_ENABLED
    if (context->ota_transfer_mode) {
        if (msg_new != 0U) {
            context->payload_length = 0U;
            context->payload[0] = '\0';
        }
        available = sizeof(context->payload) - 1U - context->payload_length;
        copy_length = message->buffer_len < available ? message->buffer_len : available;
        if (copy_length > 0U) {
            memcpy(context->payload + context->payload_length, message->buffer, copy_length);
            context->payload_length += copy_length;
            context->payload[context->payload_length] = '\0';
        }
        if (msg_done != 0U) {
            if (strcmp(context->payload, "complete") == 0) {
                context->ota_complete_seen = true;
            } else if (context->ota_transfer == NULL ||
                       PQC_OTA_ParseAndWriteChunk(context->payload, context->ota_transfer) != 0) {
                context->ota_transfer_error = MQTT_CODE_ERROR_BAD_ARG;
            }
            context->received = true;
        }
        return context->ota_transfer_error == 0 ? MQTT_CODE_SUCCESS : context->ota_transfer_error;
    }
#endif

    (void)msg_new;
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


static int PQC_WolfMQTT_PublishTopic(
    MqttClient *client, const char *topic, const char *payload, word16 packet_id)
{
    MqttPublish publish;
    if ((client == NULL) || (topic == NULL) || (payload == NULL)) return MQTT_CODE_ERROR_BAD_ARG;
    memset(&publish, 0, sizeof(publish));
    publish.topic_name = topic;
    publish.qos = MQTT_QOS_1;
    publish.packet_id = packet_id;
    publish.buffer = (byte *)payload;
    publish.total_len = (word32)strlen(payload);
    return MqttClient_Publish(client, &publish);
}

static int PQC_WolfMQTT_ClearRetainedTopic(MqttClient *client, const char *topic, word16 packet_id)
{
    MqttPublish publish;
    static byte empty = 0U;
    if (client == NULL || topic == NULL) return MQTT_CODE_ERROR_BAD_ARG;
    memset(&publish, 0, sizeof(publish));
    publish.topic_name = topic;
    publish.qos = MQTT_QOS_1;
    publish.retain = 1;
    publish.packet_id = packet_id;
    publish.buffer = &empty;
    publish.total_len = 0U;
    return MqttClient_Publish(client, &publish);
}

int PQC_WolfMQTT_PublishDeferredResults(
    const uint8_t *data,
    size_t length,
    const char *logical_sha256,
    uint32_t record_count,
    uint32_t dropped_record_count,
    bool overflowed)
{
    MqttClient client;
    MqttNet network;
    MqttConnect connect;
    MqttSubscribe subscribe;
    MqttTopic control_topic;
    PQC_WolfMQTTSocketContext socket_context;
    PQC_WolfMQTTMessageContext message_context;
    byte tx[PQC_WOLFMQTT_BUFFER_SIZE], rx[PQC_WOLFMQTT_BUFFER_SIZE];
    char run_id[PQC_REPORTING_RUN_ID_MAX];
    char topic[192];
    char payload[512];
    char hex[(PQC_REPORTING_CHUNK_BYTES * 2U) + 1U];
    size_t offset = 0U;
    uint32_t sequence = 0U;
    uint32_t chunk_count = 0U;
    int result;
    unsigned int i;

    if (((data == NULL) && (length != 0U)) || (logical_sha256 == NULL)) return MQTT_CODE_ERROR_BAD_ARG;
    memset(&client,0,sizeof(client)); memset(&network,0,sizeof(network));
    memset(&socket_context,0,sizeof(socket_context)); memset(&message_context,0,sizeof(message_context));
    socket_context.socket_fd = -1;
    socket_context.tls_requested = false;
    network.context=&socket_context;
    network.connect=PQC_WolfMQTT_LwIPConnect;
    network.read=PQC_WolfMQTT_LwIPRead;
    network.write=PQC_WolfMQTT_LwIPWrite;
    network.disconnect=PQC_WolfMQTT_LwIPDisconnect;

    result=MqttClient_Init(&client,&network,PQC_WolfMQTT_MessageCallback,tx,sizeof(tx),rx,sizeof(rx),PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    if(result!=MQTT_CODE_SUCCESS) return result;
    client.ctx=&message_context;
    result=MqttClient_NetConnect(&client,PQC_REPORTING_MQTT_HOST,(word16)PQC_REPORTING_MQTT_PORT,PQC_WOLFMQTT_COMMAND_TIMEOUT_MS,0,NULL);
    if(result!=MQTT_CODE_SUCCESS) goto cleanup_client;
    memset(&connect,0,sizeof(connect)); connect.keep_alive_sec=PQC_WOLFMQTT_KEEPALIVE_SECONDS; connect.clean_session=1; connect.client_id="pqc-stm32-reporting";
    result=MqttClient_Connect(&client,&connect);
    if(result!=MQTT_CODE_SUCCESS) goto cleanup_network;

    memset(&control_topic,0,sizeof(control_topic)); control_topic.topic_filter=PQC_REPORTING_RUN_ID_TOPIC; control_topic.qos=MQTT_QOS_1;
    memset(&subscribe,0,sizeof(subscribe)); subscribe.packet_id=41U; subscribe.topic_count=1U; subscribe.topics=&control_topic;
    result=MqttClient_Subscribe(&client,&subscribe);
    if(result!=MQTT_CODE_SUCCESS) goto cleanup_mqtt;
    result=MqttClient_WaitMessage(&client,PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    if((result!=MQTT_CODE_SUCCESS)||!message_context.received||message_context.payload_length==0U||message_context.payload_length>=sizeof(run_id)) {
        result=MQTT_CODE_ERROR_TIMEOUT; goto cleanup_mqtt;
    }
    memcpy(run_id,message_context.payload,message_context.payload_length); run_id[message_context.payload_length]='\0';

    chunk_count=(uint32_t)((length + PQC_REPORTING_CHUNK_BYTES - 1U)/PQC_REPORTING_CHUNK_BYTES);
    while(offset<length) {
        size_t amount=length-offset; size_t hex_index=0U;
        if(amount>PQC_REPORTING_CHUNK_BYTES) amount=PQC_REPORTING_CHUNK_BYTES;
        for(i=0U;i<(unsigned int)amount;i++) {
            static const char digits[]="0123456789abcdef"; uint8_t value=data[offset+i];
            hex[hex_index++]=digits[value>>4]; hex[hex_index++]=digits[value&0x0fU];
        }
        hex[hex_index]='\0';
        (void)snprintf(topic,sizeof(topic),"pqc/result/stm32/%s/chunk",run_id);
        (void)snprintf(payload,sizeof(payload),
            "{\"schema_version\":1,\"type\":\"chunk\",\"source\":\"stm32\",\"run_id\":\"%s\",\"sequence\":%lu,\"context\":\"deferred_result_buffer\",\"data_hex\":\"%s\"}",
            run_id,(unsigned long)sequence,hex);
        result=PQC_WolfMQTT_PublishTopic(&client,topic,payload,(word16)(100U+(sequence%60000U)));
        if(result!=MQTT_CODE_SUCCESS) goto cleanup_mqtt;
        offset+=amount; sequence++;
    }
    (void)snprintf(topic,sizeof(topic),"pqc/result/stm32/%s/complete",run_id);
    (void)snprintf(payload,sizeof(payload),
        "{\"schema_version\":1,\"type\":\"complete\",\"source\":\"stm32\",\"run_id\":\"%s\",\"record_count\":%lu,\"chunk_count\":%lu,\"logical_bytes\":%lu,\"dropped_record_count\":%lu,\"overflowed\":%s,\"logical_sha256\":\"%s\"}",
        run_id,(unsigned long)record_count,(unsigned long)chunk_count,(unsigned long)length,
        (unsigned long)dropped_record_count,overflowed?"true":"false",logical_sha256);
    result=PQC_WolfMQTT_PublishTopic(&client,topic,payload,60001U);
#if PQC_OTA_ENABLED
    if(result==MQTT_CODE_SUCCESS) {
        int ota_result=PQC_WolfMQTT_ProcessRetainedOta(&client,&message_context,run_id);
        if(ota_result!=MQTT_CODE_SUCCESS) result=ota_result;
        else if(PQC_OTA_ConfirmActiveCandidateIfPending()!=0) result=MQTT_CODE_ERROR_NETWORK;
    }
#endif

cleanup_mqtt:
    (void)MqttClient_Disconnect(&client);
cleanup_network:
    (void)MqttClient_NetDisconnect(&client);
cleanup_client:
    MqttClient_DeInit(&client);
    return result;
}

#if PQC_OTA_ENABLED
#define PQC_OTA_BOOT_EVENT_MAILBOX_ADDRESS 0x10000100UL
#define PQC_OTA_BOOT_EVENT_MAILBOX_MAGIC 0x504F424DUL
#define PQC_OTA_BOOT_EVENT_MAILBOX_VERSION 1U
#define PQC_OTA_BOOT_EVENT_CAPACITY 12U
#define PQC_OTA_BOOT_EVENT_START 1U
#define PQC_OTA_BOOT_EVENT_MANIFEST_AUTH 2U
#define PQC_OTA_BOOT_EVENT_APPLICATION_AUTH 3U
#define PQC_OTA_BOOT_EVENT_SWAP_REQUESTED 4U
#define PQC_OTA_BOOT_EVENT_CANDIDATE_FIRST_BOOT 5U
#define PQC_OTA_BOOT_EVENT_ROLLBACK_REQUESTED 6U

typedef struct {
    uint32_t phase;
    uint32_t active_bank;
    uint32_t bfb2;
    uint32_t from_bank;
    uint32_t to_bank;
    uint32_t target_bank;
    uint32_t migration;
} PQC_OtaBootEvent;

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t count;
    uint32_t reserved;
    PQC_OtaBootEvent events[PQC_OTA_BOOT_EVENT_CAPACITY];
} PQC_OtaBootEventMailbox;

static void PQC_OTA_EmitBootEventMailbox(void)
{
    volatile PQC_OtaBootEventMailbox *mailbox =
        (volatile PQC_OtaBootEventMailbox *)(uintptr_t)PQC_OTA_BOOT_EVENT_MAILBOX_ADDRESS;
    uint32_t count, i;
    char marker[256];
    if (mailbox->magic != PQC_OTA_BOOT_EVENT_MAILBOX_MAGIC ||
        mailbox->version != PQC_OTA_BOOT_EVENT_MAILBOX_VERSION ||
        mailbox->count > PQC_OTA_BOOT_EVENT_CAPACITY)
        return;
    count = mailbox->count;
    for (i = 0U; i < count; ++i) {
        const volatile PQC_OtaBootEvent *event = &mailbox->events[i];
        switch (event->phase) {
            case PQC_OTA_BOOT_EVENT_START:
                (void)snprintf(marker, sizeof(marker),
                    "PQC_OTA_BOOT phase=start active_bank=%lu bfb2=%lu\r\n",
                    (unsigned long)event->active_bank, (unsigned long)event->bfb2);
                break;
            case PQC_OTA_BOOT_EVENT_MANIFEST_AUTH:
                (void)snprintf(marker, sizeof(marker),
                    "PQC_OTA_BOOT phase=candidate_manifest_authenticated target_bank=%lu migration=%lu\r\n",
                    (unsigned long)event->target_bank, (unsigned long)event->migration);
                break;
            case PQC_OTA_BOOT_EVENT_APPLICATION_AUTH:
                (void)snprintf(marker, sizeof(marker),
                    "PQC_OTA_BOOT phase=candidate_application_authenticated target_bank=%lu\r\n",
                    (unsigned long)event->target_bank);
                break;
            case PQC_OTA_BOOT_EVENT_SWAP_REQUESTED:
                (void)snprintf(marker, sizeof(marker),
                    "PQC_OTA_BOOT phase=swap_requested from_bank=%lu to_bank=%lu bfb2_before=%lu\r\n",
                    (unsigned long)event->from_bank, (unsigned long)event->to_bank,
                    (unsigned long)event->bfb2);
                break;
            case PQC_OTA_BOOT_EVENT_CANDIDATE_FIRST_BOOT:
                (void)snprintf(marker, sizeof(marker),
                    "PQC_OTA_BOOT phase=candidate_first_boot active_bank=%lu bfb2=%lu\r\n",
                    (unsigned long)event->active_bank, (unsigned long)event->bfb2);
                break;
            case PQC_OTA_BOOT_EVENT_ROLLBACK_REQUESTED:
                (void)snprintf(marker, sizeof(marker),
                    "PQC_OTA_BOOT phase=rollback_requested from_bank=%lu to_bank=%lu bfb2_before=%lu\r\n",
                    (unsigned long)event->from_bank, (unsigned long)event->to_bank,
                    (unsigned long)event->bfb2);
                break;
            default:
                continue;
        }
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
    mailbox->count = 0U;
}

#define PQC_OTA_BANK_BYTES 0x00100000UL
#define PQC_OTA_INACTIVE_BASE 0x08100000UL
#define PQC_OTA_BOOTLOADER_BYTES 0x0001C000UL
#define PQC_OTA_MANIFEST_ADDRESS 0x0811C000UL
#define PQC_OTA_MANIFEST_BYTES 0x00004000UL
#define PQC_OTA_APPLICATION_ADDRESS 0x08120000UL
#define PQC_OTA_APPLICATION_BYTES 0x000E0000UL
#define PQC_OTA_ACTIVE_MANIFEST_ADDRESS 0x0801C000UL
#define PQC_OTA_MARKER_STAGED_ADDRESS (PQC_OTA_ACTIVE_MANIFEST_ADDRESS + PQC_OTA_MANIFEST_BYTES - 24UL)
#define PQC_OTA_MARKER_BOOTED_ADDRESS (PQC_OTA_ACTIVE_MANIFEST_ADDRESS + PQC_OTA_MANIFEST_BYTES - 16UL)
#define PQC_OTA_MARKER_CONFIRMED_ADDRESS (PQC_OTA_ACTIVE_MANIFEST_ADDRESS + PQC_OTA_MANIFEST_BYTES - 8UL)
#define PQC_OTA_MARKER_STAGED 0x5354414745445035ULL
#define PQC_OTA_MARKER_BOOTED 0x424F4F5445445035ULL
#define PQC_OTA_MARKER_CONFIRMED 0x434F4E4649524D35ULL
#define PQC_OTA_MANIFEST_PAYLOAD_FLAGS_ADDRESS (PQC_OTA_ACTIVE_MANIFEST_ADDRESS + 0x3000UL + 8UL)
#define PQC_OTA_FLAG_TEST_NO_CONFIRM 0x80000000UL
#define PQC_OTA_CONTROL_WAIT_MS 250
#define PQC_OTA_TRANSFER_WAIT_MS 30000

struct PQC_OtaTransfer {
    uint32_t flags;
    uint32_t bootloader_bytes;
    uint32_t manifest_bytes;
    uint32_t application_bytes;
    uint8_t bootloader_sha256[32];
    uint8_t manifest_sha256[32];
    uint8_t application_sha256[32];
    bool activate;
    uint32_t received_bootloader_bytes;
    uint32_t received_manifest_bytes;
    uint32_t received_application_bytes;
};


static bool PQC_OTA_MarkerIs(uint32_t address, uint64_t expected)
{
    return (*(const volatile uint64_t *)(uintptr_t)address == expected);
}

static uint32_t PQC_OTA_ActivePhysicalBank(void)
{
    return (READ_BIT(SYSCFG->MEMRMP, SYSCFG_MEMRMP_FB_MODE) == 0U) ? 1U : 2U;
}

static uint32_t PQC_OTA_Bfb2Enabled(void)
{
    return (READ_BIT(FLASH->OPTR, FLASH_OPTR_BFB2) != 0U) ? 1U : 0U;
}

static void PQC_OTA_LogApplicationState(const char *phase)
{
    char marker[224];
    const bool staged = PQC_OTA_MarkerIs(PQC_OTA_MARKER_STAGED_ADDRESS, PQC_OTA_MARKER_STAGED);
    const bool booted = PQC_OTA_MarkerIs(PQC_OTA_MARKER_BOOTED_ADDRESS, PQC_OTA_MARKER_BOOTED);
    const bool confirmed = PQC_OTA_MarkerIs(PQC_OTA_MARKER_CONFIRMED_ADDRESS, PQC_OTA_MARKER_CONFIRMED);
    (void)snprintf(marker, sizeof(marker),
        "PQC_OTA_APP phase=%s active_bank=%lu bfb2=%lu staged=%u booted=%u confirmed=%u\r\n",
        phase,
        (unsigned long)PQC_OTA_ActivePhysicalBank(),
        (unsigned long)PQC_OTA_Bfb2Enabled(),
        staged ? 1U : 0U,
        booted ? 1U : 0U,
        confirmed ? 1U : 0U);
    PQC_WolfMQTT_DiagnosticMarker(marker);
}

static int PQC_OTA_ConfirmActiveCandidateIfPending(void)
{
#ifdef SECURE_BOOT_APPLICATION
    PQC_OTA_EmitBootEventMailbox();
    const bool staged = PQC_OTA_MarkerIs(PQC_OTA_MARKER_STAGED_ADDRESS, PQC_OTA_MARKER_STAGED);
    const bool booted = PQC_OTA_MarkerIs(PQC_OTA_MARKER_BOOTED_ADDRESS, PQC_OTA_MARKER_BOOTED);
    const bool confirmed = PQC_OTA_MarkerIs(PQC_OTA_MARKER_CONFIRMED_ADDRESS, PQC_OTA_MARKER_CONFIRMED);
    PQC_OTA_LogApplicationState("boot_state");
    if (staged && booted && !confirmed) {
        const uint32_t manifest_flags = *(const volatile uint32_t *)(uintptr_t)PQC_OTA_MANIFEST_PAYLOAD_FLAGS_ADDRESS;
        if ((manifest_flags & PQC_OTA_FLAG_TEST_NO_CONFIRM) != 0U) {
            PQC_OTA_LogApplicationState("confirmation_withheld");
            PQC_WolfMQTT_DiagnosticMarker("PQC OTA: test candidate intentionally left unconfirmed; reset for rollback\r\n");
            NVIC_SystemReset();
        }
        uint64_t marker = PQC_OTA_MARKER_CONFIRMED;
        if (HAL_FLASH_Unlock() != HAL_OK) return -1;
        __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_DOUBLEWORD, PQC_OTA_MARKER_CONFIRMED_ADDRESS, marker) != HAL_OK) {
            (void)HAL_FLASH_Lock();
            return -1;
        }
        (void)HAL_FLASH_Lock();
        PQC_OTA_LogApplicationState("confirmed");
        PQC_WolfMQTT_DiagnosticMarker("PQC OTA: candidate application confirmed; reset to commit\r\n");
        NVIC_SystemReset();
    }
#endif
    return 0;
}

static uint32_t PQC_OTA_InactivePhysicalBank(void)
{
    return (READ_BIT(SYSCFG->MEMRMP, SYSCFG_MEMRMP_FB_MODE) == 0U) ? FLASH_BANK_2 : FLASH_BANK_1;
}

static int PQC_OTA_EraseInactiveBank(void)
{
    FLASH_EraseInitTypeDef erase = {0};
    uint32_t page_error = 0U;
    HAL_StatusTypeDef rc;
    if (HAL_FLASH_Unlock() != HAL_OK) return -1;
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);
    erase.TypeErase = FLASH_TYPEERASE_PAGES;
    erase.Banks = PQC_OTA_InactivePhysicalBank();
    erase.Page = 0U;
    erase.NbPages = FLASH_BANK_SIZE / FLASH_PAGE_SIZE;
    rc = HAL_FLASHEx_Erase(&erase, &page_error);
    (void)HAL_FLASH_Lock();
    return rc == HAL_OK ? 0 : -1;
}

static int PQC_OTA_Write(uint32_t address, const uint8_t *data, size_t length)
{
    size_t offset = 0U;
    if (data == NULL || address < PQC_OTA_INACTIVE_BASE ||
        (address + length) > (PQC_OTA_INACTIVE_BASE + PQC_OTA_BANK_BYTES)) return -1;
    if (HAL_FLASH_Unlock() != HAL_OK) return -1;
    while (offset < length) {
        uint64_t value = UINT64_MAX;
        size_t amount = length - offset;
        if (amount > 8U) amount = 8U;
        memcpy(&value, data + offset, amount);
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_DOUBLEWORD, address + offset, value) != HAL_OK) {
            (void)HAL_FLASH_Lock(); return -1;
        }
        offset += amount;
    }
    (void)HAL_FLASH_Lock();
    return 0;
}

static bool PQC_OTA_HashMatches(uint32_t address, uint32_t length, const uint8_t expected[32])
{
    uint8_t digest[32];
    PQC_ResultBufferHashData((const uint8_t *)(uintptr_t)address, length, digest);
    return memcmp(digest, expected, sizeof(digest)) == 0;
}

static int PQC_OTA_HexNibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool PQC_OTA_ParseHash(const char *text, uint8_t output[32])
{
    unsigned int i;
    if (text == NULL || strlen(text) != 64U) return false;
    for (i = 0U; i < 32U; ++i) {
        int high = PQC_OTA_HexNibble(text[2U * i]);
        int low = PQC_OTA_HexNibble(text[2U * i + 1U]);
        if (high < 0 || low < 0) return false;
        output[i] = (uint8_t)((high << 4) | low);
    }
    return true;
}

static bool PQC_OTA_ParseRequest(const char *payload, PQC_OtaTransfer *transfer)
{
    char boot_hash[65], manifest_hash[65], app_hash[65];
    unsigned long flags, boot_bytes, manifest_bytes, app_bytes, activate;
    if (payload == NULL || transfer == NULL) return false;
    if (sscanf(payload,
               "request|%lu|%lu|%64[^|]|%lu|%64[^|]|%lu|%64[^|]|%lu",
               &flags, &boot_bytes, boot_hash, &manifest_bytes, manifest_hash,
               &app_bytes, app_hash, &activate) != 8) return false;
    if (boot_bytes == 0UL || boot_bytes > PQC_OTA_BOOTLOADER_BYTES ||
        manifest_bytes == 0UL || manifest_bytes > PQC_OTA_MANIFEST_BYTES ||
        app_bytes == 0UL || app_bytes > PQC_OTA_APPLICATION_BYTES) return false;
    memset(transfer, 0, sizeof(*transfer));
    transfer->flags = (uint32_t)flags;
    transfer->bootloader_bytes = (uint32_t)boot_bytes;
    transfer->manifest_bytes = (uint32_t)manifest_bytes;
    transfer->application_bytes = (uint32_t)app_bytes;
    transfer->activate = activate != 0UL;
    return PQC_OTA_ParseHash(boot_hash, transfer->bootloader_sha256) &&
           PQC_OTA_ParseHash(manifest_hash, transfer->manifest_sha256) &&
           PQC_OTA_ParseHash(app_hash, transfer->application_sha256);
}

static int PQC_OTA_ParseAndWriteChunk(const char *payload, PQC_OtaTransfer *transfer)
{
    char region[16];
    char hex[385];
    unsigned long offset;
    uint8_t bytes[192];
    size_t hex_len, amount, i;
    uint32_t base, limit;
    uint32_t *received;
    if (sscanf(payload, "%15[^|]|%lu|%384s", region, &offset, hex) != 3) return -1;
    hex_len = strlen(hex);
    if ((hex_len & 1U) != 0U || hex_len == 0U || hex_len > sizeof(bytes) * 2U) return -1;
    amount = hex_len / 2U;
    for (i = 0U; i < amount; ++i) {
        int high = PQC_OTA_HexNibble(hex[2U * i]);
        int low = PQC_OTA_HexNibble(hex[2U * i + 1U]);
        if (high < 0 || low < 0) return -1;
        bytes[i] = (uint8_t)((high << 4) | low);
    }
    if (strcmp(region, "bootloader") == 0) {
        base = PQC_OTA_INACTIVE_BASE; limit = transfer->bootloader_bytes; received = &transfer->received_bootloader_bytes;
    } else if (strcmp(region, "manifest") == 0) {
        base = PQC_OTA_MANIFEST_ADDRESS; limit = transfer->manifest_bytes; received = &transfer->received_manifest_bytes;
    } else if (strcmp(region, "application") == 0) {
        base = PQC_OTA_APPLICATION_ADDRESS; limit = transfer->application_bytes; received = &transfer->received_application_bytes;
    } else return -1;
    if (offset + amount > limit) return -1;
    if (PQC_OTA_Write(base + (uint32_t)offset, bytes, amount) != 0) return -1;
    if ((uint32_t)(offset + amount) > *received) *received = (uint32_t)(offset + amount);
    return 0;
}

static int PQC_WolfMQTT_ProcessRetainedOta(
    MqttClient *client, PQC_WolfMQTTMessageContext *message_context, const char *run_id)
{
    MqttSubscribe subscribe;
    MqttTopic topic;
    PQC_OtaTransfer transfer;
    char request_topic[192];
    char data_topic[192];
    int result;
    bool complete = false;

    if (client == NULL || message_context == NULL || run_id == NULL) return MQTT_CODE_ERROR_BAD_ARG;
    (void)snprintf(request_topic, sizeof(request_topic), "pqc/control/ota/stm32/%s/request", run_id);
    memset(&topic, 0, sizeof(topic)); topic.topic_filter = request_topic; topic.qos = MQTT_QOS_1;
    memset(&subscribe, 0, sizeof(subscribe)); subscribe.packet_id = 420U; subscribe.topic_count = 1U; subscribe.topics = &topic;
    result = MqttClient_Subscribe(client, &subscribe);
    if (result != MQTT_CODE_SUCCESS) return result;
    memset(message_context->payload, 0, sizeof(message_context->payload)); message_context->payload_length = 0U; message_context->received = false;
    result = MqttClient_WaitMessage(client, PQC_OTA_CONTROL_WAIT_MS);
    if (result != MQTT_CODE_SUCCESS || !message_context->received) return MQTT_CODE_SUCCESS; /* no OTA requested */
    if (!PQC_OTA_ParseRequest(message_context->payload, &transfer)) return MQTT_CODE_ERROR_BAD_ARG;
    {
        char marker[256];
        (void)snprintf(marker, sizeof(marker),
            "PQC_OTA_APP phase=request_accepted active_bank=%lu inactive_bank=%lu bfb2=%lu flags=%lu boot_bytes=%lu manifest_bytes=%lu app_bytes=%lu\r\n",
            (unsigned long)PQC_OTA_ActivePhysicalBank(),
            (unsigned long)(PQC_OTA_ActivePhysicalBank() == 1U ? 2U : 1U),
            (unsigned long)PQC_OTA_Bfb2Enabled(),
            (unsigned long)transfer.flags,
            (unsigned long)transfer.bootloader_bytes,
            (unsigned long)transfer.manifest_bytes,
            (unsigned long)transfer.application_bytes);
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
    PQC_WolfMQTT_DiagnosticMarker("PQC_OTA_APP phase=erase_inactive_bank_start\r\n");
    if (PQC_OTA_EraseInactiveBank() != 0) return MQTT_CODE_ERROR_NETWORK;
    PQC_WolfMQTT_DiagnosticMarker("PQC_OTA_APP phase=erase_inactive_bank_complete\r\n");

    (void)snprintf(data_topic, sizeof(data_topic), "pqc/control/ota/stm32/%s/data/#", run_id);
    topic.topic_filter = data_topic; subscribe.packet_id = 421U;
    /* Retained data can be delivered synchronously while SUBSCRIBE is being
     * processed. Enter OTA receive mode before subscribing so those messages
     * are parsed and written immediately rather than being overwritten in the
     * single-message scratch buffer. */
    message_context->ota_transfer_mode = true;
    message_context->ota_complete_seen = false;
    message_context->ota_transfer_error = 0;
    message_context->ota_transfer = &transfer;
    message_context->payload_length = 0U;
    message_context->payload[0] = '\0';
    message_context->received = false;
    result = MqttClient_Subscribe(client, &subscribe);
    if (result != MQTT_CODE_SUCCESS) {
        message_context->ota_transfer_mode = false;
        message_context->ota_transfer = NULL;
        return result;
    }
    if (message_context->ota_transfer_error != 0) {
        result = message_context->ota_transfer_error;
        message_context->ota_transfer_mode = false;
        message_context->ota_transfer = NULL;
        return result;
    }

    complete = message_context->ota_complete_seen;
    while (!complete ||
           transfer.received_bootloader_bytes != transfer.bootloader_bytes ||
           transfer.received_manifest_bytes != transfer.manifest_bytes ||
           transfer.received_application_bytes != transfer.application_bytes) {
        message_context->received = false;
        result = MqttClient_WaitMessage(client, PQC_OTA_TRANSFER_WAIT_MS);
        if (result != MQTT_CODE_SUCCESS) {
            message_context->ota_transfer_mode = false;
            message_context->ota_transfer = NULL;
            return MQTT_CODE_ERROR_TIMEOUT;
        }
        if (message_context->ota_transfer_error != 0) {
            result = message_context->ota_transfer_error;
            message_context->ota_transfer_mode = false;
            message_context->ota_transfer = NULL;
            return result;
        }
        complete = message_context->ota_complete_seen;
    }
    message_context->ota_transfer_mode = false;
    message_context->ota_transfer = NULL;
    if (transfer.received_bootloader_bytes != transfer.bootloader_bytes ||
        transfer.received_manifest_bytes != transfer.manifest_bytes ||
        transfer.received_application_bytes != transfer.application_bytes) return MQTT_CODE_ERROR_BAD_ARG;
    {
        char marker[224];
        (void)snprintf(marker, sizeof(marker),
            "PQC_OTA_APP phase=transfer_complete boot_received=%lu manifest_received=%lu app_received=%lu\r\n",
            (unsigned long)transfer.received_bootloader_bytes,
            (unsigned long)transfer.received_manifest_bytes,
            (unsigned long)transfer.received_application_bytes);
        PQC_WolfMQTT_DiagnosticMarker(marker);
    }
    if (!PQC_OTA_HashMatches(PQC_OTA_INACTIVE_BASE, transfer.bootloader_bytes, transfer.bootloader_sha256) ||
        !PQC_OTA_HashMatches(PQC_OTA_MANIFEST_ADDRESS, transfer.manifest_bytes, transfer.manifest_sha256) ||
        !PQC_OTA_HashMatches(PQC_OTA_APPLICATION_ADDRESS, transfer.application_bytes, transfer.application_sha256)) return MQTT_CODE_ERROR_BAD_ARG;
    {
        uint64_t staged = PQC_OTA_MARKER_STAGED;
        if (PQC_OTA_Write(PQC_OTA_MANIFEST_ADDRESS + PQC_OTA_MANIFEST_BYTES - 24U,
                          (const uint8_t *)&staged, sizeof(staged)) != 0)
            return MQTT_CODE_ERROR_NETWORK;
    }

    PQC_WolfMQTT_DiagnosticMarker("PQC_OTA_APP phase=hashes_verified result=passed\r\n");
    PQC_WolfMQTT_DiagnosticMarker("PQC_OTA_APP phase=staged_marker_written staged=1\r\n");
    PQC_WolfMQTT_DiagnosticMarker("PQC OTA: staged candidate bank hashes verified\r\n");
    /* Clear only the retained request trigger before reset. Stale retained data
     * chunks are inert without a request and may be cleaned by the host after
     * evidence collection. This prevents an accepted update from replaying on
     * the newly active bank. */
    if (PQC_WolfMQTT_ClearRetainedTopic(client, request_topic, 422U) != MQTT_CODE_SUCCESS)
        return MQTT_CODE_ERROR_NETWORK;
    if (transfer.activate) {
        PQC_OTA_LogApplicationState("activation_reset");
        PQC_WolfMQTT_DiagnosticMarker("PQC OTA: activation reset requested\r\n");
        NVIC_SystemReset();
    }
    return MQTT_CODE_SUCCESS;
}

int PQC_WolfMQTT_ServiceRetainedOta(PQC_OtaStatus *status)
{
    if (status == NULL) return MQTT_CODE_ERROR_BAD_ARG;
    memset(status, 0, sizeof(*status));
    status->schema_version = PQC_OTA_SCHEMA_VERSION;
    status->active_physical_bank = (PQC_OTA_InactivePhysicalBank() == FLASH_BANK_2) ? 1U : 2U;
    status->inactive_physical_bank = status->active_physical_bank == 1U ? 2U : 1U;
    return MQTT_CODE_SUCCESS;
}
#endif /* PQC_OTA_ENABLED */

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
    memset(&client,0,sizeof(client)); memset(&network,0,sizeof(network)); memset(&socket_context,0,sizeof(socket_context));
    memset(&message_context,0,sizeof(message_context)); socket_context.socket_fd=-1; socket_context.tls_requested=PQC_WolfMQTT_TLSRequested();
    network.context = &socket_context;
    network.connect = PQC_WolfMQTT_LwIPConnect;
    network.read = PQC_WolfMQTT_LwIPRead;
    network.write = PQC_WolfMQTT_LwIPWrite;
    network.disconnect = PQC_WolfMQTT_LwIPDisconnect;
    result=MqttClient_Init(&client,&network,PQC_WolfMQTT_MessageCallback,tx,sizeof(tx),rx,sizeof(rx),PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    status->last_result=result; if(result!=MQTT_CODE_SUCCESS) return result; status->client_initialized=true; client.ctx=&message_context;
    result=MqttClient_NetConnect(&client,PQC_MQTT_BROKER_HOST,(word16)PQC_MQTT_BROKER_PORT,PQC_WOLFMQTT_COMMAND_TIMEOUT_MS,0,NULL);
    status->last_result = result;
    status->tcp_connected = socket_context.tcp_connected;
    status->tls_handshake_complete = socket_context.tls_handshake_complete;
    status->tls_context_created = socket_context.tls_context_created;
    status->tls_session_created = socket_context.tls_session_created;
    status->tls_peer_identity_configured = socket_context.tls_peer_identity_configured;
    status->ca_load_attempted = socket_context.ca_load_attempted;
    status->pqc_group_configured = socket_context.pqc_group_configured;
    status->ca_loaded = socket_context.ca_loaded;
    status->pqc_group_negotiated = socket_context.pqc_group_negotiated;
    status->tls_connect_result = socket_context.tls_connect_result;
    status->tls_error = socket_context.tls_error;
    status->tls_io_error = socket_context.tls_io_error;
    if (result != MQTT_CODE_SUCCESS) goto cleanup;
    memset(&connect,0,sizeof(connect)); connect.keep_alive_sec=PQC_WOLFMQTT_KEEPALIVE_SECONDS; connect.clean_session=1; connect.client_id=PQC_MQTT_CLIENT_ID;
    result=MqttClient_Connect(&client,&connect); status->last_result=result;
    if(result!=MQTT_CODE_SUCCESS) goto cleanup;
    status->mqtt_connected = true;
    memset(&topic,0,sizeof(topic)); topic.topic_filter=PQC_MQTT_COMMAND_TOPIC; topic.qos=MQTT_QOS_0;
    memset(&subscribe,0,sizeof(subscribe)); subscribe.packet_id=PQC_WOLFMQTT_PACKET_ID_SUBSCRIBE; subscribe.topic_count=1; subscribe.topics=&topic;
    result=MqttClient_Subscribe(&client,&subscribe); status->last_result = result;
    if (result != MQTT_CODE_SUCCESS) goto cleanup;
    status->subscribed = true;
    result=MqttClient_WaitMessage(&client,PQC_WOLFMQTT_COMMAND_TIMEOUT_MS); status->last_result=result;
    if ((result != MQTT_CODE_SUCCESS) || !message_context.received) goto cleanup;
    status->message_received = true;
    memset(&publish,0,sizeof(publish)); publish.topic_name=PQC_MQTT_RESPONSE_TOPIC; publish.qos=MQTT_QOS_0;
    publish.packet_id=(word16)(PQC_WOLFMQTT_PACKET_ID_PUBLISH+cycle); publish.buffer=(byte*)PQC_MQTT_CORRELATION_PAYLOAD;
    publish.total_len=(word32)strlen(PQC_MQTT_CORRELATION_PAYLOAD);
    result=MqttClient_Publish(&client,&publish); status->last_result = result;
    if (result == MQTT_CODE_SUCCESS) status->publish_complete = true;
cleanup:
    if(status->mqtt_connected) (void)MqttClient_Disconnect(&client);
    (void)MqttClient_NetDisconnect(&client); MqttClient_DeInit(&client); return status->last_result;
}

int PQC_WolfMQTT_RunPlaintextExchange(PQC_WolfMQTTBuildOnlyStatus *status) { return PQC_WolfMQTT_RunExchangeCycle(status,0U); }


static int PQC_WolfMQTT_PublishText(MqttClient *client, const char *payload, word16 packet_id)
{
    MqttPublish publish;
    if ((client == NULL) || (payload == NULL)) return MQTT_CODE_ERROR_BAD_ARG;
    memset(&publish, 0, sizeof(publish));
    publish.topic_name = PQC_MQTT_RESPONSE_TOPIC;
    publish.qos = MQTT_QOS_0;
    publish.packet_id = packet_id;
    publish.buffer = (byte *)payload;
    publish.total_len = (word32)strlen(payload);
    return MqttClient_Publish(client, &publish);
}

int PQC_WolfMQTT_RunReadyMetricsApplication(void (*mark_complete)(void))
{
    MqttClient client; MqttNet network; MqttConnect connect;
    PQC_WolfMQTTSocketContext socket_context; PQC_WolfMQTTMessageContext message_context;
    byte tx[PQC_WOLFMQTT_BUFFER_SIZE], rx[PQC_WOLFMQTT_BUFFER_SIZE];
    char marker[256];
    TickType_t connect_started, connect_finished;
    int result;

    memset(&client, 0, sizeof(client)); memset(&network, 0, sizeof(network));
    memset(&socket_context, 0, sizeof(socket_context)); memset(&message_context, 0, sizeof(message_context));
    socket_context.socket_fd = -1; socket_context.tls_requested = PQC_WolfMQTT_TLSRequested();
    network.context = &socket_context; network.connect = PQC_WolfMQTT_LwIPConnect;
    network.read = PQC_WolfMQTT_LwIPRead; network.write = PQC_WolfMQTT_LwIPWrite;
    network.disconnect = PQC_WolfMQTT_LwIPDisconnect;

#if PQC_TLS_COMPILED
    if (socket_context.tls_requested && (wolfSSL_Init() != WOLFSSL_SUCCESS)) return MQTT_CODE_ERROR_TLS_CONNECT;
#endif
    result = MqttClient_Init(&client, &network, PQC_WolfMQTT_MessageCallback,
        tx, sizeof(tx), rx, sizeof(rx), PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_tls;
    client.ctx = &message_context;

    connect_started = xTaskGetTickCount();
    PQC_WolfMQTT_DiagnosticMarker("PQC_APP_CONNECT timing=start boundary=before_tcp_connect\r\n");
    result = MqttClient_NetConnect(&client, PQC_MQTT_BROKER_HOST, (word16)PQC_MQTT_BROKER_PORT,
        PQC_WOLFMQTT_COMMAND_TIMEOUT_MS, 0, NULL);
    (void)snprintf(marker, sizeof(marker),
        "PQC_APP_CONNECT stage=network result=%d timeout_ms=%u\r\n",
        result, (unsigned int)PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    PQC_WolfMQTT_DiagnosticMarker(marker);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_client;
    memset(&connect, 0, sizeof(connect)); connect.keep_alive_sec = PQC_WOLFMQTT_KEEPALIVE_SECONDS;
    connect.clean_session = 1; connect.client_id = PQC_MQTT_CLIENT_ID;
    result = MqttClient_Connect(&client, &connect);
    connect_finished = xTaskGetTickCount();
    (void)snprintf(marker, sizeof(marker),
        "PQC_APP_CONNECT stage=mqtt result=%d duration_ms=%lu timeout_ms=%u\r\n",
        result,
        (unsigned long)((connect_finished - connect_started) * portTICK_PERIOD_MS),
        (unsigned int)PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    PQC_WolfMQTT_DiagnosticMarker(marker);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_network;

    PQC_WolfMQTT_DiagnosticMarker(
        "PQC_APP_PUBLISH sequence=1 type=ready state=begin\r\n");
    result = PQC_WolfMQTT_PublishText(&client, "ready", 2U);
    (void)snprintf(marker, sizeof(marker), "PQC_APP_PUBLISH sequence=1 type=ready result=%d\r\n", result);
    PQC_WolfMQTT_DiagnosticMarker(marker);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_mqtt;

    /* Request 15: the experiment broker carries only the workload response.
     * Scientific timing/memory/TLS evidence is retained in RAM and is emitted
     * after this workload returns through the reporting broker. */
    if (mark_complete != NULL) mark_complete();
    result = MQTT_CODE_SUCCESS;

cleanup_mqtt:
    (void)MqttClient_Disconnect(&client);
cleanup_network:
    (void)MqttClient_NetDisconnect(&client);
cleanup_client:
    MqttClient_DeInit(&client);
cleanup_tls:
#if PQC_TLS_COMPILED
    if (socket_context.tls_requested) (void)wolfSSL_Cleanup();
#endif
    return result;
}


const PQC_WolfMQTTReadyMetrics2Snapshot *PQC_WolfMQTT_ReadyMetrics2Snapshot(void)
{
    return &s_ready_metrics_2_snapshot;
}

static int PQC_WolfMQTT_AppendTimingRecord(
    char *buffer,
    size_t buffer_size,
    size_t *offset,
    const PQC_TLSTimingAggregate *timing,
    bool prepend_comma)
{
    int written;
    if ((buffer == NULL) || (offset == NULL) ||
        (timing == NULL) || (*offset >= buffer_size)) {
        return -1;
    }
    /* Records are emitted in the stable enum order documented by the schema.
     * Omitting repeated names keeps every MQTT payload below the existing
     * 512-byte wolfMQTT buffer without increasing firmware RAM usage. */
    written = snprintf(buffer + *offset, buffer_size - *offset,
        "%s[%lu,%lu,%lu,%lu,%lu,%lu]",
        prepend_comma ? "," : "",
        (unsigned long)timing->count,
        (unsigned long)timing->total_cycles,
        (unsigned long)timing->min_cycles,
        (unsigned long)timing->max_cycles,
        (unsigned long)timing->first_start_cycle,
        (unsigned long)timing->last_end_cycle);
    if ((written <= 0) || ((size_t)written >= (buffer_size - *offset))) {
        return -1;
    }
    *offset += (size_t)written;
    return 0;
}

static int PQC_WolfMQTT_PublishReadyMetrics2PrimitivePart(
    MqttClient *client,
    word16 packet_id,
    unsigned int part,
    unsigned int first,
    unsigned int last)
{
    char payload[PQC_WOLFMQTT_BUFFER_SIZE];
    size_t offset;
    unsigned int index;
    int written;
    const PQC_TLSInstrumentationSnapshot *tls = PQC_TLS_InstrumentationSnapshot();

    written = snprintf(payload, sizeof(payload),
        "{\"type\":\"tls_primitive_timing\",\"schema_version\":1,"
        "\"part\":%u,\"first_index\":%u,\"last_index\":%u,\"values\":[",
        part, first, last);
    if ((written <= 0) || ((size_t)written >= sizeof(payload))) return -1;
    offset = (size_t)written;

    for (index = first; index <= last; ++index) {
        if (PQC_WolfMQTT_AppendTimingRecord(payload, sizeof(payload), &offset,
                &tls->primitives[index], index != first) != 0) {
            return -1;
        }
    }
    if (offset + 3U >= sizeof(payload)) return -1;
    payload[offset++] = ']';
    payload[offset++] = '}';
    payload[offset] = '\0';
    return PQC_WolfMQTT_PublishText(client, payload, packet_id);
}

static int PQC_WolfMQTT_PublishReadyMetrics2ResultBundle(
    MqttClient *client,
    const PQC_WolfMQTTSocketContext *socket_context)
{
    char payload[PQC_WOLFMQTT_BUFFER_SIZE];
    size_t offset;
    unsigned int index;
    int written;
    int result;
    const PQC_WolfMQTTReadyMetrics2Snapshot *metrics = &s_ready_metrics_2_snapshot;
    const PQC_TLSInstrumentationSnapshot *tls = PQC_TLS_InstrumentationSnapshot();

    written = snprintf(payload, sizeof(payload),
        "{\"type\":\"experiment_timing\",\"schema_version\":1,"
        "\"ttfb_definition\":\"tcp_connect_start_to_first_mqtt_connack_plaintext_byte\","
        "\"dns_included\":false,\"tcp_connect_ms\":%lu,\"ttfb_ms\":%lu,"
        "\"mqtt_connect_ms\":%lu,\"legacy_connect_timing_ms\":%lu,"
        "\"tls_timing_valid\":%u,\"first_response_valid\":%u}",
        (unsigned long)metrics->tcp_connect_ms,
        (unsigned long)metrics->ttfb_ms,
        (unsigned long)metrics->mqtt_connect_ms,
        (unsigned long)metrics->legacy_connect_timing_ms,
        (unsigned int)metrics->tls_timing_valid,
        (unsigned int)metrics->mqtt_first_response_valid);
    if ((written <= 0) || ((size_t)written >= sizeof(payload))) return -1;
    result = PQC_WolfMQTT_PublishText(client, payload, 6U);
    if (result != MQTT_CODE_SUCCESS) return result;

    written = snprintf(payload, sizeof(payload),
        "{\"type\":\"boot_timing\",\"schema_version\":1,"
        "\"firmware_boot_origin\":\"post_hal_init\","
        "\"boot_to_tcp_connect_ms\":%lu,\"boot_to_tls_complete_ms\":%lu,"
        "\"boot_to_mqtt_first_response_ms\":%lu,\"boot_to_mqtt_connected_ms\":%lu,"
        "\"boot_to_application_first_byte_ms\":%lu,\"boot_to_application_last_byte_ms\":%lu,"
        "\"boot_to_ready_publish_ms\":%lu}",
        (unsigned long)metrics->firmware_boot_to_tcp_connect_ms,
        (unsigned long)metrics->firmware_boot_to_tls_complete_ms,
        (unsigned long)metrics->firmware_boot_to_mqtt_first_response_ms,
        (unsigned long)metrics->firmware_boot_to_mqtt_connected_ms,
        (unsigned long)metrics->firmware_boot_to_application_first_byte_ms,
        (unsigned long)metrics->firmware_boot_to_application_last_byte_ms,
        (unsigned long)metrics->firmware_boot_to_ready_publish_ms);
    if ((written <= 0) || ((size_t)written >= sizeof(payload))) return -1;
    result = PQC_WolfMQTT_PublishText(client, payload, 7U);
    if (result != MQTT_CODE_SUCCESS) return result;

    written = snprintf(payload, sizeof(payload),
        "{\"type\":\"tls_handshake_timing\",\"schema_version\":1,"
        "\"available\":%u,\"result\":%d,\"cycle_counter_available\":%u,"
        "\"elapsed_cycles\":%lu,\"elapsed_ms\":%lu,"
        "\"stack_before_min_free_bytes\":%lu,\"stack_after_min_free_bytes\":%lu,"
        "\"heap_before_free_bytes\":%lu,\"heap_after_free_bytes\":%lu,"
        "\"heap_before_min_ever_free_bytes\":%lu,\"heap_after_min_ever_free_bytes\":%lu}",
        socket_context->tls_requested ? 1U : 0U,
        tls->handshake_result,
        (unsigned int)tls->cycle_counter_available,
        (unsigned long)tls->handshake_elapsed_cycles,
        (unsigned long)tls->handshake_elapsed_ms,
        (unsigned long)tls->stack_before_min_free_bytes,
        (unsigned long)tls->stack_after_min_free_bytes,
        (unsigned long)tls->heap_before_free_bytes,
        (unsigned long)tls->heap_after_free_bytes,
        (unsigned long)tls->heap_before_min_ever_free_bytes,
        (unsigned long)tls->heap_after_min_ever_free_bytes);
    if ((written <= 0) || ((size_t)written >= sizeof(payload))) return -1;
    result = PQC_WolfMQTT_PublishText(client, payload, 8U);
    if (result != MQTT_CODE_SUCCESS) return result;

    written = snprintf(payload, sizeof(payload),
        "{\"type\":\"tls_phase_timing\",\"schema_version\":1,\"values\":[");
    if ((written <= 0) || ((size_t)written >= sizeof(payload))) return -1;
    offset = (size_t)written;
    for (index = 0U; index < (unsigned int)PQC_TLS_PHASE_COUNT; ++index) {
        if (PQC_WolfMQTT_AppendTimingRecord(payload, sizeof(payload), &offset,
                &tls->phases[index], index != 0U) != 0) {
            return -1;
        }
    }
    if (offset + 3U >= sizeof(payload)) return -1;
    payload[offset++] = ']'; payload[offset++] = '}'; payload[offset] = '\0';
    result = PQC_WolfMQTT_PublishText(client, payload, 9U);
    if (result != MQTT_CODE_SUCCESS) return result;

    result = PQC_WolfMQTT_PublishReadyMetrics2PrimitivePart(client, 10U, 1U, 0U, 3U);
    if (result != MQTT_CODE_SUCCESS) return result;
    result = PQC_WolfMQTT_PublishReadyMetrics2PrimitivePart(client, 11U, 2U, 4U, 7U);
    if (result != MQTT_CODE_SUCCESS) return result;
    result = PQC_WolfMQTT_PublishReadyMetrics2PrimitivePart(client, 12U, 3U, 8U, 11U);
    if (result != MQTT_CODE_SUCCESS) return result;
    result = PQC_WolfMQTT_PublishReadyMetrics2PrimitivePart(client, 13U, 4U, 12U, 15U);
    if (result != MQTT_CODE_SUCCESS) return result;
    result = PQC_WolfMQTT_PublishReadyMetrics2PrimitivePart(client, 14U, 5U, 16U, 19U);
    if (result != MQTT_CODE_SUCCESS) return result;
    result = PQC_WolfMQTT_PublishReadyMetrics2PrimitivePart(
        client, 15U, 6U, 20U, (unsigned int)PQC_TLS_PRIMITIVE_COUNT - 1U);
    if (result != MQTT_CODE_SUCCESS) return result;

    written = snprintf(payload, sizeof(payload),
        "{\"type\":\"tls_x509_verify_timing\",\"schema_version\":1,"
        "\"count\":%u,\"overflow\":%u,\"elapsed_cycles\":[%lu,%lu,%lu,%lu]}",
        (unsigned int)tls->x509_verify_invocation_count,
        (unsigned int)tls->x509_verify_invocation_overflow,
        (unsigned long)tls->x509_verify_invocations[0].elapsed_cycles,
        (unsigned long)tls->x509_verify_invocations[1].elapsed_cycles,
        (unsigned long)tls->x509_verify_invocations[2].elapsed_cycles,
        (unsigned long)tls->x509_verify_invocations[3].elapsed_cycles);
    if ((written <= 0) || ((size_t)written >= sizeof(payload))) return -1;
    result = PQC_WolfMQTT_PublishText(client, payload, 16U);
    if (result != MQTT_CODE_SUCCESS) return result;

    written = snprintf(payload, sizeof(payload),
        "{\"type\":\"application_transfer_timing\",\"schema_version\":1,"
        "\"ttlb_definition\":\"tcp_connect_start_to_last_byte_of_requested_application_payload\","
        "\"direction\":\"broker_to_stm32\",\"payload_bytes\":%lu,"
        "\"received_bytes\":%lu,\"message_count\":%lu,\"chunk_bytes\":%u,"
        "\"application_ttfb_ms\":%lu,\"ttlb_ms\":%lu,"
        "\"request_to_first_byte_ms\":%lu,\"application_transfer_ms\":%lu,"
        "\"first_byte_valid\":%u,\"last_byte_valid\":%u,\"complete_valid\":%u}",
        (unsigned long)metrics->transfer_payload_bytes,
        (unsigned long)metrics->transfer_received_bytes,
        (unsigned long)metrics->transfer_message_count,
        (unsigned int)PQC_MQTT_TRANSFER_CHUNK_BYTES,
        (unsigned long)metrics->application_ttfb_ms,
        (unsigned long)metrics->ttlb_ms,
        (unsigned long)metrics->application_request_to_first_byte_ms,
        (unsigned long)metrics->application_transfer_ms,
        (unsigned int)metrics->application_first_byte_valid,
        (unsigned int)metrics->application_last_byte_valid,
        (unsigned int)metrics->transfer_complete_valid);
    if ((written <= 0) || ((size_t)written >= sizeof(payload))) return -1;
    result = PQC_WolfMQTT_PublishText(client, payload, 17U);
    if (result != MQTT_CODE_SUCCESS) return result;

    written = snprintf(payload, sizeof(payload),
        "{\"type\":\"ready_metrics_2_complete\",\"schema_version\":1,"
        "\"status\":\"success\",\"message_count\":17}");
    if ((written <= 0) || ((size_t)written >= sizeof(payload))) return -1;
    return PQC_WolfMQTT_PublishText(client, payload, 18U);
}

int PQC_WolfMQTT_RunReadyMetrics2Application(
    void (*mark_complete)(void),
    uint32_t firmware_boot_origin_tick_ms)
{
    MqttClient client; MqttNet network; MqttConnect connect;
    MqttSubscribe transfer_subscribe; MqttTopic transfer_topic; MqttPublish transfer_request;
    PQC_WolfMQTTSocketContext socket_context; PQC_WolfMQTTMessageContext message_context;
    byte tx[PQC_WOLFMQTT_BUFFER_SIZE], rx[PQC_WOLFMQTT_BUFFER_SIZE];
    char marker[256];
    TickType_t legacy_connect_started, legacy_connect_finished;
    int result;

    memset(&s_ready_metrics_2_snapshot, 0, sizeof(s_ready_metrics_2_snapshot));
    s_ready_metrics_2_snapshot.schema_version = 1U;
    s_ready_metrics_2_snapshot.firmware_boot_origin_tick_ms =
        firmware_boot_origin_tick_ms;

    memset(&client, 0, sizeof(client)); memset(&network, 0, sizeof(network));
    memset(&socket_context, 0, sizeof(socket_context)); memset(&message_context, 0, sizeof(message_context));
    socket_context.socket_fd = -1;
    socket_context.tls_requested = PQC_WolfMQTT_TLSRequested();
    socket_context.ready_metrics_2 = &s_ready_metrics_2_snapshot;
    socket_context.suppress_success_diagnostics = true;
    network.context = &socket_context; network.connect = PQC_WolfMQTT_LwIPConnect;
    network.read = PQC_WolfMQTT_LwIPRead; network.write = PQC_WolfMQTT_LwIPWrite;
    network.disconnect = PQC_WolfMQTT_LwIPDisconnect;

#if PQC_TLS_COMPILED
    if (socket_context.tls_requested && (wolfSSL_Init() != WOLFSSL_SUCCESS)) return MQTT_CODE_ERROR_TLS_CONNECT;
#endif
    result = MqttClient_Init(&client, &network, PQC_WolfMQTT_MessageCallback,
        tx, sizeof(tx), rx, sizeof(rx), PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_tls;
    client.ctx = &message_context;

    /* Legacy Ready Metrics timing is retained separately for continuity. The
     * paper-comparable TTFB origin is captured later, immediately before the
     * actual lwip_connect() call and therefore excludes DNS resolution. */
    legacy_connect_started = xTaskGetTickCount();
    result = MqttClient_NetConnect(&client, PQC_MQTT_BROKER_HOST,
        (word16)PQC_MQTT_BROKER_PORT, PQC_WOLFMQTT_COMMAND_TIMEOUT_MS, 0, NULL);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_client;

    socket_context.mqtt_first_response_armed = true;
    memset(&connect, 0, sizeof(connect));
    connect.keep_alive_sec = PQC_WOLFMQTT_KEEPALIVE_SECONDS;
    connect.clean_session = 1;
    connect.client_id = PQC_MQTT_CLIENT_ID;
    result = MqttClient_Connect(&client, &connect);
    socket_context.mqtt_first_response_armed = false;
    legacy_connect_finished = xTaskGetTickCount();
    s_ready_metrics_2_snapshot.legacy_connect_timing_ms =
        (uint32_t)((legacy_connect_finished - legacy_connect_started) * portTICK_PERIOD_MS);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_network;

    s_ready_metrics_2_snapshot.mqtt_connected_tick_ms = HAL_GetTick();
    s_ready_metrics_2_snapshot.mqtt_connect_ms =
        s_ready_metrics_2_snapshot.mqtt_connected_tick_ms -
        s_ready_metrics_2_snapshot.ttfb_start_tick_ms;
    s_ready_metrics_2_snapshot.firmware_boot_to_mqtt_connected_ms =
        s_ready_metrics_2_snapshot.mqtt_connected_tick_ms -
        s_ready_metrics_2_snapshot.firmware_boot_origin_tick_ms;
    s_ready_metrics_2_snapshot.mqtt_connected_valid = 1U;

    /* Paper-aligned TTLB workload. The application requests a fixed amount of
     * data and the broker-side responder sends that payload back over this
     * already-established MQTT/TLS connection. The TTLB origin remains the
     * TCP connect start, matching Kampanakis/Childs-Klein. No application
     * diagnostics or result formatting occurs until the final response byte
     * has been received. */
    memset(&transfer_topic, 0, sizeof(transfer_topic));
    transfer_topic.topic_filter = PQC_MQTT_TRANSFER_RESPONSE_TOPIC;
    transfer_topic.qos = MQTT_QOS_0;
    memset(&transfer_subscribe, 0, sizeof(transfer_subscribe));
    transfer_subscribe.packet_id = 2U;
    transfer_subscribe.topic_count = 1;
    transfer_subscribe.topics = &transfer_topic;
    result = MqttClient_Subscribe(&client, &transfer_subscribe);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_mqtt;

    message_context.transfer_mode = true;
    message_context.transfer_expected_bytes = (uint32_t)PQC_MQTT_TRANSFER_PAYLOAD_BYTES;
    message_context.transfer_received_bytes = 0U;
    message_context.transfer_message_count = 0U;
    message_context.transfer_first_byte_valid = false;
    message_context.transfer_complete = false;

    memset(&transfer_request, 0, sizeof(transfer_request));
    transfer_request.topic_name = PQC_MQTT_TRANSFER_REQUEST_TOPIC;
    transfer_request.qos = MQTT_QOS_0;
    transfer_request.packet_id = 3U;
    transfer_request.buffer = (byte *)PQC_MQTT_TRANSFER_REQUEST_PAYLOAD;
    transfer_request.total_len = (word32)strlen(PQC_MQTT_TRANSFER_REQUEST_PAYLOAD);

    s_ready_metrics_2_snapshot.application_request_tick_ms = HAL_GetTick();
    result = MqttClient_Publish(&client, &transfer_request);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_mqtt;

    while (!message_context.transfer_complete) {
        result = MqttClient_WaitMessage(&client, PQC_WOLFMQTT_COMMAND_TIMEOUT_MS);
        if (result != MQTT_CODE_SUCCESS) goto cleanup_mqtt;
    }

    if ((message_context.transfer_received_bytes !=
            (uint32_t)PQC_MQTT_TRANSFER_PAYLOAD_BYTES) ||
        !message_context.transfer_first_byte_valid) {
        result = -1;
        goto cleanup_mqtt;
    }

    s_ready_metrics_2_snapshot.application_first_byte_tick_ms =
        message_context.transfer_first_byte_tick_ms;
    s_ready_metrics_2_snapshot.application_last_byte_tick_ms =
        message_context.transfer_last_byte_tick_ms;
    s_ready_metrics_2_snapshot.application_ttfb_ms =
        s_ready_metrics_2_snapshot.application_first_byte_tick_ms -
        s_ready_metrics_2_snapshot.ttfb_start_tick_ms;
    s_ready_metrics_2_snapshot.ttlb_ms =
        s_ready_metrics_2_snapshot.application_last_byte_tick_ms -
        s_ready_metrics_2_snapshot.ttfb_start_tick_ms;
    s_ready_metrics_2_snapshot.application_request_to_first_byte_ms =
        s_ready_metrics_2_snapshot.application_first_byte_tick_ms -
        s_ready_metrics_2_snapshot.application_request_tick_ms;
    s_ready_metrics_2_snapshot.application_transfer_ms =
        s_ready_metrics_2_snapshot.application_last_byte_tick_ms -
        s_ready_metrics_2_snapshot.application_first_byte_tick_ms;
    s_ready_metrics_2_snapshot.transfer_payload_bytes =
        (uint32_t)PQC_MQTT_TRANSFER_PAYLOAD_BYTES;
    s_ready_metrics_2_snapshot.transfer_received_bytes =
        message_context.transfer_received_bytes;
    s_ready_metrics_2_snapshot.transfer_message_count =
        message_context.transfer_message_count;
    s_ready_metrics_2_snapshot.firmware_boot_to_application_first_byte_ms =
        s_ready_metrics_2_snapshot.application_first_byte_tick_ms -
        s_ready_metrics_2_snapshot.firmware_boot_origin_tick_ms;
    s_ready_metrics_2_snapshot.firmware_boot_to_application_last_byte_ms =
        s_ready_metrics_2_snapshot.application_last_byte_tick_ms -
        s_ready_metrics_2_snapshot.firmware_boot_origin_tick_ms;
    s_ready_metrics_2_snapshot.application_first_byte_valid = 1U;
    s_ready_metrics_2_snapshot.application_last_byte_valid = 1U;
    s_ready_metrics_2_snapshot.transfer_complete_valid = 1U;
    s_ready_metrics_2_snapshot.measurement_complete_tick_ms =
        s_ready_metrics_2_snapshot.application_last_byte_tick_ms;
    message_context.transfer_mode = false;

    /* Compatibility evidence is published only after the paper-aligned
     * transfer has finished so it cannot warm the TCP congestion window or
     * otherwise perturb the measured TTLB. */
    result = PQC_WolfMQTT_PublishText(&client, "ready", 4U);
    if (result != MQTT_CODE_SUCCESS) goto cleanup_mqtt;
    s_ready_metrics_2_snapshot.ready_published_tick_ms = HAL_GetTick();
    s_ready_metrics_2_snapshot.firmware_boot_to_ready_publish_ms =
        s_ready_metrics_2_snapshot.ready_published_tick_ms -
        s_ready_metrics_2_snapshot.firmware_boot_origin_tick_ms;
    s_ready_metrics_2_snapshot.ready_publish_valid = 1U;

    /* All scientific result serialization/publication is deferred until after
     * this workload returns. The RAM snapshot above remains authoritative. */
    if (mark_complete != NULL) mark_complete();
    result = MQTT_CODE_SUCCESS;

cleanup_mqtt:
    (void)MqttClient_Disconnect(&client);
cleanup_network:
    (void)MqttClient_NetDisconnect(&client);
cleanup_client:
    MqttClient_DeInit(&client);
cleanup_tls:
#if PQC_TLS_COMPILED
    if (socket_context.tls_requested) (void)wolfSSL_Cleanup();
#endif
    return result;
}

bool PQC_WolfMQTT_RuntimeStatusLine(char *buffer,size_t size,const char *context,bool scheduler_running)
{
    PQC_WolfMQTTBuildOnlyStatus first; int result; int written;
    if((buffer==NULL)||(size==0U)||(context==NULL)) return false;
#if (PQC_MQTT_ENABLED != 0)
    PQC_WolfMQTTBuildOnlyStatus second;
    int reconnect_result=MQTT_CODE_SUCCESS;
    bool reconnect_attempted=false;
#if PQC_TLS_COMPILED
    if (PQC_WolfMQTT_TLSRequested()) {
        int wolfssl_init_result = wolfSSL_Init();
        PQC_WolfMQTT_DiagnosticCode("wolfssl_init", wolfssl_init_result, 0);
        if (wolfssl_init_result != WOLFSSL_SUCCESS) {
            PQC_WolfMQTT_DiagnosticWolfSSLState("wolfssl_init");
        }
    }
#endif
    result=PQC_WolfMQTT_RunExchangeCycle(&first,0U);
    if((result==MQTT_CODE_SUCCESS)&&(PQC_MQTT_RECONNECT_ATTEMPTS>0)) { reconnect_attempted=true; reconnect_result=PQC_WolfMQTT_RunExchangeCycle(&second,1U); } else memset(&second,0,sizeof(second));
#if PQC_TLS_COMPILED
    if (PQC_WolfMQTT_TLSRequested()) (void)wolfSSL_Cleanup();
#endif
    written=snprintf(buffer,size,
      "wolfMQTT runtime: context=%s scheduler=%s evidence=%s backend=%s result=%d transport=%s tcp=%s tls_context=%s tls_session=%s tls_peer_identity=%s tls_handshake=%s pqc_group_config=%s ca_load=%s pqc_group=%s tls_connect_result=%d tls_error=%d tls_io_error=%d mqtt_connect=%s mqtt_subscribe=%s mqtt_receive=%s mqtt_publish=%s reconnect=%s reconnect_tls_handshake=%s reconnect_pqc_group=%s reconnect_publish=%s end_to_end=%s broker=%s:%u correlation=%s\r\n",
      context,scheduler_running?"running":"not_started",PQC_WolfMQTT_PQCHybridRequested()?"stm32-st67-pqc-hybrid-tls-e2e":(PQC_WolfMQTT_PQCStandaloneRequested()?"stm32-st67-pqc-tls-e2e":(PQC_WolfMQTT_TLSRequested()?"stm32-st67-classical-tls-e2e":"stm32-st67-plaintext-mqtt-e2e")),
      PQC_WolfMQTT_BackendName(first.backend),result,first.transport_available?"available":"unavailable",first.tcp_connected?"passed":"failed",
      PQC_WolfMQTT_TLSRequested()?(first.tls_context_created?"passed":"failed"):"not_required",
      PQC_WolfMQTT_TLSRequested()?(first.tls_session_created?"passed":(first.tls_context_created?"failed":"not_run")):"not_required",
      PQC_WolfMQTT_TLSRequested()?(first.tls_peer_identity_configured?"passed":(first.tls_session_created?"failed":"not_run")):"not_required",
      first.tls_handshake_complete?"passed":(PQC_WolfMQTT_TLSRequested()?"failed":"not_required"),
      PQC_WolfMQTT_PQCHybridRequested()?(first.pqc_group_configured?"passed":"failed"):"not_required",
      PQC_WolfMQTT_TLSRequested()?(first.ca_load_attempted?(first.ca_loaded?"passed":"failed"):"not_run"):"not_required",
      PQC_WolfMQTT_PQCHybridRequested()?(first.pqc_group_negotiated?"passed":(first.tls_handshake_complete?"failed":"not_run")):"not_required",
      first.tls_connect_result,first.tls_error,first.tls_io_error,first.mqtt_connected?"passed":"failed",
      first.subscribed?"passed":"failed",first.message_received?"passed":"failed",first.publish_complete?"passed":"failed",
      reconnect_attempted?(reconnect_result==MQTT_CODE_SUCCESS?"passed":"failed"):"not_run",
      reconnect_attempted?(second.tls_handshake_complete?"passed":"failed"):"not_run",
      reconnect_attempted?(PQC_WolfMQTT_PQCHybridRequested()?(second.pqc_group_negotiated?"passed":"failed"):"not_required"):"not_run",
      reconnect_attempted?(second.publish_complete?"passed":"failed"):"not_run",
      (first.publish_complete&&((PQC_MQTT_RECONNECT_ATTEMPTS==0)||second.publish_complete))?"passed":"failed",
      PQC_MQTT_BROKER_HOST,(unsigned)PQC_MQTT_BROKER_PORT,PQC_MQTT_CORRELATION_PAYLOAD);
#else
    result=PQC_WolfMQTT_BuildOnly_Initialize(PQC_WOLFMQTT_BACKEND_FAKE_NO_NETWORK,&first);
    written=snprintf(buffer,size,"wolfMQTT runtime smoke: context=%s scheduler=%s evidence=stm32-fake-no-network-initialization-only init_result=%d\r\n",context,scheduler_running?"running":"not_started",result);
#endif
    return written>=0&&(size_t)written<size;
}
