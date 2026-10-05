# STM32 Board Setup

## Purpose

This document owns the physical board, ST-LINK, UART, and memory configuration used by the experiment framework. Gateway identity and SSH setup are owned by `docs/002_host_gateway_setup.md`; flash and capture commands are owned by `docs/005_remote_flash_workflow.md`.

## Target board

```text
Board: NUCLEO-L4R5ZI-P / NUCLEO-L4R5ZI
MCU: STM32L4R5 / STM32L4Rxxx
Flash: 2 MB
Primary RAM: 192 KB
RAM2: 64 KB
RAM3: 384 KB
```

## ST-LINK and UART

```text
ST-LINK serial: 066EFF3932504E3043111818
UART interface: LPUART1
UART device: /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
Baud: 115200
Format: 8N1
Flow control: none
```

The persistent `/dev/serial/by-id/` path is the canonical UART device for the configured board. Do not infer board identity from a transient `/dev/ttyACM*` name.

## Current firmware evidence model

Current application builds use the relocated layout and separate heartbeat/network
tasks. UART diagnostics are optional according to the selected mode; local helper
markers establish only their stated boundary. Networked scientific capture uses
deferred reporting records. See [baseline firmware](004_baseline_hal_app.md) for
startup, [architecture](007_framework_architecture.md) for runtime capabilities,
and [results](012_results_and_analysis.md) for evidence interpretation.

## Hardware evidence rules

- A build or link result is software-build evidence only.
- Flash success requires the gateway flash workflow log or manifest.
- UART success requires a bounded capture from the configured device.
- Secure-boot, timing, cycles, stack, heap, MQTT/TLS, or benchmark claims require their explicit UART fields, broker/client logs, or manifests.
- A monitor-only capture cannot prove which image is running unless image provenance is established separately.

Use `docs/005_remote_flash_workflow.md` for wrapper commands and provenance requirements.

## ST67 GPIO/SPI bring-up diagnostic

The firmware invokes the ST67 driver from `networkTask`. The task context is required because the driver
uses FreeRTOS delays, queues, semaphores, and interrupt-driven SPI handling.

The diagnostic performs the following bounded sequence:

1. waits 3 seconds in the FreeRTOS task so a logic-analyser capture can start without resetting the board during acquisition;
2. holds `BOOT`, `CHIP_EN`, and the active-high `SPI_CS` low;
3. records the initial `BOOT`, `CHIP_EN`, `SPI_RDY`, and `SPI_CS` states on UART;
4. initializes the ST67 logging service;
5. calls `W6X_Init()`, which raises `CHIP_EN` and performs the vendor-defined
   SPI transport and module initialization;
6. records the returned `W6X_Status_t` value and final GPIO states.

The UART evidence begins with `ST67 SPI bring-up: begin` and ends with
`ST67 SPI bring-up: complete`. A successful result establishes only that the
STM32 invoked the ST67 driver and that the driver reported successful module
initialization. It does not establish Wi-Fi association, IP acquisition, an
external TCP connection, a TLS handshake, MQTT operation, or end-to-end
wireless success.

The current validated runtime configuration uses SPI1 prescaler 4 (approximately 30 Mbit/s with the current 120 MHz PCLK2). The earlier prescaler-32 setting was a temporary logic-analyser diagnostic and is no longer the supported runtime configuration. A logic-analyser capture at the current rate requires equipment and sampling settings capable of resolving the faster bus. Start the capture during the 3-second UART-announced delay; no board reset is required while acquisition is active.

Do not reuse the earlier 12 MHz FX2 capture command at this rate; it cannot reliably decode an approximately 30 Mbit/s SPI clock.

The expected physical ordering is `CHIP_EN` rising, `SPI_RDY` activity, active
high `SPI_CS`, SPI clock bursts, and MOSI/MISO transfers. Compare those
transitions with the UART markers rather than treating either source alone as
higher-level network evidence.

### ST67 vendor transport baseline

The transport derives from
`Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c`, with project
integration, READY-level guards, bounded polling and diagnostics. Inspect that
source before changing transaction behavior; it is not an unmodified vendor copy.

The lwIP output adapter also follows the vendor `lwip_netif.c` behavior: each segment in a chained lwIP `pbuf` is submitted to `W6X_Netif_output()` in sequence. The framework does not coalesce the chain into a temporary contiguous allocation.

A provenance-backed 30-second hardware run with this vendor-aligned transport, SPI prescaler 4, configured-AP association, and DHCP completed without `Invalid magic 0xffff`, READY-wait timeout, or SPI transaction-timeout messages. This evidence covers only the captured interval and the association/DHCP path; sustained external traffic, TLS, MQTT, and end-to-end protocol operation require separate evidence.
