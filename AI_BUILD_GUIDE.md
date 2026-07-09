# AI Build Guide — PQC IoT Experiment Framework

## 1. Purpose

This file is the compact source-of-truth context package for AI-assisted development of this repository. It records the current repository structure, implemented workflows, testing model, documentation expectations, and safety constraints.

Update this file whenever repository structure, CLI behaviour, configuration models, test layout, documentation structure, or experiment workflows change.

## 2. Project Purpose

This repository is an STM32-based embedded security experiment framework. The current implementation covers direct-flash STM32 HAL/FreeRTOS baseline workflows, wolfBoot secure-boot workflows, classical signing-algorithm benchmark profiles, ML-DSA-44/ML-DSA-65 secure-boot signing profiles, repeated secure-boot measurements, runtime/static benchmark metrics, and cross-profile benchmark aggregation.

Longer-term areas remain planned unless implemented by later phases: STM32 MQTT client firmware integration, wolfSSL MQTT/TLS experiments, production PQC/hybrid cryptographic profiles, network-degradation automation, and broader analysis/reporting automation.

## 3. Current Status

Current known-good firmware baseline:

```text
Board: NUCLEO-L4R5ZI-P / NUCLEO-L4R5ZI
MCU: STM32L4R5 / STM32L4Rxxx
Direct-flash UART marker: stm32-basic_hal1 boot v0.1.0
Secure-boot app UART marker: stm32-basic_hal1 secure-boot app v0.1.0
FreeRTOS scheduler marker: FreeRTOS scheduler starting: cmsis_rtos=v2 default_task=defaultTask ...
FreeRTOS task marker: FreeRTOS defaultTask started: periodic tick task active
Tick marker: tick
```

Implemented framework scope as of Phase 11.7:

- direct-flash baseline build, flash, UART capture, and run workflows
- CubeMX-generated CMSIS-RTOS v2 FreeRTOS application template using TIM1 as the HAL timebase
- first-class build records under `results/builds/<build_number>/`
- source/build fingerprinting and safe rebuild skipping
- explicit direct-flash boot config under `configs/boot/direct_flash.yaml`
- relocated HAL/FreeRTOS application build preset `RelocatedDebug`
- wolfBoot build profiles using the local submodule at `tools/wolfboot`
- application-signing profiles for classical wolfBoot algorithms and ML-DSA-44/ML-DSA-65
- secure-boot two-artifact flash workflow with positive UART evidence
- corrupted-application negative secure-boot test workflow
- secure-boot timing, cycle, result-code, and stack high-water evidence from explicit firmware/UART markers
- repeated secure-boot measurement samples and aggregate statistics
- static wolfBoot ELF/resource metrics and signed-artifact overhead metrics
- classical signing benchmark profiles: ECC256, ED25519, RSA2048, ECC384, ECC521, ED448, RSA3072, RSA4096
- ML-DSA secure-boot signing benchmark profiles: ML-DSA-44 and ML-DSA-65
- ML-DSA-87 is recorded as unavailable under the current 8192-byte image-header reserve
- read-only benchmark aggregation output to JSON and CSV
- consolidated Phase 11 documentation and unit coverage for benchmark schema, repeated-run statistics, unavailable metrics, manifest updates, and aggregation output
- FreeRTOS regression coverage for generated CMake wiring, baseline FreeRTOSConfig settings, CubeMX TIM1 timebase configuration, UART marker ordering, and direct/relocated local CMake builds
- gateway MQTT broker Docker Compose scaffold under `experiment/mqtt-broker/` with classical MQTT-over-TLS, an experimental OQS Mosquitto mutual-TLS profile, local classical certificate provisioning, remote OQS certificate provisioning, OQS TLS validation, and SSH/SCP deployment helpers
- Docker-hosted Linux default path for Python validation, STM32 direct and relocated builds, wolfBoot builds, relocated application signing, pytest, gateway checks, and gateway-mediated hardware experiments
- GitHub Actions CI preserving the existing runner-compatible jobs and MQTT broker Docker runtime validation while using the containerised non-hardware job as the default reproducible software-build validation path
- Phase M2 framework-side MQTT/TLS experiment configuration and result schema support with explicit transport backend selection, evidence classes, and unavailable metrics
- Phase M3 fake/no-network MQTT transport harness for deterministic simulated connect, publish, timeout, disconnect, and reconnect control-flow evidence
- Phase M4 host-side and broker-side MQTT/TLS broker compatibility validation with explicit evidence labels and false STM32/Wi-Fi/end-to-end success claims
- Phase M5 STM32-local lwIP/ST67W6X compile-only preparation: generated lwIP sources, SICS Network LwIP sources, SPI HAL support, and ST67W6X driver sources are included in direct and relocated firmware builds with runtime networking explicitly unavailable; firmware also emits a non-network lwIP runtime smoke UART marker using version, IPv4 formatting, and checksum helpers only

Important status constraints:

- `configs/boot/direct_flash.yaml` is the generic runnable boot profile for direct-flash workflows.
- wolfBoot boot configs are used by `flash-secure-boot`; do not treat them as generic direct-flash profiles.
- Hardware, gateway, flashing, UART, runtime, timing, memory, or benchmark success must only be claimed from explicit user-provided logs/manifests.
- STM32 MQTT client firmware runtime integration, real lwIP network-interface bring-up, ST67W61M1 hardware/module validation, wolfSSL/wolfMQTT transport experiments, broker deployment from MQTT client configs, MQTT/TLS hardware tests, production PQC TLS, production hybrid profiles, ML-DSA-87 under the current 8192-byte image-header reserve, and network impairment are not implemented.

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
Middlewares/
STM32L4R5XX_FLASH.ld
STM32L4R5XX_FLASH_RELOCATED.ld
startup_stm32l4r5xx.s
stm32_basic_hal1.ioc
Core/Inc/pqc_lwip_build_only.h
Core/Src/pqc_lwip_build_only.c
configs/
scripts/
tests/
tools/
results/
docs/
docker/
.github/workflows/
pytest.ini
experiment/mqtt-broker/
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
scripts/dev.ps1
scripts/dev.sh
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
scripts/framework/mqtt_fake_transport.py
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
tests/unit/test_mqtt_fake_transport.py
tests/unit/test_run.py
tests/unit/test_secure_boot_flash.py
tests/unit/test_signing.py
tests/unit/test_source.py
tests/unit/test_uart.py
tests/unit/test_wolfboot_build.py
tests/unit/test_mqtt_broker_compose.py
tests/unit/test_docker_default_workflow_docs.py
tests/unit/test_stm32_lwip_build_only_skeleton.py
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

All default commands are run from the repository root through the Docker wrapper scripts. Host-native commands remain available only as an explicit manual fallback.

Firmware scheduler model:

```text
The application uses CubeMX-generated CMSIS-RTOS v2 FreeRTOS. main() emits one-time direct-flash and secure-boot UART markers before osKernelStart(), emits the Phase M5 non-network lwIP runtime smoke marker, then emits default task creation and scheduler-start UART markers. StartDefaultTask() emits a task-start marker before emitting the recurring tick marker and toggling the LED with osDelay(1000). HAL timebase uses TIM1 so FreeRTOS owns SysTick.
```

Direct-flash baseline:

```powershell
./scripts/dev.ps1 experiment status --experiment configs/experiments/baseline_direct_uart.yaml
./scripts/dev.ps1 experiment create-run --experiment configs/experiments/baseline_direct_uart.yaml
./scripts/dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml
./scripts/dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml --force
./scripts/dev.ps1 experiment-gateway flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run <run_id>
./scripts/dev.ps1 experiment-gateway flash --experiment configs/experiments/baseline_direct_uart.yaml --allow-untracked-artifact
./scripts/dev.ps1 experiment-gateway flash --experiment configs/experiments/baseline_direct_uart.yaml --build-run <run_id> --capture-uart
./scripts/dev.ps1 experiment-gateway build-flash --experiment configs/experiments/baseline_direct_uart.yaml
./scripts/dev.ps1 experiment-gateway build-flash --experiment configs/experiments/baseline_direct_uart.yaml --capture-uart
./scripts/dev.ps1 experiment-gateway run --experiment configs/experiments/baseline_direct_uart.yaml
./scripts/dev.ps1 experiment-gateway run --experiment configs/experiments/baseline_direct_uart.yaml --build-number <number>
./scripts/dev.ps1 experiment-gateway monitor --experiment configs/experiments/baseline_direct_uart.yaml --duration-seconds 10
./scripts/dev.ps1 experiment-gateway monitor --experiment configs/experiments/baseline_direct_uart.yaml --restart
```

Secure-boot profile pattern:

```powershell
./scripts/dev.ps1 experiment build-wolfboot --profile configs/builds/wolfboot_stm32l4_<profile>.yaml
./scripts/dev.ps1 cmake --preset RelocatedDebug
./scripts/dev.ps1 cmake --build --preset RelocatedDebug
./scripts/dev.ps1 experiment sign-application --profile configs/signing/wolfboot_<profile>_app.yaml
./scripts/dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/wolfboot_<profile>_uart.yaml --repeat-count 5
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
mldsa44
mldsa65
```

ECC256 uses the historical file stem `wolfboot_stm32l4_ecdsa_p256.yaml` and signing stem `wolfboot_ecdsa_p256_app.yaml`; benchmark metadata identifies it as `ECC256` / `ecc256_reference`.

Secure-boot diagnostic and negative-test commands:

```powershell
./scripts/dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
./scripts/dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --negative-corrupt-application
./scripts/dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --skip-uart
```

Benchmark aggregation:

```powershell
./scripts/dev.ps1 experiment aggregate-benchmarks
./scripts/dev.ps1 experiment aggregate-benchmarks --manifest results/<run_id>/manifest.json --manifest results/<run_id>/manifest.json
./scripts/dev.ps1 experiment aggregate-benchmarks --run-dir results/<run_id> --run-dir results/<run_id>
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

Post-Phase 11 ML-DSA scope:

```text
ML-DSA-44 configs/experiments/wolfboot_mldsa44_uart.yaml
ML-DSA-65 configs/experiments/wolfboot_mldsa65_uart.yaml
ML-DSA-87 unavailable under the current 8192-byte image-header reserve
```

ML-DSA-44 and ML-DSA-65 use wolfBoot `SIGN=ML_DSA`, the same board, relocated HAL payload, UART marker model, repeated-run model, static metrics model, runtime stack high-water model, and secure-boot benchmark manifest schema as the classical profiles. ML-DSA-87 is not configured because wolfBoot's ML-DSA example requires `IMAGE_HEADER_SIZE=12288` for that variant.

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

The manifest is the source of truth for what was run. MQTT/TLS manifests may include an `mqtt_tls` block when the experiment config includes MQTT schema fields. That block records schema version, evidence class, transport backend, TLS mode, optional broker metadata, metric records, metric summary, limitations, and evidence-boundary flags. Supported evidence classes are `fake_no_network`, `host_side`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1_backed`. Supported transport backends are `fake_no_network`, `host_socket`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1`. Metrics without evidence must be recorded explicitly as unavailable with a reason. Phase M3 fake/no-network harness runs may also include `mqtt_tls.fake_transport` with deterministic simulated connect, publish, timeout, disconnect, and reconnect control-flow evidence. Fake transport evidence must be labelled `fake/no-network transport evidence` and must not be treated as real broker, socket, TLS, gateway, UART, STM32 runtime, Wi-Fi, hardware, or network success.

Secure-boot benchmark manifests separate:

- profile and algorithm metadata
- build-time metrics
- signed-artifact metrics
- runtime verification metrics
- runtime memory metrics
- repeated-run samples
- aggregate statistics
- explicit limitations/unavailable metrics

Benchmark comparison rules:

- Use median verification time and median verification cycles as primary headline metrics.
- Use mean, minimum, maximum, standard deviation, range, and coefficient of variation to review repeatability and outliers.
- Treat build metrics as static bootloader/resource evidence, not runtime memory evidence.
- Treat `.data + .bss` as the static RAM estimate.
- Treat signed-image overhead separately from verification timing because signature and header overhead affect storage pressure.
- Preserve unavailable-metric records and limitation notes in manifests and summaries.

Runtime timing, cycle counts, result codes, stack high-water values, and heap values must come from explicit firmware/UART markers. Do not infer these values from host timing, UART capture duration, reset delay, linker output alone, ELF output alone, or build logs alone.

## 10. Testing Model

Use three test categories:

```powershell
.\scripts\dev.ps1 pytest tests/unit
.\scripts\dev.ps1 pytest tests/integration -m integration
.\scripts\dev.ps1 pytest-hardware
.\scripts\dev.ps1 pytest
```

Unit tests must not require STM32 hardware, SSH, UART devices, MQTT broker access, VPN access, network impairment privileges, or local wolfBoot hardware tooling. Use injected/mocked command runners for command construction and result handling. Phase 11 benchmark unit coverage should validate schema creation, repeated-run aggregate calculations, unavailable-metric handling, manifest updates, and aggregation JSON/CSV output. Phase M2/M3 MQTT/TLS unit coverage should validate MQTT config acceptance/rejection, backend/evidence compatibility, secret-reference rejection, unavailable-metric handling, manifest schema creation, and deterministic fake/no-network transport outcomes.

FreeRTOS unit coverage should validate generated CMake wiring, baseline `FreeRTOSConfig.h` settings, CubeMX `.ioc` timebase/task settings, and UART marker ordering. Local-build integration coverage should compile both `Debug` and `RelocatedDebug` presets after FreeRTOS generation. Hardware coverage should treat FreeRTOS scheduler/task success as valid only when explicit UART markers are captured.

Routine secure-boot algorithm benchmark hardware runs should keep execution time bounded by running ML-DSA-65 by default and skipping the other profile matrix entries unless explicitly selected. Set `PQC_HARDWARE_SECURE_BOOT_PROFILES=<comma-separated profile names>` to add named profiles to the default ML-DSA-65 run, or set `PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES=1` for an all-in algorithm benchmark hardware pass.

Integration tests may invoke real local toolchains or gateway probes, but must skip cleanly when capabilities are unavailable unless strict flags are supplied. A plain `./scripts/dev.ps1 pytest` run should automatically exercise available local, gateway, and hardware capabilities and skip unavailable ones. The `--pqc-require-*` switches are strictness controls that convert unavailable capabilities into failures for intentional capability-specific checks; they are not normally required to make available tests run.

Hardware tests may flash the board, capture UART, and run end-to-end secure-boot workflows. They must be marked `hardware` and skip cleanly when required capabilities are unavailable.

Capability-gated strict checks:

```powershell
.\scripts\dev.ps1 pytest tests/integration -m integration --pqc-require-local-build
.\scripts\dev.ps1 pytest-gateway tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
.\scripts\dev.ps1 pytest-gateway tests/integration/test_lwip_runtime_smoke_uart.py -m integration --pqc-require-gateway
.\scripts\dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware
.\scripts\dev.ps1 pytest-hardware tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware
.\scripts\dev.ps1 pytest-hardware tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
$env:PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES="1"; .\scripts\dev.ps1 pytest-hardware tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

Primary verification command after documentation-only changes:

```powershell
./scripts/dev.ps1 pytest tests/unit
./scripts/dev.ps1 pytest
```


## 10a. Docker-Hosted Build/Test/Experiment Environment

The project default is Docker-hosted Linux execution for framework commands, firmware builds, wolfBoot builds, application signing, pytest, gateway checks, and gateway-mediated hardware experiments. The development host should provide Docker and, for gateway/hardware workflows, runtime-mounted SSH material and network reachability to the gateway. The development host is not expected to provide local STM32 build tools, CMake, Ninja, Arm GCC, Python pytest dependencies, wolfBoot host tools, or signing tools for normal use.

The default helper entry points are:

```powershell
.\scripts\dev.ps1 build-image
.\scripts\dev.ps1 pytest tests/unit
.\scripts\dev.ps1 pytest
.\scripts\dev.ps1 experiment status --experiment configs/experiments/baseline_direct_uart.yaml
.\scripts\dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml
.\scripts\dev.ps1 experiment-gateway run --experiment configs/experiments/baseline_direct_uart.yaml
.\scripts\dev.ps1 pytest-hardware
```

The POSIX equivalent is `./scripts/dev.sh` with the same subcommands. `PQC_DOCKER_IMAGE` can override the image tag. `PQC_DOCKER_SSH_DIR` can override the host-side SSH directory used by gateway-enabled wrapper commands.

The container definition lives at `docker/python/Dockerfile`, uses `requirements-dev.txt` for Python development dependencies, includes the STM32 CMake/Ninja/Arm GCC build dependencies, host build tooling for wolfBoot/keytools, OpenSSL for local certificate provisioning, and an SSH client for runtime-provided gateway access. It defaults to `./scripts/dev.ps1 pytest tests/unit` and sets `PQC_CONTAINER=1` for explicit in-container detection. The repository `.dockerignore` excludes generated outputs and local secret material from the image build context.

Supported default Docker workflows:

```text
Python unit tests and full capability-gated pytest selection
Framework commands that load, validate, build, sign, aggregate, flash, run, or monitor according to the selected command and available capabilities
STM32 direct-flash CMake configure/build using the Debug preset
STM32 relocated CMake configure/build using the RelocatedDebug preset
Local-build integration tests when the in-container toolchain capability is available
wolfBoot build workflows and integration tests when the in-container toolchain, make, profile configs, and runtime-mounted tools/wolfboot submodule are available
Relocated application signing workflows using runtime-mounted or locally generated signing material only
Gateway-mediated flash, UART, run, monitor, and hardware pytest workflows when SSH access is mounted at runtime and explicitly enabled
```

Hardware access remains gateway-mediated over SSH/SCP. The container runs the framework on the development host, copies artifacts to `pqc-gateway1` when required, and executes configured gateway helper commands for flashing, reset, UART capture, and broker orchestration. The container does not require USB/ST-LINK passthrough, direct UART device access, Wi-Fi-module passthrough, private keys in the image, or host-native STM32 tooling.

Gateway-capable container checks require all of the following:

```text
PQC_CONTAINER_ENABLE_GATEWAY=1
runtime-mounted SSH configuration and private key material
runtime-mounted or host-prepared known_hosts data for pqc-gateway1
reachable gateway network path, including any required host VPN outside the image
```

The wrapper commands `experiment-gateway`, `pytest-gateway`, and `pytest-hardware` set `PQC_CONTAINER_ENABLE_GATEWAY=1`, mount the configured SSH directory read-only at `/host-ssh`, and copy it into the temporary container filesystem with Linux permissions for that single run. Raw `docker run` invocations may still be used for manual diagnosis.

Pytest removes generated cross-platform build state at session start when running inside the container, or when `--pqc-clean-generated-build-artifacts` or `PQC_CLEAN_GENERATED_BUILD_ARTIFACTS=1` is used. The cleanup covers generated `build/Debug`, `build/RelocatedDebug`, wolfBoot `.config`, wolfBoot artifacts, and wolfBoot object/dependency/host-tool outputs that can contain host-specific absolute paths after switching between Windows-native and Linux-container builds. It does not remove source files or canonical signing keys under `secrets/wolfboot/`. Set `PQC_SKIP_CONTAINER_GENERATED_BUILD_CLEANUP=1` to suppress the default container cleanup.

Containerised application signing must use the runtime-mounted workspace or locally generated signing material only. Private signing keys, generated wolfBoot signing material, SSH keys, VPN keys, TLS private keys, MQTT passwords, real `.env` files, private certificates, and production credentials must not be committed, copied into result artifacts, included in replacement ZIPs, sent in build contexts, or baked into container images.

Host-native Windows or development-machine builds remain available only as an explicit manual fallback for diagnosis and CubeMX/IDE-oriented work. They are not the documented default path and should not be treated as the reproducible validation gate.

Containerised build/signing evidence is portable software-build evidence only. Do not claim hardware, gateway, flashing, UART, MQTT/TLS, timing, memory, benchmark, or end-to-end runtime success from container runs unless explicit logs, manifests, or equivalent evidence from those workflows are provided.


### Phase M5 lwIP/ST67W6X compile-only preparation

Phase M5 extends the earlier `pqc_lwip_build_only` boundary by allowing CubeMX-generated lwIP, SICS Network LwIP, SPI HAL, and ST67W6X network-driver sources to compile into the STM32 firmware. The project remains in compile-only/non-network mode for this layer: firmware builds may prove that sources compile and link, and UART logs may prove that the non-network lwIP runtime smoke helper ran. That smoke helper is limited to lwIP version, IPv4 formatting, and checksum helpers. It does not prove module detection, Wi-Fi association, IP address acquisition, TCP readiness, TLS handshake, MQTT connect, publish, reconnect, network runtime success, or end-to-end wireless success.

The current compile-only pin and peripheral preparation is:

```text
SPI1_SCK  PA5   Arduino D13
SPI1_MISO PA6   Arduino D12
SPI1_MOSI PA7   Arduino D11
SPI_CS    PD14  Arduino D10
CHIP_EN   PE11  Arduino D5
BOOT      PE9   Arduino D6
SPI_RDY   PE13  Arduino D3, EXTI13 through EXTI15_10_IRQn
USER_BUTTON PF15 Arduino D2, EXTI15 through EXTI15_10_IRQn
```

The generated clock preparation currently targets a 120 MHz SYSCLK/HCLK with SPI1 prescaler 4, yielding a compile-time configured SPI baud of approximately 30 Mbit/s if SPI1 is fed from the 120 MHz APB2/PCLK2 domain. FreeRTOS heap is increased to 40000 bytes for lwIP/ST67W6X preparation. Phase M5 filters generated lwIP application/demo files and optional nonessential ST67W6X demo/protocol utilities out of the compile-only CMake path while compiling the CMSIS-RTOS v2 lwIP sys_arch port; runtime networking remains deferred. The expected UART smoke line begins with `lwIP runtime smoke:` and includes `network=unavailable`.

CI and local verification for this phase are non-hardware checks only: static/unit validation plus direct and relocated firmware builds. The optional gateway integration test `tests/integration/test_lwip_runtime_smoke_uart.py` builds, flashes, captures UART, and asserts the non-network lwIP smoke marker appears with `network=unavailable`; it is hardware/UART helper-call evidence only and remains outside the default CI path. Broker, Wi-Fi-module, TLS, MQTT, and secret-dependent workflows remain outside the default CI path.

### CI containerised non-hardware checks

GitHub Actions CI is defined in `.github/workflows/ci.yml`. The workflow keeps the previously implemented runner-compatible jobs and MQTT broker Docker runtime validation as compatibility coverage, and uses the `container-non-hardware` job as the default reproducible software-build validation path. The containerised job builds the image from `docker/python/Dockerfile` and runs:

```text
Python unit tests
Safe framework status validation with no build, flash, SSH, UART, broker, or hardware access
STM32 Debug configure/build
STM32 RelocatedDebug configure/build
wolfBoot ECDSA P-256 build profile
Relocated application signing for the ECDSA P-256 profile using runtime-generated or runtime-mounted workspace material only
Targeted local-build integration tests for `test_local_build.py` and `test_wolfboot_build_integration.py`
```

CI must not require repository, organization, or environment secrets for the containerised non-hardware job. Hardware tests, gateway SSH checks, UART capture, board flashing, Wi-Fi-module workflows, and secret-dependent workflows remain outside the default CI path. The existing MQTT broker Docker runtime job remains local Docker runtime coverage using temporary test certificates, not gateway or production broker evidence. Any future gateway, hardware, Wi-Fi-module, or secret-dependent CI workflow must be separate and explicitly opt-in. Containerised CI evidence is portable software-build evidence only; it is not hardware, gateway, flashing, UART, runtime, timing, memory, benchmark, or end-to-end evidence.

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
experiment/mqtt-broker/runtime/
experiment/mqtt-broker/data/
experiment/mqtt-broker/log/
experiment/mqtt-broker/.env
```

Never commit or request committing:

```text
SSH private keys
VPN private keys
TLS private keys
MQTT passwords
real .env files
MQTT password files
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

MQTT broker scaffold:

```powershell
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile classical
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py status
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py stop
```

The OQS Mosquitto profile is experimental and must only be used for protocol evaluation. Do not claim PQC TLS success unless explicit broker/client logs confirm the negotiated algorithms.

## MQTT Broker Gateway Integration Update

The MQTT broker compose project uses `configs/hosts/gateway.yaml` for both SSH orchestration and non-SSH network validation:

```text
alias: pqc-gateway1
user: timk
network.address: 10.1.1.18
```

Use the SSH alias/user for `ssh` and `scp`. Use `network.address` for external MQTT/TLS checks when the SSH alias is not resolvable through DNS.

Certificate provisioning should include the host config so the generated server certificate contains the gateway IP address as an IP subject alternative name:

```powershell
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1 --host-config configs/hosts/gateway.yaml
```

The MQTT broker integration test is capability-gated and deploys to a temporary gateway directory, starts a temporary Compose project on an alternate host port, validates classical TLS 1.3 mutual authentication and OQS mutual TLS with ML-KEM/ML-DSA/Falcon evidence, stops the Compose project, and removes the temporary remote directory:

```powershell
./scripts/dev.ps1 pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e.py -m integration
./scripts/dev.ps1 pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e.py -m integration --pqc-require-gateway
```

Do not record MQTT/TLS runtime success unless supported by explicit Docker status/log output or TLS client validation output. Phase M4 broker compatibility validation is host-side and broker-side evidence only; it must not be used to claim STM32 firmware, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless success.


### MQTT OQS Mutual-TLS Profile

The experimental OQS MQTT broker profile uses `openquantumsafe/mosquitto:latest` and project-managed mutual-TLS material generated on the gateway. Default OQS certificate choices are `mldsa65` for the CA and `falcon512` for broker/client/healthcheck leaf certificates. The validation command uses the `mlkem768` TLS key-share group.

The profile remains an experimental protocol-evaluation path, not a production TLS configuration. Do not record OQS MQTT/TLS success unless supported by Docker status/log output and explicit OQS TLS client validation output. Generated OQS keys and certificates under `experiment/mqtt-broker/runtime/` or the remote runtime directory must not be committed.


MQTT OQS implementation note: The OQS MQTT broker profile logs to Docker stdout and disables Mosquitto persistence to avoid container-owned bind-mount artifacts in gateway and pytest temporary deployments.
