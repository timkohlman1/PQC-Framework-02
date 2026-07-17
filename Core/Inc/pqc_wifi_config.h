#ifndef PQC_WIFI_CONFIG_H
#define PQC_WIFI_CONFIG_H

/*
 * Framework experiment builds generate pqc_wifi_config_generated.h in the
 * active build directory. Detect it at compile time so generation may occur
 * after CMake configuration while direct/manual builds retain safe defaults.
 */
#if defined(__has_include)
#  if __has_include("pqc_wifi_config_generated.h")
#    include "pqc_wifi_config_generated.h"
#  else
#    define PQC_WIFI_SSID ""
#    define PQC_WIFI_PSK ""
#    define PQC_WIFI_IPV4_MODE "unconfigured"
#  endif
#else
#  define PQC_WIFI_SSID ""
#  define PQC_WIFI_PSK ""
#  define PQC_WIFI_IPV4_MODE "unconfigured"
#endif

#endif
