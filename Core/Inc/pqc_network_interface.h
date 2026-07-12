#ifndef PQC_NETWORK_INTERFACE_H
#define PQC_NETWORK_INTERFACE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PQC_NETWORK_INTERFACE_SCHEMA_VERSION 2U

typedef enum
{
  PQC_NETWORK_AVAILABILITY_UNAVAILABLE = 0,
  PQC_NETWORK_AVAILABILITY_AVAILABLE = 1
} PQC_NetworkAvailability;

typedef struct
{
  uint32_t schema_version;
  bool boundary_present;
  bool lwip_netif_up;
  bool lwip_link_up;
  bool lwip_ipv4_any;
  PQC_NetworkAvailability link;
  PQC_NetworkAvailability ip_address;
  PQC_NetworkAvailability tcp_ready;
  PQC_NetworkAvailability transport;
} PQC_NetworkInterfaceStatus;

void PQC_NetworkInterface_Init(void);
PQC_NetworkInterfaceStatus PQC_NetworkInterface_GetStatus(void);
const char *PQC_NetworkInterface_BackendName(void);
const char *PQC_NetworkInterface_UnavailableReason(void);
bool PQC_NetworkInterface_StatusLine(char *buffer, uint32_t buffer_length);

#ifdef __cplusplus
}
#endif

#endif /* PQC_NETWORK_INTERFACE_H */
