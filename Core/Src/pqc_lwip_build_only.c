#include "pqc_lwip_build_only.h"

#include "lwip/inet_chksum.h"
#include "lwip/init.h"
#include "lwip/ip4_addr.h"

#include <stdio.h>

/*
 * Phase M5 build-only skeleton.
 *
 * This translation unit is compiled into the STM32 firmware so later phases have
 * a stable STM32-local lwIP preparation boundary. It intentionally does not
 * initialize a netif, access ST67W61M1 hardware, acquire an IP address, open
 * TCP, run TLS, or perform MQTT operations. The runtime smoke line below only
 * exercises deterministic lwIP helper functions that do not require a physical
 * network interface.
 */

static const PQC_LwIPBuildOnlyStatus kPqcLwIPBuildOnlyStatus = {
    .schema_version = PQC_LWIP_BUILD_ONLY_SCHEMA_VERSION,
    .lwip_build_boundary_present = true,
    .network_interface_available = false,
    .wifi_module_required = false,
    .ip_address_available = false,
    .tcp_transport_available = false,
};

void PQC_LwIP_BuildOnly_Init(void)
{
  /* Build-only boundary marker. Runtime network bring-up is explicitly deferred. */
}

PQC_LwIPBuildOnlyStatus PQC_LwIP_BuildOnly_GetStatus(void)
{
  return kPqcLwIPBuildOnlyStatus;
}

const char *PQC_LwIP_BuildOnly_EvidenceLabel(void)
{
  return "STM32 lwIP build-only skeleton evidence";
}

const char *PQC_LwIP_BuildOnly_UnavailableReason(void)
{
  return "network interface, Wi-Fi module, IP address, TCP transport, TLS, and MQTT runtime paths are deferred";
}


bool PQC_LwIP_BuildOnly_RuntimeSmokeLineForContext(
    char *buffer,
    uint32_t buffer_length,
    const char *context,
    bool scheduler_running)
{
  if ((buffer == NULL) || (buffer_length == 0U) || (context == NULL))
  {
    return false;
  }

  ip4_addr_t example_addr;
  char example_addr_text[IP4ADDR_STRLEN_MAX];
  const uint8_t checksum_payload[] = "pqc-lwip-smoke";

  IP4_ADDR(&example_addr, 192, 0, 2, 1);

  if (ip4addr_ntoa_r(&example_addr, example_addr_text, (int)sizeof(example_addr_text)) == NULL)
  {
    buffer[0] = '\0';
    return false;
  }

  const u16_t checksum = inet_chksum(checksum_payload, sizeof(checksum_payload) - 1U);

  const int written = snprintf(
      buffer,
      (size_t)buffer_length,
      "lwIP runtime smoke: context=%s scheduler=%s version=%u.%u.%u ip4_format=%s checksum=0x%04x network=unavailable wifi=unavailable link=unavailable ip=unavailable tcp=unavailable tls_handshake=unavailable certs=not-loaded mqtt_connect=unavailable mqtt_publish=unavailable reconnect=unavailable st67w61m1=unavailable end_to_end=unavailable\r\n",
      context,
      scheduler_running ? "running" : "not_started",
      (unsigned)LWIP_VERSION_MAJOR,
      (unsigned)LWIP_VERSION_MINOR,
      (unsigned)LWIP_VERSION_REVISION,
      example_addr_text,
      (unsigned)checksum);

  if ((written < 0) || ((uint32_t)written >= buffer_length))
  {
    buffer[0] = '\0';
    return false;
  }

  return true;
}

bool PQC_LwIP_BuildOnly_RuntimeSmokeLine(char *buffer, uint32_t buffer_length)
{
  return PQC_LwIP_BuildOnly_RuntimeSmokeLineForContext(
      buffer,
      buffer_length,
      "pre_scheduler",
      false);
}

