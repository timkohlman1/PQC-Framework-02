# PQC-Framework-02

STM32-based embedded security experiment framework for direct-flash baseline experiments, wolfBoot secure-boot experiments, and secure-boot benchmark collection.

## Current implementation

The repository currently contains:

- a CubeMX-generated STM32 HAL/FreeRTOS firmware project for the NUCLEO-L4R5ZI-P / STM32L4R5 board
- direct-flash baseline build, flash, UART, and run workflows
- first-class build records and source/build fingerprinting
- a relocated HAL/FreeRTOS application build for wolfBoot launch
- wolfBoot build profiles using the local `tools/wolfboot` submodule
- application-signing profiles for classical wolfBoot algorithms and ML-DSA-44/ML-DSA-65
- secure-boot flash, UART evidence, negative-test, repeated-run, and benchmark workflows
- benchmark aggregation to JSON and CSV
- an MQTT broker Docker Compose project under `experiment/mqtt-broker/` with classical MQTT-over-TLS and an experimental OQS Mosquitto profile for post-quantum TLS experiments
- an MQTT/TLS roadmap that separates hardware-independent STM32-local lwIP/wolfSSL/wolfMQTT preparation from future ST67W61M1-backed wireless validation
- a Docker-hosted Linux default workflow for Python validation, STM32 direct/relocated builds, wolfBoot builds, application signing, pytest, and gateway-mediated hardware experiments

Not implemented yet: STM32 MQTT client firmware runtime integration, real lwIP network-interface integration, STM32-local wolfSSL/wolfMQTT integration, ST67W61M1 network-interface backend validation, production PQC TLS deployment, hybrid algorithm profiles, ML-DSA-87 under the current 8192-byte image-header reserve, network-degradation automation, and production release packaging.

Hardware success, gateway success, UART evidence, timing values, memory values, and benchmark values must only be claimed from explicit logs or manifests.

## Key files

```text
AI_BUILD_GUIDE.md                         Compact source-of-truth for AI-assisted changes
README.md                                 User-facing overview and command reference
docs/007_framework_architecture.md        Current architecture and file map
docs/008_chatgpt_project_prompt.md        Project prompt for feature-development chats
configs/                                  Board, host, boot, build, signing, experiment, benchmark configs
scripts/experiment.py                     CLI entry point
scripts/framework/                        Framework implementation modules
tests/                                    Unit, integration, and hardware tests
Middlewares/                               CubeMX-generated FreeRTOS middleware
results/                                  Generated experiment evidence; ignored except .gitkeep
tools/wolfboot/                           Local wolfBoot submodule; generated outputs ignored
```

## Common commands

The default development path is Docker-hosted Linux execution through the project wrapper scripts. The development machine should provide Docker and runtime-mounted SSH access for gateway workflows; it should not need local STM32/CMake/Ninja/Arm GCC/Python pytest tooling for normal framework use.

Build or refresh the project image from the repository root:

```powershell
.\scripts\dev.ps1 build-image
```

Equivalent raw Docker command:

```powershell
docker build -f docker/python/Dockerfile -t pqc-framework-stm32-build .
```

Run all tests that can run without gateway access. Integration and hardware tests skip when capabilities are unavailable:

```powershell
.\scripts\dev.ps1 pytest
```

Run unit tests only:

```powershell
.\scripts\dev.ps1 pytest tests/unit
```

Equivalent raw Docker command, retained for compatibility with container baseline checks:

```powershell
docker run --rm -v ${PWD}:/workspace -w /workspace pqc-framework-stm32-build python -m pytest tests/unit
```

Check the direct-flash baseline config inside the container:

```powershell
.\scripts\dev.ps1 experiment status --experiment configs/experiments/baseline_direct_uart.yaml
```

Build the direct-flash baseline inside the container:

```powershell
.\scripts\dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml
```

Run the full direct-flash baseline workflow through Docker and the SSH gateway:

```powershell
.\scripts\dev.ps1 experiment-gateway run --experiment configs/experiments/baseline_direct_uart.yaml
```

Use an existing first-class build record for the direct-flash run through Docker and the SSH gateway:

```powershell
.\scripts\dev.ps1 experiment-gateway run --experiment configs/experiments/baseline_direct_uart.yaml --build-number <number>
```

Monitor UART through Docker and the SSH gateway:

```powershell
.\scripts\dev.ps1 experiment-gateway monitor --experiment configs/experiments/baseline_direct_uart.yaml --duration-seconds 10
.\scripts\dev.ps1 experiment-gateway monitor --experiment configs/experiments/baseline_direct_uart.yaml --restart
```

On Linux or macOS, use the equivalent shell wrapper:

```bash
./scripts/dev.sh build-image
./scripts/dev.sh pytest tests/unit
./scripts/dev.sh experiment status --experiment configs/experiments/baseline_direct_uart.yaml
./scripts/dev.sh experiment-gateway run --experiment configs/experiments/baseline_direct_uart.yaml
```

Host-native commands remain available as an explicit fallback for manual diagnosis, but they are no longer the documented default path.

## Containerised build/test/experiment environment

The Docker-hosted Linux workflow is the default path for framework commands, firmware builds, wolfBoot builds, signing, pytest, and gateway-mediated hardware experiments. Hardware access remains gateway-mediated over SSH/SCP: the container runs the framework on the development machine, then connects to `pqc-gateway1` to execute the configured flash/reset/UART helper commands. The container does not require direct UART devices, ST-LINK/USB passthrough, Wi-Fi-module passthrough, committed credentials, or host-installed STM32 build tools.

Gateway, UART, broker, flashing, and hardware workflows remain capability-gated. Inside the container, gateway probing is disabled unless `PQC_CONTAINER_ENABLE_GATEWAY=1` is set and SSH configuration is supplied at runtime. The wrapper scripts set this flag for `experiment-gateway`, `pytest-gateway`, and `pytest-hardware`, and mount the host SSH directory read-only before copying it into the temporary container filesystem with Linux permissions for that single run.

Pytest cleans generated cross-platform build state at session start when running inside the container. It removes generated `build/Debug`, `build/RelocatedDebug`, and wolfBoot object/dependency/tool outputs that can contain host-specific absolute paths after switching between Windows-native and Linux-container builds. It does not remove source files or canonical signing keys under `secrets/wolfboot/`. Set `PQC_SKIP_CONTAINER_GENERATED_BUILD_CLEANUP=1` to suppress this default container cleanup, or use `--pqc-clean-generated-build-artifacts`/`PQC_CLEAN_GENERATED_BUILD_ARTIFACTS=1` to request the cleanup explicitly in any environment.

Build the image from the repository root:

```powershell
.\scripts\dev.ps1 build-image
```

Run unit tests in the container with the repository mounted at runtime:

```powershell
.\scripts\dev.ps1 pytest tests/unit
```

Run the full capability-gated pytest suite in the container without gateway access:

```powershell
.\scripts\dev.ps1 pytest
```

Run the hardware test suite through Docker and the SSH gateway:

```powershell
.\scripts\dev.ps1 pytest-hardware
```

Run a safe framework command that loads and validates the direct-flash experiment configuration without building, flashing, opening UART, using SSH, or contacting a broker:

```powershell
.\scripts\dev.ps1 experiment status --experiment configs/experiments/baseline_direct_uart.yaml
```

Equivalent raw Docker command, retained for compatibility with container baseline checks:

```powershell
docker run --rm -v ${PWD}:/workspace -w /workspace pqc-framework-stm32-build python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
```

Build the direct-flash firmware preset inside the container:

```powershell
.\scripts\dev.ps1 cmake --preset Debug
.\scripts\dev.ps1 cmake --build --preset Debug
```

Build the relocated firmware preset inside the container:

```powershell
.\scripts\dev.ps1 cmake --preset RelocatedDebug
.\scripts\dev.ps1 cmake --build --preset RelocatedDebug
```

Build one wolfBoot profile inside the container:

```powershell
.\scripts\dev.ps1 experiment build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
```

Sign the relocated application inside the container after the relocated build exists. The signing workflow uses `secrets/wolfboot/` from the runtime-mounted workspace and may locally generate missing profile keys there; those files remain host-local generated material and must not be committed or baked into the image:

```powershell
.\scripts\dev.ps1 experiment sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
```

Run the local-build and wolfBoot integration tests inside the container. They use capability detection and skip when required in-container tooling or the wolfBoot submodule is unavailable:

```powershell
.\scripts\dev.ps1 pytest tests/integration -m integration
```

Run gateway-capable integration checks through Docker with runtime-mounted SSH material:

```powershell
.\scripts\dev.ps1 pytest-gateway tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
```

The default SSH mount source is `${env:USERPROFILE}\.ssh` on PowerShell and `$HOME/.ssh` on POSIX shells. Set `PQC_DOCKER_SSH_DIR` to use a different host-side SSH directory. Set `PQC_DOCKER_IMAGE` to use a different image tag.

The container provides portable software-build and signing evidence by default. Gateway, flashing, UART, broker, hardware, benchmark/runtime, and end-to-end runtime evidence may only be claimed when the relevant capability-gated tests or experiment commands run and produce explicit logs or manifests.

The `.dockerignore` file excludes generated outputs and local secret material from the image build context. Private signing keys, SSH keys, VPN keys, TLS private keys, MQTT passwords, real `.env` files, private certificates, generated wolfBoot signing material, and production credentials must not be committed or baked into images.

## Docker-default migration status

The containerisation track is now the default development path. Phase C2 established the Python baseline. Phase C3 added STM32 direct and relocated CMake builds plus the relevant integration tests. Phase C4 added wolfBoot build and relocated application-signing support with runtime-mounted or locally generated signing material only. Phase C5 added gateway-capable integration with runtime-provided SSH access and generated-artifact cleanup for Windows/container build switching. Phase C6 added GitHub Actions containerised non-hardware checks while preserving the existing runner-compatible and MQTT broker Docker runtime CI jobs as compatibility coverage. The host-native development-machine build path remains available only as a manual fallback.

## Firmware scheduler model

The STM32 application is CubeMX-generated HAL firmware with a CMSIS-RTOS v2 FreeRTOS template. Startup and secure-boot evidence markers are emitted after peripheral initialization and before `osKernelStart()`. The application also emits explicit FreeRTOS markers when `defaultTask` is created, when the scheduler is about to start, and when `defaultTask` starts running. The recurring `tick` marker and LED toggle run from the default FreeRTOS task using `osDelay(1000)`. The HAL timebase is generated on TIM1 so FreeRTOS can own SysTick.

FreeRTOS regression coverage checks that generated CMake includes the middleware, `FreeRTOSConfig.h` preserves the baseline scheduler settings, the CubeMX `.ioc` keeps TIM1 as the HAL timebase, the scheduler-start marker is emitted before `osKernelStart()`, and the `tick` marker is owned by `StartDefaultTask()`. The local-build integration coverage also builds both `Debug` and `RelocatedDebug` presets so FreeRTOS source integration is checked for direct-flash and post-secureboot application builds.

## Secure-boot workflow

The secure-boot profile workflow is:

```powershell
./scripts/dev.ps1 experiment build-wolfboot --profile configs/builds/wolfboot_stm32l4_<profile>.yaml
./scripts/dev.ps1 cmake --preset RelocatedDebug
./scripts/dev.ps1 cmake --build --preset RelocatedDebug
./scripts/dev.ps1 experiment sign-application --profile configs/signing/wolfboot_<profile>_app.yaml
./scripts/dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/wolfboot_<profile>_uart.yaml --repeat-count 5
```

Implemented profile stems:

```text
ecdsa_p256  # ECC256 reference profile
ecc384
ecc521
ed25519
ed448
rsa2048
rsa3072
rsa4096
mldsa44    # ML-DSA-44, wolfBoot SIGN=ML_DSA level 2
mldsa65    # ML-DSA-65, wolfBoot SIGN=ML_DSA level 3
```

The ECC256 reference uses historical file names containing `ecdsa_p256`, while benchmark metadata identifies the algorithm as `ECC256`. ML-DSA-44 and ML-DSA-65 keep the existing 8192-byte image-header reserve. ML-DSA-87 is not configured because wolfBoot's ML-DSA example requires a 12288-byte header for that variant.

Diagnostic secure-boot commands:

```powershell
./scripts/dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
./scripts/dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --negative-corrupt-application
./scripts/dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --skip-uart
```

## Benchmark aggregation

Aggregate existing secure-boot run manifests:

```powershell
./scripts/dev.ps1 experiment aggregate-benchmarks
```

Use explicit input manifests or run directories:

```powershell
./scripts/dev.ps1 experiment aggregate-benchmarks --manifest results/<run_id>/manifest.json --manifest results/<run_id>/manifest.json
./scripts/dev.ps1 experiment aggregate-benchmarks --run-dir results/<run_id> --run-dir results/<run_id>
```

Default outputs:

```text
results/benchmark-aggregation/benchmark_summary.json
results/benchmark-aggregation/benchmark_summary.csv
```

The aggregation command reads existing evidence only. It does not build firmware, sign images, flash hardware, open UART devices, use SSH, or create new measurement evidence.

Routine hardware test time is controlled by the secure-boot algorithm benchmark selection policy. `tests/hardware/test_secure_boot_algorithm_benchmarks.py` always runs ML-DSA-65 by default and skips the other profile cases. To add selected profiles, use a comma-separated environment variable before invoking pytest, for example:

```powershell
$env:PQC_HARDWARE_SECURE_BOOT_PROFILES="ecc256,ed25519"
./scripts/dev.ps1 pytest-hardware tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

For an all-in algorithm benchmark pass:

```powershell
$env:PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES="1"
./scripts/dev.ps1 pytest-hardware tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

Clear those environment variables after the run if you want to return to the default ML-DSA-65-only benchmark pass.


## Secure-boot benchmark metrics

Secure-boot benchmark runs compare classical wolfBoot signing profiles using evidence stored in each run manifest under `secure_boot_benchmark`. The manifest is the source of truth for what was measured. Summary CSV/JSON files are derived outputs and should not replace the original run manifests.

Supported metric groups:

- runtime verification metrics: verification time, verification cycles, CPU-Hz assumption, result code, source markers, and sample verdict
- repeated-run metrics: one sample per secure-boot reset/capture, with aggregate count, valid count, failed count, minimum, mean, median, maximum, standard deviation, range, and coefficient of variation
- build/resource metrics: wolfBoot `.text`, `.data`, `.bss`, flash-relevant size, and static RAM estimate
- runtime memory metrics: stack high-water evidence when explicit firmware/UART evidence is present; heap remains unavailable unless explicit heap evidence is added
- signed-artifact metrics: signed image size, unsigned image size where available, signature size, size overhead bytes, and size overhead percentage
- derived metrics: cycles per KB and time per KB where image size and median verification data are available

Interpretation rules:

- Use median verification time and median verification cycles as the primary timing comparison. Mean, minimum, maximum, standard deviation, range, and coefficient of variation are supporting values for repeatability and outlier checks.
- Compare algorithms across the same board, relocated HAL payload, CPU-Hz assumption, UART marker model, repeated-run count, and image-header reserve.
- Treat build metrics as static properties of the bootloader image, not runtime memory evidence. `.data + .bss` is the static RAM estimate.
- Treat stack and heap metrics as runtime metrics only when they come from explicit firmware-side evidence emitted over UART. Do not infer stack, heap, timing, or success from host-side capture duration, SSH duration, reset delay, ELF output alone, or build logs alone.
- Treat `unavailable` fields and limitation notes as benchmark evidence. They identify measurements that were not collected or cannot be safely interpreted.
- Compare signed-image overhead separately from verification latency. Large signatures can affect storage pressure even when verification time is acceptable.

## Test categories

```powershell
.\scripts\dev.ps1 pytest tests/unit
.\scripts\dev.ps1 pytest tests/integration -m integration
.\scripts\dev.ps1 pytest-hardware
.\scripts\dev.ps1 pytest
```

Strict capability checks:

```powershell
.\scripts\dev.ps1 pytest tests/integration -m integration --pqc-require-local-build
.\scripts\dev.ps1 pytest-gateway tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
.\scripts\dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware
.\scripts\dev.ps1 pytest-hardware tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware
.\scripts\dev.ps1 pytest-hardware tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
$env:PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES="1"; .\scripts\dev.ps1 pytest-hardware tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

## GitHub Actions CI

The repository includes `.github/workflows/ci.yml` for continuous integration on every pushed commit, pull request, and manual dispatch. The project-owned Docker image is the default CI path for reproducible non-hardware build/test validation. Existing runner-compatible jobs and MQTT broker Docker runtime validation remain as compatibility coverage.

```text
unit-tests                  Runs ./scripts/dev.ps1 pytest tests/unit.
firmware-builds            Builds the Debug and RelocatedDebug CMake presets with the ARM embedded toolchain on the runner.
wolfboot-build-integration Runs the real wolfBoot build integration test when local tooling and the wolfBoot submodule are available.
integration-tests          Runs tests/integration with --pqc-require-local-build after unit tests and firmware builds pass, including Docker Compose config rendering for the MQTT broker profiles.
mqtt-broker-docker-runtime Starts the local classical Mosquitto container, provisions temporary TLS material, validates mutual TLS, and verifies MQTT publish/subscribe with client certificates.
container-non-hardware     Default reproducible CI path: builds docker/python/Dockerfile and runs Python unit tests, safe status validation, Debug and RelocatedDebug builds, one wolfBoot profile build, relocated ECDSA P-256 application signing, and targeted local-build integration tests inside the project container.
```

The default CI workflow intentionally does not run `tests/hardware` or require the gateway. Gateway flash-helper checks and MQTT broker gateway E2E tests remain skipped on GitHub-hosted runners because they require SSH access, Docker state on the gateway, network reachability, or explicit lab evidence. The wolfBoot build integration test is enabled because it is local-toolchain-only when the wolfBoot submodule is present. MQTT broker Docker Compose config tests run on the GitHub-hosted runner with `docker compose config`; they validate rendered compose structure without deploying to the gateway or running experiment orchestration. The MQTT broker Docker runtime job starts the classical local Mosquitto container against temporary test certificates and validates mutual-TLS MQTT publish/subscribe. The experimental OQS runtime path remains covered by the gateway E2E test rather than default GitHub-hosted CI.

The containerised CI job requires no repository, organization, or environment secrets. Signing material generated by that job is runtime workspace state only and remains excluded from Git and the container image by the generated-output and secret rules. CI results provide portable software-build and local Docker runtime evidence only. Do not treat CI output as hardware, gateway, flashing, UART, production MQTT/TLS, runtime timing, runtime memory, benchmark, or end-to-end device evidence.

## Generated files and secrets

Generated outputs and local state must not be committed:

```text
build/
results/*
.last_successful_build.json
.build_number
tools/wolfboot/.config
tools/wolfboot/wolfboot.elf
tools/wolfboot/wolfboot_signing_private_key.der
secrets/wolfboot/
```

Never commit private SSH, VPN, TLS, MQTT, firmware-signing, wolfBoot-signing, certificate, `.env`, token, or production credential material.

## AI-assisted development

For feature-development chats, provide `AI_BUILD_GUIDE.md` first. The project prompt is in:

```text
docs/008_chatgpt_project_prompt.md
```

For release-readiness reviews, use:

```text
docs/009_chatgpt_project_prompt_release_readiness_review.md
```


## MQTT/TLS client roadmap and evidence boundaries

The MQTT/TLS client roadmap is split so hardware-independent work can proceed before the X-NUCLEO-67W61M1 Wi-Fi module is installed or available.

Target client architecture:

```text
STM32 application
  -> wolfMQTT client logic on STM32
  -> wolfSSL TLS endpoint on STM32
  -> lwIP TCP/IP stack on STM32
  -> network-interface boundary
  -> future ST67W61M1 Wi-Fi module backend
  -> gateway-hosted MQTT broker
```

The Wi-Fi module is the network interface backend. It is not the TLS endpoint and is not where MQTT client logic runs. Development phases must preserve that ownership boundary.

Planned transport and validation modes:

```text
fake/no-network transport          deterministic control-flow tests; simulated evidence only
host/socket validation path        host-side or broker-side compatibility evidence only
STM32 build-only preparation        compile/link evidence only; no runtime network claim
STM32 fake/no-network runtime       UART initialization evidence only; no network claim
future ST67W61M1 backend           real Wi-Fi/network-interface evidence when hardware exists
future STM32 MQTT-over-TLS          explicit STM32 + broker evidence for TLS/MQTT success
```

Evidence categories must stay separate:

```text
build-only evidence                 compiler/build output only
fake transport evidence             labelled simulation output only
host-side evidence                  host client or host utility output only
broker-side evidence                broker status, logs, or local Docker runtime output only
STM32 runtime evidence              explicit UART logs or manifests from the board
end-to-end wireless evidence        explicit ST67W61M1, STM32, and broker evidence together
```

Do not claim Wi-Fi join, IP address acquisition, TCP connection, TLS handshake, MQTT connect, publish, reconnect, latency, memory, timing, or end-to-end wireless success unless explicit logs, manifests, UART output, broker logs, or equivalent evidence support that specific claim.

Near-term MQTT/TLS work should remain in small phases: documentation split, configuration/result schema, fake transport harness, host/broker validation, STM32 lwIP build-only skeleton, wolfSSL build-only skeleton, wolfMQTT build-only skeleton, STM32 fake/no-network runtime markers, optional host-side wolfSSL/wolfMQTT validation, ST67W61M1 backend, classical STM32 MQTT-over-TLS, network degradation, and later PQC/hybrid TLS experiments.

Phase M2 adds framework-side MQTT/TLS configuration and manifest schema support. MQTT experiment configs may include an `mqtt` mapping with `schema_version: 1`, an explicit `transport_backend`, an `evidence_class`, TLS mode, optional non-secret certificate references, optional broker endpoint for host-side validation, and explicit unavailable-metric reasons. Supported evidence classes are `fake_no_network`, `host_side`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1_backed`. Supported transport backends are `fake_no_network`, `host_socket`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1`.

Phase M3 adds a deterministic fake/no-network MQTT transport harness for non-hardware control-flow testing. The `mqtt-fake-transport` command records simulated connect, publish, timeout, disconnect, and reconnect outcomes under the manifest `mqtt_tls.fake_transport` block. This evidence is labelled `fake/no-network transport evidence`; it is not broker, socket, TLS, gateway, UART, STM32 runtime, Wi-Fi, hardware, or real network evidence.

Phase M5 now compiles the STM32-local lwIP/ST67W6X preparation layer without enabling runtime networking. The earlier `Core/Inc/pqc_lwip_build_only.h` and `Core/Src/pqc_lwip_build_only.c` boundary remains present, and CubeMX-generated lwIP, SICS Network LwIP, SPI HAL, and ST67W6X driver sources are included in the direct and relocated firmware builds. This is compile/link evidence only. The generated ST67W6X hardware-facing code is present so interfaces can be inspected and future stubs can be scoped, but the firmware does not claim module detection, Wi-Fi association, IP address acquisition, TCP readiness, TLS handshake, MQTT connect, publish, reconnect, UART runtime success, or end-to-end wireless success.

The current compile-only ST67W61M1 shield pin preparation is `PA5/D13 SPI1_SCK`, `PA6/D12 SPI1_MISO`, `PA7/D11 SPI1_MOSI`, `PD14/D10 SPI_CS`, `PE11/D5 CHIP_EN`, `PE9/D6 BOOT`, `PE13/D3 SPI_RDY` through `EXTI15_10_IRQn`, and `PF15/D2 USER_BUTTON` through `EXTI15_10_IRQn`. The clock preparation targets 120 MHz SYSCLK/HCLK and SPI1 prescaler 4, which gives about 30 Mbit/s if SPI1 is clocked from the 120 MHz APB2/PCLK2 domain. FreeRTOS heap is increased to 40000 bytes for lwIP/ST67W6X preparation. The generated lwIP application/demo files are kept in the tree for inspection but filtered out of the Phase M5 compile-only CMake path; the project now compiles the CMSIS-RTOS v2 lwIP sys_arch port while runtime networking remains deferred.

The fake/no-network example config is `configs/experiments/mqtt_tls_schema_fake.yaml`. When an experiment config includes MQTT/TLS schema fields, newly created manifests include an `mqtt_tls` result model. Metrics that do not have real evidence are recorded as `status: unavailable` with a reason instead of being omitted or inferred. Phase M2/M3 schema and fake-transport handling does not perform broker deployment, socket I/O, STM32 networking, UART capture, lwIP, wolfSSL, wolfMQTT, or hardware validation.

```powershell
./scripts/dev.ps1 experiment mqtt-fake-transport --experiment configs/experiments/mqtt_tls_schema_fake.yaml
./scripts/dev.ps1 experiment mqtt-fake-transport --experiment configs/experiments/mqtt_tls_schema_fake.yaml --publish-outcome timeout
./scripts/dev.ps1 experiment mqtt-fake-transport --experiment configs/experiments/mqtt_tls_schema_fake.yaml --connect-outcome failure --reconnect-attempts 2 --reconnect-outcome success
```

## MQTT broker compose project

The gateway-hosted MQTT broker compose project lives under `experiment/mqtt-broker/`. It is orchestrated from the repository root on the build server and can provision local test certificates, deploy the compose project to `pqc-gateway1` with `scp`, and start or stop the broker with `ssh`.

Provision local classical TLS material for development testing:

```powershell
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1
```

Deploy the broker project to the gateway without committing secrets:

```powershell
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy
```

Start the classical TLS broker on the gateway:

```powershell
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile classical
```

Stop it again:

```powershell
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py stop
```

The OQS profile is experimental and depends on Open Quantum Safe's Mosquitto image. It provisions project-managed OQS mutual-TLS material on the gateway, using ML-DSA-65 for the CA, Falcon-512 for leaf certificates, and ML-KEM-768 for TLS validation. It is intended for PQC TLS protocol evaluation only, not production security claims.

Provision and validate the OQS profile after deployment:

```powershell
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-oqs-certs --host-config configs/hosts/gateway.yaml
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile oqs
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-tls
```

Run the framework-level broker experiment wrapper when you want one command to provision certificates, deploy the compose project, start one selected broker profile, retry broker validation while the selected container becomes ready, collect broker logs into `results/<run_id>/`, and optionally stop the broker. The wrapper records each step as `running` in the manifest before launching its subprocess, writes a step log immediately, prints progress for each attempt, and applies `--step-timeout-seconds` to prevent a silent unbounded subprocess:

```powershell
./scripts/dev.ps1 experiment-gateway mqtt-broker-experiment --profile classical --stop-after
./scripts/dev.ps1 experiment-gateway mqtt-broker-experiment --profile oqs --stop-after
```

Use `--no-provision-certs`, `--no-deploy`, or `--skip-validation` only when that step has already been handled manually and you still want framework result evidence for the remaining steps.


Run the runner-compatible MQTT broker checks locally when Docker is available:

```powershell
./scripts/dev.ps1 pytest tests/integration/test_mqtt_broker_docker_config.py -m integration
./scripts/dev.ps1 pytest tests/integration/test_mqtt_broker_docker_runtime.py -m docker_runtime
```

The Docker runtime test copies the broker compose project into a pytest temporary directory, provisions short-lived classical TLS material under that temporary directory, starts only the classical broker container, validates TLS 1.3 mutual authentication, verifies MQTT publish/subscribe using the Mosquitto client binaries inside the container, and tears the compose project down. It does not use the gateway or write runtime material into the repository tree.

### MQTT broker gateway validation

The MQTT broker orchestration uses the SSH alias from `configs/hosts/gateway.yaml` for `ssh`/`scp`, and uses `network.address` from the same file for external TLS validation when the SSH alias is not available through DNS.

Provision certificates with the host config so the gateway IP address is included in the server certificate SANs:

```powershell
./scripts/dev.ps1 run python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1 --host-config configs/hosts/gateway.yaml
```

Run the gateway MQTT broker integration test when Docker is available on the gateway:

```powershell
./scripts/dev.ps1 pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e.py -m integration
```


The OQS MQTT broker profile logs to Docker stdout and disables Mosquitto persistence to keep gateway temporary deployments removable by the normal gateway user.

MQTT broker note: The startup script creates a runtime-user-owned `/tmp/mosquitto-aclfile` when possible. Images with a `mosquitto` user use `mosquitto`; the current OQS Mosquitto image uses `nobody`, so the OQS config sets `user nobody` and the ACL copy is owned by that runtime user.
