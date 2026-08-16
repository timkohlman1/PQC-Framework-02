#ifndef PQC_RAM_ACCOUNTING_H
#define PQC_RAM_ACCOUNTING_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct
{
  size_t sbrk_capacity_bytes;
  size_t sbrk_current_used_bytes;
  size_t sbrk_peak_used_bytes;
  bool sbrk_ever_called;
  size_t msp_reserved_bytes;
  size_t msp_peak_used_bytes;
  size_t msp_headroom_bytes;
  size_t msp_excess_bytes;
  size_t msp_measurement_window_bytes;
  bool msp_reservation_exceeded;
  bool msp_measurement_saturated;
} PQC_RAMRuntimeSnapshot;

/*
 * Paint the unused primary-RAM interval between the static image and the
 * current MSP. This allows the runtime scan to measure MSP use beyond the
 * linker's _Min_Stack_Size reservation. Call once, as early as possible in
 * main(), before the measured workload.
 */
void PQC_RAM_InitializeMSPHighWatermark(void);

/* Collect _sbrk and MSP high-water evidence without emitting any UART output. */
void PQC_RAM_RuntimeSnapshotGet(PQC_RAMRuntimeSnapshot *snapshot);

#endif /* PQC_RAM_ACCOUNTING_H */
