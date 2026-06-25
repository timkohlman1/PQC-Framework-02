# Remote Flash Workflow

## Purpose

This document records the manual remote flashing workflow used before automation is added.

## Manual Flash Command

From the Windows development PC:

```powershell
scp .\build\Debug\stm32_basic_hal1.elf pqc-gateway1:/tmp/stm32_basic_hal1.elf
ssh pqc-gateway1 "flash-stm32a /tmp/stm32_basic_hal1.elf"
```

## Manual UART Capture

On the gateway:

```bash
picocom -b 115200 /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
```

## Expected Result

The board should reset, boot, blink LD2, and print the baseline UART output.

Expected UART output:

```text
stm32-basic_hal1 boot v0.1.0
tick
tick
tick
```

## Current Flash Helper

```text
flash-stm32a
```

## Notes

This workflow should be preserved as the known-good manual fallback even after automation is added.
