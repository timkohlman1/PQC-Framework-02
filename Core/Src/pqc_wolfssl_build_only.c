#include "pqc_wolfssl_build_only.h"

#include <stddef.h>
#include <stdio.h>

#ifndef PQC_WOLFSSL_SOURCE_BUILD
#define PQC_WOLFSSL_SOURCE_BUILD 0
#endif

#if PQC_WOLFSSL_SOURCE_BUILD
#include "wolfssl/version.h"
#define PQC_WOLFSSL_HEADERS_AVAILABLE 1
#else
#define PQC_WOLFSSL_HEADERS_AVAILABLE 0
#ifndef LIBWOLFSSL_VERSION_STRING
#define LIBWOLFSSL_VERSION_STRING "unavailable"
#endif
#endif

PQC_WolfSSLBuildOnlyStatus PQC_WolfSSL_BuildOnly_GetStatus(void)
{
  const PQC_WolfSSLBuildOnlyStatus status = {
      .schema_version = PQC_WOLFSSL_BUILD_ONLY_SCHEMA_VERSION,
      .wolfssl_build_boundary_present = true,
      .wolfssl_headers_available = PQC_WOLFSSL_HEADERS_AVAILABLE != 0,
      .wolfssl_source_build_enabled = PQC_WOLFSSL_SOURCE_BUILD != 0,
      .tls_handshake_available = false,
      .runtime_transport_available = false,
      .certificate_store_configured = false,
      .private_key_material_compiled_in = false,
      .real_credentials_required = false,
  };
  return status;
}

const char *PQC_WolfSSL_BuildOnly_EvidenceLabel(void)
{
  return "STM32 wolfSSL source build boundary";
}

const char *PQC_WolfSSL_BuildOnly_UnavailableReason(void)
{
  return "runtime capability is established by the live lwIP/wolfMQTT/TLS workflow";
}

const char *PQC_WolfSSL_BuildOnly_Version(void)
{
  return LIBWOLFSSL_VERSION_STRING;
}

bool PQC_WolfSSL_BuildOnly_BuildInfoLine(char *buffer, uint32_t buffer_length)
{
  const PQC_WolfSSLBuildOnlyStatus status = PQC_WolfSSL_BuildOnly_GetStatus();
  int written;

  if ((buffer == NULL) || (buffer_length == 0U)) return false;

  written = snprintf(
      buffer,
      (size_t)buffer_length,
      "wolfSSL build-only: headers=%s source=%s version=%s "
      "runtime_validation=live_mqtt_tls_workflow\r\n",
      status.wolfssl_headers_available ? "available" : "unavailable",
      status.wolfssl_source_build_enabled ? "enabled" : "disabled",
      PQC_WolfSSL_BuildOnly_Version());

  if ((written < 0) || ((uint32_t)written >= buffer_length)) {
    buffer[0] = '\0';
    return false;
  }
  return true;
}
