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
python -m pytest tests/integration/test_local_build_in.py -m integration --pqc-require-local-build
```

SSH/SCP uses runtime-mounted SSH access. Gateway and hardware workflows remain gateway-mediated; containers do not receive direct UART devices, ST-LINK/USB passthrough, or Wi-Fi-module passthrough. Remote gateway orchestration uses the configured SSH user and FQDN (`timk@pqc-gateway1.pqcnet`); the short alias is display-only and must not be relied on for container DNS resolution. Remote commands never fall back to the container user.

## Dependency ownership

Application TLS/wolfCrypt builds use the top-level `Middlewares/Third_Party/wolfSSL` submodule. `tools/wolfboot/lib/wolfssl` is wolfBoot's own nested dependency and must not be used as the source of application TLS changes.

When wolfSSL application sources change, commit and push the change inside `Middlewares/Third_Party/wolfSSL` first, then commit the updated submodule SHA in this repository. Detailed dependency ownership is documented in `docs/007_framework_architecture.md`.

## Secure-boot example

When no secure-boot algorithm is specified, the framework uses wolfBoot with `integrity_sha256`. This verifies the application SHA-256 digest but performs no signature or signing-key authentication. It therefore does not require or resolve a signing tuple.

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

Provision all configured X.509 research profiles once before running TLS experiments:

```powershell
.\scripts\dev.ps1 python scripts/provision_certificates.py
```

Profiles are declared under `configs/certificate_profile/` and generated directly under ignored `secrets/certificates/<profile-id>/`. Experiments never create or renew certificates; a missing selected profile is a prerequisite failure.

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

## MQTT TLS key-exchange profile matrix

Each TLS group has server-authentication and mutual-authentication profiles. The selected group controls wolfSSL source inclusion and named-group advertisement; unrelated ECC, X25519, and ML-KEM implementations are excluded from that firmware build.

Profiles are named `mqtt_tls_<group>_<server_auth|mutual_auth>_st67_e2e.yaml` under `configs/experiments/`, with groups `x25519`, `secp256r1`, `secp384r1`, `secp521r1`, `X25519MLKEM768`, `SecP256r1MLKEM768`, and `SecP384r1MLKEM1024`. Run any profile with:

```powershell
.\scripts\dev.ps1 experiment-gateway run `
    --experiment configs/experiments/<profile>.yaml
```

The same experiment profiles support `--boot-mode wolfboot --boot-algorithm <algorithm>`. Secure-boot selection is independent of the MQTT TLS key-exchange group.

Do not increase task stacks or `configTOTAL_HEAP_SIZE` from compile-time expectations alone. Compare retained UART heap-boundary and task stack high-water markers for each group, especially `SecP384r1MLKEM1024`; increase memory only when recorded minimum headroom violates the project threshold or allocation failures occur.
Final ready-metrics RAM evidence is emitted after the measured workload. `PQC_RAM_LINKER_ACCOUNTING` reports static/linker-region capacity and reservation, while `PQC_MEMORY_HIGH_WATERMARK` reports FreeRTOS heap, ML-DSA RAM3 workspace, newlib `_sbrk`, and application MSP high-water values. Treat statically backed heap/workspace reservations and their runtime peaks as two views of the same RAM rather than additive usage. MSP watermarking begins at early `main()` and paints the otherwise-unused primary-RAM interval above the static image, excluding any range already or subsequently used by `_sbrk`; this allows measured MSP demand to exceed the linker's `_Min_Stack_Size` reservation. The marker reports excess beyond that reservation and whether the observable watermark window saturated; when saturated, the derived observed-RAM requirement is explicitly a lower bound. Pre-`main()` startup stack depth remains outside this measurement.

### Ready-metrics MQTT application profiles

The original profiles retain `mqtt_validation`. Matching persistent ready/timing/memory profiles are under `configs/experiments/applications/ready_metrics/`, prefixed with `ready_metrics_`; they preserve the corresponding transport, group, and authentication mode while selecting `mqtt_ready_metrics`. Ready Metrics 2 is a separate application-performance workload under `configs/experiments/applications/ready_metrics_2/`. It retains the MQTT connection TTFB (`TCP connect start -> first plaintext CONNACK byte`) and adds a paper-aligned broker-mediated download: after MQTT CONNECT/SUBSCRIBE the STM32 sends a small request, a gateway-side responder publishes the configured payload through the broker, application TTFB ends on the first requested payload byte, and TTLB ends on the last requested payload byte. Both application metrics use the same TCP-connect origin and exclude DNS. The default payload is 200 KiB and is profile-configurable. Absolute Web/EC2 and STM32/MQTT values are not assumed interchangeable because MQTT adds protocol setup and the platform/stack differ. Firmware-boot, TLS, phase, primitive, X.509, memory, application-TTFB, and TTLB evidence are published to the broker only after the measured transfer.

### Controlled network-degradation grid

Preview the 288-run TLS handshake/first-telemetry matrix without accessing hardware:

```powershell
.\scripts\dev.ps1 python scripts/network_degradation_grid.py `
    --interface <DEDICATED_EXPERIMENT_INTERFACE> `
    --plan-only
```

Execute one repetition through the gateway:

```powershell
.\scripts\dev.ps1 python-gateway scripts/network_degradation_grid.py `
    --interface <DEDICATED_EXPERIMENT_INTERFACE>
```

The interface must be the dedicated STM32 experiment-facing interface and must not carry SSH or VPN management traffic. The runner groups selected cases by crypto profile. Each selected profile performs one normal build, flash, and smoke-test run; subsequent degradation cases use `--runtime-only`, reset the already-flashed STM32, and collect independent UART, packet-capture, MQTT broker-log, impairment, and timing evidence without rebuilding, reflashing, reprovisioning certificates, or copying firmware artifacts into every measurement result. Each measurement manifest references the successful profile-preparation manifest and firmware SHA-256.

Select subsets without editing the canonical grid. Selectors may be repeated:

```powershell
.\scripts\dev.ps1 python-gateway scripts/network_degradation_grid.py `
    --interface <DEDICATED_EXPERIMENT_INTERFACE> `
    --profile secp256r1_server_auth `
    --rate-kbit 40 `
    --rtt-ms 200 `
    --loss-percent 0 `
    --loss-percent 1 `
    --loss-percent 5 `
    --loss-percent 10 `
    --mtu 1280
```

`--case-offset` and `--case-limit` provide additional bounded chunking after filtering. The command writes its expanded plan under `.pqc-generated-state/network-degradation-grid/`.

## Canonical versioned configuration resolver

The source-controlled experiment configuration is now organised by independently selectable profile domain under `configs/targets`, `configs/gateways`, `configs/instruments`, `configs/services`, `configs/workloads`, `configs/tls_kex`, `configs/tls_auth`, `configs/secure_boot`, `configs/network_conditions`, and `configs/campaigns`. Legacy concrete experiment YAMLs remain temporarily for migration/equivalence coverage; new campaigns must use the canonical profiles rather than adding another concrete Cartesian-product experiment file.

When `experiment.py run` consumes a canonical generated case, the case's `choices.secure_boot` selection is carried automatically into the wolfBoot build/sign/flash path. An explicit `--boot-algorithm` remains an override. Legacy experiment YAMLs that do not contain a canonical secure-boot selection retain the `integrity_sha256` default.

Preview/materialise a campaign without hardware access:

```powershell
.\scripts\dev.ps1 python scripts/resolve_campaign.py tls_key_exchange
```

Generated cases are written below `.pqc-generated-state/campaigns/` and contain profile identities, non-secret resolved choices, content hashes, configuration identity, and firmware identity. Wi-Fi secret values are resolved only when a generated case is consumed for execution; set `PQC_WIFI_SSID` and `PQC_WIFI_PSK` in the local execution environment. They are not written into generated case YAML.

Ready Metrics 2 defaults are owned by `configs/workloads/ready_metrics_2.yaml`: `payload_bytes=204800` and `chunk_bytes=400`. Campaigns may vary them using matrix keys `workload.transfer.payload_bytes` and `workload.transfer.chunk_bytes` without duplicating the workload profile.

The TLS KEX catalogue contains the four classical, three hybrid ML-KEM, and three standalone ML-KEM groups. Standalone `ML_KEM_512`, `ML_KEM_768`, and `ML_KEM_1024` use wolfSSL standalone ML-KEM TLS support and are not treated as hybrid groups. The principal PQ-only TLS condition is `ML_KEM_768` with `mldsa65`; `auth_mode` remains independently selectable as `server` or `mutual`.
