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

The current app is a direct-flash baseline. It does not yet use wolfBoot, MQTT, TLS, PQC, or network-degradation automation.

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
  experiments/
    baseline_direct_uart.yaml
```

Current initial framework CLI and utilities:

```text
scripts/
  experiment.py
  framework/
    artifacts.py
    build.py
    fingerprint.py
    flash.py
    manifest.py
    source.py
    uart.py
```

Current test layout:

```text
tests/
  unit/
    test_artifacts.py
    test_build.py
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
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml --capture-uart
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart --capture-uart
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml
```

The `status` command loads the experiment config, resolves the referenced board and host configs, validates required fields, and prints a summary.

The `create-run` command loads the experiment config, resolves the referenced board and host configs, validates required fields, generates a run ID, and creates a local result folder.

The `build` command loads the experiment config, resolves the referenced board and host configs, validates required fields, generates a run ID, creates a local result folder, records local Git source-control provenance, calculates a deterministic build input fingerprint, runs the local CMake configure and build presets, captures stdout, stderr, return code, build duration, expected output ELF path, calculates the expected ELF SHA-256 after a successful build and artifact-exists check, and writes `results/<run_id>/build.log`.

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
path handling
```

Current unit tests cover:

```text
tests/unit/test_config_loading.py
tests/unit/test_config_validation.py
tests/unit/test_manifest.py
tests/unit/test_build.py
tests/unit/test_fingerprint.py
tests/unit/test_flash.py
tests/unit/test_source.py
tests/unit/test_uart.py
```

These tests validate the initial config loader, config resolution, required-field checks, ID mismatch handling, status-summary no-hardware/no-network behaviour, run ID generation, manifest field generation, result-folder creation, build command construction, and build-result handling.

Build unit tests must not invoke CubeMX, CMake, Ninja, STM32 tooling, SSH, UART, or hardware directly. They must test command construction and result handling through injected or mocked command runners. Artifact SHA-256 unit tests must use temporary files with known content and expected hashes. Build-number unit tests must use temporary `.build_number` files and must not invoke build tools, Git, SSH, UART, or hardware. Build fingerprint unit tests must use temporary files to verify deterministic output, meaningful input-change detection, excluded-file behaviour, and clear missing-input failures. Source-control provenance unit tests must use injected or mocked Git command runners and must not invoke Git directly.

Flash unit tests must not invoke SCP, SSH, the gateway helper, or hardware directly. They test generated commands, failure handling, logs, source provenance, and manifest updates through injected command runners.

UART unit tests must not invoke SSH, UART devices, the gateway, or hardware directly. They test remote command construction, bounded-capture handling, pass/fail marker detection, logs, manifest updates, and CLI result-folder creation through injected command runners.

### Integration Tests

Integration tests live under:

```text
tests/integration/
```

Integration tests must be separated from unit tests and must be opt-in when they invoke local toolchains or external capabilities.

The current integration tests are:

```text
tests/integration/test_local_build.py
tests/integration/test_gateway_flash_helper.py
```

This test invokes the real local CLI build command through subprocess when explicitly enabled with:

```powershell
$env:PQC_RUN_LOCAL_BUILD_INTEGRATION = "1"
python -m pytest tests/integration -m integration
```

The local build integration test runs the real CMake/STM32 build process, verifies the command return code, generated result directory, `manifest.json`, `build.log`, CMake configure/build command entries, and expected ELF artifact state. It must not flash hardware, open UART devices, use SSH, or touch network resources.

Without `PQC_RUN_LOCAL_BUILD_INTEGRATION=1`, the local build integration test is skipped.

The gateway flash integration test invokes the real `flash` CLI command only when explicitly enabled with:

```powershell
$env:PQC_RUN_GATEWAY_FLASH_INTEGRATION = "1"
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration
```

It requires the built ELF, gateway SSH access, the configured flash helper, ST-LINK, and the target board. Without `PQC_RUN_GATEWAY_FLASH_INTEGRATION=1`, it is skipped.

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
```

These may:

```text
flash the board
capture UART output
run MQTT tests
apply network impairment
measure timing
```

Hardware tests must be opt-in. The baseline UART monitor hardware test is enabled only with:

```powershell
$env:PQC_RUN_BASELINE_UART_HARDWARE = "1"
python -m pytest tests/hardware/test_baseline_uart.py -m hardware
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
  experiments/
    baseline_direct_uart.yaml
```

The experiment config references board and host configs by ID:

```yaml
board: board_a
host: gateway
```

The CLI resolves these references to:

```text
configs/boards/board_a.yaml
configs/hosts/gateway.yaml
```

Current required experiment fields:

```text
id
description
board
host
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
  boot/
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

The implemented `build` command creates the following on success:

```text
results/<run_id>/
  manifest.json
  build.log
  notes.md
  firmware.elf
  firmware.hex  # when generated by the build
  firmware.bin  # when generated by the build
```

The build manifest also includes `source` metadata for the Git state observed before the local build helper runs.

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

The implemented `run` command creates the following on success:

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
```

The current fingerprint algorithm is:

```text
sha256-build-inputs-v1
```

The aggregate fingerprint hashes a sorted list of repository-relative input paths and each file's content SHA-256. The initial input set is deliberately small and covers the resolved experiment, board, and host configuration files plus the known firmware build inputs: `CMakeLists.txt`, `CMakePresets.json`, `STM32L4R5XX_FLASH.ld`, `startup_stm32l4r5xx.s`, `Core/`, and `cmake/`.

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
```

The `build-flash --capture-uart` command also records combined-stage UART summary fields:

```text
build_flash.uart_return_code
build_flash.uart_log
build_flash.uart_skipped
```

In a combined `build-flash` run, the flash step refreshes `source` metadata at flash time, so the final manifest reflects the Git state when flashing was attempted.

Expected future manifest fields include:

```text
boot_crypto
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
25. Add `scripts/experiment.py monitor` for ad hoc bounded UART monitoring through the configured gateway.
26. Add pass/fail detection for ad hoc monitor connectivity and non-empty UART data capture.
27. Add optional post-flash UART capture to `flash --capture-uart` and `build-flash --capture-uart`.
28. Add post-flash pass/fail detection for the expected baseline boot marker and `tick` marker.
29. Add the opt-in baseline UART hardware test.
30. Add `scripts/experiment.py run` as the known-good automated baseline.
31. Retain the exact built ELF inside each successful baseline run directory.
32. Add mocked orchestration tests for full-run success and stage failures.
33. Track build numbers using local `.build_number` state.
34. Copy successful build artifacts into result directories using canonical artifact filenames.

Current CLI commands are:

```powershell
python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --allow-untracked-artifact
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml --capture-uart
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run 2026-06-25_001_baseline_direct_uart --capture-uart
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml
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
- runs `cmake --preset Debug` by default
- runs `cmake --build --preset Debug` by default if configure succeeds
- captures stdout, stderr, return codes, duration, expected output ELF path, build log path, build number, build input fingerprint metadata, firmware SHA-256 after a successful build, copied result-artifact metadata, and Git source-control provenance
- writes `results/<run_id>/build.log`
- copies the built ELF into the result directory as `firmware.elf` after a successful build
- copies `firmware.hex` and `firmware.bin` when matching build outputs exist, and records them as absent optional artifacts when they do not
- updates `results/<run_id>/manifest.json` with `build_number`, build metadata, `build.fingerprint`, `build.fingerprint_inputs`, `build.fingerprint_algorithm`, `firmware.sha256`, `firmware.result_artifacts`, and `source` metadata
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
- runs the same local build workflow used by `build`
- stops immediately if the build fails
- copies the exact built ELF into the result directory using its original filename
- stops immediately if artifact copying fails
- flashes using the current run ID as the verified source build record
- stops and records UART as skipped if flashing fails
- always captures UART after a successful flash
- starts UART capture before invoking the configured reset helper
- passes only when the configured boot marker and tick marker are both present
- writes `manifest.json`, `notes.md`, `build.log`, `flash.log`, `uart.log`, `firmware.elf`, and optional `firmware.hex` / `firmware.bin` on success
- records stage return codes and the failure stage under `run`
- records the retained ELF under `firmware.result_artifact` and `firmware.result_artifact_path`
- records copied artifact metadata under `firmware.result_artifacts`
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

Immediate next intended steps after this change:

1. Run the unit tests.
2. Confirm both integration tests skip by default.
3. Run the opt-in local build integration test.
4. Run the opt-in gateway flash integration test only with the gateway and board available.
5. Run the opt-in baseline UART hardware test only with the gateway and board available.
6. Review user-provided logs before claiming hardware success.
7. Commit after verification passes.

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

Run framework unit tests:

```powershell
python -m pytest tests/unit
```

Confirm the local build integration test is skipped by default:

```powershell
python -m pytest tests/integration -m integration
```

Run the opt-in local build integration test on a development PC with the valid STM32/CMake/Ninja toolchain:

```powershell
$env:PQC_RUN_LOCAL_BUILD_INTEGRATION = "1"
python -m pytest tests/integration -m integration
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

Run the opt-in gateway flash integration test:

```powershell
$env:PQC_RUN_GATEWAY_FLASH_INTEGRATION = "1"
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration
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

Run the opt-in baseline UART hardware test:

```powershell
$env:PQC_RUN_BASELINE_UART_HARDWARE = "1"
python -m pytest tests/hardware/test_baseline_uart.py -m hardware
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

When providing code changes, clearly identify the target file path.

For every file that needs to be modified or created, provide a downloadable replacement artifact using the exact target filename. This requirement applies to documentation, code, configuration, scripts, tests, and any other text file changed by the request.

For every file that needs to be modified or created, also provide the complete replacement content for that file so the user can inspect, download, copy, or replace the file locally.

If more than one file needs to be modified or created, also provide a downloadable `.zip` archive containing all replacement files at their intended repository-relative paths. The archive must be suitable for unzip-and-overwrite use from the repository root.

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

4. The AI asks for only the relevant source, config, test, and documentation files needed for the requested change.

5. The user provides the requested files.

6. The AI proposes a small, controlled implementation plan covering:
   - code changes
   - tests to add or update
   - documentation updates
   - complete replacement content for every file that needs to be modified or created
   - downloadable replacement artifacts using the exact target filenames for every modified or newly created file
   - a downloadable `.zip` archive containing all replacement files at their repository-relative paths when multiple files are changed or created
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
