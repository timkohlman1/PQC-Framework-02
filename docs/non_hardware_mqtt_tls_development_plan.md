# Non-Hardware MQTT, lwIP, wolfSSL, and wolfMQTT Development Plan

## Purpose

This plan revises the MQTT/TLS roadmap so development can proceed before the X-NUCLEO-67W61M1 Wi-Fi module is installed or available.

The target architecture remains:

- lwIP runs on the STM32.
- wolfSSL runs on the STM32.
- wolfMQTT runs on the STM32.
- The Wi-Fi module is treated as a network interface, not as the TLS endpoint.
- MQTT/TLS runtime success is only claimed when explicit logs, manifests, UART output, broker logs, or equivalent evidence support it.

Each sub-phase is intentionally scoped as a small AI-driven change request.

## Scope Principles

- Separate hardware-independent work from ST67W61M1-dependent validation.
- Prefer buildable, testable increments.
- Do not fake runtime success.
- Record unavailable metrics explicitly.
- Keep hardware tests capability-gated.
- Keep broker-side, host-side, fake-transport, STM32 build-only, pre-scheduler STM32 smoke, FreeRTOS task-context STM32 smoke, and STM32 hardware evidence clearly separated.
- Distinguish pre-scheduler firmware smoke evidence from post-scheduler FreeRTOS task-context evidence.
- Do not report compile-time timing conversion constants as measured CPU-frequency evidence.
- Do not implement future PQC/hybrid TLS phases until classical MQTT/TLS architecture is stable.
- Do not move CubeMX-generated folders unless explicitly requested.
- Do not commit private keys, real credentials, `.env` files, private certificates, or production secrets.

---

## Phase M1 — MQTT/TLS Architecture Split Without Wi-Fi Hardware

### Goal

Update the MQTT/TLS roadmap and architecture documentation so MQTT/TLS development is explicitly split into hardware-independent and ST67W61M1-dependent phases.

### Outcomes

- MQTT/TLS client development can proceed before the Wi-Fi module is installed or available.
- lwIP, wolfSSL, and wolfMQTT are assigned to the STM32.
- The ST67W61M1 is treated as a future network-interface backend rather than the TLS endpoint or MQTT client owner.
- Fake/no-network transport, host/socket validation, STM32 build-only preparation, STM32 fake/no-network runtime, and future ST67W61M1-backed validation are distinct evidence boundaries.
- Build-only, fake transport, host-side, broker-side, STM32 runtime, and end-to-end wireless evidence remain separate.

### Expected Evidence

- Architecture and roadmap documentation that state the target ownership and evidence model.
- Documentation tests that preserve the canonical plan path and capability boundaries.
- No firmware, broker, gateway, network, or hardware execution is required for this phase.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M1 of the attached development plan - MQTT/TLS Architecture Split Without Wi-Fi Hardware. Update the roadmap and architecture documentation so hardware-independent MQTT/TLS preparation is separated from future ST67W61M1-backed validation. State that lwIP, wolfSSL, and wolfMQTT run on the STM32 and that the Wi-Fi module is a network-interface backend. Keep build-only, fake/no-network, host-side, broker-side, STM32 runtime, and end-to-end wireless evidence distinct. Do not change firmware, framework code, broker implementation, or tests outside documentation integrity coverage.
```

### Pass Criteria

- The roadmap no longer assumes Wi-Fi hardware is available before MQTT/TLS design work starts.
- STM32-local lwIP/wolfSSL/wolfMQTT ownership is explicit.
- Future implementation phases are small and evidence-bound.
- No MQTT, TLS, Wi-Fi, publish, latency, reconnect, or end-to-end success is claimed.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** The canonical architecture and this plan separate hardware-independent preparation from future ST67W61M1-backed networking and assign lwIP, wolfSSL, and wolfMQTT ownership to the STM32.
- **Verification:** Documentation integrity coverage and the capability/evidence model in `docs/007_framework_architecture.md`.
- **Remaining limitations:** This phase established architecture and evidence ownership only; it did not implement networking, TLS handshake, MQTT protocol operation, Wi-Fi, or end-to-end behavior.
- **Deferred tests:** None; this was a documentation and architecture phase.
- **Last reconciled:** 2026-07-12

---

## Phase M2 — MQTT Configuration and Result Schema

### Goal

Add framework-side configuration and result-schema support for future MQTT/TLS experiments before firmware transport implementation.

### Outcomes

- MQTT experiment configuration and invalid combinations are represented and validated.
- Transport backend and evidence-class selection are explicit.
- TLS mode, non-secret certificate references, and optional host-side broker metadata are represented where appropriate.
- Unavailable hardware and network metrics are first-class records with reasons.
- Fake/no-network, host-side, STM32 build-only, STM32 runtime, and future ST67W61M1-backed evidence remain distinguishable.

### Expected Evidence

- Configuration-validation tests for valid and invalid MQTT/TLS combinations.
- Manifest tests for the `mqtt_tls` result block and unavailable metric records.
- A representative fake/no-network experiment configuration.
- No STM32 networking, broker deployment, gateway, or hardware access is required.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M2 of the attached development plan - MQTT Configuration and Result Schema. Add framework-side MQTT/TLS configuration validation and result-manifest support before transport implementation. Represent evidence class, transport backend, TLS mode, non-secret certificate references, optional host broker metadata, and unavailable metrics with explicit reasons. Reject unsafe or contradictory combinations. Do not implement STM32 networking, lwIP transport, wolfSSL transport, wolfMQTT protocol behavior, broker deployment, or hardware tests in this phase.
```

### Pass Criteria

- MQTT/TLS configs validate.
- Invalid configs are rejected.
- Unavailable hardware/network metrics are represented explicitly.
- No network or hardware access is required.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** Experiment configuration and manifests support `fake_no_network`, `host_side`, `stm32_build_only`, `stm32_runtime`, and `st67w61m1_backed` evidence classes with explicit backend, TLS, broker, limitation, and unavailable-metric fields.
- **Verification:** `tests/unit/test_config_validation.py`, `tests/unit/test_manifest.py`, and the representative `configs/experiments/mqtt_tls_schema_fake.yaml` configuration.
- **Remaining limitations:** Schema support records evidence and limitations; it does not create network, TLS, MQTT, gateway, UART, or hardware evidence.
- **Deferred tests:** None; later runtime capabilities have their own phase-specific entries in the consolidated deferred-test register.
- **Last reconciled:** 2026-07-12

---

## Phase M3 — Fake/No-Network MQTT Transport Harness

### Goal

Provide deterministic non-network test coverage for MQTT client control-flow behaviour.

### Outcomes

- A fake/no-network transport mode models connect success, connect failure, read timeout, write timeout, disconnect, and reconnect attempts.
- Simulated evidence is labelled as fake/no-network transport evidence.
- Fake outcomes cannot be promoted to real MQTT/TLS, STM32 runtime, broker, Wi-Fi, or hardware success.
- Broker, gateway, Wi-Fi module, UART, and STM32 hardware are not required.

### Expected Evidence

- Deterministic unit tests for fake transport outcomes and reconnect control flow.
- Result evidence under the MQTT/TLS manifest boundary.
- Explicit false or unavailable fields for real network, TLS, broker, STM32 runtime, Wi-Fi, and hardware claims.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M3 of the attached development plan - Fake/No-Network MQTT Transport Harness. Add deterministic fake/no-network transport control-flow support for connect, publish, timeout, disconnect, and reconnect outcomes. Label all resulting evidence as simulated fake/no-network evidence and keep real network, broker, TLS, gateway, UART, STM32 runtime, Wi-Fi, and hardware success false or unavailable. Do not require network or hardware access.
```

### Pass Criteria

- Fake transport outcomes are deterministic and testable.
- Simulated evidence is not confused with real broker, TLS, or STM32 runtime evidence.
- No hardware or network dependency is introduced.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** `scripts/framework/mqtt_fake_transport.py` and the `mqtt-fake-transport` command provide deterministic simulated control-flow evidence only.
- **Verification:** `tests/unit/test_mqtt_fake_transport.py` and the fake/no-network experiment configuration and manifest assertions.
- **Remaining limitations:** No socket, broker, TLS handshake, STM32 runtime, Wi-Fi, gateway, UART, or hardware operation occurs.
- **Deferred tests:** None; real transport and hardware-backed behavior are outside this phase.
- **Last reconciled:** 2026-07-12

---

## Phase M4 — Host-Side Broker Compatibility Validation

### Goal

Validate MQTT/TLS broker compatibility separately from STM32 firmware and Wi-Fi hardware.

### Outcomes

- The project-owned broker scaffold provides classical and experimental OQS profiles.
- Host-side broker validation is capability-gated where Docker, gateway, or broker access is required.
- Broker and host evidence is labelled separately from STM32, Wi-Fi, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, and end-to-end wireless evidence.
- Temporary certificate material remains generated runtime state and is not committed.

### Expected Evidence

- Unit coverage for Compose profiles, certificate provisioning, deployment commands, and broker experiment manifests.
- Capability-gated local Docker and gateway integration coverage.
- Host-client and broker logs where live validation is intentionally run.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M4 of the attached development plan - Host-Side Broker Compatibility Validation. Add or validate the project-owned MQTT broker profiles and host-side MQTT/TLS checks. Keep local Docker and gateway-dependent checks capability-gated, generate temporary certificate material outside tracked source, and label all results as host-side or broker-side evidence only. Do not claim STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless success.
```

### Pass Criteria

- Broker validation remains capability-gated.
- Host/broker evidence is clearly separated from STM32 evidence.
- No Wi-Fi module is required.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** `experiment/mqtt-broker/compose.yaml` provides classical and experimental OQS broker profiles with local/gateway orchestration and host-side validation paths; all evidence remains broker-side or host-side.
- **Verification:** `tests/unit/test_mqtt_broker_compose.py`, `tests/unit/test_mqtt_broker_experiment_cli.py`, `tests/integration/test_mqtt_broker_docker_config.py`, `tests/integration/test_mqtt_broker_docker_runtime.py`, and capability-gated `tests/integration/test_mqtt_broker_gateway_e2e.py`.
- **Remaining limitations:** Broker and host success does not prove STM32, ST67W61M1, embedded lwIP/wolfSSL/wolfMQTT, or end-to-end wireless operation.
- **Deferred tests:** None for the broker scaffold; the distinct live native wolfMQTT/wolfSSL gateway check is tracked as DTR-005 under Phase M9.
- **Last reconciled:** 2026-07-12

---

## Phase M5 — STM32 lwIP Build-Only Skeleton

### Goal

Introduce or validate STM32-local lwIP build integration without requiring the Wi-Fi module.

### Outcomes

- Direct and relocated firmware builds include the intended lwIP and ST67W6X preparation sources.
- The project-owned build-only boundary keeps runtime networking explicitly unavailable.
- A constrained local helper smoke may exercise deterministic lwIP version, IPv4 formatting, and checksum functions without initializing a network interface.
- CubeMX-generated layout is preserved.
- Wi-Fi join, hardware-backed IP acquisition, TCP connection, TLS handshake, MQTT publish, and reconnect are not claimed.

### Expected Evidence

- Static/unit coverage for the lwIP build-only boundary and generated source integration.
- Direct and relocated firmware builds.
- Optional capability-gated UART evidence for the non-network helper smoke.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M5 of the attached development plan - STM32 lwIP Build-Only Skeleton. Add or validate STM32-local lwIP and ST67W6X compile/link preparation while keeping the network interface absent or explicitly unavailable. Preserve the CubeMX project layout. A deterministic local helper smoke may be added, but it must not initialize a netif, access Wi-Fi hardware, acquire an IP address, open TCP, perform TLS, or perform MQTT. Keep any UART test capability-gated and label it as local non-network evidence only.
```

### Pass Criteria

- Firmware builds with the intended lwIP preparation.
- Runtime networking remains explicitly unavailable.
- No Wi-Fi hardware is required.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** Direct and relocated STM32 builds compile/link lwIP, CMSIS-RTOS integration, and ST67W6X preparation sources; the local helper smoke exercises only deterministic non-network lwIP helpers and reports `network=unavailable`.
- **Verification:** `tests/unit/test_stm32_lwip_build_only_skeleton.py`, `tests/unit/test_stm32_lwip_st67_compile_only.py`, direct/relocated local-build integration, and capability-gated `tests/integration/test_lwip_runtime_smoke_uart.py`.
- **Remaining limitations:** No registered network interface, ST67W61M1 module access, Wi-Fi association, hardware IP, socket, external TCP, TLS, MQTT, or end-to-end networking is implemented by M5.
- **Deferred tests:** None for the M5 compile/link and helper boundary; later network-interface and hardware-backed obligations are tracked separately, including DTR-002 and DTR-006.
- **Last reconciled:** 2026-07-12

---

## Phase M6.0 — wolfSSL Build-Only Skeleton

### Goal

Add or validate wolfSSL build integration for STM32 without performing a real TLS handshake.

### Outcomes

- Direct and relocated firmware builds compile and link the selected wolfSSL/wolfCrypt source path.
- A project-owned build-only helper performs a fixed non-secret SHA-256 smoke operation.
- User settings and secret-handling boundaries are explicit.
- The M6.0 helper remains separate from the later M6.1 TLS-context lifecycle extension.
- TCP transport, certificate loading, TLS session creation, TLS handshake, MQTT, Wi-Fi, and ST67W61M1 behavior are not claimed.

### Expected Evidence

- Static/unit coverage for wolfSSL source selection, user settings, and marker wording.
- Direct and relocated firmware builds.
- Optional capability-gated UART evidence for the wolfSSL/wolfCrypt source smoke.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M6.0 of the attached development plan - wolfSSL Build-Only Skeleton. Add or validate the STM32 wolfSSL/wolfCrypt source build boundary and a fixed non-secret cryptographic smoke helper. Preserve user-settings and secret-handling rules. Do not create a TLS session, load certificates or private keys, open TCP, perform a TLS handshake, invoke MQTT, access Wi-Fi, or claim end-to-end networking. Keep any UART evidence capability-gated and label it as source build/local smoke evidence only.
```

### Pass Criteria

- Firmware builds with the wolfSSL integration boundary.
- TLS runtime success is not claimed.
- Secret-handling rules are preserved.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** Direct and relocated STM32 builds include the selected wolfSSL/wolfCrypt source path, and the M6.0 helper performs a fixed-message SHA-256 smoke with transport, certificates, TLS handshake, MQTT, Wi-Fi, and end-to-end states unavailable.
- **Verification:** `tests/unit/test_stm32_wolfssl_build_only_skeleton.py`, direct/relocated local-build integration, and capability-gated `tests/hardware/test_wolfssl_source_smoke_uart.py`.
- **Remaining limitations:** The M6.0 helper itself does not create a `WOLFSSL_CTX` or `WOLFSSL` session, load certificates, perform socket I/O or a TLS handshake, or invoke MQTT; M6.1 separately adds only the bounded TLS-context lifecycle.
- **Deferred tests:** None for the M6.0 source smoke; the focused M6.1 TLS-context lifecycle assertion is tracked as DTR-001.
- **Last reconciled:** 2026-07-12

---

## Phase M6.1 — wolfSSL TLS Context Build-Only Smoke

### Goal

Extend the Phase M6.0 wolfSSL source-build work from wolfCrypt-only smoke evidence to a minimal wolfSSL TLS context lifecycle smoke, without performing a TLS handshake.

### Outcomes

- Firmware can build and link the selected wolfSSL TLS source needed for a minimal client context lifecycle.
- The STM32 firmware can call wolfSSL initialization, create a client `WOLFSSL_CTX`, free it, and clean up wolfSSL state.
- TLS context creation is represented separately from TLS handshake success.
- Certificate loading, private key loading, TCP transport, MQTT, and ST67W61M1 backend integration remain unavailable.
- The UART/runtime marker, if hardware smoke evidence is included, states that context lifecycle passed while handshake, certificates, transport, and MQTT remain unavailable.

### Expected Evidence

- Direct and relocated firmware builds.
- Unit/build tests for wolfSSL TLS source wiring and STM32 user settings.
- Optional capability-gated hardware UART smoke test using the existing STM32 board only.
- Documentation records that this is TLS context lifecycle evidence only, not TLS handshake evidence.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M6.1 of the attached development plan - wolfSSL TLS Context Build-Only Smoke. Extend the STM32 wolfSSL source-build integration so the firmware can build and run a minimal wolfSSL TLS context lifecycle smoke. The smoke may initialize wolfSSL, create and free a client TLS context, and clean up wolfSSL state, but it must not perform or claim a TLS handshake, certificate loading, TCP transport, MQTT, ST67W61M1 backend use, Wi-Fi, or end-to-end network success. Keep any hardware UART smoke test capability-gated and label the evidence as TLS context lifecycle evidence only.

```

### Pass Criteria

- Firmware builds with the selected wolfSSL TLS source and user settings.
- TLS context lifecycle evidence is clearly separated from TLS handshake success.
- No certificates, private keys, transport, MQTT, Wi-Fi, or end-to-end network success are claimed.


---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** STM32 performs wolfSSL initialization, TLS 1.2 client-context creation/free, and cleanup only.
- **Verification:** Static/unit coverage, direct/relocated builds, and task-context marker coverage in the secure-boot benchmark hardware path.
- **Remaining limitations:** No `WOLFSSL` session, certificate loading, socket transport, handshake, MQTT, Wi-Fi, or ST67W61M1 use.
- **Deferred tests:** DTR-001 in `docs/007_framework_architecture.md`.
- **Last reconciled:** 2026-07-12

---

## Phase M6.2 — lwIP Network-Interface Boundary and Unavailable Status

### Goal

Add or validate a project-owned STM32 network-interface boundary that represents the future ST67W61M1-backed lwIP netif while keeping the backend explicitly unavailable until hardware-dependent work begins.

### Outcomes

- The firmware has a clear network-interface boundary for later ST67W61M1 backend integration.
- The boundary reports unavailable link, unavailable IP address, unavailable TCP readiness, and unavailable transport state.
- lwIP helper or netif data structures may be initialized locally where safe, but no link-up, DHCP/static IP assignment, TCP connection, TLS handshake, MQTT connect, or publish success is claimed.
- The boundary can be consumed later by wolfSSL transport and wolfMQTT work without coupling MQTT logic directly to the ST67W61M1 driver.
- Documentation records that the network-interface backend remains deferred.

### Expected Evidence

- Direct and relocated firmware builds.
- Unit/build tests for the network-interface boundary and unavailable-state marker.
- Optional capability-gated hardware UART smoke test using the existing STM32 board only.
- Documentation records unavailable network metrics and deferred ST67W61M1 validation.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M6.2 of the attached development plan - lwIP Network-Interface Boundary and Unavailable Status. Add or validate a project-owned STM32 network-interface boundary for the future ST67W61M1-backed lwIP integration. The boundary should expose explicit unavailable status for link, IP address, TCP readiness, and transport availability, and may exercise safe local lwIP helpers where appropriate. This sub-phase must not claim Wi-Fi module detection, link-up, IP acquisition, TCP connection, TLS handshake, MQTT connect, MQTT publish, reconnect, or end-to-end network success. Keep any hardware UART smoke test capability-gated.

```

### Pass Criteria

- Firmware builds with the network-interface boundary.
- Network/link/IP/TCP status remains explicitly unavailable.
- The boundary is suitable for later wolfSSL transport and wolfMQTT integration without requiring Wi-Fi hardware.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** Project-owned boundary reports unattached local lwIP `netif` observations and explicitly unavailable transport/network states.
- **Verification:** Static/unit coverage and direct/relocated local-build integration.
- **Remaining limitations:** No registered interface, link-up, DHCP, hardware IP, socket, external network, or ST67W61M1 access.
- **Deferred tests:** DTR-002 in `docs/007_framework_architecture.md`.
- **Last reconciled:** 2026-07-12

---

## Phase M6.3 — wolfSSL Transport Boundary Without Network

### Goal

Prepare the wolfSSL transport integration boundary between wolfSSL and the future lwIP/ST67W61M1 network path without performing real socket I/O or a TLS handshake.

### Outcomes

- wolfSSL transport callback structure or wrapper functions are represented in project-owned firmware code.
- The transport boundary can report unavailable read/write/connect state without performing real network I/O.
- The boundary is aligned with the lwIP network-interface unavailable status from Phase M6.2.
- The firmware can build with the planned wolfSSL transport boundary before wolfMQTT is introduced.
- No TLS handshake, certificate loading, TCP connection, MQTT connect, MQTT publish, reconnect, Wi-Fi, or end-to-end network success is claimed.

### Expected Evidence

- Direct and relocated firmware builds.
- Unit/build tests for transport-boundary wiring and unavailable-state behavior.
- Optional capability-gated hardware UART smoke test using the existing STM32 board only.
- Documentation records that wolfSSL transport callbacks are prepared but runtime transport remains unavailable.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M6.3 of the attached development plan - wolfSSL Transport Boundary Without Network. Add or validate the STM32 wolfSSL transport boundary that will later connect wolfSSL to the lwIP/ST67W61M1 network path. The boundary may define callback structure, wrapper functions, and unavailable read/write/connect status, but it must not perform real socket I/O, TLS handshake, certificate loading, MQTT connect, MQTT publish, reconnect, Wi-Fi, or end-to-end network success. Keep any hardware UART smoke test capability-gated and label all evidence as build-only or unavailable-transport evidence.

```

### Pass Criteria

- Firmware builds with the wolfSSL transport boundary.
- Transport status remains explicitly unavailable.
- The boundary is ready for later wolfMQTT build-only work without requiring real networking.
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** Project-owned wolfSSL connect/read/write callback boundary is present but returns unavailable and performs no socket I/O.
- **Verification:** Static/unit coverage and direct/relocated local-build integration.
- **Remaining limitations:** No TCP connection, byte transfer, certificates, TLS handshake, MQTT, Wi-Fi, or end-to-end operation.
- **Deferred tests:** DTR-004 in `docs/007_framework_architecture.md`.
- **Last reconciled:** 2026-07-12

---

## Phase M6.4 — Secure-Boot Timing Clock Evidence Cleanup

### Goal

Replace the hard-coded wolfBoot timing CPU-frequency assumption with explicit secure-boot timing evidence that records raw verification cycles and reported bootloader clock state separately from any derived milliseconds value.

### Outcomes

- The wolfBoot verification timing instrumentation no longer treats a hard-coded `80000000` Hz constant as measured CPU frequency.
- UART output reports raw DWT verification cycles as the primary timing evidence.
- UART output reports relevant bootloader clock values separately, such as reported SYSCLK, HCLK, PCLK1, PCLK2, and `SystemCoreClock` where available in the wolfBoot build context.
- Any cycle-to-millisecond conversion is either removed from firmware/runtime evidence or clearly labelled as a derived/reporting-layer calculation using an explicitly named clock source.
- Result manifests record raw verification cycles and reported clock values without implying that a compile-time conversion constant is a measured runtime CPU frequency.
- Framework parsers, manifest schema, aggregate reporting, and tests are updated so they no longer hard-code or require `80000000` Hz.
- Existing UART and manifest fields are migrated or renamed where needed to avoid ambiguity between:
  - raw DWT cycle counts
  - reported bootloader clock values
  - derived time in milliseconds
- Hardware tests remain capability-gated and validate the new UART markers using explicit boot evidence.
- No RTC or wall-clock measurement is introduced in this phase.

### Expected Evidence

- Unit tests for UART parsing and manifest generation using the new timing/clock fields.
- Unit tests confirming tests and reporting no longer hard-code `80000000` as the expected CPU frequency.
- Integration or build tests confirming wolfBoot instrumentation still builds for secure-boot profiles.
- Capability-gated hardware tests confirming UART captures include raw verification cycles, verification result, memory markers, and bootloader clock evidence.
- Updated documentation explaining that DWT cycles are the primary firmware-side verification timing evidence and that milliseconds, if reported, are derived from an explicitly named clock source.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M6.4 of the attached development plan - Secure-Boot Timing Clock Evidence Cleanup. Update the wolfBoot secure-boot timing instrumentation and experiment framework so timing evidence no longer depends on a hard-coded 80000000 Hz CPU-frequency constant. The UART output and manifest should record raw DWT verification cycles as the primary timing metric and should report actual bootloader clock values available from the MCU/HAL/CMSIS clock model separately. Remove or relabel firmware-side cycle-to-millisecond conversion so any milliseconds value is clearly derived from an explicitly named clock source rather than treated as measured evidence. Update UART parsing, manifest schema, aggregate benchmark reporting, unit tests, integration tests, hardware tests, and documentation so they no longer hard-code 80000000 Hz. Do not introduce RTC or wall-clock timing in this phase. Keep hardware tests capability-gated and do not claim timing accuracy beyond explicit UART, manifest, or hardware evidence.
```

### Pass Criteria

- UART output no longer reports a hard-coded `wolfBoot verification cpu_hz: 80000000` value as if it were a measured runtime frequency.
- Raw DWT verification cycles remain available in UART logs and manifests.
- Bootloader clock values are reported separately where available.
- Manifest fields distinguish raw cycle evidence from reported clock state and derived milliseconds.
- Tests no longer assert `verification_cpu_hz == 80000000`.
- Hardware tests validate the new markers without assuming a fixed 80 MHz clock.
- Documentation clearly states the evidence boundary for cycles, clock reporting, and any derived time values.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** Secure-boot timing retains raw DWT cycles and explicit RCC-derived clock evidence; time is derived only from recorded cycles and HCLK.
- **Verification:** Unit coverage plus capability-gated secure-boot benchmark hardware/manifest assertions.
- **Remaining limitations:** Derived time is not independently calibrated wall-clock, RTC, host-duration, or UART-latency evidence.
- **Deferred tests:** None.
- **Last reconciled:** 2026-07-12

---

## Phase M6.5 — FreeRTOS Task-Context Runtime Smoke

### Goal

Add post-scheduler STM32 runtime smoke evidence for the lwIP and wolfSSL preparation layers so pre-scheduler boot smoke evidence is clearly separated from FreeRTOS task-context evidence.

### Outcomes

- The existing pre-scheduler smoke markers remain available as early boot/build sanity evidence.
- A FreeRTOS task-context smoke path runs after the scheduler starts.
- UART output identifies the execution context for each marker, such as `context=pre_scheduler` or `context=freertos_task`.
- The post-scheduler smoke may exercise the same local deterministic lwIP and wolfSSL/wolfCrypt checks where safe.
- The work does not introduce real network transport, TCP connection, TLS handshake, certificate loading, MQTT connect, MQTT publish, Wi-Fi, or end-to-end success.
- wolfSSL may remain single-threaded for this phase if access is serialized and no concurrent wolfSSL use is tested.
- Any future wolfSSL FreeRTOS mutex/threading support remains a separate, explicit change unless required by inspected code.

### Expected Evidence

- Unit/build tests for the new marker text, task-context wiring, and execution-context labels.
- Direct and relocated firmware builds.
- Capability-gated UART hardware test confirming the FreeRTOS scheduler starts before the task-context smoke marker is emitted.
- Documentation explaining that task-context smoke evidence is distinct from pre-scheduler evidence and still does not claim network/TLS/MQTT runtime success.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M6.5 of the attached development plan - FreeRTOS Task-Context Runtime Smoke. Add a post-scheduler STM32 runtime smoke path for the existing lwIP and wolfSSL preparation layers. Preserve the existing pre-scheduler smoke evidence, but add FreeRTOS task-context UART markers that explicitly state the scheduler is running and identify the smoke context as freertos_task. The task-context smoke may run deterministic local lwIP and wolfSSL/wolfCrypt checks, but it must not perform or claim Wi-Fi, link-up, IP assignment, TCP connection, TLS handshake, certificate loading, MQTT connect, MQTT publish, reconnect, or end-to-end network success. Keep hardware tests capability-gated and do not introduce wolfSSL multithreaded support unless the inspected implementation requires it.
```

### Pass Criteria

- Pre-scheduler and FreeRTOS task-context smoke markers are both clearly labelled.
- Hardware UART evidence confirms task-context smoke occurs after scheduler start.
- The phase does not claim network, TLS handshake, MQTT, Wi-Fi, or end-to-end success.
- Tests distinguish task-context evidence from pre-scheduler evidence.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** Local lwIP and wolfSSL smoke checks execute once in FreeRTOS task context after the scheduler starts.
- **Verification:** Static/unit checks, direct/relocated builds, and known-image secure-boot benchmark UART marker-order assertions.
- **Remaining limitations:** Execution is serialized and local; no multithreaded wolfSSL support or network/protocol capability is enabled.
- **Deferred tests:** None.
- **Last reconciled:** 2026-07-12

---

## Phase M6.6 — lwIP Local Loopback Runtime Smoke Without Network Hardware

### Goal

Validate a controlled STM32-local lwIP runtime path using loopback without requiring the ST67W61M1 Wi-Fi module or external network hardware.

### Outcomes

- lwIP loopback support is configured only where appropriate for the selected build.
- A FreeRTOS task-context loopback smoke can send and receive local traffic through lwIP without external network hardware.
- UDP loopback is preferred as the first implementation target; TCP loopback may be deferred unless required by inspected code.
- UART output clearly labels the evidence as local loopback only.
- The result does not claim Wi-Fi module detection, link-up, external IP connectivity, external ping response, broker access, TLS handshake, MQTT connect, MQTT publish, reconnect, or end-to-end network success.
- The loopback evidence can inform later transport and wolfMQTT work without coupling MQTT logic directly to the ST67W61M1 backend.

### Expected Evidence

- Unit/build tests for lwIP loopback configuration and marker wording.
- Direct and relocated firmware builds.
- Capability-gated UART hardware test confirming local loopback success and explicit external-network unavailability.
- Manifest or result schema updates where needed to distinguish local loopback evidence from real network evidence.
- Documentation recording that loopback is internal STM32/lwIP evidence only.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M6.6 of the attached development plan - lwIP Local Loopback Runtime Smoke Without Network Hardware. Add or validate a STM32-local lwIP loopback runtime smoke that runs after FreeRTOS scheduler start and does not require the ST67W61M1 Wi-Fi module or external network hardware. Prefer a deterministic UDP loopback send/receive smoke unless inspected code shows a safer alternative. UART and manifest evidence must clearly state that loopback is local-only and must not claim Wi-Fi module detection, link-up, IP acquisition over hardware, external ping, TCP external connectivity, TLS handshake, MQTT connect, MQTT publish, reconnect, broker access, or end-to-end network success. Keep hardware tests capability-gated.
```

### Pass Criteria

- STM32 firmware can produce explicit local lwIP loopback evidence without network hardware.
- Loopback evidence is not confused with ST67W61M1, external network, TLS, MQTT, or broker evidence.
- Tests remain capability-gated and distinguish local loopback from real network validation.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** STM32 runs deterministic UDP loopback at `127.0.0.1` after scheduler start.
- **Verification:** Static/unit coverage, direct/relocated builds, and known-image hardware assertion in `tests/hardware/test_baseline_uart.py`.
- **Remaining limitations:** Loopback is local-only and does not prove Wi-Fi, hardware IP, external TCP, TLS, MQTT, or broker access.
- **Deferred tests:** None.
- **Last reconciled:** 2026-07-12

---

## Phase M7 — wolfMQTT Build-Only Skeleton

### Goal

Add or validate wolfMQTT build integration and bind it to an abstract transport boundary without requiring real networking.

### Outcomes

- Firmware can build and link with wolfMQTT or the planned wolfMQTT integration layer.
- MQTT client initialization can be represented separately from MQTT connection success.
- Transport callbacks are isolated from the MQTT client logic.
- Fake/no-network backend can be selected for build/test purposes.
- No real MQTT broker connection or publish success is claimed.

### Expected Evidence

- Direct and relocated firmware builds.
- Unit/build tests for relevant wiring.
- Optional UART marker planning, if hardware runtime is included later, must distinguish initialization from network success and should identify whether evidence is pre-scheduler or FreeRTOS task-context.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M7 of the attached development plan - wolfMQTT Build-Only Skeleton. Add or validate a wolfMQTT build-only skeleton for STM32 MQTT/TLS work. The MQTT client must be separated from the transport backend so fake/no-network and future ST67W61M1 backends can be selected without changing MQTT logic. This sub-phase must not claim broker connection, TLS handshake, publish, reconnect, Wi-Fi, or end-to-end success.

```

### Pass Criteria

- Firmware builds with wolfMQTT integration boundary.
- MQTT client logic is not tightly coupled to ST67W61M1 hardware.
- No broker or publish success is claimed.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** Pinned wolfMQTT client, packet, and socket-callback layers build and link behind a project-owned backend boundary.
- **Verification:** Static/unit coverage and direct/relocated local-build integration.
- **Remaining limitations:** No network connect, MQTT CONNECT, subscribe, publish, receive, TLS, Wi-Fi, or ST67W61M1 runtime operation.
- **Deferred tests:** None.
- **Last reconciled:** 2026-07-12

---

## Phase M8 — STM32 Fake/No-Network Runtime Evidence

### Goal

Run the STM32 firmware on the existing board with a fake/no-network backend to validate initialization evidence before Wi-Fi hardware is available.

### Outcomes

- STM32 firmware boots with the MQTT/TLS components present or prepared.
- UART output can confirm initialization states.
- Runtime output clearly states fake/no-network mode where applicable.
- Runtime output does not claim Wi-Fi, IP, TCP, TLS, MQTT connect, publish, or reconnect success.
- Hardware required is the STM32 board only, not the X-NUCLEO-67W61M1.

### Expected Evidence

- UART logs.
- Manifest entries where supported.
- Hardware tests remain capability-gated.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase _ of the attached development plan - _. Add STM32 fake/no-network runtime evidence for the MQTT/TLS preparation work. The firmware may emit explicit initialization and unavailable-backend markers, but it must not claim Wi-Fi, IP, TCP, TLS handshake, MQTT connect, publish, reconnect, or end-to-end success. The X-NUCLEO-67W61M1 must not be required for this sub-phase. Keep hardware tests capability-gated.

```

### Pass Criteria

- UART evidence confirms initialization or unavailable backend markers.
- No Wi-Fi module is required.
- No network, TLS, MQTT, or publish success is claimed.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** STM32 initializes and deinitializes wolfMQTT once from `defaultTask` using the fake/no-network backend.
- **Verification:** Static/unit coverage, direct/relocated builds, and known-image hardware assertion in `tests/hardware/test_baseline_uart.py`.
- **Remaining limitations:** Transport, TLS handshake, MQTT connect/publish/reconnect, Wi-Fi, ST67W61M1, and end-to-end status remain unavailable.
- **Deferred tests:** None.
- **Last reconciled:** 2026-07-12

---

## Phase M9 — Host-Side wolfMQTT/wolfSSL Prototype or Validation Utility

### Goal

Optionally validate MQTT/TLS semantics against the broker using wolfSSL and wolfMQTT on the host side, while keeping the result separate from STM32 evidence.

### Outcomes

- Host-side wolfSSL/wolfMQTT validation can connect to the broker where supported.
- Evidence is labelled host-side only.
- The result informs later STM32 configuration without claiming STM32 runtime success.

### Expected Evidence

- Host-side client logs or integration test output.
- Broker logs where useful.
- Capability-gated if broker/gateway access is required.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase _ of the attached development plan - _. Add an optional host-side wolfSSL/wolfMQTT validation path for MQTT-over-TLS broker compatibility. Evidence from this path must be labelled host-side only and must not be used to claim STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless success. Keep broker/gateway-dependent validation capability-gated.

```

### Pass Criteria

- Host-side MQTT/TLS validation is useful but clearly separated from STM32 evidence.
- No hardware or Wi-Fi module is required.
- No STM32 runtime success is claimed.

---
### Phase status

- **Status:** completed
- **Implemented evidence boundary:** Native host wolfMQTT/wolfSSL utility provides structured `host_side` broker-compatibility evidence.
- **Verification:** Unit coverage and capability-aware native build integration in `tests/integration/test_host_wolfmqtt_build.py`.
- **Remaining limitations:** Host results do not prove STM32, Wi-Fi-module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, or wireless behavior.
- **Deferred tests:** DTR-005 in `docs/007_framework_architecture.md`.
- **Last reconciled:** 2026-07-12

---

## Deferred Phase M10 — ST67W61M1 Network Interface Backend

### Goal

Add the real Wi-Fi module backend once the X-NUCLEO-67W61M1 is installed and available.

### Outcomes

- ST67W61M1 backend is added under the established transport/network-interface boundary.
- STM32 remains responsible for lwIP, TLS, and MQTT according to the target architecture.
- Wi-Fi/module detection and network bring-up are validated separately from TLS and MQTT.
- Hardware tests remain capability-gated.

### Expected Evidence

- Explicit logs or UART markers for module detection.
- Explicit evidence for network-interface bring-up.
- Explicit evidence for IP/TCP readiness.
- No TLS/MQTT success claim unless separately validated.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase _ of the attached development plan - _. Add the ST67W61M1 network-interface backend for the existing STM32-local lwIP/wolfSSL/wolfMQTT architecture. Validate module detection and network-interface bring-up separately from TLS and MQTT success. Do not claim TLS handshake, MQTT connect, publish, reconnect, or end-to-end success unless explicit logs, UART evidence, manifests, or broker logs support those claims. Keep hardware tests capability-gated.

```

### Suggested Files to Provide

The exact files should be determined from the current repository and the selected ST67W61M1 driver/API path. At minimum, expect the AI to ask for the current build guide, architecture docs, firmware sources, CubeMX metadata, middleware files, relevant ST67W61M1 driver files, configs, and tests.

### Pass Criteria

- ST67W61M1 backend can be built and tested with real hardware.
- Evidence categories remain separated.
- No unsupported runtime success is inferred.

---
### Phase status

- **Status:** deferred
- **Implemented evidence boundary:** No hardware-backed ST67W61M1 network backend is implemented; only compile-time driver/interface preparation exists.
- **Verification:** Current builds and static tests verify preparation boundaries only.
- **Remaining limitations:** Module detection, Wi-Fi association, link, DHCP/hardware IP, and external TCP remain unimplemented.
- **Deferred tests:** DTR-006 in `docs/007_framework_architecture.md`.
- **Last reconciled:** 2026-07-12

---

## Deferred Phase M11 — Classical MQTT over TLS on STM32

### Goal

Validate actual STM32-to-broker MQTT-over-TLS with lwIP, wolfSSL, wolfMQTT, and the ST67W61M1 network interface.

### Outcomes

- STM32 performs TLS handshake.
- STM32 performs MQTT connect.
- STM32 publishes to broker.
- Reconnect behavior can be measured.
- Runtime metrics are captured from explicit firmware/UART markers and broker evidence.
- Results are recorded in manifests or metrics files.

### Expected Evidence

- STM32 UART logs.
- Broker logs.
- Result manifests.
- Repeat-run metrics where implemented.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase _ of the attached development plan - _. Implement classical MQTT-over-TLS runtime validation on STM32 using the established architecture where lwIP, wolfSSL, and wolfMQTT run on the STM32 and the ST67W61M1 provides the network interface. Capture TLS handshake, MQTT connect, publish, reconnect, and relevant resource metrics only from explicit logs, UART markers, manifests, or broker evidence. Keep tests capability-gated and preserve the repository secrets policy.

```

### Pass Criteria

- Explicit STM32 and broker evidence confirms classical MQTT-over-TLS.
- Metrics are captured without inference.
- Hardware-dependent tests remain opt-in.

---
### Phase status

- **Status:** deferred
- **Implemented evidence boundary:** No complete classical STM32 MQTT-over-TLS runtime path exists.
- **Verification:** Host/broker compatibility and STM32-local preparation are verified separately.
- **Remaining limitations:** Requires M10 plus real wolfSSL transport/handshake and wolfMQTT protocol operation on STM32.
- **Deferred tests:** DTR-007 in `docs/007_framework_architecture.md`.
- **Last reconciled:** 2026-07-12

---

## Deferred Phase M12 — Network Degradation

### Goal

Evaluate MQTT/TLS behavior under controlled network impairment after the real network path works.

### Outcomes

- Network impairment profiles can be applied and cleared safely.
- Results record the active network profile.
- Cleanup is robust after failures.
- Metrics reflect real observed behavior.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase _ of the attached development plan - _. Add controlled network-degradation support for MQTT/TLS experiments after the real STM32 MQTT-over-TLS path is working. The implementation must apply, verify, and clean up impairments safely, record the active network profile in results, and keep gateway-dependent tests capability-gated. Do not claim degraded-network results without explicit logs or manifests.

```

### Pass Criteria

- Network impairment setup and cleanup are reliable.
- Results are evidence-backed.
- No degraded-network result is inferred.

---
### Phase status

- **Status:** deferred
- **Implemented evidence boundary:** No controlled network-impairment experiment path is implemented.
- **Verification:** No current verification applies beyond existing undegraded capability boundaries.
- **Remaining limitations:** Requires a stable real STM32 MQTT-over-TLS path and safe gateway impairment/cleanup controls.
- **Deferred tests:** DTR-008 in `docs/007_framework_architecture.md`.
- **Last reconciled:** 2026-07-12

---

## Deferred Phase M13 — PQC/Hybrid MQTT/TLS Experiments

### Goal

Add PQC or hybrid TLS experiments only after classical MQTT/TLS is stable and supported library capabilities are confirmed.

### Outcomes

- wolfSSL/wolfMQTT support is confirmed before profiles are added.
- PQC/hybrid configs are introduced only for supported modes.
- Metrics remain comparable with classical TLS runs.
- Experimental status is documented.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase _ of the attached development plan - _. Add PQC or hybrid MQTT/TLS experiment profiles only after confirming the selected wolfSSL/wolfMQTT support and after classical STM32 MQTT-over-TLS is stable. Preserve comparable metrics, capability-gated tests, and evidence discipline. Do not add unsupported profiles or claim PQC/hybrid TLS success without explicit logs, manifests, or broker/client validation output.

```

### Pass Criteria

- Supported PQC/hybrid modes are confirmed.
- Profiles are evidence-backed.
- Experimental limitations are documented.

---
### Phase status

- **Status:** deferred
- **Implemented evidence boundary:** No PQC or hybrid STM32 MQTT/TLS profile is implemented.
- **Verification:** Experimental OQS broker/host evidence exists separately and is not STM32 evidence.
- **Remaining limitations:** Requires stable classical M11 behavior and confirmed target wolfSSL/wolfMQTT algorithm support.
- **Deferred tests:** DTR-009 in `docs/007_framework_architecture.md`.
- **Last reconciled:** 2026-07-12

---


## Overall Completion Criteria

The non-hardware MQTT/TLS preparation path is complete when:

- MQTT/TLS architecture is documented without assuming Wi-Fi hardware availability.
- Config and result schema support fake, host, build-only, STM32 runtime, and future ST67W61M1-backed evidence.
- Fake/no-network transport behavior is testable.
- Host/broker validation is available and clearly separated from STM32 evidence.
- STM32 firmware can build with the planned lwIP/wolfSSL/wolfMQTT boundaries where implemented.
- Intermediate lwIP network-interface, wolfSSL TLS-context, wolfSSL transport-boundary, FreeRTOS task-context smoke, and local lwIP loopback work remain clearly separated from real network and TLS handshake success.
- STM32 can provide fake/no-network initialization and local-only runtime evidence without the Wi-Fi module where implemented.
- Secure-boot timing evidence does not treat compile-time CPU-frequency assumptions as measured clock values.
- ST67W61M1-dependent work remains deferred until the hardware is available.
- No runtime success is claimed without explicit supporting evidence.
