# Remote Flash Workflow

## Purpose

This document records the automated and manual remote flashing workflows for the current STM32 HAL baseline.

## Automated Flash Command

The normal flash command requires an explicit verified build run so that the framework can prove the configured ELF matches recorded build provenance before using SCP or SSH.

From the repository root on the Windows development PC:

```powershell
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart
```

The command:

1. loads and validates the experiment, board, and host configs
2. verifies that the configured local ELF exists
3. records Git source-control provenance at flash time
4. calculates the configured ELF SHA-256 before SCP
5. calculates the current expected build fingerprint
6. reads the requested build-run manifest
7. refuses SCP and SSH unless the flash-time ELF SHA-256 and current build fingerprint match the recorded build
8. copies the ELF to `/tmp/<artifact-name>` on the configured gateway with `scp` after provenance is verified
9. invokes the configured gateway flash helper with `ssh` after SCP succeeds
10. writes `results/<run_id>/flash.log`
11. records flash metadata in `results/<run_id>/manifest.json`

Captured metadata includes the SCP and helper return codes, final return code, local and remote artifact paths, firmware SHA-256, source build run ID, source build fingerprint, current build fingerprint, flash provenance status, flash log path, duration, and configured ST-LINK serial.

The flash command does not capture UART output unless `--capture-uart` is explicitly supplied.

## Explicit Untracked-Artifact Escape Hatch

For manual recovery or investigation, the framework can flash the configured artifact without a matching build-run manifest only when explicitly requested:

```powershell
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --allow-untracked-artifact
```

This records `flash.provenance_status` as `untracked_artifact_allowed` in the manifest. Do not use this mode for normal experiment runs.

## Post-Flash UART Capture

To flash an existing verified artifact and then capture UART boot evidence in the same result run:

```powershell
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart --capture-uart
```

Post-flash UART capture starts the UART reader first, triggers the configured gateway reset helper after capture is active, writes `uart.log` inside the run directory, and evaluates the configured boot and tick markers.

## Capability-Gated Integration Test

The real gateway flash integration test uses the local build toolchain, SSH, the configured gateway flash helper, ST-LINK, and the target board. It no longer requires an environment variable. Pytest checks the required capabilities and runs the test only when they are available.

Default behaviour:

```powershell
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration
```

If the local toolchain, gateway SSH access, or flash helper is unavailable, the test is skipped with a clear reason.

Use strict mode when the gateway flash path is expected to be available and missing capabilities should fail the test run:

```powershell
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
```

The gateway flash integration test first creates a verified build record in a temporary results directory and then flashes using that build run. This keeps the flash provenance gate active during the test.

## Manual Flash Fallback

The known-good manual workflow remains available:

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

A successful flash helper invocation should program and reset the board. UART verification can be performed manually or through the framework's post-flash UART capture workflow.

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
