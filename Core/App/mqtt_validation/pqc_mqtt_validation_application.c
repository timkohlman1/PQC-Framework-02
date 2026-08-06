#include "pqc_mqtt_application.h"
#include "pqc_wifi_config.h"

#ifndef PQC_STM32_MQTT_APPLICATION_NAME
#define PQC_STM32_MQTT_APPLICATION_NAME "mqtt_validation"
#endif

void PQC_MQTT_ApplicationRun(const PQC_MQTTApplicationFixture *fixture)
{
  bool network_ready;

  if ((fixture == 0) || (fixture->uart_write == 0) ||
      (fixture->run_network_bringup == 0) || (fixture->is_network_ready == 0))
  {
    return;
  }

  fixture->uart_write("PQC_APPLICATION_SELECTED application="
                      PQC_STM32_MQTT_APPLICATION_NAME "\r\n");
  fixture->run_network_bringup();
  network_ready = fixture->is_network_ready();

  if (fixture->print_lwip_runtime != 0)
  {
    fixture->print_lwip_runtime();
  }
  if (fixture->print_wolfssl_runtime != 0)
  {
    fixture->print_wolfssl_runtime();
  }
  if (network_ready && (fixture->print_wolfmqtt_runtime != 0))
  {
    fixture->print_wolfmqtt_runtime();
  }
  else if (!network_ready)
  {
    fixture->uart_write(
        "wolfMQTT runtime: result=skipped reason=network_not_ready "
        "end_to_end=failed\r\n");
  }

  if (fixture->print_clock_configuration != 0)
  {
    fixture->print_clock_configuration();
  }
  if (fixture->print_memory_checkpoint != 0)
  {
    fixture->print_memory_checkpoint();
  }
  if (fixture->mark_complete != 0)
  {
    fixture->mark_complete();
  }
  fixture->uart_write("PQC_EXPERIMENT_COMPLETE experiment="
                      PQC_MQTT_TLS_MODE " status=done\r\n");
}
