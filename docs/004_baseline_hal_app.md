# Baseline HAL Application

## Purpose

This document describes the current STM32 HAL firmware baseline and how it relates to the secure-boot benchmark workflows.

## Direct-flash baseline behaviour

The direct-flash baseline application:

- initializes the STM32 HAL
- configures GPIO and LPUART1
- toggles LD2
- prints a boot marker
- prints repeated `tick` messages

Expected UART output:

```text
stm32-basic_hal1 boot v0.1.0
tick
tick
tick
```

The direct-flash experiment profile is:

```text
configs/experiments/baseline_direct_uart.yaml
```

The explicit direct-flash boot profile is:

```text
configs/boot/direct_flash.yaml
```

## Relocated secure-boot application

The secure-boot workflows use the same HAL application payload, built with the `RelocatedDebug` CMake preset and the relocated linker script:

```text
CMakePresets.json
STM32L4R5XX_FLASH_RELOCATED.ld
```

The relocated application entry address is `0x08022000`, leaving the shared Phase 11 wolfBoot image-header reserve at the signed image slot start.

When compiled as the secure-boot application, the firmware emits an additional UART marker before the normal boot marker:

```text
stm32-basic_hal1 secure-boot app v0.1.0
stm32-basic_hal1 boot v0.1.0
tick
```

The secure-boot marker is required for positive secure-boot UART evidence. The framework must not infer wolfBoot-mediated boot identity from the normal baseline marker alone.

## Out of scope for the current HAL app

The current firmware does not implement MQTT, TLS, PQC/hybrid crypto, or network degradation logic.
