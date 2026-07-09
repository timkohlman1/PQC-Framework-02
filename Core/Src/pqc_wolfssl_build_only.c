#include "pqc_wolfssl_build_only.h"

#include <stdio.h>

/*
 * Phase M6 wolfSSL build-only skeleton.
 *
 * This translation unit is compiled into the STM32 firmware so later phases have
 * a stable project-owned boundary for STM32-local wolfSSL configuration. It does
 * not create a wolfSSL context, load certificates or private keys, open a TCP
 * transport, perform a TLS handshake, or perform MQTT operations. Certificate
 * handling is limited to future non-secret path/reference configuration; private keys, credentials, and real certificate material must remain outside source,
 * result artifacts, and replacement archives.
 */

#if defined(__has_include)
#if __has_include("wolfssl/version.h")
#include "wolfssl/version.h"
#define PQC_WOLFSSL_HEADERS_AVAILABLE 1
#else
#define PQC_WOLFSSL_HEADERS_AVAILABLE 0
#endif
#else
#define PQC_WOLFSSL_HEADERS_AVAILABLE 0
#endif

#ifndef WOLFSSL_VERSION
#define WOLFSSL_VERSION "unavailable"
#endif

static const PQC_WolfSSLBuildOnlyStatus kPqcWolfSSLBuildOnlyStatus = {
    .schema_version = PQC_WOLFSSL_BUILD_ONLY_SCHEMA_VERSION,
    .wolfssl_build_boundary_present = true,
#if PQC_WOLFSSL_HEADERS_AVAILABLE
    .wolfssl_headers_available = true,
#else
    .wolfssl_headers_available = false,
#endif
    .tls_handshake_available = false,
    .runtime_transport_available = false,
    .certificate_store_configured = false,
    .private_key_material_compiled_in = false,
    .real_credentials_required = false,
};

void PQC_WolfSSL_BuildOnly_Init(void)
{
  /* Build-only boundary marker. TLS runtime bring-up is explicitly deferred. */
}

PQC_WolfSSLBuildOnlyStatus PQC_WolfSSL_BuildOnly_GetStatus(void)
{
  return kPqcWolfSSLBuildOnlyStatus;
}

const char *PQC_WolfSSL_BuildOnly_EvidenceLabel(void)
{
  return "STM32 wolfSSL build-only skeleton evidence";
}

const char *PQC_WolfSSL_BuildOnly_UnavailableReason(void)
{
  return "runtime transport, certificate store, private key material, TLS handshake, and MQTT runtime paths are deferred";
}

const char *PQC_WolfSSL_BuildOnly_Version(void)
{
  return WOLFSSL_VERSION;
}

bool PQC_WolfSSL_BuildOnly_BuildInfoLine(char *buffer, uint32_t buffer_length)
{
  if ((buffer == NULL) || (buffer_length == 0U))
  {
    return false;
  }

  const int written = snprintf(
      buffer,
      (size_t)buffer_length,
      "wolfSSL build-only: headers=%s version=%s tls_handshake=unavailable transport=unavailable certs=path-references-only secrets=not-compiled-in\r\n",
#if PQC_WOLFSSL_HEADERS_AVAILABLE
      "available",
#else
      "unavailable",
#endif
      PQC_WolfSSL_BuildOnly_Version());

  if ((written < 0) || ((uint32_t)written >= buffer_length))
  {
    buffer[0] = '\0';
    return false;
  }

  return true;
}
