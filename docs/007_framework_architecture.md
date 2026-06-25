# Framework Architecture

## Purpose

This document describes the planned architecture of the PQC IoT experiment framework.

## Planned Layers

The framework is expected to cover:

1. firmware builds
2. remote flashing
3. UART and log capture
4. result manifests
5. boot-security variants
6. MQTT transport variants
7. TLS/classical crypto variants
8. PQC/hybrid crypto variants
9. network degradation profiles
10. benchmark aggregation and analysis

## Current Status

The repository contains the known-good STM32 HAL baseline firmware project.

The first minimal framework skeleton now exists.

Current implemented framework pieces:

```text
configs/
  boards/
    board_a.yaml
  hosts/
    gateway.yaml
  experiments/
    baseline_direct_uart.yaml
scripts/
  experiment.py
  framework/
    build.py
    manifest.py
tests/
  unit/
    test_build.py
    test_config_loading.py
    test_config_validation.py
    test_manifest.py
  integration/
    test_local_build.py
results/
tools/
pytest.ini
```

## Result Manifest Support

The framework can create a local result run folder for an experiment without building firmware, flashing hardware, opening UART devices, using SSH, or touching network resources.

Command:

```powershell
python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
```

The command creates:

```text
results/<run_id>/
  manifest.json
  notes.md
```

Run IDs use this format:

```text
YYYY-MM-DD_NNN_experiment_id
```

Example:

```text
2026-06-25_001_baseline_direct_uart
```

The initial manifest contains:

```text
run_id
timestamp
experiment
board
gateway
boot_mode
transport_mode
network_profile
result
```

The initial baseline values are derived from the resolved experiment, board, and host configs. Until dedicated transport and network config files are implemented, `transport_mode` defaults to `direct_uart` and `network_profile` defaults to `none`.


## Build Automation Support

The framework can now create a local result run folder and run the current CMake/STM32 firmware build without flashing hardware, opening UART devices, using SSH, or touching network resources.

Command:

```powershell
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
```

The command creates:

```text
results/<run_id>/
  manifest.json
  notes.md
  build.log
```

The build command currently uses the CMake `Debug` configure and build presets by default:

```text
cmake --preset Debug
cmake --build --preset Debug
```

The command captures:

```text
stdout
stderr
return code
build duration
output ELF path
build log path
```

Build metadata is written back into `manifest.json`. A successful local firmware build sets the manifest `result` field to `build_passed`. A failed configure, failed build, or missing expected ELF artifact sets it to `build_failed`.

The unit tests cover command construction and build-result handling without invoking CubeMX, CMake, Ninja, STM32 tooling, SSH, UART, or hardware.


## Integration Test Support

The framework now has an opt-in local build integration test:

```text
tests/integration/test_local_build.py
```

This test invokes the real CLI build command through a subprocess:

```powershell
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml --results-dir <temporary-results-dir>
```

The test is marked with the `integration` pytest marker and is skipped unless this environment variable is set:

```powershell
$env:PQC_RUN_LOCAL_BUILD_INTEGRATION = "1"
```

The test validates the local build automation against the real STM32/CMake/Ninja toolchain. It checks the command return code, generated result directory, `manifest.json`, `build.log`, expected CMake configure/build commands, and expected ELF artifact state. It must not flash hardware, open UART devices, use SSH, or touch network resources.

Unit tests remain isolated from CubeMX, CMake, Ninja, STM32 tooling, SSH, UART, and hardware by using injected or mocked command runners.
