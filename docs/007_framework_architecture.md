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
    manifest.py
tests/
  unit/
    test_config_loading.py
    test_config_validation.py
    test_manifest.py
results/
tools/
```

## Result Manifest Support

The framework can create a local result folder for an experiment without building firmware, flashing hardware, opening UART devices, using SSH, or touching network resources.

Command:

```powershell
python scripts/experiment.py manifest --experiment configs/experiments/baseline_direct_uart.yaml
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
