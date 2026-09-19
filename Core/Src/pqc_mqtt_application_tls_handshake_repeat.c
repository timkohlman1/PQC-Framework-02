#include "pqc_mqtt_application.h"
#include "pqc_wifi_config.h"

#ifndef PQC_TLS_HANDSHAKES_PER_RUN
#define PQC_TLS_HANDSHAKES_PER_RUN 1U
#endif

void PQC_MQTT_ApplicationRun(const PQC_MQTTApplicationFixture *fixture)
{
    int result;
    if (fixture == 0) return;

    fixture->uart_write("MQTT application: profile=tls_handshake_repeat state=starting\r\n");
    fixture->run_network_bringup();
    if (!fixture->is_network_ready()) {
        fixture->uart_write("MQTT application: profile=tls_handshake_repeat state=network_unavailable\r\n");
        return;
    }

    fixture->print_lwip_runtime();
    fixture->print_clock_configuration();
    fixture->print_memory_checkpoint();
    fixture->uart_write("MQTT application: profile=tls_handshake_repeat state=workload_start\r\n");
    result = fixture->run_tls_handshake_repeat_workload((uint32_t)PQC_TLS_HANDSHAKES_PER_RUN);
    if (result == 0) {
        fixture->mark_complete();
    } else {
        fixture->uart_write("MQTT application: profile=tls_handshake_repeat state=workload_failed\r\n");
    }
}
