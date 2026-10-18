#ifndef PQC_ACTIVITY_TRACE_H
#define PQC_ACTIVITY_TRACE_H
#include <stdint.h>
#ifndef PQC_ACTIVITY_TRACE_ENABLED
#define PQC_ACTIVITY_TRACE_ENABLED 0
#endif
/* Numeric codebook is versioned with scripts/framework/activity_trace.py.
 * No command arguments, credentials, allocation or I/O in recording hooks. */
typedef enum {
    PQC_ACT_CHIP_ENABLE = 1,
    PQC_ACT_READY_WAIT = 2,
    PQC_ACT_READY_RECEIVED = 3,
    PQC_ACT_READY_GUARD = 4,
    PQC_ACT_CONNECT_WAIT = 5,
    PQC_ACT_CONNECTING_RECEIVED = 6,
    PQC_ACT_CONNECTED_RECEIVED = 7,
    PQC_ACT_CONNECTED_GUARD = 8,
    PQC_ACT_LINK_UP = 9,
    PQC_ACT_DHCP_START = 10,
    PQC_ACT_IPV4_AVAILABLE = 11,
    PQC_ACT_TCPIP_INIT = 12,
    PQC_ACT_POWER_MODE = 13,
    PQC_ACT_DISCONNECT_RECEIVED = 14,
    PQC_ACT_CONNECTION_REASON = 15,
    PQC_ACT_CHIP_RESET_ASSERT = 16,
    PQC_ACT_NETIF_STARTUP_GUARD = 17,
 } PQC_ActivityCode;
#if PQC_ACTIVITY_TRACE_ENABLED
void PQC_ActivityReset(void);
void PQC_ActivityStop(void);
uint16_t PQC_ActivityBegin(uint16_t code, int32_t value);
void PQC_ActivityEnd(uint16_t token, int32_t result);
void PQC_ActivityEvent(uint16_t code, int32_t value);
uint16_t PQC_ActivityCommand(const char *command);
void PQC_ActivitySPI(uint8_t host_write);
void PQC_ActivityAppend(uint32_t iteration);
#else
#define PQC_ActivityReset() ((void)0)
#define PQC_ActivityStop() ((void)0)
#define PQC_ActivityBegin(code, value) ((uint16_t)0)
#define PQC_ActivityEnd(token, result) ((void)(token))
#define PQC_ActivityEvent(code, value) ((void)0)
#define PQC_ActivityCommand(command) ((uint16_t)0)
#define PQC_ActivitySPI(host_write) ((void)0)
#define PQC_ActivityAppend(iteration) ((void)0)
#endif
#endif
