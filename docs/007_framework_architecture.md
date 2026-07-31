# Framework Architecture

## Purpose

This document maps the current repository architecture to implemented framework behaviour.

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

Current boundaries not yet implemented:

1. Real ST67W61M1-backed network-interface bring-up, module detection, Wi-Fi association, hardware-backed IP acquisition, and external TCP connectivity.
2. Real wolfSSL socket transport, certificate loading, TLS session creation, or TLS handshake on STM32.
3. Real wolfMQTT broker connect, subscribe, publish, receive, disconnect, or reconnect on STM32.
4. Classical or PQC/hybrid STM32 MQTT-over-TLS runtime validation and end-to-end wireless evidence.
5. PQC or hybrid MQTT/TLS experiments after classical STM32 MQTT-over-TLS is stable and library support is confirmed.
6. Hybrid signing profiles and ML-DSA-87 under the current 12288-byte image-header reserve.
7. Network degradation automation.
8. Production release packaging.

The repository does contain MQTT/TLS preparation and compatibility capabilities: framework schema and fake transport, broker-side profiles, host-side wolfMQTT/wolfSSL validation, STM32 lwIP build/local-only runtime preparation, a wolfSSL TLS-context lifecycle, an explicit unavailable transport boundary, and wolfMQTT build-only plus fake/no-network task-context initialization. These capabilities are not evidence of real STM32 networking or MQTT-over-TLS.

## Architectural organization

The architecture is organized by stable capability and evidence ownership rather than implementation chronology. Roadmap sequencing and phase status belong to `docs/non_hardware_mqtt_tls_development_plan.md`; historical framework sequencing belongs to `docs/pqc_iot_experiment_framework_plan.md`. This document owns the current system layers, firmware and framework boundaries, evidence model, generated-state architecture, test architecture, capability matrix, and deferred-test register.

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
| STM32 wolfSSL source and TLS-context lifecycle | Supported in direct and relocated firmware builds | Supported for initialization, TLS 1.2 client `WOLFSSL_CTX` create/free, and cleanup | Not applicable | Not applicable | UART smoke is capability-gated | `tls-context-lifecycle-only` | No `WOLFSSL` session, certificates, private keys, socket transport, handshake, MQTT, Wi-Fi, or ST67W61M1 |
| STM32 wolfSSL transport boundary | Supported | Boundary executes only to report unavailable operations | Not applicable | Not applicable | Optional UART evidence is capability-gated | `unavailable-transport-only` | Connect/read/write callbacks perform no socket I/O and transfer no data |
| STM32 wolfMQTT integration | Supported: pinned wolfMQTT client, packet, and socket callback layers build and link | Supported only for serialized fake/no-network client initialization/deinitialization after scheduler start | Separate native host validation exists but is not STM32 evidence | No broker used by STM32 path | Known-image UART assertion is capability-gated | Build-only plus `stm32-fake-no-network-initialization-only` | No TCP, TLS handshake, MQTT connect, subscribe, publish, receive, disconnect, reconnect, Wi-Fi, or ST67W61M1 |
| ST67W61M1 hardware-backed network backend | Driver and interface sources build in direct and relocated profiles | Association and DHCP-supported runtime | Not applicable | No broker used by this path | Capability-gated known-image UART and manifest evidence supported | `stm32-st67-wifi-association-dhcp` | Proves configured-AP association and DHCP IPv4 assignment only; external TCP, TLS handshake, MQTT, broker reachability, and end-to-end protocol success remain unavailable |
| Real classical STM32 MQTT-over-TLS | Dependencies and boundaries are prepared, but no complete runtime path exists | Unimplemented | Host-side compatibility exists separately | Broker profiles exist separately | Unimplemented end-to-end | Future hardware-backed STM32 runtime capability | Requires ST67W61M1 network bring-up, real wolfSSL transport/handshake, wolfMQTT protocol operations, UART/manifests, and broker corroboration |
| PQC or hybrid STM32 MQTT-over-TLS | Broker-side OQS experimentation exists separately | Unimplemented | Experimental host/broker evaluation only | Experimental OQS profile | Unimplemented end-to-end | Future protocol and hardware-backed capability | Must follow successful classical STM32 MQTT-over-TLS and confirmed embedded library support |


## Source and configuration map

```text
CMakeLists.txt                              Firmware build definition
CMakePresets.json                           Debug and Release presets
STM32L4R5XX_FLASH.ld                        Direct-flash linker script
STM32L4R5XX_FLASH_RELOCATED.ld              Secure-boot relocated linker script
Core/                                       CubeMX HAL/FreeRTOS application source
Drivers/                                    CubeMX HAL/CMSIS drivers
Middlewares/Third_Party/FreeRTOS/           CubeMX-generated FreeRTOS middleware
configs/boards/board_a.yaml                 Board metadata
configs/hosts/gateway.yaml                  Gateway, flash helper, UART path
configs/boot/direct_flash.yaml              Direct-flash boot profile
configs/targets/stm32l4r5_wolfboot.yaml   Shared wolfBoot target, layout, build, signing, and experiment defaults
configs/algorithms/*.yaml                    Canonical per-algorithm wolfBoot and signing differences
configs/experiments/baseline_direct_uart.yaml
configs/experiments/secure_boot_uart.yaml   Generic secure-boot experiment entry point
configs/benchmarks/classical_signing_profiles.yaml
configs/wolfboot/stm32l4r5_*.config         Project-local wolfBoot config templates
experiment/mqtt-broker/                      Gateway MQTT broker compose project
docker/python/Dockerfile                    Non-hardware Python, STM32, wolfBoot, and signing container baseline
.dockerignore                               Container build-context exclusions for generated output and secrets
.github/workflows/ci.yml                    CI workflow with runner-compatible, MQTT broker Docker runtime, and containerised non-hardware jobs
requirements-dev.txt                        Python development dependencies for unit-test validation
```

### Composed secure-boot profiles

The benchmark model is also consolidated. `configs/benchmarks/classical_signing_profiles.yaml` is a benchmark-suite declaration containing algorithm IDs and shared evidence rules only. Algorithm properties, wolfBoot values, and signing paths are resolved directly from `configs/algorithms/`; they are not repeated in the benchmark suite.


Secure-boot configuration uses two canonical sources. `configs/targets/stm32l4r5_wolfboot.yaml` owns values common to the STM32L4R5 wolfBoot target, including layout, common build inputs, signing defaults, and shared experiment behaviour. `configs/algorithms/<algorithm>.yaml` owns each algorithm's wolfBoot identifier, key and signature properties, config template, signing arguments, tuple paths, and algorithm-specific evidence metadata.

Secure-boot commands select an algorithm ID and resolve the requested build, signing, experiment, or boot section directly from the canonical target and algorithm profiles. `configs/experiments/secure_boot_uart.yaml` is the single secure-boot experiment entry point. The former per-algorithm build, signing, boot, and experiment wrapper files have been removed. Direct-flash and MQTT experiment profiles remain standalone.

```

## Python implementation map

```text
scripts/experiment.py                       CLI entry point
scripts/framework/artifacts.py              Result artifact helpers
scripts/framework/benchmark_aggregation.py  Benchmark summary JSON/CSV generation
scripts/framework/build.py                  Local CMake build workflow
scripts/framework/build_number.py           Build number state handling
scripts/framework/build_records.py          First-class build record validation/use
scripts/framework/build_state.py            Last-successful-build state
scripts/framework/fingerprint.py            Secure-boot and signing evidence fingerprints
scripts/framework/flash.py                  Direct-flash SCP/SSH workflow
scripts/framework/manifest.py               Manifest construction and benchmark schema helpers
scripts/framework/secure_boot_flash.py      wolfBoot two-artifact flash and UART benchmark workflow
scripts/framework/signing.py                Application signing workflow
scripts/framework/source.py                 Git provenance helpers
scripts/framework/uart.py                   UART capture and marker parsing
scripts/framework/wolfboot_build.py         wolfBoot build/config/temporary patch workflow
```



## Docker-hosted build/test/experiment baseline

The repository default is Docker-hosted Linux execution through `scripts/dev.ps1` or `scripts/dev.sh`. The container definition is `docker/python/Dockerfile`; Python development dependencies are in `requirements-dev.txt`; generated outputs and local secret material are excluded from the build context by `.dockerignore`.

The image contains the STM32 build dependencies needed to configure and build the existing `Debug` and `Release` CMake presets, host build tooling needed for wolfBoot/keytools builds, OpenSSL for local certificate provisioning, an SSH client for runtime-provided gateway access, and the tooling needed to run application-signing profiles after the relocated application has been built. The image sets `PQC_CONTAINER=1`; pytest still also detects Docker through `/.dockerenv`.

The default execution model removes the development machine's native build environment from normal framework use. Framework commands, pytest, CMake builds, wolfBoot builds, signing, and gateway-mediated hardware experiments normally run inside the project container. Hardware access remains SSH/SCP-mediated through the gateway, so the container does not need direct ST-LINK/USB passthrough, UART devices, or Wi-Fi-module access. Host-native Windows or development-machine builds remain an explicit manual fallback only.

Software-build evidence from the container includes Python test results, safe configuration-validation command output, STM32 build output for direct and relocated firmware profiles, wolfBoot build evidence, and application-signing evidence. Gateway, flashing, UART, MQTT/TLS, timing, memory, benchmark, or end-to-end runtime success still requires explicit logs, manifests, or equivalent evidence from the relevant gateway or hardware workflow.

Application signing inside the container uses the runtime-mounted workspace. Private signing keys and generated signing material must remain local generated state, such as under `secrets/wolfboot/`, and must not be committed, sent in build contexts, copied into replacement artifacts, or baked into images. The container includes an SSH client but no SSH keys, VPN keys, broker credentials, private certificates, private signing keys, or other secrets. Gateway-capable checks require `PQC_CONTAINER_ENABLE_GATEWAY=1` plus runtime-provided SSH configuration, known-hosts data, and credentials; the wrapper commands set this flag only for gateway and hardware subcommands.

Generated-state preflight is the primary compatibility and provenance mechanism for framework build, wolfBoot build, application-signing, and artifact-consuming workflows. Pytest session-start cleanup is supplementary cross-platform hygiene for stale host-specific CMake and wolfBoot object/dependency/host-tool outputs. It does not establish compatibility or provenance and must not remove source files, canonical signing keys under `secrets/wolfboot/`, or reusable wolfBoot signing-tuple members.

## Firmware scheduler model

The application firmware uses the CubeMX-generated CMSIS-RTOS v2 FreeRTOS template. `main()` performs HAL initialization, clock configuration, GPIO/UART initialization, and one-time UART evidence marker output before `osKernelStart()`. It also emits FreeRTOS scheduler markers for default task creation and scheduler start. `StartDefaultTask()` emits a task-start marker before it owns the recurring `tick` marker and LED toggle using `osDelay(1000)`. HAL timing is generated from TIM1 rather than SysTick so the FreeRTOS scheduler can own SysTick.

The direct-flash and secure-boot application markers remain part of the UART evidence contract. FreeRTOS task-level stack APIs are enabled for future task instrumentation, but task-level runtime stack/heap values must still be treated as unavailable until explicit firmware markers and manifests record them.


## Default Docker execution model

The default development execution path is Docker-hosted Linux. Framework commands, pytest, CMake firmware builds, wolfBoot builds, application signing, and gateway-mediated hardware experiments should normally be launched through `scripts/dev.ps1` or `scripts/dev.sh`. Host-native Windows or development-machine builds remain available as an explicit manual fallback, but they are not the reproducible validation gate.

Gateway and hardware workflows are still mediated by SSH/SCP rather than direct USB or UART access from the container:

```text
development host with Docker
  -> project container mounted at /workspace
    -> SSH/SCP to pqc-gateway1 using runtime-mounted SSH material
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

The direct-flash baseline uses `configs/boot/direct_flash.yaml` and `configs/experiments/baseline_direct_uart.yaml`.

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

The UART marker begins with `lwIP runtime smoke:` and includes `network=unavailable`; it is intended to prove that a constrained set of lwIP helper functions executes during the existing 10-second UART capture window without crossing the network-interface boundary. The optional gateway integration test `tests/integration/test_lwip_runtime_smoke_uart.py` exercises the baseline build/flash/UART flow and asserts that the marker appears in `uart.log`; this remains helper-call UART evidence only, not ST67W61M1, Wi-Fi, IP, TCP, TLS, MQTT, or end-to-end network evidence.

Phase M10.1 begins hardware-backed ST67W61M1 validation without importing the CubeMX HTTP-server demo application. The default FreeRTOS task registers the minimal ST67 application callbacks, initializes the module through `W6X_Init()`, initializes the Wi-Fi subsystem through `W6X_WiFi_Init()`, and starts a bounded active scan through `W6X_WiFi_Scan()`. UART evidence uses `evidence=stm32-st67-wifi-rf-scan-only`, reports the callback status and access-point count, and deliberately omits SSID and BSSID values. The scan has an 8000 ms timeout and does not attempt association, register a real lwIP netif, start DHCP, open TCP, load certificates, perform a TLS handshake, or invoke MQTT. The ST67 SPI transfer-engine task stack is currently 2048 bytes after the prior 768-byte allocation faulted in the FreeRTOS queue receive path; the final minimum safe size remains unconfirmed because the current UART memory checkpoint measures only `defaultTask`.

The ST67/lwIP transmit boundary follows the X-CUBE-ST67W61 vendor adapter: each segment in a chained lwIP `pbuf` is submitted to `W6X_Netif_output()` in sequence. The framework does not consolidate the chain into a temporary contiguous allocation. The SPI transfer engine remains aligned with the vendor `spi_iface.c` implementation, apart from the CMSIS device include required for `__get_IPSR()` and the enlarged task stack required by observed runtime stack usage.


Current compile-only ST67W61M1 shield pin preparation maps the Arduino connector labels to the NUCLEO-L4R5ZI-P pins as follows: `D13/PA5 SPI1_SCK`, `D12/PA6 SPI1_MISO`, `D11/PA7 SPI1_MOSI`, `D10/PD14 SPI_CS`, `D5/PE11 CHIP_EN`, `D6/PE9 BOOT`, `D3/PE13 SPI_RDY`, and `D2/PF15 USER_BUTTON`. `SPI_RDY` and the relocated user button share `EXTI15_10_IRQn` but use different EXTI lines, 13 and 15 respectively. The generated 120 MHz clock configuration uses SPI1 prescaler 4, giving approximately 30 Mbit/s when SPI1 is fed from the 120 MHz APB2/PCLK2 domain. The earlier prescaler-32 configuration was a temporary diagnostic and is not the supported runtime baseline. The generated lwIP application/demo files are kept in the tree for inspection but filtered out of the Phase M5 compile-only CMake path; the project now compiles the CMSIS-RTOS v2 lwIP sys_arch port while runtime networking remains deferred.

Phase M6.2 adds `Core/Inc/pqc_network_interface.h` and `Core/Src/pqc_network_interface.c` as the project-owned boundary between later protocol layers and the future ST67W61M1-backed lwIP netif. The implementation owns an unattached local `struct netif`, clears its IPv4 address, netmask, and gateway with lwIP helpers, then reads `netif_is_up`, `netif_is_link_up`, the lwIP IPv4-any state, and an lwIP-formatted IPv4 string. It maps those observed lwIP values into `link`, `ip`, and `tcp` availability, while transport remains unavailable because no backend exists. The UART line begins with `lwIP network interface:` and is labelled `evidence=lwip-netif-state-only`; it reports both the raw lwIP observations and the mapped unavailable states. Wi-Fi module, ST67W61M1, TLS handshake, MQTT connect, MQTT publish, reconnect, and end-to-end status remain unavailable. It does not call `netif_add`, set link or interface state up, start DHCP, open TCP, invoke wolfSSL, invoke wolfMQTT, or access ST67W61M1 hardware. This boundary is intended for later wolfSSL transport and wolfMQTT work without coupling those layers directly to the Wi-Fi driver.

Phase M6.0 adds a STM32-local wolfSSL source build-only boundary through `Core/Inc/pqc_wolfssl_build_only.h`, `Core/Src/pqc_wolfssl_build_only.c`, `Core/Inc/user_settings.h`, and `Core/Inc/pqc_wolfssl_user_settings.h`. The CMake target `pqc_wolfssl_stm32_build_only` builds the minimal wolfCrypt SHA-256 source file from `tools/wolfboot/lib/wolfssl/wolfcrypt/src/sha256.c` and links it into the direct and relocated firmware builds. The M6.0 smoke helper computes SHA-256 over a fixed non-secret message and can emit `wolfSSL build-only smoke:` UART evidence with `source=enabled`, `sha256=ok`, `tls_handshake=unavailable`, `transport=unavailable`, `certs=not-loaded`, and `secrets=not-compiled-in`. This proves only that the configured wolfSSL/wolfCrypt source path built, linked, and executed.

Phase M6.1 extends that source integration with bounded wolfSSL initialization, TLS 1.2 client `WOLFSSL_CTX` creation/free, and wolfSSL cleanup. It does not create a `WOLFSSL` session, open TCP, load certificates or private keys, perform a TLS handshake, or perform MQTT work. Private keys and certificates must remain outside source files, documentation, and replacement archives. Disposable experiment material selected by the owning workflow is retained in ignored result artifacts; production and host control-plane credentials remain prohibited. The M6.0 evidence class remains STM32 build-only plus capability-gated source-smoke UART evidence, while M6.1 is separately labelled `tls-context-lifecycle-only`. TLS handshake, runtime transport, certificate-store, MQTT, Wi-Fi, ST67W61M1, and end-to-end network metrics remain unavailable until later phases provide explicit transport and runtime evidence.

The wolfSSL transport integration adds `Core/Inc/pqc_wolfssl_transport.h` and `Core/Src/pqc_wolfssl_transport.c` as a project-owned boundary between wolfSSL and the future lwIP/ST67W61M1 path. The boundary exposes unavailable connect, read, and write wrappers plus callback-shaped receive and send entry points. It reads the Phase M6.2 `PQC_NetworkInterfaceStatus` only to bind the layers architecturally; it does not register a live lwIP netif, create a socket, connect TCP, register callbacks on a `WOLFSSL` session, create a TLS session, load certificates, perform a TLS handshake, invoke MQTT, or access Wi-Fi hardware. All operations return explicit unavailable status and zero transferred bytes. Firmware emits `wolfSSL transport boundary:` with `evidence=unavailable-transport-only`, `socket_io=not-performed`, and unavailable connect/read/write/TLS/MQTT/Wi-Fi/ST67W61M1/end-to-end fields.


The validation model rejects mismatched backend/evidence combinations, fake/no-network configs that name a real broker endpoint, fake-transport settings on non-fake backends, host-side configs without a broker endpoint, unsupported metric names, empty unavailable reasons, invalid fake outcome values, and private-key references in certificate metadata. Certificate references are path references only and must not introduce private keys or credentials.

When MQTT/TLS schema fields are present, the initial result manifest includes an `mqtt_tls` block. The block records the evidence class, backend, TLS mode, broker metadata, metric records, metric summary, limitations, and evidence-boundary flags. Unavailable metrics are first-class records with a source and reason. Fake transport control-flow results are embedded only as simulated fake evidence. This schema does not claim Wi-Fi association, IP address, TCP connection, TLS handshake, MQTT connect, publish, reconnect, latency, throughput, STM32 runtime success, or ST67W61M1-backed success without explicit real evidence.

## Test architecture

```text
tests/unit/          No hardware, SSH, UART, gateway, or real device requirements
tests/integration/   Real local toolchain or gateway checks; skip when unavailable
tests/hardware/      End-to-end board/gateway/UART workflows; capability gated
```

FreeRTOS-specific regression tests are split by evidence source. Unit tests inspect generated CMake, `FreeRTOSConfig.h`, the CubeMX `.ioc`, and application marker ordering. Integration tests build both `Debug` and `Release` presets with the generated FreeRTOS middleware. Hardware tests should continue to assert UART evidence from the direct-flash and secure-boot workflows; FreeRTOS runtime success must come from explicit UART markers such as scheduler-start, task-start, and recurring `tick` output.

The secure-boot algorithm benchmark hardware test is intentionally profile-selective to keep routine runs short. ML-DSA-65 is the default always-on profile. Other algorithm profiles are collected but skipped unless named with `PQC_HARDWARE_SECURE_BOOT_PROFILES`, or unless the full matrix is enabled with `PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES=1`. Capability gates decide whether selected gateway and hardware tests run or skip; command-line `--pqc-require-*` switches are strictness controls, not the normal way to make tests runnable.

Run all tests that can run without gateway access through the default Docker path:

```powershell
.\scripts\dev.ps1 pytest
```

Run strict hardware benchmark workflow through Docker and the SSH gateway only when hardware is intentionally available:

```powershell
.\scripts\dev.ps1 pytest-hardware tests/hardware/test_secure_boot_algorithm_benchmarks.py -m hardware --pqc-require-hardware
```

GitHub Actions CI is defined in `.github/workflows/ci.yml`. It runs on every pushed commit, pull request, and manual dispatch. The workflow preserves the existing runner-compatible jobs and MQTT broker Docker runtime validation, and adds a separate `container-non-hardware` job for the project-owned container workflow.

The containerised job is the default reproducible software-build validation path. The runner-compatible jobs remain as compatibility coverage: they run unit tests, build both CMake firmware presets on the Ubuntu GitHub-hosted runner, run the real wolfBoot build integration test when local tooling and the wolfBoot submodule are available, and then run integration tests with the local-build capability required. The integration job also runs MQTT broker Docker Compose config rendering tests with `docker compose config`, which validate the classical and OQS compose model without deploying to the gateway or running experiment orchestration. The MQTT broker Docker runtime job starts the local classical Mosquitto container, uses temporary test certificates, validates TLS 1.3 mutual authentication, and verifies MQTT publish/subscribe using client certificates.

The default containerised non-hardware job builds the project container image from `docker/python/Dockerfile` and runs the non-hardware checks inside that image: Python unit tests, the safe framework status command, `Debug` and `Release` CMake configure/build, one wolfBoot build profile, relocated ECDSA P-256 application signing, and targeted local-build integration tests for `test_local_build.py` and `test_wolfboot_build_integration.py`. It requires no GitHub Actions secrets; signing material generated during CI is runtime workspace state only and remains covered by the generated-output and secret exclusions.

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

This broker path is broker-side and host-side validation infrastructure. The broker workflow labels broker validation manifests and command output as `host-side/broker-side MQTT/TLS compatibility evidence`, with `host_side` evidence class and explicit false claims for STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, and end-to-end wireless success. It is not STM32 MQTT/TLS client evidence unless a later STM32 firmware phase records explicit board and broker evidence together. The classical profile uses Eclipse Mosquitto with TLS 1.3, client-certificate authentication, and an ACL file. The runner-compatible Docker runtime test exercises this classical container locally from a pytest temporary copy of the compose project, so generated certificates, data, and logs are not written to the repository tree. The experimental OQS profile uses the Open Quantum Safe Mosquitto image for post-quantum TLS protocol evaluation. Each profile overrides the image entrypoint, copies its bind-mounted ACL file to a container-local `/tmp/mosquitto-aclfile`, sets ownership and restrictive permissions for the runtime user there, and configures Mosquitto to read that copy. The top-level `mqtt-broker-experiment` command wraps certificate provisioning, deployment, profile start, validation, broker validation retries during startup, live step progress, bounded per-step subprocess timeouts, log capture even after validation failures, result manifest creation, and optional stop. OQS runtime behaviour must be confirmed with explicit broker/client logs before claiming PQC TLS success.

MQTT broker OQS image compatibility: The startup script creates a runtime-user-owned `/tmp/mosquitto-aclfile` when possible. Images with a `mosquitto` user use `mosquitto`; the current OQS Mosquitto image uses `nobody`, so the OQS config sets `user nobody` and the ACL copy is owned by that runtime user.




## Build and generated-state architecture

Framework commands that create or consume generated firmware, wolfBoot, and signed-image artifacts use `scripts/framework/generated_state.py`. The module stores project-owned scope manifests under `.pqc-generated-state/scopes/` and binds generated state to the workflow, profile, source/config fingerprint, toolchain command identity, host/container identity, and applicable signing-key tuple.

Before a build or signing command starts, the preflight compares the current identity with the last successful scope record. Demonstrably compatible state may be retained. Missing, malformed, cross-profile, cross-toolchain, or cross-host/container state causes deterministic cleanup of only the configured generated paths and stale final artifacts. Cleanup refuses paths outside the repository and refuses all paths under `secrets/`. CubeMX-generated source folders are not moved or deleted.

STM32 CMake builds use profile-scoped `build/<preset>/` directories. wolfBoot retains its upstream source layout, so the framework records a project-owned scope manifest and cleans only known host-tool outputs and final build artifacts. The wolfBoot-local private key, generated public key, and generated `src/keystore.c` are treated as one tuple; an incomplete or mismatched tuple is not silently repaired from an existing private key. Canonical keys under `secrets/wolfboot/` are never preflight cleanup targets.

Successful commands write artifact hashes and references to their build or signing records. The canonical normal signing path first creates the relocated ELF through the framework `experiment build` command with `Release`, so application signing can require that ELF to match a successful CMake generated-state record. Direct wrapped CMake remains a diagnostic fallback only and does not create the framework provenance required by downstream signing. Secure-boot flashing requires the wolfBoot ELF and original signed application to match successful wolfBoot-build and application-signing records; filesystem existence alone is insufficient. A failed command does not write a success record, and stale final artifacts are removed before execution so they cannot be mistaken for new output.



### Secure-boot profile selection and signing-tuple preservation

The secure-boot algorithm benchmark hardware test now implements the documented profile-selection environment variables. ML-DSA-65 is selected by default. `PQC_HARDWARE_SECURE_BOOT_PROFILES` adds named profiles to that default, and `PQC_HARDWARE_ALL_SECURE_BOOT_PROFILES=1` selects the complete matrix. Unselected parameter cases are collected but skipped with an explicit reason.

Hardware-test preparation must not call wolfBoot `keysclean` and pytest startup cleanup must not remove `wolfboot_signing_private_key.der`, `wolfboot_signing_public_key.der`, or `src/keystore.c`. Those files form reusable local signing state with the canonical key and are validated by the framework preflight. The hardware test removes only its directly managed relocated CMake output; wolfBoot stale-output handling remains owned by `build-wolfboot` generated-state preflight.



### Application handoff ordering and runtime memory checkpoints

After wolfBoot verifies the signed image and transfers control, the application initializes only the hardware required to expose UART evidence. The first application UART output is the preserved wolfBoot mailbox block: raw verification cycles, bootloader SYSCLK/HCLK/PCLK values, verification result, and wolfBoot stack evidence. The secure-boot application marker and other application initialization markers follow that mailbox evidence. This output ordering does not imply that application code ran before verification; the mailbox is populated by wolfBoot and printed only after verified handoff.

Application clock evidence is emitted from the running FreeRTOS default task after the scheduler starts. It records HAL-reported SYSCLK, HCLK, PCLK1, and PCLK2 separately from the bootloader clock evidence. The application HCLK must not be used to derive wolfBoot verification time.

Application memory evidence uses bounded UART checkpoints rather than configuration values alone. The current checkpoints are `pre_scheduler`, `default_task_start`, and `default_task_runtime`. Each records FreeRTOS heap total, current free heap, minimum-ever free heap, derived current used heap, and derived peak used heap. Task-stage checkpoints additionally record the default task's configured stack bytes, stack high-water bytes, and derived used bytes. The pre-scheduler checkpoint reports task-stack fields as unavailable because no task is executing at that point.

FreeRTOS heap evidence covers only allocations managed by the configured FreeRTOS heap implementation. Default-task stack evidence covers only that task at the named checkpoint. wolfBoot verification stack evidence remains a separate metric and must not be merged with application task-stack evidence. Configured heap size, configured task stack size, linker sections, host timing, and UART duration are not runtime usage measurements by themselves.

### Secure-boot timing and clock evidence

Secure-boot verification timing uses the DWT cycle counter as the primary firmware-side evidence. The wolfBoot instrumentation mailbox records raw elapsed cycles, verification result, stack high-water evidence, and bootloader clock values derived from the active STM32 RCC register model: SYSCLK, HCLK, PCLK1, and PCLK2. Firmware does not convert cycles to milliseconds and does not report a hard-coded CPU frequency.

The framework may derive `derived_verification_time_ms` as `verification_cycles * 1000 / hclk_hz` only when both explicit UART values are present. The manifest records `derived_time_clock_source: hclk_hz` and keeps the raw cycles and reported clocks separate. This derived value is not RTC, wall-clock, host-duration, UART-latency, or independently calibrated timing evidence. Hardware assertions remain capability-gated and require explicit UART/manifest evidence.


### FreeRTOS task-context runtime smoke

The deterministic lwIP helper smoke and wolfSSL/wolfCrypt TLS-context lifecycle smoke now have two explicit execution contexts. `main()` emits the existing early evidence with `context=pre_scheduler scheduler=not_started`. After `osKernelStart()` transfers control and `defaultTask` emits its task-start marker, the task runs the same local checks once and emits `context=freertos_task scheduler=running`. Hardware evidence is valid only when the task-start marker precedes both task-context smoke markers in the captured UART log.

The task-context path remains local and serialized. It does not register or bring up a lwIP netif, use Wi-Fi or ST67W61M1 hardware, report link-up or IP assignment, open TCP, load certificates, create a TLS session, perform a TLS handshake, connect or publish MQTT, reconnect, or claim end-to-end network success. wolfSSL FreeRTOS mutex or multithreaded support is not enabled because no concurrent wolfSSL use is introduced. The capability-gated secure-boot benchmark hardware test verifies marker ordering using a known built and flashed image; the ad hoc baseline monitor remains intentionally unable to assert one-shot task startup markers because it does not flash a known image.


## STM32-local lwIP UDP loopback

The baseline hardware test includes a capability-gated known-image build/flash/UART path for this marker. The ordinary monitor-only test remains non-assertive because it cannot establish which firmware image is already running. The M6.6 implementation does not add manifest fields: the current baseline `run` manifest records UART pass/fail evidence, while the detailed local-loopback evidence remains in `uart.log`. A future structured UART-evidence ingestion phase may promote these fields into the manifest without changing their local-only meaning.


## STM32 wolfMQTT build boundary

The wolfMQTT build boundary adds wolfMQTT as the dedicated `Middlewares/Third_Party/wolfMQTT` Git submodule and builds its core client, packet, and socket-callback sources into both STM32 firmware profiles. `Core/Inc/pqc_wolfmqtt_build_only.h` and `Core/Src/pqc_wolfmqtt_build_only.c` provide the project-owned integration boundary. The boundary uses wolfMQTT's native `MqttNet` callbacks and exposes backend selection independently from MQTT client initialization. The current selectable implementation is `fake_no_network`; the `st67w61m1` value is reserved and rejected until its later hardware-backed phase.

The build-only initializer constructs an unavailable `MqttNet`, calls `MqttClient_Init`, and deinitializes the client. It does not call network connect, MQTT CONNECT, publish, subscribe, wait-message, TLS, socket, lwIP external transport, or Wi-Fi APIs. No UART marker is emitted and no runtime success is claimed by the build-only boundary. Broker connection, TLS handshake, publish, reconnect, Wi-Fi, ST67W61M1, and end-to-end states remain unavailable.

### STM32 fake/no-network wolfMQTT runtime evidence

The fake/no-network runtime path reuses the build integration boundary rather than adding a second MQTT client path. A serialized one-shot call runs from `defaultTask` after the scheduler starts, selects `fake_no_network`, constructs the unavailable `MqttNet`, calls `MqttClient_Init`, and deinitializes the client without invoking network connect, MQTT CONNECT, publish, subscribe, wait-message, TLS, socket, lwIP external transport, or Wi-Fi APIs.

The UART marker begins with `wolfMQTT runtime smoke:` and is labelled `evidence=stm32-fake-no-network-initialization-only`. It records the FreeRTOS task context, backend, initializer result, client-initialized state, and callback presence. Transport, Wi-Fi, link, IP, TCP, TLS handshake, MQTT connect, MQTT publish, reconnect, ST67W61M1, and end-to-end status remain explicitly unavailable. This is initialization evidence from the STM32 board only; it is not broker or network evidence.

Static unit coverage validates invocation, marker wording, backend selection, unavailable claims, and the continued absence of protocol/network calls. Existing local-build integration coverage compiles both `Debug` and `Release`. The capability-gated known-image hardware test builds, flashes, captures UART, and verifies that the Phase M8 marker occurs after `defaultTask` starts. Detailed evidence remains in `uart.log`; no new manifest field is introduced. Verify with `./scripts/dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware`.

## Host wolfMQTT/wolfSSL compatibility boundary

`experiment/mqtt-broker/host-wolfmqtt/CMakeLists.txt` defines a separate native-host build. It compiles the pinned wolfMQTT core and upstream MQTT client/network example sources and links them to the wolfSSL source carried by the wolfBoot submodule. This target is intentionally separate from the Arm/STM32 CMake presets and from `pqc_wolfmqtt_stm32_build_only`.

`experiment/mqtt-broker/scripts/host_wolfmqtt_validate.py` configures and builds the native executable and can pass arguments through to the upstream wolfMQTT client. Before invoking the client it emits an explicit `host_side` evidence label and false claims for STM32, Wi-Fi-module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, and end-to-end wireless success. Optional JSON output preserves the same boundary. The utility may target the local or gateway-hosted classical broker, but gateway and broker availability remain capability requirements rather than assumptions.

The canonical broker definition is `experiment/mqtt-broker/compose.yaml`. Phase M4 Mosquitto/OpenSSL checks and Native wolfMQTT/wolfSSL checks are complementary host-side paths. Neither is firmware evidence.



### PowerShell client-argument boundary

The host validation wrapper accepts upstream wolfMQTT arguments after `--client-args`. This named boundary is the documented command contract because `scripts/dev.ps1` is an advanced PowerShell script. Each dash-prefixed wolfMQTT argument must be quoted individually when invoked through PowerShell so it is forwarded as data rather than bound as a `dev.ps1` parameter. Active PowerShell guidance does not use a standalone `--` forwarding path.


### Structured host runtime evidence

The host validation utility captures the wolfMQTT client output and records individual TLS/MQTT success markers in the JSON result. `broker_compatibility_confirmed` is true only when the process exits successfully and explicit markers confirm TLS socket connection, MQTT connection acknowledgement, subscription, successful publish, message receipt, MQTT disconnect, and socket disconnect. A zero process exit code alone is insufficient.
## Consolidated deferred-test register

This is the canonical register required by the deferred-test rules in `AI_BUILD_GUIDE.md`. Related implementation requests must inspect these entries and either implement the listed coverage, update the entry with current evidence, or document why it is no longer applicable. Completed gateway/UART coverage and completed lwIP-loopback/fake-no-network known-image hardware assertions are intentionally not listed.

| ID | Feature | Missing test layer | Reason | Required capability or phase | Intended test file | Eventual verification command | Status |
|---|---|---|---|---|---|---|---|
| DTR-001 | M6.1 wolfSSL TLS-context lifecycle marker | Dedicated gateway-mediated known-image UART/hardware assertion | Existing hardware evidence checks task-context ordering in the secure-boot benchmark path, but there is no focused baseline test that builds/flashes the image and asserts the complete M6.1 lifecycle and unavailable-field contract | Gateway, flash helper, UART device, and known-image baseline run capability | `tests/hardware/test_baseline_uart.py` | `./scripts/dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware` | deferred |
| DTR-002 | M6.2 lwIP network-interface boundary marker | Dedicated gateway-mediated known-image UART/hardware assertion | Static/build coverage exists, but the known-image baseline hardware test does not yet assert the complete `lwIP network interface:` marker contract | Gateway, flash helper, UART device, and known-image baseline run capability | `tests/hardware/test_baseline_uart.py` | `./scripts/dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware` | deferred |
| DTR-003 | M6.2.1 generated-state provenance refusal before gateway access | Hardware-workflow fixture coverage | Framework and integration coverage exists, but secure-boot hardware fixtures still need explicit successful build/signing records to assert provenance refusal before any gateway operation | Updated build/signing record fixtures in the secure-boot hardware workflow | `tests/hardware/test_secure_boot_flash_workflow.py` | `./scripts/dev.ps1 pytest-hardware tests/hardware/test_secure_boot_flash_workflow.py -m hardware --pqc-require-hardware` | deferred |
| DTR-004 | M6.3 wolfSSL unavailable-transport marker | Dedicated gateway-mediated known-image UART/hardware assertion | Static/build coverage exists, but the known-image baseline hardware test does not yet assert callbacks, zero-transfer behavior, no socket I/O, and all unavailable fields | Gateway, flash helper, UART device, and known-image baseline run capability | `tests/hardware/test_baseline_uart.py` | `./scripts/dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware` | deferred |
| DTR-005 | M9 live host wolfMQTT/wolfSSL validation against the gateway broker | Gateway integration and live broker compatibility | Native host build coverage exists; deterministic live validation requires reachable gateway infrastructure and provisioned temporary broker certificates | Gateway connectivity, broker deployment, temporary certificate provisioning, and host client execution | `tests/integration/test_mqtt_broker_gateway_e2e.py` | `./scripts/dev.ps1 pytest-gateway tests/integration/test_mqtt_broker_gateway_e2e.py -m integration --pqc-require-gateway`, then the documented `host_wolfmqtt_validate.py run` command | deferred |
| DTR-006 | M10 ST67W61M1 association and DHCP | Hardware coverage | Implemented by the baseline known-image UART hardware test, which requires explicit association and DHCP success markers plus a non-zero IPv4 address | Installed ST67W61M1 hardware, configured access point, gateway/UART access, and experiment-supplied credentials | `tests/hardware/test_baseline_uart.py` | `./scripts/dev.ps1 pytest-hardware tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware` | retired: coverage implemented; external TCP/TLS/MQTT remains separately deferred |
| DTR-007 | M11 classical STM32 MQTT-over-TLS | End-to-end firmware-runtime, network, broker, gateway, UART, and hardware coverage | The STM32 reaches the broker over TCP, resolves the configured FQDN, loads the CA, and receives the initial TLS 1.2 server records. The READY-level race was remediated and hardware evidence then isolated a later failure: a 94-byte first-part full-duplex SPI transfer entered DMA but did not produce the completion event, while the larger receive-only DMA path had already completed successfully. A bounded transport change routes short full-duplex control transactions through the synchronous polling path. Follow-up hardware evidence then isolated the same missing-completion behavior in the moderate receive-only second transaction. Receive-only remainders up to 2048 bytes are now polled in port-safe chunks, while larger receive-only and full-duplex payloads remain on DMA. Follow-up hardware evidence then reached certificate validation and showed the firmware checking `pqc-gateway1.pqcnet` against a generated server certificate whose SAN contained only `pqc-gateway1`, `localhost`, and IP addresses. Classical certificate provisioning now defaults to the experiment-selected FQDN and retains the short gateway alias. The runtime certificate bundle must be regenerated before complete TLS and MQTT hardware verification. | Completed M10 backend, level-aware ST67 READY handling, bounded short full-duplex polling path, real wolfSSL transport/session, classical certificates supplied outside the repository, broker access, and wolfMQTT connect/publish/reconnect implementation | `tests/hardware/test_stm32_mqtt_tls.py` | `./scripts/dev.ps1 pytest-hardware tests/hardware/test_stm32_mqtt_tls.py -m hardware --pqc-require-hardware` | in progress: SPI completion fixes and broker FQDN SAN provisioning implemented; certificate regeneration and end-to-end hardware verification pending |
| DTR-008 | M12 controlled network degradation | Gateway/network integration and end-to-end hardware coverage | A stable real M11 path and safe impairment apply/verify/cleanup controls do not yet exist | Completed M11 path and gateway network-impairment capability with guaranteed cleanup | `tests/integration/test_mqtt_network_degradation.py` | `./scripts/dev.ps1 pytest-gateway tests/integration/test_mqtt_network_degradation.py -m integration --pqc-require-gateway` | blocked by M11/M12 implementation |
| DTR-009 | M13 PQC/hybrid STM32 MQTT/TLS | End-to-end firmware-runtime, broker, network, gateway, UART, and hardware coverage | Target-library algorithm support and a stable classical STM32 MQTT/TLS baseline have not yet been established | Completed M11 baseline, confirmed wolfSSL/wolfMQTT target support, compatible broker profile, and Phase M13 implementation | `tests/hardware/test_stm32_pqc_hybrid_mqtt_tls.py` | `./scripts/dev.ps1 pytest-hardware tests/hardware/test_stm32_pqc_hybrid_mqtt_tls.py -m hardware --pqc-require-hardware` | blocked by M11/M13 implementation |

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

The baseline experiment supplies SSID and PSK through `configs/experiments/baseline_direct_uart.yaml`. The build workflow generates `build/pqc_generated/pqc_wifi_config.h`; UART and manifests redact the PSK. Firmware joins the configured AP and obtains IPv4 configuration through DHCP. Explicit UART markers record association and IPv4, gateway, and netmask values. Run manifests record parsed evidence under `network`. Hardware success requires both association and DHCP pass markers from the latest boot and a non-zero IPv4 address.


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
`tests/hardware/test_lwip_runtime_smoke_uart.py` validates module
initialization, scan completion before association, link-up, DHCP, live IPv4 evidence,
heartbeat continuity, and absence of contradictory unavailable markers after
the live-state marker.

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

The first M11 profile is `server-ecdsa-p256`: ST67W61M1 supplies the network interface, while lwIP sockets, wolfSSL TLS 1.2, certificate verification, wolfMQTT CONNECT/publish, and one bounded reconnect run on the STM32. The firmware build embeds only the generated public broker CA certificate. The existing `classical` mutual-TLS broker profile remains separate and is not claimed as STM32-validated until client-certificate provisioning is implemented and evidenced.

The configured public CA certificate is embedded into generated firmware configuration and therefore affects the resulting ELF SHA-256. Private CA keys and other private certificate material remain excluded from manifests and result artifacts.

M11 success requires explicit UART markers for DHCP, TCP, TLS handshake, MQTT connect/publish, reconnect TLS handshake, and post-reconnect publish, together with retained broker evidence. Missing resource metrics remain unavailable rather than inferred. DTR-007 is in progress until a capability-gated hardware run supplies that evidence.

### MQTT reconnect evidence

For the classical server-authenticated STM32 MQTT-over-TLS experiment, reconnect evidence requires a second complete command/response exchange. The gateway subscriber therefore remains active for the initial and reconnect responses, and command publication continues until both exact correlation responses are observed or the bounded orchestration timeout expires. The recorded evidence includes expected and observed response counts. Firmware status distinguishes an unattempted reconnect (`not_run`) from an attempted reconnect that fails (`failed`). A successful reconnect claim requires the second TLS handshake, MQTT connection/subscription, command receive, and response publish to complete.


### MQTT UART completion and logging

Routine MQTT experiment UART output is intentionally concise. Per-call TLS I/O records and individual Wi-Fi scan entries are disabled by default and may be re-enabled at compile time with `PQC_WOLFMQTT_TLS_IO_TRACE=1` and `PQC_WIFI_SCAN_VERBOSE=1`. The firmware emits `PQC_EXPERIMENT_COMPLETE experiment=mqtt_tls_server_auth status=done` after the final clock, heap, and task-stack evidence. The gateway stops capture after this marker plus the configured grace period (default three seconds), while retaining the configured UART duration as a hard limit. After completion, the scheduler continues running but the one-second UART tick stream is suppressed.

### Hybrid PQC MQTT/TLS profile

The framework includes an explicit STM32/ST67W61M1 MQTT-over-TLS 1.3 profile using `SecP256r1MLKEM768` with conventional server certificate authentication and no mutual TLS. Evidence is valid only when retained UART output records `tls_handshake=passed`, `pqc_group=passed`, the MQTT transaction stages, reconnect outcome, and `end_to_end=passed`. Classical fallback is not accepted as PQC evidence. Hardware success remains unverified until a recorded gateway experiment supplies those markers and matching broker logs.


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

Encrypted MQTT experiments use TLS 1.3 only. `framework/certs` owns one classical step-ca root/intermediate hierarchy and issues classical MQTT broker and client X.509 identities. The classical and P-256+ML-KEM-768 experiment profiles consume the same root trust anchor and broker identity model; the PQC distinction is limited to the TLS 1.3 key-exchange group. Experiment prerequisite handling synchronizes authoritative material on every run, records certificate hashes, embeds the root CA public certificate into firmware, and does not reconstruct missing CA tuples.


### MQTT authentication-mode separation

The gateway broker exposes three explicit TLS 1.3 profiles. `classical-server-auth` and `oqs` authenticate only the broker using the classical step-ca hierarchy; the OQS profile differs only by requiring `SecP256r1MLKEM768` hybrid key exchange. `classical` is a separate mutual-TLS profile and validates client certificates against the staged step-ca CA chain. Host-side validation commands must match the profile: server-auth validators omit client credentials, while the classical mutual-TLS validator supplies the staged client certificate and key.

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

The experiment CLI emits concise timestamped operational progress for profile resolution, cryptographic selection, prerequisites, configuration, build execution, gateway use, flashing, UART capture, managed broker lifecycle, MQTT command/response validation, cleanup, and final result recording. The progress timezone defaults to `Australia/Melbourne` and may be overridden with the `PQC_PROGRESS_TIMEZONE` environment variable using an IANA timezone identifier. The timestamp includes its timezone abbreviation.

CMake configuration and build execution are separate progress stages. The framework always invokes both commands; Ninja decides whether individual object files require recompilation.

Console progress is not an additional evidence class and must not be interpreted as proof of success. The result manifest and retained stage logs remain authoritative. Progress messages must not disclose private keys, passwords, wireless PSKs, or sensitive command arguments.


### Application build execution and artifact identity

Framework-level application build reuse and source/dependency fingerprinting are disabled. Each application build invokes CMake configuration and `cmake --build`; the retained Ninja build tree provides native incremental recompilation. Successful builds receive a new normal build number and an identity derived from the final ELF SHA-256. Run manifests and immutable build records store `reuse_enabled: false`, `incremental_build_system: cmake-ninja`, `artifact_identity_algorithm: sha256-elf`, and the ELF digest. Flash verification compares the selected ELF against the referenced immutable record digest and does not re-evaluate repository source state.


### Integrated MQTT secure-boot execution

The `run` command supports `--boot-mode wolfboot --boot-algorithm <id>` for
end-to-end MQTT experiments. The experiment YAML remains authoritative for
MQTT/TLS cryptography, broker orchestration, and expected protocol evidence.
The boot algorithm is resolved independently from `configs/algorithms/` and the
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

All firmware builds use the fixed wolfBoot-relocated layout. Release is the default build mode and `--debug` selects the Debug compiler configuration without changing the flash addresses. The primary slot begins at `0x08020000`; its 12 KiB manifest reserve ends at `0x08022FFF`; the application vector table begins at `0x08023000`. The default wolfBoot mode is `integrity_sha256`, which verifies the image SHA-256 digest but performs no signature or signing-key authentication. It therefore does not require or resolve a signing tuple. ML-DSA-44, ML-DSA-65, and ML-DSA-87 remain explicit non-default signing evaluation profiles.
