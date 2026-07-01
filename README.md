# PQC-Framework-02

STM32-based embedded security experiment framework for direct-flash baseline experiments, wolfBoot secure-boot experiments, and secure-boot benchmark collection.

## Current implementation

The repository currently contains:

- a CubeMX-generated STM32 HAL firmware project for the NUCLEO-L4R5ZI-P / STM32L4R5 board
- direct-flash baseline build, flash, UART, and run workflows
- first-class build records and source/build fingerprinting
- a relocated HAL application build for wolfBoot launch
- wolfBoot build profiles using the local `tools/wolfboot` submodule
- application-signing profiles for classical wolfBoot algorithms
- secure-boot flash, UART evidence, negative-test, repeated-run, and benchmark workflows
- benchmark aggregation to JSON and CSV

Not implemented yet: MQTT, TLS, PQC/hybrid algorithm profiles, network-degradation automation, and production release packaging.

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
```

The ECC256 reference uses historical file names containing `ecdsa_p256`, while benchmark metadata identifies the algorithm as `ECC256`.

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
```

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
