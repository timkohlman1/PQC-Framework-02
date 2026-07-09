#ifndef PQC_LWIP_BUILD_ONLY_H
#define PQC_LWIP_BUILD_ONLY_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PQC_LWIP_BUILD_ONLY_SCHEMA_VERSION 1U

typedef struct
{
  uint32_t schema_version;
  bool lwip_build_boundary_present;
  bool network_interface_available;
  bool wifi_module_required;
  bool ip_address_available;
  bool tcp_transport_available;
} PQC_LwIPBuildOnlyStatus;

void PQC_LwIP_BuildOnly_Init(void);
PQC_LwIPBuildOnlyStatus PQC_LwIP_BuildOnly_GetStatus(void);
const char *PQC_LwIP_BuildOnly_EvidenceLabel(void);
const char *PQC_LwIP_BuildOnly_UnavailableReason(void);
bool PQC_LwIP_BuildOnly_RuntimeSmokeLine(char *buffer, uint32_t buffer_length);

#ifdef __cplusplus
}
#endif

#endif /* PQC_LWIP_BUILD_ONLY_H */
