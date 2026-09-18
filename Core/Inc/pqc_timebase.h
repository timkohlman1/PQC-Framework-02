#ifndef PQC_TIMEBASE_H
#define PQC_TIMEBASE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PQC_APPLICATION_TIMEBASE_SCHEMA_VERSION 2U
#define PQC_APPLICATION_TIMEBASE_HZ 1000000UL
#define PQC_APPLICATION_TIMEBASE_COUNTER_BITS 32U
#define PQC_BOOT_RESET_ORIGIN_KIND_WOLFBOOT_ENTRY 1U

typedef struct
{
    uint64_t reset_origin_to_handoff_us;
    uint32_t bridge_counter_hz;
    uint32_t bridge_counter_bits;
    uint32_t reset_origin_kind;
    uint8_t valid;
} PQC_TimebaseBootHandoff;

typedef struct
{
    uint32_t schema_version;
    uint32_t timer_input_clock_hz;
    uint32_t prescaler;
    uint32_t counter_hz;
    uint32_t counter_bits;
    uint32_t reset_origin_kind;
    uint64_t reset_origin_to_application_timebase_us;
    uint8_t initialized;
    uint8_t reset_origin_valid;
    uint8_t bridge_valid;
} PQC_TimebaseProvenance;

void PQC_TimebaseConfigureBootHandoff(const PQC_TimebaseBootHandoff *handoff);
int PQC_TimebaseInitialize(void);
uint64_t PQC_TimebaseNowUs(void);
uint64_t PQC_TimebaseElapsedUs(uint64_t start_us, uint64_t end_us);
bool PQC_TimebaseResetRelativeUs(uint64_t application_timestamp_us, uint64_t *reset_relative_us);
uint32_t PQC_TimebaseLegacyMilliseconds(uint64_t elapsed_us);
const PQC_TimebaseProvenance *PQC_TimebaseGetProvenance(void);
void PQC_TimebaseTIM2IRQHandler(void);

#ifdef __cplusplus
}
#endif

#endif
