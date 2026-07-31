# PQC-Framework-02

STM32 embedded-security experiment framework for wolfBoot secure boot, reproducible evidence collection, and bounded MQTT/TLS experiments.

## Current scope

The repository provides Docker-hosted build, test, signing, experiment, gateway, UART, benchmark, packet-capture, and broker workflows for the NUCLEO-L4R5ZI-P / STM32L4R5 platform.

Evidence boundaries are strict:

- Build-only evidence proves compilation and linkage only.
- STM32 local-only and fake/no-network evidence does not prove external networking.
- Host-side or broker-side validation does not prove STM32 or end-to-end wireless success.
- MQTT, TLS, Wi-Fi, secure-boot, timing, and memory claims require retained run evidence.

The canonical capability matrix and detailed limitations are in `docs/007_framework_architecture.md`.

The non-network lwIP runtime smoke checks version, IPv4 formatting, and checksum helpers; it does not initialize a netif and is not external-network evidence.

## Documentation

- `docs/README.md` — documentation index and ownership map
- `AI_BUILD_GUIDE.md` — mandatory AI-assisted development rules
- `docs/001_ai_feature_request_workflow.md` — maintained AI workflow; there is no separate release-readiness prompt document
- `docs/008_chatgpt_project_prompt.md` — maintained reusable project prompt
- `docs/005_remote_flash_workflow.md` — build, signing, flash, secure-boot, UART, and packet-capture procedures
- `docs/006_security_and_secrets.md` — secret handling and signing-state safety
- `docs/007_framework_architecture.md` — architecture, capability matrix, evidence model, and deferred tests
- `experiment/mqtt-broker/README.md` — broker provisioning, operation, and PowerShell `--client-args` forwarding contract

## Default workflow

The default development path is Docker-hosted Linux execution through the project wrapper scripts `scripts\dev.ps1` and `scripts/dev.sh`. Host-native commands remain available as an explicit fallback for diagnosis only and are not the reproducible validation gate.

```powershell
.\scripts\dev.ps1 build-image
.\scripts\dev.ps1 pytest tests/unit
.\scripts\dev.ps1 pytest
.\scripts\dev.ps1 python scripts/experiment.py --help
.\scripts\dev.ps1 python-gateway scripts/experiment.py --help
```

All application builds use the fixed wolfBoot-relocated layout. Release is the default compiler configuration. Add `--debug` when Debug compiler settings are required; the flash addresses remain unchanged.

```powershell
.\scripts\dev.ps1 experiment status --experiment configs/experiments/baseline_direct_uart.yaml
.\scripts\dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml
.\scripts\dev.ps1 experiment-gateway run --experiment configs/experiments/baseline_direct_uart.yaml
```


Host-native diagnostic fallback:

```powershell
cmake --preset Release
cmake --build --preset Release
cmake --preset Debug
cmake --build --preset Debug
python -m pytest tests/integration/test_local_build.py -m integration --pqc-require-local-build
```

SSH/SCP uses runtime-mounted SSH access. Gateway and hardware workflows remain gateway-mediated; containers do not receive direct UART devices, ST-LINK/USB passthrough, or Wi-Fi-module passthrough.

## Secure-boot example

When no secure-boot algorithm is specified, the framework uses wolfBoot with `integrity_sha256`. This verifies the application SHA-256 digest but performs no signature or signing-key authentication.

A named algorithm implies wolfBoot; `--boot-mode wolfboot` is not required.

```powershell
.\scripts\dev.ps1 experiment-gateway run `
    --experiment configs/experiments/mqtt_plaintext_st67_e2e.yaml `
    --boot-algorithm mldsa87
```

ML-DSA-44, ML-DSA-65, and ML-DSA-87 are explicit non-default signing evaluation profiles. Release and Debug share the same relocated layout:

```text
wolfBoot primary slot:    0x08020000
manifest/header reserve:  0x00003000
application vector table: 0x08023000
```

For manual packaging, create the framework-recorded Release build before signing:

```powershell
.\scripts\dev.ps1 experiment build --experiment configs/experiments/baseline_direct_uart.yaml
.\scripts\dev.ps1 experiment sign-application
```

Detailed commands and signing-tuple rules are owned by `docs/005_remote_flash_workflow.md`.

## MQTT and broker orientation

The repository includes plaintext, classical TLS, and hybrid PQC MQTT experiment profiles. Use `experiment/mqtt-broker/README.md` for certificate provisioning, deployment, broker lifecycle, and host-side validation.

Networked profiles can retain `gateway-network-capture.pcap` and `gateway-network-capture.log`. Packet capture is supporting evidence only; correlate it with UART, broker, subscriber, and manifest evidence. Setup and inspection details are in `docs/002_host_gateway_setup.md` and `docs/005_remote_flash_workflow.md`.

## Safety and evidence

Private signing keys and generated credentials must not be committed or baked into the image. Disposable experiment signing and certificate material selected by an owning workflow may be retained only in ignored result directories with a SHA-256 material inventory. SSH/VPN keys, tokens, production credentials, unrelated host credentials, and real `.env` files must not be copied into results, committed, packaged, or baked into images.

Generated-state preflight is the primary compatibility and provenance mechanism. Pytest cleanup is supplementary cross-platform hygiene. Workflows must never silently reconstruct partial signing state.

Do not claim build, signing, flashing, hardware, UART, network, MQTT/TLS, timing, memory, or end-to-end success without explicit logs, manifests, or equivalent evidence. A skipped capability-gated test is not evidence of success.
