# ESP32-S3 / INA228 passive recorder

This ESP-IDF project implements the persistent GPIO-triggered energy appliance.
It samples into a PSRAM ring, pauses after the closing edge and publishes the
completed capture to the reporting broker. It has no experiment command protocol.
Normal STM32 campaigns do not flash or reconfigure it.

The [instrument guide](../../docs/010_esp32_ina228_energy_instrument.md) owns wiring,
configuration, calibration, sample/transport format, manual build/flash and validation.
[Results and analysis](../../docs/012_results_and_analysis.md#energy) owns energy
integration and cross-clock interpretation.

Local `sdkconfig` remains generated/ignored configuration. Its experiment Wi-Fi
settings and all other framework material follow the
[open-data policy](../../docs/006_security_and_secrets.md).
