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

For local Wi-Fi credentials, copy the committed sample file once and edit the local copy:

```powershell
Copy-Item .env.sample .env
```

Set `PQC_WIFI_SSID` and `PQC_WIFI_PSK` in `.env`. The real `.env` is Git-ignored. Both `scripts/dev.ps1` and `scripts/dev.sh` load only those two values for the duration of each Docker invocation; caller-supplied environment variables take precedence and are left unchanged. The wrapper-scoped values do not persist after the invocation, and secret values are never written into generated campaign YAML.

All application builds use the fixed wolfBoot-relocated layout. Release is the default compiler configuration. Add `--debug` when Debug compiler settings are required; the flash addresses remain unchanged.

Resolve a campaign before using the experiment runner. Generated cases are the only operational experiment inputs:

```powershell
.\scripts\dev.ps1 python scripts/resolve_campaign.py baseline.yaml
$case = Get-ChildItem ".pqc-generated-state/campaigns/baseline/cases/0001_*.yaml" | Select-Object -First 1
$path = (Resolve-Path -Relative $case.FullName) -replace '\\','/'
.\scripts\dev.ps1 experiment status --experiment $path
.\scripts\dev.ps1 experiment build --experiment $path
.\scripts\dev.ps1 experiment-gateway run --experiment $path
```

Host-native diagnostic fallback:

```powershell
cmake --preset Release
cmake --build --preset Release
cmake --preset Debug
cmake --build --preset Debug
python -m pytest tests/integration/test_local_build_in.py -m integration --pqc-require-local-build
```

SSH/SCP uses runtime-mounted SSH access. Gateway and hardware workflows remain gateway-mediated; containers do not receive direct UART devices, ST-LINK/USB passthrough, or Wi-Fi-module passthrough.

## Dependency ownership

Application TLS/wolfCrypt builds use the top-level `Middlewares/Third_Party/wolfSSL` submodule. `tools/wolfboot/lib/wolfssl` is wolfBoot's own nested dependency and must not be used as the source of application TLS changes.

When wolfSSL application sources change, commit and push the change inside `Middlewares/Third_Party/wolfSSL` first, then commit the updated submodule SHA in this repository. Detailed dependency ownership is documented in `docs/007_framework_architecture.md`.

## Secure-boot example

When no secure-boot algorithm is specified, the framework uses wolfBoot with `integrity_sha256`. This verifies the application SHA-256 digest but performs no signature or signing-key authentication. It therefore does not require or resolve a signing tuple.

A named algorithm implies wolfBoot; `--boot-mode wolfboot` is not required.

For secure-boot runs, resolve the `secure_boot` campaign and execute the selected generated case. The case already carries its secure-boot selection, so `--boot-algorithm` is normally unnecessary:

```powershell
.\scripts\dev.ps1 python scripts/resolve_campaign.py secure_boot.yaml
$case = Get-ChildItem ".pqc-generated-state/campaigns/secure_boot/cases/0012_*.yaml" | Select-Object -First 1
$path = (Resolve-Path -Relative $case.FullName) -replace '\\','/'
.\scripts\dev.ps1 experiment-gateway run --experiment $path
```

ML-DSA-44, ML-DSA-65, and ML-DSA-87 are explicit non-default signing evaluation profiles. Release and Debug share the same relocated layout:

```text
wolfBoot primary slot:    0x08020000
manifest/header reserve:  0x00003000
application vector table: 0x08023000
```

For manual packaging, create the framework-recorded Release build before signing:

```powershell
.\scripts\dev.ps1 experiment build --experiment $path
.\scripts\dev.ps1 experiment sign-application
```

Detailed commands and signing-tuple rules are owned by `docs/005_remote_flash_workflow.md`.

## MQTT and broker orientation

The repository includes plaintext, classical TLS, and hybrid PQC MQTT experiment profiles. Use `experiment/mqtt-broker/README.md` for certificate provisioning, deployment, broker lifecycle, and host-side validation.

Provision all configured X.509 research profiles once before running TLS experiments:

```powershell
.\scripts\dev.ps1 python scripts/provision_certificates.py
```

Profiles are declared under `configs/tls_auth/` and generated directly under ignored `secrets/certificates/<profile-id>/`. Experiments never create or renew certificates; a missing selected profile is a prerequisite failure.

Networked profiles can retain `gateway-network-capture.pcap` and `gateway-network-capture.log`. Packet capture is supporting evidence only; correlate it with UART, broker, subscriber, and manifest evidence. Setup and inspection details are in `docs/002_host_gateway_setup.md` and `docs/005_remote_flash_workflow.md`.

## Safety and evidence

Private signing keys and generated credentials must not be committed or baked into the image. Disposable experiment signing and certificate material selected by an owning workflow may be retained only in ignored result directories with a SHA-256 material inventory. SSH/VPN keys, tokens, production credentials, unrelated host credentials, and real `.env` files must not be copied into results, committed, packaged, or baked into images. Result archives that retain disposable private keys are intentionally self-contained but sensitive; review their material inventory before sharing and do not publish them unchanged.

Generated-state preflight is the primary compatibility and provenance mechanism. Pytest cleanup is supplementary cross-platform hygiene. Workflows must never silently reconstruct partial signing state.

Do not claim build, signing, flashing, hardware, UART, network, MQTT/TLS, timing, memory, or end-to-end success without explicit logs, manifests, or equivalent evidence. A skipped capability-gated test is not evidence of success.

Opt-in physical MQTT experiment matrix:

```powershell
.\scripts\dev.ps1 pytest-hardware `
    tests/hardware/test_mqtt_experiment_matrix_hw.py `
    -m hardware `
    --pqc-require-hardware `
    --pqc-hardware-experiment-matrix
```

This long matrix covers direct-flash and wolfBoot execution for plaintext and classical mutual TLS, plus PQC-hybrid mutual TLS with ML-DSA-65 secure boot.

## Canonical TLS and workload campaigns

TLS key exchange, authentication, secure boot, PQ-only TLS, Ready Metrics 2, and network-condition selection are expressed as canonical campaigns rather than concrete experiment-file Cartesian products. Resolve a campaign and run the generated case you need:

```powershell
.\scripts\dev.ps1 python scripts/resolve_campaign.py tls_key_exchange.yaml
$case = Get-ChildItem ".pqc-generated-state/campaigns/tls_key_exchange/cases/0006_*.yaml" | Select-Object -First 1
$path = (Resolve-Path -Relative $case.FullName) -replace '\\','/'
.\scripts\dev.ps1 experiment-gateway run --experiment $path
```

The `tls_key_exchange` campaign contains the four classical, three hybrid ML-KEM, and three standalone ML-KEM groups. `tls_authentication` varies the canonical certificate/authentication profile and server/mutual mode. `tls_pq_only` contains the two principal `ML_KEM_768` + `mldsa65` conditions. `secure_boot` contains the twelve wolfBoot selections.

Ready Metrics 2 is owned by `configs/workloads/ready_metrics_2.yaml`. Its default transfer is 200 KiB with 400-byte chunks. Campaign matrix keys may override workload fields without creating duplicate experiment YAML.

Network conditions are selected through `configs/network_conditions/` and the `network_degradation` campaign. Resolve that campaign, then execute generated cases through the normal experiment runner; impairment applies only to the dedicated experiment interface and must remain isolated from reporting/control traffic.

Final ready-metrics RAM evidence is emitted after the measured workload. `PQC_RAM_LINKER_ACCOUNTING` reports static/linker-region capacity and reservation, while `PQC_MEMORY_HIGH_WATERMARK` reports FreeRTOS heap, ML-DSA RAM3 workspace, newlib `_sbrk`, and application MSP high-water values. The linker now reserves 1280 bytes (`0x500`) for the MSP; runtime evidence still reports the actual measured peak and remaining headroom. Pre-`main()` startup stack depth remains outside this measurement.

## Canonical versioned configuration resolver

The source-controlled experiment configuration is now organised by independently selectable profile domain under `configs/targets`, `configs/gateways`, `configs/instruments`, `configs/services`, `configs/workloads`, `configs/tls_kex`, `configs/tls_auth`, `configs/secure_boot`, `configs/network_conditions`, and `configs/campaigns`. Legacy concrete experiment, board/host/boot, algorithm, wolfBoot-template, certificate-profile, and experiment-grid trees have been retired. Generated campaign cases are the only operational experiment inputs.

When `experiment.py run` consumes a canonical generated case, the case's `choices.secure_boot` selection is carried automatically into the wolfBoot build/sign/flash path. An explicit conflicting secure-boot selection is rejected before hardware side effects.

Preview/materialise a campaign without hardware access:

```powershell
.\scripts\dev.ps1 python scripts/resolve_campaign.py tls_key_exchange
```

Generated cases are written below `.pqc-generated-state/campaigns/` and contain profile identities, non-secret resolved choices, content hashes, configuration identity, and firmware identity. Wi-Fi secret values are resolved only when a generated case is consumed for execution. Set `PQC_WIFI_SSID` and `PQC_WIFI_PSK` in the local execution environment or in the Git-ignored repository-root `.env` copied from `.env.sample`. They are not written into generated case YAML.

Ready Metrics 2 defaults are owned by `configs/workloads/ready_metrics_2.yaml`: `payload_bytes=204800` and `chunk_bytes=400`. Campaigns may vary them using matrix keys `workload.transfer.payload_bytes` and `workload.transfer.chunk_bytes` without duplicating the workload profile.

The TLS KEX catalogue contains the four classical, three hybrid ML-KEM, and three standalone ML-KEM groups. Standalone `ML_KEM_512`, `ML_KEM_768`, and `ML_KEM_1024` use wolfSSL standalone ML-KEM TLS support and are not treated as hybrid groups. The principal PQ-only TLS condition is `ML_KEM_768` with `mldsa65`; `auth_mode` remains independently selectable as `server` or `mutual`.
