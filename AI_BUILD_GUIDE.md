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
    build.py
    manifest.py
```

Supported CLI commands are:

```powershell
python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
```

The `status` command loads the experiment config, resolves the referenced board and host configs, validates required fields, and prints a summary.

The `create-run` command loads the experiment config, resolves the referenced board and host configs, validates required fields, generates a run ID, and creates a local result folder.

The `build` command loads the experiment config, resolves the referenced board and host configs, validates required fields, generates a run ID, creates a local result folder, runs the local CMake configure and build presets, captures stdout, stderr, return code, build duration, expected output ELF path, and writes `results/<run_id>/build.log`.

The `status` and `create-run` commands must not build firmware, flash hardware, open UART devices, use SSH, or require physical hardware.

The `build` command may invoke local CMake/STM32 build tooling, but must not flash hardware, open UART devices, use SSH, or touch network resources.

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
build hash calculation
path handling
```

Current unit tests cover:

```text
tests/unit/test_config_loading.py
tests/unit/test_config_validation.py
tests/unit/test_manifest.py
tests/unit/test_build.py
```

These tests validate the initial config loader, config resolution, required-field checks, ID mismatch handling, status-summary no-hardware/no-network behaviour, run ID generation, manifest field generation, result-folder creation, build command construction, and build-result handling.

Build unit tests must not invoke CubeMX, CMake, Ninja, STM32 tooling, SSH, UART, or hardware directly. They must test command construction and result handling through injected or mocked command runners.

### Integration Tests

Integration tests live under:

```text
tests/integration/
```

These may require SSH access to `pqc-gateway1`, but should not necessarily flash hardware unless explicitly marked.

Examples:

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

These may:

```text
flash the board
capture UART output
run MQTT tests
apply network impairment
measure timing
```

Hardware tests must be opt-in.

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

The implemented `build` command creates:

```text
results/<run_id>/
  manifest.json
  build.log
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

The manifest should become the source of truth for what was run.

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

The `build` command adds build-related manifest fields after the local firmware build completes:

```text
firmware.artifact
firmware.artifact_path
firmware.artifact_exists
build.configure_preset
build.build_preset
build.return_code
build.duration_seconds
build.log
```

Expected future manifest fields include:

```text
git_commit
build_number
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

Current CLI commands are:

```powershell
python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
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
- captures stdout, stderr, return codes, duration, expected output ELF path, and build log path
- writes `results/<run_id>/build.log`
- updates `results/<run_id>/manifest.json` with build metadata
- does not flash anything
- does not open UART devices
- does not use SSH
- does not require physical hardware beyond the local build toolchain

Immediate next intended steps after this change:

1. Run the unit tests.
2. Run the `status` command.
3. Run the `create-run` command.
4. Run the `build` command.
5. Inspect the generated `results/<run_id>/manifest.json` and `results/<run_id>/build.log`.
6. Commit the build automation support if verification passes.

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
