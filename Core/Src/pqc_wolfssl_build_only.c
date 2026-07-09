#include "pqc_wolfssl_build_only.h"

#include <stddef.h>
#include <stdio.h>

/*
 * Phase M6 wolfSSL source build-only skeleton.
 *
 * This translation unit is compiled into the STM32 firmware and links against a
 * minimal wolfCrypt source target built from tools/wolfboot/lib/wolfssl. It runs
 * a deterministic SHA-256 smoke check so hardware UART evidence can prove that
 * repository-local wolfSSL/wolfCrypt code was linked and executed. It does not
 * create a wolfSSL context, load certificates or private keys, open a TCP
 * transport, perform a TLS handshake, or perform MQTT operations. Certificate
 * handling is limited to future non-secret path/reference configuration;
 * private keys, credentials, and real certificate material must remain outside
 * source, result artifacts, and replacement archives.
 */

#ifndef PQC_WOLFSSL_SOURCE_BUILD
#define PQC_WOLFSSL_SOURCE_BUILD 0
#endif

/*
 * Phase M6 requires the source-build path to fail at compile time if the
 * repository-local wolfSSL headers are not available. The previous permissive
 * A permissive optional-header fallback could produce weak UART evidence such as
 * source=unknown/sha256=failed after a misconfigured build. Building from
 * wolfSSL source is now an explicit requirement for this phase.
 */
#if PQC_WOLFSSL_SOURCE_BUILD
#include "wolfssl/version.h"
#include "wolfssl/wolfcrypt/sha256.h"
#define PQC_WOLFSSL_HEADERS_AVAILABLE 1
#define PQC_WOLFCRYPT_SHA256_HEADERS_AVAILABLE 1
#else
#define PQC_WOLFSSL_HEADERS_AVAILABLE 0
#define PQC_WOLFCRYPT_SHA256_HEADERS_AVAILABLE 0
#ifndef LIBWOLFSSL_VERSION_STRING
#define LIBWOLFSSL_VERSION_STRING "unavailable"
#endif
#endif

static const unsigned char kPqcWolfSSLSmokeMessage[] = "pqc-wolfssl-build-only";
static const unsigned char kPqcWolfSSLExpectedSha256[32] = {
    0x01U, 0xb2U, 0x74U, 0xb1U, 0x96U, 0x59U, 0x99U, 0x5cU,
    0xb8U, 0x29U, 0xa9U, 0xa9U, 0x25U, 0xf6U, 0x13U, 0x10U,
    0x9eU, 0xc0U, 0x2aU, 0x08U, 0x8fU, 0x94U, 0xd9U, 0xe9U,
    0x14U, 0xa3U, 0x60U, 0x26U, 0xceU, 0xcfU, 0x00U, 0xe5U,
};

static unsigned char kPqcWolfSSLLatestDigest[32];
static bool kPqcWolfSSLSmokeHasRun = false;
static bool kPqcWolfSSLSmokePassed = false;

static char PQC_WolfSSL_NibbleToHex(unsigned char value)
{
  value &= 0x0FU;
  if (value < 10U)
  {
    return (char)('0' + value);
  }
  return (char)('a' + (value - 10U));
}

static bool PQC_WolfSSL_DigestMatchesExpected(const unsigned char *digest)
{
  unsigned char diff = 0U;

  if (digest == NULL)
  {
    return false;
  }

  for (uint32_t index = 0U; index < sizeof(kPqcWolfSSLExpectedSha256); index++)
  {
    diff |= (unsigned char)(digest[index] ^ kPqcWolfSSLExpectedSha256[index]);
  }

  return diff == 0U;
}

void PQC_WolfSSL_BuildOnly_Init(void)
{
  (void)PQC_WolfSSL_BuildOnly_RunSourceSmoke();
}

bool PQC_WolfSSL_BuildOnly_RunSourceSmoke(void)
{
#if PQC_WOLFSSL_SOURCE_BUILD && PQC_WOLFCRYPT_SHA256_HEADERS_AVAILABLE
  wc_Sha256 sha256;
  int result = wc_InitSha256(&sha256);

  if (result == 0)
  {
    result = wc_Sha256Update(
        &sha256,
        kPqcWolfSSLSmokeMessage,
        (word32)(sizeof(kPqcWolfSSLSmokeMessage) - 1U));
  }

  if (result == 0)
  {
    result = wc_Sha256Final(&sha256, kPqcWolfSSLLatestDigest);
  }

  kPqcWolfSSLSmokeHasRun = true;
  kPqcWolfSSLSmokePassed = (result == 0) && PQC_WolfSSL_DigestMatchesExpected(kPqcWolfSSLLatestDigest);
  return kPqcWolfSSLSmokePassed;
#else
  kPqcWolfSSLSmokeHasRun = true;
  kPqcWolfSSLSmokePassed = false;
  return false;
#endif
}

PQC_WolfSSLBuildOnlyStatus PQC_WolfSSL_BuildOnly_GetStatus(void)
{
  if (!kPqcWolfSSLSmokeHasRun)
  {
    (void)PQC_WolfSSL_BuildOnly_RunSourceSmoke();
  }

  const PQC_WolfSSLBuildOnlyStatus status = {
      .schema_version = PQC_WOLFSSL_BUILD_ONLY_SCHEMA_VERSION,
      .wolfssl_build_boundary_present = true,
#if PQC_WOLFSSL_HEADERS_AVAILABLE
      .wolfssl_headers_available = true,
#else
      .wolfssl_headers_available = false,
#endif
#if PQC_WOLFSSL_SOURCE_BUILD
      .wolfssl_source_build_enabled = true,
#else
      .wolfssl_source_build_enabled = false,
#endif
#if PQC_WOLFSSL_SOURCE_BUILD && PQC_WOLFCRYPT_SHA256_HEADERS_AVAILABLE
      .wolfcrypt_sha256_smoke_available = true,
#else
      .wolfcrypt_sha256_smoke_available = false,
#endif
      .wolfcrypt_sha256_smoke_passed = kPqcWolfSSLSmokePassed,
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
  return "STM32 wolfSSL source build-only smoke evidence";
}

const char *PQC_WolfSSL_BuildOnly_UnavailableReason(void)
{
  return "runtime transport, certificate store, private key material, TLS handshake, and MQTT runtime paths are deferred";
}

const char *PQC_WolfSSL_BuildOnly_Version(void)
{
  return LIBWOLFSSL_VERSION_STRING;
}

bool PQC_WolfSSL_BuildOnly_SmokeDigestHex(char *buffer, uint32_t buffer_length)
{
  if ((buffer == NULL) || (buffer_length < (PQC_WOLFSSL_SHA256_DIGEST_HEX_LENGTH + 1U)))
  {
    return false;
  }

  if (!kPqcWolfSSLSmokeHasRun)
  {
    (void)PQC_WolfSSL_BuildOnly_RunSourceSmoke();
  }

  for (uint32_t index = 0U; index < sizeof(kPqcWolfSSLLatestDigest); index++)
  {
    buffer[index * 2U] = PQC_WolfSSL_NibbleToHex((unsigned char)(kPqcWolfSSLLatestDigest[index] >> 4U));
    buffer[(index * 2U) + 1U] = PQC_WolfSSL_NibbleToHex(kPqcWolfSSLLatestDigest[index]);
  }
  buffer[PQC_WOLFSSL_SHA256_DIGEST_HEX_LENGTH] = '\0';

  return true;
}

bool PQC_WolfSSL_BuildOnly_BuildInfoLine(char *buffer, uint32_t buffer_length)
{
  if ((buffer == NULL) || (buffer_length == 0U))
  {
    return false;
  }

  const PQC_WolfSSLBuildOnlyStatus status = PQC_WolfSSL_BuildOnly_GetStatus();
  const int written = snprintf(
      buffer,
      (size_t)buffer_length,
      "wolfSSL build-only: headers=%s source=%s version=%s wolfcrypt_sha256_smoke=%s tls_handshake=unavailable transport=unavailable certs=path-references-only secrets=not-compiled-in\r\n",
      status.wolfssl_headers_available ? "available" : "unavailable",
      status.wolfssl_source_build_enabled ? "enabled" : "disabled",
      PQC_WolfSSL_BuildOnly_Version(),
      status.wolfcrypt_sha256_smoke_passed ? "passed" : "failed");

  if ((written < 0) || ((uint32_t)written >= buffer_length))
  {
    buffer[0] = '\0';
    return false;
  }

  return true;
}

bool PQC_WolfSSL_BuildOnly_RuntimeSmokeLine(char *buffer, uint32_t buffer_length)
{
  char digest_hex[PQC_WOLFSSL_SHA256_DIGEST_HEX_LENGTH + 1U];

  if ((buffer == NULL) || (buffer_length == 0U))
  {
    return false;
  }

  const PQC_WolfSSLBuildOnlyStatus status = PQC_WolfSSL_BuildOnly_GetStatus();
  if (!PQC_WolfSSL_BuildOnly_SmokeDigestHex(digest_hex, (uint32_t)sizeof(digest_hex)))
  {
    digest_hex[0] = '\0';
  }

  const int written = snprintf(
      buffer,
      (size_t)buffer_length,
      "wolfSSL build-only smoke: source=%s version=%s sha256=%s digest=%s tls_handshake=unavailable transport=unavailable certs=not-loaded secrets=not-compiled-in\r\n",
      status.wolfssl_source_build_enabled ? "enabled" : "disabled",
      PQC_WolfSSL_BuildOnly_Version(),
      status.wolfcrypt_sha256_smoke_passed ? "ok" : "failed",
      digest_hex);

  if ((written < 0) || ((uint32_t)written >= buffer_length))
  {
    buffer[0] = '\0';
    return false;
  }

  return true;
}
