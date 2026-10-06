# Decision 0001 — Keep CubeMX Project at Repository Root

> Historical record. Original phase instructions, capability limits, commands and
> handling rules below describe their original context. Use the
> [current reference](../007_framework_architecture.md) and [open-data policy](../006_security_and_secrets.md)
> for present work; this record does not authorize implementing old requests.

## Context

The current STM32CubeMX-generated firmware project builds successfully from the repository root.

The current structure includes:

```text
CMakeLists.txt
CMakePresets.json
cmake/
Core/
Drivers/
STM32L4R5XX_FLASH.ld
startup_stm32l4r5xx.s
stm32_basic_hal1.ioc
```

## Decision

Keep the CubeMX-generated files and folders at the repository root for now.

## Reason

STM32CubeMX, STM32 VS Code tooling, and CMake paths can be sensitive to project layout.

Moving the firmware project before the framework is stable would add unnecessary risk.

## Consequences

Framework folders such as `configs/`, `scripts/`, `tests/`, and `docs/` will be added alongside the firmware project.

A later restructure can be considered once the framework is stable and the firmware build process is well understood.
