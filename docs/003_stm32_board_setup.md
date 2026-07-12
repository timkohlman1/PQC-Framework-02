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
