# Framework architecture

This reference describes the implemented system and its component boundaries.
Implementation support is not evidence that a particular experiment succeeded.
Use the [documentation index](README.md) to choose a topic; read this document
when changing a boundary that crosses components.

Detailed owners:

- [Configuration and campaign execution](011_experiment_configuration.md)
- [Result contracts and offline analysis](012_results_and_analysis.md)
- [Test architecture and deferred coverage](013_testing_and_deferred_coverage.md)
- [Build, flash and operation](005_remote_flash_workflow.md)
- [Open-data and signing-state policy](006_security_and_secrets.md)

## System boundaries

```text
Linux development host
  ├─ terminal queue / collection coordinator
  └─ scripts/dev.sh → pinned Docker development environment
       ├─ canonical profiles → resolver → generated campaign cases
       ├─ CMake/Ninja + wolfBoot/keytools → recorded firmware artifacts
       └─ campaign executor → per-run experiment runner
            └─ SSH/SCP + gateway lease
                 ├─ flash/reset/UART helpers → STM32L4R5 + ST67W61M1
                 ├─ experiment broker ← workload traffic / scoped impairment
                 ├─ reporting broker ← deferred STM32 and ESP32 records
                 └─ packet capture / broker logs → immutable run capture

retained captures → selected archives → shared analysis notebook/CLI → tables and figures
```

The NUCLEO-L4R5ZI-P hosts the application, cryptography and protocol clients.
ST67W61M1 supplies the Wi-Fi interface. The gateway owns physical board access,
brokers and packet acquisition. The optional ESP32/INA228 is a passive energy
instrument. The development container reaches hardware through the gateway;
it does not need USB or UART device passthrough.

## Current capability matrix

Rows describe implemented paths, not a blanket laboratory acceptance result.
Specific missing validation remains in the [deferred-test register](013_testing_and_deferred_coverage.md#consolidated-deferred-test-register).

| Capability | Implemented path | Required evidence and limitation |
|---|---|---|
| Firmware and scheduler | CubeMX HAL, CMSIS-RTOS v2/FreeRTOS, Release/Debug application builds | Build logs prove compilation; known-image runtime records establish task execution |
| Build, signing and flash | Framework build records, wolfBoot preparation, application packaging and gateway flash | Artifact hashes and successful stage records; file existence alone is insufficient |
| Secure boot | Integrity-only SHA-256 and configured classical/ML-DSA signature profiles, including ML-DSA-87 | Integrity-only does not authenticate a signing key; runtime verification is profile-specific |
| Dual-bank OTA | Authenticated inactive-bank staging, activation, confirmation and rollback | Retained delivery, verification and physical-bank evidence; see [OTA workflow](009_dual_bank_ota_workflow.md) |
| STM32 networking | ST67 initialization/scan/association, lwIP IPv4 DHCP and sockets | Association/DHCP evidence alone does not establish TCP, TLS or MQTT success |
| STM32 MQTT | wolfMQTT validation and Ready Metrics workloads over plaintext or TLS | Device result stream plus independent broker/workload evidence; reconnect needs its own completed exchange |
| STM32 TLS 1.3 | wolfSSL session/transport, CA and peer-name checks, server/mutual authentication, classical/hybrid/standalone ML-KEM groups | Configured and negotiated groups must agree; no classical fallback may count as PQC success |
| Reporting | Separate plaintext broker, bounded deferred STM32 stream and capture integrity checks | Accepted capture establishes retained raw evidence, not validity of every scientific metric |
| Network impairment | Bidirectional experiment-broker veth shaping and MTU control | Requested, verified-applied and observed conditions remain distinct; reporting/control path is exempt |
| Energy | GPIO-delimited passive ESP32/INA228 capture, retained samples and offline integration | Valid sampling/coverage/alignment and an identified electrical boundary; no boot-energy inference from application intervals |
| Primitive benchmarks | Pre-scheduler wolfCrypt operations with raw DWT cycle records | Dedicated benchmark boundary; RTOS TLS attribution is not isolated primitive cost or PQM4 equivalence |
| Offline analysis | Timing, resource, TLS, packet/network, energy, secure-boot and bounded OTA/primitive importers | Selected-input integrity, metric validity and matched controls; analysis creates no new hardware evidence |
| Host/broker validation | Separate native host wolfMQTT/wolfSSL and Docker broker checks | Host-side or broker-side compatibility only |
| Local/fake helpers | lwIP helper smoke and retained fake/no-network initialization paths | Local execution or simulation only; legacy unavailable-boundary diagnostics do not describe the live TLS path |

Production release packaging, protected production device-key provisioning and
complete hardware qualification of every profile combination are outside this
implemented/verified boundary.

## Source ownership

| Area | Primary source/configuration owner |
|---|---|
| Firmware startup, tasks and workload fixture | `Core/Src/main.c`, `Core/Inc/pqc_mqtt_application.h`, `Core/Src/pqc_mqtt_application_*.c` |
| STM32 network and TLS/MQTT runtime | `Core/Src/pqc_wolfmqtt_build_only.c`, `Core/Src/pqc_network_interface.c`, `LWIP/`, `Middlewares/ST/` |
| Measurement and deferred records | `Core/Src/pqc_timebase.c`, `pqc_tls_instrumentation.c`, `pqc_result_buffer.c`, `pqc_energy_boundary.c`, `Core/Inc/pqc_boot_evidence.h` |
| Application build/linker | `CMakeLists.txt`, `CMakePresets.json`, `cmake/`, `STM32L4R5XX_FLASH_RELOCATED.ld` |
| Resolution and orchestration | `scripts/framework/config_resolver.py`, `campaign_executor.py`, `scripts/experiment.py` |
| Build and security state | `scripts/framework/build.py`, `build_records.py`, `generated_state.py`, `wolfboot_build.py`, `signing.py` |
| Runtime acquisition | `scripts/framework/result_collector.py`, `run_evidence.py`, `network_degradation.py`, `packet_capture.py`, `energy_evidence.py` |
| Broker and instrument | `experiment/mqtt-broker/`, `instruments/esp32_ina228/` |
| Queue and collection | `scripts/run_queue.py`, `scripts/collect_thesis_evidence.py`, `scripts/framework/run_queue.py`, `thesis_collection.py` |
| Offline interpretation | `scripts/analyse_results.py`, `analysis_workspace.py`, `analysis_comparison.py`, `thesis_tables.py`, `analysis_presentation.py`; shared domain engines and `archive_table.py` |
| Collection chapter snapshots | `scripts/build_research_report.py`, `research_report.py`; internal notebook template under `scripts/framework/templates/` |

Some runtime files retain historical `build_only` names. Read the selected
backend and actual call path before treating a filename as a capability limit.
CubeMX-generated folders remain at the repository root; vendor source is not
project documentation.

### Dependencies

Application TLS/wolfCrypt uses the project-controlled
`Middlewares/Third_Party/wolfSSL` submodule, selected by
`PQC_WOLFSSL_SOURCE_DIR` in CMake. `Middlewares/Third_Party/wolfMQTT` is the
pinned public client dependency. `tools/wolfboot` is the project-controlled
bootloader fork; `tools/wolfboot/lib/wolfssl` is its separate nested dependency.
Application TLS fixes belong in the application submodule.

The parent Git gitlinks and `.gitmodules` define exact revisions and fetch
locations. When Git publication is explicitly authorized, publish a modified
submodule commit before advancing its parent gitlink. A parent commit cannot
preserve dirty or unreachable submodule changes. Container images, packages and
external Actions are pinned by their maintained definitions; the dependency-pin
checker and captured tool versions support reproducibility.

## Firmware execution

`main()` initializes HAL, clocks, TIM2 measurement time, peripherals and selected
allocators before starting the kernel. `defaultTask` handles the LED heartbeat;
`networkTask` invokes the selected workload through the common application
fixture. HAL uses TIM1, FreeRTOS uses SysTick, and research elapsed time uses TIM2
at an explicitly derived 1 MHz rate. See [baseline firmware](004_baseline_hal_app.md)
for startup and diagnostic details.

The dedicated `baremetal_benchmark` workload measures before
`osKernelInitialize()` and before network activity, then uses the normal reporting
path later. Its operation/interrupt/allocator contract belongs to the
[benchmark guide](baremetal_benchmark_measurement_core.md).

The normal network stack is:

```text
selected application → wolfMQTT → wolfSSL (TLS profiles only)
                     → lwIP IPv4 sockets → ST67 netif/SPI → Wi-Fi → broker
```

TLS, certificate verification and MQTT execute on STM32. IPv6, PPP and SLIP are
excluded by the maintained lwIP configuration/build. TLS capabilities are selected
from resolved profiles; plaintext builds exclude application wolfSSL/wolfCrypt.
KEX, certificate authentication and firmware signing are independent choices.
The supported workloads and profile domains are described in the
[configuration reference](011_experiment_configuration.md).

UART modes are `disabled`, `minimal` and `full`, and affect firmware identity.
Disabled excludes UART initialization/implementation; minimal suppresses output
inside measured workloads; full is diagnostic and may perturb measurements.
Normal networked capture completion uses reporting records. UART-focused baseline
and negative secure-boot tests have their own explicit diagnostic contracts.

## Build and generated state

Normal application builds use the fixed relocated application layout. Release is
the default; Debug changes compiler settings without changing flash addresses.
Legacy direct-flash helpers and local smoke paths remain compatibility mechanisms,
not a second default build layout.

A normal build invokes CMake configure and Ninja and creates a new immutable
`results/builds/<build_number>/` record. Ninja may reuse object files; the
framework does not search old application build records for automatic reuse.
The final ELF SHA-256 identifies the produced artifact. Campaigns can explicitly
reuse a validated preparation across runtime repetitions.

Generated-state preflight owns compatibility checks, stale generated-output
cleanup and downstream provenance. Scope records live under
`.pqc-generated-state/scopes/`. Cleanup is limited to workflow-owned generated
paths; canonical keys and source are excluded. Signing and flashing require
matching successful records and artifact hashes. Direct CMake is a diagnostic
fallback and does not create framework provenance. Pytest cleanup is supplementary
hygiene, not provenance validation.

Persistent signing tuples under `secrets/wolfboot/tuples/` contain the primary private key,
keystore and hash manifest, plus profile-selected public exports/standby keys. Complete matching tuples are reused; partial or
mismatched tuples fail. wolfBoot-local files are materializations of that state.
The [open-data policy](006_security_and_secrets.md) owns creation, preservation and
retention rules. Integrity-only packaging requires no signing tuple.

The Docker runtime drops to the invoking non-root UID/GID before workload
execution. Hardware tests use isolated build/generated-state volumes. Neither
container output ownership nor a software test establishes gateway/board success.

## Boot and update boundary

The signed application slot begins at logical `0x08020000`; the 12 KiB header
reserve puts the vector table at `0x08023000`. `single_bank` retains the software
primary/update/swap layout. `dual_bank_no_ota` and `dual_bank_ota` use symmetric
1 MiB hardware banks, each with 128 KiB for wolfBoot/metadata and an 896 KiB signed
application slot. Only the OTA mode includes the reporting-plane delivery path.
Target profiles and the [OTA guide](009_dual_bank_ota_workflow.md) own layout detail.

The maintained boot/application mailbox is version 8. It preserves separate
integrity, authenticity, selected-image verification, handoff and optional stack
observations in reserved RAM2. Selected-image validity binds partition, content
length and verified content digest to the handoff; earlier candidate/retry
measurements must not be attributed to a different selected image. Both images
must use a compatible mailbox layout.

An LPTIM2 bridge links operational wolfBoot-entry time to application TIM2.
Unavailable or wrapped bridge evidence disables reset-relative timing. DWT cycles
use recorded bootloader clocks, never an assumed application frequency. Content
digests differ from whole signed-package hashes. The device does not self-measure
its bootloader binary hash. Stack profiling and early-boot UART diagnostics have
explicit timing-exclusion policies in the [result reference](012_results_and_analysis.md).

## Experiment, reporting and acquisition planes

The experiment broker carries measured workload traffic. The reporting broker is
a separate plaintext service on port 1886 for control and deferred evidence.
The collector subscribes and establishes run identity before target execution.
Firmware buffers results in a bounded RAM3 store, then publishes sequenced chunks
and a completion record with counts and logical SHA-256 after measurement.
Repeated TLS workloads publish complete epochs between measured iterations.

The collector checks identity, order, completion and integrity. Firmware buffer
size/overflow and required-source failures remain explicit. Normal experiment
traffic capture excludes the reporting port. Gateway PCAP, broker observations
and UART are separate sources with separate clock domains.

Network impairment targets only the experiment broker's veth pair, with egress
and IFB ingress shaping. Both directions and MTUs are checked and restored;
reporting/control traffic remains outside that scope. Broker reuse and retained
conditions are campaign-owned, while each runtime attempt owns its capture.

The passive ESP32 samples before and during the STM32 GPIO window and publishes
a completed trace afterward. It has no run-ID command protocol; host acceptance
uses retained acquisition integrity and the explicit STM32 window. Physical
qualification and offline alignment belong to the
[instrument guide](010_esp32_ina228_energy_instrument.md).

## Evidence and validation boundary

A finalized `pqc-run-evidence` v3 manifest records execution/capture provenance.
`resolved-case.json` and `run-provenance.json` retain resolved configuration and
source/build/deployment identity. Scientific values remain in indexed raw records;
post-capture analysis has separate input/output hashes and cannot rewrite the
sealed capture. Execution outcome, capture acceptance, metric validity and
comparison eligibility are four separate decisions.

Build-only, STM32 local-only, fake/no-network, host-side, broker-side and
hardware-backed evidence cannot substitute for each other. Runtime timing,
memory, networking and cryptographic success need explicit records from their
own boundary. Missing measurements remain unavailable with a reason.

Tests follow unit, integration and hardware layers. Unit checks establish software
contracts; hardware tests prepare their own case and retain their own evidence.
A skip is not a pass. Use [testing and deferred coverage](013_testing_and_deferred_coverage.md)
for validation commands, capability gates and unresolved acceptance work.
