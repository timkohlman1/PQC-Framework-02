#include "pqc_lwip_build_only.h"

/*
 * Phase M5 build-only skeleton.
 *
 * This translation unit is compiled into the STM32 firmware so later phases have
 * a stable STM32-local lwIP preparation boundary. It intentionally does not
 * include lwIP middleware headers, initialize a netif, access ST67W61M1 hardware,
 * acquire an IP address, open TCP, run TLS, or perform MQTT operations.
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
