# PQC-Framework-02

STM32-based embedded security experiment framework.

The current known-good baseline is a CubeMX-generated STM32 HAL firmware project for the NUCLEO-L4R5ZI-P / STM32L4R5 board.

## Current baseline status

- STM32 HAL firmware project builds successfully.
- Firmware can be flashed remotely through `pqc-gateway1`.
- ST-LINK UART logging works.
- The app prints a boot message and repeated `tick` messages.
- wolfBoot, MQTT, TLS, PQC, and network-degradation automation are not implemented yet.

## AI-assisted development

For every AI-assisted feature request, provide `AI_BUILD_GUIDE.md` first.

Workflow and prompt documentation:

- `docs/001_ai_feature_request_workflow.md`
- `docs/008_chatgpt_project_prompt.md`

The AI agent should use `AI_BUILD_GUIDE.md` as the source of truth for:

- current repository structure
- known-good baseline
- current implementation phase
- testing expectations
- documentation requirements
- safety and secret-handling rules

## Repository layout

The STM32CubeMX-generated firmware project currently lives at the repository root.

Do not move CubeMX-generated folders unless that change is deliberate and documented.

Important documentation:

- `AI_BUILD_GUIDE.md`
- `docs/000_project_overview.md`
- `docs/001_ai_feature_request_workflow.md`
- `docs/002_host_gateway_setup.md`
- `docs/003_stm32_board_setup.md`
- `docs/004_baseline_hal_app.md`
- `docs/005_remote_flash_workflow.md`
- `docs/006_security_and_secrets.md`
- `docs/007_framework_architecture.md`
- `docs/008_chatgpt_project_prompt.md`
- `docs/decisions/`


## Framework CLI

Check the current baseline experiment configuration without using hardware:

```powershell
python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
```

Create a local result run folder without building, flashing, opening UART, using SSH, or touching network resources:

```powershell
python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
```

Build the current STM32 firmware locally without flashing, opening UART, using SSH, or touching network resources:

```powershell
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
```

The create-run command creates:

```text
results/<run_id>/
  manifest.json
  notes.md
```

The build command creates:

```text
results/<run_id>/
  manifest.json
  notes.md
  build.log
```

The build command runs the CMake configure and build presets, captures stdout, stderr, return codes, build duration, and the expected output ELF path, then records build metadata in the run manifest.

Flash the existing configured ELF through the gateway:

```powershell
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml
```

The flash command creates `flash.log`, copies the ELF to `/tmp` with `scp`, invokes the configured gateway flash helper with `ssh`, and records the return codes, remote artifact path, and ST-LINK serial in `manifest.json`. It does not capture UART output.

Build and then flash the resulting ELF in one result run:

```powershell
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml
```

The build-flash command creates one `results/<run_id>/` directory, writes both `build.log` and `flash.log` when the build succeeds, and records combined `build_flash` metadata in the same `manifest.json`. If the build fails, the flash step is skipped so a stale ELF is not flashed.

Run IDs use the format:

```text
YYYY-MM-DD_NNN_experiment_id
```

Example:

```text
2026-06-25_001_baseline_direct_uart
```

## Tests

Run framework unit tests without invoking CubeMX, CMake, Ninja, STM32 tooling, SSH, UART, or hardware:

```powershell
python -m pytest tests/unit
```

The local build integration test is opt-in because it runs the real local STM32/CMake build command. It does not flash hardware, open UART devices, use SSH, or touch network resources.

Run the integration test only on a development PC with the valid STM32/CMake/Ninja toolchain available:

```powershell
$env:PQC_RUN_LOCAL_BUILD_INTEGRATION = "1"
python -m pytest tests/integration -m integration
```

Without `PQC_RUN_LOCAL_BUILD_INTEGRATION=1`, the local build integration test is skipped.

The real gateway flash integration test is separately opt-in because it uses SSH and physical hardware:

```powershell
$env:PQC_RUN_GATEWAY_FLASH_INTEGRATION = "1"
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration
```

## Development rule

Preserve the current known-good STM32 HAL baseline unless a change explicitly targets it.

Do not commit secrets, private keys, credentials, generated build outputs, or experiment results.
