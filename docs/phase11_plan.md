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
