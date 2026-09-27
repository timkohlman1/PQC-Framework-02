#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "driver/i2c.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    bool online;
    bool valid;
    bool paused;
    uint64_t sample_sequence;
    int64_t timestamp_us;
    double bus_v;
    double current_a;
    double power_w;
    uint32_t read_duration_us;
    uint32_t status_flags;
    uint32_t i2c_errors;
    uint32_t alert_timeouts;
    uint32_t coalesced_alerts;
    uint32_t timing_errors;
    uint32_t saturation_errors;
    uint32_t sample_gaps;
    uint16_t diagnostic_flags;
} pqc_ina228_snapshot_t;

/* The touch controller must initialise the shared I2C bus before this call. */
void pqc_ina228_sparkfun_start(i2c_port_t port);
typedef void (*pqc_ina228_sample_callback_t)(const pqc_ina228_snapshot_t *sample);

void pqc_ina228_sparkfun_snapshot(pqc_ina228_snapshot_t *out);
void pqc_ina228_sparkfun_set_sample_callback(pqc_ina228_sample_callback_t callback);

#ifdef __cplusplus
}
#endif

/* Called only outside a measured interval. Pause waits for the acquisition task
 * to finish its current sample. Resume preserves sequence/error counters. */
#ifdef __cplusplus
extern "C" {
#endif
bool pqc_ina228_sparkfun_pause(uint32_t timeout_ms);
void pqc_ina228_sparkfun_resume(void);
bool pqc_ina228_sparkfun_is_paused(void);
#ifdef __cplusplus
}
#endif
