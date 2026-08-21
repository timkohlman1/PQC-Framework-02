#include "pqc_mqtt_application.h"
#include "pqc_wifi_config.h"

void PQC_MQTT_ApplicationRun(const PQC_MQTTApplicationFixture *fixture)
{
    int result;
    if (fixture == 0) return;
    fixture->uart_write("MQTT application: profile=mqtt_ready_metrics_2 state=starting\r\n");
    fixture->run_network_bringup();
    if (!fixture->is_network_ready()) {
        fixture->uart_write("MQTT application: profile=mqtt_ready_metrics_2 state=network_unavailable\r\n");
        return;
    }
    fixture->print_lwip_runtime();
    fixture->print_wolfssl_runtime();
    fixture->print_clock_configuration();
    fixture->print_memory_checkpoint();
    fixture->uart_write("MQTT application: profile=mqtt_ready_metrics_2 state=workload_start\r\n");
    result = fixture->run_ready_metrics_2_workload(fixture->mark_complete);
    fixture->uart_write("MQTT application: profile=mqtt_ready_metrics_2 state=workload_stopped result=");
    (void)result;
}
