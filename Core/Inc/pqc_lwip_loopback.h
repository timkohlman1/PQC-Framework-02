#ifndef PQC_LWIP_LOOPBACK_H
#define PQC_LWIP_LOOPBACK_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PQC_LWIP_LOOPBACK_SCHEMA_VERSION 1U

typedef enum
{
  PQC_LWIP_LOOPBACK_RESULT_NOT_RUN = 0,
  PQC_LWIP_LOOPBACK_RESULT_PASSED,
  PQC_LWIP_LOOPBACK_RESULT_INIT_TIMEOUT,
  PQC_LWIP_LOOPBACK_RESULT_PCB_CREATE_FAILED,
  PQC_LWIP_LOOPBACK_RESULT_BIND_FAILED,
  PQC_LWIP_LOOPBACK_RESULT_ALLOC_FAILED,
  PQC_LWIP_LOOPBACK_RESULT_SEND_FAILED,
  PQC_LWIP_LOOPBACK_RESULT_RECEIVE_TIMEOUT,
  PQC_LWIP_LOOPBACK_RESULT_PAYLOAD_MISMATCH
} PQC_LwIPLoopbackResult;

typedef struct
{
  uint32_t schema_version;
  PQC_LwIPLoopbackResult result;
  uint16_t destination_port;
  uint16_t payload_length;
  uint16_t received_length;
  bool tcpip_core_ready;
  bool datagram_sent;
  bool datagram_received;
  bool payload_matched;
} PQC_LwIPLoopbackStatus;

PQC_LwIPLoopbackStatus PQC_LwIP_Loopback_RunUdpSmoke(void);
const char *PQC_LwIP_Loopback_ResultName(PQC_LwIPLoopbackResult result);
bool PQC_LwIP_Loopback_StatusLine(
    char *buffer,
    uint32_t buffer_length,
    const PQC_LwIPLoopbackStatus *status);

#ifdef __cplusplus
}
#endif

#endif /* PQC_LWIP_LOOPBACK_H */
