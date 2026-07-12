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
- Phase M6.3 project-owned wolfSSL unavailable transport boundary: `pqc_wolfssl_transport` exposes connect/read/write wrappers and callback-shaped receive/send entry points, consumes the Phase M6.2 network-interface state, and reports all transport operations unavailable without socket I/O, TLS sessions, certificates, handshake, MQTT, Wi-Fi, ST67W61M1, or end-to-end success
- Phase M6.2 project-owned STM32 lwIP network-interface boundary: `pqc_network_interface` owns an unattached local lwIP netif, derives interface/link/IP/TCP observations from lwIP netif and IPv4 state, and reports transport, Wi-Fi module, ST67W61M1, TLS handshake, MQTT connect/publish, reconnect, and end-to-end status as explicitly unavailable
- Phase M6.5 FreeRTOS task-context runtime smoke: existing deterministic lwIP and wolfSSL/wolfCrypt smokes remain labelled `context=pre_scheduler scheduler=not_started`, and serialized one-shot copies run from `defaultTask` with `context=freertos_task scheduler=running`; all Wi-Fi/link/IP/TCP/TLS-handshake/certificate/MQTT/reconnect/ST67W61M1/end-to-end claims remain unavailable and wolfSSL multithreaded support is not enabled.
- Phase M6.6 STM32-local lwIP UDP loopback smoke: a serialized one-shot check runs from `defaultTask` after scheduler start, initializes the lwIP TCP/IP core, sends a deterministic UDP payload to `127.0.0.1`, and validates the returned payload through the lwIP loop interface; UART evidence is labelled `stm32-local-lwip-loopback-only`, while Wi-Fi/ST67W61M1/link/hardware-IP/external-ping/external-TCP/TLS/MQTT/broker/reconnect/end-to-end claims remain unavailable.
- Phase M6.1 STM32-local wolfSSL TLS-context lifecycle preparation: selected wolfSSL client-context and supporting wolfCrypt sources are built from `tools/wolfboot/lib/wolfssl`, linked into direct and relocated firmware builds, and exercised through `pqc_wolfssl_build_only`; wolfSSL initialization, TLS 1.2 client `WOLFSSL_CTX` creation/free, and cleanup are supported, while certificate loading, private keys, runtime transport, TLS handshake, MQTT, Wi-Fi, ST67W61M1, and end-to-end network success remain explicitly unavailable
- Phase M7/M8 STM32-local wolfMQTT preparation: wolfMQTT is pinned as `Middlewares/Third_Party/wolfMQTT`, its client/packet/socket callback layers build in direct and relocated firmware, and project-owned `pqc_wolfmqtt_build_only` performs a serialized FreeRTOS task-context client initialization against an unavailable fake/no-network `MqttNet`; UART evidence is initialization-only, while transport, broker connection, TLS handshake, publish, reconnect, Wi-Fi, ST67W61M1, and end-to-end success remain unavailable

Important status constraints:

- wolfBoot signing state is managed as a reusable local tuple: canonical private key, matching wolfBoot-local private key, generated public key, and `tools/wolfboot/src/keystore.c`. A completely absent tuple may be created by the owning workflow when profile configuration permits generation. A complete matching tuple is preserved and reused. Partially missing or mismatched tuple state must fail before `make`; do not silently reconstruct tuple members from partial state or replace a canonical key.

- `configs/boot/direct_flash.yaml` is the generic runnable boot profile for direct-flash workflows.
- wolfBoot boot configs are used by `flash-secure-boot`; do not treat them as generic direct-flash profiles.
- Hardware, gateway, flashing, UART, runtime, timing, memory, or benchmark success must only be claimed from explicit user-provided logs/manifests.
- real STM32 MQTT protocol runtime, real lwIP network-interface bring-up, ST67W61M1 hardware/module validation, real wolfSSL TLS handshakes, wolfMQTT transport experiments, broker deployment from MQTT client configs, MQTT/TLS hardware tests beyond the Phase M6.1 TLS context lifecycle and Phase M6.2 unavailable-boundary markers, production PQC TLS, production hybrid profiles, ML-DSA-87 under the current 8192-byte image-header reserve, and network impairment are not implemented.

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
Core/Inc/pqc_wolfssl_build_only.h
Core/Src/pqc_wolfssl_build_only.c
Core/Inc/pqc_wolfssl_transport.h
Core/Src/pqc_wolfssl_transport.c
Core/Inc/pqc_wolfmqtt_build_only.h
Core/Src/pqc_wolfmqtt_build_only.c
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
tests/unit/test_stm32_wolfssl_build_only_skeleton.py
tests/unit/test_stm32_wolfmqtt_build_only_skeleton.py
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
docs/decisions/0001_keep_cubemx_project_at_repo_root.md
docs/decisions/0002_wolfboot_stm32l4_target_support_assessment.md
docs/decisions/0003_secure_boot_flash_layout.md
docs/pqc_iot_experiment_framework_plan.md
```

Historical plans and decision records may intentionally preserve phase history; keep current-state claims in `AI_BUILD_GUIDE.md`, `README.md`, and `docs/007_framework_architecture.md` concise and current.

The supported AI entry points are `docs/001_ai_feature_request_workflow.md` and `docs/008_chatgpt_project_prompt.md`. Release-readiness assessments use the review-request path in the maintained workflow; there is no separate release-readiness prompt document. Obsolete Phase 11 plan and checklist paths are not active documentation entry points.

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

Secure-boot profile pattern (normal Docker-wrapper path with framework-recorded relocated-build provenance):

```powershell
./scripts/dev.ps1 experiment build-wolfboot --profile configs/builds/wolfboot_stm32l4_<profile>.yaml
./scripts/dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml --configure-preset RelocatedDebug --build-preset RelocatedDebug --artifact build/RelocatedDebug/stm32_basic_hal1.elf
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

Do not run wolfBoot `keysclean` or manually remove any member of the reusable signing tuple. Generated-state preflight owns stale generated-output handling; incomplete or mismatched signing state must fail safely. Host-native build commands are diagnostic fallback only.

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
  For alternate presets, use `--configure-preset`, `--build-preset`, and `--artifact` together so the expected ELF and generated-state scope match the selected preset.
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

All current classical benchmark profiles use the same board, relocated HAL payload, UART marker model, reported bootloader RCC clock evidence, Phase 11 8192-byte image-header reserve, repeated-run model, static metrics model, runtime stack high-water model, and secure-boot benchmark manifest schema.

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

- Use median derived verification time and median raw verification cycles as primary headline metrics.
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

Generated-state preflight is the primary mechanism for build/signing compatibility, artifact provenance, and safe stale-output handling. Pytest session-start cleanup is supplementary cross-platform hygiene when running inside the container, or when `--pqc-clean-generated-build-artifacts` or `PQC_CLEAN_GENERATED_BUILD_ARTIFACTS=1` is used. It removes selected host-specific CMake and wolfBoot object/dependency/host-tool outputs, but it does not establish downstream provenance and must not remove source files, canonical signing keys under `secrets/wolfboot/`, or reusable signing-tuple members. Set `PQC_SKIP_CONTAINER_GENERATED_BUILD_CLEANUP=1` to suppress the default container hygiene cleanup.

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

CI and local verification for this phase are non-hardware checks only: static/unit validation plus direct and relocated firmware builds. Hardware, gateway, UART, broker, Wi-Fi-module, TLS, MQTT, and secret-dependent workflows remain outside the default CI path.


### Phase M6.3 wolfSSL unavailable transport boundary

Phase M6.3 adds `Core/Inc/pqc_wolfssl_transport.h` and `Core/Src/pqc_wolfssl_transport.c`. The project-owned boundary exposes connect, read, write, receive-callback, and send-callback entry points and reads the Phase M6.2 network-interface status only to preserve architectural alignment. Every operation returns explicit unavailable status, transfers zero bytes, and performs no socket I/O. Firmware emits `wolfSSL transport boundary:` with `evidence=unavailable-transport-only` and unavailable connect/read/write/TLS handshake/certificate/MQTT/reconnect/Wi-Fi/ST67W61M1/end-to-end fields. Direct and relocated builds plus static unit coverage are the non-hardware verification path. A known-image capability-gated UART assertion remains deferred in `docs/007_framework_architecture.md`.

### Phase M6.2 lwIP network-interface boundary and unavailable status

Phase M6.2 adds `Core/Inc/pqc_network_interface.h` and `Core/Src/pqc_network_interface.c` as a project-owned boundary for future ST67W61M1-backed lwIP integration. The current backend initializes an unattached local lwIP `struct netif`, clears its IPv4 storage with lwIP helpers, and derives interface-up, link-up, IPv4-any, IP-availability, and TCP-readiness observations from lwIP netif/IP state. Firmware emits an `lwIP network interface:` marker labelled `evidence=lwip-netif-state-only` with both raw lwIP observations and mapped unavailable states. Transport, Wi-Fi module detection, ST67W61M1 use, TLS handshake, MQTT connect, MQTT publish, reconnect, and end-to-end network success remain unavailable.

The boundary uses lwIP netif/IP state locally but does not register a netif, bring an interface or link up, start DHCP, open TCP, invoke wolfSSL or wolfMQTT, or access network hardware. Direct and relocated builds plus static unit coverage are the non-hardware verification path. A dedicated known-image hardware UART assertion remains capability-gated and deferred in `docs/007_framework_architecture.md` until the supplied hardware helper can build and flash the image before capture.

### Phase M6.1 wolfSSL TLS context lifecycle preparation

Phase M6.1 extends the project-owned `pqc_wolfssl_build_only` boundary from the earlier wolfCrypt SHA-256 primitive smoke to a minimal wolfSSL client TLS-context lifecycle. The CMake target `pqc_wolfssl_stm32_build_only` builds the selected wolfSSL client-context and supporting wolfCrypt sources from `tools/wolfboot/lib/wolfssl`, uses `Core/Inc/user_settings.h` and `Core/Inc/pqc_wolfssl_user_settings.h`, and links into both direct and relocated firmware builds. Firmware calls `wolfSSL_Init()`, creates and frees a TLS 1.2 client `WOLFSSL_CTX`, calls `wolfSSL_Cleanup()`, and emits a `wolfSSL TLS context smoke:` UART marker labelled `evidence=tls-context-lifecycle-only`.

This is source-build and optional hardware-smoke evidence for context lifecycle only. It does not create a `WOLFSSL` session, load certificates or private keys, open TCP, perform a TLS handshake, perform MQTT work, use Wi-Fi or ST67W61M1, or claim end-to-end network success. Private keys, credentials, real certificates, private CA material, and production TLS material must not be committed, copied into result artifacts, included in replacement ZIPs, or baked into container images.

CI and local verification remain non-hardware checks: static/unit validation plus direct and relocated firmware builds. A dedicated capability-gated hardware UART test is deferred in `docs/007_framework_architecture.md` until the known-image build/flash/UART helper is available in the supplied test context.

### CI containerised non-hardware checks

GitHub Actions CI is defined in `.github/workflows/ci.yml`. The workflow keeps the previously implemented runner-compatible jobs and MQTT broker Docker runtime validation as compatibility coverage, and uses the `container-non-hardware` job as the default reproducible software-build validation path. The containerised job builds the image from `docker/python/Dockerfile` and runs:

```text
Python unit tests
Safe framework status validation with no build, flash, SSH, UART, broker, or hardware access
STM32 Debug configure/build
STM32 RelocatedDebug configure/build through the framework build command so generated-state provenance is recorded before signing
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
8. Add or update tests for framework code changes. Do not stop at unit tests when the feature crosses process, build, Docker, gateway, broker, UART, firmware-runtime, network, or hardware boundaries. If no integration, gateway, or hardware test is added for an affected boundary, state the specific reason in the implementation response and document the deferred test item in `docs/007_framework_architecture.md` under a concise "Deferred test coverage" subsection for the affected area. Each deferred item must name the feature, the missing test layer, the capability or phase needed to complete it, and the command that should eventually verify it. Future AI requests that modify or complete related functionality must inspect this deferred coverage subsection and either implement the listed test, update it with current context, or explicitly justify why it is no longer applicable.
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

## Phase M6.2.1 Generated-State Preflight Update

The reusable generated-state preflight is implemented in `scripts/framework/generated_state.py`. Project-owned manifests are stored under `.pqc-generated-state/` and are generated local state that must not be committed. STM32 CMake, wolfBoot, application-signing, integration-test, and artifact-consuming experiment paths must use direct preflight/provenance checks rather than relying on pytest session-start cleanup. Successful build/signing records and matching artifact hashes are required for downstream signing and secure-boot flashing where configured.

The canonical MQTT/TLS development plan path is `docs/non_hardware_mqtt_tls_development_plan.md`. Future context-package commands must use that repository-relative path.

### Phase M6.2.1 hardware benchmark cleanup correction

`tests/hardware/test_secure_boot_algorithm_benchmarks.py` must not invoke wolfBoot `keysclean`. The benchmark test relies on `build-wolfboot` generated-state preflight for wolfBoot cleanup and may remove only its directly managed relocated CMake output. Pytest startup cleanup must not delete the wolfBoot-local private key, public key, or generated keystore because they are members of the reusable local signing tuple.

The profile-selection contract is executable: ML-DSA-65 runs by default, `PQC_HARDWARE_SECURE_BOOT_PROFILES` adds comma-separated named profiles, and `PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES=1` selects all profiles. Unknown profile names are rejected during collection.


### Phase M6.4 secure-boot timing clock evidence

Secure-boot verification timing uses the DWT cycle counter as the primary firmware-side evidence. The wolfBoot instrumentation mailbox records raw elapsed cycles, verification result, stack high-water evidence, and bootloader clock values derived from the active STM32 RCC register model: SYSCLK, HCLK, PCLK1, and PCLK2. Firmware does not convert cycles to milliseconds and does not report a hard-coded CPU frequency.

The framework may derive `derived_verification_time_ms` as `verification_cycles * 1000 / hclk_hz` only when both explicit UART values are present. The manifest records `derived_time_clock_source: hclk_hz` and keeps the raw cycles and reported clocks separate. This derived value is not RTC, wall-clock, host-duration, UART-latency, or independently calibrated timing evidence. Hardware assertions remain capability-gated and require explicit UART/manifest evidence.


### Phase M6.5 FreeRTOS task-context runtime smoke

Pre-scheduler and task-context smoke evidence are distinct. The task-context lwIP and wolfSSL/wolfCrypt checks run once from `defaultTask` after its explicit start marker and are labelled `context=freertos_task scheduler=running`. They remain deterministic local evidence only. No network interface bring-up, Wi-Fi, link, IP, TCP, certificate loading, TLS handshake, MQTT, reconnect, ST67W61M1, or end-to-end success is implemented or claimed. Calls are serialized, so this phase does not enable wolfSSL multithreaded or FreeRTOS mutex support.


### Phase M6.6 STM32-local lwIP UDP loopback

The project-owned loopback boundary lives in `Core/Inc/pqc_lwip_loopback.h` and `Core/Src/pqc_lwip_loopback.c`. It runs once from `defaultTask` after scheduler start and uses the configured lwIP loop interface to send and receive a deterministic UDP payload at `127.0.0.1`. The UART marker is local-only STM32/lwIP evidence. It must not be interpreted as Wi-Fi module detection, link-up, hardware-backed IP acquisition, external ping, external TCP connectivity, TLS handshake, MQTT connect/publish/reconnect, broker access, ST67W61M1 use, or end-to-end network success.

Non-hardware verification consists of static unit coverage plus direct and relocated builds. The capability-gated known-image hardware test builds, flashes, captures UART, and requires the scheduler marker to precede a passing local-loopback marker. No new manifest field is introduced in this phase; detailed loopback evidence remains in the captured UART log.


### Phase M7 wolfMQTT build-only skeleton

wolfMQTT is a dedicated pinned submodule at `Middlewares/Third_Party/wolfMQTT`. The STM32 build compiles `src/mqtt_client.c`, `src/mqtt_packet.c`, and `src/mqtt_socket.c` into `pqc_wolfmqtt_stm32_build_only`. `Core/Inc/pqc_wolfmqtt_build_only.h` and `Core/Src/pqc_wolfmqtt_build_only.c` use wolfMQTT's native `MqttNet` callback boundary, expose fake/no-network and reserved future ST67W61M1 backend selection, and initialize/deinitialize a client without performing network or MQTT protocol operations.

Phase M7 established build-only integration. Phase M8 reuses the same boundary for a one-shot FreeRTOS task-context fake/no-network initialization marker. Broker connection, TLS handshake, publish, reconnect, Wi-Fi, ST67W61M1, and end-to-end success remain unavailable. Static unit coverage and direct/relocated local-build integration are the verification path. Phase M8 adds the capability-gated known-image UART assertion for that fake/no-network initialization evidence.


### Phase M8 STM32 fake/no-network wolfMQTT runtime evidence

The existing `pqc_wolfmqtt_build_only` boundary is invoked once from `defaultTask` after the FreeRTOS scheduler starts. It selects `fake_no_network`, initializes and deinitializes a wolfMQTT client against unavailable callbacks, and emits `wolfMQTT runtime smoke:` with `evidence=stm32-fake-no-network-initialization-only`. The marker records initialization state only. Transport, Wi-Fi, link, IP, TCP, TLS handshake, MQTT connect, MQTT publish, reconnect, ST67W61M1, and end-to-end status remain unavailable. No X-NUCLEO-67W61M1 is required. Static unit coverage, direct/relocated builds, and a capability-gated known-image UART assertion are the verification path. Detailed runtime evidence remains in `uart.log`; no dedicated manifest field is added.

### Phase M9 host-side wolfMQTT/wolfSSL validation

Phase M9 adds `experiment/mqtt-broker/host-wolfmqtt/CMakeLists.txt` and `experiment/mqtt-broker/scripts/host_wolfmqtt_validate.py`. The native target compiles the pinned wolfMQTT client/example network path against the wolfSSL source pinned through the wolfBoot submodule. It is independent of the STM32 cross-compiled targets. Unit coverage checks source pinning and evidence labels; capability-aware integration coverage builds the native client when CMake, Ninja, wolfMQTT, and wolfSSL are available.

All Phase M9 output is `host_side` MQTT-over-TLS broker-compatibility evidence. It must keep STM32, Wi-Fi-module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, and end-to-end wireless claims false. Live local or gateway broker checks require separately provisioned temporary certificates and available broker capability. The canonical broker Compose path is `experiment/mqtt-broker/compose.yaml`.


### Phase M9 PowerShell argument forwarding

The host wolfMQTT wrapper uses `--client-args` as the PowerShell-safe boundary between wrapper options and upstream wolfMQTT arguments. When invoked through `scripts/dev.ps1`, every dash-prefixed wolfMQTT token must be quoted individually, such as `'-h'`, `'-p'`, `'-t'`, and `'-i'`. A standalone `--` is not the documented PowerShell path, and unquoted client flags may be bound as parameters of the advanced `dev.ps1` script before Docker is invoked.


### Phase M9 structured compatibility result

The host wolfMQTT/wolfSSL utility captures client output and records explicit runtime-marker booleans. `broker_compatibility_confirmed` may be true only for `host_side` evidence when the command returns zero and the required TLS socket connect, MQTT connect/acknowledge, subscribe, successful publish, message receive, MQTT disconnect, and socket disconnect markers are all present. This field must never be used as STM32, Wi-Fi, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, ST67W61M1, or end-to-end wireless evidence.
