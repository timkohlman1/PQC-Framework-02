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
11. Post-secureboot application scheduler template using CMSIS-RTOS v1 FreeRTOS.
12. Gateway MQTT broker Docker Compose project with classical MQTT-over-TLS and an experimental OQS Mosquitto profile.
13. Containerised baseline with Python validation, STM32 direct/relocated local CMake builds, wolfBoot builds, application signing, and explicitly opt-in gateway-capable integration checks.

Planned but not implemented:

1. CI container integration.
2. STM32 MQTT client firmware integration.
3. TLS/wolfSSL transport experiments.
4. Hybrid signing profiles and ML-DSA-87 under the current 8192-byte image-header reserve.
5. Network degradation automation.
6. Production release packaging.

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



## Containerised build/test baseline

The repository includes a container baseline for portable framework validation before STM32 MQTT client firmware, lwIP, wolfSSL, and wolfMQTT implementation work. The container definition is `docker/python/Dockerfile`; Python development dependencies are in `requirements-dev.txt`; generated outputs and local secret material are excluded from the build context by `.dockerignore`.

The default container command still runs Python unit tests. The container also includes the local STM32 build dependencies needed to configure and build the existing `Debug` and `RelocatedDebug` CMake presets, host build tooling needed for wolfBoot/keytools builds, OpenSSL for local certificate provisioning, an SSH client for runtime-provided gateway access, and the tooling needed to run local application-signing profiles after the relocated application has been built. Local-build, wolfBoot, gateway, broker, and hardware tests use capability detection: a plain `python -m pytest` run exercises available capabilities and skips unavailable ones. Strict flags still convert unavailable capabilities into failures when an intentional capability-specific check is required.

Supported default evidence is limited to portable software validation: Python test results, safe configuration-validation command output, STM32 local build output for direct and relocated firmware profiles, wolfBoot build evidence, and application-signing evidence. Containerised build/signing evidence must not be treated as hardware, gateway, flashing, UART, MQTT/TLS, timing, memory, benchmark, or end-to-end runtime success. Those claims still require explicit logs, manifests, or equivalent evidence from the relevant hardware or gateway workflow.

Application signing inside the container uses the runtime-mounted workspace. Private signing keys and generated signing material must remain local generated state, such as under `secrets/wolfboot/`, and must not be committed, sent in build contexts, copied into replacement artifacts, or baked into images. The container includes an SSH client but no SSH keys, VPN keys, broker credentials, private certificates, private signing keys, or other secrets. Gateway-capable checks are disabled by default inside the container and require `PQC_CONTAINER_ENABLE_GATEWAY=1` plus runtime-provided SSH configuration, known-hosts data, and credentials. UART access, MQTT broker validation, ST-LINK/USB access, Wi-Fi-module access, flashing support, and hardware-test support remain capability-gated.

Pytest performs generated-artifact cleanup at session start inside the container, and on native hosts when stale foreign build paths are detected. The cleanup scope is limited to generated `build/Debug`, `build/RelocatedDebug`, wolfBoot artifacts, `.config`, and wolfBoot object/dependency/host-tool outputs. It prevents CMake cache and wolfBoot dependency files from reusing absolute paths from a different build host while preserving source files and canonical signing keys under `secrets/wolfboot/`.

## Firmware scheduler model

The application firmware uses the CubeMX-generated CMSIS-RTOS v1 FreeRTOS template. `main()` performs HAL initialization, clock configuration, GPIO/UART initialization, and one-time UART evidence marker output before `osKernelStart()`. It also emits FreeRTOS scheduler markers for default task creation and scheduler start. `StartDefaultTask()` emits a task-start marker before it owns the recurring `tick` marker and LED toggle using `osDelay(1000)`. HAL timing is generated from TIM6 rather than SysTick so the FreeRTOS scheduler can own SysTick.

The direct-flash and secure-boot application markers remain part of the UART evidence contract. FreeRTOS task-level stack APIs are enabled for future task instrumentation, but task-level runtime stack/heap values must still be treated as unavailable until explicit firmware markers and manifests record them.

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

## Test architecture

```text
tests/unit/          No hardware, SSH, UART, gateway, or real device requirements
tests/integration/   Real local toolchain or gateway checks; skip when unavailable
tests/hardware/      End-to-end board/gateway/UART workflows; capability gated
```

FreeRTOS-specific regression tests are split by evidence source. Unit tests inspect generated CMake, `FreeRTOSConfig.h`, the CubeMX `.ioc`, and application marker ordering. Integration tests build both `Debug` and `RelocatedDebug` presets with the generated FreeRTOS middleware. Hardware tests should continue to assert UART evidence from the direct-flash and secure-boot workflows; FreeRTOS runtime success must come from explicit UART markers such as scheduler-start, task-start, and recurring `tick` output.

The secure-boot algorithm benchmark hardware test is intentionally profile-selective to keep routine runs short. ML-DSA-65 is the default always-on profile. Other algorithm profiles are collected but skipped unless named with `PQC_HARDWARE_SECURE_BOOT_PROFILES`, or unless the full matrix is enabled with `PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES=1`. Capability gates decide whether selected gateway and hardware tests run or skip; command-line `--pqc-require-*` switches are strictness controls, not the normal way to make tests runnable.

Run all tests that can run on the current machine:

```powershell
python -m pytest
```

Run strict hardware benchmark workflow only when hardware is intentionally available:

```powershell
python -m pytest tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

GitHub Actions CI is defined in `.github/workflows/ci.yml`. It runs on every pushed commit and pull request, checks unit tests first, builds both local CMake firmware presets that can run on an Ubuntu GitHub-hosted runner, runs the real wolfBoot build integration test when local tooling and the wolfBoot submodule are available, and then runs integration tests with the local-build capability required. The integration job also runs MQTT broker Docker Compose config rendering tests with `docker compose config`, which validate the classical and OQS compose model without deploying to the gateway or running experiment orchestration. A separate MQTT broker Docker runtime job starts the local classical Mosquitto container, uses temporary test certificates, validates TLS 1.3 mutual authentication, and verifies MQTT publish/subscribe using client certificates. Gateway and hardware tests remain outside the default CI workflow because they require SSH access, board flashing, UART devices, Docker gateway state, or explicit lab evidence. The experimental OQS runtime path remains covered by explicit gateway validation rather than default GitHub-hosted CI.

## Result ownership

Build records identify produced firmware binaries. Experiment run records identify one execution and its hardware-facing evidence. Secure-boot build/sign/flash evidence remains explicit and profile-specific. Aggregated benchmark summaries are derived outputs from existing manifests.


## ML-DSA secure-boot profiles

The framework includes post-Phase 11 ML-DSA benchmark profiles for `mldsa44` and `mldsa65`. Both use wolfBoot `SIGN=ML_DSA`, the existing relocated HAL payload, the same UART marker model, and the Phase 11 repeated-run/statistics manifest schema. `mldsa44` sets `ML_DSA_LEVEL=2` and `IMAGE_SIGNATURE_SIZE=2420`; `mldsa65` sets `ML_DSA_LEVEL=3` and `IMAGE_SIGNATURE_SIZE=3309`.

`mldsa87` is intentionally not configured as a runnable profile in this change because wolfBoot's ML-DSA example documents `IMAGE_HEADER_SIZE=12288` for the level-5 signature, while the current framework layout reserves 8192 bytes for the image header.

## MQTT broker compose data flow

```text
build server repository checkout
  -> local certificate provisioning under experiment/mqtt-broker/runtime/
  -> scp of compose/config/script/runtime files to the gateway
  -> optional scripts/experiment.py mqtt-broker-experiment orchestration
  -> ssh remote Docker Compose start/stop/status/log commands
  -> MQTT-over-TLS broker listener on the gateway
  -> MQTT/TLS validation logs and manifest under results/<run_id>/
```

The classical profile uses Eclipse Mosquitto with TLS 1.3, client-certificate authentication, and an ACL file. The runner-compatible Docker runtime test exercises this classical container locally from a pytest temporary copy of the compose project, so generated certificates, data, and logs are not written to the repository tree. The experimental OQS profile uses the Open Quantum Safe Mosquitto image for post-quantum TLS protocol evaluation. Each profile overrides the image entrypoint, copies its bind-mounted ACL file to a container-local `/tmp/mosquitto-aclfile`, sets ownership and restrictive permissions for the runtime user there, and configures Mosquitto to read that copy. The top-level `mqtt-broker-experiment` command wraps certificate provisioning, deployment, profile start, validation, broker validation retries during startup, live step progress, bounded per-step subprocess timeouts, log capture even after validation failures, result manifest creation, and optional stop. OQS runtime behaviour must be confirmed with explicit broker/client logs before claiming PQC TLS success.

MQTT broker OQS image compatibility: The startup script creates a runtime-user-owned `/tmp/mosquitto-aclfile` when possible. Images with a `mosquitto` user use `mosquitto`; the current OQS Mosquitto image uses `nobody`, so the OQS config sets `user nobody` and the ACL copy is owned by that runtime user.
