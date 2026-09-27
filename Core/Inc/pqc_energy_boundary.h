#ifndef PQC_ENERGY_BOUNDARY_H
#define PQC_ENERGY_BOUNDARY_H
#include <stdint.h>
#include <stdbool.h>
#ifndef PQC_ENERGY_SYNC_ENABLED
#define PQC_ENERGY_SYNC_ENABLED 0
#endif
void PQC_EnergyBoundaryInitialize(void);
bool PQC_EnergyAwaitStart(void);
void PQC_EnergyBoundaryBegin(void);
void PQC_EnergyBoundaryEnd(void);
void PQC_EnergyBoundaryAppend(uint32_t interval_index);
#endif
