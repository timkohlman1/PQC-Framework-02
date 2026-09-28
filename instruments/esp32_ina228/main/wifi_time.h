#ifndef PQC_WIFI_TIME_H
#define PQC_WIFI_TIME_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool configured;
    bool connected;
    bool time_synced;
    char ip[16];
    int64_t last_sync_monotonic_us;
} pqc_wifi_time_snapshot_t;

/* Nonblocking startup. No acquisition clock is adjusted by SNTP. */
void pqc_wifi_time_start(void);
void pqc_wifi_time_snapshot(pqc_wifi_time_snapshot_t *out);

#endif
