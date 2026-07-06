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
- Keep broker-side, host-side, fake-transport, STM32 build-only, and STM32 hardware evidence clearly separated.
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

Requirement: Update the MQTT/TLS roadmap and architecture documentation to split hardware-independent development from ST67W61M1-dependent validation. The revised plan must preserve the target architecture where lwIP, wolfSSL, and wolfMQTT run on the STM32, while the Wi-Fi module is treated as the network interface. Focus on goals, outcomes, evidence boundaries, and small future implementation phases. Do not implement firmware, Docker, or framework code yet.

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

Requirement: Add framework-side MQTT/TLS experiment configuration and result schema support for future MQTT client work. The schema must support explicit transport backend selection and unavailable metrics. It must distinguish fake/no-network, host-side, STM32 build-only, STM32 runtime, and future ST67W61M1-backed evidence. Do not implement STM32 firmware networking, lwIP integration, wolfSSL integration, wolfMQTT integration, broker deployment, or hardware tests in this sub-phase.

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

Requirement: Add a fake/no-network MQTT transport harness for deterministic non-hardware testing of MQTT client control-flow behavior. It should support simulated connect, publish, timeout, disconnect, and reconnect outcomes, and all simulated evidence must be clearly labelled as fake transport evidence. Do not implement real networking, lwIP, wolfSSL, wolfMQTT firmware integration, broker deployment, gateway access, or hardware tests in this sub-phase.

```

### Pass Criteria

- Fake transport outcomes are deterministic and testable.
- Simulated evidence is not confused with real broker, TLS, or STM32 runtime evidence.
- No hardware or network dependency is introduced.

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

Requirement: Add or refine host-side MQTT/TLS broker compatibility validation for the existing broker scaffold. The validation must be clearly labelled as host-side and broker-side evidence only. It must not claim STM32, Wi-Fi module, lwIP, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless success. Keep gateway/broker-dependent tests capability-gated.

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

Requirement: Add or validate a STM32-local lwIP build-only skeleton for future MQTT/TLS work. This sub-phase must not require the ST67W61M1 Wi-Fi module and must not claim Wi-Fi, IP, TCP, TLS, MQTT, publish, reconnect, or end-to-end success. Keep any network interface unavailable, stubbed, or explicitly deferred. Preserve CubeMX-generated layout unless an inspected file requires a scoped change.

```

### Pass Criteria

- Firmware builds with the intended lwIP preparation.
- Runtime networking remains explicitly unavailable.
- No Wi-Fi hardware is required.

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

Requirement: Add or validate a wolfSSL build-only skeleton for STM32 MQTT/TLS work. The firmware should build with the intended wolfSSL integration boundary, but this sub-phase must not perform or claim a real TLS handshake. Certificate and secret handling must follow the repository secrets policy. Do not implement real network transport, ST67W61M1 backend, MQTT publish, or hardware tests in this sub-phase.

```

### Pass Criteria

- Firmware builds with wolfSSL integration boundary.
- TLS runtime success is not claimed.
- Secret-handling rules are preserved.

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
- Optional UART marker planning, if hardware runtime is included later, must distinguish initialization from network success.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Add or validate a wolfMQTT build-only skeleton for STM32 MQTT/TLS work. The MQTT client must be separated from the transport backend so fake/no-network and future ST67W61M1 backends can be selected without changing MQTT logic. This sub-phase must not claim broker connection, TLS handshake, publish, reconnect, Wi-Fi, or end-to-end success.

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

Requirement: Add STM32 fake/no-network runtime evidence for the MQTT/TLS preparation work. The firmware may emit explicit initialization and unavailable-backend markers, but it must not claim Wi-Fi, IP, TCP, TLS handshake, MQTT connect, publish, reconnect, or end-to-end success. The X-NUCLEO-67W61M1 must not be required for this sub-phase. Keep hardware tests capability-gated.

```

### Pass Criteria

- UART evidence confirms initialization or unavailable backend markers.
- No Wi-Fi module is required.
- No network, TLS, MQTT, or publish success is claimed.

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

Requirement: Add an optional host-side wolfSSL/wolfMQTT validation path for MQTT-over-TLS broker compatibility. Evidence from this path must be labelled host-side only and must not be used to claim STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless success. Keep broker/gateway-dependent validation capability-gated.

```

### Pass Criteria

- Host-side MQTT/TLS validation is useful but clearly separated from STM32 evidence.
- No hardware or Wi-Fi module is required.
- No STM32 runtime success is claimed.

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

Requirement: Add the ST67W61M1 network-interface backend for the existing STM32-local lwIP/wolfSSL/wolfMQTT architecture. Validate module detection and network-interface bring-up separately from TLS and MQTT success. Do not claim TLS handshake, MQTT connect, publish, reconnect, or end-to-end success unless explicit logs, UART evidence, manifests, or broker logs support those claims. Keep hardware tests capability-gated.

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

Requirement: Implement classical MQTT-over-TLS runtime validation on STM32 using the established architecture where lwIP, wolfSSL, and wolfMQTT run on the STM32 and the ST67W61M1 provides the network interface. Capture TLS handshake, MQTT connect, publish, reconnect, and relevant resource metrics only from explicit logs, UART markers, manifests, or broker evidence. Keep tests capability-gated and preserve the repository secrets policy.

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

Requirement: Add controlled network-degradation support for MQTT/TLS experiments after the real STM32 MQTT-over-TLS path is working. The implementation must apply, verify, and clean up impairments safely, record the active network profile in results, and keep gateway-dependent tests capability-gated. Do not claim degraded-network results without explicit logs or manifests.

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

Requirement: Add PQC or hybrid MQTT/TLS experiment profiles only after confirming the selected wolfSSL/wolfMQTT support and after classical STM32 MQTT-over-TLS is stable. Preserve comparable metrics, capability-gated tests, and evidence discipline. Do not add unsupported profiles or claim PQC/hybrid TLS success without explicit logs, manifests, or broker/client validation output.

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
- STM32 can provide fake/no-network initialization evidence without the Wi-Fi module where implemented.
- ST67W61M1-dependent work remains deferred until the hardware is available.
- No runtime success is claimed without explicit supporting evidence.
