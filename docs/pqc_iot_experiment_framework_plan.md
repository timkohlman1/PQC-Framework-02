# PQC IoT Experiment Framework — Step-by-Step Plan

This checklist tracks the staged development of the STM32-based PQC IoT experiment framework. The project is broader than wolfBoot: it will eventually cover secure boot, MQTT, TLS, classical crypto, PQC/hybrid crypto, network degradation, benchmarking, result capture, documentation, and tests.

## Phase 0 — Freeze the Known-Good STM32 Baseline

## Phase 1 — Establish Documentation and AI Workflow

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




## Phase ??? — Containerised Build and Test Environment

### Goal

Provide a portable container-based development environment so the framework's build, signing, and non-hardware test workflows can be reproduced consistently across Windows, Linux, and macOS hosts.

The initial scope should focus on build and software verification portability. Hardware flashing and UART workflows may be supported later through the existing gateway abstraction, but should not be required for the first container milestone.

### Requirements / Outcomes

- Add a project-owned container build environment for the STM32 framework.
- Ensure a fresh checkout from Git, including required submodules, can run the documented container workflow.
- Support the core non-hardware development commands inside the container, including:
  - Python unit tests
  - configuration/status checks
  - direct-flash firmware build
  - relocated firmware build
  - wolfBoot build
  - application signing
- Keep hardware-dependent workflows separate from the default container workflow.
- Do not require USB/ST-LINK passthrough for the initial container environment.
- Do not bake private keys, SSH keys, VPN keys, credentials, signing keys, or other secrets into the container image.
- Document how local-only secrets and generated signing material are handled when container workflows need them.
- Preserve the existing host/gateway flashing and UART architecture.
- Ensure generated build artifacts, object files, signing outputs, and result directories remain out of Git.
- Add documentation describing:
  - supported host platforms
  - expected Docker or container runtime prerequisites
  - commands to build or run the container
  - which workflows are supported inside the container
  - which workflows remain host/gateway/hardware dependent
  - known limitations and reproducibility assumptions
- Add tests or verification commands proving that the container can run the intended non-hardware workflow from a clean checkout.

### Optional Later Extension

Add an explicitly enabled hardware-capable container workflow that can use the existing SSH gateway abstraction to run flash and UART tests, without requiring direct USB/ST-LINK access from the container.

This extension should:

- mount or provide SSH access at runtime only
- avoid storing SSH private keys in the image
- preserve the existing `pqc-gateway1` flash and UART helper model
- run hardware tests only when the gateway and board are intentionally available
- keep hardware tests skipped or unavailable by default when prerequisites are missing

### Pass Criteria

- A developer on Windows, Linux, or macOS can clone the repository and run the documented container workflow for non-hardware development.
- The container can run Python unit tests successfully.
- The container can build the direct-flash firmware profile.
- The container can build the relocated firmware profile.
- The container can run the wolfBoot build workflow when the wolfBoot submodule and required tools are available.
- The container can run the application signing workflow without committing or baking private signing keys into the image.
- Hardware flashing and UART capture remain optional and are not required for the default container pass criteria.
- Documentation clearly distinguishes build/test portability from hardware evidence collection.

### Not in Scope for Initial Container Phase

- Replacing the existing gateway flash workflow.
- Replacing the existing UART capture workflow.
- Running ST-LINK USB directly from inside the container.
- Baking private credentials, SSH keys, signing keys, or generated secrets into the image.
- Treating containerised hardware tests as mandatory for normal development.
- Changing secure-boot flash layout, signing format, UART markers, or experiment semantics.

---

