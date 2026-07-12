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
2. STM32-local wolfMQTT build/runtime integration and real wolfSSL transport/handshake integration.
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

Generated-state preflight is the primary compatibility and provenance mechanism for framework build, wolfBoot build, application-signing, and artifact-consuming workflows. Pytest session-start cleanup is supplementary cross-platform hygiene for stale host-specific CMake and wolfBoot object/dependency/host-tool outputs. It does not establish compatibility or provenance and must not remove source files, canonical signing keys under `secrets/wolfboot/`, or reusable wolfBoot signing-tuple members.

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
- Runtime verification metrics describe firmware-reported verification evidence. Verification time, cycles, bootloader HCLK, result code, and marker sources must come from explicit UART markers.
- Runtime memory metrics describe firmware-reported memory evidence. Stack high-water data is valid only when explicit firmware-side stack markers are present. Heap remains unavailable unless explicit heap evidence is added.
- Repeated-run samples record one verification sample per secure-boot reset/capture. Aggregate statistics use only samples marked valid for statistics.
- Derived metrics such as cycles per KB and time per KB are calculated only when the required source values are available.

Median verification time and cycles are the primary headline metrics for cross-profile comparison. Mean, minimum, maximum, standard deviation, range, and coefficient of variation support repeatability and outlier review. Unavailable fields and limitations are intentional evidence and must remain visible in manifests and aggregated summaries.

Profiles should be compared only when they use the same board, relocated HAL payload, bootloader clock evidence model, UART marker model, repeated-run model, image-header reserve, and measurement sources. Timing, stack, heap, or pass/fail status must not be inferred from host-side duration, SSH duration, reset delay, build logs, ELF files alone, or marker ordering alone.

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

Phase M6.2 adds `Core/Inc/pqc_network_interface.h` and `Core/Src/pqc_network_interface.c` as the project-owned boundary between later protocol layers and the future ST67W61M1-backed lwIP netif. The implementation owns an unattached local `struct netif`, clears its IPv4 address, netmask, and gateway with lwIP helpers, then reads `netif_is_up`, `netif_is_link_up`, the lwIP IPv4-any state, and an lwIP-formatted IPv4 string. It maps those observed lwIP values into `link`, `ip`, and `tcp` availability, while transport remains unavailable because no backend exists. The UART line begins with `lwIP network interface:` and is labelled `evidence=lwip-netif-state-only`; it reports both the raw lwIP observations and the mapped unavailable states. Wi-Fi module, ST67W61M1, TLS handshake, MQTT connect, MQTT publish, reconnect, and end-to-end status remain unavailable. It does not call `netif_add`, set link or interface state up, start DHCP, open TCP, invoke wolfSSL, invoke wolfMQTT, or access ST67W61M1 hardware. This boundary is intended for later wolfSSL transport and wolfMQTT work without coupling those layers directly to the Wi-Fi driver.

Phase M6 adds a STM32-local wolfSSL source build-only boundary through `Core/Inc/pqc_wolfssl_build_only.h`, `Core/Src/pqc_wolfssl_build_only.c`, `Core/Inc/user_settings.h`, and `Core/Inc/pqc_wolfssl_user_settings.h`. The CMake target `pqc_wolfssl_stm32_build_only` builds the minimal wolfCrypt SHA-256 source file from `tools/wolfboot/lib/wolfssl/wolfcrypt/src/sha256.c` and links it into the direct and relocated firmware builds. The firmware smoke helper computes SHA-256 over a fixed non-secret message and can emit `wolfSSL build-only smoke:` UART evidence with `source=enabled`, `sha256=ok`, `tls_handshake=unavailable`, `transport=unavailable`, `certs=not-loaded`, and `secrets=not-compiled-in`. This proves only that the configured wolfSSL/wolfCrypt source path built, linked, and executed. It does not create a wolfSSL context, open TCP, load certificates or private keys, perform a TLS handshake, or perform MQTT work. Private keys, real credentials, private certificates, and production TLS material must remain outside source files, result artifacts, documentation, and replacement archives. The Phase M6 evidence class remains STM32 build-only evidence plus capability-gated UART smoke evidence; TLS handshake, runtime transport, certificate-store, MQTT, Wi-Fi, ST67W61M1, and end-to-end network metrics remain unavailable until later phases provide explicit transport and runtime evidence.

Phase M6.3 adds `Core/Inc/pqc_wolfssl_transport.h` and `Core/Src/pqc_wolfssl_transport.c` as a project-owned boundary between wolfSSL and the future lwIP/ST67W61M1 path. The boundary exposes unavailable connect, read, and write wrappers plus callback-shaped receive and send entry points. It reads the Phase M6.2 `PQC_NetworkInterfaceStatus` only to bind the layers architecturally; it does not register a live lwIP netif, create a socket, connect TCP, register callbacks on a `WOLFSSL` session, create a TLS session, load certificates, perform a TLS handshake, invoke MQTT, or access Wi-Fi hardware. All operations return explicit unavailable status and zero transferred bytes. Firmware emits `wolfSSL transport boundary:` with `evidence=unavailable-transport-only`, `socket_io=not-performed`, and unavailable connect/read/write/TLS/MQTT/Wi-Fi/ST67W61M1/end-to-end fields.


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


## Deferred test coverage — Phase M6.1 wolfSSL TLS context lifecycle

The Phase M6.1 implementation includes static unit coverage and existing direct/relocated local-build integration coverage. A dedicated gateway-mediated hardware test that flashes the known Phase M6.1 image and asserts the `wolfSSL TLS context smoke:` UART marker is deferred because the supplied test context only included the ad hoc monitor test, which does not flash a known image before capture. Complete this when the baseline build/flash/UART result helper is supplied or extended. The future verification command should be `./scripts/dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware`, with the test requiring `evidence=tls-context-lifecycle-only`, `client_ctx=created`, and all handshake/certificate/transport/MQTT/Wi-Fi/ST67W61M1 fields to remain unavailable.


## Deferred test coverage — Phase M6.2 lwIP network-interface boundary

The Phase M6.2 implementation includes static unit coverage and the existing direct/relocated local-build integration coverage. A dedicated gateway-mediated hardware test that flashes a known Phase M6.2 image and asserts the `lwIP network interface:` UART marker is deferred because the supplied hardware test only monitors the currently running image and does not build or flash a known artifact before capture. Complete this when the baseline known-image build/flash/UART helper is supplied or extended. The future verification command should be `./scripts/dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware`, with the test requiring `evidence=lwip-netif-state-only`, `boundary=present`, raw lwIP observations showing netif down, link down, and an unspecified IPv4 address, and link, IP, TCP, transport, Wi-Fi module, ST67W61M1, TLS handshake, MQTT connect, MQTT publish, reconnect, and end-to-end fields to remain unavailable.


### wolfBoot signing-key and generated-keystore lifecycle

The wolfBoot build wrapper treats the canonical private key, matching wolfBoot-local
private key, generated public key, and generated `src/keystore.c` as one reusable
local signing tuple. Its lifecycle is explicit:

- **Completely absent tuple:** when no tuple member exists, the owning workflow may
  create a new local benchmark tuple if the selected profile permits generation.
- **Complete matching tuple:** when all members exist and the private-key
  fingerprints match, the tuple is preserved and reused unchanged.
- **Partially missing tuple:** when only some members exist, the workflow fails
  before invoking `make`; it does not reconstruct a public key or keystore from
  the remaining private key.
- **Mismatched tuple:** when canonical and wolfBoot-local private-key fingerprints
  differ, the workflow fails before invoking `make`; it does not overwrite the
  canonical key or silently rotate either key.

A deliberate local benchmark-key rotation requires explicit operator action and
invalidates compatibility with artifacts signed by the previous tuple. Routine
preflight and cleanup must never perform that rotation.

## Phase M6.2.1 — Generated Build-State Isolation and Stale-Artifact Preflight

Framework commands that create or consume generated firmware, wolfBoot, and signed-image artifacts use `scripts/framework/generated_state.py`. The module stores project-owned scope manifests under `.pqc-generated-state/scopes/` and binds generated state to the workflow, profile, source/config fingerprint, toolchain command identity, host/container identity, and applicable signing-key tuple.

Before a build or signing command starts, the preflight compares the current identity with the last successful scope record. Demonstrably compatible state may be retained. Missing, malformed, cross-profile, cross-toolchain, or cross-host/container state causes deterministic cleanup of only the configured generated paths and stale final artifacts. Cleanup refuses paths outside the repository and refuses all paths under `secrets/`. CubeMX-generated source folders are not moved or deleted.

STM32 CMake builds use profile-scoped `build/<preset>/` directories. wolfBoot retains its upstream source layout, so the framework records a project-owned scope manifest and cleans only known host-tool outputs and final build artifacts. The wolfBoot-local private key, generated public key, and generated `src/keystore.c` are treated as one tuple; an incomplete or mismatched tuple is not silently repaired from an existing private key. Canonical keys under `secrets/wolfboot/` are never preflight cleanup targets.

Successful commands write artifact hashes and references to their build or signing records. The canonical normal signing path first creates the relocated ELF through the framework `experiment build` command with `RelocatedDebug`, so application signing can require that ELF to match a successful CMake generated-state record. Direct wrapped CMake remains a diagnostic fallback only and does not create the framework provenance required by downstream signing. Secure-boot flashing requires the wolfBoot ELF and original signed application to match successful wolfBoot-build and application-signing records; filesystem existence alone is insufficient. A failed command does not write a success record, and stale final artifacts are removed before execution so they cannot be mistaken for new output.

The canonical non-hardware MQTT/TLS phase plan is `docs/non_hardware_mqtt_tls_development_plan.md`.

### Deferred test coverage

No hardware test is added for Phase M6.2.1 because the behavior is framework-side artifact selection and preflight, not a firmware-runtime feature. Existing capability-gated flashing tests should validate provenance refusal before gateway access when their fixtures are updated to create successful build/signing records. Verification command: `./scripts/dev.ps1 pytest-hardware tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware`.

### Phase M6.2.1 secure-boot hardware profile selection and tuple preservation

The secure-boot algorithm benchmark hardware test now implements the documented profile-selection environment variables. ML-DSA-65 is selected by default. `PQC_HARDWARE_SECURE_BOOT_PROFILES` adds named profiles to that default, and `PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES=1` selects the complete matrix. Unselected parameter cases are collected but skipped with an explicit reason.

Hardware-test preparation must not call wolfBoot `keysclean` and pytest startup cleanup must not remove `wolfboot_signing_private_key.der`, `wolfboot_signing_public_key.der`, or `src/keystore.c`. Those files form reusable local signing state with the canonical key and are validated by the framework preflight. The hardware test removes only its directly managed relocated CMake output; wolfBoot stale-output handling remains owned by `build-wolfboot` generated-state preflight.


## Deferred test coverage — Phase M6.3 wolfSSL unavailable transport boundary

The Phase M6.3 implementation includes static unit coverage and existing direct/relocated local-build integration coverage. A dedicated gateway-mediated hardware test that flashes a known Phase M6.3 image and asserts the `wolfSSL transport boundary:` UART marker is deferred because the supplied hardware test only monitors the currently running image and does not build or flash a known artifact before capture. Complete this when the baseline known-image build/flash/UART helper is supplied or extended. The future verification command should be `./scripts/dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware`, with the test requiring `evidence=unavailable-transport-only`, `boundary=present`, `callbacks=present`, `network_boundary=present`, `socket_io=not-performed`, and connect, read, write, TLS handshake, certificates, MQTT connect, MQTT publish, reconnect, Wi-Fi, ST67W61M1, and end-to-end fields to remain unavailable.



### Application handoff ordering and runtime memory checkpoints

After wolfBoot verifies the signed image and transfers control, the application initializes only the hardware required to expose UART evidence. The first application UART output is the preserved wolfBoot mailbox block: raw verification cycles, bootloader SYSCLK/HCLK/PCLK values, verification result, and wolfBoot stack evidence. The secure-boot application marker and other application initialization markers follow that mailbox evidence. This output ordering does not imply that application code ran before verification; the mailbox is populated by wolfBoot and printed only after verified handoff.

Application clock evidence is emitted from the running FreeRTOS default task after the scheduler starts. It records HAL-reported SYSCLK, HCLK, PCLK1, and PCLK2 separately from the bootloader clock evidence. The application HCLK must not be used to derive wolfBoot verification time.

Application memory evidence uses bounded UART checkpoints rather than configuration values alone. The current checkpoints are `pre_scheduler`, `default_task_start`, and `default_task_runtime`. Each records FreeRTOS heap total, current free heap, minimum-ever free heap, derived current used heap, and derived peak used heap. Task-stage checkpoints additionally record the default task's configured stack bytes, stack high-water bytes, and derived used bytes. The pre-scheduler checkpoint reports task-stack fields as unavailable because no task is executing at that point.

FreeRTOS heap evidence covers only allocations managed by the configured FreeRTOS heap implementation. Default-task stack evidence covers only that task at the named checkpoint. wolfBoot verification stack evidence remains a separate metric and must not be merged with application task-stack evidence. Configured heap size, configured task stack size, linker sections, host timing, and UART duration are not runtime usage measurements by themselves.

### Phase M6.4 secure-boot timing clock evidence

Secure-boot verification timing uses the DWT cycle counter as the primary firmware-side evidence. The wolfBoot instrumentation mailbox records raw elapsed cycles, verification result, stack high-water evidence, and bootloader clock values derived from the active STM32 RCC register model: SYSCLK, HCLK, PCLK1, and PCLK2. Firmware does not convert cycles to milliseconds and does not report a hard-coded CPU frequency.

The framework may derive `derived_verification_time_ms` as `verification_cycles * 1000 / hclk_hz` only when both explicit UART values are present. The manifest records `derived_time_clock_source: hclk_hz` and keeps the raw cycles and reported clocks separate. This derived value is not RTC, wall-clock, host-duration, UART-latency, or independently calibrated timing evidence. Hardware assertions remain capability-gated and require explicit UART/manifest evidence.


### Phase M6.5 FreeRTOS task-context runtime smoke

The deterministic lwIP helper smoke and wolfSSL/wolfCrypt TLS-context lifecycle smoke now have two explicit execution contexts. `main()` emits the existing early evidence with `context=pre_scheduler scheduler=not_started`. After `osKernelStart()` transfers control and `defaultTask` emits its task-start marker, the task runs the same local checks once and emits `context=freertos_task scheduler=running`. Hardware evidence is valid only when the task-start marker precedes both task-context smoke markers in the captured UART log.

The task-context path remains local and serialized. It does not register or bring up a lwIP netif, use Wi-Fi or ST67W61M1 hardware, report link-up or IP assignment, open TCP, load certificates, create a TLS session, perform a TLS handshake, connect or publish MQTT, reconnect, or claim end-to-end network success. wolfSSL FreeRTOS mutex or multithreaded support is not enabled because no concurrent wolfSSL use is introduced. The capability-gated secure-boot benchmark hardware test verifies marker ordering using a known built and flashed image; the ad hoc baseline monitor remains intentionally unable to assert one-shot task startup markers because it does not flash a known image.


## Phase M6.6 STM32-local lwIP UDP loopback

Phase M6.6 adds `Core/Inc/pqc_lwip_loopback.h` and `Core/Src/pqc_lwip_loopback.c`. The one-shot smoke runs from `defaultTask` after the FreeRTOS scheduler has started. It initializes the lwIP TCP/IP core, creates a local IPv4 UDP PCB, binds a fixed high port, sends a deterministic payload to `127.0.0.1`, and verifies the received length and bytes through the lwIP loop interface. The smoke is serialized with the existing task-context checks and uses lwIP core locking for raw UDP API access outside the TCP/IP thread.

The UART marker begins with `lwIP local loopback smoke:` and labels the evidence as `stm32-local-lwip-loopback-only`. A passing marker requires `result=passed`, `sent=1`, `received=1`, and `payload_match=1`. This is internal STM32/lwIP runtime evidence only. It does not prove ST67W61M1 detection, Wi-Fi association, link-up, address acquisition from hardware, external ping, external TCP connectivity, broker access, TLS handshake, MQTT connect, MQTT publish, reconnect, or end-to-end network success. Those fields remain explicitly unavailable in the marker.

The baseline hardware test includes a capability-gated known-image build/flash/UART path for this marker. The ordinary monitor-only test remains non-assertive because it cannot establish which firmware image is already running. The M6.6 implementation does not add manifest fields: the current baseline `run` manifest records UART pass/fail evidence, while the detailed local-loopback evidence remains in `uart.log`. A future structured UART-evidence ingestion phase may promote these fields into the manifest without changing their local-only meaning.


## Phase M7 — wolfMQTT build-only skeleton

Phase M7 adds wolfMQTT as the dedicated `Middlewares/Third_Party/wolfMQTT` Git submodule and builds its core client, packet, and socket-callback sources into both STM32 firmware profiles. `Core/Inc/pqc_wolfmqtt_build_only.h` and `Core/Src/pqc_wolfmqtt_build_only.c` provide the project-owned integration boundary. The boundary uses wolfMQTT's native `MqttNet` callbacks and exposes backend selection independently from MQTT client initialization. The current selectable implementation is `fake_no_network`; the `st67w61m1` value is reserved and rejected until its later hardware-backed phase.

The build-only initializer constructs an unavailable `MqttNet`, calls `MqttClient_Init`, and deinitializes the client. It does not call network connect, MQTT CONNECT, publish, subscribe, wait-message, TLS, socket, lwIP external transport, or Wi-Fi APIs. No UART marker is emitted and no runtime success is claimed in Phase M7. Broker connection, TLS handshake, publish, reconnect, Wi-Fi, ST67W61M1, and end-to-end states remain unavailable.

### Phase M8 — STM32 fake/no-network wolfMQTT runtime evidence

Phase M8 reuses the Phase M7 integration boundary rather than adding a second MQTT client path. A serialized one-shot call runs from `defaultTask` after the scheduler starts, selects `fake_no_network`, constructs the unavailable `MqttNet`, calls `MqttClient_Init`, and deinitializes the client without invoking network connect, MQTT CONNECT, publish, subscribe, wait-message, TLS, socket, lwIP external transport, or Wi-Fi APIs.

The UART marker begins with `wolfMQTT runtime smoke:` and is labelled `evidence=stm32-fake-no-network-initialization-only`. It records the FreeRTOS task context, backend, initializer result, client-initialized state, and callback presence. Transport, Wi-Fi, link, IP, TCP, TLS handshake, MQTT connect, MQTT publish, reconnect, ST67W61M1, and end-to-end status remain explicitly unavailable. This is initialization evidence from the STM32 board only; it is not broker or network evidence.

Static unit coverage validates invocation, marker wording, backend selection, unavailable claims, and the continued absence of protocol/network calls. Existing local-build integration coverage compiles both `Debug` and `RelocatedDebug`. The capability-gated known-image hardware test builds, flashes, captures UART, and verifies that the Phase M8 marker occurs after `defaultTask` starts. Detailed evidence remains in `uart.log`; no new manifest field is introduced. Verify with `./scripts/dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware`.

### Phase M9 host wolfMQTT/wolfSSL compatibility boundary

`experiment/mqtt-broker/host-wolfmqtt/CMakeLists.txt` defines a separate native-host build. It compiles the pinned wolfMQTT core and upstream MQTT client/network example sources and links them to the wolfSSL source carried by the wolfBoot submodule. This target is intentionally separate from the Arm/STM32 CMake presets and from `pqc_wolfmqtt_stm32_build_only`.

`experiment/mqtt-broker/scripts/host_wolfmqtt_validate.py` configures and builds the native executable and can pass arguments through to the upstream wolfMQTT client. Before invoking the client it emits an explicit `host_side` evidence label and false claims for STM32, Wi-Fi-module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, and end-to-end wireless success. Optional JSON output preserves the same boundary. The utility may target the local or gateway-hosted classical broker, but gateway and broker availability remain capability requirements rather than assumptions.

The canonical broker definition is `experiment/mqtt-broker/compose.yaml`. Phase M4 Mosquitto/OpenSSL checks and Phase M9 wolfMQTT/wolfSSL checks are complementary host-side paths. Neither is firmware evidence.

#### Deferred test coverage

- **Phase M9 gateway wolfMQTT/wolfSSL live validation — gateway integration layer:** the supplied implementation provides the host client, native build integration test, and command path, but a deterministic gateway run requires available gateway connectivity plus provisioned temporary broker certificates. Verify when that capability is intentionally enabled with `./scripts/dev.ps1 pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e.py -m integration --pqc-require-gateway`, followed by the documented `host_wolfmqtt_validate.py run` command against the gateway endpoint. Evidence must remain `host_side`.


#### Phase M9 PowerShell client-argument boundary

The host validation wrapper accepts upstream wolfMQTT arguments after `--client-args`. This named boundary is the documented command contract because `scripts/dev.ps1` is an advanced PowerShell script. Each dash-prefixed wolfMQTT argument must be quoted individually when invoked through PowerShell so it is forwarded as data rather than bound as a `dev.ps1` parameter. Active PowerShell guidance does not use a standalone `--` forwarding path.


#### Phase M9 structured runtime evidence

The host validation utility captures the wolfMQTT client output and records individual TLS/MQTT success markers in the JSON result. `broker_compatibility_confirmed` is true only when the process exits successfully and explicit markers confirm TLS socket connection, MQTT connection acknowledgement, subscription, successful publish, message receipt, MQTT disconnect, and socket disconnect. A zero process exit code alone is insufficient.
