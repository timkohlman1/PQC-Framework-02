# PQC IoT Experiment Framework — Step-by-Step Plan

This checklist tracks the staged development of the STM32-based PQC IoT experiment framework. The project is broader than wolfBoot: it will eventually cover secure boot, MQTT, TLS, classical crypto, PQC/hybrid crypto, network degradation, benchmarking, result capture, documentation, and tests.

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

## Phase 12 — Add MQTT Plain Baseline

- [ ] Add simple MQTT firmware variant.

- [ ] Add broker configuration on `pqc-gateway1`.

- [ ] Add transport config:

  ```text
  configs/transport/mqtt_plain.yaml
  ```

- [ ] Add experiment config:

  ```text
  configs/experiments/mqtt_plain_baseline.yaml
  ```

- [ ] Capture:
  - [ ] connect success
  - [ ] publish success
  - [ ] publish latency
  - [ ] reconnect behaviour
  - [ ] UART logs
  - [ ] broker logs where useful

- [ ] Save metrics:

  ```text
  results/<run_id>/metrics.json
  ```

- [ ] Add tests for:
  - [ ] MQTT config parsing
  - [ ] result schema

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 13 — Add Classical MQTT over TLS

- [ ] Add wolfSSL classical TLS firmware profile.

- [ ] Add certificate handling.

- [ ] Commit only:
  - [ ] public CA certificates where appropriate
  - [ ] example configs
  - [ ] documentation

- [ ] Keep private keys in local secrets only.

- [ ] Add transport config:

  ```text
  configs/transport/mqtt_tls_classic.yaml
  ```

- [ ] Capture:
  - [ ] TLS handshake time
  - [ ] MQTT connect time
  - [ ] first publish time
  - [ ] repeat publish latency
  - [ ] RAM usage if available
  - [ ] firmware size
  - [ ] network bytes if available

- [ ] Add result metrics schema.

- [ ] Add repeat-run support.

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 14 — Add Network Degradation

- [ ] Add network profile configs:

  ```text
  configs/network/normal.yaml
  configs/network/latency_50ms.yaml
  configs/network/loss_1pct.yaml
  configs/network/jitter_20ms.yaml
  ```

- [ ] Add Linux `tc netem` wrapper on `pqc-gateway1`.

- [ ] Add setup and cleanup behaviour:
  - [ ] apply impairment before run
  - [ ] verify impairment active
  - [ ] run experiment
  - [ ] clear impairment after run
  - [ ] verify impairment cleared

- [ ] Make cleanup robust even if the experiment fails.

- [ ] Add unit tests for generated `tc` commands.

- [ ] Add opt-in integration tests for applying and clearing network impairment.

- [ ] Record network profile in manifest.

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 15 — Add PQC/Hybrid Transport Experiments

- [ ] Verify selected wolfSSL version.

- [ ] Confirm supported PQC/hybrid options.

- [ ] Add build profiles for PQC/hybrid TLS only after support is confirmed.

- [ ] Add transport configs:

  ```text
  configs/transport/mqtt_tls_pqc.yaml
  configs/transport/mqtt_tls_hybrid.yaml
  ```

- [ ] Capture the same metrics as classical TLS:
  - [ ] firmware size
  - [ ] RAM use
  - [ ] handshake time
  - [ ] MQTT connect time
  - [ ] publish latency
  - [ ] success/failure under degraded networks
  - [ ] reconnect behaviour

- [ ] Add comparison scripts later.

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---

## Phase 16 — Add Analysis and Reporting Tooling

- [ ] Add script to aggregate result manifests and metrics:

  ```text
  scripts/analyse_results.py
  ```

- [ ] Produce CSV summaries:

  ```text
  results_summary.csv
  ```

- [ ] Produce charts later:
  - [ ] boot verification time
  - [ ] TLS handshake time
  - [ ] publish latency
  - [ ] success rate under packet loss
  - [ ] firmware size by crypto profile
  - [ ] RAM use by crypto profile

- [ ] Keep raw results immutable.

- [ ] Put derived summaries in a separate folder:

  ```text
  analysis/
  ```

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit.

---
