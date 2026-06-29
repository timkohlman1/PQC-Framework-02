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





Phase 10d — Automatic Reuse of Matching Builds

Goal: Let the framework reuse a previous matching build automatically when appropriate.

Scope:

Detect whether an existing build record matches the current source/build hash.
Reuse a matching build when allowed by the command behavior.
Create a new build when no matching build exists.
Preserve explicit forced rebuild behavior.
Record whether the run used a reused build or a newly created build.
Add unit tests for automatic reuse, no matching build, forced rebuild, and stale artifact cases.
Update documentation and AI_BUILD_GUIDE.md.

End state: Routine experiment runs can avoid unnecessary rebuilds while retaining full provenance.




Phase 10e — Clean Up Build/Run Terminology and CLI

Goal: Make the user-facing workflow consistent after build/run separation.

Scope:

Ensure command names, help text, manifest fields, documentation, and tests use consistent terminology:
build record
experiment run
build number
run ID
reused build
forced build
Remove or deprecate ambiguous fields where safe.
Preserve backward compatibility where needed.
Update README, architecture docs, and AI_BUILD_GUIDE.md.

End state: The framework has a clean distinction between build artifacts and experiment evidence.








## Phase 10 — Start Boot-Security Experiments

- [ ] Add boot mode config:

  ```text
  configs/boot/direct_flash.yaml
  ```

- [ ] Refactor baseline experiment to reference that boot config.

- [ ] Add planned config:

  ```text
  configs/boot/wolfboot_ecdsa_p256.yaml
  ```

- [ ] Do not implement wolfBoot until ready.

- [ ] Inspect wolfBoot STM32 target support.

- [ ] Choose or adapt the closest STM32L4 target.

- [ ] Define flash layout.

- [ ] Use initial working assumption only if appropriate:

  ```text
  0x08000000  wolfBoot
  0x08020000  signed application
  ```

- [ ] Relocate the HAL app linker script.

- [ ] Set vector table offset.

- [ ] Build relocated app.

- [ ] Build wolfBoot with ECDSA-P256.

- [ ] Generate signing keypair.

- [ ] Keep private signing key out of Git.

- [ ] Sign application image.

- [ ] Flash wolfBoot plus signed app.

- [ ] Confirm UART boot marker.

- [ ] Add negative test: corrupted app should not boot.

- [ ] Add boot timing instrumentation.

- [ ] Record in manifest:
  - [ ] `boot_mode`
  - [ ] `boot_crypto`
  - [ ] `signature_size`
  - [ ] `verification_time_ms`

- [ ] Update documentation.

- [ ] Update `AI_BUILD_GUIDE.md`.

- [ ] Commit at each working sub-step.

---

## Phase 11 — Add MQTT Plain Baseline

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

## Phase 12 — Add Classical MQTT over TLS

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

## Phase 13 — Add Network Degradation

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

## Phase 14 — Add PQC/Hybrid Transport Experiments

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

## Phase 15 — Add Analysis and Reporting Tooling

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

## Immediate Next Actions

- [ ] Finish `.gitignore`.
- [ ] Commit the STM32 HAL baseline.
- [ ] Create `AI_BUILD_GUIDE.md`.
- [ ] Create the docs skeleton.
- [ ] Create the ChatGPT Project instruction prompt.
- [ ] Commit documentation.
- [ ] Add `configs/`, `scripts/`, and `tests/`.
- [ ] Implement `experiment.py status`.
- [ ] Add unit tests for config loading.
- [ ] Add manifest creation.
- [ ] Add unit tests for manifest creation.
- [ ] Only then automate build, flash, and UART capture.

## Current Rule

Do not start wolfBoot, MQTT, TLS, PQC, or network impairment until the baseline framework exists and has tests.
