# PQC IoT Experiment Framework — Step-by-Step Plan

> **Lifecycle classification: Historical roadmap.** This document preserves the original framework goals, sequencing, checklists, and pass criteria. It is not the canonical current implementation-status source. Current architecture and evidence boundaries are owned by `docs/007_framework_architecture.md`; current MQTT phase status is owned by `docs/non_hardware_mqtt_tls_development_plan.md`. Last reconciled: 2026-07-12.

This historical checklist tracks the staged development of the STM32-based PQC IoT experiment framework. The project is broader than wolfBoot: it will eventually cover secure boot, MQTT, TLS, classical crypto, PQC/hybrid crypto, network degradation, benchmarking, result capture, documentation, and tests.

## Phase 0 — Freeze the Known-Good STM32 Baseline

## Phase 1 — Establish Documentation and AI Workflowg

## Phase 2 — Add Minimal Framework Skeleton

## Phase 3 — Add Result Manifest Support

## Phase 4 — Automate Build, But Do Not Flash Yet

## Phase 5 — Automate Remote Flash

## Phase 6 — Automate UART Capture

## Phase 7 — Add Full Baseline Run Command

## Phase 8 — Add Build Numbers and Artifact Tracking

## Phase 9 — Add Source-Hash Rebuild Skipping

## Phase 10 — Start Boot-Security Experiments

## Phase 11 — Secure-Boot Benchmark Metrics and Repeated-Run Support

## Phase C — Containerised Non-Hardware Build/Test Environment

This phase sits before STM32 MQTT client firmware, lwIP, wolfSSL, and wolfMQTT implementation work. It is a portability track for non-hardware development workflows. It preserves the existing host, gateway, flashing, UART, and hardware-test model.

Do not commit or bake SSH private keys, VPN private keys, TLS private keys, MQTT passwords, real `.env` files, private certificates, private signing keys, wolfBoot private signing keys, generated signing material, tokens, or production credentials into images or repository files. Use runtime mounts or locally generated material only when a workflow needs local secrets.

Generated build outputs, object files, signed images, signing outputs, result directories, cache directories, and container runtime state remain generated artifacts and must stay out of Git.

---

### Phase C1 — Containerisation Plan and Documentation

Goal: Add a repository-aligned containerisation plan before adding Docker or container runtime files.

Outcomes:

- [x] Document containerisation as a non-hardware portability phase.
- [x] Position the phase before STM32 MQTT client firmware, lwIP, wolfSSL, and wolfMQTT implementation work.
- [x] Identify supported future non-hardware workflow goals: Python tests, framework scripts, STM32 direct builds, STM32 relocated builds, wolfBoot builds, and relocated application signing.
- [x] Identify unsupported default-container workflows: hardware flashing, UART capture, direct USB/ST-LINK access, Wi-Fi-module access, gateway SSH workflows, MQTT broker gateway validation, and runtime evidence collection.
- [x] Document that signing workflows must use runtime-mounted or locally generated signing material only.
- [x] Preserve generated-output and secrets rules.
- [x] Avoid adding Dockerfiles, compose files, entrypoint scripts, CI changes, or container runtime commands in this phase.

Pass criteria:

- [x] Documentation defines the containerisation phase.
- [x] Existing hardware workflows are not made mandatory in the container.
- [x] Secret-handling constraints are preserved.
- [x] No Docker implementation is included in this phase.

---

### Phase C2 — Python-Only Container Baseline

Goal: Create the smallest useful container workflow for Python framework development.

Outcomes:

- [ ] Add a project-owned Python-only container baseline.
- [ ] Support Python dependency installation for framework development.
- [ ] Run unit tests inside the container.
- [ ] Run framework commands that do not require STM32 toolchains, SSH, UART, gateway access, broker access, or hardware.
- [ ] Document the workflow for a fresh checkout.
- [ ] Keep generated test, cache, and runtime output out of Git.

Pass criteria:

- [ ] Python unit tests pass inside the container.
- [ ] Non-hardware framework commands run inside the container.
- [ ] No STM32 build, wolfBoot build, signing, gateway, UART, broker, or hardware capability is required.

---

### Phase C3 — STM32 Build Container

Goal: Extend the container workflow to support non-hardware STM32 firmware builds.

Outcomes:

- [ ] Support the existing direct-flash CMake build workflow.
- [ ] Support the existing relocated CMake build workflow.
- [ ] Support relevant local-build integration tests when explicitly requested.
- [ ] Keep build outputs as generated artifacts outside Git.
- [ ] Keep the workflow independent of STM32 board access, ST-LINK, UART, gateway access, and Wi-Fi hardware.

Pass criteria:

- [ ] Direct-flash firmware builds inside the container.
- [ ] Relocated firmware builds inside the container.
- [ ] No flashing, UART capture, gateway access, or Wi-Fi-module access is required.

---

### Phase C4 — wolfBoot Build and Application Signing Container Support

Goal: Extend the container workflow to support secure-boot build and signing workflows without committing or baking secret material into the image.

Outcomes:

- [ ] Support wolfBoot build workflows inside the container.
- [ ] Support relocated application signing workflows inside the container.
- [ ] Use runtime-mounted or locally generated signing material only.
- [ ] Keep private keys and generated signing material uncommitted and outside the image.
- [ ] Keep secure-boot hardware flashing outside this sub-phase.

Pass criteria:

- [ ] wolfBoot builds inside the container.
- [ ] Relocated application signing works inside the container.
- [ ] Secret-handling documentation remains accurate.
- [ ] No secure-boot flashing, UART capture, or runtime benchmark success is claimed.

---

### Phase C5 — Optional Gateway-Capable Container Integration

Goal: Allow opt-in gateway-dependent integration workflows from the container without making them part of the default container pass criteria.

Outcomes:

- [ ] Support gateway-capable workflows only when explicitly enabled.
- [ ] Provide SSH access, known-hosts data, and credentials at runtime only.
- [ ] Keep private SSH keys, VPN keys, broker credentials, certificates, private signing keys, and other secrets out of the image.
- [ ] Keep hardware, gateway, UART, and broker tests capability-gated.
- [ ] Keep the default container workflow non-hardware.

Pass criteria:

- [ ] Gateway workflows are opt-in.
- [ ] No credentials are committed or baked into the image.
- [ ] Tests skip cleanly without gateway capability.
- [ ] No hardware, flashing, UART, broker, or MQTT/TLS success is claimed without explicit logs.

---

### Phase C6 — Optional CI Integration

Goal: Use the container as a reproducible non-hardware CI baseline after local container workflows are stable.

Outcomes:

- [ ] Build or reuse the project container image in CI.
- [ ] Run Python unit tests in CI.
- [ ] Run non-hardware build checks where toolchain availability permits.
- [ ] Exclude hardware, gateway, UART, and Wi-Fi-module tests from the default CI path.
- [ ] Keep CI free of committed, printed, or baked secrets.

Pass criteria:

- [ ] CI validates the containerised non-hardware baseline.
- [ ] Hardware and gateway tests are not run by default.
- [ ] No secrets are committed, printed, or baked into images.

---

## Phase M — MQTT/TLS Architecture Split and Non-Hardware Preparation

> **Historical goals and pass criteria only.** The checklist markers below have been converted to ordinary bullets so this document no longer acts as duplicate live MQTT status tracking. Use `docs/non_hardware_mqtt_tls_development_plan.md` for reconciled phase status and deferred-test references.

This phase family replaced the previous single-step assumption that MQTT/TLS firmware work starts only after Wi-Fi hardware is available. It keeps the target architecture unchanged: lwIP, wolfSSL, and wolfMQTT run on the STM32, while the ST67W61M1 Wi-Fi module is a future network-interface backend.

The phase family is evidence-bound. Build-only, fake transport, host-side, broker-side, STM32 runtime, and end-to-end wireless evidence must remain separate. Do not claim Wi-Fi, IP, TCP, TLS handshake, MQTT connect, publish, reconnect, latency, runtime memory, or end-to-end success without explicit logs, manifests, UART output, broker logs, or equivalent evidence for that exact claim.

Do not commit SSH private keys, VPN private keys, TLS private keys, MQTT passwords, real `.env` files, private certificates, private signing keys, wolfBoot private signing keys, generated signing material, tokens, or production credentials.

---

### Phase M1 — MQTT/TLS Architecture Split Without Wi-Fi Hardware

Goal: Update the MQTT/TLS roadmap and architecture documentation so MQTT/TLS development is explicitly split into hardware-independent and ST67W61M1-dependent phases.

Outcomes:

- Record that MQTT/TLS client development can proceed before the Wi-Fi module is installed or available.
- State that lwIP, wolfSSL, and wolfMQTT are intended to run on the STM32.
- State that the ST67W61M1 is a network-interface backend, not the TLS endpoint or MQTT client owner.
- Distinguish fake/no-network transport, host/socket validation, STM32 build-only preparation, STM32 fake/no-network runtime, and future ST67W61M1-backed validation.
- Separate build-only, fake transport, host-side, broker-side, STM32 runtime, and end-to-end wireless evidence categories.
- Avoid firmware, Docker, framework code, broker implementation, or test implementation changes in this phase.

Pass criteria:

- The roadmap no longer assumes Wi-Fi hardware is available before MQTT/TLS design work starts.
- STM32-local lwIP/wolfSSL/wolfMQTT ownership is explicit.
- Future implementation phases are small and evidence-bound.
- No MQTT, TLS, Wi-Fi, publish, latency, reconnect, or end-to-end success is claimed.

---

### Phase M2 — MQTT Configuration and Result Schema

Goal: Add framework-side configuration and result schema support for future MQTT/TLS experiments before firmware transport implementation.

Outcomes:

- Represent MQTT experiment configuration and validate invalid combinations.
- Represent transport backend selection.
- Represent TLS mode and certificate references where appropriate.
- Represent unavailable hardware/network metrics explicitly.
- Distinguish fake/no-network, host-side, STM32 build-only, STM32 runtime, and future ST67W61M1-backed evidence.
- Avoid STM32 firmware networking, lwIP integration, wolfSSL integration, wolfMQTT integration, broker deployment, and hardware tests in this sub-phase.

Pass criteria:

- MQTT/TLS configs validate.
- Invalid configs are rejected.
- Unavailable hardware/network metrics are represented explicitly.
- No network or hardware access is required.

---

### Phase M3 — Fake/No-Network MQTT Transport Harness

Goal: Provide deterministic non-network test coverage for MQTT client control-flow behaviour.

Outcomes:

- Add a fake/no-network transport mode for tests.
- Model connect success, connect failure, read timeout, write timeout, disconnect, and reconnect attempts.
- Label simulated evidence as fake transport evidence.
- Prevent fake transport results from being treated as real MQTT/TLS runtime success.
- Avoid broker, gateway, Wi-Fi module, UART, and STM32 hardware requirements.

Pass criteria:

- Fake transport outcomes are deterministic and testable.
- Simulated evidence is not confused with real broker, TLS, or STM32 runtime evidence.
- No hardware or network dependency is introduced.

---

### Phase M4 — Host-Side Broker Compatibility Validation

Goal: Validate MQTT/TLS broker compatibility separately from STM32 firmware and Wi-Fi hardware.

Outcomes:

- Use or extend the existing MQTT broker scaffold for host-side validation.
- Validate classical MQTT-over-TLS broker setup from a host-side client path where capability is available.
- Label validation evidence as host-side and broker-side only.
- Keep gateway/broker-dependent tests capability-gated.
- Avoid STM32, Wi-Fi module, lwIP-on-STM32, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless success claims.

Pass criteria:

- Broker validation remains capability-gated.
- Host/broker evidence is clearly separated from STM32 evidence.
- No Wi-Fi module is required.

---

### Phase M5 — STM32 lwIP Build-Only Skeleton

Goal: Introduce or validate STM32-local lwIP build integration without requiring the Wi-Fi module.

Outcomes:

- Build firmware with the intended lwIP structure or preparation layer.
- Keep the network interface absent, stubbed, or explicitly unavailable.
- Review generated-code impacts and preserve the CubeMX project layout unless a scoped inspected-file change requires otherwise.
- Record build-only status and unavailable runtime metrics.
- Avoid Wi-Fi join, IP address acquisition, TCP connection, TLS handshake, MQTT publish, and reconnect success claims.

Pass criteria:

- Firmware builds with the intended lwIP preparation.
- Runtime networking remains explicitly unavailable.
- No Wi-Fi hardware is required.

---

### Phase M6 — wolfSSL Build-Only Skeleton

Goal: Add or validate wolfSSL build integration for STM32 without performing a real TLS handshake.

Outcomes:

- Build and link firmware with wolfSSL or the planned wolfSSL integration boundary.
- Represent TLS configuration and certificate-handling boundaries.
- Preserve private-key and credential rules.
- Record TLS runtime metrics as unavailable until real transport evidence exists.
- Avoid real network transport, ST67W61M1 backend, MQTT publish, and hardware tests in this sub-phase.

Pass criteria:

- Firmware builds with the wolfSSL integration boundary.
- TLS runtime success is not claimed.
- Secret-handling rules are preserved.

---

### Phase M7 — wolfMQTT Build-Only Skeleton

Goal: Add or validate wolfMQTT build integration and bind it to an abstract transport boundary without requiring real networking.

Outcomes:

- Build and link firmware with wolfMQTT or the planned wolfMQTT integration layer.
- Represent MQTT client initialization separately from MQTT connection success.
- Isolate transport callbacks from MQTT client logic.
- Keep fake/no-network and future ST67W61M1 backends selectable without changing MQTT logic.
- Avoid broker connection, TLS handshake, publish, reconnect, Wi-Fi, and end-to-end success claims.

Pass criteria:

- Firmware builds with the wolfMQTT integration boundary.
- MQTT client logic is not tightly coupled to ST67W61M1 hardware.
- No broker or publish success is claimed.

---

### Phase M8 — STM32 Fake/No-Network Runtime Evidence

Goal: Run STM32 firmware on the existing board with a fake/no-network backend to validate initialization evidence before Wi-Fi hardware is available.

Outcomes:

- Emit explicit initialization and unavailable-backend markers where implemented.
- Label runtime output as fake/no-network mode where applicable.
- Require the STM32 board only, not the X-NUCLEO-67W61M1.
- Keep hardware tests capability-gated.
- Avoid Wi-Fi, IP, TCP, TLS handshake, MQTT connect, publish, reconnect, and end-to-end success claims.

Pass criteria:

- UART evidence confirms initialization or unavailable-backend markers.
- No Wi-Fi module is required.
- No network, TLS, MQTT, or publish success is claimed.

---

### Phase M9 — Host-Side wolfMQTT/wolfSSL Prototype or Validation Utility

Goal: Optionally validate MQTT/TLS semantics against the broker using wolfSSL and wolfMQTT on the host side while keeping the result separate from STM32 evidence.

Outcomes:

- Add host-side wolfSSL/wolfMQTT validation where supported.
- Label evidence as host-side only.
- Use results to inform later STM32 configuration without claiming STM32 runtime success.
- Keep broker/gateway-dependent validation capability-gated.

Pass criteria:

- Host-side MQTT/TLS validation is useful but clearly separated from STM32 evidence.
- No hardware or Wi-Fi module is required.
- No STM32 runtime success is claimed.

---

### Deferred Phase M10 — ST67W61M1 Network Interface Backend

Goal: Add the real Wi-Fi module backend once the X-NUCLEO-67W61M1 is installed and available.

Outcomes:

- Add the ST67W61M1 backend under the established transport/network-interface boundary.
- Keep STM32 responsible for lwIP, TLS, and MQTT.
- Validate module detection and network-interface bring-up separately from TLS and MQTT success.
- Keep hardware tests capability-gated.

Pass criteria:

- ST67W61M1 backend can be built and tested with real hardware.
- Evidence categories remain separated.
- No TLS/MQTT success is inferred from module or network-interface bring-up alone.

---

### Deferred Phase M11 — Classical MQTT over TLS on STM32

Goal: Validate actual STM32-to-broker MQTT-over-TLS with lwIP, wolfSSL, wolfMQTT, and the ST67W61M1 network interface.

Outcomes:

- Capture TLS handshake, MQTT connect, publish, reconnect, and relevant resource metrics from explicit evidence only.
- Record STM32 UART logs, broker logs, manifests, and repeat-run metrics where implemented.
- Keep private keys and credentials out of Git and generated replacement artifacts.
- Keep tests capability-gated.

Pass criteria:

- Explicit STM32 and broker evidence confirms classical MQTT-over-TLS.
- Metrics are captured without inference.
- Hardware-dependent tests remain opt-in.

---

### Deferred Phase M12 — Network Degradation

Goal: Evaluate MQTT/TLS behaviour under controlled network impairment after the real network path works.

Outcomes:

- Apply, verify, and clear network impairment profiles safely.
- Record the active network profile in results.
- Keep cleanup robust after failures.
- Keep gateway-dependent tests capability-gated.

Pass criteria:

- Network impairment setup and cleanup are reliable.
- Results are evidence-backed.
- No degraded-network result is inferred.

---

### Deferred Phase M13 — PQC/Hybrid MQTT/TLS Experiments

Goal: Add PQC or hybrid TLS experiments only after classical MQTT/TLS is stable and supported library capabilities are confirmed.

Outcomes:

- Confirm wolfSSL/wolfMQTT support before profiles are added.
- Add PQC/hybrid configs only for supported modes.
- Preserve comparable metrics with classical TLS runs.
- Document experimental limitations.

Pass criteria:

- Supported PQC/hybrid modes are confirmed.
- Profiles are evidence-backed.
- Experimental limitations are documented.

---

## Phase 16 — Add Analysis and Reporting Tooling

- Add script to aggregate result manifests and metrics:

  ```text
  scripts/analyse_results.py
  ```

- Produce CSV summaries:

  ```text
  results_summary.csv
  ```

- Produce charts later:
  - [ ] boot verification time
  - [ ] TLS handshake time
  - [ ] publish latency
  - [ ] success rate under packet loss
  - [ ] firmware size by crypto profile
  - [ ] RAM use by crypto profile

- Keep raw results immutable.

- Put derived summaries in a separate folder:

  ```text
  analysis/
  ```

- Update documentation.

- Update `AI_BUILD_GUIDE.md`.

- Commit.

---
