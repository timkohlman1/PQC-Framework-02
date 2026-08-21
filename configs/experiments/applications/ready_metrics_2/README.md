# Ready Metrics 2 profile matrix

This directory contains a one-for-one Ready Metrics 2 clone of every profile in
`configs/experiments/applications/ready_metrics/`.

Each profile selects `mqtt_ready_metrics_2`, retains the original network,
broker, authentication, certificate, key-exchange and capture configuration,
uses UART `info` for the transitional evidence path, and adds a broker-mediated
application download benchmark aligned to the Time-To-Last-Byte methodology
used by Kampanakis and Childs-Klein.

The timing model is:

- MQTT connection TTFB starts immediately before TCP connect after DNS
  resolution and ends on the first plaintext MQTT CONNACK byte.
- Application TTFB uses the same TCP-connect origin and ends on the first byte
  of the requested application payload received by the STM32.
- TTLB uses the same TCP-connect origin and ends on the last byte of the
  requested application payload received by the STM32.
- The STM32 publishes a small transfer request after MQTT CONNECT and
  SUBSCRIBE; a gateway-side MQTT responder publishes the configured payload
  through the broker to the STM32 over the established MQTT/TLS connection.
- Firmware boot timing uses the first HAL tick captured immediately after
  `HAL_Init()`.

The default transfer is 200 KiB (`204800` bytes), matching one of the principal
application-data sizes in the referenced TTLB study. The transfer size is
profile-configurable through `mqtt.transfer.payload_bytes`. Payloads are
received incrementally; the firmware does not allocate a buffer equal to the
entire transfer size.

The Wi-Fi configuration is populated for the current experiment environment,
so the generated profiles require no per-profile credential editing.

Run the complete matrix sequentially from the Windows host with:

```powershell
python scripts\run_all_ready_metrics_2_profiles.py
```

Do not invoke the runner through `dev.ps1 python`; each profile is already
launched through `dev.ps1 experiment-gateway run`. The runner stops on the
first failed experiment and otherwise processes every YAML profile in sorted
order.

For plaintext MQTT, TLS timing remains explicitly unavailable. The host
validator preserves zero for the unavailable TLS-complete timestamp while
validating TCP, MQTT, application-first-byte, application-last-byte, and ready
ordering.
