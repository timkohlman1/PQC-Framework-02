# Framework Architecture

## Purpose

This document maps the current repository architecture to implemented framework behaviour.

## Current layers

Implemented:

1. CubeMX STM32 HAL/FreeRTOS firmware project at repository root.
2. Direct-flash baseline experiment workflow.
3. Local build automation and build records.
4. Remote gateway flash workflow.
5. UART capture and marker evaluation.
6. wolfBoot secure-boot build/sign/flash workflow.
7. Secure-boot benchmark evidence model.
8. Classical signing-algorithm benchmark profiles.
9. ML-DSA-44 and ML-DSA-65 secure-boot benchmark profiles using the existing 8192-byte image-header reserve.
10. Cross-profile benchmark aggregation output.
11. Post-secureboot application scheduler template using CMSIS-RTOS v2 FreeRTOS.
12. Gateway MQTT broker Docker Compose project with classical MQTT-over-TLS and an experimental OQS Mosquitto profile.
13. MQTT/TLS architecture documentation split between hardware-independent STM32-local lwIP/wolfSSL/wolfMQTT preparation and future ST67W61M1-backed validation.
14. Docker-hosted Linux default workflow for Python validation, STM32 direct/relocated builds, wolfBoot builds, application signing, pytest, and gateway-mediated hardware experiments.
15. GitHub Actions CI preserving existing runner-compatible and MQTT broker Docker runtime jobs while using the containerised non-hardware job as the default reproducible software-build validation path.

Planned but not implemented:

1. STM32 MQTT client firmware integration.
2. STM32-local lwIP, wolfSSL, and wolfMQTT build/runtime integration.
3. ST67W61M1 network-interface backend validation.
4. Classical STM32 MQTT-over-TLS runtime validation.
5. PQC or hybrid MQTT/TLS experiments after classical MQTT/TLS is stable and library support is confirmed.
6. Hybrid signing profiles and ML-DSA-87 under the current 8192-byte image-header reserve.
7. Network degradation automation.
8. Production release packaging.

## Source and configuration map

```text
CMakeLists.txt                              Firmware build definition
CMakePresets.json                           Debug and RelocatedDebug presets
STM32L4R5XX_FLASH.ld                        Direct-flash linker script
STM32L4R5XX_FLASH_RELOCATED.ld              Secure-boot relocated linker script
Core/                                       CubeMX HAL/FreeRTOS application source
Drivers/                                    CubeMX HAL/CMSIS drivers
Middlewares/Third_Party/FreeRTOS/           CubeMX-generated FreeRTOS middleware
configs/boards/board_a.yaml                 Board metadata
configs/hosts/gateway.yaml                  Gateway, flash helper, UART path
configs/boot/direct_flash.yaml              Direct-flash boot profile
configs/boot/wolfboot_*.yaml                Secure-boot profile metadata
configs/builds/wolfboot_stm32l4_*.yaml      wolfBoot build profiles
configs/signing/wolfboot_*_app.yaml         Application-signing profiles
configs/experiments/baseline_direct_uart.yaml
configs/experiments/wolfboot_*_uart.yaml    Experiment profiles
configs/benchmarks/classical_signing_profiles.yaml
configs/wolfboot/stm32l4r5_*.config         Project-local wolfBoot config templates
experiment/mqtt-broker/                      Gateway MQTT broker compose project
docker/python/Dockerfile                    Non-hardware Python, STM32, wolfBoot, and signing container baseline
.dockerignore                               Container build-context exclusions for generated output and secrets
.github/workflows/ci.yml                    CI workflow with runner-compatible, MQTT broker Docker runtime, and containerised non-hardware jobs
requirements-dev.txt                        Python development dependencies for unit-test validation
```

## Python implementation map

```text
scripts/experiment.py                       CLI entry point
scripts/framework/artifacts.py              Result artifact helpers
scripts/framework/benchmark_aggregation.py  Benchmark summary JSON/CSV generation
scripts/framework/build.py                  Local CMake build workflow
scripts/framework/build_number.py           Build number state handling
scripts/framework/build_records.py          First-class build record validation/use
scripts/framework/build_state.py            Last-successful-build state
scripts/framework/fingerprint.py            Build and secure-boot input fingerprints
scripts/framework/flash.py                  Direct-flash SCP/SSH workflow
scripts/framework/manifest.py               Manifest construction and benchmark schema helpers
scripts/framework/secure_boot_flash.py      wolfBoot two-artifact flash and UART benchmark workflow
scripts/framework/signing.py                Application signing workflow
scripts/framework/source.py                 Git provenance helpers
scripts/framework/uart.py                   UART capture and marker parsing
scripts/framework/wolfboot_build.py         wolfBoot build/config/temporary patch workflow
```



## Docker-hosted build/test/experiment baseline

The repository default is Docker-hosted Linux execution through `scripts/dev.ps1` or `scripts/dev.sh`. The container definition is `docker/python/Dockerfile`; Python development dependencies are in `requirements-dev.txt`; generated outputs and local secret material are excluded from the build context by `.dockerignore`.

The image contains the STM32 build dependencies needed to configure and build the existing `Debug` and `RelocatedDebug` CMake presets, host build tooling needed for wolfBoot/keytools builds, OpenSSL for local certificate provisioning, an SSH client for runtime-provided gateway access, and the tooling needed to run application-signing profiles after the relocated application has been built. The image sets `PQC_CONTAINER=1`; pytest still also detects Docker through `/.dockerenv`.

The default execution model removes the development machine's native build environment from normal framework use. Framework commands, pytest, CMake builds, wolfBoot builds, signing, and gateway-mediated hardware experiments normally run inside the project container. Hardware access remains SSH/SCP-mediated through the gateway, so the container does not need direct ST-LINK/USB passthrough, UART devices, or Wi-Fi-module access. Host-native Windows or development-machine builds remain an explicit manual fallback only.

Software-build evidence from the container includes Python test results, safe configuration-validation command output, STM32 build output for direct and relocated firmware profiles, wolfBoot build evidence, and application-signing evidence. Gateway, flashing, UART, MQTT/TLS, timing, memory, benchmark, or end-to-end runtime success still requires explicit logs, manifests, or equivalent evidence from the relevant gateway or hardware workflow.

Application signing inside the container uses the runtime-mounted workspace. Private signing keys and generated signing material must remain local generated state, such as under `secrets/wolfboot/`, and must not be committed, sent in build contexts, copied into replacement artifacts, or baked into images. The container includes an SSH client but no SSH keys, VPN keys, broker credentials, private certificates, private signing keys, or other secrets. Gateway-capable checks require `PQC_CONTAINER_ENABLE_GATEWAY=1` plus runtime-provided SSH configuration, known-hosts data, and credentials; the wrapper commands set this flag only for gateway and hardware subcommands.

Pytest performs generated-artifact cleanup at session start inside the container, and on native hosts when stale foreign build paths are detected. The cleanup scope is limited to generated `build/Debug`, `build/RelocatedDebug`, wolfBoot artifacts, `.config`, and wolfBoot object/dependency/host-tool outputs. It prevents CMake cache and wolfBoot dependency files from reusing absolute paths from a different build host while preserving source files and canonical signing keys under `secrets/wolfboot/`.

## Firmware scheduler model

The application firmware uses the CubeMX-generated CMSIS-RTOS v2 FreeRTOS template. `main()` performs HAL initialization, clock configuration, GPIO/UART initialization, and one-time UART evidence marker output before `osKernelStart()`. It also emits FreeRTOS scheduler markers for default task creation and scheduler start. `StartDefaultTask()` emits a task-start marker before it owns the recurring `tick` marker and LED toggle using `osDelay(1000)`. HAL timing is generated from TIM1 rather than SysTick so the FreeRTOS scheduler can own SysTick.

The direct-flash and secure-boot application markers remain part of the UART evidence contract. FreeRTOS task-level stack APIs are enabled for future task instrumentation, but task-level runtime stack/heap values must still be treated as unavailable until explicit firmware markers and manifests record them.


## Default Docker execution model

The default development execution path is Docker-hosted Linux. Framework commands, pytest, CMake firmware builds, wolfBoot builds, application signing, and gateway-mediated hardware experiments should normally be launched through `scripts/dev.ps1` or `scripts/dev.sh`. Host-native Windows or development-machine builds remain available as an explicit manual fallback, but they are not the reproducible validation gate.

Gateway and hardware workflows are still mediated by SSH/SCP rather than direct USB or UART access from the container:

```text
development host with Docker
  -> project container mounted at /workspace
    -> SSH/SCP to pqc-gateway1 using runtime-mounted SSH material
      -> gateway flash/reset/UART helpers
        -> STM32 board
```

This keeps the development machine's local build environment out of the normal experiment path while preserving the existing gateway hardware boundary.

## Direct-flash data flow

```text
experiment config
  -> board/host/boot resolution
  -> CMake build
  -> build record under results/builds/<build_number>/
  -> flash provenance check
  -> gateway SCP/SSH flash helper
  -> UART capture
  -> manifest verdict
```

The direct-flash baseline uses `configs/boot/direct_flash.yaml` and `configs/experiments/baseline_direct_uart.yaml`.

## Secure-boot data flow

```text
wolfBoot build profile
  -> project-local wolfBoot config template
  -> temporary local wolfBoot patches during build
  -> wolfBoot artifact evidence

RelocatedDebug application build
  -> profile-specific BIN
  -> signing profile
  -> signed application image evidence

secure-boot experiment profile
  -> key-consistency check
  -> flash wolfBoot artifact
  -> flash signed application artifact
  -> UART capture samples
  -> secure_boot_benchmark manifest evidence
```

The secure-boot workflow must not infer timing, stack, heap, or hardware success from host-side behaviour. Runtime metrics must come from explicit firmware/UART markers.


## STM32 MQTT/TLS target architecture

MQTT/TLS client development is split between hardware-independent preparation and future ST67W61M1-dependent validation. The target ownership model is:

```text
STM32 firmware
  -> application MQTT/TLS experiment logic
  -> wolfMQTT client layer
  -> wolfSSL TLS endpoint
  -> lwIP TCP/IP stack
  -> network-interface abstraction
  -> future ST67W61M1 Wi-Fi module backend
  -> external MQTT broker
```

The Wi-Fi module is treated as the network interface backend. It must not be documented or implemented as the MQTT client, TLS endpoint, certificate owner, or broker-side validation source. lwIP, wolfSSL, and wolfMQTT are intended to run on the STM32.

Supported planning modes are evidence-bound:

- Fake/no-network transport: deterministic simulated control-flow evidence only.
- Host/socket validation path: host-side client or broker compatibility evidence only.
- STM32 build-only path: compiler/linker evidence only.
- STM32 fake/no-network runtime path: board UART initialization evidence only.
- Future ST67W61M1 network-interface path: module detection, link, IP, and TCP readiness evidence only until TLS/MQTT are explicitly validated.
- Future STM32 MQTT-over-TLS path: TLS handshake, MQTT connect, publish, reconnect, timing, and resource evidence only from explicit STM32 UART logs, manifests, and broker logs.

Evidence categories must not be collapsed. Build-only evidence does not imply runtime success. Fake transport evidence does not imply broker, TLS, STM32, or Wi-Fi success. Host-side and broker-side evidence does not imply STM32 success. STM32 UART initialization evidence does not imply Wi-Fi, IP, TCP, TLS, MQTT, publish, reconnect, or end-to-end wireless success.

Small future implementation phases should preserve this boundary: MQTT/TLS config/result schema, fake/no-network transport harness, host-side broker compatibility validation, STM32 lwIP build-only skeleton, wolfSSL build-only skeleton, wolfMQTT build-only skeleton, STM32 fake/no-network runtime evidence, optional host-side wolfSSL/wolfMQTT validation, ST67W61M1 network-interface backend, classical STM32 MQTT-over-TLS validation, network degradation, and later PQC/hybrid MQTT/TLS experiments.

## Benchmark model

Secure-boot manifests include `secure_boot_benchmark`, which separates:

- profile identity and algorithm metadata
- build-time metrics
- signed-artifact metrics
- runtime verification metrics
- runtime memory metrics
- repeated-run samples
- aggregate statistics
- explicit limitations and unavailable metrics

Benchmark evidence is grouped by source and interpretation:

- Build-time metrics are static wolfBoot artifact measurements. They include `.text`, `.data`, `.bss`, flash-relevant bytes, and static RAM estimate. Static RAM is calculated from `.data + .bss`; it is not runtime stack usage.
- Signed-artifact metrics describe the application image after signing. They include signed size, unsigned size where available, signature size, overhead bytes, and overhead percentage.
- Runtime verification metrics describe firmware-reported verification evidence. Verification time, cycles, CPU-Hz, result code, and marker sources must come from explicit UART markers.
- Runtime memory metrics describe firmware-reported memory evidence. Stack high-water data is valid only when explicit firmware-side stack markers are present. Heap remains unavailable unless explicit heap evidence is added.
- Repeated-run samples record one verification sample per secure-boot reset/capture. Aggregate statistics use only samples marked valid for statistics.
- Derived metrics such as cycles per KB and time per KB are calculated only when the required source values are available.

Median verification time and cycles are the primary headline metrics for cross-profile comparison. Mean, minimum, maximum, standard deviation, range, and coefficient of variation support repeatability and outlier review. Unavailable fields and limitations are intentional evidence and must remain visible in manifests and aggregated summaries.

Profiles should be compared only when they use the same board, relocated HAL payload, CPU-Hz assumption, UART marker model, repeated-run model, image-header reserve, and measurement sources. Timing, stack, heap, or pass/fail status must not be inferred from host-side duration, SSH duration, reset delay, build logs, ELF files alone, or marker ordering alone.

The aggregation command reads existing manifests and writes:

```text
results/benchmark-aggregation/benchmark_summary.json
results/benchmark-aggregation/benchmark_summary.csv
```

It does not create new measurement evidence.


## MQTT/TLS configuration and result schema

Framework-side MQTT/TLS schema support starts with the Phase M2 configuration/result model. Experiment configs can carry an `mqtt` mapping with schema version, evidence class, transport backend, TLS mode, optional non-secret certificate references, optional host-side broker endpoint, and explicit unavailable metrics. The supported evidence classes are `fake_no_network`, `host_side`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1_backed`. The supported transport backends are `fake_no_network`, `host_socket`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1`.

Phase M3 adds `scripts/framework/mqtt_fake_transport.py` and the `mqtt-fake-transport` CLI command. This path models MQTT client control flow with deterministic simulated outcomes for connect, publish, disconnect, timeout, and reconnect attempts. It writes result evidence under `mqtt_tls.fake_transport`, labels that evidence as `fake/no-network transport evidence`, and keeps all real network, broker, TLS, gateway, UART, STM32 runtime, Wi-Fi, and hardware success flags false.

Phase M5 adds STM32-local lwIP/ST67W6X compile-only preparation to the firmware target. `Core/Inc/pqc_lwip_build_only.h` still defines the project-owned build-only status boundary and `Core/Src/pqc_lwip_build_only.c` keeps runtime networking explicitly unavailable. CubeMX-generated lwIP application files, SICS Network LwIP sources, SPI HAL support, and ST67W6X network-driver sources are now allowed to compile and link in both direct and relocated application builds so the future network-interface layer can be inspected against the real generated interfaces. This remains compile/link evidence only, with one additional non-network lwIP runtime smoke marker emitted over UART. The smoke marker exercises deterministic lwIP version, IPv4 formatting, and checksum helpers only; it does not initialize a netif, use ST67W6X hardware, acquire an IP address, open TCP, run TLS, or perform MQTT. The generated ST67W6X hardware-facing code is present so interfaces can be inspected and future stubs can be scoped, but the firmware does not claim module detection, Wi-Fi association, IP address acquisition, TCP readiness, TLS handshake, MQTT connect, publish, reconnect, network runtime success, or end-to-end wireless success.

The UART marker begins with `lwIP runtime smoke:` and includes `network=unavailable`; it is intended to prove that a constrained set of lwIP helper functions executes during the existing 10-second UART capture window without crossing the network-interface boundary. The optional gateway integration test `tests/integration/test_lwip_runtime_smoke_uart.py` exercises the baseline build/flash/UART flow and asserts that the marker appears in `uart.log`; this remains helper-call UART evidence only, not ST67W61M1, Wi-Fi, IP, TCP, TLS, MQTT, or end-to-end network evidence.

Current compile-only ST67W61M1 shield pin preparation maps the Arduino connector labels to the NUCLEO-L4R5ZI-P pins as follows: `D13/PA5 SPI1_SCK`, `D12/PA6 SPI1_MISO`, `D11/PA7 SPI1_MOSI`, `D10/PD14 SPI_CS`, `D5/PE11 CHIP_EN`, `D6/PE9 BOOT`, `D3/PE13 SPI_RDY`, and `D2/PF15 USER_BUTTON`. `SPI_RDY` and the relocated user button share `EXTI15_10_IRQn` but use different EXTI lines, 13 and 15 respectively. The generated 120 MHz clock configuration with SPI1 prescaler 4 is compile-time preparation for an approximately 30 Mbit/s SPI setting when SPI1 is fed from the 120 MHz APB2/PCLK2 domain; hardware behaviour is not claimed from this configuration alone. The generated lwIP application/demo files are kept in the tree for inspection but filtered out of the Phase M5 compile-only CMake path; the project now compiles the CMSIS-RTOS v2 lwIP sys_arch port while runtime networking remains deferred.

The validation model rejects mismatched backend/evidence combinations, fake/no-network configs that name a real broker endpoint, fake-transport settings on non-fake backends, host-side configs without a broker endpoint, unsupported metric names, empty unavailable reasons, invalid fake outcome values, and private-key references in certificate metadata. Certificate references are path references only and must not introduce private keys or credentials.

When MQTT/TLS schema fields are present, the initial result manifest includes an `mqtt_tls` block. The block records the evidence class, backend, TLS mode, broker metadata, metric records, metric summary, limitations, and evidence-boundary flags. Unavailable metrics are first-class records with a source and reason. Fake transport control-flow results are embedded only as simulated fake evidence. This schema does not claim Wi-Fi association, IP address, TCP connection, TLS handshake, MQTT connect, publish, reconnect, latency, throughput, STM32 runtime success, or ST67W61M1-backed success without explicit real evidence.

## Test architecture

```text
tests/unit/          No hardware, SSH, UART, gateway, or real device requirements
tests/integration/   Real local toolchain or gateway checks; skip when unavailable
tests/hardware/      End-to-end board/gateway/UART workflows; capability gated
```

FreeRTOS-specific regression tests are split by evidence source. Unit tests inspect generated CMake, `FreeRTOSConfig.h`, the CubeMX `.ioc`, and application marker ordering. Integration tests build both `Debug` and `RelocatedDebug` presets with the generated FreeRTOS middleware. Hardware tests should continue to assert UART evidence from the direct-flash and secure-boot workflows; FreeRTOS runtime success must come from explicit UART markers such as scheduler-start, task-start, and recurring `tick` output.

The secure-boot algorithm benchmark hardware test is intentionally profile-selective to keep routine runs short. ML-DSA-65 is the default always-on profile. Other algorithm profiles are collected but skipped unless named with `PQC_HARDWARE_SECURE_BOOT_PROFILES`, or unless the full matrix is enabled with `PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES=1`. Capability gates decide whether selected gateway and hardware tests run or skip; command-line `--pqc-require-*` switches are strictness controls, not the normal way to make tests runnable.

Run all tests that can run without gateway access through the default Docker path:

```powershell
.\scripts\dev.ps1 pytest
```

Run strict hardware benchmark workflow through Docker and the SSH gateway only when hardware is intentionally available:

```powershell
.\scripts\dev.ps1 pytest-hardware tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

GitHub Actions CI is defined in `.github/workflows/ci.yml`. It runs on every pushed commit, pull request, and manual dispatch. The workflow preserves the existing runner-compatible jobs and MQTT broker Docker runtime validation, and adds a separate `container-non-hardware` job for the project-owned container workflow.

The containerised job is the default reproducible software-build validation path. The runner-compatible jobs remain as compatibility coverage: they run unit tests, build both CMake firmware presets on the Ubuntu GitHub-hosted runner, run the real wolfBoot build integration test when local tooling and the wolfBoot submodule are available, and then run integration tests with the local-build capability required. The integration job also runs MQTT broker Docker Compose config rendering tests with `docker compose config`, which validate the classical and OQS compose model without deploying to the gateway or running experiment orchestration. The MQTT broker Docker runtime job starts the local classical Mosquitto container, uses temporary test certificates, validates TLS 1.3 mutual authentication, and verifies MQTT publish/subscribe using client certificates.

The default containerised non-hardware job builds the project container image from `docker/python/Dockerfile` and runs the non-hardware checks inside that image: Python unit tests, the safe framework status command, `Debug` and `RelocatedDebug` CMake configure/build, one wolfBoot build profile, relocated ECDSA P-256 application signing, and targeted local-build integration tests for `test_local_build.py` and `test_wolfboot_build_integration.py`. It requires no GitHub Actions secrets; signing material generated during CI is runtime workspace state only and remains covered by the generated-output and secret exclusions.

Gateway and hardware tests remain outside the default CI workflow because they require SSH access, board flashing, UART devices, Docker gateway state, or explicit lab evidence. The experimental OQS runtime path remains covered by explicit gateway validation rather than default GitHub-hosted CI. CI output is portable software-build and local Docker runtime evidence only; it must not be used as hardware, gateway, flashing, UART, production MQTT/TLS, runtime timing, runtime memory, benchmark, or end-to-end device evidence.

## Result ownership

Build records identify produced firmware binaries. Experiment run records identify one execution and its hardware-facing evidence. Secure-boot build/sign/flash evidence remains explicit and profile-specific. Aggregated benchmark summaries are derived outputs from existing manifests.


## ML-DSA secure-boot profiles

The framework includes post-Phase 11 ML-DSA benchmark profiles for `mldsa44` and `mldsa65`. Both use wolfBoot `SIGN=ML_DSA`, the existing relocated HAL payload, the same UART marker model, and the Phase 11 repeated-run/statistics manifest schema. `mldsa44` sets `ML_DSA_LEVEL=2` and `IMAGE_SIGNATURE_SIZE=2420`; `mldsa65` sets `ML_DSA_LEVEL=3` and `IMAGE_SIGNATURE_SIZE=3309`.

`mldsa87` is intentionally not configured as a runnable profile in this change because wolfBoot's ML-DSA example documents `IMAGE_HEADER_SIZE=12288` for the level-5 signature, while the current framework layout reserves 8192 bytes for the image header.

## MQTT broker compose data flow

```text
Docker-hosted framework checkout
  -> local certificate provisioning under experiment/mqtt-broker/runtime/
  -> scp of compose/config/script/runtime files to the gateway
  -> optional scripts/experiment.py mqtt-broker-experiment orchestration
  -> ssh remote Docker Compose start/stop/status/log commands
  -> MQTT-over-TLS broker listener on the gateway
  -> broker-side or host-side MQTT/TLS validation logs and manifest under results/<run_id>/
```

This broker path is broker-side and host-side validation infrastructure. Phase M4 labels broker validation manifests and command output as `host-side/broker-side MQTT/TLS compatibility evidence`, with `host_side` evidence class and explicit false claims for STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, and end-to-end wireless success. It is not STM32 MQTT/TLS client evidence unless a later STM32 firmware phase records explicit board and broker evidence together. The classical profile uses Eclipse Mosquitto with TLS 1.3, client-certificate authentication, and an ACL file. The runner-compatible Docker runtime test exercises this classical container locally from a pytest temporary copy of the compose project, so generated certificates, data, and logs are not written to the repository tree. The experimental OQS profile uses the Open Quantum Safe Mosquitto image for post-quantum TLS protocol evaluation. Each profile overrides the image entrypoint, copies its bind-mounted ACL file to a container-local `/tmp/mosquitto-aclfile`, sets ownership and restrictive permissions for the runtime user there, and configures Mosquitto to read that copy. The top-level `mqtt-broker-experiment` command wraps certificate provisioning, deployment, profile start, validation, broker validation retries during startup, live step progress, bounded per-step subprocess timeouts, log capture even after validation failures, result manifest creation, and optional stop. OQS runtime behaviour must be confirmed with explicit broker/client logs before claiming PQC TLS success.

MQTT broker OQS image compatibility: The startup script creates a runtime-user-owned `/tmp/mosquitto-aclfile` when possible. Images with a `mosquitto` user use `mosquitto`; the current OQS Mosquitto image uses `nobody`, so the OQS config sets `user nobody` and the ACL copy is owned by that runtime user.
