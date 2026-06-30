# AI Build Guide — PQC IoT Experiment Framework

## 1. Purpose of This File

This file is the compact technical context package for AI-assisted development of this repository.

When starting a new feature request with an AI coding assistant, provide this file first. It explains the current project structure, known-good baseline, development rules, testing expectations, documentation requirements, and safety constraints.

This file must be updated whenever the framework structure, CLI behaviour, configuration model, testing model, documentation structure, or experiment workflow changes.

## 2. Project Purpose

This repository contains an STM32-based embedded security experiment framework.

The long-term goal is to support repeatable experiments involving:

- STM32 firmware builds
- remote flashing through an experiment gateway
- UART log capture
- wolfBoot secure boot experiments
- wolfSSL-based MQTT over TLS
- classical cryptographic baselines
- later PQC and hybrid cryptographic profiles
- network degradation experiments
- benchmark collection
- repeatable result manifests
- documentation and tests

The project is not limited to wolfBoot. wolfBoot and wolfSSL are expected to be important components, but the framework should remain general enough to support boot, transport, network, benchmark, and analysis experiments.

## 3. Current Known-Good Baseline

The current known-good firmware baseline is a CubeMX-generated STM32 HAL application for the NUCLEO-L4R5ZI-P / STM32L4R5 board.

Confirmed behaviour:

- Firmware builds successfully using VS Code, STM32 tooling, CMake, and Ninja.
- Firmware flashes remotely through `pqc-gateway1`.
- ST-LINK SWD flashing works.
- ST-LINK VCP UART logging works.
- The application prints a boot message and repeated `tick` messages.
- LD2 blink/tick loop is working.

Current baseline UART output:

```text
stm32-basic_hal1 boot v0.1.0
tick
tick
tick
```

The current app is a direct-flash baseline. The baseline experiment now references the explicit runnable boot config `configs/boot/direct_flash.yaml`. A planned wolfBoot placeholder exists at `configs/boot/wolfboot_ecdsa_p256.yaml`, but it is marked non-runnable and must not be treated as implemented wolfBoot support. The baseline does not yet use wolfBoot, MQTT, TLS, PQC, or network-degradation automation. Phase 10d defines a planned STM32L4R5 secure-boot flash layout for the non-runnable wolfBoot profile. Phase 10e adds a build-only relocated HAL application profile for the selected `0x08020100` application entry address. Phase 10f adds a configurable wolfBoot build profile and build-evidence capture. Phase 10f.1 adds a project-local STM32L4R5 wolfBoot build adaptation using the local Git submodule at `tools/wolfboot` and the tracked config template `configs/wolfboot/stm32l4r5_ecdsa_p256.config`. The framework copies that template to `tools/wolfboot/.config`, applies temporary MinGW host-keytools stdio and STM32L4 HAL PWR-include compatibility patches when enabled, invokes `make`, and records wolfBoot build evidence. Phase 10g adds a local-only application signing workflow. Phase 10h adds an explicit two-artifact wolfBoot flash workflow and post-flash UART capture using `configs/experiments/wolfboot_ecdsa_p256_uart.yaml` and `python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml`. This records wolfBoot and signed-application flash evidence. Phase 10i adds the distinct secure-boot application UART marker required for positive boot evidence, Phase 10j adds the corrupted-application negative-test workflow, and Phase 10k adds secure-boot timing instrumentation that temporarily patches the local STM32L4R5 wolfBoot build to measure verification time, pass the result to the relocated HAL application through a RAM2 mailbox, and record the application-emitted timing line in the manifest.

## 4. Hardware and Host Context

Target board:

```text
Board: NUCLEO-L4R5ZI-P / NUCLEO-L4R5ZI
MCU: STM32L4R5 / STM32L4Rxxx
Flash: 2 MB
Primary RAM: 192 KB
Additional RAM regions: RAM2 64 KB, RAM3 384 KB
```

Experiment gateway:

```text
Host alias: pqc-gateway1
User: timk
Current local IP: 10.1.1.18
Purpose: remote flashing, UART capture, later MQTT broker and network impairment
OS: Linux pqc-gateway1 6.12.90+deb13.1-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.12.90-2 (2026-05-27) x86_64 GNU/Linux
Host: Dell Laptop with wired NIC connected to 10.1.1.0/24 and currently unused wireless NIC
```

ST-LINK details:

```text
ST-LINK serial: 066EFF3932504E3043111818
UART path: /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
```

Remote flash helper on gateway:

```text
flash-stm32a
```

Remote reset helper on gateway:

```text
reset-stm32a
```

Manual flash command:

```powershell
scp .\build\Debug\stm32_basic_hal1.elf pqc-gateway1:/tmp/stm32_basic_hal1.elf
ssh pqc-gateway1 "flash-stm32a /tmp/stm32_basic_hal1.elf"
```

Manual UART capture command on the gateway:

```bash
picocom -b 115200 /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
```

## 5. Current Repository Layout

The STM32CubeMX-generated firmware project currently lives at the repository root.

Important firmware files and folders:

```text
CMakeLists.txt
CMakePresets.json
cmake/
Core/
Drivers/
STM32L4R5XX_FLASH.ld
startup_stm32l4r5xx.s
stm32_basic_hal1.ioc
.vscode/
.clangd
.mxproject
.settings/
```

Project documentation now exists under:

```text
AI_BUILD_GUIDE.md
docs/
  000_project_overview.md
  001_ai_feature_request_workflow.md
  002_host_gateway_setup.md
  003_stm32_board_setup.md
  004_baseline_hal_app.md
  005_remote_flash_workflow.md
  006_security_and_secrets.md
  007_framework_architecture.md
  008_chatgpt_project_prompt.md
  decisions/
    0001_keep_cubemx_project_at_repo_root.md
```

Current rule:

```text
Do not move the CubeMX-generated folders yet.
```

The STM32 tooling is path-sensitive, and the current firmware project builds correctly in this layout.

Framework folders are being added alongside the CubeMX-generated project:

```text
configs/
scripts/
tests/
results/
tools/
pytest.ini
```

Current initial framework configuration layout:

```text
configs/
  boards/
    board_a.yaml
  hosts/
    gateway.yaml
  boot/
    direct_flash.yaml
    wolfboot_ecdsa_p256.yaml
  builds/
    wolfboot_stm32l4_ecdsa_p256.yaml
  signing/
    wolfboot_ecdsa_p256_app.yaml
  experiments/
    baseline_direct_uart.yaml
    wolfboot_ecdsa_p256_uart.yaml
```

Current initial framework CLI and utilities:

```text
scripts/
  experiment.py
  framework/
    artifacts.py
    build.py
    build_records.py
    build_state.py
    fingerprint.py
    flash.py
    manifest.py
    source.py
    uart.py
    signing.py
    secure_boot_flash.py
```

Current test layout:

```text
tests/
  conftest.py
  unit/
    test_artifacts.py
    test_build.py
    test_build_state.py
    test_fingerprint.py
    test_flash.py
    test_uart.py
    test_config_loading.py
    test_config_validation.py
    test_manifest.py
    test_source.py
  integration/
    test_gateway_flash_helper.py
    test_local_build.py
  hardware/
    test_baseline_uart.py
pytest.ini
```

Supported CLI commands are:

```powershell
python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml --force
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml --capture-uart
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml --build-number 7
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart --capture-uart
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --repeat-count 5
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --negative-corrupt-application
```

The `status` command loads the experiment config, resolves the referenced board, host, and boot configs, validates required fields, and prints a summary.

The `create-run` command loads the experiment config, resolves the referenced board, host, and boot configs, validates required fields, generates a run ID, and creates a local result folder.

The `build` command loads the experiment config, resolves the referenced board, host, and boot configs, validates required fields, generates a run ID, creates a local result folder, records local Git source-control provenance, calculates a deterministic build input fingerprint, runs the local CMake configure and build presets, captures stdout, stderr, return code, build duration, expected output ELF path, calculates the expected ELF SHA-256 after a successful build and artifact-exists check, and writes `results/<run_id>/build.log`.

The `build-wolfboot` command loads a wolfBoot build profile from `configs/builds/`, validates required fields, creates a wolfBoot build evidence directory under `results/wolfboot-builds/`, copies the project-local config template from `configs/wolfboot/stm32l4r5_ecdsa_p256.config` to `tools/wolfboot/.config` when configured, invokes the configured local build command only when the configured wolfBoot source directory exists, captures stdout, stderr, return code, duration, command, expected artifact path, retained artifact path, generated config path, config-application status, temporary MinGW keytools patch status, and artifact SHA-256 when present, and writes `manifest.json` plus `wolfboot_build.log`. It does not generate durable signing keys, sign application images, flash hardware, open UART devices, use SSH, or require physical hardware. If `tools/wolfboot` or the configured source directory is absent, it fails clearly before invoking build tooling. If the configured executable, such as `make`, is unavailable, it records a controlled missing-tool failure rather than raising a Python traceback.

The `status` and `create-run` commands must not build firmware, flash hardware, open UART devices, use SSH, or require physical hardware.

The `build` command may invoke local CMake/STM32 build tooling, but must not flash hardware, open UART devices, use SSH, or touch network resources.

The `flash` command records local Git source-control provenance at flash time, calculates the configured ELF SHA-256 before SCP, calculates the current expected build fingerprint, and refuses to use SCP or SSH unless the artifact matches an explicit build-run manifest or the explicit untracked-artifact escape hatch is used. It requires the configured ELF artifact, gateway access, and physical hardware when provenance verification passes, but it does not capture UART output.

The `build-flash` command creates one result directory, runs the local firmware build, and only then invokes the remote flash helper if the build succeeds. This avoids flashing a stale ELF from a previous build and records both build and flash evidence under the same run ID. It requires the local build toolchain, gateway access, and physical hardware when the build succeeds, but it does not capture UART output.

The `monitor` command is an ad hoc diagnostic command. It captures bounded UART output through the configured gateway ST-LINK VCP path, writes a timestamped log under `results/adhoc/`, and passes when it connects and captures non-empty UART output. It requires gateway access and physical hardware, but it does not create a result manifest, build firmware, or flash firmware.

The `flash --capture-uart` and `build-flash --capture-uart` workflows capture UART immediately after a successful flash, write `uart.log` inside the run directory, and evaluate the configured boot and tick markers as experiment evidence.

The `run` command is the known-good automated baseline. It creates one result directory, assigns a local build number, builds, copies the exact ELF into that directory as `firmware.elf`, flashes only after successful build and copy stages, captures UART, evaluates the configured boot and tick markers, and writes the final manifest verdict.

## 6. Git and Generated-File Rules

The CubeMX project source files should be committed.

The `.ioc` file must be committed. It is the CubeMX source-of-truth for regenerating the STM32 project.

The `.vscode/` files currently contain project-level STM32/CMake settings and may be committed unless they become machine-specific.

Do not commit generated build outputs.

Ignored examples:

```text
build/
CMakeFiles/
CMakeCache.txt
compile_commands.json
*.elf
*.bin
*.hex
*.map
*.list
*.su
mx.scratch/
results/*
!results/.gitkeep
.build_number
.last_successful_build.json
__pycache__/
*.py[cod]
.pytest_cache/
```

Recommended line-ending policy:

```text
Use LF for source, config, Markdown, CMake, Python, shell, and STM32 project text files.
Allow CRLF only for Windows-native scripts if required.
```

Recommended `.gitattributes` policy:

```gitattributes
* text=auto eol=lf

*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf

*.sh text eol=lf
*.py text eol=lf
*.c text eol=lf
*.h text eol=lf
*.s text eol=lf
*.ld text eol=lf
*.cmake text eol=lf
CMakeLists.txt text eol=lf
*.yaml text eol=lf
*.yml text eol=lf
*.json text eol=lf
*.md text eol=lf
*.ioc text eol=lf

*.elf binary
*.bin binary
*.png binary
*.jpg binary
*.jpeg binary
*.pdf binary
*.zip binary
```

## 7. Secret-Handling Rules

Do not commit secrets.

Never commit:

```text
SSH private keys
VPN private keys
TLS private keys
MQTT passwords
.env files containing real credentials
private client certificates or key bundles
private signing keys
private wolfBoot signing keys
production credentials
```

Usually safe to commit if clearly non-secret:

```text
public CA certificates
example configuration files
documentation
public test certificates
dummy credentials used only for examples
```

Public CA certificates may be committed if they are non-secret and needed for TLS validation.

Each development PC should generate its own SSH keypair for gateway access. The private key remains local. Only the public key is installed on `pqc-gateway1`.

Prefer using the local SSH alias:

```text
pqc-gateway1
```

rather than hard-coding private key paths into framework code.

If VPN access is required, document the VPN requirement, but do not commit VPN keys, VPN credentials, or private VPN profiles.

## 8. Development Rules for AI-Assisted Changes

When making changes:

1. Work in small steps.
2. Do not implement future phases early.
3. Preserve the current known-good firmware baseline unless explicitly asked to change it.
4. Do not move CubeMX-generated folders unless explicitly requested.
5. Add or update tests for framework code.
6. Do not require physical hardware for unit tests.
7. Mark hardware-dependent tests separately.
8. Update relevant documentation in the same change.
9. Do not claim hardware success unless user-provided logs confirm it.
10. Prefer simple Python scripts over complex abstractions.
11. Capture command output, errors, and return codes when adding automation.
12. Store experiment outputs under `results/<run_id>/`.
13. Keep generated artifacts out of Git.
14. Keep private keys and credentials out of Git.
15. Update this file when the repository structure or framework behaviour changes.

## 9. Testing Model

Use three test categories.

### Unit Tests

Unit tests live under:

```text
tests/unit/
```

Unit tests must not require:

```text
STM32 hardware
SSH access
MQTT broker access
VPN access
network impairment privileges
```

Examples:

```text
config loading
schema validation
manifest generation
run ID generation
command construction
artifact SHA-256 calculation
build hash calculation
build input fingerprinting
last successful build-hash state handling
rebuild-skip decision handling
path handling
```

Current unit tests cover:

```text
tests/unit/test_config_loading.py
tests/unit/test_config_validation.py
tests/unit/test_manifest.py
tests/unit/test_build.py
tests/unit/test_build_state.py
tests/unit/test_fingerprint.py
tests/unit/test_flash.py
tests/unit/test_source.py
tests/unit/test_uart.py
tests/unit/test_signing.py
tests/unit/test_secure_boot_flash.py
```

These tests validate the initial config loader, config resolution, required-field checks, ID mismatch handling, status-summary no-hardware/no-network behaviour, run ID generation, manifest field generation, result-folder creation, build command construction, and build-result handling.

Build unit tests must not invoke CubeMX, CMake, Ninja, STM32 tooling, SSH, UART, or hardware directly. They must test command construction and result handling through injected or mocked command runners. Artifact SHA-256 unit tests must use temporary files with known content and expected hashes. Build-number unit tests must use temporary `.build_number` files and must not invoke build tools, Git, SSH, UART, or hardware. Last-successful-build state unit tests must use temporary `.last_successful_build.json` files and cover reading, writing, missing state, and invalid state without invoking build tools, Git, SSH, UART, or hardware. Build fingerprint unit tests must use temporary files to verify deterministic output, meaningful input-change detection, excluded-file behaviour, and clear missing-input failures. Source-control provenance unit tests must use injected or mocked Git command runners and must not invoke Git directly.

Flash unit tests must not invoke SCP, SSH, the gateway helper, or hardware directly. They test generated commands, failure handling, logs, source provenance, and manifest updates through injected command runners.

UART unit tests must not invoke SSH, UART devices, the gateway, or hardware directly. They test remote command construction, bounded-capture handling, pass/fail marker detection, logs, manifest updates, and CLI result-folder creation through injected command runners.

### Integration Tests

Integration tests live under:

```text
tests/integration/
```

Integration tests must be separated from unit tests and must skip cleanly when required local toolchains or external capabilities are unavailable.

The current integration tests are:

```text
tests/integration/test_local_build.py
tests/integration/test_gateway_flash_helper.py
```

Capability checks are implemented in:

```text
tests/conftest.py
```

The local build integration test runs the real CMake/STM32 build process through the CLI only when the `local_toolchain` capability is available. That capability checks `cmake --version`, `ninja --version`, and `cmake --list-presets` from the repository root. The test verifies the command return code, generated result directory, `manifest.json`, `build.log`, CMake configure/build command entries, and expected ELF artifact state. It must not flash hardware, open UART devices, use SSH, or touch network resources.

The gateway flash integration test invokes the real build and then the real `flash` CLI command only when the `local_toolchain`, `gateway`, and `flash_helper` capabilities are available. It requires the built ELF, gateway SSH access, the configured flash helper, ST-LINK, and the target board.

Missing integration-test capabilities produce pytest skips by default. Strict mode turns missing expected capabilities into failures:

```powershell
python -m pytest tests/integration -m integration --pqc-require-local-build
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
```

Additional future integration test examples:

```text
gateway SSH reachable
flash helper exists
UART device path exists
MQTT broker reachable
tc/netem available
```

### Hardware Tests

Hardware tests live under:

```text
tests/hardware/
```

The current hardware test is:

```text
tests/hardware/test_baseline_uart.py
tests/hardware/test_secure_boot_flash_workflow.py
```

These may:

```text
flash the board
capture UART output
run MQTT tests
apply network impairment
measure timing
```

Hardware tests must remain marked separately and must skip cleanly when required hardware capabilities are unavailable. The baseline UART monitor hardware test runs only when the `gateway` and `uart_device` capability probes pass:

```powershell
python -m pytest tests/hardware/test_baseline_uart.py -m hardware
```

The secure-boot workflow hardware tests run only when the `local_toolchain`, `gateway`, `flash_helper`, and `uart_device` capability probes pass. They are end-to-end hardware tests and build any missing generated artifacts they need instead of skipping when `tools/wolfboot/wolfboot.elf` or the relocated signed application is absent. The positive test builds the instrumented wolfBoot artifact, builds and signs the relocated application, flashes wolfBoot plus the signed application, captures UART, and verifies the secure-boot marker, normal boot marker, tick marker, and parsed verification timing. The negative test builds the same prerequisites, flashes wolfBoot plus a result-local corrupted signed application, verifies that the application markers are absent, and then flashes the valid signed application again to restore the board to the positive secure-boot state.

```powershell
python -m pytest tests/hardware/test_secure_boot_flash_workflow.py -m hardware
```

Strict hardware mode turns missing expected hardware capabilities into failures:

```powershell
python -m pytest tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware
python -m pytest tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware
```

## 10. Configuration Model

Use small YAML files composed by experiment configs.

Current implemented structure:

```text
configs/
  boards/
    board_a.yaml
  hosts/
    gateway.yaml
  boot/
    direct_flash.yaml
    wolfboot_ecdsa_p256.yaml
  builds/
    wolfboot_stm32l4_ecdsa_p256.yaml
  signing/
    wolfboot_ecdsa_p256_app.yaml
  experiments/
    baseline_direct_uart.yaml
    wolfboot_ecdsa_p256_uart.yaml
```

The experiment config references board, host, and boot configs by ID:

```yaml
board: board_a
host: gateway
boot: direct_flash
```

The CLI resolves these references to:

```text
configs/boards/board_a.yaml
configs/hosts/gateway.yaml
configs/boot/direct_flash.yaml
```

Current required experiment fields:

```text
id
description
board
host
boot
firmware.mode
firmware.artifact
uart.expected_boot_message
uart.expected_tick_message
```

Current required board fields:

```text
id
name
mcu
description
stlink.serial
uart.baud
```

Current required host fields:

```text
id
alias
user
description
flash.helper
uart.device
uart.baud
```

Current required boot fields:

```text
id
mode
description
runnable
```

Planned boot profiles may include additional descriptive metadata, for example:

```text
status
implementation_state
intended_signature_algorithm
application_slot_concept
flash_layout_status
secure_boot_layout
notes
```

Execution-oriented experiment workflows require `runnable: true`. Planned boot configs such as `wolfboot_ecdsa_p256` may be loaded for inspection but must be rejected before build, flash, UART, SSH, or hardware-facing actions.

Current optional host reset field used by `monitor --restart` when present:

```text
reset.helper
```

Planned future structure:

```text
configs/
  boards/
    board_a.yaml
  hosts/
    gateway.yaml
  builds/
    stm32_hal_baseline.yaml
    wolfboot_stm32l4_ecdsa_p256.yaml
  boot/
    direct_flash.yaml
    direct_flash.yaml
    wolfboot_ecdsa_p256.yaml
  transport/
    mqtt_plain.yaml
    mqtt_tls_classic.yaml
    mqtt_tls_pqc.yaml
  network/
    normal.yaml
    latency_50ms.yaml
    lossy_1pct.yaml
  experiments/
    baseline_direct_uart.yaml
    wolfboot_ecdsa_p256_uart.yaml
```

Do not create all of these at once. Add them only as the relevant framework features are implemented.

## 11. Planned Result Model

Every experiment run should eventually create a result directory:

```text
results/<run_id>/
  manifest.json
  build.log
  flash.log
  uart.log
  metrics.json
  notes.md
```

The implemented `create-run` command creates:

```text
results/<run_id>/
  manifest.json
  notes.md
```

The implemented `build` command preserves the compatibility run-result directory and creates a first-class build-record directory on success.

Compatibility run-result directory:

```text
results/<run_id>/
  manifest.json
  build.log
  notes.md
  firmware.elf
  firmware.hex  # when generated by the build
  firmware.bin  # when generated by the build
```

First-class build-record directory:

```text
results/builds/<build_number>/
  manifest.json
  build.log
  firmware.elf
  firmware.hex  # when generated by the build
  firmware.bin  # when generated by the build
```

The compatibility run manifest and build-record manifest include `source` metadata for the Git state observed before the local build helper runs.

The implemented `flash` command creates:

```text
results/<run_id>/
  manifest.json
  flash.log
  notes.md
```

The flash manifest also includes `source` metadata for the Git state observed at flash time and flash provenance metadata linking the flashed artifact to a verified build record.

The implemented `build-flash` command creates the following when both stages pass:

```text
results/<run_id>/
  manifest.json
  build.log
  flash.log
  notes.md
  firmware.elf
  firmware.hex  # when generated by the build
  firmware.bin  # when generated by the build
```

If the build stage fails, `build-flash` skips the flash stage and creates no `flash.log`.

The implemented `run` command creates the following on success when it creates a new build:

```text
results/<run_id>/
  manifest.json
  notes.md
  build.log
  flash.log
  uart.log
  firmware.elf
  firmware.hex  # when generated by the build
  firmware.bin  # when generated by the build
```

When `run --build-number <number>` reuses an existing first-class build record, it creates a run directory with `manifest.json`, `notes.md`, `flash.log`, `uart.log`, and a run-scoped `firmware.elf` copied from `results/builds/<number>/firmware.elf`. It does not create a new `build.log` for that run because no build is performed.

The copied ELF uses the stable result filename `firmware.elf`. The manifest preserves the original configured firmware artifact path and records copied artifact metadata and hashes under `firmware.result_artifacts`. Failed runs contain only the files produced before the failing stage.

The implemented `monitor` command creates ad hoc logs only:

```text
results/adhoc/
  uart_monitor_YYYYMMDD_HHMMSS.log
```

The implemented `flash --capture-uart` and `build-flash --capture-uart` workflows create `uart.log` inside the relevant run directory after a successful flash.

Run IDs use this format:

```text
YYYY-MM-DD_NNN_experiment_id
```

Example:

```text
2026-06-25_001_baseline_direct_uart
```

The manifest should become the source of truth for what was run.

Phase 10b implements build records and experiment run records as separate first-class concepts while preserving the existing `results/<run_id>/` compatibility layout. Successful build-producing workflows create or refresh a dedicated build-record directory under `results/builds/<build_number>/`. Current flash and run workflows may still use compatibility run manifests where required until later phases migrate them to build-number-only references.

A build record describes the firmware build identity. It should contain:

```text
build_number
source/build fingerprint
fingerprint algorithm
fingerprint input list
firmware SHA-256
build.log reference
copied firmware artifacts
build metadata
source-control provenance
```

The build metadata includes configure/build presets, return code, duration, rebuild-skip decision, skip reason/detail, forced-build status, and artifact-copy metadata. Source-control provenance includes Git commit, dirty state, and whether Git status was available.

An experiment run record describes one experiment execution. It should contain:

```text
experiment config identity
referenced build number or build record
flash evidence
UART evidence
pass/fail verdict
notes
```

Phase 10c allows `run` to reference a first-class build record by build number. The run command verifies `results/builds/<build_number>/manifest.json`, verifies the retained `firmware.elf`, verifies the firmware SHA-256, verifies the current source/build fingerprint, refuses unsafe or inconsistent references before flash or UART, copies the verified artifact into the run directory as `firmware.elf`, and records the referenced build number and artifact hash in the run manifest.

Flash evidence includes the flashed firmware hash, provenance status, gateway helper return codes, remote artifact path, ST-LINK serial, flash log reference, and flash-time source-control provenance where applicable. UART evidence includes the UART log reference, device, baud rate, capture return code, marker-detection booleans, data-captured status, reset command, and capture duration.

The implemented build-record directory layout is:

```text
results/builds/<build_number>/
  manifest.json
  build.log
  firmware.elf
  firmware.hex  # when generated by the build
  firmware.bin  # when generated by the build
```

The build number is the primary build-record identifier. The compatibility run manifest links to the build record with `build.record_path` and `build.record_manifest` when a build record exists. Until later phases migrate flash/run provenance to build-number-only references, a `results/<run_id>/manifest.json` may still contain copied build evidence for compatibility.

Build and flash commands record source-control provenance under:

```text
source.git_commit
source.git_dirty
source.git_status_available
```

If Git is unavailable, not installed, or not readable in the repository, normal operation does not fail solely for that reason. The manifest records `source.git_status_available` as `false`, `source.git_commit` as `null`, and `source.git_dirty` as `null`.

Build commands record deterministic build input fingerprint metadata under:

```text
build.fingerprint
build.fingerprint_inputs
build.fingerprint_algorithm
build.skipped
build.skip_reason
build.skip_detail
build.force
build.record_path
build.record_manifest
build.source_state_run_id
build.source_state_build_number
build.source_state_fingerprint
```

After a successful build, build-producing workflows also update generated repository-local last-successful-build state:

```text
.last_successful_build.json
```

This file records the latest successful build fingerprint, fingerprint algorithm and inputs, successful return code, build number, run ID, configured firmware artifact path, firmware SHA-256, and copied result-artifact metadata. It is generated local state and is not intended for Git. Phase 9c uses this state for rebuild-skip decisions. CMake configure/build is skipped only when the current build fingerprint and algorithm match the local last-successful-build state, the expected ELF exists, the prior state records success, and `--force` is not supplied. Missing state, invalid state, changed hash, missing ELF, failed prior-build state, or `--force` cause the normal CMake configure/build path to run. Flash provenance continues to use explicit build-run manifests rather than this local state.

The current fingerprint algorithm is:

```text
sha256-build-inputs-v1
```

The aggregate fingerprint hashes a sorted list of repository-relative input paths and each file's content SHA-256. The build input fingerprint remains unchanged in Phase 10e because the relocated build is verified through an explicit local CMake preset rather than through the experiment build workflow.

The fingerprint intentionally excludes `results/`, `build/`, `.venv/`, `.git/`, documentation-only files, and unrelated generated artifacts.

If a required fingerprint input is missing, the build fails before CMake runs and records the error in `build.log` and `manifest.json`.

Initial implemented manifest fields are:

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

Build-producing workflows add the local build counter at top level:

```text
build_number
```

The `build` command adds build-related manifest fields after the local firmware build completes:

```text
build_number
firmware.artifact
firmware.artifact_path
firmware.artifact_exists
firmware.sha256
firmware.result_artifacts.elf.source_path
firmware.result_artifacts.elf.path
firmware.result_artifacts.elf.artifact_path
firmware.result_artifacts.elf.sha256
firmware.result_artifacts.elf.copied
firmware.result_artifacts.hex.source_path
firmware.result_artifacts.hex.path
firmware.result_artifacts.hex.artifact_path
firmware.result_artifacts.hex.sha256
firmware.result_artifacts.hex.copied
firmware.result_artifacts.hex.missing_reason
firmware.result_artifacts.bin.source_path
firmware.result_artifacts.bin.path
firmware.result_artifacts.bin.artifact_path
firmware.result_artifacts.bin.sha256
firmware.result_artifacts.bin.copied
firmware.result_artifacts.bin.missing_reason
source.git_commit
source.git_dirty
source.git_status_available
build.configure_preset
build.build_preset
build.return_code
build.duration_seconds
build.log
build.fingerprint
build.fingerprint_inputs
build.fingerprint_algorithm
build.skipped
build.skip_reason
build.skip_detail
build.force
build.record_path
build.record_manifest
build.source_state_run_id
build.source_state_build_number
build.source_state_fingerprint
```

The `flash` command adds flash-related manifest fields after remote flashing completes or fails:

```text
flash.return_code
flash.duration_seconds
flash.log
flash.remote_artifact_path
flash.stlink_serial
flash.firmware_sha256
source.git_commit
source.git_dirty
source.git_status_available
flash.scp_return_code
flash.helper_return_code
flash.source_build_run_id
flash.source_build_fingerprint
flash.source_build_firmware_sha256
flash.source_build_artifact_path
flash.current_build_fingerprint
flash.current_build_fingerprint_algorithm
flash.current_build_fingerprint_error
flash.provenance_status
flash.provenance_message
flash.untracked_artifact_allowed
```

Supported flash provenance statuses are:

```text
verified_build_match
untracked_artifact_allowed
mismatch_refused
missing_build_record
```

The `build-flash` command adds combined-stage manifest fields after the combined command completes:

```text
build_flash.return_code
build_flash.build_return_code
build_flash.flash_return_code
build_flash.build_log
build_flash.flash_log
build_flash.flash_skipped
build_flash.failure_stage
build_flash.duration_seconds
```

Post-flash UART capture adds UART manifest fields after capture completes:

```text
uart.return_code
uart.capture_return_code
uart.duration_seconds
uart.capture_duration_seconds
uart.log
uart.device
uart.baud
uart.requested_duration_seconds
uart.expected_boot_message
uart.expected_tick_message
uart.boot_marker_present
uart.tick_present
uart.data_captured
uart.restart_command
uart.restart_during_capture
uart.skipped
uart.verification_time_ms
uart.verification_cycles
uart.verification_cpu_hz
uart.verification_result_code
uart.verification_time_source
uart.verification_time_measurement_method
uart.verification_time_limitations
boot_timing.verification_time_ms
boot_timing.verification_cycles
boot_timing.verification_cpu_hz
boot_timing.verification_result_code
boot_timing.verification_time_source
boot_timing.measurement_method
boot_timing.limitations
```

The `build-flash --capture-uart` command also records combined-stage UART summary fields:

```text
build_flash.uart_return_code
build_flash.uart_log
build_flash.uart_skipped
```

In a combined `build-flash` run, the flash step refreshes `source` metadata at flash time, so the final manifest reflects the Git state when flashing was attempted.

When `run --build-number <number>` reuses an existing first-class build record, the run manifest records build-reference fields such as:

```text
build_number
build_reference.build_number
build_reference.status
build_reference.record_path
build_reference.record_manifest
build_reference.artifact_path
build_reference.artifact_sha256
build_reference.build_fingerprint
build_reference.current_build_fingerprint
run.referenced_build_number
run.referenced_build_artifact_sha256
```

Expected future manifest fields include:

```text
boot_crypto
signature_size
transport_crypto
logs
artifacts
```

Add fields incrementally as features are implemented.

## 12. Current Implementation Phase

Current phase:

```text
STM32 HAL baseline firmware project setup is complete.
AI build guide and documentation skeleton have been added.
Basic framework skeleton is being extended with local build automation.
```

Do not implement wolfBoot, MQTT, TLS, PQC, or network impairment until the basic build, flash, and UART workflow steps are implemented incrementally and covered by tests.

Current framework skeleton completed items:

1. Add `configs/`, `scripts/`, `tests/`, `results/`, and `tools/`.
2. Add initial config files:
   - `configs/boards/board_a.yaml`
   - `configs/hosts/gateway.yaml`
   - `configs/experiments/baseline_direct_uart.yaml`
3. Implement `scripts/experiment.py status`.
4. Add unit tests for config loading and validation.
5. Update framework documentation.
6. Add `scripts/framework/manifest.py`.
7. Add run ID generation.
8. Add result-folder creation under `results/<run_id>/`.
9. Add initial manifest fields and unit tests.
10. Add `scripts/framework/build.py`.
11. Add `scripts/experiment.py build`.
12. Add build command construction and build-result unit tests.
13. Add opt-in local build integration test in `tests/integration/test_local_build.py`.
14. Add `pytest.ini` with the `integration` marker.
15. Add `scripts/framework/flash.py`.
16. Add `scripts/experiment.py flash`.
17. Add remote flash command-construction and result-handling unit tests.
18. Add the opt-in gateway flash integration test.
19. Add `scripts/experiment.py build-flash` to build and flash in one result run.
20. Add unit tests for the combined build-flash flow.
21. Add artifact SHA-256 provenance for build and flash manifests/logs.
22. Add Git source-control provenance for build and flash manifests.
23. Add deterministic build input fingerprinting for build and build-flash manifests.
24. Link flash runs to verified build records by requiring `flash --build-run <run_id>` or the explicit `--allow-untracked-artifact` escape hatch.
25. Complete Phase 9a source hash coverage for the full required firmware/build input set without adding rebuild skipping.
26. Add `scripts/experiment.py monitor` for ad hoc bounded UART monitoring through the configured gateway.
27. Add pass/fail detection for ad hoc monitor connectivity and non-empty UART data capture.
28. Add optional post-flash UART capture to `flash --capture-uart` and `build-flash --capture-uart`.
29. Add post-flash pass/fail detection for the expected baseline boot marker and `tick` marker.
30. Add the opt-in baseline UART hardware test.
31. Add `scripts/experiment.py run` as the known-good automated baseline.
32. Retain the exact built ELF inside each successful baseline run directory.
33. Add mocked orchestration tests for full-run success and stage failures.
34. Track build numbers using local `.build_number` state.
35. Copy successful build artifacts into result directories using canonical artifact filenames.
36. Add generated `.last_successful_build.json` state for the latest successful build hash and artifact identity without enabling rebuild skipping.
37. Add safe rebuild skipping for build-producing workflows without restructuring result directories.
38. Define first-class build records and experiment run records at the model and documentation level without migrating the current result layout.
39. Create first-class build result directories under `results/builds/<build_number>/` while preserving compatibility run-result directories.
40. Allow `run --build-number <number>` to reuse an existing first-class build record after validating the record, retained artifact, artifact hash, and current source/build fingerprint.
41. Add Phase 10a direct-flash boot config resolution through `configs/boot/direct_flash.yaml` without changing runtime behaviour or adding wolfBoot.
42. Add Phase 10b planned wolfBoot boot config placeholder at `configs/boot/wolfboot_ecdsa_p256.yaml`; it is loadable for inspection but marked `runnable: false` and rejected by execution-oriented workflows.
43. Add Phase 10c wolfBoot STM32L4 target support assessment in `docs/decisions/0002_wolfboot_stm32l4_target_support_assessment.md`; upstream STM32L4 support is the closest starting point, but STM32L4R5 requires a project-local target configuration or adaptation before wolfBoot is built or treated as runnable.
44. Add Phase 10d secure-boot flash layout decision in `docs/decisions/0003_secure_boot_flash_layout.md`; `configs/boot/wolfboot_ecdsa_p256.yaml` now records the planned STM32L4R5 layout metadata while remaining non-runnable.
45. Add Phase 10e relocated HAL application build profile using `RelocatedDebug`, `STM32L4R5XX_FLASH_RELOCATED.ld`, and vector offset `0x00020100` while preserving the direct-flash `Debug` baseline.
46. Add Phase 10f configurable wolfBoot build profile support with `configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml`, `scripts/framework/wolfboot_build.py`, and `python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml`. This captures wolfBoot build evidence only and does not sign images, flash hardware, capture UART, or claim secure-boot runtime success.
47. Add Phase 10f.1 project-local STM32L4R5 wolfBoot build adaptation using the local Git submodule at `tools/wolfboot`, the tracked config template `configs/wolfboot/stm32l4r5_ecdsa_p256.config`, generated local copy `tools/wolfboot/.config`, `STM32CUBE=../..`, Phase 10d partition values, target-only Cortex-M4/thumb/HAL/CMSIS compile settings, and STM32L4R5 MCU macro selection that undefines upstream `STM32L4A6xx` before defining `STM32L4R5xx`, decimal `IMAGE_HEADER_SIZE=256`, and a temporary MinGW host-keytools stdio compatibility patch and temporary STM32L4 HAL config PWR/PWREx include patch. The command can retain `wolfboot.elf` and record SHA-256 when the submodule and required toolchain are available.
49. Add Phase 10g local-only ECDSA-P256 application signing workflow with `configs/signing/wolfboot_ecdsa_p256_app.yaml`, `scripts/framework/signing.py`, and `python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml`. This can generate or use a local private signing key under `secrets/wolfboot/`, converts the relocated ELF to a BIN when needed, signs the relocated application BIN, records signing evidence under `results/signing/`, and does not copy private keys into results, flash hardware, capture UART, or claim secure-boot runtime success.
50. Add Phase 10h explicit wolfBoot secure-boot flash workflow with `configs/experiments/wolfboot_ecdsa_p256_uart.yaml`, `scripts/framework/secure_boot_flash.py`, and `python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml`. This flashes the configured `wolfboot.elf` and signed application image in sequence, records both artifact hashes, offsets, remote paths, return codes, and logs, and captures UART by default after successful flashing.
51. Add Phase 10i positive wolfBoot boot evidence by compiling a distinct relocated secure-boot application UART marker, requiring it in the wolfBoot UART experiment, and recording `secure_boot_run.boot_path_distinguished`, `secure_boot_run.secure_boot_marker_present`, and signature metadata in the manifest.
52. Add Phase 10j corrupted-application negative-test support with `python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --negative-corrupt-application`. This creates a result-local corrupted copy of the signed application image, flashes that copy, captures UART, and passes only when the normal boot, tick, and secure-boot markers are absent. It does not modify the original signed image or private signing key. The hardware workflow test also covers this negative path and restores the valid signed image afterward.
53. Add Phase 10k boot timing instrumentation. The wolfBoot build helper temporarily instruments local STM32L4R5 wolfBoot `src/image.c` during `build-wolfboot`, wraps `wolfBoot_verify_authenticity()` with a Cortex-M DWT cycle-counter measurement, writes the measured millisecond value into a RAM2 mailbox before jumping to the application, restores the submodule files after the build, and records the application-emitted `wolfBoot verification time: <N> ms` UART evidence in the secure-boot run manifest. Host-side SSH, reset, and UART capture duration are not treated as verification time.
54. Add Phase 10l secure-boot manifest and documentation consolidation. Secure-boot run manifests now record the required consolidated fields `boot_mode`, `boot_crypto`, `signature_size`, `boot_signature.signature_size`, `boot_signature.signature_size_bytes`, and `boot_timing.verification_time_ms`. They also record `secure_boot_evidence` to link wolfBoot build-artifact evidence, signed-application evidence, flash evidence, UART marker evidence, timing evidence, final result, and negative-test evidence in one object. The signing manifest also records `signing.signature_size` alongside `signing.signature_size_bytes`.
55. Add Phase 11.1 secure-boot benchmark result model. Secure-boot run manifests now record `secure_boot_benchmark` as a schema-first evidence object that distinguishes build-time metrics, signed-artifact metrics, runtime verification metrics, runtime memory metrics, repeated-run samples, aggregate statistics, and limitations. Existing secure-boot timing fields remain compatible. Metrics not implemented until later Phase 11 steps are recorded explicitly as unavailable rather than omitted. Phase 11.1 does not add new signing profiles, repeated-run execution, aggregation commands, or runtime stack/heap instrumentation.
56. Add Phase 11.2 repeated-run measurement support. The secure-boot flash workflow supports `--repeat-count <N>` for repeated post-flash reset/UART verification samples of the same profile. Each sample records run index, timestamp, explicit timing/cycle/CPU/result-code evidence, UART marker verdict, pass/fail sample verdict, and referenced wolfBoot/signed-application artifact identity. Aggregates record sample count, valid sample count, failed sample count, minimum, mean, median, maximum, standard deviation, range, and coefficient of variation for verification time and cycles. Median values are the primary headline metrics. The CLI summary prints the aggregate counts and timing/cycle statistics at the end of the repeated-run workflow. Phase 11.2 does not add new signing profiles, static build/resource metrics, runtime stack/heap instrumentation, or cross-profile aggregation output.
Current CLI commands are:

```powershell
python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml --force
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --allow-untracked-artifact
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml --capture-uart
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml --build-number 7
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart --capture-uart
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
```

Expected `status` behaviour:

- loads the experiment config
- resolves board and host config files
- validates required fields
- prints a summary
- does not build anything
- does not flash anything
- does not require hardware

Expected `create-run` behaviour:

- loads the experiment config
- resolves board and host config files
- validates required fields
- generates a run ID
- creates `results/<run_id>/manifest.json`
- creates `results/<run_id>/notes.md`
- does not build anything
- does not flash anything
- does not require hardware

Expected `build` behaviour:

- loads the experiment config
- resolves board and host config files
- validates required fields
- generates a run ID
- creates `results/<run_id>/manifest.json`
- creates `results/<run_id>/notes.md`
- creates or refreshes `results/builds/<build_number>/manifest.json` after a successful build or skipped build with a known build number
- runs `cmake --preset Debug` by default
- runs `cmake --build --preset Debug` by default if configure succeeds
- captures stdout, stderr, return codes, duration, expected output ELF path, build log path, build number, build input fingerprint metadata, firmware SHA-256 after a successful build, copied result-artifact metadata, last-successful-build local state, and Git source-control provenance
- writes `results/<run_id>/build.log`
- copies the built ELF into the compatibility result directory as `firmware.elf` after a successful build
- copies the built ELF and build log into the first-class build-record directory after a successful build
- copies `firmware.hex` and `firmware.bin` when matching build outputs exist, and records them as absent optional artifacts when they do not
- updates `results/<run_id>/manifest.json` with `build_number`, build metadata, `build.fingerprint`, `build.fingerprint_inputs`, `build.fingerprint_algorithm`, `build.record_path`, `build.record_manifest`, `firmware.sha256`, `firmware.result_artifacts`, and `source` metadata
- writes `results/builds/<build_number>/manifest.json` with build metadata, artifact metadata, source-control provenance, and compatibility back-references
- updates `.last_successful_build.json` only after a successful non-skipped build with a valid artifact
- skips CMake configure/build only when the current source/build hash equals the local last-successful-build hash, the expected ELF exists, the previous state records success, and `--force` is not supplied
- preserves normal CMake configure/build behaviour when the hash changed, the ELF is missing, local state is missing or invalid, previous state records failure, or `--force` is supplied
- records the rebuild decision in both `build.log` and `manifest.json`
- does not flash anything
- does not open UART devices
- does not use SSH
- does not require physical hardware beyond the local build toolchain

Expected `flash` behaviour:

- loads and validates the experiment bundle
- creates a new result directory
- verifies the configured ELF exists
- records Git source-control provenance at flash time
- calculates the configured ELF SHA-256 before SCP
- calculates the current expected build fingerprint
- requires `--build-run <run_id>` unless `--allow-untracked-artifact` is explicitly used
- reads `results/<build-run>/manifest.json` when `--build-run` is provided
- compares the flash-time ELF SHA-256 against `firmware.sha256` from the build-run manifest
- compares the current expected build fingerprint against `build.fingerprint` from the build-run manifest
- records `flash.source_build_run_id`, `flash.source_build_fingerprint`, `flash.source_build_firmware_sha256`, `flash.firmware_sha256`, and `flash.provenance_status` in the manifest
- refuses to run SCP or SSH if no matching build record exists
- records `flash.provenance_status` as `untracked_artifact_allowed` when the explicit escape hatch is used
- copies the ELF to `/tmp/<artifact-name>` on the configured gateway only after provenance is verified or explicitly bypassed
- invokes the configured flash helper over SSH only after SCP succeeds
- writes `flash.log`
- records final and per-step return codes, remote artifact path, duration, ST-LINK serial, `source`, and `flash.firmware_sha256` in the manifest
- skips SSH if SCP fails
- captures UART output only when `--capture-uart` is explicitly supplied


Expected `monitor` behaviour:

- loads and validates the experiment bundle
- creates `results/adhoc/` if needed
- captures UART output through the configured gateway using SSH
- uses the configured ST-LINK VCP path `/dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02`
- captures for a bounded duration of 10 seconds by default
- writes a timestamped ad hoc log such as `results/adhoc/uart_monitor_YYYYMMDD_HHMMSS.log`
- optionally triggers a gateway reset helper during the capture window when `--restart` is supplied
- opens UART capture before reset so startup-only messages can be observed
- uses configured `host.reset.helper` as the default restart command when available, currently `reset-stm32a`, overridable with `--restart-command`
- passes when the capture command completes normally or through GNU `timeout` return code 124 and captured stdout is non-empty
- fails when the optional restart command fails, the SSH/UART command fails, or no UART data is captured
- does not create a run manifest
- does not build firmware
- does not flash firmware

Expected post-flash UART capture behaviour:

- is enabled explicitly with `--capture-uart` on `flash` or `build-flash`
- runs only after a successful flash step
- starts UART capture first and then triggers the configured gateway reset helper after a short delay
- writes `uart.log` inside the existing result run directory
- uses `--uart-duration-seconds` to control the bounded capture duration
- records UART device, baud rate, requested duration, command return code, marker detection booleans, data-captured status, and final return code in `manifest.json`
- sets the relevant run result to passed only when the expected boot marker and expected `tick` marker are both present
- sets the relevant run result to failed when the command fails or either marker is missing
- treats GNU `timeout` return code 124 as a completed bounded capture when evaluating UART marker pass/fail status
- records UART as skipped if the flash step fails

Expected `run` behaviour:

- loads and validates the experiment bundle
- creates one new result directory
- without `--build-number`, runs the same local build workflow used by `build`
- stops immediately if the build fails
- without `--build-number`, copies the exact built ELF into the result directory using its original filename
- with `--build-number <number>`, verifies `results/builds/<number>/manifest.json`, the retained `firmware.elf`, the retained firmware SHA-256, and the current source/build fingerprint before use
- with `--build-number <number>`, refuses missing, malformed, incomplete, mismatched, or unsafe build references before flash or UART capture
- with `--build-number <number>`, copies the verified build-record artifact into the new result directory as `firmware.elf` without invoking CMake or creating a new build record
- stops immediately if artifact copying fails
- flashes using the current run ID or verified build record as the source build record
- stops and records UART as skipped if flashing fails
- always captures UART after a successful flash
- starts UART capture before invoking the configured reset helper
- passes only when the configured boot marker and tick marker are both present
- writes `manifest.json`, `notes.md`, `build.log`, `flash.log`, `uart.log`, `firmware.elf`, and optional `firmware.hex` / `firmware.bin` on success
- records stage return codes and the failure stage under `run`
- records the retained ELF under `firmware.result_artifact` and `firmware.result_artifact_path`
- records copied artifact metadata under `firmware.result_artifacts` when a build is performed
- records `build_reference` plus `run.referenced_build_number` and `run.referenced_build_artifact_sha256` when an existing build is reused
- sets the final manifest result to `baseline_run_passed` or `baseline_run_failed`
- returns non-zero when build, artifact copy, flash, or UART evaluation fails

Expected `build-flash` behaviour:

- loads and validates the experiment bundle
- creates one new result directory
- runs the same local build workflow used by `build`
- writes `build.log` in the same result directory
- records the build input fingerprint under `build.fingerprint`, `build.fingerprint_inputs`, and `build.fingerprint_algorithm`
- records the built ELF hash as `firmware.sha256`
- skips flash entirely if the build fails
- if the build succeeds, uses the same remote flash workflow used by `flash` with the current run ID as the source build record
- records the pre-SCP ELF hash as `flash.firmware_sha256`
- records `flash.provenance_status` as `verified_build_match` for a normal successful build-to-flash provenance check
- records Git source-control provenance again at flash time
- writes `flash.log` in the same result directory when flash is attempted
- records build number, build metadata, copied artifact metadata, flash metadata, and combined `build_flash` metadata in one manifest
- returns the build return code when build fails
- returns the flash return code when build succeeds and flash is attempted
- captures UART output only when `--capture-uart` is explicitly supplied


Expected `build-wolfboot` behaviour:

- loads and validates a wolfBoot build profile from `configs/builds/`
- validates required profile fields including `source_dir`, `output_dir`, `artifact`, `target`, `signature_algorithm`, `boot_profile`, and `build.command`
- currently requires `signature_algorithm: ecdsa_p256`
- creates `results/wolfboot-builds/<timestamp>_<profile_id>/`
- writes `manifest.json` and `wolfboot_build.log`
- constructs the configured command from scalar `build.command` and optional scalar `build.args` without using a shell
- fails before invoking build tooling when the configured source directory is absent
- records a controlled missing-tool failure when the configured executable cannot be started
- copies the configured project-local build config template to the generated wolfBoot `.config` path when `build.config_template` and `build.generated_config` are set
- invokes the configured local wolfBoot build command only when the source directory exists and the configured project-local build config is available
- captures stdout, stderr, return code, duration, working directory, expected artifact path, artifact existence, project-local config paths, config-application status, artifact SHA-256 when present, and retained artifact path when copied
- copies the produced artifact into the wolfBoot build evidence directory as `wolfboot.elf` when the command succeeds and the configured artifact exists
- returns non-zero when profile validation fails, the source directory is missing, the command fails, or the command succeeds but the configured artifact is absent
- does not generate signing keys
- does not sign application images
- does not flash hardware
- does not open UART devices
- does not use SSH
- does not require physical hardware
- does not mark `configs/boot/wolfboot_ecdsa_p256.yaml` as runnable

Immediate next intended steps after this change:

1. Run the Phase 10f wolfBoot build-profile unit tests.
2. Run `python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml` only when the configured local wolfBoot source/tooling is intentionally available.
3. Treat a controlled `stm32l4xx_hal.h` / HAL-CMSIS integration failure from upstream `TARGET=stm32l4` as expected until the project-local STM32L4R5 wolfBoot target adaptation phase is implemented.
4. Run the Phase 10e relocated local build verification command when the local STM32/CMake/Ninja toolchain is available.
5. Run the unit tests.
6. Run `python -m pytest` and confirm unavailable integration or hardware capabilities produce clear skips rather than environment-variable setup errors.
7. Run the strict local-build integration check only when the local STM32/CMake/Ninja toolchain is expected to be available.
8. Run the strict gateway flash integration check only when the gateway and board are expected to be available.
9. Run the strict baseline UART hardware check only when the gateway and board are expected to be available.
10. Review user-provided logs before claiming hardware success.
11. Commit after verification passes.

## Phase 10h Flash wolfBoot and Signed Application

Implemented scope:

- Added `configs/experiments/wolfboot_ecdsa_p256_uart.yaml` as the explicit Phase 10h wolfBoot flash experiment profile.
- Added `scripts/framework/secure_boot_flash.py` for the two-artifact flash workflow. Unit tests use injected command runners and do not require SSH, UART, gateway access, or STM32 hardware.
- Added `python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml`.
- Added `tests/hardware/test_secure_boot_flash_workflow.py` as a capability-gated hardware workflow test that runs the instrumented wolfBoot build, relocated application build, application signing, two-artifact secure-boot flash, and UART marker check when the required local toolchain, gateway, flash helper, and UART device are available. The test is end-to-end and does not skip solely because generated wolfBoot or signed-application artifacts are absent.
- The command stages and flashes the configured wolfBoot bootloader artifact first, then stages and flashes the configured signed application image.
- The command records the wolfBoot artifact path, signed application artifact path, SHA-256 values, configured flash offsets, remote staging paths, SCP return codes, helper return codes, ST-LINK serial, Git source provenance, and a `secure_boot_flash.log` file in the run result directory.
- The command captures UART by default after successful two-artifact flashing and records UART marker evaluation in `uart.log` and `manifest.json`.
- The command includes `--skip-uart` only as a diagnostic escape hatch. When used, no boot confirmation is made.
- `configs/boot/wolfboot_ecdsa_p256.yaml` remains `runnable: false` for generic direct-flash workflows. The Phase 10h command loads it explicitly for the secure-boot flash workflow so the known-good direct-flash path cannot accidentally treat wolfBoot as a generic validated runtime path.
- The command records `secure_boot_run.boot_confirmed_from_uart_log` from UART marker evaluation. Phase 10i updates this evidence so a positive run requires the distinct secure-boot application marker and records `secure_boot_run.boot_path_distinguished: true` only when that marker is present.

Implemented after Phase 10h:

- Phase 10i adds the distinct secure-boot application UART marker and positive boot-evidence manifest fields.
- Phase 10j adds the corrupted-application negative-test workflow.
- Phase 10l consolidates secure-boot manifest evidence and documentation after Phase 10k timing instrumentation.

Still not implemented:

- production signing-key handling

Manual Phase 10h command:

```powershell
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
```

Phase 10h hardware workflow test:

```powershell
python -m pytest tests/hardware/test_secure_boot_flash_workflow.py -m hardware
python -m pytest tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware
```

Expected result: when `tools/wolfboot/wolfboot.elf`, `build/RelocatedDebug/stm32_basic_hal1_v1_signed.bin`, the gateway, flash helper, ST-LINK, and board are intentionally available, the command creates a normal result run directory containing `manifest.json`, `secure_boot_flash.log`, `uart.log`, and `notes.md`. Hardware success must still only be claimed from user-provided logs. A successful Phase 10h run does not by itself prove wolfBoot-mediated boot-path identity.


## Phase 10i wolfBoot Positive Boot Evidence

Implemented scope:

- The relocated application build defines `SECURE_BOOT_APPLICATION` when `STM32_APP_VECTOR_OFFSET` is not `0x00000000`.
- The secure-boot application prints the additional UART marker `stm32-basic_hal1 secure-boot app v0.1.0` before the normal `stm32-basic_hal1 boot v0.1.0` marker.
- `configs/experiments/wolfboot_ecdsa_p256_uart.yaml` records `uart.expected_secure_boot_message` so positive secure-boot evidence requires the secure-boot marker, normal boot marker, and `tick` marker.
- UART capture records `uart.expected_secure_boot_message` and `uart.secure_boot_marker_present` in `manifest.json` and `uart.log`.
- The secure-boot command records `boot_crypto`, `boot_signature`, `secure_boot_run.boot_path_distinguished`, `secure_boot_run.secure_boot_marker_present`, and `secure_boot_run.positive_boot_evidence_passed`.
- A positive run result is recorded as `secure_boot_positive_boot_evidence_passed` only when flash succeeds and all required UART markers are present.

Manual Phase 10i command:

```powershell
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
```

Expected result: when the wolfBoot artifact, signed relocated application, gateway, flash helper, ST-LINK, and board are intentionally available, the run manifest records positive secure-boot evidence only if the UART log contains the secure-boot marker, normal boot marker, and tick marker. Hardware success must still only be claimed from user-provided logs.

## Phase 10j Negative Boot Test for Corrupted Application

Implemented scope:

- `flash-secure-boot` supports `--negative-corrupt-application`.
- The workflow copies the signed application image into the result directory, flips the first byte of that result-local copy, and flashes the corrupted copy instead of the original signed image.
- The original signed application under `build/` and the private signing key under `secrets/wolfboot/` are not modified or copied into result artifacts.
- The manifest records the original signed-image path and SHA-256, corrupted image path and SHA-256, corruption method, and `source_image_modified: false`.
- The negative test captures UART and passes only when capture completes and the normal boot marker, tick marker, and secure-boot marker are absent.
- `tests/hardware/test_secure_boot_flash_workflow.py` includes the negative hardware workflow and restores the valid signed application after the corrupted-image test.

Manual Phase 10j command:

```powershell
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --negative-corrupt-application
```

Expected result: the corrupted application does not produce the normal application boot marker, tick marker, or secure-boot marker, and the manifest records `secure_boot_negative_test.verdict: passed`. When using the hardware test, the board is restored by a final positive secure-boot flash. Hardware success must still only be claimed from user-provided logs.


## Phase 10k Boot Timing Instrumentation

Implemented scope:

- The wolfBoot build profile enables a temporary Phase 10k instrumentation patch during `build-wolfboot`.
- The build helper temporarily patches local wolfBoot `src/image.c` to wrap `wolfBoot_verify_authenticity()` with a Cortex-M DWT cycle-counter measurement and write the measured millisecond value, elapsed cycle count, configured CPU frequency, and verification return code into a RAM2 mailbox at `0x10000000`.
- The relocated HAL application reads the RAM2 mailbox after UART initialization and emits parser-compatible lines such as `wolfBoot verification time: <N> ms`, `wolfBoot verification cycles: <N> cycles`, `wolfBoot verification cpu_hz: <N>`, and `wolfBoot verification result: <N>` over the known-good application UART path.
- The tracked project-local wolfBoot config defines `WOLFBOOT_PQC_BOOT_TIMING`, `WOLFBOOT_PQC_BOOT_TIMING_CPU_HZ=80000000UL`, and `WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR=0x10000000UL` for the instrumented build.
- Post-flash UART capture parses explicit verification-time UART evidence, for example `wolfBoot verification time: 17 ms`, `verification_time_ms=17`, `wolfBoot verification cycles: 1360000 cycles`, `verification_cycles=1360000`, `wolfBoot verification cpu_hz: 80000000`, and `verification_result_code=0`.
- The run manifest records `boot_timing.verification_time_ms`, `boot_timing.verification_cycles`, `boot_timing.verification_cpu_hz`, `boot_timing.verification_result_code`, `boot_timing.verification_time_source`, `boot_timing.measurement_method`, and `boot_timing.limitations`.
- The secure-boot run summary mirrors the same timing evidence under `secure_boot_run.verification_time_ms`, `secure_boot_run.verification_cycles`, `secure_boot_run.verification_cpu_hz`, `secure_boot_run.verification_result_code`, and related source/method/limitation fields.
- When no explicit UART timing marker is present, the framework records `verification_time_ms: null`, `verification_cycles: null` when no cycle marker is present, `verification_time_source: unavailable`, and a limitation explaining that timing was not estimated.
- Host-side SSH command duration, UART capture duration, reset delay, and marker ordering are not used as wolfBoot verification time.
- `configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml` records that boot timing instrumentation is enabled for the local wolfBoot build.
- `configs/experiments/wolfboot_ecdsa_p256_uart.yaml` documents the expected timing source and unavailable-timing behaviour.
- Unit tests cover timing parsing, manifest fields, unavailable timing evidence, and temporary wolfBoot source patch/restore behaviour without requiring SSH, UART, gateway access, or STM32 hardware.

Manual Phase 10k commands:

```powershell
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
cmake --preset RelocatedDebug
cmake --build --preset RelocatedDebug
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
```

Expected result: the wolfBoot build evidence records that the boot timing instrumentation patch was enabled and applied, the submodule files are restored after the build, the relocated application emits `wolfBoot verification time: <N> ms`, `wolfBoot verification cycles: <N> cycles`, `wolfBoot verification cpu_hz: <N>`, and `wolfBoot verification result: <N>` from the RAM2 mailbox after boot, and the run manifest records the parsed millisecond, cycle-count, CPU-Hz, and verification-result values. If the captured UART log does not contain such lines, the manifest records unavailable/null timing with the unavailable source and documented limitations. Hardware success and timing evidence must still only be claimed from user-provided logs.


## Phase 10l Secure-Boot Manifest and Documentation Consolidation

Implemented scope:

- Secure-boot run manifests record the required Phase 10l fields `boot_mode`, `boot_crypto`, `signature_size`, and `boot_timing.verification_time_ms`.
- `boot_signature` now records both `signature_size` and `signature_size_bytes` for the configured signature byte count while preserving `algorithm` and `image_version`.
- `secure_boot_evidence` links the run's wolfBoot artifact evidence, signed-application evidence, flash evidence, UART marker evidence, boot-timing evidence, result status, and negative-test verdict in one consolidated object.
- The application-signing manifest records `signing.signature_size` alongside `signing.signature_size_bytes` so signing evidence and secure-boot run evidence use a consistent field name.
- Documentation has been consolidated in `README.md`, `docs/007_framework_architecture.md`, `docs/006_security_and_secrets.md`, and this build guide.
- `.gitignore` continues to exclude generated outputs, result directories, local signing keys, signed images, wolfBoot generated artifacts, and `tools/wolfboot/.config`.
- The direct-flash baseline remains available and `configs/boot/wolfboot_ecdsa_p256.yaml` remains non-runnable for generic direct-flash workflows.

Manual Phase 10l verification commands:

```powershell
python -m pytest tests/unit
python -m pytest
python -m pytest tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware
```

Expected result: unit tests pass without hardware. Integration and hardware tests skip cleanly unless strict capability flags are supplied. When hardware is intentionally available, the secure-boot workflow manifest contains coherent `secure_boot_evidence`, `signature_size`, `boot_crypto`, `boot_mode`, and `boot_timing.verification_time_ms` evidence. Hardware success and timing values must still only be claimed from user-provided logs.


## Phase 11.1 Secure-Boot Benchmark Result Model

Implemented scope:

- Secure-boot run manifests now include `secure_boot_benchmark` alongside the existing Phase 10l `secure_boot_evidence` object.
- The benchmark schema records `schema_version: 1`, `model_phase: phase_11_1_schema_only`, benchmark scope, profile identity, boot mode, boot crypto, signature algorithm, signature size, and image version.
- The schema separates `build_time_metrics`, `signed_artifact_metrics`, `runtime_verification_metrics`, `runtime_memory_metrics`, `repeated_run_samples`, `aggregate_statistics`, and top-level limitations.
- Existing secure-boot timing fields remain compatible under `boot_timing`, `secure_boot_run`, and `secure_boot_evidence.boot_timing`. Available timing evidence is mirrored into `secure_boot_benchmark.runtime_verification_metrics`.
- Signed-artifact evidence records available artifact identity and file-size evidence, including wolfBoot ELF and signed-application size when those artifacts exist.
- Static build/resource metrics, unsigned-image overhead metrics, runtime stack/heap metrics, repeated-run samples, and aggregate statistics are explicitly recorded as unavailable placeholders with reasons until later Phase 11 sub-steps implement their collection or calculation.
- Phase 11.1 does not add new signing-algorithm profiles, benchmark aggregation commands, repeated-run execution behaviour, or runtime stack/heap instrumentation.
- Unit tests cover schema creation and secure-boot manifest population without requiring SSH, UART, gateway access, STM32 hardware, or real wolfBoot tooling.

Manual Phase 11.1 verification commands:

```powershell
python -m pytest tests/unit/test_manifest.py tests/unit/test_secure_boot_flash.py
python -m pytest tests/unit
python -m pytest
```

Expected result: unit tests pass without hardware. Integration and hardware tests skip cleanly unless strict capability flags are supplied. Secure-boot manifests contain `secure_boot_benchmark` with explicit unavailable placeholders for later Phase 11 metrics. Hardware success and timing values must still only be claimed from user-provided logs.


## Phase 11.2 Repeated-Run Measurement Support

Implemented scope:

- `flash-secure-boot` supports `--repeat-count <N>` for repeated secure-boot verification samples of the same configured profile.
- The workflow flashes wolfBoot and the signed application once, then performs one reset/UART capture per sample.
- Single-sample runs preserve `uart.log`; repeated runs write `uart_sample_001.log`, `uart_sample_002.log`, and so on.
- Each sample is recorded under `secure_boot_benchmark.repeated_run_samples.samples` with run index, timestamp, verification time in milliseconds, verification cycles, verification CPU frequency, verification result code, timing source, cycle source, UART marker detection result, sample verdict, validity-for-statistics flag, and referenced artifact identity.
- `secure_boot_benchmark.aggregate_statistics` records sample count, valid sample count, failed sample count, minimum, mean, median, maximum, standard deviation, range, and coefficient of variation for verification time and verification cycles.
- Primary headline metrics use the median and are recorded under `secure_boot_benchmark.aggregate_statistics.headline_metrics` and mirrored into `secure_boot_run.primary_verification_time_ms` and `secure_boot_run.primary_verification_cycles`.
- Failed samples and samples missing explicit timing or cycle evidence remain visible in the manifest but are excluded from valid timing/cycle statistics.
- Host-side SSH duration, UART capture duration, reset delay, and marker ordering are not used as verification timing evidence.
- Phase 11.2 does not add new classical signing-algorithm profiles, static build/resource metrics, runtime stack/heap instrumentation, or benchmark aggregation output files.

Manual Phase 11.2 command:

```powershell
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --repeat-count 5
```

Manual Phase 11.2 verification commands:

```powershell
python -m pytest tests/unit/test_manifest.py tests/unit/test_secure_boot_flash.py
python -m pytest tests/unit
python -m pytest
```

Expected result: unit tests pass without hardware. Integration and hardware tests skip cleanly unless strict capability flags are supplied. When hardware is intentionally available, repeated secure-boot runs record one sample per reset/UART capture and aggregate only valid explicit timing/cycle samples. Hardware success and timing values must still only be claimed from user-provided logs.

## 13. Common Manual Commands

Delete stale CMake build cache:

```powershell
Remove-Item -Recurse -Force .\build
```

Run the initial framework CLI status command:

```powershell
python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
```

Create an initial result run folder:

```powershell
python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
```

Run a local firmware build and capture a build log:

```powershell
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
```

Force CMake configure/build even when rebuild skipping would be allowed:

```powershell
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml --force
```

Run framework unit tests:

```powershell
python -m pytest tests/unit
```

Run all tests that can run on the current machine. Integration and hardware tests auto-skip when required capabilities are unavailable:

```powershell
python -m pytest
```

Run the integration tests with automatic capability checks:

```powershell
python -m pytest tests/integration -m integration
```

Require the local build capability to be present, failing rather than skipping if it is missing:

```powershell
python -m pytest tests/integration -m integration --pqc-require-local-build
```

Flash current firmware with an explicit verified build record:

```powershell
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart
```

Flash current firmware with the explicit untracked-artifact escape hatch:

```powershell
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --allow-untracked-artifact
```

Build and flash current firmware in one result run:

```powershell
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml
```

Run the gateway flash integration test with automatic capability checks:

```powershell
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration
```

Require gateway flash capability to be present, failing rather than skipping if it is missing:

```powershell
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
```

Ad hoc UART monitor through the framework:

```powershell
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml --duration-seconds 10
```

Ad hoc UART monitor with the configured gateway reset helper during capture:

```powershell
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml --restart
```

Build, flash, and capture post-flash UART in one run:

```powershell
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml --capture-uart
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
```

Run the known-good automated baseline:

```powershell
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
```

Build wolfBoot through the Phase 10f build profile when local wolfBoot source and tooling are intentionally available:

```powershell
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
```

Expected result: the build command creates `results/wolfboot-builds/<timestamp>_wolfboot_stm32l4_ecdsa_p256/manifest.json` and `wolfboot_build.log`. If `tools/wolfboot` is absent, the command fails before invoking build tooling and records a clear missing-source result. If `make` or the configured executable is unavailable, it records a controlled missing-tool result. With upstream wolfBoot source present, the current default profile may still fail at STM32L4 HAL/CMSIS integration until the project-local STM32L4R5 target adaptation is implemented.

Run the baseline experiment using an existing first-class build record:

```powershell
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml --build-number 7
```

Run the baseline UART hardware test with automatic capability checks:

```powershell
python -m pytest tests/hardware/test_baseline_uart.py -m hardware
```

Run the Phase 10i/10j secure-boot positive and negative hardware workflow tests with automatic capability checks:

```powershell
python -m pytest tests/hardware/test_secure_boot_flash_workflow.py -m hardware
```

Require hardware/UART capability to be present, failing rather than skipping if it is missing:

```powershell
python -m pytest tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware
python -m pytest tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware
```

Flash current firmware manually:

```powershell
scp .\build\Debug\stm32_basic_hal1.elf pqc-gateway1:/tmp/stm32_basic_hal1.elf
ssh pqc-gateway1 "flash-stm32a /tmp/stm32_basic_hal1.elf"
```

Capture UART log on the gateway:

```bash
picocom -b 115200 /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
```

Expected UART baseline:

```text
stm32-basic_hal1 boot v0.1.0
tick
tick
tick
```

## 14. Instructions for Future AI Agents

Before proposing code changes, inspect:

```text
AI_BUILD_GUIDE.md
README.md
docs/
configs/
scripts/
tests/
```

When asked to implement a feature, respond with:

1. A brief interpretation of the requested change.
2. Files that need to be inspected.
3. Files that will likely change.
4. Proposed code changes.
5. Proposed test changes.
6. Proposed documentation updates.
7. Exact commands to run.
8. Expected output or pass/fail criteria.
9. Assumptions, risks, or unresolved questions.

Do not make broad architectural changes unless explicitly requested.

Do not invent files that were not shown or described.

If context is missing, ask for it before giving a patch.

When asking the user to upload more than one repository file, include a copy-paste PowerShell `Compress-Archive` command that zips exactly those requested files to `C:\Users\timko\Downloads\<descriptive-context-name>.zip`. Use a `$files = @(...)` list containing repository-relative paths and a command in this form:

```powershell
$files = @(
  "path/to/first-file",
  "path/to/second-file"
)

Compress-Archive -LiteralPath $files -DestinationPath "$env:USERPROFILE\Downloads\<descriptive-context-name>.zip" -Force
```

If asking for only one file, a ZIP command is optional.

When providing code changes, clearly identify the target file path.

For every file that needs to be modified or created, provide a downloadable replacement artifact using the exact target filename. This requirement applies to documentation, code, configuration, scripts, tests, and any other text file changed by the request.

For every file that needs to be modified or created, also provide the complete replacement content for that file so the user can inspect, download, copy, or replace the file locally.

If more than one file needs to be modified or created, also provide a downloadable `.zip` archive containing all replacement files at their intended repository-relative paths. The archive must be suitable for unzip-and-overwrite use from the repository root.

Whenever a downloadable `.zip` archive is provided, also provide the exact PowerShell extraction command immediately after the archive link. The command must assume the user has downloaded the archive to `C:\Users\timko\Downloads\` and will run the command from the repository workspace root, such as a VS Code terminal opened at the project root. Use this form, replacing only the archive filename:

```powershell
Expand-Archive -LiteralPath "C:\Users\timko\Downloads\<archive-name>.zip" -DestinationPath . -Force
```

Do not require the user to copy or move the downloaded archive into the repository root before extracting it.

Also highlight the specific changes or manual edits separately, such as with a short summary or focused diff-style notes.

Do not change unrelated content in the replacement file. The full-file replacement must contain only the changes necessary to implement the requested change.

Prefer complete replacement snippets for small files and focused patch-style edits for larger files, but full replacement content and downloadable replacement artifacts are still required for every modified or newly created file.

End implementation responses with the next verification command.

## Expected Response Format for Review Requests

For review-only requests, such as checking whether instructions, documentation, configuration, tests, or workflow rules are implemented correctly, respond with:

1. A brief interpretation of the review.
2. Files inspected.
3. Compliance result.
4. Issues found.
5. Files that likely need changes.
6. Proposed documentation, prompt, test, or code updates.
7. Exact verification commands.
8. Expected output or pass/fail criteria.
9. Assumptions, risks, or unresolved questions.

Do not claim that external ChatGPT Project settings are installed correctly unless the user provides the actual settings text, export, or screenshot.

## 15. Feature Request Workflow

For each new feature request:

1. The user opens a new feature-request chat and describes the requested change.

2. If the latest `AI_BUILD_GUIDE.md` has not already been provided, the AI asks the user to provide it before proposing code changes.

3. The AI reviews the current `AI_BUILD_GUIDE.md` and treats it as the source of truth for:
   - repository structure
   - workflow rules
   - known-good baseline
   - tests
   - documentation expectations
   - safety constraints
   - current implementation phase

4. The AI asks for only the relevant source, config, test, and documentation files needed for the requested change. When requesting more than one repository file, the AI also provides a copy-paste PowerShell `Compress-Archive` command so the user can zip the requested files and upload one context archive.

5. The user provides the requested files.

6. The AI proposes a small, controlled implementation plan covering:
   - code changes
   - tests to add or update
   - documentation updates
   - complete replacement content for every file that needs to be modified or created
   - downloadable replacement artifacts using the exact target filenames for every modified or newly created file
   - a downloadable `.zip` archive containing all replacement files at their repository-relative paths when multiple files are changed or created
   - the exact PowerShell extraction command for that archive, using `C:\Users\timko\Downloads\<archive-name>.zip` as the source path and `.` as the destination so it can be run from the repository workspace root
   - highlighted manual edits or diff-style notes for each modified or newly created file
   - build or verification commands
   - expected pass/fail criteria
   - assumptions, risks, or unresolved questions

7. The user applies the changes locally.

8. The user runs the requested verification commands.

9. The user returns relevant logs, errors, test output, flashing output, UART output, or screenshots.

10. The AI reviews the evidence and updates the next step.

The next step may be to revise the change, request one additional relevant file, update tests, update documentation, run another verification command, or mark the feature request as complete if verification passes.

The AI should not proceed with code generation until the current build guide and relevant files have been provided.

The AI must not ask for the full repository by default.


## Phase 10a Direct-Flash Boot Config Model

Implemented scope:

- `configs/boot/direct_flash.yaml` is the only runnable boot config.
- `configs/experiments/baseline_direct_uart.yaml` references it with `boot: direct_flash`.
- Config loading resolves experiment, board, host, and boot configs.
- Validation rejects missing boot references, boot ID mismatches, non-runnable boot configs, and mismatches between `firmware.mode` and the resolved boot mode.
- Manifest generation records the resolved boot config mode as `boot_mode: direct_flash`.
- Build fingerprint input coverage includes the resolved boot config.
- Existing direct-flash commands remain the intended regression path: `status`, `create-run`, `build`, `flash`, `build-flash`, and `run`.

Not implemented in Phase 10a:

- wolfBoot build support
- wolfBoot flash layout
- linker relocation
- image signing
- wolfBoot flashing
- wolfBoot UART evidence

## Phase 10b Planned wolfBoot Boot Config Placeholder

Implemented scope:

- `configs/boot/wolfboot_ecdsa_p256.yaml` exists as a planned, inactive boot profile.
- The planned profile records `mode: wolfboot_ecdsa_p256`, `runnable: false`, `status: planned`, intended ECDSA-P256 signature metadata, a planned signed-application slot concept, and, after Phase 10d, `flash_layout_status: defined_phase_10d_planned_not_implemented`.
- The planned profile originally avoided claiming a final flash layout; Phase 10d now records a planned layout while still avoiding any runtime implementation claim.
- The direct-flash baseline remains unchanged and continues to reference `direct_flash`.
- Boot config validation distinguishes inspection from execution: planned configs can be schema-validated for inspection, but execution-oriented experiment bundle loading rejects non-runnable boot configs.
- Unit tests cover planned wolfBoot config inspection and execution rejection.

Not implemented in Phase 10b:

- wolfBoot source
- wolfBoot target support
- secure-boot flash layout
- linker relocation
- image signing
- wolfBoot flashing
- wolfBoot UART evidence

## Phase 10c wolfBoot STM32L4 Target Support Assessment

Implemented scope:

- `docs/decisions/0002_wolfboot_stm32l4_target_support_assessment.md` records the Phase 10c decision.
- The closest upstream wolfBoot target is the existing STM32L4 support.
- The project decision is to use existing STM32L4 support as the starting point, but to create a project-local STM32L4R5 / NUCLEO-L4R5ZI-P target configuration or adaptation before building or flashing wolfBoot.
- The decision records compatibility concerns for flash size, flash page/sector layout, vector-table and image-header offset expectations, bootloader location, application offset, ECDSA-P256 signing support, and wolfBoot build/toolchain assumptions.
- `configs/boot/wolfboot_ecdsa_p256.yaml` remains non-runnable and now references the Phase 10c assessment decision.
- The direct-flash baseline remains the only runnable boot mode.

Not implemented in Phase 10c:

- wolfBoot source vendoring or submodule setup
- secure-boot flash layout finalization
- linker relocation
- wolfBoot build profile
- image signing
- signing-key generation
- wolfBoot flashing
- wolfBoot UART evidence
- secure-boot runtime success claims

Next intended Phase 10 step:

- Phase 10e should relocate the HAL application build to the selected signed-image entry address `0x08020100` while preserving the direct-flash baseline.

Hardware success must still only be claimed from user-provided logs.

## Phase 10d Define Secure-Boot Flash Layout

Implemented scope:

- `docs/decisions/0003_secure_boot_flash_layout.md` records the Phase 10d flash layout decision.
- The selected initial planned layout uses the STM32L4R5 2 MB internal flash range from `0x08000000` through `0x081FFFFF`.
- The planned wolfBoot region is `0x08000000..0x0801FFFF` with size `0x00020000` / 128 KB.
- The planned signed application primary slot is `0x08020000..0x080FFFFF` with size `0x000E0000` / 896 KB.
- The planned relocated application entry address is `0x08020100`, accounting for the intended `0x100` wolfBoot image header.
- The planned signed application update slot is `0x08100000..0x081DFFFF` with size `0x000E0000` / 896 KB.
- The planned swap / metadata reserve is `0x081E0000..0x081FFFFF` with size `0x00020000` / 128 KB.
- The planned wolfBoot target values are recorded as `WOLFBOOT_SECTOR_SIZE 0x1000`, `WOLFBOOT_PARTITION_BOOT_ADDRESS 0x08020000`, `WOLFBOOT_PARTITION_SIZE 0x000E0000`, `WOLFBOOT_PARTITION_UPDATE_ADDRESS 0x08100000`, and `WOLFBOOT_PARTITION_SWAP_ADDRESS 0x081E0000`.
- `configs/boot/wolfboot_ecdsa_p256.yaml` records the layout under `secure_boot_layout` and remains `runnable: false`.
- Unit tests cover loading and inspection validation for the planned layout metadata and confirm the planned profile remains rejected for execution.
- The direct-flash baseline remains the only runnable boot mode.

Not implemented in Phase 10d:

- linker relocation
- vector-table changes
- wolfBoot source vendoring or submodule setup
- wolfBoot build profile
- signing-key generation
- image signing
- wolfBoot flashing
- signed application flashing
- wolfBoot UART evidence
- secure-boot runtime success claims


## Phase 10e Relocate HAL Application for Bootloader Launch

Implemented scope:

- Added the opt-in CMake configure/build preset `RelocatedDebug`.
- Added `STM32L4R5XX_FLASH_RELOCATED.ld` for the relocated HAL application build.
- The relocated linker script places the application vector table and reset entry at `0x08020100`, leaving the planned `0x100` wolfBoot image header at `0x08020000..0x080200FF`.
- The relocated preset sets `STM32_APP_VECTOR_OFFSET` to `0x00020100`, which is passed into the existing `system_stm32l4xx.c` vector-table configuration path through `VECT_TAB_OFFSET`.
- The default direct-flash `Debug` preset remains available and uses `STM32L4R5XX_FLASH.ld` with vector offset `0x00000000`.
- `configs/boot/wolfboot_ecdsa_p256.yaml` records the relocated build metadata but remains `runnable: false`.
- Unit tests cover the relocated CMake preset and linker-script address selection.

Manual relocated-build verification command:

```powershell
cmake --preset RelocatedDebug
cmake --build --preset RelocatedDebug
Test-Path .\build\RelocatedDebug\stm32_basic_hal1.elf
```

Expected result: the configure/build commands return success and `Test-Path` prints `True` when the local STM32/CMake/Ninja toolchain is available.

Not implemented in Phase 10e:

- wolfBoot source vendoring or submodule setup
- wolfBoot build profile
- signing-key generation
- image signing
- wolfBoot flashing
- signed application flashing
- wolfBoot UART evidence
- secure-boot runtime success claims

Hardware success must still only be claimed from user-provided logs.

Risks and unresolved items:

- The layout cannot be confirmed as bootable until wolfBoot is built for the project-local STM32L4R5 target and user-provided hardware logs show the expected UART evidence.
- The exact STM32L4R5 erase geometry, bank mode, and option-byte state still need confirmation before relying on swap/update behaviour.
- The 128 KB wolfBoot reserve and 128 KB swap / metadata reserve may need adjustment after measuring the selected wolfBoot build and verifying update/trailer requirements.


## Phase 10f Add wolfBoot Build Profile

Implemented scope:

- Added `configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml` as the build-only wolfBoot ECDSA-P256 profile.
- Added `scripts/framework/wolfboot_build.py` to construct and run the configured local wolfBoot build command through an injectable runner.
- Added `python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml`.
- The command records build evidence under `results/wolfboot-builds/<timestamp>_wolfboot_stm32l4_ecdsa_p256/`. It also records whether the project-local config was copied and whether the temporary MinGW keytools patch was enabled/applied.
- Build evidence includes `manifest.json`, `wolfboot_build.log`, command, working directory, return code, duration, source directory, output directory, expected artifact path, artifact existence, retained artifact path, and artifact SHA-256 when present.
- The helper fails before invoking build tooling when the configured source directory is absent.
- Unit tests cover command construction, missing source handling, successful mocked build evidence capture, missing artifact handling, profile validation, and CLI output without invoking real wolfBoot tooling.
- Direct-flash build behaviour remains unchanged.
- The default profile expects the produced ELF at `tools/wolfboot/wolfboot.elf`; generated wolfBoot ELF/BIN/HEX/MAP/object outputs under `tools/wolfboot` remain ignored by Git.
- `configs/boot/wolfboot_ecdsa_p256.yaml` remains `runnable: false`.

Not implemented in Phase 10f:

- wolfBoot source vendoring or submodule setup
- signing-key generation
- image signing
- wolfBoot flashing
- signed application flashing
- UART boot evidence
- secure-boot runtime success claims

Manual wolfBoot build-profile command:

```powershell
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
```

Expected result: the command records build evidence for success or failure. When `tools/wolfboot` is absent, it returns non-zero before invoking build tooling and records a clear missing-source result. When `make` or the configured executable is unavailable, it records a controlled missing-tool result. With upstream wolfBoot source present, the Phase 10f.1 profile supplies the required project HAL/CMSIS integration, target-only ARM compile settings, STM32L4R5 macro selection, decimal image-header size, and temporary MinGW host-keytools stdio compatibility patch and temporary STM32L4 HAL config PWR/PWREx include patch. A successful retained `wolfboot.elf` still depends on the local wolfBoot source revision and toolchain.

Hardware success must still only be claimed from user-provided logs.

Risks and unresolved items:

- A successful wolfBoot build is not evidence that the secure-boot path flashes or boots. Flashing, signing, and UART evidence remain later phases.
- The exact wolfBoot upstream commit should be pinned and reviewed before relying on long-term reproducibility.

## Phase 10f.1 Project-Local wolfBoot STM32L4R5 Target Adaptation

Implemented scope:

- The wolfBoot dependency strategy is the Git submodule at `tools/wolfboot`.
- Added `configs/wolfboot/stm32l4r5_ecdsa_p256.config` as the tracked project-local wolfBoot build configuration template.
- The framework copies that template to `tools/wolfboot/.config` before invoking the configured wolfBoot build command.
- The config preserves `SIGN=ECC256`, records the Phase 10d partition values, sets `STM32CUBE=../..` so wolfBoot can find the CubeMX-generated `Drivers/` tree from `tools/wolfboot`, and adds the required STM32L4R5 HAL/CMSIS include paths.
- The config applies Cortex-M4/thumb settings through wolfBoot target CFLAGS rather than through global host-tool compiler flags.
- The config undefines upstream wolfBoot's default `STM32L4A6xx` macro before defining `STM32L4R5xx`, because the project CubeMX CMSIS tree is for STM32L4R5 and does not provide `stm32l4a6xx.h`.
- The config uses decimal `IMAGE_HEADER_SIZE=256` because wolfBoot shell tests compare that value as an integer.
- The config keeps the Phase 10d layout assumptions and does not revise bootloader, primary slot, update slot, swap/metadata, or image-header addresses.
- The build profile invokes `make WOLFBOOT_ROOT=. wolfboot.elf` so wolfBoot builds the retained bootloader ELF without continuing into upstream `test-app/image.bin`, which is outside Phase 10f.1 scope.
- On Windows/MSYS, the build helper temporarily patches wolfBoot's host keytools Makefile to add `-D__USE_MINGW_ANSI_STDIO=1`, then restores the original Makefile so the submodule is not left dirty.
- The build helper temporarily patches wolfBoot's local `hal/stm32l4xx_hal_conf.h` to expose PWR/PWREx declarations needed by the STM32L4 flash-extension source, then restores the original file so the submodule is not left dirty.
- The project-local config adds the matching `stm32l4xx_hal_pwr.o` and `stm32l4xx_hal_pwr_ex.o` target objects.
- The wolfBoot build manifest and log record the config template path, generated config path, temporary patch status, return code, artifact path, retained artifact path, and SHA-256 when `wolfboot.elf` is produced.
- Unit tests cover config-copy handling, retained artifact metadata, generated-config validation, missing config templates, target-only command construction, and temporary patch/restore behaviour without invoking real wolfBoot tooling.
- The planned wolfBoot boot profile remains `runnable: false`.

Verified local evidence provided for Phase 10f.1:

```text
python -m pytest: 101 passed, 1 skipped
build-wolfboot return code: 0
wolfboot.elf artifact exists: True
wolfboot.elf SHA-256: 535b729aee2e112291761f7e3d60e46b094eb9079c09fd66529bd70b7b1edc83
```

Not implemented in Phase 10f.1:

- private signing-key generation
- application image signing
- wolfBoot flashing
- signed application flashing
- UART boot evidence
- secure-boot runtime success claims

Manual wolfBoot build-profile command:

```powershell
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
```

Expected result: when the `tools/wolfboot` submodule, required submodules, `make`, and ARM cross-toolchain are available, the command should produce and retain `wolfboot.elf` under `results/wolfboot-builds/<timestamp>_wolfboot_stm32l4_ecdsa_p256/` and record its SHA-256. If prerequisites are absent, the command records a controlled failure. A successful wolfBoot build still does not prove signing, flashing, UART boot, or secure-boot runtime success.

### Phase 10f.1 wolfBoot STM32L4R5 Troubleshooting Notes

These observed failures and fixes should be preserved for future AI-assisted changes:

1. **Missing STM32L4 HAL/CMSIS integration** — upstream `TARGET=stm32l4` did not directly find the repository-local CubeMX HAL/CMSIS layout until `STM32CUBE=../..` and project-local include paths were supplied.
2. **Wrong STM32L4 device macro** — upstream `TARGET=stm32l4` defined `STM32L4A6xx`; the STM32L4R5 CubeMX tree requires undefining that macro and defining `STM32L4R5xx`.
3. **Hex image-header size rejected by shell tests** — `IMAGE_HEADER_SIZE=0x100` caused integer-test errors in the observed Windows/MSYS environment. Use decimal `IMAGE_HEADER_SIZE=256` while preserving the same 256-byte header.
4. **Host keytools are not ARM target objects** — Cortex-M4/thumb flags must remain target-only. Host keytools may need the temporary MinGW ANSI stdio patch, but they must not receive ARM compiler flags.
5. **Incorrect wolfBoot root path** — plain `make` produced `/tools/keytools/keygen` in the observed Windows/MSYS environment. The build profile passes `WOLFBOOT_ROOT=.` so generated keytool paths resolve relative to `tools/wolfboot`.
6. **PWR/PWREx visibility for flash-extension HAL** — `stm32l4xx_hal_flash_ex.c` requires PWR/PWREx declarations and objects. A broad force-include of the CubeMX HAL config exposed HAL type-order errors, so the framework instead temporarily patches wolfBoot's local STM32L4 HAL config and adds PWR/PWREx objects.
7. **Plain `make` continues into upstream test-app** — plain `make` can link `wolfboot.elf` and then fail while building upstream `test-app/image.bin`. Phase 10f.1 should invoke the specific `wolfboot.elf` target because the upstream test application is outside this phase.
8. **Generated and temporary files must stay out of Git** — `tools/wolfboot/.config`, wolfBoot build outputs, private signing keys, and generated artifacts remain untracked. Temporary patches are applied and restored during `build-wolfboot`.

Future AI changes should avoid removing these fixes unless a new wolfBoot version or a deliberate target strategy change makes them unnecessary and that decision is documented.


## Phase 10g Signing Key and Image-Signing Workflow

Implemented scope:

- Added `configs/signing/wolfboot_ecdsa_p256_app.yaml` as the signing-only profile for the relocated HAL application image.
- Added `scripts/framework/signing.py` to construct and run configured local key-generation and image-signing commands through an injectable runner.
- Added `python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml`.
- The command expects the relocated application ELF at `build/RelocatedDebug/stm32_basic_hal1.elf` and signs `build/RelocatedDebug/stm32_basic_hal1.bin`. When the configured ELF exists and binary conversion is enabled, it regenerates the BIN with the configured `arm-none-eabi-objcopy -O binary` command before signing so stale pre-marker BIN files are not re-signed.
- The default private key location is `secrets/wolfboot/ecdsa_p256_private_key.der`.
- The command may generate the local ECDSA-P256 private key when absent by invoking the configured wolfBoot key-generation command from the configured `tools/wolfboot` working directory because wolfBoot keygen writes `src/keystore.c` relative to the wolfBoot source tree.
- Private key material remains local and is not copied into `results/`, replacement artifacts, or documentation.
- Signing evidence is recorded under `results/signing/<timestamp>_wolfboot_ecdsa_p256_app/` with `manifest.json`, `signing.log`, and retained `application_signed.bin` when signing succeeds.
- Signing metadata includes input ELF path, input image path and SHA-256, binary-conversion working directory and return code, signed image path and SHA-256, signature algorithm, signature size, image version, private-key path, private-key presence booleans, key-generation and signing working directories and return codes, and retained signed-image path.
- `.gitignore` excludes `secrets/wolfboot/` and generated signed images under `build/`.
- Unit tests cover command construction, key generation, signing metadata, existing-key handling, missing input handling, disabled-keygen missing-key handling, and signing profile validation without invoking real wolfBoot tooling.

Not implemented in Phase 10g:

- wolfBoot flashing
- signed-application flashing
- UART boot evidence
- secure-boot runtime success claims
- negative corrupted-image boot tests
- boot timing instrumentation

Manual signing verification command:

```powershell
cmake --preset RelocatedDebug
cmake --build --preset RelocatedDebug
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
```

Flash wolfBoot and the signed application, then capture UART evidence:

```powershell
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
```

Expected result: when the relocated build artifact, local wolfBoot keytools, and required toolchain are available, the command should produce signing evidence under `results/signing/` and retain `application_signed.bin`. If prerequisites are absent, the command records a controlled failure. A successful signing result still does not prove flashing, UART boot, or secure-boot runtime success.
