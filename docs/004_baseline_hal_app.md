# Baseline HAL Application

## Purpose

This document describes the current known-good STM32 HAL firmware baseline.

## Behaviour

The baseline application:

- initialises the STM32 HAL
- configures GPIO
- configures LPUART1
- toggles LD2
- prints a boot message
- prints repeated `tick` messages

## Expected UART Output

```text
stm32-basic_hal1 boot v0.1.0
tick
tick
tick
```

## Current Role

This is the direct-flash baseline.

It does not yet use:

- wolfBoot
- MQTT
- TLS
- PQC
- network degradation
- automated result manifests

## Build Status

The baseline has been confirmed to build successfully from the current repository location.

## Flash Status

The baseline has been confirmed to flash remotely through `pqc-gateway1` using ST-LINK/SWD.

## Notes

This document should be updated when the baseline application is modified or when automated build/flash/log capture is added.
