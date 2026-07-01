# Project Overview

## Purpose

This repository is an STM32-based embedded security experiment framework. It supports repeatable firmware, gateway, UART, secure-boot, and benchmark workflows for the NUCLEO-L4R5ZI-P / STM32L4R5 platform.

The project is broader than wolfBoot. wolfBoot is the current secure-boot component, but later phases may add wolfSSL MQTT/TLS, PQC/hybrid cryptographic profiles, network impairment, and broader analysis tooling.

## Current implementation

Implemented areas:

- CubeMX-generated STM32 HAL direct-flash baseline
- local CMake/Ninja build automation
- remote gateway flashing
- bounded UART capture
- result manifests and first-class build records
- source/build fingerprinting and rebuild-skip logic
- relocated HAL application build for wolfBoot launch
- wolfBoot build profiles using `tools/wolfboot`
- application-signing profiles for classical wolfBoot algorithms
- secure-boot two-artifact flash workflow
- positive UART marker evidence
- corrupted-application negative-test workflow
- secure-boot verification timing, cycle, result-code, and stack high-water evidence from explicit firmware/UART markers
- repeated secure-boot benchmark samples and aggregate statistics
- static ELF/resource and signed-artifact metrics
- benchmark aggregation output to JSON and CSV

Not implemented yet:

- MQTT transport experiments
- TLS/wolfSSL transport experiments
- PQC or hybrid signing profiles
- network degradation automation
- production release packaging

## Current benchmark scope

Minimum classical secure-boot benchmark profiles:

```text
ECC256
ED25519
RSA2048
```

Optional expanded classical profiles:

```text
ECC384
ECC521
ED448
RSA3072
RSA4096
```

Hardware and benchmark success must only be claimed from explicit user-provided logs or generated manifests.
