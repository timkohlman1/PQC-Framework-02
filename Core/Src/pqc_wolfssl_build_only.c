#include "pqc_wolfssl_build_only.h"

#include <stddef.h>
#include <stdio.h>

#ifndef PQC_WOLFSSL_SOURCE_BUILD
#define PQC_WOLFSSL_SOURCE_BUILD 0
#endif

#if PQC_WOLFSSL_SOURCE_BUILD
#include "wolfssl/ssl.h"
#include "wolfssl/version.h"
#include "wolfssl/wolfcrypt/sha256.h"
#define PQC_WOLFSSL_HEADERS_AVAILABLE 1
#define PQC_WOLFCRYPT_SHA256_HEADERS_AVAILABLE 1
#define PQC_WOLFSSL_TLS_CONTEXT_HEADERS_AVAILABLE 1
#else
#define PQC_WOLFSSL_HEADERS_AVAILABLE 0
#define PQC_WOLFCRYPT_SHA256_HEADERS_AVAILABLE 0
#define PQC_WOLFSSL_TLS_CONTEXT_HEADERS_AVAILABLE 0
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
static bool kPqcWolfSSLTLSContextSmokeHasRun = false;
static bool kPqcWolfSSLTLSContextSmokePassed = false;

static char PQC_WolfSSL_NibbleToHex(unsigned char value)
{
  value &= 0x0FU;
  return (value < 10U) ? (char)('0' + value) : (char)('a' + (value - 10U));
}

static bool PQC_WolfSSL_DigestMatchesExpected(const unsigned char *digest)
{
  unsigned char diff = 0U;
  if (digest == NULL) return false;
  for (uint32_t index = 0U; index < sizeof(kPqcWolfSSLExpectedSha256); index++)
  {
    diff |= (unsigned char)(digest[index] ^ kPqcWolfSSLExpectedSha256[index]);
  }
  return diff == 0U;
}

void PQC_WolfSSL_BuildOnly_Init(void)
{
  (void)PQC_WolfSSL_BuildOnly_RunSourceSmoke();
  (void)PQC_WolfSSL_BuildOnly_RunTLSContextLifecycleSmoke();
}

bool PQC_WolfSSL_BuildOnly_RunSourceSmoke(void)
{
#if PQC_WOLFSSL_SOURCE_BUILD && PQC_WOLFCRYPT_SHA256_HEADERS_AVAILABLE
  wc_Sha256 sha256;
  int result = wc_InitSha256(&sha256);
  if (result == 0)
  {
    result = wc_Sha256Update(&sha256, kPqcWolfSSLSmokeMessage,
                             (word32)(sizeof(kPqcWolfSSLSmokeMessage) - 1U));
  }
  if (result == 0) result = wc_Sha256Final(&sha256, kPqcWolfSSLLatestDigest);
  kPqcWolfSSLSmokeHasRun = true;
  kPqcWolfSSLSmokePassed = (result == 0) && PQC_WolfSSL_DigestMatchesExpected(kPqcWolfSSLLatestDigest);
  return kPqcWolfSSLSmokePassed;
#else
  kPqcWolfSSLSmokeHasRun = true;
  kPqcWolfSSLSmokePassed = false;
  return false;
#endif
}

bool PQC_WolfSSL_BuildOnly_RunTLSContextLifecycleSmoke(void)
{
#if PQC_WOLFSSL_SOURCE_BUILD && PQC_WOLFSSL_TLS_CONTEXT_HEADERS_AVAILABLE
  int init_result = wolfSSL_Init();
  WOLFSSL_CTX *context = NULL;
  bool passed = false;

  if (init_result == WOLFSSL_SUCCESS)
  {
    context = wolfSSL_CTX_new(wolfTLSv1_2_client_method());
    passed = (context != NULL);
    if (context != NULL) wolfSSL_CTX_free(context);
    (void)wolfSSL_Cleanup();
  }

  kPqcWolfSSLTLSContextSmokeHasRun = true;
  kPqcWolfSSLTLSContextSmokePassed = passed;
  return passed;
#else
  kPqcWolfSSLTLSContextSmokeHasRun = true;
  kPqcWolfSSLTLSContextSmokePassed = false;
  return false;
#endif
}

PQC_WolfSSLBuildOnlyStatus PQC_WolfSSL_BuildOnly_GetStatus(void)
{
  if (!kPqcWolfSSLSmokeHasRun) (void)PQC_WolfSSL_BuildOnly_RunSourceSmoke();
  if (!kPqcWolfSSLTLSContextSmokeHasRun) (void)PQC_WolfSSL_BuildOnly_RunTLSContextLifecycleSmoke();

  const PQC_WolfSSLBuildOnlyStatus status = {
      .schema_version = PQC_WOLFSSL_BUILD_ONLY_SCHEMA_VERSION,
      .wolfssl_build_boundary_present = true,
      .wolfssl_headers_available = PQC_WOLFSSL_HEADERS_AVAILABLE != 0,
      .wolfssl_source_build_enabled = PQC_WOLFSSL_SOURCE_BUILD != 0,
      .wolfcrypt_sha256_smoke_available = PQC_WOLFCRYPT_SHA256_HEADERS_AVAILABLE != 0,
      .wolfcrypt_sha256_smoke_passed = kPqcWolfSSLSmokePassed,
      .tls_context_lifecycle_available = PQC_WOLFSSL_TLS_CONTEXT_HEADERS_AVAILABLE != 0,
      .tls_context_lifecycle_passed = kPqcWolfSSLTLSContextSmokePassed,
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
  return "STM32 wolfSSL TLS context lifecycle evidence only";
}

const char *PQC_WolfSSL_BuildOnly_UnavailableReason(void)
{
  return "TLS handshake, certificates, private keys, transport, MQTT, Wi-Fi, and ST67W61M1 runtime paths are unavailable";
}

const char *PQC_WolfSSL_BuildOnly_Version(void)
{
  return LIBWOLFSSL_VERSION_STRING;
}

bool PQC_WolfSSL_BuildOnly_SmokeDigestHex(char *buffer, uint32_t buffer_length)
{
  if ((buffer == NULL) || (buffer_length < (PQC_WOLFSSL_SHA256_DIGEST_HEX_LENGTH + 1U))) return false;
  if (!kPqcWolfSSLSmokeHasRun) (void)PQC_WolfSSL_BuildOnly_RunSourceSmoke();
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
  if ((buffer == NULL) || (buffer_length == 0U)) return false;
  const PQC_WolfSSLBuildOnlyStatus status = PQC_WolfSSL_BuildOnly_GetStatus();
  const int written = snprintf(buffer, (size_t)buffer_length,
      "wolfSSL build-only: headers=%s source=%s version=%s sha256=%s tls_context=%s tls_handshake=unavailable transport=unavailable certs=not-loaded secrets=not-compiled-in\r\n",
      status.wolfssl_headers_available ? "available" : "unavailable",
      status.wolfssl_source_build_enabled ? "enabled" : "disabled",
      PQC_WolfSSL_BuildOnly_Version(),
      status.wolfcrypt_sha256_smoke_passed ? "passed" : "failed",
      status.tls_context_lifecycle_passed ? "passed" : "failed");
  if ((written < 0) || ((uint32_t)written >= buffer_length)) { buffer[0] = '\0'; return false; }
  return true;
}

bool PQC_WolfSSL_BuildOnly_RuntimeSmokeLine(char *buffer, uint32_t buffer_length)
{
  char digest_hex[PQC_WOLFSSL_SHA256_DIGEST_HEX_LENGTH + 1U];
  if ((buffer == NULL) || (buffer_length == 0U)) return false;
  const PQC_WolfSSLBuildOnlyStatus status = PQC_WolfSSL_BuildOnly_GetStatus();
  if (!PQC_WolfSSL_BuildOnly_SmokeDigestHex(digest_hex, (uint32_t)sizeof(digest_hex))) digest_hex[0] = '\0';
  const int written = snprintf(buffer, (size_t)buffer_length,
      "wolfSSL TLS context smoke: evidence=tls-context-lifecycle-only source=%s version=%s sha256=%s digest=%s init=%s client_ctx=%s free=done cleanup=done tls_handshake=unavailable certs=not-loaded transport=unavailable mqtt=unavailable wifi=unavailable st67w61m1=unavailable secrets=not-compiled-in\r\n",
      status.wolfssl_source_build_enabled ? "enabled" : "disabled",
      PQC_WolfSSL_BuildOnly_Version(),
      status.wolfcrypt_sha256_smoke_passed ? "ok" : "failed",
      digest_hex,
      status.tls_context_lifecycle_passed ? "ok" : "failed",
      status.tls_context_lifecycle_passed ? "created" : "failed");
  if ((written < 0) || ((uint32_t)written >= buffer_length)) { buffer[0] = '\0'; return false; }
  return true;
}
