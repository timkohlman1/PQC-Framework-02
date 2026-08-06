#ifndef PQC_MQTT_APPLICATION_H
#define PQC_MQTT_APPLICATION_H

#include <stdbool.h>

typedef struct
{
  void (*uart_write)(const char *text);
  void (*run_network_bringup)(void);
  bool (*is_network_ready)(void);
  void (*print_lwip_runtime)(void);
  void (*print_wolfssl_runtime)(void);
  void (*print_wolfmqtt_runtime)(void);
  void (*print_clock_configuration)(void);
  void (*print_memory_checkpoint)(void);
  void (*mark_complete)(void);
} PQC_MQTTApplicationFixture;

void PQC_MQTT_ApplicationRun(const PQC_MQTTApplicationFixture *fixture);

#endif
