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
    bool capture_active;
    char capture_id[17];
    uint32_t ring_capacity_samples;
    uint32_t ring_used_samples;
    int64_t oldest_timestamp_us;
    int64_t newest_timestamp_us;
    uint32_t completed_capture_count;
    uint32_t aborted_capture_count;
    uint32_t sync_isr_edges;
    uint32_t sync_queue_drops;
} pqc_energy_session_snapshot_t;

/* Persistent GPIO-triggered energy recorder. INA228 acquisition starts at boot.
 * A rising STM32 sync edge opens one capture window; the following falling edge
 * closes it, pauses acquisition, publishes the immutable ring contents, then resets
 * and resumes acquisition. No MQTT command or experiment identity is accepted. */
void pqc_energy_session_start(void);
void pqc_energy_session_snapshot(pqc_energy_session_snapshot_t *out);

#ifdef __cplusplus
}
#endif
