# AI Build Guide — PQC IoT Experiment Framework

## 1. Purpose

This file is the compact source-of-truth context package for AI-assisted development of this repository. It records the current repository structure, implemented workflows, testing model, documentation expectations, and safety constraints.

Update this file whenever repository structure, CLI behaviour, configuration models, test layout, documentation structure, or experiment workflows change.

## 2. Project Purpose

This repository is an STM32-based embedded security experiment framework. The current implementation covers direct-flash STM32 HAL baseline workflows, wolfBoot secure-boot workflows, classical signing-algorithm benchmark profiles, repeated secure-boot measurements, runtime/static benchmark metrics, and cross-profile benchmark aggregation.

Longer-term areas remain planned unless implemented by later phases: wolfSSL MQTT/TLS experiments, PQC/hybrid cryptographic profiles, network-degradation automation, and broader analysis/reporting automation.

## 3. Current Status

Current known-good firmware baseline:

```text
Board: NUCLEO-L4R5ZI-P / NUCLEO-L4R5ZI
MCU: STM32L4R5 / STM32L4Rxxx
Direct-flash UART marker: stm32-basic_hal1 boot v0.1.0
Secure-boot app UART marker: stm32-basic_hal1 secure-boot app v0.1.0
Tick marker: tick
```

Implemented framework scope as of Phase 11.6:

- direct-flash baseline build, flash, UART capture, and run workflows
- first-class build records under `results/builds/<build_number>/`
- source/build fingerprinting and safe rebuild skipping
- explicit direct-flash boot config under `configs/boot/direct_flash.yaml`
- relocated HAL application build preset `RelocatedDebug`
- wolfBoot build profiles using the local submodule at `tools/wolfboot`
- application-signing profiles for classical wolfBoot algorithms
- secure-boot two-artifact flash workflow with positive UART evidence
- corrupted-application negative secure-boot test workflow
- secure-boot timing, cycle, result-code, and stack high-water evidence from explicit firmware/UART markers
- repeated secure-boot measurement samples and aggregate statistics
- static wolfBoot ELF/resource metrics and signed-artifact overhead metrics
- classical signing benchmark profiles: ECC256, ED25519, RSA2048, ECC384, ECC521, ED448, RSA3072, RSA4096
- read-only benchmark aggregation output to JSON and CSV

Important status constraints:

- `configs/boot/direct_flash.yaml` is the generic runnable boot profile for direct-flash workflows.
- wolfBoot boot configs are used by `flash-secure-boot`; do not treat them as generic direct-flash profiles.
- Hardware, gateway, flashing, UART, runtime, timing, memory, or benchmark success must only be claimed from explicit user-provided logs/manifests.
- MQTT, TLS, PQC/hybrid profiles, and network impairment are not implemented.

## 4. Hardware and Gateway Context

```text
Gateway SSH alias: pqc-gateway1
Gateway user: timk
Gateway role: remote flashing and UART capture
Flash helper: flash-stm32a
Reset helper: reset-stm32a
ST-LINK serial: 066EFF3932504E3043111818
UART device: /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
UART baud: 115200
```

Manual direct-flash recovery command:

```powershell
scp .\build\Debug\stm32_basic_hal1.elf pqc-gateway1:/tmp/stm32_basic_hal1.elf
ssh pqc-gateway1 "flash-stm32a /tmp/stm32_basic_hal1.elf"
```

Manual UART capture on the gateway:

```bash
picocom -b 115200 /dev/serial/by-id/usb-STMicroelectronics_STM32_STLink_066EFF3932504E3043111818-if02
```

## 5. Repository Layout

CubeMX-generated firmware project remains at the repository root. Do not move CubeMX-generated folders unless explicitly requested.

Important root files and folders:

```text
CMakeLists.txt
CMakePresets.json
Core/
Drivers/
STM32L4R5XX_FLASH.ld
STM32L4R5XX_FLASH_RELOCATED.ld
startup_stm32l4r5xx.s
stm32_basic_hal1.ioc
configs/
scripts/
tests/
tools/
results/
docs/
pytest.ini
```

Implemented config layout:

```text
configs/
  boards/board_a.yaml
  hosts/gateway.yaml
  boot/direct_flash.yaml
  boot/wolfboot_*.yaml
  builds/wolfboot_stm32l4_*.yaml
  signing/wolfboot_*_app.yaml
  experiments/baseline_direct_uart.yaml
  experiments/wolfboot_*_uart.yaml
  benchmarks/classical_signing_profiles.yaml
  wolfboot/stm32l4r5_*.config
```

Implemented Python modules:

```text
scripts/experiment.py
scripts/framework/artifacts.py
scripts/framework/benchmark_aggregation.py
scripts/framework/build.py
scripts/framework/build_number.py
scripts/framework/build_records.py
scripts/framework/build_state.py
scripts/framework/fingerprint.py
scripts/framework/flash.py
scripts/framework/manifest.py
scripts/framework/secure_boot_flash.py
scripts/framework/signing.py
scripts/framework/source.py
scripts/framework/uart.py
scripts/framework/wolfboot_build.py
```

Implemented tests:

```text
tests/conftest.py
tests/unit/test_artifacts.py
tests/unit/test_benchmark_aggregation.py
tests/unit/test_build.py
tests/unit/test_build_number.py
tests/unit/test_build_records.py
tests/unit/test_build_state.py
tests/unit/test_cmake_relocated_profile.py
tests/unit/test_config_loading.py
tests/unit/test_config_validation.py
tests/unit/test_fingerprint.py
tests/unit/test_flash.py
tests/unit/test_manifest.py
tests/unit/test_run.py
tests/unit/test_secure_boot_flash.py
tests/unit/test_signing.py
tests/unit/test_source.py
tests/unit/test_uart.py
tests/unit/test_wolfboot_build.py
tests/integration/test_gateway_flash_helper.py
tests/integration/test_local_build.py
tests/integration/test_wolfboot_build_integration.py
tests/hardware/test_baseline_uart.py
tests/hardware/test_secure_boot_algorithm_benchmarks.py
tests/hardware/test_secure_boot_flash_workflow.py
```

Documentation layout:

```text
README.md
AI_BUILD_GUIDE.md
docs/000_project_overview.md
docs/001_ai_feature_request_workflow.md
docs/002_host_gateway_setup.md
docs/003_stm32_board_setup.md
docs/004_baseline_hal_app.md
docs/005_remote_flash_workflow.md
docs/006_security_and_secrets.md
docs/007_framework_architecture.md
docs/008_chatgpt_project_prompt.md
docs/009_chatgpt_project_prompt_release_readiness_review.md
docs/decisions/0001_keep_cubemx_project_at_repo_root.md
docs/decisions/0002_wolfboot_stm32l4_target_support_assessment.md
docs/decisions/0003_secure_boot_flash_layout.md
docs/phase11_plan.md
docs/plase11_checklist.md
docs/pqc_iot_experiment_framework_plan.md
```

Historical plans and decision records may intentionally preserve phase history; keep current-state claims in `AI_BUILD_GUIDE.md`, `README.md`, and `docs/007_framework_architecture.md` concise and current.

## 6. CLI Commands

All commands are run from the repository root.

Direct-flash baseline:

```powershell
python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py create-run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml --force
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run <run_id>
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --allow-untracked-artifact
python scripts/experiment.py flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run <run_id> --capture-uart
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py build-flash --experiment configs/experiments/baseline_direct_uart.yaml --capture-uart
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml --build-number <number>
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml --duration-seconds 10
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml --restart
```

Secure-boot profile pattern:

```powershell
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_<profile>.yaml
cmake --preset RelocatedDebug
cmake --build --preset RelocatedDebug
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_<profile>_app.yaml
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_<profile>_uart.yaml --repeat-count 5
```

Use these profile names where matching config files exist:

```text
ecdsa_p256
ecc384
ecc521
ed25519
ed448
rsa2048
rsa3072
rsa4096
```

ECC256 uses the historical file stem `wolfboot_stm32l4_ecdsa_p256.yaml` and signing stem `wolfboot_ecdsa_p256_app.yaml`; benchmark metadata identifies it as `ECC256` / `ecc256_reference`.

Secure-boot diagnostic and negative-test commands:

```powershell
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --negative-corrupt-application
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --skip-uart
```

Benchmark aggregation:

```powershell
python scripts/experiment.py aggregate-benchmarks
python scripts/experiment.py aggregate-benchmarks --manifest results/<run_id>/manifest.json --manifest results/<run_id>/manifest.json
python scripts/experiment.py aggregate-benchmarks --run-dir results/<run_id> --run-dir results/<run_id>
```

The aggregation command is read-only with respect to benchmark evidence. It scans existing manifests and writes summaries under `results/benchmark-aggregation/` by default.

## 7. Command Behaviour Summary

- `status`: loads and validates an experiment bundle; no build, flash, SSH, UART, or hardware access.
- `create-run`: creates `results/<run_id>/manifest.json` and `notes.md`; no build, flash, SSH, UART, or hardware access.
- `build`: runs local CMake configure/build unless safe rebuild skipping applies; creates compatibility run evidence and first-class build records; no SSH, UART, or hardware access.
- `flash`: validates artifact provenance through `--build-run` or explicit `--allow-untracked-artifact`; then uses SCP/SSH to flash; UART only with `--capture-uart`.
- `build-flash`: performs build then flash in one result run; skips flash if build fails; UART only with `--capture-uart`.
- `run`: direct-flash baseline orchestration: build or reuse a build record, flash, capture UART, and set pass/fail from boot/tick markers.
- `monitor`: ad hoc bounded UART capture through the gateway; writes logs under `results/adhoc/`; no manifest.
- `build-wolfboot`: builds the configured wolfBoot profile locally and records evidence under `results/wolfboot-builds/`; no signing, flashing, SSH, UART, or hardware access.
- `sign-application`: signs the relocated application for the configured profile and records evidence under `results/signing/`; no flashing, SSH, UART, or hardware access.
- `flash-secure-boot`: flashes wolfBoot plus a signed application, captures UART unless `--skip-uart`, supports repeated samples and corrupted-application negative testing.
- `aggregate-benchmarks`: reads existing secure-boot manifests and writes JSON/CSV summaries; no build, signing, flashing, SSH, UART, or hardware access.

## 8. Secure-Boot Benchmark Profiles

Minimum classical comparison scope:

```text
ECC256    configs/experiments/wolfboot_ecdsa_p256_uart.yaml
ED25519   configs/experiments/wolfboot_ed25519_uart.yaml
RSA2048   configs/experiments/wolfboot_rsa2048_uart.yaml
```

Optional expanded classical scope:

```text
ECC384    configs/experiments/wolfboot_ecc384_uart.yaml
ECC521    configs/experiments/wolfboot_ecc521_uart.yaml
ED448     configs/experiments/wolfboot_ed448_uart.yaml
RSA3072   configs/experiments/wolfboot_rsa3072_uart.yaml
RSA4096   configs/experiments/wolfboot_rsa4096_uart.yaml
```

All current classical benchmark profiles use the same board, relocated HAL payload, UART marker model, 80 MHz CPU-Hz assumption, Phase 11 8192-byte image-header reserve, repeated-run model, static metrics model, runtime stack high-water model, and secure-boot benchmark manifest schema.

## 9. Result and Evidence Model

Generated result locations:

```text
results/<run_id>/manifest.json
results/<run_id>/notes.md
results/<run_id>/build.log
results/<run_id>/flash.log
results/<run_id>/secure_boot_flash.log
results/<run_id>/uart.log
results/<run_id>/uart_sample_001.log
results/builds/<build_number>/manifest.json
results/wolfboot-builds/<timestamp>_<profile_id>/manifest.json
results/signing/<timestamp>_<profile_id>/manifest.json
results/benchmark-aggregation/benchmark_summary.json
results/benchmark-aggregation/benchmark_summary.csv
```

The manifest is the source of truth for what was run. Secure-boot benchmark manifests separate:

- profile and algorithm metadata
- build-time metrics
- signed-artifact metrics
- runtime verification metrics
- runtime memory metrics
- repeated-run samples
- aggregate statistics
- explicit limitations/unavailable metrics

Runtime timing, cycle counts, result codes, and stack high-water values must come from explicit firmware/UART markers. Do not infer these values from host timing, UART capture duration, reset delay, linker output alone, ELF output alone, or build logs alone.

## 10. Testing Model

Use three test categories:

```powershell
python -m pytest tests/unit
python -m pytest tests/integration -m integration
python -m pytest tests/hardware -m hardware
python -m pytest
```

Unit tests must not require STM32 hardware, SSH, UART devices, MQTT broker access, VPN access, network impairment privileges, or local wolfBoot hardware tooling. Use injected/mocked command runners for command construction and result handling.

Integration tests may invoke real local toolchains or gateway probes, but must skip cleanly when capabilities are unavailable unless strict flags are supplied.

Hardware tests may flash the board, capture UART, and run end-to-end secure-boot workflows. They must be marked `hardware` and skip cleanly unless strict capability flags are supplied.

Capability-gated strict checks:

```powershell
python -m pytest tests/integration -m integration --pqc-require-local-build
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
python -m pytest tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware
python -m pytest tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware
python -m pytest tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

Primary verification command after documentation-only changes:

```powershell
python -m pytest tests/unit
python -m pytest
```

## 11. Git, Generated Files, and Secrets

Commit source, configs, tests, docs, `.ioc`, linker scripts, and project-local wolfBoot config templates.

Do not commit generated outputs or local state, including:

```text
build/
results/*
!results/.gitkeep
.last_successful_build.json
.build_number
*.elf
*.bin
*.hex
*.map
*.list
*.su
__pycache__/
.pytest_cache/
tools/wolfboot/.config
tools/wolfboot/wolfboot.elf
tools/wolfboot/wolfboot.bin
tools/wolfboot/wolfboot_signing_private_key.der
secrets/wolfboot/
```

Never commit or request committing:

```text
SSH private keys
VPN private keys
TLS private keys
MQTT passwords
real .env files
private certificates
private signing keys
private wolfBoot signing keys
production credentials
```

Build/signing workflows may record non-secret key SHA-256 fingerprints as consistency evidence, but private key material must remain local and must not be copied into results or documentation.

## 12. AI-Assisted Development Rules

When implementing or reviewing changes:

1. Read this guide first.
2. Do not rely on prior chats, prior uploads, memory, or inferred repository state.
3. Ask only for files needed for the current change or review.
4. If asking for multiple files, provide a PowerShell `Compress-Archive` command with a repository-relative `$files = @(...)` list and output to `C:\Users\timko\Downloads\<name>.zip`.
5. Do not implement future phases early.
6. Preserve the direct-flash baseline unless explicitly asked to change it.
7. Do not move CubeMX-generated folders unless explicitly requested.
8. Add or update tests for framework code changes.
9. Keep hardware-dependent tests separate and capability-gated.
10. Update relevant documentation in the same change.
11. Do not claim hardware, gateway, flashing, UART, runtime, timing, memory, or benchmark success without explicit logs/manifests.
12. Do not ask for or suggest committing secrets.
13. Provide complete replacement content and downloadable artifacts for every modified or created file.
14. If multiple files are changed, provide a ZIP with repository-relative paths and the exact `Expand-Archive` command.

Implementation-response sections:

1. Brief interpretation.
2. Files inspected.
3. Files likely to change.
4. Proposed code changes.
5. Proposed test changes.
6. Proposed documentation updates.
7. Exact commands to run.
8. Expected output or pass/fail criteria.
9. Assumptions, risks, or unresolved questions.

Review-response sections:

1. Brief interpretation.
2. Files inspected.
3. Compliance result.
4. Issues found.
5. Files likely needing changes.
6. Proposed updates.
7. Exact verification commands.
8. Expected output or pass/fail criteria.
9. Assumptions, risks, or unresolved questions.

## 13. Known Documentation Maintenance Rules

- Keep `AI_BUILD_GUIDE.md` concise and current; avoid accumulating full phase-by-phase implementation history.
- Use `README.md` for user-facing command orientation.
- Use `docs/007_framework_architecture.md` for current architecture and file map.
- Keep detailed phase plans/checklists as historical planning artifacts unless explicitly updating them.
- Do not duplicate long command explanations across every document.
