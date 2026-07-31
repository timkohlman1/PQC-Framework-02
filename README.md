# PQC-Framework-02

STM32 embedded-security experiment framework for direct-flash firmware, wolfBoot secure boot, reproducible evidence collection, and bounded MQTT/TLS preparation.

## Current scope

The repository provides Docker-hosted build, test, signing, experiment, gateway, UART, benchmark, and broker workflows for the NUCLEO-L4R5ZI-P / STM32L4R5 platform. Implemented firmware capabilities include HAL/CMSIS-RTOS v2 FreeRTOS execution, classical and ML-DSA wolfBoot profiles, STM32-local lwIP and wolfSSL preparation, fake/no-network wolfMQTT initialization, and recorded plaintext, classical TLS, and hybrid P-256 plus ML-KEM-768 MQTT-over-TLS paths through the ST67/lwIP transport.

Evidence boundaries are strict:

- Build-only evidence proves compilation and linkage only.
- STM32 local-only and fake/no-network evidence does not prove external networking.
- Host-side or broker-side validation does not prove STM32 or end-to-end wireless success.
- The unavailable transport boundary performs no socket I/O.
- The ST67W61M1 integration supports configured-AP association, link-up, host-side lwIP DHCP, and live IPv4 evidence in capability-gated hardware runs. Earlier local smoke markers remain limited to their execution point.
- STM32 firmware builds are intentionally limited to Ethernet-style IPv4 over the ST67 netif. IPv6, bridge, PPP/PPPoE/PPPoS/L2TP, and SLIP components are disabled or excluded from the firmware target.
- The non-network lwIP runtime smoke exercises version, IPv4 formatting, and checksum helpers only; it does not initialize a netif or prove external networking.
- MQTT capability claims remain run-specific: only retained UART, broker, subscriber, and manifest evidence can establish plaintext, classical TLS, or hybrid PQC success.

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

Run unit tests, repository Python tools, or the complete capability-gated test selection:

```powershell
.\scripts\dev.ps1 pytest tests/unit
.\scripts\dev.ps1 python experiment/mqtt-broker/scripts/mqtt_broker_ctl.py --help
.\scripts\dev.ps1 pytest
```

Use `.\scripts\dev.ps1 python-gateway <script> [arguments...]` for Python tools that require configured gateway SSH access.

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

Use `run` for an end-to-end MQTT/TLS experiment through wolfBoot:

```powershell
.\scripts\dev.ps1 experiment-gateway run `
    --experiment configs/experiments/mqtt_tls_server_auth_st67_e2e.yaml `
    --boot-mode wolfboot `
    --boot-algorithm ecdsa_p256
```

The workflow prepares dependencies and signing material, builds wolfBoot and the relocated MQTT firmware, signs and flashes both images, validates UART and broker behaviour, stops the broker, and retains one result set. Omit the boot options for direct flash. MQTT/TLS algorithms remain owned by the experiment YAML.

For a manual secure-boot sequence, create the framework-recorded relocated application before signing:

```powershell
.\scripts\dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml --configure-preset RelocatedDebug --build-preset RelocatedDebug --artifact build/RelocatedDebug/stm32_basic_hal1.elf
.\scripts\dev.ps1 experiment sign-application --boot-algorithm ecdsa_p256
```

Further manual commands, signing-tuple rules, and diagnostic fallbacks are documented in `docs/005_remote_flash_workflow.md`.

## MQTT and broker orientation

The repository includes framework schema validation, deterministic fake/no-network execution, an initial plaintext ST67/lwIP STM32 MQTT path, classical and experimental OQS broker profiles, and native host wolfMQTT/wolfSSL compatibility validation. The canonical broker Compose file is `experiment/mqtt-broker/compose.yaml`.

Use `experiment/mqtt-broker/README.md` for certificate provisioning, gateway deployment, broker lifecycle commands, and the PowerShell `--client-args` forwarding contract. Those workflows produce host-side or broker-side evidence only; they do not prove wolfMQTT-on-STM32 or end-to-end wireless operation.

## Safety and evidence

Disposable experiment signing, certificate, broker, and client material used by an owning workflow is retained in that workflow's ignored result directory with a SHA-256 `material-inventory.json`, together with applicable unsigned/signed application images and bootloader outputs. These result copies are sensitive reproduction evidence, not authoritative future inputs. SSH/VPN keys, tokens, production or externally managed credentials, real `.env` files, and unrelated host credentials must never be copied into results, committed, packaged in AI replacement archives, or baked into images.

Generated-state preflight is the primary mechanism for signing-state compatibility and provenance. Pytest cleanup is supplementary cross-platform hygiene and must not remove source files, canonical signing keys, or reusable tuple members. Workflows must never silently reconstruct partial signing state.

Do not claim build, signing, flashing, gateway, hardware, UART, runtime, timing, memory, benchmark, MQTT/TLS, Wi-Fi, or end-to-end success without explicit logs, manifests, or equivalent evidence from the relevant workflow. A skipped capability-gated test is not evidence that the capability succeeded.

Detailed signing-tuple, automated-test evidence, MQTT broker lifecycle, classical TLS, and hybrid PQC procedures are owned by `docs/005_remote_flash_workflow.md`, `docs/007_framework_architecture.md`, and `experiment/mqtt-broker/README.md`.

### Declared certificate prerequisites

TLS experiment profiles declare `mqtt.tls.certificate_profile`. Running `experiment build` or `experiment-gateway run` prepares or reuses the matching tuple under `secrets/mqtt/<profile>/`, validates public provenance, and embeds the resolved public material into generated build configuration. Do not invoke certificate provisioning as a separate prerequisite and do not place authoritative certificates under `experiment/mqtt-broker/runtime/`.

### Certificate services

Classical X.509 certificate generation is owned by `framework/certs` (step-ca, Vault, and LocalStack KMS). All MQTT TLS profiles use TLS 1.3; the PQC MQTT profile uses hybrid key exchange with a classical broker certificate. Run the certificate services and synchronize `stepca-classical` material before encrypted MQTT builds. See `framework/certs/README.md` and `experiment/mqtt-broker/README.md`.

## Experiment console progress

Experiment commands emit timestamped stage messages for resolved cryptography, prerequisites, CMake configuration and build execution, gateway operations, broker/MQTT lifecycle work, cleanup, and final result recording. Timestamps default to `Australia/Melbourne`, include `AEST` or `AEDT`, and may be overridden with `PQC_PROGRESS_TIMEZONE` using an IANA timezone name.

Progress output is operational context only. The result manifest and retained logs remain authoritative evidence.

### Application build identity and incremental compilation

Application builds no longer use framework-level source, header, tool, or dependency fingerprints and are never selected from a reusable build pool. Every build request invokes `cmake --preset <preset>` followed by `cmake --build --preset <preset>`. The retained CMake/Ninja build directory provides native incremental optimisation, so unchanged object files may be reused by Ninja without the framework claiming cross-run artifact compatibility.

After a successful build, the framework calculates the final ELF SHA-256. This digest is the artifact identity recorded in the run manifest and immutable build record. Normal build identities use `build-<number>-<elf-sha256-prefix>`. Flash provenance verifies that the selected ELF matches the SHA-256 in the referenced immutable record; it does not recalculate source-state fingerprints.

Managed STM32 MQTT experiments retain verbose broker packet evidence alongside UART and topic-qualified subscriber output. See `experiment/mqtt-broker/README.md` and `docs/007_framework_architecture.md` for the cross-validation contract and evidence limits.

Disposable experiment cryptographic material may be retained only in ignored result directories when the owning workflow selects it explicitly. Private signing keys, TLS private keys, and certificates copied into results remain sensitive experiment artifacts. They must not be committed, published, or baked into the image. SSH/VPN keys, tokens, production credentials, and unrelated host secrets remain prohibited.
