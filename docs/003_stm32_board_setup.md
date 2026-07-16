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

The current application is a CubeMX-generated HAL/CMSIS-RTOS v2 FreeRTOS firmware with direct-flash and relocated secure-boot builds. A representative successful direct-flash capture includes the application boot marker, scheduler/task markers, and recurring `tick` output. It may also include local-only lwIP and wolfSSL smokes, STM32-local UDP loopback, and fake/no-network wolfMQTT initialization.

Those markers are evidence only for the boundary explicitly named in each line. They do not establish ST67W61M1 detection, Wi-Fi association, hardware-backed IP, external TCP, certificate-backed TLS handshake, real MQTT broker operations, or end-to-end wireless success. The canonical capability matrix and exact marker interpretation are in `docs/007_framework_architecture.md`.

## Hardware evidence rules

- A build or link result is software-build evidence only.
- Flash success requires the gateway flash workflow log or manifest.
- UART success requires a bounded capture from the configured device.
- Secure-boot, timing, cycles, stack, heap, MQTT/TLS, or benchmark claims require their explicit UART fields, broker/client logs, or manifests.
- A monitor-only capture cannot prove which image is running unless image provenance is established separately.

Use `docs/005_remote_flash_workflow.md` for wrapper commands and provenance requirements.

## ST67 GPIO/SPI bring-up diagnostic

The `feature/st67-spi-bringup` firmware invokes the existing ST67 vendor driver
from the FreeRTOS default task. The task context is required because the driver
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

For logic-analyser capture, SPI1 is temporarily reduced to prescaler 32 (approximately 3.75 Mbit/s with the current 120 MHz PCLK2) so the FX2 analyser can sample it reliably. Start the capture during the 3-second UART-announced delay; no board reset is required while acquisition is active. Use:

```bash
sudo sigrok-cli \
  --driver fx2lafw:conn=3.5 \
  --config samplerate=12m \
  --channels D0=SCK,D1=MISO,D2=MOSI,D3=CS,D4=BOOT,D5=CHIP_EN,D6=RDY \
  --time 5s \
  --output-file st67-startup.sr
```

Decode the active-high, mode-0 SPI traffic with:

```bash
sigrok-cli \
  --input-file st67-startup.sr \
  --protocol-decoders \
  'spi:clk=SCK:miso=MISO:mosi=MOSI:cs=CS:cs_polarity=active-high:cpol=0:cpha=0:bitorder=msb-first:wordsize=8' \
  --protocol-decoder-annotations \
  'spi=miso-data:mosi-data:warnings' \
  > st67-spi.txt
```

The expected physical ordering is `CHIP_EN` rising, `SPI_RDY` activity, active
high `SPI_CS`, SPI clock bursts, and MOSI/MISO transfers. Compare those
transitions with the UART markers rather than treating either source alone as
higher-level network evidence.

