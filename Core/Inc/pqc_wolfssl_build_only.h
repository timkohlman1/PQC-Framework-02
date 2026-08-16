#ifndef PQC_WOLFSSL_BUILD_ONLY_H
#define PQC_WOLFSSL_BUILD_ONLY_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PQC_WOLFSSL_BUILD_ONLY_SCHEMA_VERSION 4U

typedef struct
{
  uint32_t schema_version;
  bool wolfssl_build_boundary_present;
  bool wolfssl_headers_available;
  bool wolfssl_source_build_enabled;
  bool tls_handshake_available;
  bool runtime_transport_available;
  bool certificate_store_configured;
  bool private_key_material_compiled_in;
  bool real_credentials_required;
} PQC_WolfSSLBuildOnlyStatus;

PQC_WolfSSLBuildOnlyStatus PQC_WolfSSL_BuildOnly_GetStatus(void);
const char *PQC_WolfSSL_BuildOnly_EvidenceLabel(void);
const char *PQC_WolfSSL_BuildOnly_UnavailableReason(void);
const char *PQC_WolfSSL_BuildOnly_Version(void);
bool PQC_WolfSSL_BuildOnly_BuildInfoLine(char *buffer, uint32_t buffer_length);

#ifdef __cplusplus
}
#endif

#endif /* PQC_WOLFSSL_BUILD_ONLY_H */
