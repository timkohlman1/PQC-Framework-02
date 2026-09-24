#include "pqc_mqtt_application.h"

/* The measurement phase has already finished before the network task exists.
 * This workload performs reporting-path initialization only; it must never
 * run the experiment broker's TLS or application workload. */
void PQC_MQTT_ApplicationRun(const PQC_MQTTApplicationFixture *fixture)
{
    if (fixture == 0) return;
    fixture->uart_write("PQC_BENCHMARK phase=reporting_start\r\n");
    fixture->run_network_bringup();
    if (!fixture->is_network_ready()) {
        fixture->uart_write("PQC_BENCHMARK phase=reporting_network_unavailable\r\n");
        return;
    }
    fixture->mark_complete();
}
