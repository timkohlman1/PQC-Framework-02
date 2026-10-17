#include "pqc_network_phases.h"
#include "pqc_timebase.h"
#include "pqc_result_buffer.h"
#include <stdio.h>
#include <string.h>

typedef struct {
    uint64_t start_us, end_us;
    int32_t result;
    uint8_t state; /* 0 not attempted, 1 started, 2 ended, 3 invalid. */
} PQC_NetworkPhaseRecord;
static PQC_NetworkPhaseRecord s_network_phases[PQC_NET_PHASE_COUNT];
static uint32_t s_network_phase_errors;
static const char *const names[PQC_NET_PHASE_COUNT] = {
    "module_init", "wifi_init", "lwip_init", "wifi_scan", "wifi_connect",
    "association_check", "dhcp_wait"
};

void PQC_NetworkPhasesReset(void)
{
    memset(s_network_phases, 0, sizeof(s_network_phases));
    s_network_phase_errors = 0U;
}
void PQC_NetworkPhaseBegin(PQC_NetworkPhase phase)
{
    if ((unsigned)phase >= PQC_NET_PHASE_COUNT) { s_network_phase_errors++; return; }
    if (s_network_phases[phase].state != 0U || !PQC_TimebaseGetProvenance()->initialized) {
        s_network_phases[phase].state = 3U; s_network_phase_errors++; return;
    }
    s_network_phases[phase].start_us = PQC_TimebaseNowUs();
    s_network_phases[phase].state = 1U;
}
void PQC_NetworkPhaseEnd(PQC_NetworkPhase phase, int32_t result)
{
    uint64_t now = PQC_TimebaseNowUs();
    if ((unsigned)phase >= PQC_NET_PHASE_COUNT) { s_network_phase_errors++; return; }
    if (s_network_phases[phase].state != 1U || now < s_network_phases[phase].start_us) {
        s_network_phases[phase].state = 3U; s_network_phase_errors++; return;
    }
    s_network_phases[phase].end_us = now;
    s_network_phases[phase].result = result;
    s_network_phases[phase].state = 2U;
}
/* newlib-nano does not provide 64-bit printf conversions. */
static char *decimal(uint64_t value, char buffer[21])
{
    char *p = buffer + 20; *p = '\0';
    do { *--p = (char)('0' + value % 10U); value /= 10U; } while (value);
    return p;
}
void PQC_NetworkPhasesAppend(uint32_t iteration)
{
    char line[256], start[21], end[21];
    unsigned i;
    (void)snprintf(line, sizeof(line),
        "PQC_NETWORK_PHASES schema=1 count=%u errors=%lu clock=TIM2 counter_hz=1000000 "
        "timestamp_origin=application_timebase_start", (unsigned)PQC_NET_PHASE_COUNT,
        (unsigned long)s_network_phase_errors);
    (void)PQC_ResultBufferAppendText(iteration, "network_phases", line);
    for (i = 0; i < PQC_NET_PHASE_COUNT; i++) {
        const PQC_NetworkPhaseRecord *r = &s_network_phases[i];
        (void)snprintf(line, sizeof(line),
            "PQC_NETWORK_PHASE schema=1 phase=%s state=%u start_us=%s end_us=%s result=%ld",
            names[i], (unsigned)r->state, decimal(r->start_us,start),
            decimal(r->end_us,end), (long)r->result);
        (void)PQC_ResultBufferAppendText(iteration, "network_phases", line);
    }
}
