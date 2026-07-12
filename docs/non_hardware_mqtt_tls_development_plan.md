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

Update the plan and architecture documentation so MQTT/TLS development is explicitly split into hardware-independent and hardware-dependent phases.

### Outcomes

- The roadmap records that MQTT/TLS client development can proceed without the Wi-Fi module.
- The architecture states that lwIP, wolfSSL, and wolfMQTT are intended to run on STM32.
- Transport modes are distinguished:
  - fake/no-network transport
  - host/socket validation path
  - future ST67W61M1 network-interface backend
- Evidence categories are separated:
  - build-only evidence
  - fake transport evidence
  - host-side evidence
  - broker-side evidence
  - STM32 runtime evidence
  - end-to-end wireless evidence
- No code is implemented in this phase.

### Expected Evidence

- Updated planning documentation.
- Updated architecture documentation where needed.
- No MQTT, TLS, Wi-Fi, publish, latency, or reconnect success claims.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M1 of the attached development plan - MQTT/TLS Architecture Split Without Wi-Fi Hardware. Update the MQTT/TLS roadmap and architecture documentation to split hardware-independent development from ST67W61M1-dependent validation. The revised plan must preserve the target architecture where lwIP, wolfSSL, and wolfMQTT run on the STM32, while the Wi-Fi module is treated as the network interface. Focus on goals, outcomes, evidence boundaries, and small future implementation phases. Do not implement firmware, Docker, or framework code yet.

```

### Pass Criteria

- The plan no longer assumes Wi-Fi hardware is available before MQTT/TLS design work starts.
- STM32-local lwIP/wolfSSL/wolfMQTT ownership is explicit.
- Future implementation phases are small and evidence-bound.

---

## Phase M2 — MQTT Configuration and Result Schema

### Goal

Add framework-side configuration and result schema support for MQTT/TLS experiments before firmware transport implementation.

### Outcomes

- MQTT experiment configuration can be represented and validated.
- Transport backend selection can be represented.
- TLS mode and certificate references can be represented where appropriate.
- Result schema can represent available and unavailable metrics.
- Hardware-dependent metrics are not fabricated.
- The schema can distinguish fake, host, STM32 build-only, STM32 runtime, and ST67W61M1-backed runs.

### Expected Evidence

- Config validation tests.
- Result schema tests.
- No MQTT runtime success claims.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M2 of the attached development plan - MQTT Configuration and Result Schema. Add framework-side MQTT/TLS experiment configuration and result schema support for future MQTT client work. The schema must support explicit transport backend selection and unavailable metrics. It must distinguish fake/no-network, host-side, STM32 build-only, STM32 runtime, and future ST67W61M1-backed evidence. Do not implement STM32 firmware networking, lwIP integration, wolfSSL integration, wolfMQTT integration, broker deployment, or hardware tests in this sub-phase.

```

### Pass Criteria

- MQTT/TLS configs validate.
- Invalid configs are rejected.
- Unavailable hardware/network metrics are represented explicitly.
- No network or hardware access is required.

---

## Phase M3 — Fake/No-Network MQTT Transport Harness

### Goal

Provide deterministic non-network test coverage for MQTT client control-flow behavior.

### Outcomes

- A fake/no-network transport mode exists for tests.
- Tests can model connect success, connect failure, read timeout, write timeout, disconnect, and reconnect attempts.
- The harness produces simulated evidence that is clearly labelled as simulated.
- The framework does not treat fake transport results as real MQTT/TLS runtime success.

### Expected Evidence

- Unit tests for simulated transport outcomes.
- Result records or manifests label fake transport evidence clearly.
- No broker, gateway, Wi-Fi module, UART, or STM32 hardware is required.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M3 of the attached development plan - Fake/No-Network MQTT Transport Harness. Add a fake/no-network MQTT transport harness for deterministic non-hardware testing of MQTT client control-flow behavior. It should support simulated connect, publish, timeout, disconnect, and reconnect outcomes, and all simulated evidence must be clearly labelled as fake transport evidence. Do not implement real networking, lwIP, wolfSSL, wolfMQTT firmware integration, broker deployment, gateway access, or hardware tests in this sub-phase.

```

### Pass Criteria

- Fake transport outcomes are deterministic and testable.
- Simulated evidence is not confused with real broker, TLS, or STM32 runtime evidence.
- No hardware or network dependency is introduced.

### Implementation Status

Implemented by the Phase M3 fake/no-network transport harness. The harness records simulated control-flow evidence only and keeps broker, network, TLS, STM32 runtime, gateway, UART, Wi-Fi, and hardware success claims false.

---

## Phase M4 — Host-Side Broker Compatibility Validation

### Goal

Validate MQTT/TLS broker compatibility separately from STM32 firmware and Wi-Fi hardware.

### Outcomes

- Existing MQTT broker scaffolding is used or extended for host-side validation.
- Classical MQTT-over-TLS broker setup can be validated from a host-side client path.
- Validation evidence is clearly labelled as host-side and broker-side.
- The work does not claim STM32 MQTT/TLS success.

### Expected Evidence

- Broker status/log output or host-side TLS/MQTT validation output.
- Capability-gated integration tests where gateway/broker access is required.
- No STM32 Wi-Fi hardware required.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M4 of the attached development plan - Host-Side Broker Compatibility Validation. Add or refine host-side MQTT/TLS broker compatibility validation for the existing broker scaffold. The validation must be clearly labelled as host-side and broker-side evidence only. It must not claim STM32, Wi-Fi module, lwIP, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless success. Keep gateway/broker-dependent tests capability-gated.

```

### Verification Commands

The implementation should provide exact commands. Expected validation may include:

```powershell
python -m pytest tests/unit
python -m pytest tests/integration/test_mqtt_broker_gateway_e2e.py -m integration
python -m pytest tests/integration/test_mqtt_broker_gateway_e2e.py -m integration --pqc-require-gateway
```

### Pass Criteria

- Broker validation remains capability-gated.
- Host/broker evidence is clearly separated from STM32 evidence.
- No Wi-Fi module is required.

---

## Phase M5 — STM32 lwIP Build-Only Skeleton

### Goal

Introduce or validate STM32-local lwIP build integration without requiring the Wi-Fi module.

### Outcomes

- The firmware can build with the intended lwIP structure or preparation layer.
- The network interface can remain absent, stubbed, or explicitly unavailable.
- No Wi-Fi join, IP address acquisition, TCP connection, TLS handshake, or MQTT publish success is claimed.
- Generated-code impacts are reviewed carefully and kept aligned with project rules.

### Expected Evidence

- Direct and relocated firmware builds.
- Local-build integration tests.
- Documentation records the build-only status and unavailable runtime metrics.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M5 of the attached development plan - STM32 lwIP Build-Only Skeleton. Add or validate a STM32-local lwIP build-only skeleton for future MQTT/TLS work. This sub-phase must not require the ST67W61M1 Wi-Fi module and must not claim Wi-Fi, IP, TCP, TLS, MQTT, publish, reconnect, or end-to-end success. Keep any network interface unavailable, stubbed, or explicitly deferred. Preserve CubeMX-generated layout unless an inspected file requires a scoped change.

```

### Pass Criteria

- Firmware builds with the intended lwIP preparation.
- Runtime networking remains explicitly unavailable.
- No Wi-Fi hardware is required.

### Implementation Status

Implemented to the current evidence boundary. The STM32 firmware emits a pre-scheduler lwIP runtime smoke marker for local deterministic helpers, while network hardware, link-up, IP assignment, TCP, TLS, MQTT, and end-to-end success remain unavailable. This is not FreeRTOS task-context networking evidence.

---

## Phase M6 — wolfSSL Build-Only Skeleton

### Goal

Add or validate wolfSSL build integration for STM32 without performing a real TLS handshake.

### Outcomes

- Firmware can build and link with wolfSSL or the planned wolfSSL integration layer.
- TLS configuration and certificate-handling boundaries are represented.
- Private keys and real credentials are not committed.
- TLS runtime metrics are unavailable until real transport evidence exists.

### Expected Evidence

- Direct and relocated firmware builds.
- Unit/build tests for relevant configuration or build wiring.
- Documentation records build-only status.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase M6 of the attached development plan - wolfSSL Build-Only Skeleton. Add or validate a wolfSSL build-only skeleton for STM32 MQTT/TLS work. The firmware should build with the intended wolfSSL integration boundary, but this sub-phase must not perform or claim a real TLS handshake. Certificate and secret handling must follow the repository secrets policy. Do not implement real network transport, ST67W61M1 backend, MQTT publish, or hardware tests in this sub-phase.

```

### Pass Criteria

- Firmware builds with wolfSSL integration boundary.
- TLS runtime success is not claimed.
- Secret-handling rules are preserved.

### Implementation Status

Implemented to the current evidence boundary. The STM32 firmware builds and invokes wolfSSL/wolfCrypt source in a pre-scheduler build/runtime smoke using deterministic local SHA-256 evidence. The evidence does not claim TLS context creation, TLS handshake, certificate loading, transport, MQTT, Wi-Fi, or end-to-end network success. wolfBoot and STM32 application wolfSSL settings must remain isolated so the application `user_settings.h` does not contaminate wolfBoot secure-boot builds.

---

## Phase M6.1 — wolfSSL TLS Context Build-Only Smoke

### Goal

Extend the Phase M6 wolfSSL source-build work from wolfCrypt-only smoke evidence to a minimal wolfSSL TLS context lifecycle smoke, without performing a TLS handshake.

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

### Implementation Status

Implementation may be in progress, but completion requires explicit test evidence. Do not mark this phase complete until unit/build tests and any selected capability-gated UART smoke tests pass and the evidence remains labelled as TLS context lifecycle evidence only.

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


## Phase M6.2.1 — Generated Build-State Isolation and Stale-Artifact Preflight

### Goal

Add a framework-level preflight that prevents stale, cross-profile, cross-toolchain, and cross-host/container generated state from being reused by STM32 CMake builds, wolfBoot builds, application signing, integration tests, and artifact-consuming experiment commands.

### Outcomes

- Project-owned generated-state manifests bind reusable state to workflow, profile, source/config fingerprint, toolchain identity, host/container identity, applicable key tuple, and successful artifact hashes.
- Compatible profile-scoped state may be retained; incompatible state and stale final artifacts are removed or quarantined deterministically before execution.
- Canonical local signing keys and other secrets are never cleanup targets.
- The wolfBoot-local private key, generated public key, and generated keystore are treated as one tuple and are not silently reconstructed from an existing private key.
- Downstream signing and flashing require successful provenance records and matching artifact hashes rather than filesystem existence alone.
- Direct command preflight is independent of pytest session-start cleanup.
- CubeMX-generated folders remain in place and Phase M6.3 transport work is not introduced.

### Expected Evidence

- Unit coverage for same-profile reuse, profile switching, host/container mismatch, failed-build stale artifact prevention, key/keystore mismatch, secret-path protection, and downstream provenance enforcement.
- Integration coverage that invokes the preflight directly without pytest startup cleanup.
- Direct and relocated builds, wolfBoot build, and signing verification using the normal container workflow.

### Pass Criteria

- Stale generated state cannot produce a trusted successful artifact after a failed command.
- Compatible same-profile state remains reusable.
- Cross-profile and cross-host/container state is rejected and cleaned deterministically.
- Canonical keys are preserved.
- Signing and secure-boot flashing reject unrecorded or hash-mismatched inputs before tool or gateway execution.


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

### Implementation Status

Implemented in project-owned `pqc_wolfssl_transport` firmware code. The boundary exposes connect/read/write wrappers and callback-shaped receive/send functions, consumes the Phase M6.2 network-interface status, and always reports unavailable transport without socket I/O, TLS sessions, certificate loading, handshake, MQTT, Wi-Fi, or ST67W61M1 runtime work. Completion still requires the documented unit and direct/relocated build evidence; any UART assertion remains capability-gated and must use a known flashed image.


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


### Implementation Status

Implemented with separate pre-scheduler and post-scheduler evidence. The deterministic lwIP helper smoke and wolfSSL/wolfCrypt TLS-context lifecycle smoke retain `context=pre_scheduler scheduler=not_started` markers and run once again from `defaultTask` with `context=freertos_task scheduler=running`. The calls are serialized; no wolfSSL multithreaded support is introduced. All Wi-Fi, link, IP, TCP, certificate, TLS-handshake, MQTT, reconnect, ST67W61M1, and end-to-end states remain explicitly unavailable.

### Pass Criteria

- Pre-scheduler and FreeRTOS task-context smoke markers are both clearly labelled.
- Hardware UART evidence confirms task-context smoke occurs after scheduler start.
- The phase does not claim network, TLS handshake, MQTT, Wi-Fi, or end-to-end success.
- Tests distinguish task-context evidence from pre-scheduler evidence.

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

Requirement: Implement Phase M8 of the attached development plan - STM32 Fake/No-Network Runtime Evidence. Add STM32 fake/no-network runtime evidence for the MQTT/TLS preparation work. The firmware may emit explicit initialization and unavailable-backend markers, but it must not claim Wi-Fi, IP, TCP, TLS handshake, MQTT connect, publish, reconnect, or end-to-end success. The X-NUCLEO-67W61M1 must not be required for this sub-phase. Keep hardware tests capability-gated. Some of these features may already be present, don't re-implement these, instead check that it matches the requirements and report any inconsistencies for a decision on what to do.

```

### Pass Criteria

- UART evidence confirms initialization or unavailable backend markers.
- No Wi-Fi module is required.
- No network, TLS, MQTT, or publish success is claimed.

### Implementation Status

Implemented by reusing the Phase M7 wolfMQTT boundary. A serialized one-shot initialization runs from `defaultTask` with `backend=fake_no_network`, emits `wolfMQTT runtime smoke:` as `stm32-fake-no-network-initialization-only` evidence, and deinitializes without network or MQTT protocol operations. Transport, Wi-Fi, link, IP, TCP, TLS handshake, MQTT connect, MQTT publish, reconnect, ST67W61M1, and end-to-end states remain unavailable. Direct and relocated builds plus static tests are the non-hardware evidence path; the known-image UART assertion is capability-gated and requires explicit user-provided output before hardware runtime success is claimed.

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

Requirement: Implement Phase M9 of the attached development plan - Host side wolfmqtt/wolfssl prototype or validation utility. Add a host-side wolfSSL/wolfMQTT validation path for MQTT-over-TLS broker compatibility. Evidence from this path must be labelled host-side only and must not be used to claim STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless success. Keep broker/gateway-dependent validation capability-gated. Some of this requirement may already be partially implemented as part of the MQTT broker that runs on the gateway and associated validation tests.

```

### Pass Criteria

- Host-side MQTT/TLS validation is useful but clearly separated from STM32 evidence.
- No STM32 hardware or Wi-Fi module is required.
- No STM32 runtime success is claimed.

### Implementation Status

Implemented with a separate native-host CMake target and wrapper utility. The target builds the pinned wolfMQTT client/example network path against the wolfSSL source pinned through the wolfBoot submodule. Output and optional JSON records are labelled `host_side` and explicitly keep STM32, Wi-Fi-module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, and end-to-end wireless claims false. Native build verification is capability-aware; live local or gateway broker validation requires separately available broker and temporary certificate capability. The broker Compose filename is `experiment/mqtt-broker/compose.yaml`.

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
