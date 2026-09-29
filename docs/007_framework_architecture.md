# Framework Architecture

## Purpose

This document maps the current repository architecture to implemented framework behaviour.

## Request 1 — pre-scheduler wolfCrypt benchmark boundary

The `baremetal_benchmark` workload builds a dedicated pre-scheduler measurement
phase using the application wolfCrypt submodule/configuration and a separate
SRAM3 allocator. It records DWT cycles before any RTOS/network activity and
flushes records after the last cryptographic interval through the normal STM32
plaintext reporting collector. The benchmark suite is independent of the
existing **secure-boot** `configs/benchmarks/classical_signing_profiles.yaml`
aggregation. Raw primitive records belong to the `stm32_result_stream` artifact;
there are no metric-specific top-level run-manifest values. The benchmark
build selects ML-DSA-65 deterministic keygen/sign/verify independently of
regular TLS workload algorithm selection, with ten repetitions and a strict
post-run raw-cycle summary tool. ML-DSA hardware acceptance remains pending
until a strict hardware test records successful ML-DSA operations and retained
collector evidence. Regular TLS hardware regression must be run separately;
the source-level isolation check alone is insufficient. See
`docs/baremetal_benchmark_measurement_core.md` for operation boundaries and
example commands. No hardware or PQM4 equivalence is claimed from build-only
or host-unit evidence.

## System capability overview

Implemented:

1. CubeMX STM32 HAL/FreeRTOS firmware project at repository root.
2. Direct-flash baseline experiment workflow.
3. Local build automation and build records.
4. Remote gateway flash workflow.
5. UART capture and marker evaluation.
6. wolfBoot secure-boot build/sign/flash workflow.
7. Secure-boot benchmark evidence model.
8. Classical signing-algorithm benchmark profiles.
9. ML-DSA-44 and ML-DSA-65 secure-boot benchmark profiles using the existing 12288-byte image-header reserve.
10. Cross-profile benchmark aggregation output.
11. Post-secureboot application scheduler template using CMSIS-RTOS v2 FreeRTOS.
12. Gateway MQTT broker Docker Compose project with classical MQTT-over-TLS and an experimental OQS Mosquitto profile.
13. MQTT/TLS architecture documentation split between hardware-independent STM32-local lwIP/wolfSSL/wolfMQTT preparation and future ST67W61M1-backed validation.
14. Docker-hosted Linux default workflow for Python validation, STM32 direct/relocated builds, wolfBoot builds, application signing, pytest, and gateway-mediated hardware experiments.
15. GitHub Actions CI preserving existing runner-compatible and MQTT broker Docker runtime jobs while using the containerised non-hardware job as the default reproducible software-build validation path.
16. Selectable wolfBoot firmware modes: `single_bank`, `dual_bank_no_ota`, and `dual_bank_ota`, with build-time exclusion of unused OTA, multi-key, or BFB2-switching paths.
17. Authenticated dual-bank OTA over the impairment-exempt reporting plane, including complete inactive-bank staging, hash verification, hardware bank activation, candidate confirmation, and rollback of an unconfirmed candidate.

Current boundaries not yet fully verified or completed:

1. Complete recorded end-to-end hardware verification of every classical and PQC/hybrid STM32 MQTT-over-TLS profile remains capability-gated; DTR-007 through DTR-010 record the outstanding evidence.
2. Network degradation includes source-level effective-state checks and capability-gated STM32 hardware assertions; the live gateway, reporting-path and ESP32 qualification remains deferred under DTR-008.
3. Hybrid signing profiles and ML-DSA-87 remain unavailable under the current 12288-byte image-header reserve.
4. Production release packaging remains outside the current capability set.

The repository now contains a real STM32/ST67 MQTT/TLS runtime path: ST67W61M1 association/DHCP, lwIP sockets, wolfSSL TLS 1.3 transport/session and certificate verification, and wolfMQTT connect/publish workflows are implemented. These implementation capabilities must still be distinguished from completed end-to-end hardware evidence for a particular profile; deferred verification status is recorded in the consolidated register below.

### Plaintext MQTT validation campaign

`configs/campaigns/mqtt_plaintext_validation.yaml` selects the `mqtt_validation` workload with
`mqtt_transport: plaintext`. The resolver derives the ST67/lwIP socket evidence class,
port 1883 on the experiment broker, and a disabled TLS workload while keeping the
separate impairment-exempt reporting broker. Legacy TLS campaigns retain their
existing default transport. The `secp256r1`/`rsa3072` fields in this plaintext
campaign are inert compatibility selections for the current resolver schema; they
do not indicate a TLS handshake or certificate-backed workload. The two MQTT
hardware assertions share one experiment within their file; full STM32 MQTT
success and evidence retention remain subject to the recorded hardware test result.

## Architectural organization

The architecture is organized by stable capability and evidence ownership rather than implementation chronology.  This document owns the current system layers, firmware and framework boundaries, evidence model, generated-state architecture, test architecture, capability matrix, and deferred-test register.

### External dependency ownership

The STM32 application and wolfBoot intentionally use separate wolfSSL checkouts with different ownership:

```text
Middlewares/Third_Party/wolfSSL
    Application TLS/wolfCrypt source of truth.
    Top-level Git submodule backed by the project-controlled wolfssl-embedded repository.
    CMake application TLS builds, application-side wolfSSL instrumentation, and application TLS fixes belong here.

tools/wolfboot
    Project-controlled wolfBoot fork used by the framework for STM32L4R5-specific dual-bank OTA and bootloader changes.
    The parent repository records an exact gitlink/SHA for reproducibility.

tools/wolfboot/lib/wolfssl
    wolfBoot-owned nested wolfSSL dependency.
    It follows the wolfBoot revision and is not the source of truth for STM32 application TLS changes.
```

Application work must not patch `tools/wolfboot/lib/wolfssl` merely because the same upstream wolfSSL files also exist there. The application build resolves `PQC_WOLFSSL_SOURCE_DIR` to `Middlewares/Third_Party/wolfSSL`.

Because `Middlewares/Third_Party/wolfSSL` is a Git submodule, durable source changes use a two-repository workflow: commit and push the wolfSSL source change in the wolfSSL submodule first, then commit the updated wolfSSL gitlink/SHA in `PQC-Framework-02`. A parent commit cannot preserve uncommitted source edits inside the submodule.

The top-level dependency policy is:

- `Middlewares/Third_Party/wolfSSL` uses the project-controlled `https://github.com/timkohlman1/wolfssl-embedded.git` fork and is pinned by the parent repository to an exact commit. The configured tracking branch is `pqc-signing-tls-wolfssl`; reproducibility still comes from the recorded gitlink SHA.
- `tools/wolfboot` uses the project-controlled `https://github.com/timkohlman1/wolfBoot.git` fork and is pinned by the parent repository to an exact commit. Framework-owned wolfBoot source changes, including dual-bank OTA support, must be committed and pushed to this fork before the parent gitlink is advanced. The official `wolfSSL/wolfBoot` repository may be retained locally as an `upstream` remote for maintenance.
- `Middlewares/Third_Party/wolfMQTT` remains the public `https://github.com/wolfSSL/wolfMQTT.git` dependency pinned to an exact upstream commit because the framework does not currently carry project-specific wolfMQTT source changes.

For any project-modified top-level submodule, durable source changes use a two-repository workflow: commit and push the source change in the submodule repository first, then commit the updated submodule gitlink/SHA in `PQC-Framework-02`. A parent commit cannot preserve uncommitted or unreachable source edits inside a submodule. A clean clone is reproducible only when the recorded SHA is fetchable from the URL in the parent `.gitmodules`.

wolfBoot-specific temporary source adjustments remain owned by `scripts/framework/wolfboot_build.py` where implemented. Those build-time patches do not make wolfBoot's nested wolfSSL checkout the application dependency. wolfBoot's own nested submodules remain upstream-owned unless separately documented and modified.

## Canonical current capability matrix

This matrix is the canonical detailed implementation-status reference. A supported cell identifies the strongest evidence currently represented by inspected repository sources, configs, and tests; it does not promote that evidence into another layer.

| Capability | Build-only | STM32-local runtime | Host-side | Broker-side | Gateway/hardware | Evidence class or boundary | Current limitation |
|---|---|---|---|---|---|---|---|
| Direct-flash HAL/FreeRTOS application | Supported | Supported through explicit boot, scheduler, task, and tick UART markers | Framework orchestration | Not applicable | Supported through gateway-mediated flash/UART workflows when capability is available | STM32 runtime and gateway/hardware evidence | Hardware success requires explicit logs or manifests; container builds alone are software-build evidence |
| FreeRTOS scheduler and task execution | Supported | Supported through scheduler-start and default-task markers | Not applicable | Not applicable | Capability-gated UART validation | STM32-local runtime | No network capability follows from scheduler/task execution |
| wolfBoot secure-boot build, signing, and flashing | Supported for configured profiles | Supported when explicit secure-boot UART evidence is captured | Build/sign orchestration | Not applicable | Gateway-mediated two-artifact flash and UART workflows | Build, signing, and secure-boot hardware evidence | Runtime success, timing, and memory require explicit firmware/UART/manifest evidence |
| Classical secure-boot profiles | Supported: ECC256, ECC384, ECC521, ED25519, ED448, RSA2048, RSA3072, RSA4096 | Supported through capability-gated secure-boot runs | Build/sign/aggregation tooling | Not applicable | Capability-gated hardware benchmark workflows | Secure-boot benchmark evidence | Profile comparison is valid only under the documented common measurement model |
| ML-DSA secure-boot profiles | Supported: ML-DSA-44 and ML-DSA-65 | Supported through capability-gated secure-boot runs | Build/sign/aggregation tooling | Not applicable | Capability-gated hardware benchmark workflows | Secure-boot benchmark evidence | ML-DSA-87 remains unavailable under the current 12288-byte image-header reserve |
| Secure-boot benchmark collection and aggregation | Static build/sign metrics supported | Runtime timing/cycles/result/stack only when explicit markers exist | Aggregation to JSON/CSV | Not applicable | Hardware samples capability-gated | Manifest-backed benchmark evidence | Host duration, UART duration, linker output, or ELF output alone are not runtime evidence |
| MQTT/TLS config and result schema | Supported | No protocol runtime implied | Supported by framework validation | Not applicable | Not applicable | `fake_no_network`, `host_side`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1_backed` schema classes | Schema acceptance is not network, TLS, MQTT, or hardware success |
| Deterministic fake/no-network MQTT transport | Supported | Not an STM32 network path | Supported as simulated control-flow execution | No real broker used | No gateway/hardware required | `fake/no-network transport evidence` | Connect, publish, timeout, disconnect, and reconnect outcomes are simulated only |
| Classical MQTT broker Compose profile | Supported | Not applicable | Host clients may validate it | Supported with temporary classical mutual-TLS material | Gateway deployment and validation are capability-gated | Broker-side and host-side evidence | Does not prove STM32, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, Wi-Fi, or end-to-end wireless success |
| Experimental OQS MQTT broker profile | Supported | Not applicable | OQS-capable host validation supported where tooling is available | Supported as an experimental protocol-evaluation profile | Gateway deployment and validation are capability-gated | Broker-side and host-side experimental evidence | Not production TLS and not STM32 or wireless evidence |
| Native host wolfMQTT/wolfSSL broker validation | Supported as a native host target | Not applicable | Supported, including structured compatibility markers | Uses the configured broker | Local or gateway broker checks are capability-gated | `host_side` MQTT-over-TLS compatibility evidence | Must keep all STM32, ST67W61M1, and end-to-end wireless claims false |
| STM32 lwIP/ST67W6X source integration | Supported in direct and relocated firmware builds | Module initialization and bounded Wi-Fi RF scan supported; local lwIP helper smoke remains separate | Not applicable | Not applicable | Capability-gated UART validation | STM32 build evidence plus `stm32-st67-wifi-rf-scan-only` hardware evidence | Module initialization and RF scan do not prove association, link, hardware IP, TCP, TLS, or MQTT |
| STM32 lwIP network-interface boundary | Supported | Supported only as unattached local `netif` state observation | Not applicable | Not applicable | Optional UART evidence is capability-gated | `lwip-netif-state-only`; unavailable-boundary evidence | No `netif_add`, link-up, DHCP, socket, external network, or ST67W61M1 access |
| STM32 wolfSSL TLS 1.3 runtime | Supported in direct and relocated firmware builds with profile-selected algorithms | Real client context/session creation, CA loading, peer-name verification, lwIP socket I/O, TLS 1.3 handshake, negotiated-group verification, and in-RAM handshake instrumentation are implemented | Not applicable | Broker profiles exist separately | Gateway/hardware evidence is capability-gated per profile | STM32 runtime plus deferred end-to-end hardware evidence | A built runtime path does not by itself prove a specific experiment completed; use retained UART/manifests/broker evidence |
| STM32 wolfSSL transport boundary | Supported | Project-owned transport uses lwIP/ST67-backed socket callbacks for wolfSSL read/write in TLS profiles | Not applicable | Not applicable | Capability-gated hardware verification | STM32 runtime transport evidence | Transport success for a profile requires explicit runtime evidence and cannot be inferred from compilation |
| STM32 wolfMQTT integration | Supported: pinned wolfMQTT client, packet, socket callback layers, and selectable application workloads build and link | Real TCP/TLS MQTT connect and publish workflow is implemented for ST67-backed profiles; fake/no-network coverage remains a separate evidence class | Separate native host validation exists but is not STM32 evidence | Managed broker profiles supported | End-to-end verification is capability-gated | STM32 runtime plus broker/gateway evidence when recorded | Runtime success must be established from retained experiment evidence, not build-only or host-side validation |
| ST67W61M1 hardware-backed network backend | Driver and interface sources build in direct and relocated profiles | Association and DHCP-supported runtime | Not applicable | No broker used by this path | Capability-gated known-image UART and manifest evidence supported | `stm32-st67-wifi-association-dhcp` | Proves configured-AP association and DHCP IPv4 assignment only; external TCP, TLS handshake, MQTT, broker reachability, and end-to-end protocol success remain unavailable |
| Real classical STM32 MQTT-over-TLS | Implemented | ST67/lwIP/wolfSSL/wolfMQTT runtime path implemented | Host-side compatibility exists separately | Classical broker profiles supported | End-to-end hardware verification remains tracked by DTR-007 | Hardware-backed STM32 runtime capability with deferred profile verification | A successful build or partial TLS progress is not complete end-to-end evidence |
| PQC or hybrid STM32 MQTT-over-TLS | Profile-selected ML-KEM/hybrid wolfSSL builds implemented | Hybrid TLS 1.3 runtime path and group verification implemented | Host/broker validation supported separately | Hybrid broker profiles supported | End-to-end hardware verification remains tracked by DTR-009/DTR-010 | STM32 PQC/hybrid runtime capability with deferred profile verification | Classical fallback is not accepted as PQC evidence; retained negotiated-group/runtime evidence is required |


## Source and configuration map

```text
CMakeLists.txt                              Firmware build definition
CMakePresets.json                           Debug and Release presets
STM32L4R5XX_FLASH.ld                        Direct-flash linker script
STM32L4R5XX_FLASH_RELOCATED.ld              Secure-boot relocated linker script
Core/                                       CubeMX HAL/FreeRTOS application source
Drivers/                                    CubeMX HAL/CMSIS drivers
Middlewares/Third_Party/FreeRTOS/           CubeMX-generated FreeRTOS middleware
Middlewares/Third_Party/wolfSSL/            Project-controlled application TLS/wolfCrypt submodule
Middlewares/Third_Party/wolfMQTT/           Public upstream wolfMQTT submodule pinned by exact parent gitlink SHA
tools/wolfboot/                              Project-controlled wolfBoot fork pinned by exact parent gitlink SHA; owns its nested lib/wolfssl dependency
configs/targets/stm32l4r5_st67.yaml          Board, MCU, UART, build and wolfBoot target metadata
configs/gateways/pqc_gateway1.yaml                  Gateway, flash helper, UART path
canonical generated-case direct-flash compatibility metadata              Direct-flash boot profile
configs/targets/stm32l4r5_wolfboot.yaml   Shared wolfBoot target, layout, build, signing, and experiment defaults
configs/secure_boot/*.yaml                    Canonical per-algorithm wolfBoot and signing differences
.pqc-generated-state/campaigns/baseline/cases/<case>.yaml
.pqc-generated-state/campaigns/secure_boot/cases/<case>.yaml   Generic secure-boot experiment entry point
configs/benchmarks/classical_signing_profiles.yaml
resolver-generated tools/wolfboot/.config         Project-local wolfBoot config templates
experiment/mqtt-broker/                      Gateway MQTT broker compose project
docker/python/Dockerfile                    Non-hardware Python, STM32, wolfBoot, and signing container baseline
.dockerignore                               Container build-context exclusions for generated output and secrets
.github/workflows/ci.yml                    CI workflow with runner-compatible, MQTT broker Docker runtime, and containerised non-hardware jobs
requirements-dev.txt                        Python development dependencies for unit-test validation
```

### Composed secure-boot profiles

The benchmark model is also consolidated. `configs/benchmarks/classical_signing_profiles.yaml` is a benchmark-suite declaration containing algorithm IDs and shared evidence rules only. Algorithm properties, wolfBoot values, and signing paths are resolved directly from `configs/secure_boot/`; they are not repeated in the benchmark suite.


Secure-boot configuration uses two canonical sources. `configs/targets/stm32l4r5_wolfboot.yaml` owns values common to the STM32L4R5 wolfBoot target, including layout, common build inputs, signing defaults, and shared experiment behaviour. `configs/secure_boot/<algorithm>.yaml` owns each algorithm's wolfBoot identifier, key and signature properties, config template, signing arguments, tuple paths, and algorithm-specific evidence metadata.

Secure-boot commands select an algorithm ID and resolve the requested build, signing, experiment, or boot section directly from the canonical target and algorithm profiles. `.pqc-generated-state/campaigns/secure_boot/cases/<case>.yaml` is the single secure-boot experiment entry point. The former per-algorithm build, signing, boot, and experiment wrapper files have been removed. Direct-flash and MQTT experiment profiles remain standalone.

```

## Python implementation map

```text
scripts/experiment.py                       Per-run experiment CLI/authority
scripts/export_timing_dataset.py            Offline run inventory/timing CSV export and verification
scripts/framework/timing_dataset.py         Selected-input integrity, inventory and dataset lineage
scripts/framework/timing_metrics.py         Current deferred-record decoding and A1 scalar formulas
scripts/framework/timing_dataset_schema.py  Versioned columns, units, nulls and metric definitions
scripts/framework/timing_dataset_loader.py  Typed loading and notebook-ready timing view
scripts/run_campaign.py                     First-class campaign execution CLI
scripts/framework/artifacts.py              Result artifact helpers
scripts/framework/benchmark_aggregation.py  Benchmark summary JSON/CSV generation
scripts/framework/build.py                  Local CMake build workflow
scripts/framework/build_number.py           Build number state handling
scripts/framework/build_records.py          First-class build record validation/use
scripts/framework/build_state.py            Last-successful-build state
scripts/framework/campaign_executor.py       Campaign grouping/reuse/repetition/resume orchestration
scripts/framework/fingerprint.py            Secure-boot and signing evidence fingerprints
scripts/framework/flash.py                  Direct-flash SCP/SSH workflow
scripts/framework/manifest.py               Manifest construction and benchmark schema helpers
scripts/framework/secure_boot_flash.py      wolfBoot two-artifact flash and UART benchmark workflow
scripts/framework/signing.py                Application signing workflow
scripts/framework/source.py                 Git provenance helpers
scripts/framework/uart.py                   Raw UART capture plus explicit legacy/offline parsing helpers
scripts/framework/wolfboot_build.py         wolfBoot build/config/temporary patch workflow
```



## Docker-hosted build/test/experiment baseline

The repository default is Docker-hosted Linux execution through `scripts/dev.sh`. The container definition is `docker/python/Dockerfile`; Python development dependencies are in `requirements-dev.txt`; generated outputs and local secret material are excluded from the build context by `.dockerignore`.

The image contains the STM32 build dependencies needed to configure and build the existing `Debug` and `Release` CMake presets, host build tooling needed for wolfBoot/keytools builds, OpenSSL for local certificate provisioning, an SSH client for runtime-provided gateway access, and the tooling needed to run application-signing profiles after the relocated application has been built. The image sets `PQC_CONTAINER=1`; pytest still also detects Docker through `/.dockerenv`.

The default execution model removes the development machine's native build environment from normal framework use. Framework commands, pytest, CMake builds, wolfBoot builds, signing, and gateway-mediated hardware experiments normally run inside the project container. Hardware access remains SSH/SCP-mediated through the gateway, so the container does not need direct ST-LINK/USB passthrough, UART devices, or Wi-Fi-module access. Host-native development-machine builds remain an explicit manual fallback only.

Software-build evidence from the container includes Python test results, safe configuration-validation command output, STM32 build output for direct and relocated firmware profiles, wolfBoot build evidence, and application-signing evidence. Gateway, flashing, UART, MQTT/TLS, timing, memory, benchmark, or end-to-end runtime success still requires explicit logs, manifests, or equivalent evidence from the relevant gateway or hardware workflow.

Application signing inside the container uses the runtime-mounted workspace. Private signing keys and generated signing material must remain local generated state, such as under `secrets/wolfboot/`, and must not be committed, sent in build contexts, copied into replacement artifacts, or baked into images. The container includes an SSH client but no SSH keys, VPN keys, broker credentials, private certificates, private signing keys, or other secrets. Gateway-capable checks require `PQC_CONTAINER_ENABLE_GATEWAY=1` plus runtime-provided SSH configuration, known-hosts data, and credentials; the wrapper commands set this flag only for gateway and hardware subcommands.

Generated-state preflight is the primary compatibility and provenance mechanism for framework build, wolfBoot build, application-signing, and artifact-consuming workflows. Pytest session-start cleanup is supplementary cross-platform hygiene for stale host-specific CMake and wolfBoot object/dependency/host-tool outputs. It does not establish compatibility or provenance and must not remove source files, canonical signing keys under `secrets/wolfboot/`, or reusable wolfBoot signing-tuple members.

### Runtime ownership and private output

`scripts/container_runtime.py` is installed into the development image and is
invoked with isolated Python before any workspace code. `scripts/dev.sh` passes
the invoking non-root UID/GID, supplementary groups and umask for every workload
mode. Only container account/home setup and ownership of verified empty,
separately mounted hardware build/state roots happen before the irreversible
privilege drop. SSH copying and all framework/build/signing/test processes run
as that user. No recursive host-tree ownership repair or root workload fallback
is performed. The private dataset staging-directory policy remains unchanged:
A1 outputs can remain `0700`, now owned by their invoking user.

The separate certificate provisioner shares the drop-to-user helper after its
existing Alpine package installation and before material generation; its mask
is `0077`. Tool/image/package pins, firmware, evidence schemas, capture integrity,
gateway/service privilege policies and signing-tuple lifecycle are unchanged.
See `docs/002_host_gateway_setup.md` for the one-time explicit legacy-output
repair, rebuild instructions and the supported local/non-remapped daemon boundary.

`scripts/check_container_host_user.py`, exposed as `./scripts/dev.sh check-host-user`,
is a stdlib-only host-side Docker integration gate with a temporary workspace
and dummy SSH files. It does not use the user's SSH credentials or reach a gateway.
`tests/unit/test_container_host_user.py` covers identity validation, wrapper modes,
argument/environment preservation, drop ordering, private SSH copying and overlay
refusal cases. `tests/integration/test_container_host_user_in.py` invokes the real
Docker gate where available; CI runs it directly on the host after image build.
CI also verifies host ownership/private directories after its existing provisioning
step. These software checks must not be reported as live gateway or STM32 success.

## Firmware scheduler model

The application firmware uses the CubeMX-generated CMSIS-RTOS v2 FreeRTOS template. `main()` performs HAL initialization, clock configuration, GPIO/UART initialization, and one-time UART evidence marker output before `osKernelStart()`. It also emits FreeRTOS scheduler markers for default task creation and scheduler start. `StartDefaultTask()` emits a task-start marker before it owns the recurring `tick` marker and LED toggle using `osDelay(1000)`. HAL timing is generated from TIM1 rather than SysTick so the FreeRTOS scheduler can own SysTick.

The direct-flash and secure-boot application markers remain part of the UART evidence contract. FreeRTOS task-level stack APIs are enabled for future task instrumentation, but task-level runtime stack/heap values must still be treated as unavailable until explicit firmware markers and manifests record them.


## Default Docker execution model

The default development execution path is Docker-hosted Linux. Framework commands, pytest, CMake firmware builds, wolfBoot builds, application signing, and gateway-mediated hardware experiments should normally be launched through `scripts/dev.sh`. Host-native development-machine builds remain available as an explicit manual fallback, but they are not the reproducible validation gate.

Gateway and hardware workflows are still mediated by SSH/SCP rather than direct USB or UART access from the container:

```text
development host with Docker
  -> project container mounted at /workspace
    -> SSH/SCP to pqc-gateway1.pqcnet using runtime-mounted SSH material
      -> gateway flash/reset/UART helpers
        -> STM32 board
```

This keeps the development machine's local build environment out of the normal experiment path while preserving the existing gateway hardware boundary.

## Direct-flash data flow

```text
experiment config
  -> board/host/boot resolution
  -> CMake build
  -> build record under results/builds/<build_number>/
  -> flash provenance check
  -> gateway SCP/SSH flash helper
  -> UART capture
  -> manifest verdict
```

The direct-flash baseline uses `canonical generated-case direct-flash compatibility metadata` and `.pqc-generated-state/campaigns/baseline/cases/<case>.yaml`.

## Secure-boot data flow

```text
wolfBoot build profile
  -> project-local wolfBoot config template
  -> temporary local wolfBoot patches during build
  -> wolfBoot artifact evidence

Release application build
  -> profile-specific BIN
  -> signing profile
  -> signed application image evidence

secure-boot experiment profile
  -> key-consistency check
  -> flash wolfBoot artifact
  -> flash signed application artifact
  -> UART capture samples
  -> secure_boot_benchmark manifest evidence
```

The secure-boot workflow must not infer timing, stack, heap, or hardware success from host-side behaviour. Runtime metrics must come from explicit firmware/UART markers.

Single-capture `flash-secure-boot` acceptance separates flash/startup evidence
from benchmark eligibility: unavailable aggregate timing does not invalidate
successful flashing and the required application boot markers. Repeated
benchmark runs still require valid timing samples; typed operation diagnostics
are not substituted for aggregate verification measurements. See
`docs/005_remote_flash_workflow.md` for exit-status and hardware-test contracts.


### Request 14 secure-boot timing work in progress (not validated)

The bootloader-local DWT instrumentation records SHA-256 image-integrity and
signature-authenticity function calls as separate operations in a version-4 RAM2
mailbox. The application emits typed UART diagnostic markers, and the host can
parse those raw markers separately from the immutable run-capture manifest.
A missing or zero-cycle record is unavailable, not a zero-cost verification.
The existing 1 MHz LPTIM2/TIM2 reset-origin bridge is unchanged.

**This is not yet a validated secure-boot reference baseline.** The current
function-level records are not bound to a selected image, physical bank, or
verification attempt. They can include candidate-manifest or recovery
verification and must not be aggregated as normal active-application
verification. Complete-image verification excluding intermediate UART output,
bootloader-total execution, application-image SHA-256 identity, and explicit
bootloader source/build provenance are not yet implemented in these records.
The maintained secure-boot hardware matrix and corrupt-image rejection test
remain outstanding; no hardware validity claim follows from the source patch.

Deferred test entry: feature=Request 14 typed secure-boot verification;
missing layer=hardware and gateway integration; reason=requires physical STM32,
controlled corruption and gateway evidence; capability=instrumented wolfBoot,
flash/reset/UART and retained run evidence; intended tests=
`tests/hardware/test_secure_boot_integrity_hw.py` and
`tests/integration/test_secure_boot_integrity_in.py`;
eventual verification=`./scripts/dev.sh pytest-hardware`;
status=deferred pending attempt-bound instrumentation and hardware validation.

## STM32 MQTT/TLS target architecture

MQTT/TLS client development is split between hardware-independent preparation and future ST67W61M1-dependent validation. The target ownership model is:

```text
STM32 firmware
  -> application MQTT/TLS experiment logic
  -> wolfMQTT client layer
  -> wolfSSL TLS endpoint
  -> lwIP TCP/IP stack
  -> network-interface abstraction
  -> future ST67W61M1 Wi-Fi module backend
  -> external MQTT broker
```

The Wi-Fi module is treated as the network interface backend. It must not be documented or implemented as the MQTT client, TLS endpoint, certificate owner, or broker-side validation source. lwIP, wolfSSL, and wolfMQTT are intended to run on the STM32.

Supported planning modes are evidence-bound:

- Fake/no-network transport: deterministic simulated control-flow evidence only.
- Host/socket validation path: host-side client or broker compatibility evidence only.
- STM32 build-only path: compiler/linker evidence only.
- STM32 fake/no-network runtime path: board UART initialization evidence only.
- Current ST67W61M1 Wi-Fi/DHCP path: configured-AP association and DHCP IPv4 evidence only. External TCP and all TLS/MQTT claims remain unavailable until explicitly implemented and validated.
- Future STM32 MQTT-over-TLS path: TLS handshake, MQTT connect, publish, reconnect, timing, and resource evidence only from explicit STM32 UART logs, manifests, and broker logs.

Evidence categories must not be collapsed. Build-only evidence does not imply runtime success. Fake transport evidence does not imply broker, TLS, STM32, or Wi-Fi success. Host-side and broker-side evidence does not imply STM32 success. STM32 UART initialization evidence does not imply Wi-Fi, IP, TCP, TLS, MQTT, publish, reconnect, or end-to-end wireless success.

Current implemented preparation, ST67W61M1 association/DHCP support, and compatibility layers must preserve this boundary as later work adds external TCP readiness, classical STM32 MQTT-over-TLS validation, network degradation, and eventual PQC/hybrid MQTT/TLS experiments.

## Benchmark model

Secure-boot manifests include `secure_boot_benchmark`, which separates:

- profile identity and algorithm metadata
- build-time metrics
- signed-artifact metrics
- runtime verification metrics
- runtime memory metrics
- repeated-run samples
- aggregate statistics
- explicit limitations and unavailable metrics

Benchmark evidence is grouped by source and interpretation:

- Build-time metrics are static wolfBoot artifact measurements. They include `.text`, `.data`, `.bss`, flash-relevant bytes, and static RAM estimate. Static RAM is calculated from `.data + .bss`; it is not runtime stack usage.
- Signed-artifact metrics describe the application image after signing. They include signed size, unsigned size where available, signature size, overhead bytes, and overhead percentage.
- Runtime verification metrics describe firmware-reported verification evidence. Verification time, cycles, bootloader HCLK, result code, and marker sources must come from explicit UART markers.
- Runtime memory metrics describe firmware-reported memory evidence. Stack high-water data is valid only when explicit firmware-side stack markers are present. Heap remains unavailable unless explicit heap evidence is added.
- Repeated-run samples record one verification sample per secure-boot reset/capture. Aggregate statistics use only samples marked valid for statistics.
- Derived metrics such as cycles per KB and time per KB are calculated only when the required source values are available.

Median verification time and cycles are the primary headline metrics for cross-profile comparison. Mean, minimum, maximum, standard deviation, range, and coefficient of variation support repeatability and outlier review. Unavailable fields and limitations are intentional evidence and must remain visible in manifests and aggregated summaries.

Profiles should be compared only when they use the same board, relocated HAL payload, bootloader clock evidence model, UART marker model, repeated-run model, image-header reserve, and measurement sources. Timing, stack, heap, or pass/fail status must not be inferred from host-side duration, SSH duration, reset delay, build logs, ELF files alone, or marker ordering alone.

The aggregation command reads existing manifests and writes:

```text
results/benchmark-aggregation/benchmark_summary.json
results/benchmark-aggregation/benchmark_summary.csv
```

It does not create new measurement evidence.


## MQTT/TLS configuration and result schema

Framework-side MQTT/TLS schema support starts with the Phase M2 configuration/result model. Experiment configs can carry an `mqtt` mapping with schema version, evidence class, transport backend, TLS mode, optional non-secret certificate references, optional host-side broker endpoint, and explicit unavailable metrics. The supported evidence classes are `fake_no_network`, `host_side`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1_backed`. The supported transport backends are `fake_no_network`, `host_socket`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1`.

Phase M3 adds `scripts/framework/mqtt_fake_transport.py` and the `mqtt-fake-transport` CLI command. This path models MQTT client control flow with deterministic simulated outcomes for connect, publish, disconnect, timeout, and reconnect attempts. It writes result evidence under `mqtt_tls.fake_transport`, labels that evidence as `fake/no-network transport evidence`, and keeps all real network, broker, TLS, gateway, UART, STM32 runtime, Wi-Fi, and hardware success flags false.

Phase M5 adds STM32-local lwIP/ST67W6X compile-only preparation to the firmware target. `Core/Inc/pqc_lwip_build_only.h` still defines the project-owned build-only status boundary and `Core/Src/pqc_lwip_build_only.c` keeps runtime networking explicitly unavailable. CubeMX-generated lwIP application files, SICS Network LwIP sources, SPI HAL support, and ST67W6X network-driver sources are now allowed to compile and link in both direct and relocated application builds so the future network-interface layer can be inspected against the real generated interfaces. This remains compile/link evidence only, with one additional non-network lwIP runtime smoke marker emitted over UART. The smoke marker exercises deterministic lwIP version, IPv4 formatting, and checksum helpers only; it does not initialize a netif, use ST67W6X hardware, acquire an IP address, open TCP, run TLS, or perform MQTT. The generated ST67W6X hardware-facing code is present so interfaces can be inspected and future stubs can be scoped, but the firmware does not claim module detection, Wi-Fi association, IP address acquisition, TCP readiness, TLS handshake, MQTT connect, publish, reconnect, network runtime success, or end-to-end wireless success.

STM32 networking is intentionally limited to Ethernet-style IPv4 over the ST67 netif for all experiment profiles. `LWIP/Target/lwipopts.h` fixes `LWIP_IPV6` and the DHCPv6, MLD6, neighbour-discovery, IPv6-forwarding, and IPv6 route-table options to `0`; it also fixes PPP, PPPoE, PPPoS, and PPP over L2TP support to `0`. The generated CMake source list excludes the complete lwIP `src/core/ipv6` set together with bridge, PPP-family, and SLIP translation units, while retaining `src/netif/ethernet.c`. These excluded families are not experiment-profile options and must not be re-enabled without an explicit architecture change.

The UART marker begins with `lwIP runtime smoke:` and includes `network=unavailable`; it is intended to prove that a constrained set of lwIP helper functions executes during the existing 10-second UART capture window without crossing the network-interface boundary. The optional gateway integration test `tests/integration/test_lwip_runtime_smoke_uart_in.py` exercises the baseline build/flash/UART flow and asserts that the marker appears in `uart.log`; this remains helper-call UART evidence only, not ST67W61M1, Wi-Fi, IP, TCP, TLS, MQTT, or end-to-end network evidence.

Phase M10.1 begins hardware-backed ST67W61M1 validation without importing the CubeMX HTTP-server demo application. The default FreeRTOS task registers the minimal ST67 application callbacks, initializes the module through `W6X_Init()`, initializes the Wi-Fi subsystem through `W6X_WiFi_Init()`, and starts a bounded active scan through `W6X_WiFi_Scan()`. UART evidence uses `evidence=stm32-st67-wifi-rf-scan-only`, reports the callback status and access-point count, and deliberately omits SSID and BSSID values. The scan has an 8000 ms timeout and does not attempt association, register a real lwIP netif, start DHCP, open TCP, load certificates, perform a TLS handshake, or invoke MQTT. The ST67 SPI transfer-engine task stack is currently 2048 bytes after the prior 768-byte allocation faulted in the FreeRTOS queue receive path; the final minimum safe size remains unconfirmed because the current UART memory checkpoint measures only `defaultTask`.

The ST67/lwIP transmit boundary follows the X-CUBE-ST67W61 vendor adapter: each segment in a chained lwIP `pbuf` is submitted to `W6X_Netif_output()` in sequence. The framework does not consolidate the chain into a temporary contiguous allocation. The SPI transfer engine remains aligned with the vendor `spi_iface.c` implementation, apart from the CMSIS device include required for `__get_IPSR()` and the enlarged task stack required by observed runtime stack usage.


Current compile-only ST67W61M1 shield pin preparation maps the Arduino connector labels to the NUCLEO-L4R5ZI-P pins as follows: `D13/PA5 SPI1_SCK`, `D12/PA6 SPI1_MISO`, `D11/PA7 SPI1_MOSI`, `D10/PD14 SPI_CS`, `D5/PE11 CHIP_EN`, `D6/PE9 BOOT`, `D3/PE13 SPI_RDY`, and `D2/PF15 USER_BUTTON`. `SPI_RDY` and the relocated user button share `EXTI15_10_IRQn` but use different EXTI lines, 13 and 15 respectively. The generated 120 MHz clock configuration uses SPI1 prescaler 4, giving approximately 30 Mbit/s when SPI1 is fed from the 120 MHz APB2/PCLK2 domain. The earlier prescaler-32 configuration was a temporary diagnostic and is not the supported runtime baseline. The generated lwIP application/demo files are kept in the tree for inspection but filtered out of the historical Phase M5 compile-only CMake path. That compile-only preparation has since been superseded for MQTT experiments by the ST67W61M1-backed runtime path; the retained Phase M5 helper remains build/local-smoke evidence only.

Phase M6.2 introduced the project-owned lwIP network-interface boundary. That historical unattached-netif smoke path remains useful as a bounded local test, but it has been superseded for MQTT experiments by the ST67W61M1-backed association/DHCP and external socket runtime. Documentation must distinguish the local smoke helper from the current network-backed MQTT/TLS path.

Phase M6.0 adds a STM32-local wolfSSL source build-only boundary through `Core/Inc/pqc_wolfssl_build_only.h`, `Core/Src/pqc_wolfssl_build_only.c`, `Core/Inc/user_settings.h`, and `Core/Inc/pqc_wolfssl_user_settings.h`. The CMake target `pqc_wolfssl_stm32_build_only` builds the minimal wolfCrypt SHA-256 source file from `tools/wolfboot/lib/wolfssl/wolfcrypt/src/sha256.c` and links it into the direct and relocated firmware builds. The M6.0 smoke helper computes SHA-256 over a fixed non-secret message and can emit `wolfSSL build-only smoke:` UART evidence with `source=enabled`, `sha256=ok`, `tls_handshake=unavailable`, `transport=unavailable`, `certs=not-loaded`, and `secrets=not-compiled-in`. This proves only that the configured wolfSSL/wolfCrypt source path built, linked, and executed.

The original M6.1 TLS-context smoke boundary has been superseded by the current STM32 TLS 1.3 runtime. The firmware now creates a `WOLFSSL_CTX` and `WOLFSSL` session, loads the generated trust anchor, configures peer identity and the profile-selected group, attaches lwIP socket I/O contexts, performs `wolfSSL_connect()`, and verifies the negotiated group. Historical `tls-context-lifecycle-only` wording must not be used to describe the current MQTT/TLS runtime path. The former local-context startup callback has been removed from the maintained firmware; neither `wolfSSL TLS startup self-test:` nor the earlier `wolfSSL TLS context smoke:` marker is emitted. `tests/hardware/test_wolfssl_source_smoke_uart_hw.py` has therefore been retired. A successful build-boundary SHA-256 check is not evidence of context creation. The `tls_handshake_repeat` hardware test checks complete STM32 reporting epochs and per-iteration firmware status for successful fresh TLS contexts, certificate/peer checks, negotiated group and cleanup; it is not a replacement local-only UART self-test. No hardware success is claimed until that hardware test is executed.

`Core/Inc/pqc_wolfssl_transport.h` and `Core/Src/pqc_wolfssl_transport.c` retain a legacy project-owned transport-boundary self-test. Its UART line is explicitly labelled `wolfSSL transport startup self-test:` with `scope=legacy_boundary_self_test` and `runtime_capability=not_assessed`. Current MQTT/TLS execution instead connects the wolfSSL session to the live lwIP/ST67-backed socket path in the MQTT runtime; the legacy self-test does not establish or negate that runtime capability.

TLS handshake benchmark reporting uses two bounded post-handshake summary records, `PQC_TLS_HANDSHAKE_TIMING` and `PQC_TLS_HANDSHAKE_MEMORY`, followed by zero or more `PQC_TLS_PHASE` and `PQC_TLS_PRIMITIVE` records. The project-owned instrumentation API is event-parameterised: call sites use the same matched `PQC_TLS_InstrumentationBegin(event)` / `PQC_TLS_InstrumentationEnd(event, result)` interface for the handshake, protocol phases, and security/cryptographic operations. When available, every application-side event boundary captures both the DWT cycle counter and the dedicated 1 MHz monotonic application timebase. The 1 MHz value is the canonical elapsed-time source for application-visible/system timing; DWT remains an independent cycle-attribution view and is not interpreted as isolated primitive computational cost in the FreeRTOS runtime. Stack high-water and FreeRTOS heap queries occur before and after `wolfSSL_connect()` and are never executed inside the critical handshake interval. Primitive coverage follows the ready-metrics TLS matrix: P-256/P-384/P-521 and X25519 key generation/shared-secret operations, ML-KEM-768/1024 key generation/decapsulation, RSA verification/signing, ML-DSA-65 verification/signing, SHA-256, HKDF extract/expand, and aggregate X.509 verification. RSA and ML-DSA verification hooks cover both TLS CertificateVerify and certificate-chain signature verification paths so authentication cost is not silently omitted.

The `tls_handshake_repeat` workload establishes Wi-Fi/IP state once and then performs the configured `handshakes_per_run` iterations without resetting the STM32. Every iteration creates a fresh TCP connection and fresh wolfSSL context/session, does not provide a prior session object for resumption, verifies the configured named group, preserves the configured authentication mode/profile evidence, and closes/frees the per-handshake transport before result publication. A TCP/TLS failure is retained with its iteration and failure stage; it does not disappear from the sample set. Failure to cleanly isolate per-handshake state or failure to publish a completed result epoch aborts later iterations because subsequent evidence could no longer be trusted. Campaign repetition remains an outer framework run and is independent of this workload iteration count.


The validation model rejects mismatched backend/evidence combinations, fake/no-network configs that name a real broker endpoint, fake-transport settings on non-fake backends, host-side configs without a broker endpoint, unsupported metric names, empty unavailable reasons, invalid fake outcome values, and private-key references in certificate metadata. Certificate references are path references only and must not introduce private keys or credentials.

When MQTT/TLS schema fields are present, the initial result manifest includes an `mqtt_tls` block. The block records the evidence class, backend, TLS mode, broker metadata, metric records, metric summary, limitations, and evidence-boundary flags. Unavailable metrics are first-class records with a source and reason. Fake transport control-flow results are embedded only as simulated fake evidence. This schema does not claim Wi-Fi association, IP address, TCP connection, TLS handshake, MQTT connect, publish, reconnect, latency, throughput, STM32 runtime success, or ST67W61M1-backed success without explicit real evidence.

### Checkout notebook

Open `notebooks/00_checkout.ipynb` in the existing Linux Jupyter environment and
Run All. It displays the current Git branch/commit and dirty paths, submodule
revisions, host/container versions, wrapper syntax and Git whitespace checks,
dependency-pin validation, and `./scripts/dev.sh pytest tests/unit -ra` output.
Commands stream stdout/stderr directly into their cells; failures remain visible
and subsequent checks continue. A final in-memory summary lists exit statuses.

The notebook creates no separate reports, manifests, exports or result directories.
The framework's normal pytest evidence/cache and generated-state hygiene still
apply. It uses the existing Docker image via `scripts/dev.sh`; gateway, broker,
firmware build and hardware workflows are excluded. Status and unit-test success
are software evidence only. The notebook is self-contained and has no reporter CLI.

## Test architecture

```text
tests/unit/          No hardware, SSH, UART, gateway, or real device requirements
tests/integration/   Real local toolchain or gateway checks; skip when unavailable
tests/hardware/      End-to-end board/gateway/UART workflows; capability gated
```

Test-module filenames encode the test layer to keep pytest module names unique across the tree: integration tests under `tests/integration/` end in `_in.py`, and hardware tests under `tests/hardware/` end in `_hw.py`. Unit-test filenames retain the normal `test_*.py` form without a layer suffix. New tests and documentation references must follow this convention; do not create the same Python module basename in multiple test directories.

Hardware tests are self-contained by default. The test owns the framework preparation needed to exercise its selected case: it resolves or materialises canonical configuration, creates test-owned build/generated state, invokes the normal framework build/sign/flash/run path, captures its own UART/manifest/result evidence, validates that evidence, and cleans up test-owned temporary state. A default hardware-test invocation must not depend on a user first resolving a campaign, manually configuring CMake, manually signing or flashing firmware, exporting a test-specific result/log path, or pointing the test at prior evidence. Gateway reachability, SSH credentials, flash helper availability, UART devices, broker/instrument availability, and other real laboratory resources remain capability gates rather than setup performed by the test. Optional selectors may narrow a large profile matrix, but at least one valid default case must be runnable without test-specific setup. The dual-bank OTA hardware test is the reference pattern for this self-bootstrapping model.

`pytest-hardware` runs with isolated Docker volumes over `/workspace/build` and `/workspace/.pqc-generated-state`; self-contained hardware tests should use those repository-shaped locations for ephemeral build/generated state and use pytest-owned temporary/result locations for test evidence as appropriate. Retained-log validation can be factored into helper functions or lower-layer tests, but a log path supplied by the user is not the primary hardware-test contract.

FreeRTOS-specific regression tests are split by evidence source. Unit tests inspect generated CMake, `FreeRTOSConfig.h`, the CubeMX `.ioc`, and application marker ordering. Integration tests build both `Debug` and `Release` presets with the generated FreeRTOS middleware. Hardware tests should continue to assert UART evidence from the direct-flash and secure-boot workflows; FreeRTOS runtime success must come from explicit UART markers such as scheduler-start, task-start, and recurring `tick` output.

The former standalone secure-boot algorithm benchmark hardware module is no longer present. The maintained `tests/hardware/test_secure_boot_flash_workflow_hw.py` supplies a positive ECDSA P-256 build/sign/flash/UART case and separate negative/restoration cases. This is not full algorithm-matrix coverage. Capability gates decide whether selected gateway and hardware tests run or skip; command-line `--pqc-require-*` switches are strictness controls, not the normal way to make tests runnable.

Run all tests that can run without gateway access through the default Docker path:

```bash
./scripts/dev.sh pytest
```

Run the single positive secure-boot workflow through Docker and the SSH gateway only when hardware is intentionally available:

```bash
./scripts/dev.sh pytest-hardware tests/hardware/test_secure_boot_flash_workflow_hw.py::test_secure_boot_build_sign_flash_uart_workflow -m hardware --pqc-require-hardware
```

GitHub Actions CI is defined in `.github/workflows/ci.yml`. It runs on every pushed commit, pull request, and manual dispatch. The workflow preserves the existing runner-compatible jobs and MQTT broker Docker runtime validation, and adds a separate `container-non-hardware` job for the project-owned container workflow.

The containerised job is the default reproducible software-build validation path. The runner-compatible jobs remain as compatibility coverage: they run unit tests, build both CMake firmware presets on the Ubuntu GitHub-hosted runner, run the real wolfBoot build integration test when local tooling and the wolfBoot submodule are available, and then run integration tests with the local-build capability required. The integration job also runs MQTT broker Docker Compose config rendering tests with `docker compose config`, which validate the classical and OQS compose model without deploying to the gateway or running experiment orchestration. The MQTT broker Docker runtime job starts the local classical Mosquitto container, uses temporary test certificates, validates TLS 1.3 mutual authentication, and verifies MQTT publish/subscribe using client certificates.

The default containerised non-hardware job builds the project container image from `docker/python/Dockerfile` and runs the non-hardware checks inside that image: Python unit tests, the safe framework status command, `Debug` and `Release` CMake configure/build, one wolfBoot build profile, relocated ECDSA P-256 application signing, and targeted local-build integration tests for `test_local_build_in.py` and `test_wolfboot_build_integration_in.py`. It requires no GitHub Actions secrets; signing material generated during CI is runtime workspace state only and remains covered by the generated-output and secret exclusions.

Gateway and hardware tests remain outside the default CI workflow because they require SSH access, board flashing, UART devices, Docker gateway state, or explicit lab evidence. The experimental OQS runtime path remains covered by explicit gateway validation rather than default GitHub-hosted CI. CI output is portable software-build and local Docker runtime evidence only; it must not be used as hardware, gateway, flashing, UART, production MQTT/TLS, runtime timing, runtime memory, benchmark, or end-to-end device evidence.

## Result ownership

Build records identify produced firmware binaries. Experiment run records identify one execution and its hardware-facing evidence. Secure-boot build/sign/flash evidence remains explicit and profile-specific. Aggregated benchmark summaries are derived outputs from existing manifests.

A directory under `results/builds/<build_number>/` is an immutable compilation record. Each successful normal application build reserves a new build number and writes the produced ELF, build log, configuration/tool evidence, and final ELF SHA-256. Application build records are not searched for automatic reuse and are not mutated by later runs.

Normal application firmware no longer has a framework-level source/dependency fingerprint. Every request invokes CMake configure and build, while Ninja may incrementally reuse unchanged object files in the retained build directory. The final ELF SHA-256 is the authoritative artifact identity. Secure-boot wolfBoot, relocated-application, signing, and secure-boot flash stages retain their separate evidence fingerprints where required by those workflows.


## ML-DSA secure-boot profiles

The framework includes post-Phase 11 ML-DSA benchmark profiles for `mldsa44` and `mldsa65`. Both use wolfBoot `SIGN=ML_DSA`, the existing relocated HAL payload, the same UART marker model, and the Phase 11 repeated-run/statistics manifest schema. `mldsa44` sets `ML_DSA_LEVEL=2` and `IMAGE_SIGNATURE_SIZE=2420`; `mldsa65` sets `ML_DSA_LEVEL=3` and `IMAGE_SIGNATURE_SIZE=3309`.

`mldsa87` is intentionally not configured as a runnable profile in this change because wolfBoot's ML-DSA example documents `IMAGE_HEADER_SIZE=12288` for the level-5 signature, while the current framework layout reserves 12288 bytes for the image header.

## MQTT broker compose data flow

```text
Docker-hosted framework checkout
  -> local certificate provisioning under experiment/mqtt-broker/runtime/
  -> scp of compose/config/script/runtime files to the gateway
  -> optional scripts/experiment.py mqtt-broker-experiment orchestration
  -> ssh remote Docker Compose start/stop/status/log commands
  -> MQTT-over-TLS broker listener on the gateway
  -> broker-side or host-side MQTT/TLS validation logs and manifest under results/<run_id>/
```

This broker path is broker-side and host-side validation infrastructure. The broker workflow labels broker validation manifests and command output as `host-side/broker-side MQTT/TLS compatibility evidence`, with `host_side` evidence class and explicit false claims for STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, and end-to-end wireless success. It is not STM32 MQTT/TLS client evidence unless a later STM32 firmware phase records explicit board and broker evidence together. The classical profile uses Eclipse Mosquitto with TLS 1.3, client-certificate authentication, and an ACL file. The runner-compatible Docker runtime test exercises this classical container locally from a pytest temporary copy of the compose project, so generated certificates, data, and logs are not written to the repository tree. The experimental OQS profile uses the pinned Eclipse Mosquitto 2.1.2 Alpine image with OpenSSL 3.5 native ML-KEM support for post-quantum TLS protocol evaluation. Each profile overrides the image entrypoint, copies its bind-mounted ACL file to a container-local `/tmp/mosquitto-aclfile`, sets ownership and restrictive permissions for the runtime user there, and configures Mosquitto to read that copy. The top-level `mqtt-broker-experiment` command wraps certificate provisioning, deployment, profile start, validation, broker validation retries during startup, live step progress, bounded per-step subprocess timeouts, log capture even after validation failures, result manifest creation, and optional stop. OQS runtime behaviour must be confirmed with explicit broker/client logs before claiming PQC TLS success.

MQTT broker OQS image compatibility: The startup script creates a runtime-user-owned `/tmp/mosquitto-aclfile` when possible. Images with a `mosquitto` user use `mosquitto`; the current shared Eclipse Mosquitto image uses `nobody`, so the OQS config sets `user nobody` and the ACL copy is owned by that runtime user.




## Build and generated-state architecture

Framework commands that create or consume generated firmware, wolfBoot, and signed-image artifacts use `scripts/framework/generated_state.py`. The module stores project-owned scope manifests under `.pqc-generated-state/scopes/` and binds generated state to the workflow, profile, source/config fingerprint, toolchain command identity, host/container identity, and applicable signing-key tuple.

Before a build or signing command starts, the preflight compares the current identity with the last successful scope record. Demonstrably compatible state may be retained. Missing, malformed, cross-profile, cross-toolchain, or cross-host/container state causes deterministic cleanup of only the configured generated paths and stale final artifacts. Cleanup refuses paths outside the repository and refuses all paths under `secrets/`. CubeMX-generated source folders are not moved or deleted.

STM32 CMake builds use profile-scoped `build/<preset>/` directories. wolfBoot retains its upstream source layout, so the framework records a project-owned scope manifest and cleans only known host-tool outputs and final build artifacts. The wolfBoot-local private key, generated public key, and generated `src/keystore.c` are treated as one tuple; an incomplete or mismatched tuple is not silently repaired from an existing private key. Canonical keys under `secrets/wolfboot/` are never preflight cleanup targets.

Successful commands write artifact hashes and references to their build or signing records. The canonical normal signing path first creates the relocated ELF through the framework `experiment build` command with `Release`, so application signing can require that ELF to match a successful CMake generated-state record. Direct wrapped CMake remains a diagnostic fallback only and does not create the framework provenance required by downstream signing. Secure-boot flashing requires the wolfBoot ELF and original signed application to match successful wolfBoot-build and application-signing records; filesystem existence alone is insufficient. A failed command does not write a success record, and stale final artifacts are removed before execution so they cannot be mistaken for new output.



### Secure-boot profile selection and signing-tuple preservation

The former standalone benchmark module and its profile-selection environment-variable contract are no longer a runnable hardware validation path. Use the maintained secure-boot flash workflow described above; its positive flash/startup assertions and documented legacy benchmark-sample exception are defined in `docs/005_remote_flash_workflow.md`. Do not infer benchmark or full algorithm-matrix success from that focused test.

Hardware-test preparation must not call wolfBoot `keysclean` and pytest startup cleanup must not remove `wolfboot_signing_private_key.der`, `wolfboot_signing_public_key.der`, or `src/keystore.c`. Those files form reusable local signing state with the canonical key and are validated by the framework preflight. The maintained secure-boot hardware test does not manually remove build outputs; framework generated-state preflight owns compatibility and stale-output handling.



### Application handoff ordering and runtime memory checkpoints

After wolfBoot verifies the signed image and transfers control, the application initializes only the hardware required to expose UART evidence. The first application UART output is the preserved wolfBoot mailbox block: raw verification cycles, bootloader SYSCLK/HCLK/PCLK values, verification result, and wolfBoot stack evidence. The secure-boot application marker and other application initialization markers follow that mailbox evidence. This output ordering does not imply that application code ran before verification; the mailbox is populated by wolfBoot and printed only after verified handoff.

Application clock evidence is emitted from the running FreeRTOS default task after the scheduler starts. It records HAL-reported SYSCLK, HCLK, PCLK1, and PCLK2 separately from the bootloader clock evidence. The application HCLK must not be used to derive wolfBoot verification time.

Application memory evidence uses bounded UART checkpoints rather than configuration values alone. The current checkpoints are `pre_scheduler`, `default_task_start`, and `default_task_runtime`. Each records FreeRTOS heap total, current free heap, minimum-ever free heap, derived current used heap, and derived peak used heap. Task-stage checkpoints additionally record the default task's configured stack bytes, stack high-water bytes, and derived used bytes. The pre-scheduler checkpoint reports task-stack fields as unavailable because no task is executing at that point.

FreeRTOS heap evidence covers only allocations managed by the configured FreeRTOS heap implementation. Default-task stack evidence covers only that task at the named checkpoint. wolfBoot verification stack evidence remains a separate metric and must not be merged with application task-stack evidence. Configured heap size, configured task stack size, linker sections, host timing, and UART duration are not runtime usage measurements by themselves.

The ready-metrics completion callback also emits final RAM accounting after the measured workload and before `PQC_EXPERIMENT_COMPLETE`. `PQC_RAM_LINKER_ACCOUNTING` reports the capacities of linker regions `RAM`, `RAM2`, and `RAM3`, initialized-data and BSS footprint, the primary-RAM static base, the linker minimum newlib-heap/MSP reservations, linker-reserved versus unreserved primary RAM, the dedicated RAM3 ML-DSA workspace reservation, and aggregate linker RAM capacity/reservation. `PQC_MEMORY_HIGH_WATERMARK` remains the runtime companion marker and reports FreeRTOS `heap_4` peak/final evidence, ML-DSA workspace peak/final evidence, newlib `_sbrk` capacity/peak/final evidence, MSP reserved/peak/headroom evidence, and derived observed primary-RAM/workload requirements. These final markers are independent of verbose CMake memory diagnostics and `PQC_WOLFSSL_ALLOCATION_PROVENANCE`; disabling per-allocation/provenance UART output must not disable final RAM evidence.

The FreeRTOS heap backing array is statically linked into application RAM, and the ML-DSA workspace is statically reserved in RAM3. Their runtime high-water values therefore describe demand within already reserved physical storage and must not be added again to linker-reserved totals. `_sbrk` is different: it grows from `_end` toward the MSP limit, so its runtime high-water is added to the primary-RAM static base when deriving observed primary-RAM demand. MSP high-water is measured by painting the otherwise-unused primary-RAM interval from above the static image (or any pre-`main()` `_sbrk` high-water) to the current MSP at the beginning of `main()`, then scanning only after workload completion while excluding every byte ever loaned to `_sbrk`. This allows application/interrupt MSP demand to be measured beyond `_Min_Stack_Size` rather than saturating at the linker reservation. Runtime evidence records the linker reservation, measured peak, reservation headroom, excess beyond the reservation, observable measurement window, and a saturation flag. If the observable window is exhausted, `msp_peak_used_bytes` and the derived observed-RAM requirement are lower bounds rather than exact peaks. The watermark still cannot reconstruct stack depth consumed by reset/startup code before `main()`; that limitation must remain explicit in evidence interpretation.

### Application timing timebase and reset-origin handoff

Application-visible research timing uses the project-owned `Core/Inc/pqc_timebase.h` / `Core/Src/pqc_timebase.c` interface. TIM1 remains exclusively the HAL timebase and is not repurposed. TIM2 is reserved by the project as a 32-bit free-running counter configured from the active APB1 timer clock to an effective 1 MHz rate. The implementation derives the timer input clock at runtime, requires exact integer division to 1 MHz, records the programmed prescaler, and extends the 32-bit counter with a very-low-priority update interrupt so monotonic `uint64_t` microsecond timestamps remain valid across hardware wrap. Normal HAL/FreeRTOS millisecond ticks remain scheduler/timeout facilities and are not the research measurement source.

TLS handshake, protocol-phase, primitive, and X.509 event boundaries capture the application microsecond timebase and DWT cycles when both sources are available. Application-visible elapsed time is derived from the microsecond timebase, while DWT cycles remain an independent attribution field; runtime primitive cycle observations are not treated as bare-metal computational-cost measurements. Ready Metrics 2 schema version 3 uses the canonical thesis names `rtfb_us`, `rtlb_us`, `ttfb_us`, `ttlb_us`, `req_tfb_us`, and `req_tlb_us`. Compatibility millisecond values remain only where their names are unambiguous and are derived from the microsecond source rather than measured from `HAL_GetTick()` or `xTaskGetTickCount()`. The raw structured result stream also includes an `application_timebase` provenance record identifying TIM2, timer input clock, prescaler, effective counter rate, counter width, wrap-extension method, the operational wolfBoot-entry reset origin, reset-origin state, and the fact that the exact ELF SHA-256 is supplied by the run manifest/build provenance.

For secure-boot runs, the wolfBoot temporary build instrumentation establishes the operational reset origin at entry to the STM32L4 `hal_init()` path before image verification. The short pre-stable-clock interval is bridged with LPTIM2 clocked directly from HSI16 at 1 MHz; DWT then measures the stable-clock wolfBoot interval without being reset at the authenticity-verification boundary. At `hal_prepare_boot()` wolfBoot stores the reset-origin-to-handoff value and restarts the independent 1 MHz LPTIM2 bridge. The application consumes that bridge after its clock configuration and before starting TIM2, yielding a reset-origin-to-application-timebase offset without relying on the HAL tick. The 16-bit bridge is accepted only when no wrap occurred; otherwise reset-relative timing is explicitly unavailable while ordinary application-relative TIM2 timing remains valid.

### Secure-boot timing and clock evidence

Secure-boot verification timing uses the DWT cycle counter as the primary firmware-side evidence. The wolfBoot instrumentation mailbox records raw elapsed cycles, verification result, stack high-water evidence, and bootloader clock values derived from the active STM32 RCC register model: SYSCLK, HCLK, PCLK1, and PCLK2. Firmware does not convert cycles to milliseconds and does not report a hard-coded CPU frequency.

The framework may derive `derived_verification_time_ms` as `verification_cycles * 1000 / hclk_hz` only when both explicit UART values are present. The manifest records `derived_time_clock_source: hclk_hz` and keeps the raw cycles and reported clocks separate. This derived value is not RTC, wall-clock, host-duration, UART-latency, or independently calibrated timing evidence. Hardware assertions remain capability-gated and require explicit UART/manifest evidence.


### FreeRTOS task-context runtime smoke

The deterministic lwIP helper smoke can emit pre-scheduler and FreeRTOS task-context diagnostics. The historical wolfSSL local-context lifecycle smoke was removed and no longer emits a required UART marker. The current TLS runtime is exercised by TLS workload experiments, with deferred result reporting rather than UART-only evidence.

The local lwIP helper smoke remains distinct from the live ST67 and TLS workloads. A local helper marker does not prove an external connection or TLS handshake. The baseline hardware test flashes a file-owned known image before its bounded, reset-triggered UART monitor; runtime TLS functionality requires separate TLS experiment and reporting evidence.


## STM32-local lwIP UDP loopback

The baseline hardware test includes a capability-gated known-image build/flash/UART path for this marker. The baseline hardware module now shares one independently prepared, known-image run across its five related checks; its bounded monitor test explicitly resets that same image and validates a fresh boot marker. A standalone monitor invocation without known-image preparation still cannot establish which firmware was already running. The M6.6 implementation does not add manifest fields: the current baseline `run` manifest records UART pass/fail evidence, while the detailed local-loopback evidence remains in `uart.log`. A future structured UART-evidence ingestion phase may promote these fields into the manifest without changing their local-only meaning.


The known-image baseline UART test explicitly resolves `workload.uart_output_mode=full` to qualify diagnostic marker ordering, SPI bring-up, association, and DHCP from one retained boot. This override is confined to UART diagnostics; normal minimal/disabled scientific runs continue to use their own selected mode. The finalized manifest records capture integrity and indexes `uart.log`; network association and DHCP are checked against same-boot UART evidence rather than transient top-level manifest fields. Each hardware test file provisions its own case and evidence independently.

## STM32 wolfMQTT build boundary

The wolfMQTT build boundary adds wolfMQTT as the dedicated `Middlewares/Third_Party/wolfMQTT` Git submodule and builds its core client, packet, and socket-callback sources into the STM32 firmware. `Core/Inc/pqc_wolfmqtt_build_only.h` and `Core/Src/pqc_wolfmqtt_build_only.c` provide the project-owned integration boundary. The boundary uses wolfMQTT's native `MqttNet` callbacks. The retained `fake_no_network` path is build/runtime boundary evidence only; hardware-backed experiment profiles use the implemented `st67w61m1` + lwIP socket path, with wolfSSL providing TLS when requested.

The build-only initializer constructs an unavailable `MqttNet`, calls `MqttClient_Init`, and deinitializes the client. It does not call network connect, MQTT CONNECT, publish, subscribe, wait-message, TLS, socket, lwIP external transport, or Wi-Fi APIs. No UART marker is emitted and no runtime success is claimed by the build-only boundary. Broker connection, TLS handshake, publish, reconnect, Wi-Fi, ST67W61M1, and end-to-end states remain unavailable.

### STM32 fake/no-network wolfMQTT runtime evidence

The fake/no-network runtime path reuses the build integration boundary rather than adding a second MQTT client path. A serialized one-shot call runs from `defaultTask` after the scheduler starts, selects `fake_no_network`, constructs the unavailable `MqttNet`, calls `MqttClient_Init`, and deinitializes the client without invoking network connect, MQTT CONNECT, publish, subscribe, wait-message, TLS, socket, lwIP external transport, or Wi-Fi APIs.

The UART marker begins with `wolfMQTT runtime smoke:` and is labelled `evidence=stm32-fake-no-network-initialization-only`. It records the FreeRTOS task context, backend, initializer result, client-initialized state, and callback presence. Transport, Wi-Fi, link, IP, TCP, TLS handshake, MQTT connect, MQTT publish, reconnect, ST67W61M1, and end-to-end status remain explicitly unavailable. This is initialization evidence from the STM32 board only; it is not broker or network evidence.

Static unit coverage validates invocation, marker wording, backend selection, unavailable claims, and the continued absence of protocol/network calls. Existing local-build integration coverage compiles both `Debug` and `Release`. The maintained `tests/hardware/test_baseline_uart_hw.py` now checks baseline UART and ST67 startup/network evidence; it no longer supplies the former dedicated Phase M8 fake/no-network marker assertion. Do not treat that test as verification of this historical runtime-smoke contract or infer current hardware success from the earlier description.

## Host wolfMQTT/wolfSSL compatibility boundary

`experiment/mqtt-broker/host-wolfmqtt/CMakeLists.txt` defines a separate native-host build. It compiles the pinned wolfMQTT core and upstream MQTT client/network example sources and links them to the wolfSSL source carried by the wolfBoot submodule. This target is intentionally separate from the Arm/STM32 CMake presets and from `pqc_wolfmqtt_stm32_build_only`.

`experiment/mqtt-broker/scripts/host_wolfmqtt_validate.py` configures and builds the native executable and can pass arguments through to the upstream wolfMQTT client. Before invoking the client it emits an explicit `host_side` evidence label and false claims for STM32, Wi-Fi-module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, and end-to-end wireless success. Optional JSON output preserves the same boundary. The utility may target the local or gateway-hosted classical broker, but gateway and broker availability remain capability requirements rather than assumptions.

The canonical broker definition is `experiment/mqtt-broker/compose.yaml`. Phase M4 Mosquitto/OpenSSL checks and Native wolfMQTT/wolfSSL checks are complementary host-side paths. Neither is firmware evidence.



### Linux/bash client-argument boundary

The host validation wrapper accepts upstream wolfMQTT arguments after `--client-args`. Under Linux/bash, pass explicit upstream arguments after this named boundary; a standalone `--` forwarding delimiter is not required.


### Structured host runtime evidence

The host validation utility captures the wolfMQTT client output and records individual TLS/MQTT success markers in the JSON result. `broker_compatibility_confirmed` is true only when the process exits successfully and explicit markers confirm TLS socket connection, MQTT connection acknowledgement, subscription, successful publish, message receipt, MQTT disconnect, and socket disconnect. A zero process exit code alone is insufficient.
## Consolidated deferred-test register

This is the canonical register required by the deferred-test rules in `AI_BUILD_GUIDE.md`. Related implementation requests must inspect these entries and either implement the listed coverage, update the entry with current evidence, or document why it is no longer applicable. Completed gateway/UART coverage and completed lwIP-loopback/fake-no-network known-image hardware assertions are intentionally not listed.

| ID | Feature | Missing test layer | Reason | Required capability or phase | Intended test file | Eventual verification command | Status |
|---|---|---|---|---|---|---|---|
| DTR-HOST-USER | Host-user runtime identity and private output ownership | Remaining local firmware/wolfBoot build regression | Docker ownership and certificate provisioning are now verified on the development host; those gates do not establish firmware build/runtime success | Non-root Linux user, local non-remapped Docker daemon, development image and complete checkout | `tests/integration/test_container_host_user_in.py`, `tests/integration/test_certificate_ownership_in.py`, `tests/integration/test_local_build_in.py`, `tests/integration/test_wolfboot_build_integration_in.py` | `./scripts/dev.sh check-host-user`; `python3 scripts/check_certificate_ownership.py`; `./scripts/dev.sh pytest tests/unit`; `./scripts/dev.sh pytest tests/integration/test_local_build_in.py tests/integration/test_wolfboot_build_integration_in.py -m integration --pqc-require-local-build` | partially verified 2026-09-29: host-user Docker gate passed, disposable RSA-3072/ML-DSA-65 provisioning passed at UID/GID 1000:1000, and 1137 unit tests passed; firmware build gates remain pending |
| DTR-HOST-USER-GATEWAY | Non-root gateway wrapper and isolated hardware outputs | Live SSH/gateway and representative hardware regression after identity change | Dummy SSH/volume tests do not establish real SSH credentials, remote helper permissions or hardware lifecycle | Rebuilt development image, runtime SSH credentials, gateway and STM32 where required | Existing `tests/integration/test_gateway_flash_helper_in.py` and `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-gateway tests/integration/test_gateway_flash_helper_in.py -m integration --pqc-require-gateway`; `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | deferred; these commands can build/flash hardware and require retained evidence |
| DTR-CAMPAIGN-RESUME-FLASH | Restore expected firmware on campaign resume | Live resume after an intervening different firmware flash | Prepared offline while a user campaign owns the board; subprocess tests cannot prove physical flash | Gateway, STM32/ST67, build/sign prerequisites and brokers | `tests/hardware/test_campaign_executor_hw.py` (extend with intervening flash and resume) | `./scripts/dev.sh pytest-hardware tests/hardware/test_campaign_executor_hw.py -m hardware --pqc-require-hardware` after extending the live resume scenario | pending live intervening-flash/resume validation |
| DTR-OQS-MTLS-CHAIN | Container-local CA chain and dedicated health-topic ACL | Gateway deployment and blocked campaign retry | Local Docker verifies broker behavior but not gateway deployment or STM32 mutual TLS | Gateway and STM32/ST67 laboratory | `tests/integration/test_oqs_mtls_permissions_in.py`; `scripts/check_oqs_mtls_broker.py` local gate; retained campaign manifests | `python3 scripts/check_oqs_mtls_broker.py`; `./scripts/dev.sh campaign-gateway --resume results/campaigns/tls_matrix_energy_20260928_222043/campaign-manifest.json` | local Docker passed 2026-09-29 for RSA-3072 and ML-DSA-65: healthy startup, staged-file access, authenticated publish and rejection without client certificate; live campaign retry pending |
| DTR-CAMPAIGN-CONTINUE | Continue after runtime failures and blocked preparation/broker setup | Live failure followed by successful reset/repetition | Offline subprocess tests cannot establish device/network recovery | Gateway, STM32/ST67 and brokers | `tests/hardware/test_campaign_executor_hw.py` | `./scripts/dev.sh campaign-gateway --resume results/campaigns/tls_matrix_energy_20260928_222043/campaign-manifest.json` | offline runtime and broker/setup continuation tested; live recovery validation pending |
| DTR-TLS-MATRIX-ENERGY | Ready Metrics 2 TLS matrix with energy on every condition | Live 12-condition TLS/energy campaign acceptance | Newly created matrix has not been run; resolver, broker dry-runs and synthetic notebook execution cannot establish target/broker interoperability or captured timing/energy validity | STM32/ST67, gateway, experiment/reporting brokers, configured Wi-Fi and persistent ESP32/INA228 | `tests/integration/test_tls_matrix_energy_campaign_in.py` (offline); existing `tests/hardware/test_energy_capture_hw.py` (instrument boundary); retained campaign manifests for the complete matrix | `./scripts/dev.sh campaign-gateway tls_matrix_energy`; export the exact resulting campaign with `scripts/export_timing_dataset.py` and verify consumed inputs | pending first live matrix run; energy enabled in all 12 conditions, 120 planned runtime attempts |
| DTR-A3-MATCHED | A3 application resource comparisons | Real-evidence matched profile delta acceptance | Retained TLS matrix has unknown source revision and QoS controls; some pairs also differ in evidence class. Absolute resource import succeeds but controls cannot be silently waived | Retained runs with known comparable controls and explicit analysis specification; no new instrumentation | `tests/integration/test_resource_analysis_in.py` (extend retained-evidence coverage when suitable records exist) | `./scripts/dev.sh python scripts/summarise_timing_dataset.py --dataset results/analysis/SELECTED_DATASET --spec notebooks/SELECTED_SPEC.json --output results/analysis/NEW_RESOURCE_SUMMARY --resources` | partially verified 2026-09-29: 12 unique retained ELF builds imported; synthetic matched deltas and CLI/notebook equivalence pass; real matched deltas deferred for provenance gaps |
| DTR-A1-CONTAINER | A1 offline timing export and typed loader | Post-correction Docker-hosted documentation and full unit regression | Earlier upload-session README-length failure required a fresh regression | Complete Linux development checkout and rebuilt Docker Python image; no gateway, credentials or hardware | `tests/unit/test_timing_dataset_documentation.py`, `tests/unit/test_documentation_integrity.py`, `tests/unit/test_docker_default_workflow_docs.py` and `tests/integration/test_timing_dataset_in.py` | `./scripts/dev.sh pytest tests/unit`; `./scripts/dev.sh pytest tests/integration/test_timing_dataset_in.py -m integration` | closed during A2: 2026-09-28 Docker full unit regression passed, including A1 and documentation tests; A1 local integration rechecked |
| DTR-R4-STACK | Request 4 wolfBoot stack watermark, mode isolation and mailbox v8 | Containerized wolfBoot/application build, bounded gateway/STM32 verification and OTA handoff regression | Local syntax/source tests cannot prove actual stack depth, absence of RAM corruption, normal-mode non-interference or SRAM2 handoff on hardware | STM32 target, Docker cross-toolchain, gateway, broker and maintained secure-boot profiles | `tests/hardware/test_secure_boot_flash_workflow_hw.py` and `tests/hardware/test_ota_dualbank_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_secure_boot_flash_workflow_hw.py -m hardware --pqc-require-hardware`; profile-enabled campaign `./scripts/dev.sh experiment-gateway run --experiment <resolved secure_boot_stack case>`; then targeted OTA smoke test | deferred pending explicit cross-build, STM32 high-water evidence and bounded OTA regression |
| DTR-GWLOCK | Cross-development-host gateway resource exclusion and recovery | Live multi-host contention, force-release and hardware/campaign lifecycle | Unit subprocess flock tests cannot show that remote experimental processes stop before reassignment or validate hardware state after interrupted flashing | Two Linux development machines, shared gateway SSH account, gateway Python 3 and STM32 hardware | `tests/integration/test_gateway_lock_in.py` and `tests/hardware/test_gateway_lock_hw.py` | `./scripts/dev.sh gateway-lock status` from both machines; run a gated representative `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` while competing for the lock; verify forced recovery only after the old operation is stopped | deferred: unit-only protocol verification; no live gateway/multi-host evidence |
| DTR-001 | M6.1 wolfSSL TLS-context lifecycle marker | Dedicated gateway-mediated known-image UART/hardware assertion | Existing hardware evidence checks task-context ordering in the secure-boot benchmark path, but there is no focused baseline test that builds/flashes the image and asserts the complete M6.1 lifecycle and unavailable-field contract | Gateway, flash helper, UART device, and known-image baseline run capability | `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | deferred |
| DTR-002 | M6.2 lwIP network-interface boundary marker | Dedicated gateway-mediated known-image UART/hardware assertion | Static/build coverage exists, but the known-image baseline hardware test does not yet assert the complete `lwIP network interface:` marker contract | Gateway, flash helper, UART device, and known-image baseline run capability | `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | deferred |
| DTR-003 | M6.2.1 generated-state provenance refusal before gateway access | Hardware-workflow fixture coverage | Framework and integration coverage exists, but secure-boot hardware fixtures still need explicit successful build/signing records to assert provenance refusal before any gateway operation | Updated build/signing record fixtures in the secure-boot hardware workflow | `tests/hardware/test_secure_boot_flash_workflow_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_secure_boot_flash_workflow_hw.py -m hardware --pqc-require-hardware` | deferred |
| DTR-004 | M6.3 wolfSSL legacy transport-boundary self-test marker | Dedicated gateway-mediated known-image UART/hardware assertion | Static/build coverage exists, but the known-image baseline hardware test does not yet assert callbacks, zero-transfer behavior, no socket I/O, and all unavailable fields | Gateway, flash helper, UART device, and known-image baseline run capability | `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | deferred |
| DTR-005 | M9 live host wolfMQTT/wolfSSL validation against the gateway broker | Gateway integration and live broker compatibility | Native host build coverage exists; deterministic live validation requires reachable gateway infrastructure and provisioned temporary broker certificates | Gateway connectivity, broker deployment, temporary certificate provisioning, and host client execution | `tests/integration/test_mqtt_broker_gateway_e2e_in.py` | `./scripts/dev.sh pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e_in.py -m integration --pqc-require-gateway`, then the documented `host_wolfmqtt_validate.py run` command | deferred |
| DTR-006 | M10 ST67W61M1 association and DHCP | Hardware coverage | Implemented by the baseline known-image UART hardware test, which requires explicit association and DHCP success markers plus a non-zero IPv4 address | Installed ST67W61M1 hardware, configured access point, gateway/UART access, and experiment-supplied credentials | `tests/hardware/test_baseline_uart_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_baseline_uart_hw.py -m hardware --pqc-require-hardware` | retired: coverage implemented; external TCP/TLS/MQTT remains separately deferred |
| DTR-007 | M11 classical STM32 MQTT-over-TLS | End-to-end firmware-runtime, network, broker, gateway, UART, and hardware coverage | The STM32 reaches the broker over TCP, resolves the configured FQDN, loads the CA, and receives the initial TLS 1.3 server records. The READY-level race was remediated and hardware evidence then isolated a later failure: a 94-byte first-part full-duplex SPI transfer entered DMA but did not produce the completion event, while the larger receive-only DMA path had already completed successfully. A bounded transport change routes short full-duplex control transactions through the synchronous polling path. Follow-up hardware evidence then isolated the same missing-completion behavior in the moderate receive-only second transaction. Receive-only remainders up to 2048 bytes are now polled in port-safe chunks, while larger receive-only and full-duplex payloads remain on DMA. Follow-up hardware evidence then reached certificate validation and showed the firmware checking `pqc-gateway1.pqcnet` against a generated server certificate whose SAN contained only `pqc-gateway1`, `localhost`, and IP addresses. Classical certificate provisioning now defaults to the experiment-selected FQDN and retains the short gateway alias. The runtime certificate bundle must be regenerated before complete TLS and MQTT hardware verification. | Completed M10 backend, level-aware ST67 READY handling, bounded short full-duplex polling path, real wolfSSL transport/session, classical certificates supplied outside the repository, broker access, and wolfMQTT connect/publish/reconnect implementation | `tests/hardware/test_stm32_mqtt_tls_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_stm32_mqtt_tls_hw.py -m hardware --pqc-require-hardware` | in progress: SPI completion fixes and broker FQDN SAN provisioning implemented; certificate regeneration and end-to-end hardware verification pending |
| DTR-008 | M12 controlled network degradation / Request 8 | Live gateway/network integration, per-direction packet-path and hardware ESP32 reporting qualification | Source-level rollback, occupied-resource refusal, distinct experiment/reporting veth peer checks, independent qdisc/filter/MTU inspection, retained-condition rechecks and two-direction packet-counter assertions have been added. The STM32 four-condition hardware test and retained two-repetition campaign test are capability-gated; no live gateway or STM32 run has yet established pass. Packet counters and raw PCAP do not on their own prove a quantitative RTT, loss rate or throughput. ESP32 is selected only by the explicit `--pqc-request8-esp32-hardware` gate; successful energy reporting under impairment remains unverified pending live evidence and complete energy acquisition integration. | Reachable privileged gateway, independent broker veth peers, `tc`/`iproute2`/IFB/`nsenter`, exclusive gateway lease, STM32/ST67 hardware and plaintext reporting infrastructure; persistent provisioned/calibrated ESP32/INA228 and enabled energy-result acquisition for the ESP32 extension | `tests/hardware/test_reporting_plane_isolation_hw.py` (STM32) and the opt-in energy-enabled cases in the same hardware file after instrument-runtime integration is available | `./scripts/dev.sh pytest-hardware tests/hardware/test_reporting_plane_isolation_hw.py -m hardware --pqc-require-hardware` then run an energy-enabled hardware matrix with ESP32 source/result integrity checks | implemented source checks; gateway/STM32 and ESP32 hardware acceptance pending |
| DTR-009 | M13 PQC/hybrid STM32 MQTT/TLS | End-to-end firmware-runtime, broker, network, gateway, UART, and hardware coverage | Target-library algorithm support and a stable classical STM32 MQTT/TLS baseline have not yet been established | Completed M11 baseline, confirmed wolfSSL/wolfMQTT target support, compatible broker profile, and Phase M13 implementation | `tests/hardware/test_stm32_pqc_hybrid_mqtt_tls_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_stm32_pqc_hybrid_mqtt_tls_hw.py -m hardware --pqc-require-hardware` | blocked by M11/M13 implementation |
| DTR-010 | ML-DSA-65 certificate authentication with hybrid ML-KEM MQTT/TLS | End-to-end STM32/server-auth and mTLS hardware verification | Unit coverage and a Docker broker integration test exercise profile selection, PKI generation, and broker-side ML-DSA TLS, but the supplied implementation context cannot execute the STM32/wolfSSL hardware handshake | Reachable gateway, STM32/ST67 hardware, ML-DSA-capable target wolfSSL build, provisioned `mldsa65` certificate profile, and hybrid broker | `tests/hardware/test_stm32_pqc_hybrid_mqtt_tls_hw.py` | `./scripts/dev.sh experiment-gateway run --experiment .pqc-generated-state/campaigns/tls_key_exchange/cases/<case>.yaml` followed by the mutual-auth profile | deferred: implementation requires repository/hardware verification |
| DTR-011 | Extended application MSP high-water and derived RAM requirement | Gateway-mediated firmware-runtime verification | Unit coverage can validate marker/parser contracts, but only a real STM32 run can confirm that the extended sentinel window reports an MSP peak beyond `_Min_Stack_Size` without saturation or `_sbrk` interference and that the derived required/headroom values reconcile | Gateway, STM32/ST67 hardware, ready-metrics application, UART capture, and a completed representative MQTT/TLS workload | `tests/hardware/test_stm32_mqtt_tls_hw.py` | `./scripts/dev.sh experiment-gateway run --experiment .pqc-generated-state/campaigns/tls_key_exchange/cases/<case>.yaml` | deferred: rerun required after extended MSP watermark implementation |
| DTR-012 | Ready Metrics 2 paper-aligned MQTT application TTFB/TTLB with deferred reporting | Gateway-mediated end-to-end timing/evidence validation | A 2026-09-18 gateway/STM32 run completed the ML-KEM-768/ML-DSA-65 Ready Metrics 2 workload and produced a hash-valid reporting stream plus experiment PCAP, but inspection showed that the canonical RM2 checkpoint/metric snapshot had not been appended to the common deferred result buffer. The buffer-integration fix now appends `rm2_timebase`, `rm2_checkpoints`, `rm2_metrics`, and `rm2_complete` records after the measured workload; a repeat hardware run is still required to confirm those records and reconcile them with packet timing. | Gateway, STM32/ST67 hardware, experiment and reporting brokers, gateway transfer responder, packet capture, and the Ready Metrics 2 campaign case | `tests/hardware/test_reporting_plane_isolation_hw.py` | `./scripts/dev.sh experiment-gateway run --experiment .pqc-generated-state/campaigns/ready_metrics_2/cases/<case>.yaml` then inspect `mqtt-reporting-raw.ndjson` and capture integrity | in progress: workload/collector succeeded; RM2 deferred-buffer integration fixed; repeat hardware evidence required |
| DTR-013 | Passive STM32/ESP32 energy acquisition acceptance | Gateway/hardware | The 2026-09-27 ready-metrics runs validated the superseded command/session energy protocol only. The current design replaces association tokens, the UART start gate and per-handshake intervals with one experiment-wide PF12 GPIO window, fixed publish-only ESP32 topics, 20-byte packed samples, up to 1 s of optional pre-trigger history and two-edge TIM2/ESP32 alignment. The 2026-09-28 06:53 UTC campaign received 6,507 samples with matching transfer hash but failed the former strict pre-trigger rule. Optional history capped at 1 s and measured-only gap acceptance have source/native tests; fresh hardware acceptance of the updated ESP32 firmware remains pending, as do stale-capture supersession, transfer timeout and repeated-TLS one-window behaviour. | Gateway, STM32/ST67 and manually provisioned/flashed ESP32/INA228 running the matching simplified firmware | `tests/hardware/test_energy_capture_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_energy_capture_hw.py -m hardware --pqc-require-hardware` | deferred: fresh hardware acceptance required for the simplified passive protocol |

| DTR-014 | Request-15 impairment-exempt reporting plane under rate, RTT, loss and MTU | Live gateway/network/hardware validation | Gateway/network/hardware execution previously produced all four configured veth impairments, successful cleanup transcripts and complete STM32 reporting streams, but the old hardware test failed on transient manifest fields. The revised persistent-evidence assertions and network-boundary check require a fresh hardware rerun. These checks do not measure realised packet loss, achieved throughput or observed RTT. | Reachable gateway with non-interactive `tc`/`ip`/`modprobe`/`nsenter`, running experiment/reporting brokers, STM32/ST67 and four resolver-generated impairment cases | `tests/hardware/test_reporting_plane_isolation_hw.py` | `./scripts/dev.sh pytest-hardware tests/hardware/test_reporting_plane_isolation_hw.py -m hardware --pqc-require-hardware` | in progress: previous gateway and reporting evidence inspected; revised hardware-test assertions not yet executed on device |
| DTR-015 | Request-13 1 MHz application timing timebase and reset-origin handoff | Representative gateway/hardware timing validation across plaintext, classical/hybrid TLS, server/mutual auth, Ready Metrics and Ready Metrics 2 | The dedicated hardware delay test is now self-contained and has produced hardware evidence confirming the selected timer derives 1 MHz (`120000000 / (119 + 1)`), a 10 ms requested delay measured 10985 us, HAL tick advanced 11 ms, wolfBoot verification succeeded, and the secure-boot application started. The remaining deferred work is the representative workload/profile matrix needed to confirm reset-origin validity, DWT preservation, and complete structured timing records across the required experiment families. | Reachable gateway, STM32/ST67 hardware, reporting/experiment brokers as required by the selected cases, and the maintained representative workload/profile matrix | `tests/hardware/test_application_timebase_hw.py` plus the maintained workload hardware tests | `./scripts/dev.sh pytest-hardware tests/hardware/test_application_timebase_hw.py -m hardware --pqc-require-hardware`, then run the maintained self-contained hardware/profile tests for plaintext, classical/hybrid TLS, server/mutual auth, Ready Metrics and Ready Metrics 2 | partially complete: 1 MHz hardware self-test passed; representative profile-matrix evidence still required |

| DTR-016 | Independent Ready Metrics 2 reliability runner | Real destructive Docker reset/rebuild, certificate provisioning and sequential gateway/STM32 trials | Automated coverage uses disposable command shims; the requested script has not been executed against the user's live Docker state or hardware | Dedicated idle Linux lab checkout/daemon, sudo, network access for image builds, configured gateway/SSH/Wi-Fi and STM32/ST67 | `tests/integration/test_ready_metrics_2_reliability_in.py` for process coverage; disposable-host acceptance via the runner | `./scripts/dev.sh pytest tests/integration/test_ready_metrics_2_reliability_in.py -m integration`, then on the dedicated host `python3 scripts/ready_metrics_2_reliability.py --runs 3 --execute` and inspect each manifest/UART plus summary | deferred: real Docker and hardware acceptance pending; simulated process coverage only |

Deferred status is not evidence that the named capability works. Future test files and commands are intended contracts and must be reconciled against the implementation that eventually supplies the capability.

### ST67 GPIO/SPI bring-up evidence

The bounded ST67 bring-up path calls `W6X_Init()` from a running FreeRTOS task after initializing the ST67 logging service. SPI1 uses prescaler 4, giving approximately 30 Mbit/s from the 120 MHz APB2/PCLK2 domain. UART markers record the pre-init GPIO state, driver invocation, returned status, and post-init GPIO state. The earlier prescaler-32 configuration was limited to logic-analyser diagnostics and is no longer the supported runtime setting.
A paired logic-analyser capture can establish that `CHIP_EN`, `SPI_RDY`,
active-high `SPI_CS`, SCK, MOSI, and MISO behaved consistently with a real
transport attempt.

This evidence class is **STM32-to-ST67 GPIO/SPI bring-up evidence**. It may
support a claim that the module driver was invoked and that physical SPI
activity occurred. It must not be promoted into evidence of Wi-Fi association,
IP acquisition, external TCP communication, certificate-backed TLS, MQTT
connect/publish/reconnect, or end-to-end wireless operation. Those capabilities
remain unavailable until their own explicit runtime evidence is recorded.



## ST67W61M1 Wi-Fi/DHCP evidence

The baseline experiment supplies SSID and PSK through `.pqc-generated-state/campaigns/baseline/cases/<case>.yaml`. The build workflow generates `build/pqc_generated/pqc_wifi_config.h`; UART and manifests redact the PSK. Firmware joins the configured AP and obtains IPv4 configuration through DHCP. Explicit UART markers record association and IPv4, gateway, and netmask values. Run manifests record parsed evidence under `network`. Hardware success requires both association and DHCP pass markers from the latest boot and a non-zero IPv4 address.


### Vendor-aligned SPI transport validation

The supported runtime remains based on the X-CUBE-ST67W61 vendor `spi_iface.c` transaction model, and the lwIP output adapter follows the vendor per-segment `pbuf` submission path. Local integration now includes bounded diagnostics and a level-aware transaction-ready guard required by the real TLS traffic path.

`SPI_RDY` is both a GPIO level and the source of `SPI_EVT_TXN_RDY`. The transfer task may consume the event while selecting work, or a rising edge may occur immediately around the nested wait in `spi_xfer_one()`. Waiting only for a new event can therefore time out while the physical READY input is already asserted. The supported guard checks the READY level before blocking, waits for the event only while the line is low, and checks the level once more after a timeout. It does not add transaction retries, discard queued payloads, or treat an unasserted READY line as success.

A controlled 30-second M10 hardware run using SPI prescaler 4 previously completed module initialization, configured-AP association, link-up, DHCP assignment, and live IPv4 reporting without invalid-header, READY-wait-timeout, or SPI transaction-timeout messages. A later M11 run reached the broker, sent the TLS ClientHello, and received the initial server records before exposing the READY event/level race under sustained TLS traffic. The level-aware fix requires a new recorded hardware run before it can support any TLS, MQTT, or end-to-end success claim.

## ST67 T02 normal startup and live network evidence

The normal ST67 T02 startup path initializes the module and host-side lwIP,
performs a bounded active Wi-Fi scan, associates with the configured access
point, waits for the station link, and obtains IPv4 configuration through
host-side lwIP DHCP. The scan runs after Wi-Fi and lwIP initialization and
before `W6X_WiFi_Connect()`. It logs discovered SSID, RSSI, channel, security,
and a configured-SSID summary to UART. Scan failure or timeout remains
best-effort diagnostic evidence and does not block the configured association
attempt.

After DHCP succeeds, runtime evidence must be derived from the live station
`netif`. The canonical marker is `lwIP runtime network:` with
`evidence=stm32-st67-t02-live-state`, `network=available`,
`wifi=connected`, `link=up`, and the complete assigned IPv4 address. Static
pre-network smoke markers do not override later live network evidence.

The gateway-mediated hardware test
`tests/hardware/test_lwip_runtime_smoke_uart_hw.py` validates module
initialization, scan completion before association, link-up, DHCP, live IPv4 evidence,
heartbeat continuity, and absence of contradictory unavailable markers after
the live-state marker.
The test resolves its own baseline campaign with full UART output, executes one
file-owned build/flash/run, and checks only the latest boot in the indexed
retained UART artifact. It checks the finalized manifest and preserves the
original UART log; the normalized timestamp-free view is used only for
diagnostic assertions. This UART-focused configuration is not a timing
benchmark or a requirement for MQTT/TLS measurement workloads.

Secure-boot profiles use the same relocated application image and therefore
must preserve these runtime markers after wolfBoot verification and handoff.
The existing secure-boot profile and benchmark tests remain the authoritative
build, signing, flash, verification, and profile-matrix coverage.

## Persistent signing tuple model

wolfBoot build profiles and application-signing profiles select an
algorithm-specific tuple under `secrets/wolfboot/tuples/`. The tuple contains
the private key, generated keystore, and a hash manifest. It is
persistent local security state, not build output.

`tools/wolfboot/wolfboot_signing_private_key.der` and
`tools/wolfboot/src/keystore.c` are disposable materializations. A separate
public-key DER file is optional because the maintained wolfBoot profiles
embed the verification public key in generated `keystore.c`. Their absence
does not make the persistent tuple partial; the next wolfBoot build restores
them. Only missing or inconsistent members inside the persistent tuple cause a
safe failure.


### wolfBoot cross-profile object isolation

The wolfBoot checkout is reused across signing algorithms, but wolfCrypt target
object filenames do not encode the active algorithm or preprocessor settings.
Before each wolfBoot profile build, the framework removes generated `.o` and
`.d` files below `tools/wolfboot/lib/wolfssl/`. This forces target wolfCrypt
sources and ARM assembly wrappers to be rebuilt for the selected profile and
prevents stale cross-profile symbol combinations such as an unresolved
`BlockSha3`.

This cleanup does not remove wolfSSL source files, persistent signing tuples, or
private keys.

### Plaintext STM32 MQTT end-to-end baseline

The `mqtt_plaintext_st67_e2e` profile extends the working ST67 Wi-Fi/DHCP path with a bounded wolfMQTT exchange over lwIP sockets. The firmware connects to the gateway broker on TCP port 1883, subscribes to a command topic, waits for one message, and publishes a correlation acknowledgement on a response topic. The existing TLS listener remains separate on port 8883.

End-to-end success requires recorded evidence of DHCP acquisition, TCP/MQTT connection, subscription, inbound delivery, outbound publication, and receipt of the expected correlation value by an independent gateway subscriber. Firmware UART markers alone prove the STM32-side observations but do not by themselves prove that the gateway received the response. TLS, reconnect, latency, and throughput remain unavailable for this baseline and must not be inferred.


### Automated plaintext MQTT orchestration evidence

The `stm32_st67_plaintext_e2e` experiment class uses one bounded gateway operation that starts the response subscriber before MCU reset, captures UART from reset, and republishes the non-retained command at a configured interval until the response arrives or the attempt limit is reached. A successful record requires matching STM32 UART protocol markers and an independently observed response payload. The result retains `mqtt-publisher.log`, `mqtt-subscriber.log`, and an `mqtt_e2e` manifest block with the failure stage, publication count, response verdict, and missing UART markers.

### Managed broker evidence for STM32 plaintext MQTT

The `stm32_st67_plaintext_e2e` evidence class owns the framework Mosquitto Compose project during each run. The workflow stops any prior instance of that known project, deploys the current broker configuration, starts the classical profile, performs a bounded plaintext MQTT readiness exchange, runs the STM32 command/response exchange, captures complete broker logs, and stops the project in guaranteed cleanup. Result folders retain broker deploy, start, status, readiness, log, and stop evidence. Broker lifecycle failures remain distinct from STM32 exchange failures, and a successful exchange does not mask failed log collection or cleanup.
## Automated-test results and build-purpose boundary

Pytest is a provenance-producing workflow. Its generated evidence is stored
under `results/automated-tests/<test-run-id>/`, separately from canonical
experiment results and from `results/builds/<build-number>/`.

Identity domains are not interchangeable:

- `test_run_id` identifies one pytest process.
- `run_id` identifies one canonical experiment execution.
- `build_number` identifies one normal reusable firmware build.
- `build_identity` identifies a test-only build within a test run.

A test-run manifest is written at session start and updated incrementally after
collection and each setup, call, and teardown stage. It records invocation
arguments, non-secret environment metadata, collected and outcome counts,
failure stage, case-stage records, retained artifact hashes, unavailable
artifacts, referenced canonical result records, and test-triggered build
records. A failed or interrupted run remains inspectable even if finalisation is
incomplete.

Application build reuse is disabled. Automated-test builds are retained under
`results/automated-tests/<test-run-id>/builds/<sequence>/`; they do not reserve
or increment `.build_number` and do not enter `results/builds/`. Fingerprint
equality cannot override this boundary. Normal experiment, benchmark,
secure-boot, and release selectors must only consider normal-purpose records in
the canonical reusable build pool. References from a test result to a canonical
experiment result are immutable references; the referenced record must not be
rewritten or supplemented in place.

Test evidence records unavailable artifacts explicitly with a producing stage
and reason. Secrets, private key material, credentials, PSKs, tokens, and
passwords are redacted or omitted; only approved public hashes and
fingerprints may be retained.

### Classical STM32 MQTT-over-TLS boundary

The first M11 profile is `server-ecdsa-p256`: ST67W61M1 supplies the network interface, while lwIP sockets, wolfSSL TLS 1.3, certificate verification, wolfMQTT CONNECT/publish, and one bounded reconnect run on the STM32. The firmware build embeds only the generated public broker CA certificate. The existing `classical` mutual-TLS broker profile remains separate and is not claimed as STM32-validated until client-certificate provisioning is implemented and evidenced.

The configured public CA certificate is embedded into generated firmware configuration and therefore affects the resulting ELF SHA-256. Private CA keys and other private certificate material remain excluded from manifests and result artifacts.

M11 execution success is established from the workload transaction and broker/runtime evidence, while normal structured STM32 scientific evidence is retained through the dedicated reporting collector. UART is diagnostic/fallback evidence according to `uart_output_mode` and is not a mandatory success predicate. Missing resource metrics remain unavailable rather than inferred. DTR-007 remains in progress until a capability-gated hardware run supplies end-to-end TLS/MQTT evidence.

### MQTT reconnect evidence

For the classical server-authenticated STM32 MQTT-over-TLS experiment, reconnect evidence requires a second complete command/response exchange. The gateway subscriber therefore remains active for the initial and reconnect responses, and command publication continues until both exact correlation responses are observed or the bounded orchestration timeout expires. The recorded evidence includes expected and observed response counts. Firmware status distinguishes an unattempted reconnect (`not_run`) from an attempted reconnect that fails (`failed`). A successful reconnect claim requires the second TLS handshake, MQTT connection/subscription, command receive, and response publish to complete.


### MQTT completion and UART diagnostics

Routine MQTT execution no longer uses UART text as its completion authority. The gateway starts the reporting collector before target execution and watches for the STM32 `<run-id>/complete` reporting topic; that completion record, followed by collector sequence/count/hash validation, terminates the bounded run. UART remains diagnostic/fallback evidence according to `uart_output_mode`. `minimal` suppresses UART output while the measured workload is active, `full` permits it for troubleshooting, and `disabled` omits LPUART initialisation and the HAL UART implementation from the firmware build. Per-call TLS I/O and verbose Wi-Fi scan diagnostics remain separately compile-time controlled. TLS instrumentation is buffered in RAM during the sensitive interval and serialized only after the workload returns.

### Hybrid PQC MQTT/TLS profile

The framework includes an explicit STM32/ST67W61M1 MQTT-over-TLS 1.3 profile using `SecP256r1MLKEM768` with conventional server certificate authentication and no mutual TLS. Classical fallback is not accepted as PQC evidence. End-to-end evidence must establish the negotiated PQC/hybrid group and successful MQTT workload from retained structured/broker/network evidence; UART may supplement diagnosis but is not required for capture acceptance. Hardware success remains unverified until a recorded gateway experiment supplies that evidence.


OQS gateway orchestration resolves the running broker container by Docker Compose project/service labels and uses direct `docker exec` for the OQS-enabled MQTT clients. Readiness requires exactly one running `mqtt-oqs` container, zero exit status from both subscriber and publisher, and an exact response payload. This avoids treating Compose service-discovery inconsistencies as broker failures and preserves explicit diagnostics when container resolution fails.

### OQS MQTT broker TLS group configuration

The OQS Mosquitto profile mounts a project-owned OpenSSL configuration that activates the default and OQS providers and sets the TLS default group to `SecP256r1MLKEM768`. This is required because provider algorithm availability alone does not make the Mosquitto server context select that hybrid key share. OQS certificate provisioning runs on the gateway and copies only the public CA certificate back to the ignored local runtime tree for firmware embedding. The host-side TLS validator requires a successful OpenSSL exit, a presented peer certificate, a negotiated non-`NONE` cipher, TLS 1.3, and successful certificate verification; broker-side validation remains host/broker evidence only.


### PQC MQTT TLS group and capture requirements

The STM32 wolfSSL profile for `SecP256r1MLKEM768` must enable the current wolfSSL ML-KEM feature guards `WOLFSSL_HAVE_MLKEM` and `WOLFSSL_PQC_HYBRIDS`. Legacy Kyber-only macros are not sufficient because the pinned wolfSSL supported-group API only registers the hybrid named group under those guards.

The PQC MQTT experiment sets a 60-second UART hard limit because ST67 initialization, Wi-Fi association, DHCP, DNS and the hybrid TLS handshake all occur inside the same capture. Successful runs still terminate early after the explicit completion marker and configured grace interval. After the capture process exits, orchestration performs a final marker check to avoid misclassifying a marker written at the timeout boundary. MQTT command publisher failures are counted and retained in the result evidence rather than suppressed.

## External cryptographic prerequisite phase

Executable experiment plans prepare declared external dependencies before build configuration. `prepare_external_dependencies()` resolves MQTT TLS certificate profiles and returns a resolved context consumed by generated build configuration, broker deployment, and manifest creation. TLS YAML uses `mqtt.tls.certificate_profile`; direct `certificate_refs` in source YAML are prohibited.

Secure-boot signing similarly resolves the complete signing tuple below `secrets/wolfboot/tuples/` before invoking signing. Missing or partial tuples fail before signing. Tuple creation remains owned by the wolfBoot preparation workflow; application signing does not silently reconstruct key material.

## Classical PKI with TLS 1.3 PQC key exchange

Encrypted MQTT experiments use TLS 1.3 only. `scripts/provision_certificates.py` is a generic offline X.509 provisioner. Certificate-profile definitions live under `configs/tls_auth/*.yaml`; each filename and `id` maps directly to `secrets/certificates/<profile-id>/`. The initial profiles are `rsa3072`, `ecdsa-p256`, `ecdsa-p384`, `ed25519`, and `mldsa65`, each currently defining a root, intermediate, broker leaf, STM32 client leaf, and distinct health-check client leaf. Profile YAML controls key generation, certificate digest/signature metadata, validity, hierarchy topology, leaf identities, EKUs, DNS names, and IP SANs. Experiment prerequisites consume this material only and fail if it has not been provisioned.


### MQTT authentication-mode separation

The gateway broker exposes explicit TLS 1.3 server-authentication and mutual-authentication profiles. Experiments selecting `certificate_profile: rsa3072` authenticate with the directly provisioned RSA-3072 hierarchy; OQS/hybrid profiles independently select their TLS key-exchange group. Mutual-TLS profiles validate the STM32 client certificate against the selected staged CA chain, while broker health checks use a separate generated client identity. Host-side validation commands must match the profile: server-auth validators omit client credentials, while mutual-TLS validators supply the staged client certificate and key.

STM32 mutual-TLS profiles may use disposable experiment client keys as explicit build inputs and retain them in the owning result. This result retention does not establish a production device-key provisioning or protected-storage design; production-grade key storage remains outside the framework evidence boundary.

### Profile-selected STM32 TLS algorithms

STM32 MQTT/TLS builds resolve each experiment TLS profile into a deterministic algorithm set before CMake configure. The generated selection controls both wolfSSL compile definitions and conditional wolfCrypt source inclusion. Classical RSA TLS 1.3 builds enable RSA-PSS verification and advertise `rsa_pss_rsae_sha256`. PQC hybrid TLS adds only the `SecP256r1MLKEM768` key-exchange implementation while retaining classical RSA server-certificate authentication. Post-quantum signature schemes are not TLS capabilities in this framework; firmware-signing algorithms remain confined to wolfBoot secure-boot profiles.

The resolved algorithm set drives generated CMake and compile definitions. Because every application build request invokes CMake/Ninja, profile changes are handled by the build system and reflected in the final ELF SHA-256. Compile-time capability evidence and emitted ClientHello evidence remain separate: generated CMake/compile definitions prove selected build capabilities, while the UART `wolfMQTT TLS ClientHello` marker proves the schemes emitted by the running STM32 binary.

## Human-facing experiment progress reporting

The experiment CLI has a shared timestamped progress reporter for major workflow
boundaries. Orchestration code emits progress at stage transitions rather than
echoing complete subprocess logs. Relevant events include profile and crypto
resolution, prerequisite preparation, build execution, compiler warning
counts when captured output is available, gateway-facing flash and UART work,
secure-boot stages, and managed MQTT broker lifecycle work.

Console progress is not a separate evidence model. It may explain that a stage
is starting or report a completed return code, but the result manifest remains
the source of truth and retained logs remain the supporting evidence. Crypto
text describes resolved configuration and compiled capabilities; it must not be
interpreted as proof that a runtime handshake, signature verification, publish,
or subscription succeeded unless the corresponding recorded evidence supports
that claim.

### Human-facing experiment progress output

The experiment CLI emits concise timestamped operational progress for profile resolution, cryptographic selection, prerequisites, configuration, build execution, gateway use, flashing, UART capture, managed broker lifecycle, MQTT command/response validation, cleanup, and final result recording. TLS cryptographic progress reports both the canonical authentication profile (for example `rsa3072`) and the derived TLS signature scheme (for example `rsa_pss_rsae_sha256`) so selected profiles remain distinct from implementation settings. The progress timezone defaults to `Australia/Melbourne` and may be overridden with the `PQC_PROGRESS_TIMEZONE` environment variable using an IANA timezone identifier. The timestamp includes its timezone abbreviation.

CMake configuration and build execution are separate progress stages. The framework always invokes both commands; Ninja decides whether individual object files require recompilation.

Console progress is not an additional evidence class and must not be interpreted as proof of success. The result manifest and retained stage logs remain authoritative. Progress messages must not disclose private keys, passwords, wireless PSKs, or sensitive command arguments.


### Application build execution and artifact identity

Framework-level application build reuse and source/dependency fingerprinting are disabled. Each application build invokes CMake configuration and `cmake --build`; the retained Ninja build tree provides native incremental recompilation. Successful builds receive a new normal build number and an identity derived from the final ELF SHA-256. Run manifests and immutable build records store `reuse_enabled: false`, `incremental_build_system: cmake-ninja`, `artifact_identity_algorithm: sha256-elf`, and the ELF digest. Flash verification compares the selected ELF against the referenced immutable record digest and does not re-evaluate repository source state.


### Integrated MQTT secure-boot execution

The `run` command supports `--boot-mode wolfboot --boot-algorithm <id>` for
end-to-end MQTT experiments. The experiment YAML remains authoritative for
MQTT/TLS cryptography, broker orchestration, and expected protocol evidence.
The boot algorithm is resolved independently from `configs/secure_boot/` and the
target from `configs/targets/`.

The integrated path prepares dependencies and signing state, builds wolfBoot,
builds the selected experiment with the relocated application preset, signs the
resulting image, performs the two-artifact flash, and then executes the normal
MQTT broker/UART command-response validation. All stage references are recorded
under the primary experiment result directory. Partial or mismatched signing
tuples continue to fail safely; only a completely absent tuple may be created by
its owning wolfBoot build workflow.


## Self-contained result material

Successful application-signing results retain the unsigned image, signed image, source ELF when available, and the validated signing tuple under `artifacts/application/` and `cryptographic-material/firmware-signing/`. Successful wolfBoot builds retain ELF/BIN/HEX outputs when generated and the validated bootloader signing tuple under `artifacts/bootloader/` and `cryptographic-material/bootloader-signing/`. MQTT prerequisite preparation retains the selected certificate-profile directory under `cryptographic-material/mqtt/`.

`material-inventory.json` is the result-local index. Each entry records a result-relative path, source path, SHA-256 digest, size, role, classification, private/public flag, and intended use. Canonical generated state remains the only source for later workflows; archived copies are reproduction evidence and must not be auto-selected as future inputs.

### MQTT broker packet-evidence boundary

Managed MQTT experiment brokers enable packet-level Mosquitto logging. End-to-end STM32 runs retain explicit host publisher/subscriber identities, topic-qualified subscriber output, the complete broker log, and a parsed `mqtt-broker-message-evidence.json` summary. A passing result requires independent broker evidence for STM32 subscription acknowledgement, command publication routing to the STM32, response publication received from the STM32, and response routing to the host subscriber, in addition to the existing UART and payload-correlation checks.

Broker packet logs establish broker-observed MQTT routing. They do not independently prove firmware-internal state or necessarily expose complete application payload bytes; those claims require the corresponding UART and retained subscriber evidence.

### Gateway packet-capture evidence

Full firmware runs with a top-level `network` profile own a bounded gateway `tcpdump` lifecycle. Capture begins before the STM32 reset that initiates network execution and is collected during guaranteed MQTT orchestration cleanup on both success and failure paths. The result retains `gateway-network-capture.pcap` and `gateway-network-capture.log`; `manifest.json` records the selected interface, effective filter, optional STM32 MAC address, lifecycle return codes, artifact filename, byte count, SHA-256 digest, and any failure reason.

`network.packet_capture.stm32_mac_address` is the preferred selector because it includes address acquisition and protocol traffic involving the device without depending on its DHCP lease. When no MAC is configured, the default `any`-interface capture is intentionally unfiltered to preserve DHCP, DNS, ARP, TCP, TLS, MQTT, and failure traffic, but it may contain unrelated gateway traffic and must be handled as sensitive experiment evidence. Packet capture is supporting network evidence; it does not independently prove firmware state, TLS authentication, MQTT semantic success, or endpoint identity.

The unit test boundary is `tests/unit/test_gateway_packet_capture.py`, covering configuration resolution, MAC filtering, process ownership, collection, non-empty artifact validation, and hashing. Live verification remains part of the existing gateway/hardware MQTT experiment commands because it requires gateway capture privileges and real STM32 traffic.


## Relocated secure-boot build defaults

The secure-boot application vector remains logical `0x08023000` after the 12 KiB image-header reserve, but the flash/update layout is selected by the resolved `firmware_mode`.

`single_bank` preserves the legacy primary/update/software-swap arrangement. `dual_bank_no_ota` and `dual_bank_ota` use the symmetric STM32L4R5 hardware-bank layout: each 1 MiB physical bank is a complete boot environment with a 128 KiB wolfBoot/metadata reservation at bank offset `0x00000` and an 896 KiB signed application slot at bank offset `0x20000`. `dual_bank_no_ota` compiles out the application OTA receiver/staging path; `dual_bank_ota` enables it. Hardware BFB2 switching is not selected in `single_bank`.

Release is the default build mode and `--debug` changes compiler configuration without changing the selected mode's flash addresses. The default wolfBoot algorithm is `integrity_sha256`, which verifies the image SHA-256 digest but performs no signature or signing-key authentication. It therefore does not require or resolve a signing tuple.


### MQTT experiment test matrix

Completion-marker composition is covered without hardware by `tests/integration/test_mqtt_experiment_completion_markers_in.py`. The integration cases load the maintained MQTT experiment profiles, verify the exact mode-specific marker, and validate direct-flash, integrity-wolfBoot, and ML-DSA-65 wolfBoot command selection.

The former physical-board MQTT experiment matrix module is no longer present. The remaining `--pqc-hardware-experiment-matrix` option does not provide matrix coverage by itself. For focused plaintext MQTT validation, use the self-contained test through the gateway-enabled wrapper:

```bash
./scripts/dev.sh pytest-hardware tests/hardware/test_mqtt_plaintext_st67_e2e_hw.py -m hardware --pqc-require-hardware
```

The focused test checks its own retained broker and STM32 reporting evidence. It does not establish the former plaintext/classical/hybrid, direct-flash/wolfBoot matrix. No full-matrix hardware success is claimed without the corresponding implemented tests and recorded evidence.


Managed MQTT brokers are rationalised on the pinned `eclipse-mosquitto:2.1.2-alpine@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797` image. Its OpenSSL 3.5 runtime provides native classical and ML-KEM/hybrid groups; the hybrid profiles select `SecP256r1MLKEM768` without an external OQS provider. TLS-enabled runs collect Mosquitto's NSS-format key log into `mqtt-broker-tls-keylog.log`, colocated with the gateway packet capture, and record its size, SHA-256 digest, and collection status in the manifest.


### MQTT TLS key-exchange matrix

The maintained STM32 MQTT/TLS matrix contains server-authentication and mutual-authentication profiles for `x25519`, `secp256r1`, `secp384r1`, `secp521r1`, `X25519MLKEM768`, `SecP256r1MLKEM768`, and `SecP384r1MLKEM1024`. Experiment resolution emits one wolfSSL named-group token and compile capability set. CMake includes `ecc.c`, `curve25519.c`, and ML-KEM/SHA-3 sources only when required by that group. ML-KEM-768 and ML-KEM-1024 are mutually pruned through wolfSSL parameter-set guards. Runtime evidence must record the configured and negotiated group and reject a mismatch.

Prime-curve TLS selection keeps the negotiated key-exchange curve independent from certificate authentication. `PQC_TLS_ECC_BITS` identifies the selected prime-curve key-exchange size. The certificate profile is independent of the key-exchange group. ECDSA P-256 and P-384 profiles require the corresponding certificate-side ECC support and `PQC_TLS_ECC_MIN_BITS` must reflect both certificate authentication and key exchange when either uses ECC.

The framework does not infer stack or heap sufficiency from firmware size. Each hardware run must retain task stack high-water and heap-boundary markers. `SecP384r1MLKEM1024` is expected to be the highest-pressure profile, but any memory increase requires recorded evidence; this expectation is not itself runtime evidence.


## Selectable STM32 MQTT application fixture

STM32 MQTT experiment profiles may select `firmware.application`. The registered applications are `mqtt_validation`, `mqtt_ready_metrics`, and `mqtt_ready_metrics_2`; omitted values resolve to `mqtt_validation` for compatibility. Existing ready-metrics profiles retain `mqtt_ready_metrics`; Ready Metrics 2 is a separate timing workload. The selector changes only
the MQTT workload source compiled into the firmware. FreeRTOS, lwIP, ST67 Wi-Fi,
wolfMQTT/wolfSSL, broker orchestration, packet capture, flashing, and result
evidence remain shared framework fixtures.

The build writes `build/<preset>/pqc_generated/pqc_application_selection.cmake`
before CMake configure. CMake maps the registered identifier to one application
source and fails on unknown identifiers. The selected application is recorded in
build and generated-state evidence. `mqtt_validation` preserves the existing
bounded smoke-test and command/response behaviour through the shared
`PQC_MQTTApplicationFixture` callback interface. `mqtt_ready_metrics` keeps one MQTT session active and preserves the existing application connection metric from immediately before TCP connect through successful MQTT CONNECT. TLS timing, phase/primitive and memory observations remain in bounded RAM while the sensitive interval is active. The experiment broker carries only the workload response required by the experiment; scientific result records are not published there. After the final workload boundary the application returns to the common deferred-reporting stage, serialises the retained observations into the preallocated result buffer, and publishes them through the dedicated reporting broker. Ready Metrics 2 appends explicit `rm2_timebase`, `rm2_checkpoints`, `rm2_metrics`, and `rm2_complete` records at this stage; therefore its canonical timing/checkpoint evidence is present in the same completion-bounded, hash-validated STM32 result stream as TLS and memory evidence rather than in a second direct MQTT result path.

`mqtt_ready_metrics_2` adds application-level timing without changing the Ready Metrics 1 contract. Schema v3 defines six canonical application metrics: `rtfb_us`/`rtlb_us` run from the operational wolfBoot-entry reset origin to the first/final requested application-payload byte; `ttfb_us`/`ttlb_us` run from TCP-connect initiation to those same payload boundaries; and `req_tfb_us`/`req_tlb_us` run from the application transfer request to those boundaries. The first MQTT CONNACK/plaintext response byte is retained separately as MQTT readiness and is never labelled TTFB. `application_transfer_us` remains the optional first-payload-byte to final-payload-byte duration and is not ReqTLB. All research checkpoints are captured from the dedicated 1 MHz application timebase. DNS is deliberately excluded from the TCP-connect origin. The result bundle records the underlying TCP-connect-start, MQTT-readiness, application-request, first-byte and final-byte checkpoints plus explicit operational-reset provenance so every derived metric can be re-derived and validated offline. The default payload is 200 KiB (`204800` bytes) and is configurable through the workload profile; the gateway responder sends deterministic payload chunks over one MQTT publisher connection and the STM32 validates the exact byte count without allocating the complete payload in RAM. After the final payload byte, the firmware may emit diagnostic UART markers using the same canonical names (`PQC_RM2_METRICS`, `PQC_RM2_RESET`, and `PQC_RM2_MQTT_READINESS`); UART remains fallback/diagnostic evidence and normal structured results continue to use the deferred reporting plane.

The methodology is deliberately comparable rather than numerically identical to the Web benchmark. The prior work uses a small client request followed by server-to-client TLS application data; Ready Metrics 2 uses a small MQTT request followed by broker-mediated responder-to-STM32 application data. MQTT CONNECT and SUBSCRIBE add protocol-specific work, and the embedded STM32/wolfSSL/wolfMQTT platform differs from the server-class TLS stack, so absolute values are reported as an embedded application data point rather than treated as direct equivalents. Ready Metrics 2 records the underlying TCP, TLS, MQTT-readiness, application-request, first-byte and last-byte checkpoints as microsecond values. When a valid wolfBoot handoff record is present, the same record also carries reset-origin-relative checkpoints; direct-flash runs retain valid application-relative timing while marking reset-origin timing unavailable. The former post-`HAL_Init()` millisecond origin is no longer used as research evidence.

Ready Metrics 2 completes the measured transfer before any structured result publication. The compatibility `ready` response remains part of the workload, but timing, memory and TLS evidence stay in RAM and are transferred only after the workload returns. The common reporting path publishes bounded sequenced chunks under `pqc/result/stm32/<run-id>/...` followed by one completion record carrying record/chunk counts, logical byte count, overflow/drop state and the SHA-256 of the logical buffered stream. Packet capture excludes reporting-broker port 1886 by default so reporting traffic is not counted as experiment network evidence. Future MQTT workloads must add a
registered source implementation and application-specific runtime evidence; they
must not bypass the shared network or orchestration fixtures.

### STM32 UART output modes

UART is diagnostic/fallback evidence, not the normal structured-result transport. `uart_output_mode` is part of the resolved firmware identity and accepts `disabled`, `minimal`, or `full`. `disabled` is a compile-time exclusion: LPUART initialisation is omitted and the HAL UART implementation is not linked. `minimal` retains UART for boot, fault, recovery and post-measurement/reporting-failure diagnostics but suppresses output while the measured workload is active. `full` bypasses that suppression for troubleshooting and is explicitly allowed to perturb measurements.

Run acceptance does not require UART marker strings. Structured STM32 result acceptance is based on reporting-collector run identity, ordering/count validation, completion state and logical-buffer hash. UART logs, when enabled, remain distinct raw diagnostic artefacts.

`uart.log` is the raw captured device stream only. The UART capture stage must not prepend repository paths, capture commands, expected-marker checks, timing/memory summaries, clock derivations, or other framework-generated interpretation. Per-run acquisition metadata such as device, baud, requested/actual duration, reset/restart use, capture return code, byte count and acquisition status belongs in the run manifest/capture metadata. Scientific interpretation of UART contents belongs after the immutable capture boundary under `analysis/` with input-hash and parser lineage. Legacy workflows that cannot use reporting-MQTT completion may inspect raw UART markers transiently for orchestration, but those observations are not part of the authoritative UART capture artefact and do not convert the capture stage into a scientific parser.

### Structured UART tick evidence

STM32 application UART lines may use the structured prefix
`[tick=NNNNNNNNNN]`, where the value is the `HAL_GetTick()` millisecond count
since application startup. Experiment profiles using this logger declare
`uart.expected_tick_prefix: "[tick="` rather than requiring a standalone
heartbeat line. Legacy profiles may continue to use `uart.expected_tick_message`
when the heartbeat itself is part of the evidence contract.

UART numeric formatting must use a non-overlapping source and destination
buffer. In-place reversal is prohibited because it can corrupt clock, memory,
IPv4, and other recorded evidence. INFO logging suppresses whitespace-only
records and the complete ST67 informational banner; DEBUG retains diagnostic
detail.

### Ready-metrics application experiment matrix

Operational MQTT cases are resolver-generated from canonical campaigns and profiles. The selected workload, TLS KEX, TLS authentication, authentication mode, secure-boot profile, and network condition are recorded in the resolved case and provenance identity. Runtime commands consume only generated cases under `.pqc-generated-state`; source-controlled campaign YAML remains declarative input rather than an executable experiment profile.

## General campaign executor and repetition policy

`scripts/run_campaign.py` is the first-class outer campaign executor. It operates above `scripts/experiment.py`; it does not replace the experiment runner's ownership of preparation/runtime execution, validation, per-run result creation, or run-evidence finalisation. Canonical campaign YAML owns an explicit execution policy: repetitions, reset policy, build/flash once per firmware identity, compatible broker reuse, always-available reporting broker, condition retention within a condition, and per-run evidence. Policy/profile compatibility is validated before preparation or hardware access. A workload that explicitly requires a fresh boot cannot be executed with `reset_between_runs: none`.

Campaign expansion remains deterministic through `ConfigResolver`. Cases are initially grouped by the resolver's build-affecting firmware identity, which includes target, workload and workload compile-time overrides, TLS KEX/authentication capability, authentication mode, secure-boot selection, and source profile hashes. That identity is only a preparation candidate key: reusable execution is bound to the final firmware/ELF SHA-256 produced by a successful, finalized preparation run. Preparation is performed once per unchanged firmware group using a baseline network condition so network impairment is not part of firmware validation. Runtime repetitions reference that finalized preparation manifest and validated firmware SHA-256. Finalized Request-16 manifests may store the detailed firmware record in `run-provenance.json`; runtime-only preparation validation accepts that authoritative provenance snapshot rather than requiring a transient root-level `firmware` block.

The executor groups cases by firmware, then by network-condition identity. At a condition boundary it applies the existing experiment-broker-veth impairment once and retains it across all repetitions for that condition. Per-run packet capture, reporting result collection and diagnostic UART remain run-owned and are started/stopped for every repetition. The experiment runner receives explicit campaign-ownership controls so it health-checks a reused broker, records campaign/repetition/preparation provenance in the compact `configuration.campaign_execution` section, collects broker evidence without stopping campaign-owned services, and does not remove a campaign-owned condition. Standalone `experiment.py run` behavior is unchanged: it continues to own broker and condition lifecycle itself.

Broker compatibility is a hash over the effective experiment service/profile identity, listener endpoint, TLS policy, certificate identity and KEX/authentication selections. A compatible broker may remain active, but status/readiness is checked before reuse; an incompatible or unhealthy broker is stopped and restarted. The reporting broker remains a separate mandatory plaintext service. Campaign cleanup always attempts network-condition removal before broker shutdown, including failure and interruption paths. A cleanup failure changes the campaign outcome to failed.

Every repetition has a distinct Request-16 run directory and finalized `pqc-run-evidence` manifest. The compact configuration index retains campaign id, case id, condition identity, repetition index, preparation-manifest reference, final firmware SHA-256, reset choice and infrastructure ownership. Campaign-level state is kept separately in `campaign-manifest.json`, recording source/configuration identity, expanded cases, firmware grouping, preparation dependencies, condition events/order, repetitions, per-run manifest references, failure state and cleanup outcome.

Runtime subprocess failures and rejected per-run evidence are recorded as failed repetitions and do not stop the remaining matrix. The finalized campaign index reports `completed_with_failures` with completed/failed/planned counts; the CLI returns 1 only after finishing the matrix and cleanup when any repetitions failed (all-success returns 0). Preparation and broker setup failures block the remaining unstarted repetitions in the affected firmware group and continue to the next group after successful cleanup. These `blocked` entries have no runtime manifest and are counted separately from failed runtime attempts; resume retries them. Already completed and failed runtime evidence remains retained. Condition verification, cleanup failures and interruption remain fatal. Resume retries failures while retaining previous attempt references and separate retry logs. Failed attempts do not have to advance impairment packet counters; the condition is checked again before the next attempt.

Resume is explicit (`scripts/run_campaign.py --resume <campaign-manifest.json>`). The source/resolution identity must still match. A recorded preparation is reused only after its finalized manifest, firmware identity and authoritative firmware SHA-256 validate. A completed repetition is skipped only when its finalized manifest has successful execution, accepted raw capture and matching campaign/case/condition/repetition/firmware fields. Stale or partial entries are rerun. Fully validated completed firmware groups are skipped before hardware work. Each group with pending repetitions is prepared/built/signed/flashed again on resume, even when its saved preparation is valid: that historical record does not establish the current device contents. Both wolfBoot and the application are restored by the normal preparation path; a preparation/flash failure blocks that group before runtime reuse; subsequent groups may proceed after successful cleanup. Prior preparation references are retained, and a changed firmware SHA-256 causes previously successful repetitions in that group to be rerun under the existing matching rules. This is restoration by flashing, not flash readback or device attestation. Broker and impairment process state is never trusted from the previous process: infrastructure is re-established and checked before resumed execution.

Campaign repetition is an outer independent framework/device run. It is separate from workload-internal iterations such as multiple fresh TLS handshakes within one boot. `reset_between_runs: hardware_reset` uses the existing gateway reset helper at the beginning of every repetition; `none` suppresses that outer reset only when the selected workload explicitly permits it.

The `tls_matrix_energy` campaign combines three KEX families, two certificate profiles and server/mutual authentication using Ready Metrics 2. It selects the passive energy instrument for all twelve conditions and requests ten reset-separated runs each. The companion `notebooks/tls_matrix_energy.example.json` exercises A2 without waiving unknown controls or merging evidence classes. Operation and notebook commands are in [the TLS matrix procedure](005_remote_flash_workflow.md#tls-matrix-with-energy-and-notebook-analysis); first live matrix evidence remains tracked by DTR-TLS-MATRIX-ENERGY.

## Controlled network degradation grid

Gateway MQTT experiments may declare `network.degradation`, but Request 15 no longer applies `tc` or MTU changes to the gateway physical interface. The framework resolves the running experiment Mosquitto container, discovers its host-side veth peer, and applies egress netem plus IFB-backed ingress shaping to that veth only. MTU is changed only on the experiment-broker veth pair (host peer and container `eth0`). The reporting broker remains on its separate unmodified Docker/control path, so result collection can complete while an experiment condition remains installed. The framework retains requested/effective impairment state, resolved experiment-veth identity, lifecycle return codes and cleanup result as raw network-control evidence. Effective state must be checked separately in both directions before acceptance; a successful command exit code alone is not applied evidence.

The implementation uses separate egress and IFB-backed ingress `netem` qdiscs on the experiment broker's host-side veth. Symmetric RTT is divided equally between directions, while loss is sampled independently by the two qdiscs. Rate is applied symmetrically. MTU is changed only on the host/container ends of that experiment-broker veth pair; their original values are recorded independently and restored during guaranteed cleanup. The gateway physical interface and reporting-broker path are never modified. A failed apply or cleanup is an experiment failure; no success claim may be made from requested settings alone.

The canonical matrix is `configs/campaigns/network_degradation.yaml`. `scripts/run_campaign.py` consumes the resolver-expanded matrix, groups cases by build-affecting firmware identity, performs one validated preparation for each group, and then executes each condition/repetition through the normal runtime-only experiment path. Network impairment is installed once per condition and retained across its repetitions. The campaign independently rechecks both directional qdiscs, the IFB redirection and both experiment-link MTUs before and after every repetition; its two directional qdisc packet counters must advance while the repetition is running. It removes the condition before the next condition and again defensively during final cleanup. UART/result collection and experiment-data-plane PCAP remain independent per repetition. The reporting broker is not impaired and does not need condition teardown for result transfer.

### ML-DSA-65 TLS certificate profile

The MQTT X.509 provisioner generates five independent controlled certificate families: `rsa3072`, `ecdsa-p256`, `ecdsa-p384`, `ed25519`, and `mldsa65`. Each family is a complete same-algorithm root/intermediate/broker/client/health-check hierarchy. Experiment YAML selects the real certificate-profile id directly; compatibility aliases are not retained. KEM/group selection remains independent from certificate authentication.

The provisioner is offline and finite. Host execution launches a short-lived Alpine/OpenSSL container and reads the mounted certificate-profile YAML definitions. Generated private CA and leaf keys remain ignored under `secrets/certificates/`. Provisioning is an explicit user action; experiment execution never invokes the provisioner. Profiles whose configured OpenSSL algorithm is unavailable fail closed rather than substituting another algorithm.

STM32 builds compile ML-DSA-65 verification only for profiles that select `server_signature_algorithm: mldsa65`. Existing classical and hybrid-key-share/classical-authentication profiles retain RSA-PSS CertificateVerify support and are not migrated. The six `ready_metrics` hybrid key-share profiles therefore remain available unchanged, with a parallel six-profile ML-DSA-65 authentication matrix for direct comparison. TLS instrumentation qualification is profile-aware and operates on the retained raw structured result stream rather than treating UART as the scientific result transport. Every TLS run expects the common handshake/phase/hash/KDF/X.509 events plus the primitive events implied by its configured key-exchange group and authentication family; mutual-authentication profiles additionally require the matching client-sign event. Missing expected records are reported explicitly as unavailable by the qualification helper, while overflow, truncation, invalid ordering or incomplete parent/child state prevents complete analytical qualification.

## Reproducibility and software-environment provenance

Successful framework build and flash evidence records the parent repository commit and dirty state, recursive Git submodule revisions plus content-free dirty state, and the effective local versions of `arm-none-eabi-gcc`, CMake, Ninja, Python, and OpenSSL. Unavailable tools are recorded explicitly rather than inferred. Build records continue to bind the generated firmware ELF by SHA-256, while secure-boot flash evidence binds the exact wolfBoot and signed-application artifacts by SHA-256. These hashes identify the firmware artifacts actually selected by the recorded workflow.

The default development container pins the maintained `python:3.13-slim` image by immutable OCI digest (`python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285`) rather than following a mutable tag. Maintained external Docker image dependencies must retain a human-readable version tag and an `@sha256:<digest>` qualifier; tag-only Docker dependencies are not permitted in maintained Dockerfiles, Compose configuration, CI, or framework orchestration. The certificate-provisioning utility image is likewise pinned as `alpine:3.23@sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40`. External GitHub Actions are pinned to full commit SHAs with the release tag retained as an inline maintenance comment. `scripts/check_dependency_pins.py` enforces these rules in CI before container build/runtime validation. The build image also freezes Debian resolution to the `20260914T040000Z` snapshots of the `debian` and `debian-security` archives and installs the validated Trixie package set with exact versions. This includes the ARM compiler/binutils/Newlib toolchain, CMake, Ninja, OpenSSL, Git, OpenSSH client, CA certificates, and `build-essential`. The OCI digest, snapshot timestamp, exact package versions, and execution-time version evidence together define the reproducible compiler/tool environment; snapshot and package pins must be advanced together as an intentional maintenance change. The broker runtime is consistently declared as `eclipse-mosquitto:2.1.2-alpine@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797` in Compose, broker control code, experiment orchestration, and CI. Gateway broker startup records the configured digest-qualified image and queries the image on the gateway for the effective Mosquitto version.

Canonical configuration stores Wi-Fi credentials only as named environment references. Resolver-generated cases preserve the selected profile hashes, configuration identity, firmware identity, and the secret-reference-bearing target profile hash without materialising the referenced values. Runtime secret resolution occurs only when constructing the in-memory execution bundle. Result and provenance writers must continue to redact secret-bearing keys and must not serialize resolved Wi-Fi values.

Gateway broker deployment treats certificate profile directories as sensitive staging state. Directories are mode `0700`, private `*.key` files are mode `0600`, and non-key certificate/profile files may be mode `0644`; broad recursive read grants over the certificate tree are prohibited. Container-local broker startup retains its existing private-key restriction after copying the required key into `/tmp/mosquitto-certs`.

## Versioned run-capture and provenance model (Implementation Request 16)

Every new experiment result uses schema version 3 of `pqc-run-evidence`. The authoritative responsibility of `manifest.json` is execution/capture provenance, not scientific result interpretation. The framework records what was resolved, built, deployed and captured; timing, memory, energy, TLS-instrumentation and packet-derived values remain in raw artefacts until a separate ingestion/analysis stage interprets them. This separation prevents execution code from having to understand every future metric schema and allows historical raw runs to be re-ingested with improved parsers without rerunning hardware.
During execution, some older stage helpers may still create verbose stage/metric structures because orchestration code consumes them transiently. Schema v3 removes those structures when the run is finalised. New requests must not add metric-specific fields to the final persisted manifest; scientific values belong in raw records and later ingestion outputs.

`resolved-case.json` is created before side effects and retains selected profile identities, profile-content hashes, resolver/schema identity, effective non-secret parameters and named secret references. Resolved Wi-Fi values and other secret values are excluded. The manifest retains the snapshot path and SHA-256 plus configuration/firmware identities. Detailed source, dependency, build, preparation and deployment provenance is snapshotted to `run-provenance.json`, whose SHA-256 is itself retained as required run evidence.

The `capture_contract` is generated from the resolved experiment class and feature set. Contract entries use `required`, `optional` or `not_applicable`; acquisition states are pending, available, unavailable, invalid or not applicable. Captured artefacts use an extensible common envelope containing semantic role, source class, result-relative path, producer stage/tool, size, SHA-256, requirement and acquisition result/reason. The role vocabulary is intentionally open so later reporting-broker, campaign, OTA, energy and analysis requests can add producers without changing the envelope. Finalisation also inventories retained result files that were not explicitly registered by a producer, without parsing their scientific contents. `manifest.json`, mutable manual notes and the `analysis/` namespace are excluded from this self-inventory.

Raw captured files are immutable after successful collection through the framework API. Finalisation re-hashes retained files against their indexed size/SHA-256 and makes them read-only where supported; the sealed capture index remains the logical integrity boundary. The final index hashes only the compact configuration identity/reference, capture contract, semantic artefact inventory, compact retained-file inventory, execution outcome and capture-acceptance decision. Detailed preparation/source provenance is covered transitively by the hashed `run-provenance.json` artefact. Interpreted metrics are not part of that immutable run-capture digest.

`execution_outcome` is deliberately separate from `capture_acceptance`. Execution outcome records only orchestration/SUT completion facts such as completed, failed, not executed or not applicable and may use the expected endpoint/completion marker as its basis. `capture_acceptance` means only that all raw artefacts required by the resolved capture contract were retained and passed integrity checks. It does not claim that every scientific metric is present, parseable or valid. A completed workload may therefore have incomplete capture, while a failed workload may still have a complete and analytically useful capture package.

Finalised schema-v3 manifests are deliberately compact. Verbose runtime blocks used temporarily during orchestration (including parsed UART/TLS/memory/secure-boot stage payloads) are discarded from the root manifest. Reproducibility/deployment metadata needed beyond the compact index is written once to `run-provenance.json` and hashed as required evidence. Unregistered retained files are listed in `retained_files` using only result-relative path, byte size and SHA-256; semantic contract artefacts retain their richer role/producer/requirement envelope.

Scientific ingestion and analysis occur after capture. Derived outputs do not reopen or mutate the finalized run manifest. They are stored under the result-local `analysis/` namespace with separate lineage records containing parser/analyser identity and version, direct input SHA-256 values, analysis parameters, output size and output SHA-256. Reanalysis may create a new lineage/output record while the original raw capture and finalized run manifest remain unchanged. Request 7 is the first explicit consumer of this offline-analysis boundary, but the same rule applies to later timing, memory, TLS, benchmark and energy ingestion.

### Offline run inventory and timing dataset (Analysis Request A1)

`scripts/export_timing_dataset.py` accepts repeated explicit `--run-dir` inputs or
one explicitly selected `--results-root`, plus a new `--output` directory. It is a
read-only consumer of retained evidence, not an experiment command. Generated
cross-run products belong under an explicitly named `results/analysis/<dataset>/`
location. No per-run derivatives are needed by A1; if later consumers create
those, the existing run-local `analysis/` ownership remains unchanged. Outputs
must not be inside, equal to, or an ancestor of a selected raw run. Existing
output directories and symlink inputs/destinations are refused. The CLI reports
per-run problems in the dataset rather than failing the entire batch; exit 0
means export/check completed, not scientific success. Bad selections, output
collisions and invalid dataset checks exit 2.

Root discovery excludes `analysis`, `preparations`, `prerequisites`,
`cryptographic-material`, `builds`, `secrets`, `.git`, `.venv`, `__pycache__` and
`.pqc-generated-state`. It stops descending once a run is found. Known non-run
manifests are listed as exclusions in the selection snapshot; unreadable
candidate manifests remain inventory entries. Explicit run inputs may identify
missing directories and still receive an unavailable inventory row. An empty
discovery is an error rather than a misleading empty successful dataset.

**Commands and typed loading.**

Export selected **existing** captures without running experiments, signing, building
firmware, contacting a gateway, or changing raw evidence. No additional Python
packages are required. Use a new generated destination for each snapshot:

```bash
./scripts/dev.sh python scripts/export_timing_dataset.py \
    --results-root results/campaigns/SELECTED_CAMPAIGN \
    --output results/analysis/SELECTED_DATASET
```

To select individual runs instead, repeat `--run-dir`; do not combine it with
`--results-root`:

```bash
./scripts/dev.sh python scripts/export_timing_dataset.py \
    --run-dir results/campaigns/SELECTED_CAMPAIGN/runs/SELECTED_RUN \
    --output results/analysis/SELECTED_DATASET
```

The products are `runs.csv`, `timings.csv`, `issues.csv`, `dataset.json` and
`dataset.sha256`. A successful command means the dataset was generated, **not**
that its experiments succeeded or all timings are available. Failed, incomplete
and unreadable selected inputs remain visible. Existing datasets are never
silently overwritten. The selected root is snapshotted; later runs do not change
an existing dataset.

Verify the exported tables and their exact original consumed inputs:

```bash
./scripts/dev.sh python scripts/export_timing_dataset.py \
    --check results/analysis/SELECTED_DATASET --verify-source-inputs
```

For a relocated dataset whose original capture paths are unavailable, omit
`--verify-source-inputs`; table and metadata integrity checks still run. This is
not a fresh full-capture audit: unconsumed PCAPs, keys, images and optional channels
are not revalidated. Capture acceptance, selected-input integrity, execution
outcome and individual timing validity are separate fields.

Load in an existing Python/notebook environment from the repository root:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve()))
from framework.timing_dataset_loader import load_dataset

dataset = load_dataset("results/analysis/SELECTED_DATASET")
view = dataset.timing_view()  # typed row dictionaries; None stays missing
```

The shared loader keeps identifiers as strings and timestamps as exact Python
integers. Do not use automatic CSV dtype inference or replace missing values with
zero. The view retains failures and metric-specific timing-policy exclusions; it
performs no statistical comparison. Jupyter server setup, notebook execution,
pandas/NumPy/Matplotlib dependencies and statistical summaries belong to A2, not
this command. Definitions, source references and limitations are documented below.

A1 software verification (no hardware required):

```bash
./scripts/dev.sh pytest tests/unit/test_timing_dataset.py
./scripts/dev.sh pytest tests/integration/test_timing_dataset_in.py -m integration
```

**Verified format and reuse.** Input support is bounded to finalized
`pqc-run-evidence` v3 with capture contract v2, resolved-case/provenance snapshots
v1, reporting and logical-record envelopes v1, current outer TLS timing markers,
TLS event-buffer/repeated-iteration schema 1, and Ready Metrics 2 marker schema 3.
The implementation reuses `validate_manifest_schema`, `canonical_sha256`,
`evaluate_capture_acceptance`, `sha256_file`, the collector's `_parse_raw_stream`,
`energy_evidence.envelope`/`chunk_bytes`, TLS field extraction and
`build_derived_record`. A1 never calls capture finalization/freezing helpers and
never changes raw content or permissions. It does not invoke the reliability
runner or the legacy workload-subscriber parser. The inspected current Ready
Metrics producer no longer publishes the older scientific subscriber bundle;
its connect-duration diagnostic is not the RM2 first-CONNACK-byte checkpoint.
A missing current readiness checkpoint is therefore unavailable, not a renamed
legacy connect duration. The existing outer TLS marker remains usable without
requiring unrelated memory/primitive/phase coverage.

**Integrity and identities.** The sealed index is recomputed and the recorded
capture-acceptance decision checked using the capture evaluator. Only
`resolved-case.json`, `run-provenance.json` and `mqtt-reporting-raw.ndjson` are
selected for content ingestion, using their manifest roles and exact current
run-relative paths. Their lengths/hashes are checked before interpretation and
all consumed input bytes are rechecked before publishing the dataset. A1 records
`capture_recheck=selected_inputs_only`: the manifest's capture acceptance remains
the historical decision, not a new verification of every image, PCAP, private
material or unrelated artifact. A missing unrelated artifact cannot invalidate
an otherwise supported timing. Corruption of the consumed reporting file does
invalidate its timings even when the file also carries energy; invalid energy
acquisition content in an otherwise hash-consistent file is not interpreted by
A1 and cannot invalidate STM32 timing records.

The `run_key` hashes the recorded run ID and the exact manifest hash. Join tables
on this key, not a directory basename or `run_id` alone. The existing allocator
numbers runs within each results root, so distinct captures can legitimately
reuse a run ID across campaign roots; this produces an explicit collision
warning while retaining separate capture keys. An envelope/logical identity
conflict inside a capture makes the affected measurements unavailable. Repeated
identical paths or identical-manifest copies do not duplicate observations;
selected copies with conflicting required-input availability/integrity are
reported and cannot produce valid timing rows. Explicit `retry_of_run_id` and
`attempt_index` configuration fields, where present, are retained without
inventing retry links; otherwise they are null. Campaign repetition comes from
`configuration.campaign_execution`, not filename parsing or the campaign's
configured repetition count. Firmware/configuration identities and recorded
build/preparation references are retained without claiming new build or
preparation verification. Missing build numbers/source commits remain null with
inventory reasons; a recorded `preparation.verified=false` remains false.

Reporting epochs are transport completion boundaries, **not** inferred resets or
boot epochs. The actual logical `iteration` and recorded handshake/invocation
identifiers remain distinct. A repeated-handshake run contributes rows only for
encountered timing/status iterations; aggregate-only evidence does not generate
per-iteration observations, and a final energy-boundary epoch is not an extra
handshake. Run-level availability rows use null iteration/epoch IDs. Conflicting
iteration identities, duplicate chunks, missing completions, result-buffer
truncation and unknown schemas remain diagnostics, not guessed compatibility.
TLS phase-buffer overflow does not by itself invalidate an independently
recorded outer handshake scalar, and no phase/primitive attribution is performed.

**Metric definitions (all values are integer microseconds).** Let `T` be
`tcp_connect_start_us`, `M` the first-CONNACK-plaintext-byte readiness checkpoint,
`Q` the application request, `F` the first application payload byte, `L` the last
application payload byte, and `O` the valid reset-origin-to-application-timebase
offset. These are not broker/gateway timestamps.

| Metric column name | Formula | Meaning/evidence boundary |
|---|---|---|
| `tls_handshake` | `end_us - start_us` | Outer instrumented handshake; successful result 1 and available application timebase; any recorded outer event must agree |
| `mqtt_readiness` | `M - T` | TCP connect attempt to first MQTT CONNACK plaintext byte; not application TTFB |
| `rtfb` | `O + F` | Operational wolfBoot entry to first application payload byte |
| `rtlb` | `O + L` | Operational wolfBoot entry to last application payload byte |
| `ttfb` | `F - T` | TCP connect attempt, after DNS, to first application payload byte |
| `ttlb` | `L - T` | TCP connect attempt, after DNS, to last application payload byte |
| `req_tfb` | `F - Q` | Application request to first application payload byte |
| `req_tlb` | `L - Q` | Application request to last application payload byte |

RM2 scalars are recalculated from checkpoints and checked against the recorded
values. Its application-transfer metrics require matching payload/received-byte
counts, valid completion and consistent ordering. MQTT readiness validity does
not require valid reset handoff or the transfer scalar bundle. Invalid/missing
reset origin disables `rtfb`/`rtlb` only; application TIM2 values are never
substituted for reset-relative timing. TIM2 input frequency, prescaler, effective
1 MHz rate, counter width and wrap extension are cross-checked when the RM2
provenance marker exists. Repeated status records identify `TIM2_1MHz`; the generic
outer TLS marker only establishes available application microsecond timing, so
its unrecorded timer configuration remains absent rather than copied from a
current profile. No cycle-to-time conversion is performed. Failed TLS attempts
retain result/outcome and source references but have no successful-latency value.

Boot stack-profiling runs retain measured values for inspection but every A1
timing carries `timing_policy_exclusion=boot_stack_profiling`. Boot-UART diagnostic
runs flag reset-relative `rtfb`/`rtlb` only. Neither policy flag is a capture or
mathematical-validity failure. No comparison is selected by A1:
`comparison_inclusion=not_assessed`. The unfiltered view preserves these flags;
A2 must apply applicable control matching and exclusion rules before aggregation.

**Products and loader.** `runs.csv` contains captured configuration/build
identities, selected controls, network condition, execution/capture decisions
and observed repetition/iteration identities. `capture_class` retains the sealed
capture contract's `experiment_class`; `evidence_class` remains the separately
recorded workload evidence class. Positive runs and deliberate negative-validation
captures must not be pooled as the same experiment class. Configured impairment is separate
from verified-applied/observed impairment, which A1 does not derive.
`timings.csv` is a long-form scalar table with run/epoch/iteration/handshake
identifiers, validity/reason, boundary timestamps, clock provenance, metric
version and source references. `issues.csv` retains failures and parsing/integrity
findings. `dataset.json` stores the frozen discovered inputs, consumed hashes,
schemas/dtypes, formulas, parser/source-file fingerprints, parameters, Python
identity and output hashes. `dataset.sha256` covers the metadata without a
recursive self-hash. SHA-256 matching provides consistency checks, not a digital
signature or independent proof of capture authenticity.

`framework.timing_dataset_loader.load_dataset(path, verify_inputs=False)` checks
metadata/table hashes, exact column schemas, types, units, null/value invariants
and table joins. Identifiers remain strings, booleans remain booleans, JSON
columns become structured Python values, and timestamps remain Python integers,
including integers above 2**53. The CSV null token is `\N`; string values beginning
with a backslash have that first backslash doubled. A true observed zero remains
zero; unavailable values are `None` with a reason. `timing_view()` pivots into
one row per run/transport epoch/recorded iteration and preserves runs without
measurements. It neither drops failures nor calculates summaries. Avoid direct
CSV dtype inference. In a future pandas consumer, request nullable integer
dtypes explicitly rather than allowing a mixed `int`/`None` column to become a
floating-point timestamp.

Exports are byte-equivalent for the same paths, bytes, parser and Python version.
Relocation, alias selection, parser fingerprints and environment changes are
declared provenance differences. Output directory and generation wall time are
not embedded as unstable scientific values. A previously exported dataset can
be checked without rediscovery using `--check`; add `--verify-source-inputs` to
recheck its original consumed file paths. Dataset validation checks output bytes
by default, so relocated frozen datasets remain usable without raw evidence
present. No secret values or raw payloads are copied into the scalar export;
exports still contain experiment metadata and are not a public-release process.

**Verification and limits.** Unit fixtures provide hand-checkable values for all
eight formulas, missing/invalid boundaries, legitimate zero/large integers,
failed/unreadable inputs, deduplication, tampering, schema/identity refusals,
optional-channel isolation, policy flags and unchanged raw content/permissions.
Local integration tests run the real exporter and loader in separate Python
processes with synthetic captures; the same tests are runnable through Docker.
The narrowly selected real RM2 marker excerpt is explicitly reconstructed test
data with new synthetic envelopes/IDs/seals, not the original capture identity.
Offline replay against the supplied completed RM2 measurement and earlier
infrastructure-readiness failure has been exercised separately. The earlier
manifest records `campaign_broker_readiness`, not a TLS-handshake or application
transfer failure. Replay does not revalidate absent unrelated artifacts or
establish new hardware success.

User-supplied Linux/Docker output on 2026-09-28 confirms 61 A1 unit tests,
3 local-process integration tests and 9 Docker-workflow documentation tests
passed, plus real-capture export, consumed-input verification and typed loading.
The full unit suite reported 1,058 passed and one README-length failure
(267 lines against a 200-line limit); it was not a clean full-suite pass.
A1 usage now resides in this canonical section, with a short README link, and
`tests/unit/test_timing_dataset_documentation.py` guards that routing and the
location/required fields of the A1 deferred-test entry. Post-correction Docker
full unit regression passed during A2 on 2026-09-28; see DTR-A1-CONTAINER. Original retained
Ready Metrics/repeated-handshake captures were not supplied for this change;
those parser paths have source/fixture coverage, not a real-capture smoke claim.
A1 adds no dependencies, notebooks, statistics, energy integration, memory
accounting, packet decoding or firmware/execution changes.

### Offline timing comparisons and starter notebook (Analysis Request A2)

A2 consumes the hash-checked A1 loader through
`scripts/framework/timing_summary.py`; it never parses raw captures or executes
experiments. `scripts/summarise_timing_dataset.py` and
`notebooks/timing_comparison.ipynb` use the same functions. The notebook is a
research starter, not evidence that RQ1/RQ4 have enough measurements.

Build the development image once after dependency changes, then copy the example
analysis specification and edit the copy before selecting data:

```bash
./scripts/dev.sh build-image
cp notebooks/timing_comparison.example.json /tmp/timing-comparison.json
```

The example selects all runs as one **named baseline** for completeness inspection;
it deliberately makes no treatment comparison and no independence assertion.
Set `conditions` to non-overlapping field/value selectors, for example
`{"classical":{"tls_kex":"secp256r1"},"candidate":{"tls_kex":"ML_KEM_768"}}`,
and `baseline` to the explicitly selected reference label. This example names
recorded properties, not filenames or a recommended historical baseline.
`filters` applies exact matches to recorded values; unknown properties cannot
match. For this example declare `tls_kex` and
`controls.tls.key_exchange_group` as treatment paths, plus only other properties
that intentionally change with the treatment. Review all reported conflicts.
The `controls` array can add recorded control paths. The implementation also
checks core properties and every recorded configured control leaf by default.
Do not remove controls simply to obtain a numeric difference.

Target, gateway, workload, payload/chunk size, authentication, secure boot,
firmware mode, source revision, diagnostic flags, configured network properties,
MQTT settings and service/profile properties must remain fixed unless explicitly
declared treatments. ELF/configuration/build identities remain in inventory for
provenance and are not required equal. Treatment-specific profile hashes may
be declared treatment paths; unrelated profiles remain controls. A1 does not
export private credential hashes. Missing controls refuse matched interpretation;
absolute distributions remain available. `not_applicable` maps control paths to
explicit methodological reasons, never automatic guesses for missing values.
Recorded observed/applied network state remains unavailable and is not inferred
from configured controls. Capture/evidence classes are separate strata; mixed
classes cannot silently form a single matched comparison. Positive and negative
validation cases are never pooled.

`exclude_runs` maps exact A1 run keys to reasons, including any operator-selected
infrastructure exclusions. Every selected input remains in inventory; filtered,
nonmatching and explicitly excluded attempts retain their reasons. By default,
failures remain included and there is no outlier removal. Completion means the
recorded framework execution outcome `completed`, not inferred protocol success.
The binary denominator is **completed + failed** included runs; other outcomes
are unknown and separately counted. Capture acceptance and timing validity are
reported separately and do not convert an unknown outcome to a success/failure.

Latency distributions include completed runs with verified selected inputs,
valid measurements and no applicable A1 timing-policy exclusion. Timeout
thresholds never become latency samples. Missing optional measurements remain
unavailable; no zero is inserted. Tables include contributing runs, recorded
iterations and observations. Quartiles and configurable `percentiles` use linear
interpolation; IQR is Q3 minus Q1. Matched differences subtract baseline median
from treatment median; percentage difference divides by baseline median and is
null with `zero_baseline` when the reference is zero. These are descriptive
between-condition differences, not paired-run estimates or causal conclusions.

Inference requires `independent_runs: true`, an explicit researcher assertion
that the sampled framework runs are independent. Repetition labels alone do not
establish independence. Defaults: seed 20260928, 2,000 bootstrap resamples and
95% confidence. The continuous estimand is the success-conditional median; the
percentile bootstrap resamples whole run observations equally and uses linear
quantiles. At least two contributing runs and one observation per run per metric
are required. Any recorded repeated intra-run observations suppress this
interval until A4 supplies per-run summaries, even if only one repeated
observation is valid. Binary completion uses the two-sided Wilson score interval
on independent known framework-run outcomes, with at least two known outcomes.
Recorded linked retries/attempt indices above one suppress both inference types.
Small samples can give unstable or degenerate intervals; these methods are not
hypothesis tests. Every suppressed interval has an explicit reason.

Batch export (repository root; specification must be within the mounted workspace):

```bash
mkdir -p results/analysis
cp /tmp/timing-comparison.json results/analysis/timing-comparison.json
./scripts/dev.sh python scripts/summarise_timing_dataset.py \
    --dataset results/analysis/SELECTED_DATASET \
    --spec results/analysis/timing-comparison.json \
    --output results/analysis/SELECTED_SUMMARY
```

Choose a new output directory each time; existing outputs, raw-run descendants
and dataset descendants are refused. Products: inventory, observations, issues,
completeness, distributions and differences CSVs, timing-distribution and
matched-difference PNGs, and `summary.json`. CSV nulls use `\N`; identifiers and
observation timestamps retain A1 integer/string values. `summary.json` records
the A1 metadata/lineage, direct dataset hashes, effective selection/statistical
parameters, methods, source fingerprints, package/Python versions and output
hashes. Input captures and the A1 snapshot remain unchanged. Raw secrets and
key logs are not consumed. These local scalar exports are not a public release.

Clean-kernel execution, with cell errors causing a nonzero exit:

```bash
./scripts/dev.sh python scripts/summarise_timing_dataset.py \
    --dataset results/analysis/SELECTED_DATASET \
    --spec results/analysis/timing-comparison.json \
    --output results/analysis/SELECTED_NOTEBOOK_SUMMARY --execute-notebook
```

The extra `executed.ipynb` and `notebook-execution.json` record the executed
notebook and its source/specification/output hashes. Execution timestamps and
render metadata may differ; scientific CSV values reproduce for the same
inputs, specification and software versions. A failed run may leave partial
output for diagnosis; use a new destination on retry. Exit 0 means analysis
execution succeeded, not that all comparisons are supported.

Interactive use:

```bash
./scripts/dev.sh notebook
```

Open the token-authenticated localhost URL printed by Jupyter and select
`notebooks/timing_comparison.ipynb`. Edit the configuration cell's dataset,
specification and new output paths, then restart the kernel and run all cells.
Docker publishes only `127.0.0.1:8888`; the server binds within the container to
accept that forwarding. Authentication is retained, no public host binding or
server override is accepted, and an occupied port fails rather than silently
changing ports. Stop with Ctrl-C. Notebook startup does not load Wi-Fi `.env`
values or mount gateway credentials.

Verification (synthetic tests, no firmware builds or gateway access):

```bash
./scripts/dev.sh pytest tests/unit/test_timing_summary.py
./scripts/dev.sh pytest tests/integration/test_timing_summary_in.py -m integration
./scripts/dev.sh pytest tests/unit/test_documentation_integrity.py tests/unit/test_docker_default_workflow_docs.py
./scripts/dev.sh pytest tests/unit
```

Known-answer fixtures cover arithmetic, denominators, zero references, unknown
controls, mixed capture classes, explicit exclusions, retries and repeated
observations. Local-process tests compare batch and clean-kernel scientific
CSVs, verify raw input immutability, refuse tampering and prove deliberate cell
failure propagates. Notebook integration tests generate their own synthetic raw
runs and A1 datasets under pytest temporary directories. They execute temporary
copies of the real notebooks with only the first configuration cell replaced by
test-owned dataset/specification/output paths; saved interactive campaign settings
and outputs are not CI prerequisites, and the source notebooks remain unchanged.
The remaining analysis and plotting cells execute in a clean kernel. These tests
require no gateway, hardware, private credentials or prior campaign capture and
remain in ordinary CI; live capture tests belong to the separate capability-gated
laboratory layers. A bounded loopback server test checks authenticated access;
a wrapper test checks the localhost-only Docker port mapping. Real-data replay
was also exercised on `a1-ready-metrics-2-20260928-210728`: two inventoried
runs (one completed, one infrastructure failure), with one contributing run for
each of eight metrics. The starter withheld inference and made no matched
comparison with this inspection-only specification. This verifies offline
consumption of an existing A1 dataset, not a fresh raw capture audit or new
hardware success. A2 does not add memory,
energy, TLS phase attribution, firmware changes or new experiment measurements.


### Offline application resource comparisons (Analysis Request A3)

A3 is an opt-in companion to the A1 dataset and A2 summary workflow, implemented
in `scripts/framework/resource_analysis.py`. Existing A1 CSV contracts, timing
summaries and timing-only notebook execution are unchanged. Enable resources in
`notebooks/timing_comparison.ipynb` with `INCLUDE_RESOURCES`, or use the batch CLI:

```bash
./scripts/dev.sh python scripts/summarise_timing_dataset.py \
  --dataset results/analysis/SELECTED_DATASET \
  --spec notebooks/SELECTED_SPEC.json \
  --output results/analysis/NEW_RESOURCE_SUMMARY --resources
```

Add `--execute-notebook` for clean-kernel notebook execution. Resource analysis
requires the original retained inputs at the dataset's recorded paths; run a
Docker-created dataset inside the same `/workspace` mount. It never changes raw
captures, runs a build, flashes firmware or instruments memory. Resource exports
are `resource_builds.csv`, `resource_observations.csv`,
`resource_distributions.csv` and `resource_differences.csv`; `summary.json`
records parser/version, definitions, input paths/hashes and output hashes.
Only scalar metrics and lineage are exported, not ELF contents, UART text,
cryptographic material or whole provenance documents.

**Build identity and footprint.** A static observation is one unique application
ELF SHA-256, regardless of the number of runs or build numbers referencing it.
A run firmware hash can identify a signed image. In that case the preparation's
verified manifest and provenance must explicitly associate that image hash with
the application ELF hash; a matching build number alone is insufficient. This
association does not prove flashing or execution, and preparation verification
status remains in the A2 inventory. Only fixed retained `firmware.elf`,
`firmware.bin` and provenance names are read through manifest-selected roles.
Recorded `/workspace/results/` preparation references may be relocated within
the selected run's results root; symlinks and traversal are refused.

The bounded decoder supports ELF32 little-endian ARM executables with the
maintained STM32L4R5 RAM/RAM2/RAM3 linker symbols and region layout. Flash bytes
count the union of allocated file-backed section load addresses, including the
Flash copy of initialized RAM data. Debug data, ELF headers, segment alignment
padding and NOBITS reservations are excluded. Application image span includes
gaps between those sections; retained binary length is a separate metric. These
are application footprints, not signed-header capacity or bootloader footprint.
RAM static base and linker reservation remain separate. RAM3 allocated storage
includes the result buffer and workspace; their subset reservations must not be
added to that storage again. Unknown layouts or absent/invalid artifacts produce
null values with reasons, never configured capacity substituted for measurement.

**Runtime scope and accounting.** A3 decodes existing integrity-checked deferred
`memory` records and `PQC_TLS_HANDSHAKE_MEMORY` records, using A1 run keys,
transport epochs, record references and input hashes. Final heap, newlib and
workspace measurements retain run-lifetime scope with no synthetic iteration
identity. TLS before/after heap-free and stack-minimum-free checkpoints preserve
the recorded iteration, but are not reset per-handshake peaks. Available bounded
diagnostic task-stack checkpoints are retained separately, with task/stage and
UART line references; absent task or TLS evidence is not inferred from capacity.

FreeRTOS heap backing storage is already included in static RAM; dynamically
allocated task stacks are already included in heap allocation. Workspace peaks
are maximum requested capacity within the RAM3 reservation, not observed touched
bytes. Newlib allocation grows above the static base. MSP watermarks exclude
startup before `main()`; saturated measurements are retained as lower bounds and
excluded from exact-peak summaries. Independent regional peaks are never labelled
an observed simultaneous whole-system peak: `simultaneous_system_peak_bytes`
remains unavailable with the accounting explanation. No aggregate RAM requirement
is computed by adding these overlapping quantities.

Native values are bytes; **1 KiB = 1024 bytes**. Comparisons reuse A2 conditions,
filters, exclusions and control matching. Static medians count unique builds;
runtime medians use one unambiguous final lifetime observation per completed,
input-verified run. Duplicate final records/multiple epochs are visible but
excluded from those summaries. No resource confidence intervals are inferred.
Absolute and percentage differences require matched known controls; unknown
controls, unavailable metrics and zero percentage baselines retain reasons.

**Validation.** Known-answer fixtures cover section/region accounting, build
reuse, lifetime scope, saturation, malformed/missing evidence, unit conversion,
control matching, source tampering and secret-path refusal. CLI and clean-kernel
notebook integration must agree on all four resource tables:

```bash
./scripts/dev.sh pytest tests/unit/test_resource_analysis.py
./scripts/dev.sh pytest tests/integration/test_resource_analysis_in.py -m integration
```

The retained TLS matrix dataset was exported during A3 development: 12 unique
application ELF builds supplied 108 valid static resource values. Its recorded
specification leaves QoS and source revision controls unknown, and some profile
pairs have different evidence classes. Those matched deltas remain unavailable;
absolute resource tables still retain run/build/source references. This is an
offline parser/export check against retained evidence, not a new hardware run.
The missing real matched-delta acceptance is tracked in DTR-A3-MATCHED.


### Offline packet-capture analysis (Implementation Request 7)

`scripts/framework/packet_analysis.py` is the read-only packet-analysis implementation and `scripts/analyse_packet_capture.py` is its command-line entry point. The analyser requires a finalized schema-v3 run manifest, re-hashes the retained `packet_capture` and optional `tls_key_log`/`stm32_result_stream` inputs against their finalized identities, then writes `analysis/packet_capture/packet_analysis.json` and `packet_analysis_lineage.json`. The raw PCAP, TLS key log, reporting stream and finalized manifest are never rewritten.

The built-in parser derives capture packet/byte counts, IPv4 fragmentation observations, TCP connection boundaries, payload-byte counts, overlapping/retransmitted TCP payload observations, and conservative plaintext MQTT/TLS-record summaries from classic PCAP evidence. It supports Ethernet, Linux cooked v1/v2 and raw-IP link types. The maintained Docker development image pins `tshark` so retained broker TLS key logs can provide TLS/MQTT decryption enrichment in the normal reproducible workflow. `--no-tshark` explicitly disables that enrichment; if the key log is unavailable or `tshark` decryption fails, the derived record retains an explicit unavailable/failed status rather than treating encrypted traffic as parsed MQTT. No packet metric is copied back into `manifest.json`.

Correlation is intentionally conservative. The retained STM32 reporting MQTT stream is the primary structured device-side source when present; broker/observer evidence remains an independent network/application source, and UART is secondary diagnostic evidence. Packet timestamps remain in the gateway capture epoch domain while STM32 1 MHz/DWT and broker timestamps retain their own domains. The analyser records run-ID/hash identity mappings where defensible but does not fabricate offset/drift alignment or infer firmware-internal state from network traffic alone. Connection-relative packet observations may therefore assist interpretation of TTFB/TTLB without silently replacing the firmware/application timing definitions.


Build-only execution uses a build-only capture contract even when the resolved firmware is capable of runtime MQTT/TLS. Signed wolfBoot preparation remains a generic build/sign/flash contract without collected workload evidence and does not claim an energy result. The passive ESP32 has no preparation/start command; STM32 reset returns PF12 LOW and one rising/falling GPIO interval delimits the experiment. INA228 acquisition runs before and throughout that interval, then pauses only after the falling-edge timestamp has closed the measured window. MQTT publication reads an immutable PSRAM capture; after success, failure or bounded publication timeout the ring is reset and sampling resumes to rebuild pre-trigger history. Normal framework execution does not start another experiment until the preceding energy publication has completed. An unexpected rising edge during publication cancels the old transfer and invalidates that abnormal new window rather than introducing concurrent ring publication logic. Runtime contracts distinguish plaintext MQTT and TLS raw capture, with feature overlays for network degradation, secure boot, OTA and energy. The common collector validates the run-scoped STM32 stream and also records the fixed `pqc/instrument/energy/capture/#` topic. Energy validation is separate: it reconstructs the packed sample stream, accepts optional pre-trigger history capped at 1 s, enforces coverage and gap limits within the measured GPIO interval, checks sequence/chunk/hash/configuration/acquisition integrity, requires exactly one experiment-wide STM32 TIM2 boundary, and selects the newest ESP32 completion whose two-edge duration is compatible with that STM32 window. There is no ESP32 run ID, association token, MQTT command plane, clock fitting inside firmware, or online energy integration. Scientific clock mapping and joule integration belong to offline analysis. See [the instrument guide](010_esp32_ina228_energy_instrument.md) for the optional energy workflow and current hardware validation limits.

Preparation reuse is explicit. Runtime-only/repeated executions record the referenced preparation/build manifest, build number where applicable and exact firmware SHA-256. Flash code re-hashes the selected artefact before target access and refuses a mismatch against the referenced build record. Secure-boot capture separately binds wolfBoot and signed-application identities. Legacy schema-v1 manifests remain readable as historical records but are not silently upgraded or treated as satisfying schema-v3 capture contracts.

Source provenance records the parent commit, branch when available, dirty state and a SHA-256 fingerprint of the tracked diff plus untracked file content without retaining source text in the manifest. Recursive submodule revision/checkout/dirty state and effective compiler, CMake, Ninja, Python and OpenSSL versions remain recorded. Digest-qualified external container images remain canonical source configuration; execution-time image/version evidence is retained where the owning workflow can obtain it.

## Canonical versioned configuration resolver (Implementation Request 10)

The maintained configuration source of truth is the schema-versioned profile hierarchy under `configs/{targets,gateways,instruments,services,workloads,tls_kex,tls_auth,secure_boot,network_conditions,campaigns}`. Gateway profiles retain a human-readable short alias separately from the FQDN used for SSH/SCP orchestration; the current gateway FQDN is `pqc-gateway1.pqcnet`. `scripts/framework/config_resolver.py` is the canonical loader/resolver and `scripts/resolve_campaign.py` materialises derivative cases below `.pqc-generated-state/campaigns/`. Generated cases deliberately retain selected profile identities, non-secret resolved choices, content hashes, configuration identity and firmware identity rather than copying complete profile bodies. When consumed, selected profile hashes are re-evaluated; stale generated state fails before execution.

TLS authentication family and `auth_mode` are orthogonal. `configs/tls_auth/*.yaml` is also the canonical certificate-provisioning catalogue; `scripts/provision_certificates.py` consumes it directly. Ed25519 is retained as a compatibility profile but is not part of the thesis authentication campaign. Ready Metrics 2 transfer size and chunk size are workload parameters and may be promoted to dotted campaign matrix dimensions.

For a canonical generated case, `scripts/experiment.py status` reports the resolved configuration identity and the experiment-defining profile choices before any side effects. The status view includes target/gateway/workload, secure-boot and network-condition selections; configured TLS mode/version, KEX group, authentication profile/mode and signature scheme; experiment-broker endpoint/profile; reporting-broker profile; workload transfer parameters; and selected instruments. Cipher-suite policy is shown only when the resolver explicitly pins it; otherwise status states that the cipher suite is negotiated at runtime. Configured values are kept distinct from negotiated runtime evidence, which must come from UART/broker/result artefacts after execution.

The normal `run` path also consumes the canonical case's `choices.secure_boot` value when selecting the wolfBoot algorithm. This prevents the execution adapter from collapsing generated secure-boot cases to the legacy `integrity_sha256` default. A user-supplied `--boot-algorithm` takes precedence, while non-canonical legacy experiment YAMLs retain the integrity baseline when no algorithm is supplied.

The reporting MQTT service is defined separately from the experiment broker. The `reporting_gateway1` profile is plaintext/non-TLS, declares no PKI requirement and is impairment-exempt. The broker compose project provides a separate `reporting` Mosquitto profile on port 1886. Experiment startup starts this reporting service in addition to the selected workload broker, and cleanup retains its log as independent evidence. Network impairment must remain scoped to the experiment interface and must not include the reporting path.

The secure-boot catalogue contains integrity SHA-256, ECDSA P-256/P-384/P-521, Ed25519, Ed448, RSA-2048/3072/4096 and ML-DSA-44/65/87. Common STM32L4R5 wolfBoot values, including SHA-256, the 12 KiB image-header reserve and flash-layout values, live once in `configs/targets/stm32l4r5_st67.yaml`; algorithm profiles contain only algorithm-specific wolfBoot selections. `render_wolfboot_config()` generates the complete effective `.config`. Migration tests compare generated effective assignments with the existing per-algorithm `.config` files; those legacy files must not be removed until the repository's full build/runtime qualification has passed.

The three standalone ML-KEM TLS groups are explicit wolfSSL named groups (`WOLFSSL_ML_KEM_512`, `WOLFSSL_ML_KEM_768`, `WOLFSSL_ML_KEM_1024`). The generated CMake selection independently controls ML-KEM-512/768/1024 and whether standalone mode is selected. `WOLFSSL_PQC_HYBRIDS` is not defined for standalone mode, preventing silent hybrid substitution.

Request-16 secure-boot capture uses the resolved secure-boot choice and the effective wolfBoot firmware mode when generating the capture contract; it does not rely solely on the legacy top-level boot object. Deployment provenance is an identity record for the exact flashed firmware SHA-256 and is intentionally pathless. The flash transcript is retained separately as the `flash_log` artefact with its own file SHA-256. This prevents a firmware-image digest from being incorrectly validated as though it were the digest of the flash log. Signed application binaries retained under the result directory are indexed according to their actual file type and do not overwrite or invalidate a separately retained application ELF record.

### Dedicated reporting plane and deferred STM32 result publication

Every MQTT runtime experiment starts and explicitly checks the separate `reporting` Mosquitto profile. It is plaintext/non-TLS, uses port 1886, requires no experiment certificates, and owns the common control/result namespace. The gateway collector subscribes before target execution, arms the retained `pqc/control/run-id/current` value, stores the raw topic/payload stream as `mqtt-reporting-raw.ndjson`, and validates only transport integrity: run identity, source/topic association, completion-bounded sequence uniqueness/completeness, declared logical record/chunk/byte counts and logical SHA-256. A source may emit multiple complete boot epochs under one run ID when an OTA activation, confirmation, or rollback reset occurs; sequence numbers may restart only after the preceding epoch has completed. Configured instrument sources are mandatory collection sources for that run. Scientific values are not copied into metric-specific manifest fields.

The STM32 result path uses a bounded 32 KiB preallocated SRAM buffer in RAM3. Existing TLS instrumentation continues to collect low-overhead in-RAM snapshots during measurement. The default workload contract serializes application state and final memory evidence only after the selected workload returns. A bounded iterative workload may instead close and publish one completed measurement epoch between iterations when retaining all iteration evidence would exceed the fixed buffer, provided publication, formatting and buffer reset occur only after that iteration's sensitive measurement boundary and complete before the next boundary begins. The repeated TLS workload uses this exception: every fresh full TLS 1.3 handshake is measured with the TIM2-backed 1 MHz application timebase, its independently indexed TLS hierarchy is serialized after `wolfSSL_connect()` and transport cleanup, the completed epoch is published through the impairment-exempt reporting broker, and only then is the RAM3 buffer recycled for the next handshake. Reporting time is not part of any TLS measurement. Result chunks are bounded to 96 logical bytes before hexadecimal envelope encoding. A final completion record identifies the run and declares logical record/chunk counts, byte count, drop/overflow state and SHA-256. Completion-bounded sequence namespaces may therefore restart for reset-spanning boot epochs and for explicitly configured per-iteration measurement epochs; the collector validates the expected completion count from resolved workload configuration. The same collector handles instrument producers under `pqc/instrument/<source>/<run-id>/...`, with an independent completion-bounded sequence/hash namespace for every configured source.

### Hierarchical TLS instrumentation evidence

`Core/Inc/pqc_tls_instrumentation.h` and `Core/Src/pqc_tls_instrumentation.c` own the bounded TLS hierarchy recorder. The existing per-phase and per-primitive aggregate counters remain available for low-overhead summaries and compatibility consumers. Semantic handshake, phase, security-function, KEX/signature, X.509 and HKDF spans receive ordered hierarchy records. High-frequency SHA-256/SHA-384 helper invocations remain aggregate-only so hundreds of digest calls cannot crowd later semantic TLS phases out of the fixed event store; their count/total/minimum/maximum timing remains retained and participates in profile-aware completeness checks. The fixed ordered record stores the semantic event identifier, hierarchy level, sequence, depth, parent sequence, begin/end DWT cycles, begin/end application-timebase timestamps, elapsed values, completion state and operation result. Maintained TLS/wolfCrypt hook sites propagate the meaningful result available at the exact wrapped boundary rather than the unspecified sentinel. Where a verification API reports transport/execution status separately from a validity flag, the hook normalises a completed invalid signature to the path's canonical verification error so the retained outcome cannot report success for an invalid signature. The complete handshake is hierarchy level 2, received TLS protocol phases are level 3, X.509 certificate-chain verification is level 4, and algorithm-specific cryptographic operations are level 5. These are overlapping attribution views and must not be summed as disjoint time components.

The ordered event store is preallocated at compile time (`PQC_TLS_INSTRUMENTATION_EVENT_CAPACITY`) and performs no allocation, text formatting, UART output or MQTT publication inside a measured span. Exhausting the capacity does not overwrite earlier records. Aggregate accumulation continues where possible, while `event_overflowed`, `event_truncated`, `dropped_event_count` and `hierarchy_incomplete` make the ordered evidence explicitly incomplete. Duplicate begins, unmatched ends, non-LIFO end ordering and spans left active when the handshake closes increment the invalid-sequence state rather than being silently normalised. The deferred serializer emits one `PQC_TLS_EVENT_BUFFER` status record followed by sequence-addressable `PQC_TLS_EVENT` records after the workload returns.

The wolfSSL hooks remain thin calls at the existing application, `tls13.c`, `tls.c`, `internal.c` and wolfCrypt sites. The ML-KEM key-generation and decapsulation hooks are shared between standalone and hybrid TLS groups; the compile-time resolved active parameter set selects the ML-KEM-512, ML-KEM-768 or ML-KEM-1024 semantic event identity at those same call sites. `scripts/framework/tls_instrumentation.py` derives the expected semantic event set from the resolved KEX group, certificate/signature profile and authentication mode, accepting both the final `effective_non_secret_parameters.mqtt.tls` resolved-case snapshot layout and the historical `experiment.mqtt.tls` layout. It qualifies ordered hierarchy records together with retained primitive aggregates without mutating the immutable run manifest. A missing required operation is represented as an explicit `unavailable` qualification result with a reason rather than being converted to a zero-valued measurement.

### Request 14 — retained RAM2 secure-boot MQTT evidence (partial implementation)

The application linker scripts reserve the first 1 KiB of RAM2 (`0x10000000` through `0x100003FF`) for existing wolfBoot timing (`0x10000000`) and OTA event (`0x10000100`) mailboxes. The allocatable RAM2 region begins at `0x10000400`. This prevents application linker-allocated data from overlapping either mailbox, but it does not by itself prove retention through hardware reset, against explicit application/bootloader writes, or under every OTA path. The normal application-timebase handoff continues to read mailbox version 5 from its original fixed address.

Following the measured workload, `PQC_BootEvidenceAppendToResultBuffer` serializes the retained version-5 mailbox into the existing deferred STM32 result buffer using `secure_boot` context records for SHA-256 integrity verification, signature/authenticity verification, and reset-origin handoff. The individual records retain raw DWT cycles, verification result, validity, and bootloader SYSCLK/HCLK; no CPU-frequency assumption or UART timing marker is required to transfer these fields. Absent magic/version yields an explicit unavailable record. Zero cycles and absent HCLK are invalid; an absent signature sample is *not measured* (this mailbox alone cannot distinguish non-applicability from a skipped/failed signed attempt).

Normal workloads add the boot records before calculating the result-buffer SHA-256 and MQTT completion metadata. Repeated TLS workloads add them once, in the first completed per-iteration reporting epoch, after its measured interval. They do not publish an extra untracked MQTT message or change expected completion counts. The original RAM2 record remains in place; formatted evidence is copied only after measurement. The v5 mailbox has no nonce/checksum, image hash, bootloader provenance, complete-image verification cycles, or total secure-boot execution interval: these cannot be inferred from its existing fields. This partial change does **not** establish the full Request 14 timing/evidence contract or repeated-run hardware validation.

Deferred test entry: feature=Request 14 persistent RAM2 mailbox and secure-boot MQTT evidence; missing layer=containerized application build, gateway/hardware continuous-run retention and reporting; reason=source-level/host-only checks do not prove retained SRAM or publish behaviour; required capability=STM32/ST67, gateway, broker, maintained secure-boot cases; intended test=`tests/hardware/test_secure_boot_mqtt_evidence_hw.py`; eventual verification=`./scripts/dev.sh experiment-gateway run --experiment <resolved integrity_sha256 case>` and inspect `mqtt-reporting-raw.ndjson` then signed profiles, OTA and repeat-handshake cases; status=deferred, source-level tests only.

Request 14 algorithm identity extension (schema v5): the instrumented bootloader writes a compact ID for the resolved secure-boot algorithm into the RAM2 mailbox. The application decodes it into the `PQC_SECURE_BOOT_PROFILE` result and includes the identity on both verification records, independently of TLS profile identity. A parameter-bit field reports RSA modulus or ECDSA curve size only where the profile determines it; it is unavailable (zero with documented unavailable semantics) for EdDSA, ML-DSA, and integrity-only profiles. The optional declared signature capacity is not an actual signature length; `declared_signature_capacity_available=0` means that the resolved build profile did not supply this value. Integrity-only authenticity reports `measurement_status=not_applicable`, while an absent signed-profile timing record reports `unavailable`. The real public-key encoding size is explicitly unavailable until derived from verified key material outside the timing interval. This version change requires matching bootloader and relocated application builds; version-4 mailboxes are rejected rather than reinterpreted. No hashing, key parsing, UART or network transmission is added inside verification intervals.


Request 14 incremental image identity (schema v6): the deferred MQTT PQC_SECURE_BOOT_IMAGE record contains wolfBoot's already-validated SHA-256 image-content digest and selected partition when integrity verification succeeded. The digest is not the SHA-256 of the entire packaged image artifact; the latter is retained in build/flash provenance, not inferred from the image header. The hash is copied after the DWT end read and serialized only after the application workload. The v6 mailbox still lacks a boot nonce/checksum; complete-image-verification timing, total secure-boot timing and per-boot build attribution are deferred and must not be inferred from the existing individual measurements.


### Request 14 incremental attempt-isolation hardening (not final acceptance)

The generated STM32L4 wolfBoot instrumentation clears the earlier integrity,
image-digest, and authenticity evidence **before** starting every new integrity
measurement. An authenticity sample is marked valid only when its image's
partition, firmware-content length and stored SHA-256 digest match the most
recent successfully verified integrity image. `SIGN=NONE` does not produce a
valid signature-verification sample. This prevents several candidate/recovery
cross-attribution cases; it does **not** establish that the recorded image is
the final application selected for handoff, since that requires an explicit
selection checkpoint on both update paths. The version-6 mailbox layout and
working deferred MQTT publication are unchanged.

An independent complete-image-verification timer, separately bounded total
boot-execution measurement, run-to-bootloader source/artifact correlation,
negative integrity-only hardware rejection test, and complete profile-matrix
hardware validation remain **not verified**. In particular, adding an enclosing
DWT interval across the existing standard-update UART output would count
reporting overhead and must not be represented as verified computational timing.


### Request 14: selected-image timing and provenance (mailbox v7)

The STM32 application serializes boot evidence **after** workload measurement to the
impairment-exempt MQTT reporting broker. The bootloader records a DWT snapshot at the
start of image-content verification and another at the end of signature verification,
or at the end of content verification for the integrity-only build. The
`PQC_SECURE_BOOT_VERIFICATION` record is an **independently sampled enclosing
interval**, not the sum of individual cryptographic timings. It includes the
measurement-wrapper bookkeeping between the cryptographic calls. The normal
standard-flash path excludes its intervening benchmark output and signature-start
UART message while the timing instrumentation is enabled. The firmware treats
intervals longer than 30 seconds as unavailable to guard against ambiguous 32-bit
DWT wrapping at the selected clock rate; the limit is a measurement constraint,
not a boot security policy.

Candidate manifest checks, retries and bank fallbacks invalidate the preceding
image interval. Just before `hal_prepare_boot`, the selected image is checked
against the mailbox's verified partition, firmware-content size and SHA-256
content digest. If these do not match, or the required integrity/authenticity
checks did not succeed, `selected_image_valid=0` and the application does not
present those previous-attempt measurements or digest as selected-image evidence.
For a migration path that explicitly bypasses authenticity, signed-image
selected-image measurement is marked unavailable rather than silently presented
as a complete signed verification. When a hardware bank swap returns rather than
resetting, `fw_image` can still describe the old PART_UPDATE while `do_boot`
targets PART_BOOT; the selected-image checkpoint is invalidated in that case.

`PQC_SECURE_BOOT_TOTAL` labels the existing operational interval from the
start of `hal_init` to the pre-handoff LPTIM2 bridge checkpoint. It is **not**
physical reset-to-application-startup timing; that includes the handoff and
application startup. Image-content SHA-256 is **not** the signed package's SHA-256.
The host-generated result/flash manifests retain the package, bootloader and
flash-artifact hashes for separate provenance correlation. The device does not
self-measure its bootloader binary SHA-256; no on-device bootloader provenance
claim is inferred from a build-side hash alone.

Mailbox v7 changes the shared bootloader/application layout. Both images must
be rebuilt and flashed together. Unit tests check the generated instrumentation
and serialized record schema, but cannot establish an STM32 runtime result.
A successful integrity-only corrupted-image rejection and all maintained
secure-boot profiles require retained hardware evidence before the request can
be marked hardware-validated.
### Request 4 — optional wolfBoot verification stack profiling (mailbox v8)

The `runtime_stack_high_water_instrumentation` wolfBoot build option defaults to
`false`. The canonical `secure_boot_stack` campaign enables it, independently
of the secure-boot algorithm selection. The resolved `boot_stack_profiling`
choice participates in the firmware identity and the bootloader build-state
identity; a profiling build cannot be substituted for a normal timing build.
All normal DWT verification measurements and the reset-origin 1 MHz handoff
remain enabled in either mode.

The instrumented STM32L4 bootloader fills available primary RAM between the
aligned end of BSS plus 128 bytes and the *currently unused* stack area below
the live MSP, excluding an additional 128 bytes below MSP. It does so before
each integrity-verification attempt, outside the DWT interval. The
watermark is examined only after the final DWT verification end snapshot and
outside the timed interval. It is invalidated for a new integrity attempt and
accepted only if the selected-image checkpoint agrees with the verified image.
The reported high-water value is the distance in bytes from `END_STACK` to the
lowest overwritten watermark word, **not** the linker stack reservation or
`.data`/`.bss` size. It covers the instrumented interval from watermark
initialization immediately before integrity checking through completion of
image verification, including incidental interrupt stack use in that interval. It excludes
stack use before initialization, after verification, and separate FreeRTOS
application task/MSP use. If the paint is untouched, the bottom sentinel is
consumed, memory is insufficient, or the deepest observation is potentially
from the scan function itself, the metric is explicitly unavailable. This
technique detects overwritten bytes, not reserved-but-unwritten stack frames.

The appended v8 mailbox fields are `stack_profiling_enabled`,
`stack_measurement_status` (0=disabled, 1=measured, 2=initialization unavailable,
3=watermark untouched, 4=region exhausted, 5=scan interference), and
`stack_watermark_capacity_bytes`. The existing `max_stack_used_bytes` is
retained; `0xFFFFFFFF` remains the unavailable sentinel. The RAM2 OTA event
mailbox remains at offset `0x100`. `PQC_SECURE_BOOT_STACK` is appended only
when profiling is enabled, after the workload has finished and before the
result-buffer hash/completion is calculated. It states the measurement status,
boundary, timing-comparison exclusion, and `unavailable_reason` explicitly.
The reduced 128-byte exclusion makes shallow verification usage observable but
still excludes stack usage within that region. A run reporting
`watermark_untouched` or another unavailable reason must not be treated as a
measured stack value; an instrumented hardware run is required to establish
that the chosen exclusion also protects live frames. Normal runs report the
existing secure-boot records without a stack record. Both application and
bootloader must be rebuilt together for mailbox v8; the version mismatch
invalidates reset-origin bridging and secure-boot evidence rather than silently
interpreting the old record.

Stack-profiling runs are **not timing benchmark runs**: the watermark fill
changes boot duration and can change memory/cache or runtime conditions. The
verification DWT readings are retained as diagnostics, but application-boot,
TLS and secure-boot timings from profiling runs must not enter normal timing
aggregates. Cross-profile stack comparison is permitted only for successfully
selected images with explicit measured status and retained raw evidence.
Firmware/build and gateway/hardware behavior, including OTA compatibility,
remain unverified until the specified gates are executed on the development
host and STM32 laboratory target.

### Hardware-test isolation retrofit (in progress)

The `tests/hardware/test_mqtt_plaintext_st67_e2e_hw.py`,
`test_reporting_plane_isolation_hw.py`, and `test_campaign_executor_hw.py`
modules use `scripts/framework/hardware_test_support.py` to create unique
module-owned generated campaigns and persistent evidence under the active
`results/automated-tests/<run-id>/hardware/` directory. MQTT UART and broker
assertions reuse one freshly executed hardware experiment within their file;
reporting-plane conditions retain separate resolved configurations and results;
and the campaign executor uses a test-owned two-repetition baseline campaign.
The reporting-plane hardware test selects the canonical plaintext MQTT
validation campaign independently for each rate, RTT, loss and MTU profile.
It checks the finalized manifest artifact index, the retained gateway veth/IFB
configuration and cleanup transcript against the selected profile, and
independently reparses the complete run-specific STM32 reporting stream. UART
diagnostic verbosity is not an isolation-success criterion. Applied qdisc
settings and stream completeness are configuration and reporting-integrity
evidence; they do not by themselves quantify actual packet loss, achieved
throughput or observed RTT, or prove that no reporting packet ever experienced
impairment.
These modules run the existing Python experiment/campaign entry points *inside*
the current development container; they do not start nested Docker containers.
The remaining hardware modules have not yet been migrated to this contract.
This change does not establish cross-module build/signing isolation and does not
establish successful physical hardware execution without recorded test evidence.

### Cross-host gateway lease (Linux wrapper, unverified on gateway)

`scripts/gateway_lock.py` uses a persistent SSH session to hold a gateway-side
advisory `flock`. Linux wrapper gateway-enabled commands keep one lease for
the entire Docker process, including nested hardware-test and campaign
operations. Generic `./scripts/dev.sh run` and local build-only modes do not
acquire the lock; explicit `gateway-lock run -- <command>` remains available. The
administrative status/release commands and recovery restrictions are documented
in `docs/002_host_gateway_setup.md`. Direct SSH and direct Python/gateway
administration paths are not intercepted and must not be used concurrently with
protected experiments. Wrapper exit/SSH disconnect does not prove a detached
remote helper has stopped; inspect/recover gateway and STM32 state after failures.


### Request 17 optional wolfBoot UART diagnostics

The STM32L4R5 wolfBoot target has a separate, default-off early-boot UART diagnostic
configuration. `boot_uart_diagnostics` is part of the resolved choices and firmware
identity, so diagnostic and measurement builds cannot be silently grouped together.
When enabled, wolfBoot initializes the same LPUART1/PG7/PG8/115200 gateway console used
by the application and emits `PQC_WOLFBOOT_DIAG` decision records. The normal structured
application result path remains deferred MQTT reporting; boot UART is fallback/control
evidence for pre-application failures only.

The measurement policy is categorical: diagnostic-enabled bootloader runs are excluded
from reset-to-application and bootloader-entry-to-handoff timing comparisons because
UART initialization, formatting, polling and transmission add execution time. Existing
DWT integrity/authenticity/complete-image intervals are not widened and contain no UART
operations. The default `boot_uart_diagnostics: false` build preserves Request 14 timing,
mailbox, 1 MHz reset-origin bridge and deferred-reporting semantics.

Hardware completion remains evidence-gated. The maintained Request-17 test exercises
diagnostic-enabled valid/rejected images and restoration while the existing diagnostics-off
negative test remains the Request-14 control. Representative dual-bank decisions are
emitted by the hardware-swap path; success is claimed only after the corresponding
capability-gated hardware/OTA evidence is supplied.
