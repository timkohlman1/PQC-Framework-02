#ifndef PQC_WOLFSSL_TRANSPORT_H
#define PQC_WOLFSSL_TRANSPORT_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PQC_WOLFSSL_TRANSPORT_SCHEMA_VERSION 1U

typedef enum
{
  PQC_WOLFSSL_TRANSPORT_RESULT_UNAVAILABLE = -1,
  PQC_WOLFSSL_TRANSPORT_RESULT_INVALID_ARGUMENT = -2
} PQC_WolfSSLTransportResult;

typedef struct
{
  uint32_t schema_version;
  bool boundary_present;
  bool callbacks_present;
  bool network_boundary_present;
  bool connect_available;
  bool read_available;
  bool write_available;
  bool socket_io_performed;
  bool tls_handshake_available;
} PQC_WolfSSLTransportStatus;

void PQC_WolfSSL_Transport_Init(void);
PQC_WolfSSLTransportStatus PQC_WolfSSL_Transport_GetStatus(void);
PQC_WolfSSLTransportResult PQC_WolfSSL_Transport_Connect(void);
PQC_WolfSSLTransportResult PQC_WolfSSL_Transport_Read(
    uint8_t *buffer,
    uint32_t buffer_length,
    uint32_t *bytes_read);
PQC_WolfSSLTransportResult PQC_WolfSSL_Transport_Write(
    const uint8_t *buffer,
    uint32_t buffer_length,
    uint32_t *bytes_written);
int PQC_WolfSSL_Transport_RecvCallback(
    void *wolfssl_session,
    char *buffer,
    int buffer_length,
    void *context);
int PQC_WolfSSL_Transport_SendCallback(
    void *wolfssl_session,
    char *buffer,
    int buffer_length,
    void *context);
const char *PQC_WolfSSL_Transport_EvidenceLabel(void);
const char *PQC_WolfSSL_Transport_UnavailableReason(void);
bool PQC_WolfSSL_Transport_StatusLine(char *buffer, uint32_t buffer_length);

#ifdef __cplusplus
}
#endif

#endif /* PQC_WOLFSSL_TRANSPORT_H */
