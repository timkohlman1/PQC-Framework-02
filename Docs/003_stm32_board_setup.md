# STM32 Board Setup

## Purpose

This document records the current STM32 board, ST-LINK, UART, and memory details used by the experiment framework.

## Target Board

```text
Board: NUCLEO-L4R5ZI-P / NUCLEO-L4R5ZI
MCU: STM32L4R5 / STM32L4Rxxx
Flash: 2 MB
Primary RAM: 192 KB
RAM2: 64 KB
RAM3: 384 KB
```

## ST-LINK

```text
ST-LINK serial: 066EFF3932504E3043111818
UART path: /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
```

## Current UART Configuration

```text
Interface: LPUART1
Baud: 115200
Data: 8N1
Flow control: none
```

## Current Baseline Behaviour

The board currently runs a direct-flash STM32 HAL baseline application.

Expected UART output:

```text
stm32-basic_hal1 boot v0.1.0
tick
tick
tick
```

## Notes

This document should be updated if additional boards are added or if board aliases are introduced in the framework configuration.
