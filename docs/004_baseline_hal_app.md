# Baseline firmware and diagnostics

This reference owns application startup and local diagnostic meaning. The
[architecture](007_framework_architecture.md) owns the full runtime capability
model; [results and analysis](012_results_and_analysis.md) owns scientific capture
and measurement interpretation. Diagnostic strings depend on the selected UART
mode and are not a universal MQTT success predicate.

## Startup and task ownership

`Core/Src/main.c` performs these steps:

1. Initialize MSP watermarking and HAL; read any compatible wolfBoot handoff.
2. Configure clocks and TIM2 measurement time; initialize GPIO, DMA, SPI and
   UART when enabled.
3. Emit available boot/mailbox diagnostics, the application boot marker and
   local lwIP helper/netif state.
4. Configure the selected wolfSSL allocator. For `baremetal_benchmark`, run
   primitive measurements before kernel initialization and retain their records.
5. Initialize the kernel and create `defaultTask` and `networkTask`.
6. Emit available pre-scheduler memory/scheduler diagnostics and start FreeRTOS.

`defaultTask` toggles the LED with `osDelay(1000)` and emits a bounded memory
checkpoint. `networkTask` owns ST67 bring-up and the selected application fixture.
The old recurring standalone `tick` line and wolfSSL local-context smoke sequence
are not the current startup contract. The retained wolfSSL fixture callback is a
no-op. HAL uses TIM1, FreeRTOS uses SysTick and research timing uses TIM2.

Useful diagnostic markers in UART-enabled runs include:

```text
stm32-basic_hal1 secure-boot app v0.1.0
stm32-basic_hal1 boot v0.1.0
FreeRTOS defaultTask created:
FreeRTOS networkTask created:
FreeRTOS scheduler starting:
FreeRTOS defaultTask started
FreeRTOS networkTask started: initialization active
```

The secure-boot application marker identifies the relocated payload; it alone
does not prove verification. Scheduling can interleave task output. Exact fields
are owned by firmware sources and behavioral/source-contract tests, not a copied
full expected log in this document.

## Local helpers and live networking

The non-network lwIP runtime smoke checks version, IPv4 formatting, and checksum
helpers. It does not initialize a netif or contact external hardware. A local
loopback observation and fake/no-network wolfMQTT initialization similarly prove
only their stated local boundary. Historical `build_only` filenames do not limit
the separately implemented socket/TLS path.

Normal ST67 startup initializes the module, Wi-Fi and lwIP, then associates with
the configured AP and waits for DHCP. The optional AP-inventory scan is disabled
by default (`PQC_ST67_WIFI_DIAGNOSTIC_SCAN=0`). An explicit diagnostic CMake build
can enable it with `-DPQC_ST67_WIFI_DIAGNOSTIC_SCAN=ON`; this adds scan time and
energy before association and must be kept separate from normal experiments.
It does not disable any discovery internal to `W6X_WiFi_Connect`. When the explicit
scan is disabled, its deferred phase record remains `state=0` (`not_attempted`),
with no invented zero-duration measurement or added UART message. In diagnostic
mode, a scan failure does not itself cancel the configured association attempt. Later live
network evidence comes from the actual station netif, including its assigned
IPv4 address; pre-network unavailable markers do not override it.

The baseline UART hardware test selects full diagnostic output and checks the
latest boot from its own prepared image. Association/DHCP acceptance requires both
pass markers and a nonzero IPv4 address. Those observations do not establish an
external TCP connection, TLS handshake, MQTT exchange or complete profile matrix.
The separate workload tests use their own device/broker/capture contracts.

Current implementation resolves Wi-Fi environment references during preparation,
uses values in generated build inputs, and redacts logs/provenance. This behavior
is distinct from the [open-data policy](006_security_and_secrets.md); experiment
Wi-Fi settings are not confidential.

## UART modes and transport diagnostics

`disabled` excludes LPUART initialization and HAL UART linkage. `minimal` suppresses
UART during the measured workload while retaining supported boot/fault/recovery
and post-workload diagnostics. `full` permits diagnostic output and can perturb
measurements. `[tick=...]` prefixes, where emitted, are HAL millisecond diagnostics,
not TIM2 research checkpoints. The captured `uart.log` remains raw device output.

SPI1 uses `SPI_BAUDRATEPRESCALER_4`, approximately 30 Mbit/s with the configured
120 MHz peripheral clock. The ST67 transport derives from the vendor `spi_iface.c`
implementation with project guards/diagnostics and bounded polling paths; it is
not an unmodified vendor copy. The lwIP adapter submits each segment in a chained
`pbuf` to `W6X_Netif_output()`. GPIO/SPI activity or module initialization proves
only that boundary, not higher-level protocol success.

For wiring and analyzer constraints use [board setup](003_stm32_board_setup.md).
For known-image capture and flash commands use the
[operating guide](005_remote_flash_workflow.md). Current coverage and missing
qualification are listed in [testing](013_testing_and_deferred_coverage.md).
