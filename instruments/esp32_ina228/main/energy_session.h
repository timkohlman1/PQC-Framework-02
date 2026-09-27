#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    bool mqtt_connected;
    bool publishing;
    bool last_publish_ok;
    bool ring_ready;
    bool ring_overflowed;
    bool interval_active;
    char run_id[80];
    uint32_t ring_capacity_samples;
    uint32_t ring_used_samples;
    uint64_t oldest_sequence;
    uint64_t newest_sequence;
    uint32_t completed_interval_count;
    uint32_t unclaimed_interval_count;
    uint32_t sync_isr_edges;
    uint32_t sync_queue_drops;
    uint32_t sync_processed_rising;
    uint32_t sync_processed_falling;
    uint32_t sync_unexpected_rising;
    uint32_t sync_orphan_falling;
} pqc_energy_session_snapshot_t;

/* Persistent framework-facing MQTT/evidence service. Acquisition starts at boot
 * and continues regardless of MQTT availability. */
void pqc_energy_session_start(void);
void pqc_energy_session_snapshot(pqc_energy_session_snapshot_t *out);


#ifdef __cplusplus
}
#endif
