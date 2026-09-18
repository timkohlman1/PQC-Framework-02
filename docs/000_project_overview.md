# Project Overview

## Purpose

This repository is an STM32-based embedded security experiment framework for the NUCLEO-L4R5ZI-P / STM32L4R5 platform. It supports reproducible firmware builds, gateway-mediated flash and UART workflows, wolfBoot secure boot, benchmark collection, and bounded MQTT/TLS preparation and compatibility validation.

Docker-hosted Linux execution is the documented default for framework commands, STM32 direct and relocated builds, wolfBoot builds, application signing, pytest, and capability-gated gateway or hardware operations. Host-native tooling is a diagnostic fallback.

## Current implementation

The implemented baseline includes a CubeMX-generated HAL/CMSIS-RTOS v2 FreeRTOS application, direct-flash and relocated builds, generated-state preflight and build provenance, gateway flash/UART orchestration, wolfBoot build/sign/flash workflows, selectable `single_bank`, `dual_bank_no_ota`, and `dual_bank_ota` firmware modes, authenticated dual-bank OTA staging/activation/confirmation/rollback, classical and ML-DSA-44/ML-DSA-65 secure-boot profiles, negative testing, repeated measurements, manifest-backed metrics, and JSON/CSV benchmark aggregation. GitHub Actions provides reproducible non-hardware validation without treating container output as hardware or runtime evidence.

MQTT/TLS support is divided by evidence boundary:

- **Framework and fake/no-network:** configuration/result schemas and deterministic simulated transport outcomes; no sockets, broker, STM32 runtime, or network success.
- **Broker-side and host-side:** classical and experimental OQS broker profiles plus native host wolfMQTT/wolfSSL compatibility validation; this does not prove STM32, Wi-Fi, or end-to-end wireless behavior.
- **STM32 build-only:** lwIP/ST67W6X sources, selected wolfSSL sources, and wolfMQTT client/packet/socket layers compile and link in direct and relocated firmware builds.
- **STM32 local-only:** constrained lwIP/wolfSSL helper smokes, an unattached lwIP `netif` status boundary, and UDP loopback at `127.0.0.1` run without external networking.
- **STM32 unavailable transport:** the project-owned wolfSSL transport callbacks report connect/read/write as unavailable and perform no socket I/O.
- **STM32 fake/no-network MQTT:** wolfMQTT initializes and deinitializes from `defaultTask` against unavailable callbacks; broker connection, TLS handshake, publish, and reconnect remain unavailable.
- **Hardware-backed runtime:** the ST67W61M1 backend, Wi-Fi association/DHCP, lwIP sockets, STM32 TLS transport/session handling, wolfMQTT operations, secure boot, and dual-bank OTA paths are implemented. Hardware evidence remains profile- and test-specific; implementation alone must not be generalized into success for unexecuted TLS, MQTT, impairment, benchmark, or OTA combinations.
- **Future hardware-backed:** additional hardware validation remains future work for combinations and profiles that have not yet been executed on the target. This label refers to unvalidated coverage, not to the already implemented hardware-backed runtime paths above.

Hardware, gateway, UART, runtime, timing, memory, MQTT/TLS, and benchmark claims require explicit logs, manifests, or equivalent evidence.

## External dependency reproducibility

The parent repository pins each top-level Git submodule to an exact commit. Project-modified dependencies use project-controlled forks so the pinned commit remains fetchable from a fresh clone; unmodified dependencies remain pinned directly to their public upstream repositories.

- `tools/wolfboot` -> `https://github.com/timkohlman1/wolfBoot.git`: project-controlled fork for STM32L4R5 and dual-bank OTA bootloader changes.
- `Middlewares/Third_Party/wolfSSL` -> `https://github.com/timkohlman1/wolfssl-embedded.git`: project-controlled application wolfSSL fork for framework-specific TLS/crypto instrumentation and fixes.
- `Middlewares/Third_Party/wolfMQTT` -> `https://github.com/wolfSSL/wolfMQTT.git`: unmodified public upstream dependency pinned to an exact commit.

For a modified submodule, commit and push the submodule change first, then commit the updated gitlink in `PQC-Framework-02`. The SHA recorded by the parent repository, rather than a branch name, is the reproducible dependency identity.

## Current benchmark scope

Implemented secure-boot profiles are ECC256, ECC384, ECC521, ED25519, ED448, RSA2048, RSA3072, RSA4096, ML-DSA-44, and ML-DSA-65. ML-DSA-87 is unavailable under the current 8192-byte image-header reserve.

Benchmark evidence distinguishes static build/signing metrics from firmware-reported runtime timing, cycles, result codes, stack high-water values, and other explicit UART/manifest measurements. Host duration, UART capture duration, linker output, and ELF output alone are not runtime evidence.
