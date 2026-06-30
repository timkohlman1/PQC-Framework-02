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

# Phase 11 — Secure-Boot Benchmark Metrics and Repeated-Run Support

## 11.1 Purpose

Phase 11 extends the PQC IoT experiment framework so wolfBoot secure-boot benchmarks can compare classical signing algorithms using repeatable, statistically meaningful, and resource-aware measurements.

The framework already records secure-boot verification timing evidence from explicit firmware/UART markers. Phase 11 extends the benchmark evidence model so each signing profile can also record memory/resource metrics, artifact-size metrics, repeated-run measurements, and aggregated statistics.

This phase is focused on classical wolfBoot signing-algorithm benchmarking only.

PQC and hybrid signing algorithms are out of scope for Phase 11.

## 11.2 Rationale

The current framework can measure image verification time in milliseconds and CPU cycles. These are important, but they are not sufficient for selecting a signing algorithm on Arm Cortex-M4 hardware.

For Cortex-M4 secure boot, the relevant trade-off includes:

- verification latency
- CPU cycle cost
- bootloader flash footprint
- static RAM usage
- runtime stack usage
- signed-image size overhead
- signature size
- repeatability of measurements
- failure/pass consistency across runs

Memory metrics and repeated-run support should be added before running the full signing-algorithm benchmark. If timing-only algorithm benchmarks are run first, the same experiments may need to be repeated later to collect comparable memory and statistical data.

## 11.3 Recommended Phase 11 Order

Phase 11 should be implemented in the following order:

1. Define the benchmark result model.
2. Add repeated-run measurement support.
3. Add static build/resource metrics.
4. Add runtime stack/memory metrics.
5. Add classical signing-algorithm benchmark profiles.
6. Add benchmark aggregation output.
7. Update documentation and tests.

The signing-algorithm profiles should not be added before the benchmark result model is stable.

## 11.4 Phase 11.1 — Benchmark Result Model

Define the manifest fields and result structure needed for secure-boot benchmark runs before adding new algorithm profiles.

The result model should distinguish between:

- build-time metrics
- signed-artifact metrics
- runtime verification metrics
- repeated-run samples
- aggregate statistics
- limitations or unavailable metrics

Expected outcomes:

- The framework has a stable schema for benchmark evidence.
- Existing secure-boot timing fields remain compatible.
- Missing metrics are recorded explicitly as unavailable rather than inferred or omitted.
- The manifest remains the source of truth for what was measured.

## 11.5 Phase 11.2 — Repeated-Run Measurement Support

Add support for executing the same benchmark profile multiple times and recording one measurement sample per run.

Each sample should capture:

- run index
- verification time in milliseconds
- verification cycles
- verification CPU frequency
- verification result code
- UART marker detection result
- pass/fail verdict for that sample
- timestamp
- referenced build or artifact identity

The framework should calculate aggregate statistics across valid samples.

Minimum aggregate statistics:

- sample count
- valid sample count
- failed sample count
- minimum
- mean
- median
- maximum
- standard deviation

Primary headline metrics should use the median rather than a single run.

Expected outcomes:

- A signing profile can be benchmarked over multiple verification runs.
- Timing and cycle results are statistically meaningful.
- Outliers are visible rather than hidden.
- Failed samples do not silently contaminate timing statistics.

## 11.6 Phase 11.3 — Static Build and Resource Metrics

Add build-level metrics that do not require additional firmware runtime instrumentation.

These metrics should be associated with the wolfBoot build record, the benchmark profile, or both.

Required metrics:

- bootloader ELF size
- `.text` size
- `.data` size
- `.bss` size
- total flash-relevant size
- static RAM usage estimate from `.data + .bss`
- retained wolfBoot artifact size
- unsigned application artifact size, where available
- signed application artifact size
- size overhead in bytes
- size overhead percentage

Expected outcomes:

- Each algorithm profile records its bootloader flash footprint.
- Each profile records static RAM pressure.
- Signed-image overhead is visible.
- Algorithm comparisons are not limited to timing only.

## 11.7 Phase 11.4 — Runtime Stack and Memory Metrics

Add runtime memory evidence after static build/resource metrics are in place.

Required runtime metric:

- maximum stack high-water mark during verification, where available

Optional runtime metrics:

- heap usage, only if heap is actually used and can be measured reliably
- estimated total RAM pressure, calculated as static RAM plus measured stack high-water mark

Important requirements:

- Runtime stack and heap values must come from explicit firmware-side measurement evidence.
- Runtime memory values must not be inferred from host-side timing, UART capture duration, reset delay, or build output alone.
- If a runtime memory metric is unavailable, the manifest must record it as unavailable and include a limitation note.

Expected outcomes:

- The benchmark can compare runtime RAM pressure between EdDSA, ECDSA, and RSA profiles.
- Stack-heavy algorithms or wolfCrypt configurations become visible.
- The framework avoids unsupported memory claims.

## 11.8 Phase 11.5 — Classical Signing-Algorithm Benchmark Profiles

After the metrics and repeated-run model are in place, add experiment, build, and signing profiles for the classical signing algorithms.

Recommended full profile set:

- `ED25519`
- `ED448`
- `ECC256`
- `ECC384`
- `ECC521`
- `RSA2048`
- `RSA4096`

Alternative profile set if scope needs to be reduced:

- `ED25519`
- `ECC256`
- `ECC384`
- `RSA2048`
- `RSA3072`
- `RSA4096`

Minimum practical comparison set:

- `ED25519`
- `ECC256`
- `RSA2048`

Expected outcomes:

- Each profile can build wolfBoot with a defined signing algorithm.
- Each profile can sign the same application payload.
- Each profile can run through the same benchmark workflow.
- Results are comparable because the image payload, board, clock speed, measurement method, and run count are controlled.

## 11.9 Phase 11.6 — Benchmark Aggregation Output

Add a framework output that aggregates results across signing profiles.

The aggregation should produce machine-readable summary files such as:

- `benchmark_summary.json`
- `benchmark_summary.csv`

Required summary fields:

- profile ID
- signing algorithm
- curve or key size
- sample count
- valid sample count
- failed sample count
- median verification time
- mean verification time
- minimum verification time
- maximum verification time
- verification time standard deviation
- median verification cycles
- mean verification cycles
- minimum verification cycles
- maximum verification cycles
- verification cycles standard deviation
- cycles per KB
- bootloader flash size
- static RAM size
- maximum stack usage, where available
- signed-image size
- signature size, where available
- size overhead bytes
- size overhead percentage
- final profile verdict
- limitations

Expected outcomes:

- Results can be compared across all signing algorithms without manually opening each run manifest.
- The CSV output can be used for charts.
- The JSON output can preserve richer structured evidence.

## 11.10 Phase 11.7 — Documentation and Tests

Update project documentation and tests in the same change.

Documentation updates should cover:

- benchmark purpose
- supported metrics
- repeated-run model
- difference between build metrics and runtime metrics
- interpretation of timing, cycles, flash, RAM, stack, and size overhead
- limitations of unavailable metrics
- how benchmark profiles should be compared

Testing requirements:

- Unit tests must not require hardware.
- Unit tests should validate metrics schema creation.
- Unit tests should validate aggregation calculations.
- Unit tests should validate unavailable-metric handling.
- Unit tests should validate manifest updates.
- Hardware tests should remain separate.
- Hardware tests should skip cleanly when required capabilities are unavailable.
- Existing known-good direct-flash baseline behaviour must not be broken.
- Existing secure-boot workflow behaviour must not be broken.

Expected outcomes:

- The feature is documented.
- The result model is test-covered.
- Hardware-dependent benchmark collection remains isolated from unit tests.
- The framework remains safe to run without connected STM32 hardware unless a hardware benchmark is explicitly invoked.

## 11.11 Required Benchmark Metrics

### 11.11.1 Runtime Verification Metrics

Each valid verification sample should record:

- `verification_time_ms`
- `verification_cycles`
- `verification_cpu_hz`
- `verification_result_code`
- `verification_time_source`
- `verification_cycles_source`
- `sample_verdict`

### 11.11.2 Build and Resource Metrics

Each profile should record:

- `bootloader_text_bytes`
- `bootloader_data_bytes`
- `bootloader_bss_bytes`
- `bootloader_flash_bytes`
- `bootloader_static_ram_bytes`
- `wolfboot_elf_size_bytes`
- `unsigned_application_size_bytes`
- `signed_application_size_bytes`
- `signed_image_overhead_bytes`
- `signed_image_overhead_percent`

### 11.11.3 Runtime Memory Metrics

Where available, each profile should record:

- `max_stack_used_bytes`
- `stack_metric_source`
- `heap_used_bytes`, if applicable
- `heap_metric_source`, if applicable
- `runtime_memory_limitations`

### 11.11.4 Derived Metrics

The framework should calculate:

- `cycles_per_kb`
- `time_ms_per_kb`
- `static_ram_bytes`
- `estimated_total_ram_pressure_bytes`, only when stack evidence is available

Definitions:

```text
cycles_per_kb = verification_cycles / (image_size_bytes / 1024)

time_ms_per_kb = verification_time_ms / (image_size_bytes / 1024)

static_ram_bytes = data_bytes + bss_bytes

estimated_total_ram_pressure_bytes = static_ram_bytes + max_stack_used_bytes

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

