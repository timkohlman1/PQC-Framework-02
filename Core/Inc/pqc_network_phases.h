#ifndef PQC_NETWORK_PHASES_H
#define PQC_NETWORK_PHASES_H
#include <stdint.h>
/* One startup pass, recorded by networkTask only. No allocation, formatting,
 * UART or MQTT in Begin/End; report after the measured workload finishes. */
typedef enum {
    PQC_NET_MODULE_INIT, PQC_NET_WIFI_INIT, PQC_NET_LWIP_INIT,
    PQC_NET_WIFI_SCAN, PQC_NET_WIFI_CONNECT, PQC_NET_ASSOCIATION_CHECK,
    PQC_NET_DHCP_WAIT, PQC_NET_PHASE_COUNT
} PQC_NetworkPhase;
void PQC_NetworkPhasesReset(void);
void PQC_NetworkPhaseBegin(PQC_NetworkPhase phase);
void PQC_NetworkPhaseEnd(PQC_NetworkPhase phase, int32_t result);
void PQC_NetworkPhasesAppend(uint32_t iteration);
#endif
