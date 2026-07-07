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
- a Python-only container baseline for non-hardware framework validation

Not implemented yet: STM32 container build toolchain support, wolfBoot container build/signing support, gateway-capable container support, CI container integration, STM32 MQTT client firmware integration, wolfSSL transport experiments, production PQC TLS deployment, hybrid algorithm profiles, ML-DSA-87 under the current 8192-byte image-header reserve, network-degradation automation, and production release packaging.

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

Run all tests that can run on the current machine. Integration and hardware tests skip when capabilities are unavailable:

```powershell
python -m pytest
```

Run unit tests only:

```powershell
python -m pytest tests/unit
```

Check the direct-flash baseline config:

```powershell
python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
```

Build the direct-flash baseline:

```powershell
python scripts/experiment.py build --experiment configs/experiments/baseline_direct_uart.yaml
```

Run the full direct-flash baseline workflow:

```powershell
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
```

Use an existing first-class build record for the direct-flash run:

```powershell
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml --build-number <number>
```

Monitor UART through the gateway:

```powershell
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml --duration-seconds 10
python scripts/experiment.py monitor --experiment configs/experiments/baseline_direct_uart.yaml --restart
```



## Python-only container baseline

The repository includes a Python-only container baseline for portable non-hardware framework validation. It is intentionally limited to Python dependencies, unit tests, and framework commands that do not require STM32 toolchains, wolfBoot build/signing tools, gateway SSH, UART devices, broker access, Wi-Fi-module access, ST-LINK access, or hardware.

Build the image from the repository root:

```powershell
docker build -f docker/python/Dockerfile -t pqc-framework-python .
```

Run unit tests in the container with the repository mounted at runtime:

```powershell
docker run --rm -v ${PWD}:/workspace -w /workspace pqc-framework-python python -m pytest tests/unit
```

Run a safe framework command that loads and validates the direct-flash experiment configuration without building, flashing, opening UART, using SSH, or contacting a broker:

```powershell
docker run --rm -v ${PWD}:/workspace -w /workspace pqc-framework-python python scripts/experiment.py status --experiment configs/experiments/baseline_direct_uart.yaml
```

The Python-only image does not include STM32 toolchains and does not provide gateway SSH, UART, broker, Wi-Fi-module, ST-LINK, or hardware access. Do not use it for CMake firmware builds, wolfBoot builds, application signing, flashing, UART capture, MQTT broker validation, or benchmark/runtime evidence. Those remain later containerisation sub-phases or existing host/gateway workflows.

The `.dockerignore` file excludes generated outputs and local secret material from the image build context. Private signing keys, SSH keys, VPN keys, TLS private keys, MQTT passwords, real `.env` files, private certificates, generated wolfBoot signing material, and production credentials must not be committed or baked into images.

## Containerised non-hardware build/test plan

The staged containerisation track remains positioned before STM32 MQTT client firmware, lwIP, wolfSSL, and wolfMQTT implementation work. Phase C2 implements only the Python baseline. Later phases may add STM32 direct/relocated build support, wolfBoot build/signing support with runtime-mounted or locally generated signing material only, optional gateway-capable support, and CI integration.

## Firmware scheduler model

The STM32 application is CubeMX-generated HAL firmware with a CMSIS-RTOS v1 FreeRTOS template. Startup and secure-boot evidence markers are emitted after peripheral initialization and before `osKernelStart()`. The application also emits explicit FreeRTOS markers when `defaultTask` is created, when the scheduler is about to start, and when `defaultTask` starts running. The recurring `tick` marker and LED toggle run from the default FreeRTOS task using `osDelay(1000)`. The HAL timebase is generated on TIM6 so FreeRTOS can own SysTick.

FreeRTOS regression coverage checks that generated CMake includes the middleware, `FreeRTOSConfig.h` preserves the baseline scheduler settings, the CubeMX `.ioc` keeps TIM6 as the HAL timebase, the scheduler-start marker is emitted before `osKernelStart()`, and the `tick` marker is owned by `StartDefaultTask()`. The local-build integration coverage also builds both `Debug` and `RelocatedDebug` presets so FreeRTOS source integration is checked for direct-flash and post-secureboot application builds.

## Secure-boot workflow

The secure-boot profile workflow is:

```powershell
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_<profile>.yaml
cmake --preset RelocatedDebug
cmake --build --preset RelocatedDebug
python scripts/experiment.py sign-application --profile configs/signing/wolfboot_<profile>_app.yaml
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_<profile>_uart.yaml --repeat-count 5
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
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --negative-corrupt-application
python scripts/experiment.py flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml --skip-uart
```

## Benchmark aggregation

Aggregate existing secure-boot run manifests:

```powershell
python scripts/experiment.py aggregate-benchmarks
```

Use explicit input manifests or run directories:

```powershell
python scripts/experiment.py aggregate-benchmarks --manifest results/<run_id>/manifest.json --manifest results/<run_id>/manifest.json
python scripts/experiment.py aggregate-benchmarks --run-dir results/<run_id> --run-dir results/<run_id>
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
python -m pytest tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

For an all-in algorithm benchmark pass:

```powershell
$env:PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES="1"
python -m pytest tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
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
python -m pytest tests/unit
python -m pytest tests/integration -m integration
python -m pytest tests/hardware -m hardware
python -m pytest
```

Strict capability checks:

```powershell
python -m pytest tests/integration -m integration --pqc-require-local-build
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
python -m pytest tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware
python -m pytest tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware
python -m pytest tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
$env:PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES="1"; python -m pytest tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

## GitHub Actions CI

The repository includes `.github/workflows/ci.yml` for runner-compatible continuous integration on every pushed commit and pull request. The workflow runs in runner-compatible jobs:

```text
unit-tests                  Runs python -m pytest tests/unit.
firmware-builds            Builds the Debug and RelocatedDebug CMake presets with the ARM embedded toolchain.
wolfboot-build-integration Runs the opt-in real wolfBoot build integration test with PQC_RUN_WOLFBOOT_BUILD_INTEGRATION=1.
integration-tests          Runs tests/integration with --pqc-require-local-build after unit tests and firmware builds pass, including Docker Compose config rendering for the MQTT broker profiles.
mqtt-broker-docker-runtime Starts the local classical Mosquitto container, provisions temporary TLS material, validates mutual TLS, and verifies MQTT publish/subscribe with client certificates.
```

The CI workflow intentionally does not run `tests/hardware` or require the gateway. Gateway flash-helper checks and MQTT broker gateway E2E tests remain skipped on GitHub-hosted runners because they require SSH access, Docker state on the gateway, network reachability, or explicit lab evidence. The wolfBoot build integration test is enabled because it is local-toolchain-only when the wolfBoot submodule is present. MQTT broker Docker Compose config tests run on the GitHub-hosted runner with `docker compose config`; they validate rendered compose structure without deploying to the gateway or running experiment orchestration. The separate MQTT broker Docker runtime job starts the classical local Mosquitto container against temporary test certificates and validates mutual-TLS MQTT publish/subscribe. The experimental OQS runtime path remains covered by the gateway E2E test rather than default GitHub-hosted CI.

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

## MQTT broker compose project

The gateway-hosted MQTT broker compose project lives under `experiment/mqtt-broker/`. It is orchestrated from the repository root on the build server and can provision local test certificates, deploy the compose project to `pqc-gateway1` with `scp`, and start or stop the broker with `ssh`.

Provision local classical TLS material for development testing:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1
```

Deploy the broker project to the gateway without committing secrets:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py deploy
```

Start the classical TLS broker on the gateway:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile classical
```

Stop it again:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py stop
```

The OQS profile is experimental and depends on Open Quantum Safe's Mosquitto image. It provisions project-managed OQS mutual-TLS material on the gateway, using ML-DSA-65 for the CA, Falcon-512 for leaf certificates, and ML-KEM-768 for TLS validation. It is intended for PQC TLS protocol evaluation only, not production security claims.

Provision and validate the OQS profile after deployment:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-oqs-certs --host-config configs/hosts/gateway.yaml
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py start --profile oqs
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py validate-oqs-tls
```

Run the framework-level broker experiment wrapper when you want one command to provision certificates, deploy the compose project, start one selected broker profile, retry broker validation while the selected container becomes ready, collect broker logs into `results/<run_id>/`, and optionally stop the broker. The wrapper records each step as `running` in the manifest before launching its subprocess, writes a step log immediately, prints progress for each attempt, and applies `--step-timeout-seconds` to prevent a silent unbounded subprocess:

```powershell
python scripts/experiment.py mqtt-broker-experiment --profile classical --stop-after
python scripts/experiment.py mqtt-broker-experiment --profile oqs --stop-after
```

Use `--no-provision-certs`, `--no-deploy`, or `--skip-validation` only when that step has already been handled manually and you still want framework result evidence for the remaining steps.


Run the runner-compatible MQTT broker checks locally when Docker is available:

```powershell
python -m pytest tests/integration/test_mqtt_broker_docker_config.py -m integration
python -m pytest tests/integration/test_mqtt_broker_docker_runtime.py -m docker_runtime
```

The Docker runtime test copies the broker compose project into a pytest temporary directory, provisions short-lived classical TLS material under that temporary directory, starts only the classical broker container, validates TLS 1.3 mutual authentication, verifies MQTT publish/subscribe using the Mosquitto client binaries inside the container, and tears the compose project down. It does not use the gateway or write runtime material into the repository tree.

### MQTT broker gateway validation

The MQTT broker orchestration uses the SSH alias from `configs/hosts/gateway.yaml` for `ssh`/`scp`, and uses `network.address` from the same file for external TLS validation when the SSH alias is not available through DNS.

Provision certificates with the host config so the gateway IP address is included in the server certificate SANs:

```powershell
python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py provision-certs --server-name pqc-gateway1 --host-config configs/hosts/gateway.yaml
```

Run the gateway MQTT broker integration test when Docker is available on the gateway:

```powershell
python -m pytest tests/integration/test_mqtt_broker_gateway_e2e.py -m integration
```


The OQS MQTT broker profile logs to Docker stdout and disables Mosquitto persistence to keep gateway temporary deployments removable by the normal gateway user.

MQTT broker note: The startup script creates a runtime-user-owned `/tmp/mosquitto-aclfile` when possible. Images with a `mosquitto` user use `mosquitto`; the current OQS Mosquitto image uses `nobody`, so the OQS config sets `user nobody` and the ACL copy is owned by that runtime user.
