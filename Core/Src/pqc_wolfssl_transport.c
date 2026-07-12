#include "pqc_wolfssl_transport.h"

#include "pqc_network_interface.h"

#include <stddef.h>
#include <stdio.h>

/*
 * Phase M6.3 project-owned wolfSSL transport boundary.
 *
 * These wrappers and callback-shaped functions deliberately perform no socket
 * I/O. They consume the Phase M6.2 network-interface status only to preserve a
 * clean future integration point and always report unavailable transport.
 */

static bool s_pqc_wolfssl_transport_initialized = false;

void PQC_WolfSSL_Transport_Init(void)
{
  PQC_NetworkInterface_Init();
  s_pqc_wolfssl_transport_initialized = true;
}

PQC_WolfSSLTransportStatus PQC_WolfSSL_Transport_GetStatus(void)
{
  if (!s_pqc_wolfssl_transport_initialized)
  {
    PQC_WolfSSL_Transport_Init();
  }

  const PQC_NetworkInterfaceStatus network_status =
      PQC_NetworkInterface_GetStatus();
  const PQC_WolfSSLTransportStatus status = {
      .schema_version = PQC_WOLFSSL_TRANSPORT_SCHEMA_VERSION,
      .boundary_present = true,
      .callbacks_present = true,
      .network_boundary_present = network_status.boundary_present,
      .connect_available = false,
      .read_available = false,
      .write_available = false,
      .socket_io_performed = false,
      .tls_handshake_available = false,
  };

  return status;
}

PQC_WolfSSLTransportResult PQC_WolfSSL_Transport_Connect(void)
{
  (void)PQC_WolfSSL_Transport_GetStatus();
  return PQC_WOLFSSL_TRANSPORT_RESULT_UNAVAILABLE;
}

PQC_WolfSSLTransportResult PQC_WolfSSL_Transport_Read(
    uint8_t *buffer,
    uint32_t buffer_length,
    uint32_t *bytes_read)
{
  if (bytes_read == NULL)
  {
    return PQC_WOLFSSL_TRANSPORT_RESULT_INVALID_ARGUMENT;
  }

  *bytes_read = 0U;
  if ((buffer == NULL) && (buffer_length > 0U))
  {
    return PQC_WOLFSSL_TRANSPORT_RESULT_INVALID_ARGUMENT;
  }

  return PQC_WOLFSSL_TRANSPORT_RESULT_UNAVAILABLE;
}

PQC_WolfSSLTransportResult PQC_WolfSSL_Transport_Write(
    const uint8_t *buffer,
    uint32_t buffer_length,
    uint32_t *bytes_written)
{
  if (bytes_written == NULL)
  {
    return PQC_WOLFSSL_TRANSPORT_RESULT_INVALID_ARGUMENT;
  }

  *bytes_written = 0U;
  if ((buffer == NULL) && (buffer_length > 0U))
  {
    return PQC_WOLFSSL_TRANSPORT_RESULT_INVALID_ARGUMENT;
  }

  return PQC_WOLFSSL_TRANSPORT_RESULT_UNAVAILABLE;
}

int PQC_WolfSSL_Transport_RecvCallback(
    void *wolfssl_session,
    char *buffer,
    int buffer_length,
    void *context)
{
  uint32_t bytes_read = 0U;
  (void)wolfssl_session;
  (void)context;

  if (buffer_length < 0)
  {
    return (int)PQC_WOLFSSL_TRANSPORT_RESULT_INVALID_ARGUMENT;
  }

  return (int)PQC_WolfSSL_Transport_Read(
      (uint8_t *)buffer,
      (uint32_t)buffer_length,
      &bytes_read);
}

int PQC_WolfSSL_Transport_SendCallback(
    void *wolfssl_session,
    char *buffer,
    int buffer_length,
    void *context)
{
  uint32_t bytes_written = 0U;
  (void)wolfssl_session;
  (void)context;

  if (buffer_length < 0)
  {
    return (int)PQC_WOLFSSL_TRANSPORT_RESULT_INVALID_ARGUMENT;
  }

  return (int)PQC_WolfSSL_Transport_Write(
      (const uint8_t *)buffer,
      (uint32_t)buffer_length,
      &bytes_written);
}

const char *PQC_WolfSSL_Transport_EvidenceLabel(void)
{
  return "STM32 wolfSSL unavailable-transport evidence only";
}

const char *PQC_WolfSSL_Transport_UnavailableReason(void)
{
  return "lwIP/ST67W61M1 transport backend and socket I/O are unavailable";
}

bool PQC_WolfSSL_Transport_StatusLine(char *buffer, uint32_t buffer_length)
{
  const PQC_WolfSSLTransportStatus status = PQC_WolfSSL_Transport_GetStatus();

  if ((buffer == NULL) || (buffer_length == 0U))
  {
    return false;
  }

  const int written = snprintf(
      buffer,
      (size_t)buffer_length,
      "wolfSSL transport boundary: evidence=unavailable-transport-only boundary=%s callbacks=%s network_boundary=%s connect=unavailable read=unavailable write=unavailable socket_io=not-performed tls_handshake=unavailable certs=not-loaded mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable wifi=unavailable st67w61m1=unavailable end_to_end=unavailable\r\n",
      status.boundary_present ? "present" : "absent",
      status.callbacks_present ? "present" : "absent",
      status.network_boundary_present ? "present" : "absent");

  if ((written < 0) || ((uint32_t)written >= buffer_length))
  {
    buffer[0] = '\0';
    return false;
  }

  return true;
}
