# Remote Flash Workflow

## Purpose

This document records the automated and manual remote flashing workflows for the current STM32 HAL baseline.

## Automated Flash Command

From the repository root on the Windows development PC:

```powershell
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml
```

The command:

1. loads and validates the experiment, board, and host configs
2. verifies that the configured local ELF exists
3. copies the ELF to `/tmp/<artifact-name>` on the configured gateway with `scp`
4. invokes the configured gateway flash helper with `ssh`
5. writes `results/<run_id>/flash.log`
6. records flash metadata in `results/<run_id>/manifest.json`

Captured metadata includes the SCP and helper return codes, final return code, local and remote artifact paths, flash log path, duration, and configured ST-LINK serial.

The flash command does not capture UART output.

## Opt-In Integration Test

The real gateway flash integration test is disabled by default because it uses SSH and physical hardware.

Run it only after building the configured ELF and confirming the gateway and board are available:

```powershell
$env:PQC_RUN_GATEWAY_FLASH_INTEGRATION = "1"
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration
```

Without `PQC_RUN_GATEWAY_FLASH_INTEGRATION=1`, the test is skipped.

## Manual Flash Fallback

The known-good manual workflow remains available:

```powershell
scp .uild\Debug\stm32_basic_hal1.elf pqc-gateway1:/tmp/stm32_basic_hal1.elf
ssh pqc-gateway1 "flash-stm32a /tmp/stm32_basic_hal1.elf"
```

## Manual UART Capture

On the gateway:

```bash
picocom -b 115200 /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
```

## Expected Result

A successful flash helper invocation should program and reset the board. UART verification remains a separate manual step in this phase.

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

Do not hard-code SSH private-key paths. The automation uses the configured gateway alias and relies on the local SSH configuration.
