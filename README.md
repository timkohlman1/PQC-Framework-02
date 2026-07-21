# PQC-Framework-02

STM32 embedded-security experiment framework for direct-flash firmware, wolfBoot secure boot, reproducible evidence collection, and bounded MQTT/TLS preparation.

## Current scope

The repository provides Docker-hosted build, test, signing, experiment, gateway, UART, benchmark, and broker workflows for the NUCLEO-L4R5ZI-P / STM32L4R5 platform. Implemented firmware capabilities include HAL/CMSIS-RTOS v2 FreeRTOS execution, classical and ML-DSA wolfBoot profiles, STM32-local lwIP and wolfSSL preparation, fake/no-network wolfMQTT initialization, and an initial plaintext ST67/lwIP wolfMQTT publish/subscribe path that still requires recorded hardware evidence before end-to-end success may be claimed.

Evidence boundaries are strict:

- Build-only evidence proves compilation and linkage only.
- STM32 local-only and fake/no-network evidence does not prove external networking.
- Host-side or broker-side validation does not prove STM32 or end-to-end wireless success.
- The unavailable transport boundary performs no socket I/O.
- The ST67W61M1 integration supports configured-AP association, link-up, host-side lwIP DHCP, and live IPv4 evidence in capability-gated hardware runs. Earlier local smoke markers remain limited to their execution point.
- The non-network lwIP runtime smoke exercises version, IPv4 formatting, and checksum helpers only; it does not initialize a netif or prove external networking.
- The plaintext ST67/lwIP wolfMQTT path is implemented for capability-gated evaluation; successful STM32 TCP, MQTT subscribe/receive/publish, and end-to-end operation remain unproven until explicit UART, broker, and manifest evidence is recorded. STM32 TLS and PQC/hybrid MQTT-over-TLS remain unavailable.

The canonical capability matrix and detailed limitations are in `docs/007_framework_architecture.md`.

## Documentation

- `docs/README.md` — documentation index and ownership map
- `AI_BUILD_GUIDE.md` — mandatory rules for AI-assisted implementation and review
- `docs/001_ai_feature_request_workflow.md` — maintained AI request workflow; there is no separate release-readiness prompt document
- `docs/007_framework_architecture.md` — architecture, evidence model, capability matrix, and deferred-test register
- `docs/005_remote_flash_workflow.md` — build, signing, flash, secure-boot, and UART procedures
- `docs/006_security_and_secrets.md` — secret handling and signing-state safety
- `experiment/mqtt-broker/README.md` — broker provisioning, deployment, and host-side validation
- `docs/non_hardware_mqtt_tls_development_plan.md` — active MQTT/TLS roadmap

The maintained project prompt is `docs/008_chatgpt_project_prompt.md`.

## Default workflow

The default development path is Docker-hosted Linux execution through the project wrapper scripts, `scripts\dev.ps1` and `scripts/dev.sh`. Host-native commands remain available as an explicit fallback for diagnosis, but they are not the reproducible validation gate.

Build the development image:

```powershell
.\scripts\dev.ps1 build-image
```

Run unit tests or the complete capability-gated test selection:

```powershell
.\scripts\dev.ps1 pytest tests/unit
.\scripts\dev.ps1 pytest
```

Inspect or build the direct-flash baseline:

```powershell
.\scripts\dev.ps1 experiment status --experiment configs/experiments/baseline_direct_uart.yaml
.\scripts\dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml
```

Run the direct-flash workflow through Docker and the SSH gateway. SSH/SCP uses runtime-mounted SSH access; containers do not receive direct UART devices, ST-LINK/USB passthrough, or Wi-Fi-module passthrough; hardware workflows remain gateway-mediated:

```powershell
.\scripts\dev.ps1 experiment-gateway run --experiment configs/experiments/baseline_direct_uart.yaml
```

Run the hardware test selection when the required gateway and board capabilities are intentionally available:

```powershell
.\scripts\dev.ps1 pytest-hardware
```

On Linux or macOS, use the equivalent `./scripts/dev.sh` commands.

Representative host-native commands remain diagnostic fallback only:

```powershell
cmake --preset Debug
cmake --build --preset Debug
cmake --preset RelocatedDebug
cmake --build --preset RelocatedDebug
python -m pytest tests/integration/test_local_build.py -m integration --pqc-require-local-build
```

## Secure-boot example

The normal secure-boot path records relocated-build provenance before signing:

```powershell
.\scripts\dev.ps1 experiment build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
.\scripts\dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml --configure-preset RelocatedDebug --build-preset RelocatedDebug --artifact build/RelocatedDebug/stm32_basic_hal1.elf
.\scripts\dev.ps1 experiment sign-application --profile configs/signing/wolfboot_ecdsa_p256_app.yaml
.\scripts\dev.ps1 experiment-gateway flash-secure-boot --experiment configs/experiments/wolfboot_ecdsa_p256_uart.yaml
```

Generated-state preflight is the primary compatibility and provenance mechanism. Pytest cleanup is supplementary cross-platform hygiene only. Do not run wolfBoot `keysclean`, delete reusable signing-tuple members, silently reconstruct partial signing state, or silently replace a canonical private key. Full profile coverage and diagnostic fallback commands are owned by `docs/005_remote_flash_workflow.md`.

## MQTT and broker orientation

The repository includes framework schema validation, deterministic fake/no-network execution, an initial plaintext ST67/lwIP STM32 MQTT path, classical and experimental OQS broker profiles, and native host wolfMQTT/wolfSSL compatibility validation. The canonical broker Compose file is `experiment/mqtt-broker/compose.yaml`.

Use `experiment/mqtt-broker/README.md` for certificate provisioning, gateway deployment, broker lifecycle commands, and the PowerShell `--client-args` forwarding contract. Those workflows produce host-side or broker-side evidence only; they do not prove wolfMQTT-on-STM32 or end-to-end wireless operation.

## Safety and evidence

Private signing keys, credentials, real `.env` files, generated broker runtime state, local signing tuples, build output, and result output must not be committed or packaged. Secrets must not be baked into the image. Gateway credentials and private material must be supplied outside the repository and mounted or referenced only for the current run.

Do not claim build, signing, flashing, gateway, hardware, UART, runtime, timing, memory, benchmark, MQTT/TLS, Wi-Fi, or end-to-end success without explicit logs, manifests, or equivalent evidence from the relevant workflow. A skipped capability-gated test is not evidence that the capability succeeded.

## Persistent wolfBoot signing tuples

Signing identities are selected by the signing and wolfBoot build profiles.
The complete reusable tuple is stored locally under
`secrets/wolfboot/tuples/<tuple-id>/`. Files copied into `tools/wolfboot/` are
disposable build material and are recreated from the persistent tuple on every
build when necessary.

A new tuple is generated atomically by the owning wolfBoot build when the
configured tuple directory is completely absent. A partial, corrupted, or
algorithm-incompatible persistent tuple fails safely. Application signing does
not create a private key independently; run the matching `build-wolfboot`
profile first when initializing a new signing identity.


### Plaintext STM32 MQTT end-to-end run

The `mqtt_plaintext_st67_e2e` experiment starts a gateway-side response subscriber before resetting the MCU, repeatedly publishes the configured command during the bounded startup window, and requires both the STM32 UART success markers and the independently received broker response. Evidence is retained as `uart.log`, `mqtt-publisher.log`, `mqtt-subscriber.log`, and `manifest.json` in the run result directory. A generic boot/tick pass is not sufficient for this profile.

```powershell
.\scripts\dev.ps1 experiment-gateway run `
    --experiment configs/experiments/mqtt_plaintext_st67_e2e.yaml `
    --uart-duration-seconds 30
```

### Managed broker lifecycle for the plaintext STM32 MQTT experiment

The `mqtt_plaintext_st67_e2e` gateway run owns the framework MQTT broker for the duration of that run. It stops the known framework Compose broker, deploys the current broker project, starts the classical profile, waits for a successful plaintext MQTT readiness exchange on port 1883, performs the STM32 command/response exchange, captures the complete broker log, and stops the broker in cleanup. Broker lifecycle evidence is retained beside `uart.log` as `mqtt-broker-*.log`. A readiness, log-collection, or cleanup failure is recorded as a distinct failure stage and cannot be reported as a successful end-to-end run.
