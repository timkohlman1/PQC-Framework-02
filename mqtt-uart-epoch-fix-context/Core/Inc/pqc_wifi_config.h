#ifndef PQC_WIFI_CONFIG_H
#define PQC_WIFI_CONFIG_H

#if defined(__has_include)
#  if __has_include("pqc_wifi_config_generated.h")
#    include "pqc_wifi_config_generated.h"
#  else
#    define PQC_WIFI_SSID ""
#    define PQC_WIFI_PSK ""
#    define PQC_WIFI_IPV4_MODE "unconfigured"
#    define PQC_MQTT_ENABLED 0
#    define PQC_MQTT_BROKER_HOST ""
#    define PQC_MQTT_BROKER_PORT 1883
#    define PQC_MQTT_DNS_REQUIRED 0
#    define PQC_MQTT_CLIENT_ID "pqc-stm32"
#    define PQC_MQTT_COMMAND_TOPIC "pqc/stm32/command"
#    define PQC_MQTT_RESPONSE_TOPIC "pqc/stm32/response"
#    define PQC_MQTT_CORRELATION_PAYLOAD "pqc-e2e"
#  endif
#else
#  define PQC_WIFI_SSID ""
#  define PQC_WIFI_PSK ""
#  define PQC_WIFI_IPV4_MODE "unconfigured"
#  define PQC_MQTT_ENABLED 0
#  define PQC_MQTT_BROKER_HOST ""
#  define PQC_MQTT_BROKER_PORT 1883
#  define PQC_MQTT_DNS_REQUIRED 0
#  define PQC_MQTT_CLIENT_ID "pqc-stm32"
#  define PQC_MQTT_COMMAND_TOPIC "pqc/stm32/command"
#  define PQC_MQTT_RESPONSE_TOPIC "pqc/stm32/response"
#  define PQC_MQTT_CORRELATION_PAYLOAD "pqc-e2e"
#endif

#ifndef PQC_MQTT_TLS_MODE
#define PQC_MQTT_TLS_MODE "plaintext"
#endif

#ifndef PQC_MQTT_TLS_SERVER_NAME
#define PQC_MQTT_TLS_SERVER_NAME ""
#endif

#ifndef PQC_MQTT_TLS_CA_PEM
#define PQC_MQTT_TLS_CA_PEM ""
#endif

#ifndef PQC_MQTT_TLS_CA_PEM_SHA256
#define PQC_MQTT_TLS_CA_PEM_SHA256 ""
#endif

#ifndef PQC_MQTT_TLS_SERVER_SIGNATURE_ALGORITHM
#define PQC_MQTT_TLS_SERVER_SIGNATURE_ALGORITHM ""
#endif

#endif
