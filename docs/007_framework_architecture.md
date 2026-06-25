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
    artifacts.py
    build.py
    fingerprint.py
    flash.py
    manifest.py
    source.py
tests/
  unit/
    test_artifacts.py
    test_build.py
    test_fingerprint.py
    test_flash.py
    test_config_loading.py
    test_config_validation.py
    test_manifest.py
    test_source.py
  integration/
    test_gateway_flash_helper.py
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

After a successful build and expected-artifact check, the framework calculates the ELF SHA-256 and records it as `firmware.sha256` in `manifest.json` and as `Output ELF SHA-256` in `build.log`. This gives the built firmware artifact a stable identity even though the artifact path stays the same across builds.

The build command also records a deterministic build input fingerprint in `manifest.json` under `build.fingerprint`, `build.fingerprint_inputs`, and `build.fingerprint_algorithm`. The current algorithm is `sha256-build-inputs-v1`. It hashes a sorted list of repository-relative input paths and each file's content SHA-256. The initial input set covers the resolved experiment, board, and host configuration files plus the known firmware build inputs: `CMakeLists.txt`, `CMakePresets.json`, `STM32L4R5XX_FLASH.ld`, `startup_stm32l4r5xx.s`, `Core/`, and `cmake/`.

The fingerprint intentionally excludes generated result folders, generated build outputs, virtual environments, Git internals, documentation-only files, and unrelated generated artifacts. If a required fingerprint input is missing, the build fails before CMake runs and records the fingerprint error in `build.log` and `manifest.json`.

The build command also records source-control provenance in `manifest.json` under `source`. The currently recorded fields are `source.git_commit`, `source.git_dirty`, and `source.git_status_available`. This records which Git commit was present and whether the working tree was dirty when the build command ran. If Git is unavailable or the repository state cannot be read, the command does not fail solely for that reason; it records an explicit unavailable state.

The unit tests cover command construction, deterministic fingerprinting, fingerprint change detection, excluded-file behaviour, missing fingerprint input handling, and build-result handling without invoking CubeMX, CMake, Ninja, STM32 tooling, SSH, UART, or hardware.


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


## Remote Flash Automation Support

The framework can create a result run and remotely flash the existing configured ELF only when the artifact matches a recorded build run:

```powershell
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart
```

The command calculates the local ELF SHA-256 before SCP, records Git source-control provenance at flash time, calculates the current expected build fingerprint, reads the requested build-run manifest, and compares both the flash-time ELF SHA-256 and current build fingerprint against the recorded build metadata. If the build record is missing, incomplete, or mismatched, the command writes `flash.log`, updates `manifest.json`, records a provenance failure status, and refuses to run SCP or SSH.

The flash manifest records:

```text
flash.source_build_run_id
flash.source_build_fingerprint
flash.source_build_firmware_sha256
flash.source_build_artifact_path
flash.current_build_fingerprint
flash.current_build_fingerprint_algorithm
flash.current_build_fingerprint_error
flash.firmware_sha256
flash.provenance_status
flash.provenance_message
flash.untracked_artifact_allowed
```

The supported provenance statuses are:

```text
verified_build_match
untracked_artifact_allowed
mismatch_refused
missing_build_record
```

An explicit escape hatch exists for manual recovery or investigation:

```powershell
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --allow-untracked-artifact
```

When the escape hatch is used, the command records `flash.provenance_status` as `untracked_artifact_allowed`. This is intentionally visible in the manifest and should not be used for normal experiment runs. The SSH step is skipped if SCP fails, and no network command is executed if the local artifact is missing or provenance verification is refused.

Unit tests validate command construction and result handling with an injected runner, so normal unit tests require neither SSH nor hardware. The real gateway flash test in `tests/integration/test_gateway_flash_helper.py` is opt-in through `PQC_RUN_GATEWAY_FLASH_INTEGRATION=1`.


## Combined Build and Flash Support

The framework can build firmware and then remotely flash the resulting artifact in one result run:

```powershell
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml
```

This command creates a single result directory and runs the normal build helper first. If the build succeeds, it runs the normal remote flash helper using the same run ID as the source build record. The same manifest records the build metadata, flash metadata, provenance comparison, and a `build_flash` summary so the build and flash evidence remain tied to the same run ID.

For provenance, `firmware.sha256` records the ELF hash from the successful build step. `flash.firmware_sha256` records the ELF hash immediately before SCP in the flash step. `flash.source_build_run_id`, `flash.source_build_fingerprint`, and `flash.source_build_firmware_sha256` identify the build record used for the flash decision. For a normal successful `build-flash` run, `flash.provenance_status` is `verified_build_match`. The flash helper also refreshes `source` metadata at flash time, so a combined manifest records the Git state that existed when flashing was attempted, not only the state observed during the build step.

If the build fails, the flash step is skipped. This avoids flashing a stale ELF that may already exist in the build folder from a previous experiment. In that case the result directory contains `manifest.json`, `notes.md`, and `build.log`, but no `flash.log`.

A successful combined run creates:

```text
results/<run_id>/
  manifest.json
  notes.md
  build.log
  flash.log
```

Unit tests cover the combined CLI flow with mocked build and flash helpers. They verify that both helpers receive the same result directory and that the flash helper is not called when the build fails. Artifact-hash unit tests use temporary files with known content and expected SHA-256 values. Fingerprint unit tests use temporary files to verify deterministic output, meaningful input-change detection, excluded-file behaviour, and clear missing-input failures. Source-provenance unit tests cover clean, dirty, and unavailable Git states with mocked command runners.
