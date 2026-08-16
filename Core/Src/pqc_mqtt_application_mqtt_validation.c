#include "pqc_mqtt_application.h"
#include "pqc_wifi_config.h"

void PQC_MQTT_ApplicationRun(const PQC_MQTTApplicationFixture *fixture)
{
    if (fixture == 0) return;
    fixture->uart_write("MQTT application: profile=mqtt_validation state=starting\r\n");
    fixture->run_network_bringup();
    if (!fixture->is_network_ready()) {
        fixture->uart_write("MQTT application: profile=mqtt_validation state=network_unavailable\r\n");
        return;
    }
    fixture->print_lwip_runtime();
    fixture->print_wolfmqtt_runtime();
    fixture->print_clock_configuration();
    fixture->print_memory_checkpoint();
    fixture->mark_complete();
}
