# Ready Metrics 2 profile matrix

This directory contains a one-for-one Ready Metrics 2 clone of every profile in
`configs/experiments/applications/ready_metrics/`.

Each profile selects `mqtt_ready_metrics_2`, retains the original network,
broker, authentication, certificate, key-exchange and capture configuration,
uses UART `info` for the transitional evidence path, and records the Ready
Metrics 2 timing contract:

- TTFB starts immediately before TCP connect after DNS resolution.
- TTFB ends on the first plaintext MQTT CONNACK byte returned to wolfMQTT.
- Firmware boot timing uses the first HAL tick captured immediately after
  `HAL_Init()`.

The Wi-Fi configuration is populated for the current experiment environment, so
the generated profiles require no per-profile credential editing.

Run the complete matrix sequentially with:

```powershell
.\scripts\dev.ps1 python scripts/run_all_ready_metrics_2_profiles.py
```

The runner stops on the first failed experiment and otherwise processes every
YAML profile in this directory in sorted order.

For plaintext MQTT, TLS timing remains explicitly unavailable. The host
validator accepts `boot_to_tls_complete_ms: 0` when `tls_timing_valid` is zero
and validates the remaining TCP/MQTT boot-time ordering.
