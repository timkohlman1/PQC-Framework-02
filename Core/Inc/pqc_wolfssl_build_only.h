#ifndef PQC_WOLFSSL_BUILD_ONLY_H
#define PQC_WOLFSSL_BUILD_ONLY_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PQC_WOLFSSL_BUILD_ONLY_SCHEMA_VERSION 3U
#define PQC_WOLFSSL_SHA256_DIGEST_HEX_LENGTH 64U

typedef struct
{
  uint32_t schema_version;
  bool wolfssl_build_boundary_present;
  bool wolfssl_headers_available;
  bool wolfssl_source_build_enabled;
  bool wolfcrypt_sha256_smoke_available;
  bool wolfcrypt_sha256_smoke_passed;
  bool tls_context_lifecycle_available;
  bool tls_context_lifecycle_passed;
  bool tls_handshake_available;
  bool runtime_transport_available;
  bool certificate_store_configured;
  bool private_key_material_compiled_in;
  bool real_credentials_required;
} PQC_WolfSSLBuildOnlyStatus;

void PQC_WolfSSL_BuildOnly_Init(void);
PQC_WolfSSLBuildOnlyStatus PQC_WolfSSL_BuildOnly_GetStatus(void);
const char *PQC_WolfSSL_BuildOnly_EvidenceLabel(void);
const char *PQC_WolfSSL_BuildOnly_UnavailableReason(void);
const char *PQC_WolfSSL_BuildOnly_Version(void);
bool PQC_WolfSSL_BuildOnly_RunSourceSmoke(void);
bool PQC_WolfSSL_BuildOnly_RunTLSContextLifecycleSmoke(void);
bool PQC_WolfSSL_BuildOnly_SmokeDigestHex(char *buffer, uint32_t buffer_length);
bool PQC_WolfSSL_BuildOnly_BuildInfoLine(char *buffer, uint32_t buffer_length);
bool PQC_WolfSSL_BuildOnly_RuntimeSmokeLine(char *buffer, uint32_t buffer_length);

#ifdef __cplusplus
}
#endif

#endif /* PQC_WOLFSSL_BUILD_ONLY_H */
