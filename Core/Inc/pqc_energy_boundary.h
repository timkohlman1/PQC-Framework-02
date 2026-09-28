#ifndef PQC_ENERGY_BOUNDARY_H
#define PQC_ENERGY_BOUNDARY_H
#include <stdint.h>
#ifndef PQC_ENERGY_SYNC_ENABLED
#define PQC_ENERGY_SYNC_ENABLED 0
#endif

/* One experiment-wide GPIO window. TIM2 timestamps are retained as the two
 * anchors used later to map the ESP32 sample clock onto the STM32 timebase. */
void PQC_EnergyBoundaryInitialize(void);
void PQC_EnergyBoundaryBegin(void);
void PQC_EnergyBoundaryEnd(void);
void PQC_EnergyBoundaryAppend(uint32_t result_iteration);
#endif
