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
  decisions/
    0001_keep_cubemx_project_at_repo_root.md
```

Current rule:

```text
Do not move the CubeMX-generated folders yet.
```

The STM32 tooling is path-sensitive, and the current firmware project builds correctly in this layout.

Future framework folders should be added alongside the CubeMX-generated project:

```text
configs/
scripts/
tests/
results/
tools/
```

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
client key bundles
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

## 10. Planned Configuration Model

Use small YAML or JSON files, composed by experiment configs.

Planned structure:

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

The manifest should become the source of truth for what was run.

Expected manifest fields include:

```text
run_id
timestamp
git_commit
board
gateway
firmware
build_number
boot_mode
boot_crypto
transport_mode
transport_crypto
network_profile
result
logs
artifacts
```

Add fields incrementally as features are implemented.

## 12. Current Implementation Phase

Current phase:

```text
STM32 HAL baseline firmware project setup is complete.
AI build guide and documentation skeleton have been added.
Next phase: ChatGPT Project instruction prompt and minimal framework skeleton.
```

Do not implement wolfBoot, MQTT, TLS, PQC, or network impairment until the basic framework skeleton exists and has tests.

Immediate next intended steps:

1. Add the ChatGPT Project instruction prompt.
2. Commit documentation if not already committed.
3. Add `configs/`, `scripts/`, `tests/`, `results/`, and `tools/`.
4. Add initial config files:
   - `configs/boards/board_a.yaml`
   - `configs/hosts/gateway.yaml`
   - `configs/experiments/baseline_direct_uart.yaml`
5. Implement `scripts/experiment.py status`.
6. Add unit tests for config loading.
7. Add manifest-generation utilities.
8. Add unit tests for manifest creation.
9. Update this file after each structural or behavioural framework change.

## 13. Common Manual Commands

Delete stale CMake build cache:

```powershell
Remove-Item -Recurse -Force .\build
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

Prefer complete replacement snippets for small files and focused patch-style edits for larger files.

End implementation responses with the next verification command.

## 15. Feature Request Workflow

For each new feature request:

1. The user provides the latest `AI_BUILD_GUIDE.md`.
2. The AI reviews the build guide.
3. The AI asks for only the relevant source, config, test, and documentation files.
4. The user provides those files.
5. The AI proposes a small, controlled change.
6. The AI includes tests and documentation updates.
7. The AI provides exact verification commands.
8. The user applies the change and returns logs.
9. The AI helps interpret logs and identify the next step.

The AI should not proceed with code generation until the current build guide and relevant files have been provided.
