#include "pqc_lwip_loopback.h"

#include "cmsis_os2.h"
#include "lwip/ip_addr.h"
#include "lwip/pbuf.h"
#include "lwip/tcpip.h"
#include "lwip/udp.h"

#include <stdio.h>
#include <string.h>

#define PQC_LWIP_LOOPBACK_PORT 49152U
#define PQC_LWIP_LOOPBACK_INIT_TIMEOUT_MS 2000U
#define PQC_LWIP_LOOPBACK_RECEIVE_TIMEOUT_MS 2000U
#define PQC_LWIP_LOOPBACK_POLL_DELAY_MS 1U

static const uint8_t kLoopbackPayload[] = "pqc-lwip-local-loopback";

static volatile bool s_tcpip_ready = false;
static volatile bool s_receive_complete = false;
static volatile uint16_t s_received_length = 0U;
static volatile bool s_payload_matched = false;

static void PQC_LwIP_Loopback_TcpipReady(void *argument)
{
  (void)argument;
  s_tcpip_ready = true;
}

static void PQC_LwIP_Loopback_Receive(
    void *argument,
    struct udp_pcb *pcb,
    struct pbuf *packet,
    const ip_addr_t *source_address,
    u16_t source_port)
{
  (void)argument;
  (void)pcb;
  (void)source_address;
  (void)source_port;

  if (packet != NULL)
  {
    const uint16_t expected_length = (uint16_t)(sizeof(kLoopbackPayload) - 1U);
    uint8_t received[sizeof(kLoopbackPayload) - 1U];

    s_received_length = packet->tot_len;
    if ((packet->tot_len == expected_length) &&
        (pbuf_copy_partial(packet, received, expected_length, 0U) == expected_length) &&
        (memcmp(received, kLoopbackPayload, expected_length) == 0))
    {
      s_payload_matched = true;
    }

    pbuf_free(packet);
  }

  s_receive_complete = true;
}

static bool PQC_LwIP_Loopback_WaitForFlag(volatile bool *flag, uint32_t timeout_ms)
{
  uint32_t elapsed_ms = 0U;

  while ((!(*flag)) && (elapsed_ms < timeout_ms))
  {
    osDelay(PQC_LWIP_LOOPBACK_POLL_DELAY_MS);
    elapsed_ms += PQC_LWIP_LOOPBACK_POLL_DELAY_MS;
  }

  return *flag;
}

PQC_LwIPLoopbackStatus PQC_LwIP_Loopback_RunUdpSmoke(void)
{
  PQC_LwIPLoopbackStatus status = {
      .schema_version = PQC_LWIP_LOOPBACK_SCHEMA_VERSION,
      .result = PQC_LWIP_LOOPBACK_RESULT_NOT_RUN,
      .destination_port = PQC_LWIP_LOOPBACK_PORT,
      .payload_length = (uint16_t)(sizeof(kLoopbackPayload) - 1U),
      .received_length = 0U,
      .tcpip_core_ready = false,
      .datagram_sent = false,
      .datagram_received = false,
      .payload_matched = false,
  };

  s_tcpip_ready = false;
  s_receive_complete = false;
  s_received_length = 0U;
  s_payload_matched = false;

  tcpip_init(PQC_LwIP_Loopback_TcpipReady, NULL);
  if (!PQC_LwIP_Loopback_WaitForFlag(&s_tcpip_ready, PQC_LWIP_LOOPBACK_INIT_TIMEOUT_MS))
  {
    status.result = PQC_LWIP_LOOPBACK_RESULT_INIT_TIMEOUT;
    return status;
  }
  status.tcpip_core_ready = true;

  LOCK_TCPIP_CORE();

  struct udp_pcb *pcb = udp_new_ip_type(IPADDR_TYPE_V4);
  if (pcb == NULL)
  {
    UNLOCK_TCPIP_CORE();
    status.result = PQC_LWIP_LOOPBACK_RESULT_PCB_CREATE_FAILED;
    return status;
  }

  err_t error = udp_bind(pcb, IP_ANY_TYPE, PQC_LWIP_LOOPBACK_PORT);
  if (error != ERR_OK)
  {
    udp_remove(pcb);
    UNLOCK_TCPIP_CORE();
    status.result = PQC_LWIP_LOOPBACK_RESULT_BIND_FAILED;
    return status;
  }

  udp_recv(pcb, PQC_LwIP_Loopback_Receive, NULL);

  struct pbuf *packet = pbuf_alloc(
      PBUF_TRANSPORT,
      (u16_t)(sizeof(kLoopbackPayload) - 1U),
      PBUF_RAM);
  if (packet == NULL)
  {
    udp_remove(pcb);
    UNLOCK_TCPIP_CORE();
    status.result = PQC_LWIP_LOOPBACK_RESULT_ALLOC_FAILED;
    return status;
  }

  error = pbuf_take(packet, kLoopbackPayload, sizeof(kLoopbackPayload) - 1U);
  if (error == ERR_OK)
  {
    const ip_addr_t loopback_address = IPADDR4_INIT_BYTES(127, 0, 0, 1);
    error = udp_sendto(pcb, packet, &loopback_address, PQC_LWIP_LOOPBACK_PORT);
  }

  pbuf_free(packet);
  UNLOCK_TCPIP_CORE();

  if (error != ERR_OK)
  {
    LOCK_TCPIP_CORE();
    udp_remove(pcb);
    UNLOCK_TCPIP_CORE();
    status.result = PQC_LWIP_LOOPBACK_RESULT_SEND_FAILED;
    return status;
  }
  status.datagram_sent = true;

  if (!PQC_LwIP_Loopback_WaitForFlag(&s_receive_complete, PQC_LWIP_LOOPBACK_RECEIVE_TIMEOUT_MS))
  {
    LOCK_TCPIP_CORE();
    udp_remove(pcb);
    UNLOCK_TCPIP_CORE();
    status.result = PQC_LWIP_LOOPBACK_RESULT_RECEIVE_TIMEOUT;
    return status;
  }

  LOCK_TCPIP_CORE();
  udp_remove(pcb);
  UNLOCK_TCPIP_CORE();

  status.datagram_received = true;
  status.received_length = s_received_length;
  status.payload_matched = s_payload_matched;
  status.result = s_payload_matched
      ? PQC_LWIP_LOOPBACK_RESULT_PASSED
      : PQC_LWIP_LOOPBACK_RESULT_PAYLOAD_MISMATCH;

  return status;
}

const char *PQC_LwIP_Loopback_ResultName(PQC_LwIPLoopbackResult result)
{
  switch (result)
  {
    case PQC_LWIP_LOOPBACK_RESULT_PASSED:
      return "passed";
    case PQC_LWIP_LOOPBACK_RESULT_INIT_TIMEOUT:
      return "init_timeout";
    case PQC_LWIP_LOOPBACK_RESULT_PCB_CREATE_FAILED:
      return "pcb_create_failed";
    case PQC_LWIP_LOOPBACK_RESULT_BIND_FAILED:
      return "bind_failed";
    case PQC_LWIP_LOOPBACK_RESULT_ALLOC_FAILED:
      return "alloc_failed";
    case PQC_LWIP_LOOPBACK_RESULT_SEND_FAILED:
      return "send_failed";
    case PQC_LWIP_LOOPBACK_RESULT_RECEIVE_TIMEOUT:
      return "receive_timeout";
    case PQC_LWIP_LOOPBACK_RESULT_PAYLOAD_MISMATCH:
      return "payload_mismatch";
    case PQC_LWIP_LOOPBACK_RESULT_NOT_RUN:
    default:
      return "not_run";
  }
}

bool PQC_LwIP_Loopback_StatusLine(
    char *buffer,
    uint32_t buffer_length,
    const PQC_LwIPLoopbackStatus *status)
{
  if ((buffer == NULL) || (buffer_length == 0U) || (status == NULL))
  {
    return false;
  }

  const int written = snprintf(
      buffer,
      (size_t)buffer_length,
      "lwIP local loopback smoke: context=freertos_task scheduler=running evidence=stm32-local-lwip-loopback-only protocol=udp address=127.0.0.1 port=%u result=%s tcpip_core_ready=%u sent=%u received=%u payload_bytes=%u received_bytes=%u payload_match=%u wifi_module=unavailable link=unavailable hardware_ip_acquisition=unavailable external_ping=unavailable external_tcp=unavailable tls_handshake=unavailable mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable broker_access=unavailable st67w61m1=unavailable end_to_end=unavailable\r\n",
      (unsigned)status->destination_port,
      PQC_LwIP_Loopback_ResultName(status->result),
      status->tcpip_core_ready ? 1U : 0U,
      status->datagram_sent ? 1U : 0U,
      status->datagram_received ? 1U : 0U,
      (unsigned)status->payload_length,
      (unsigned)status->received_length,
      status->payload_matched ? 1U : 0U);

  if ((written < 0) || ((uint32_t)written >= buffer_length))
  {
    buffer[0] = '\0';
    return false;
  }

  return true;
}
