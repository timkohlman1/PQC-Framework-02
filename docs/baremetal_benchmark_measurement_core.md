# STM32 pre-scheduler wolfCrypt benchmark (Request 1)

This is the project-owned operational description for the dedicated bare-metal
cryptographic measurement phase. The definitive framework capability/evidence
matrix and deferred tests remain in `docs/007_framework_architecture.md`.

## Execution and clock policy

`baremetal_benchmark` runs after STM32 HAL clock/peripheral setup and the wolfSSL
allocator has been configured, but before `osKernelInitialize()` and before any
Wi-Fi, lwIP, MQTT, or TLS application workload. During each primitive operation
it saves PRIMASK, disables configurable interrupts, reads DWT CYCCNT, invokes
exactly one wolfCrypt public API, reads DWT CYCCNT, and restores the saved
PRIMASK. NMI and HardFault are not masked. Cycle reads and function-call
bookkeeping remain part of the measured cost. The 32-bit DWT counter is reset
and enabled before the first operation; candidate readings of zero or more than
2^31-1 cycles are marked invalid. An operation that silently traverses a full
2^32 counter revolution cannot be distinguished by the 32-bit API; hardware
validation must reject such profiles rather than treat them as observations.

The primary quantity is raw cycles. The effective HCLK is recorded as provenance
for optional cycle/time conversion, not used to normalize the raw result. Raw
cycle counts from differing cryptographic implementations, compiler flags,
interrupt policies, RNG paths, processor revisions, and operation boundaries
must **not** be described as directly equivalent PQM4 measurements.

## Supported and unavailable operations

Three resolved firmware identities select ML-KEM-512, ML-KEM-768 or ML-KEM-1024.
Each image measures its selected ML-KEM key generation, encapsulation and
 decapsulation, SHA-256 over 32 public bytes, and ML-DSA-65 key generation,
contextless signing and verification. Each image retains ten repetitions of
each operation. The six non-selected ML-KEM operations appear exactly once
as explicit `algorithm_not_compiled` records, never as zero-time samples.
RSA, ECC, energy and memory measurements are not part of Request 1's original
selected-operation acceptance criteria; they are not presented as measured.

The two KEM deterministic APIs and ML-DSA seed-based keygen/signing APIs use
fixed public *benchmark-only* seeds. They exclude entropy acquisition; neither
benchmarked key material nor these cycles represent production RNG-driven
operations. SHA-256 digest, KEM shared-secret equality and ML-DSA signature
verification are checked. Failed checks/return codes invalidate samples.
The benchmark-only 160 KiB static arena recycles and coalesces freed scratch
blocks while the ML-DSA key remains live. Freed payloads are zeroed; no
FreeRTOS allocation is performed in the pre-scheduler phase. Exhausting
simultaneously live arena capacity remains an operation failure, not an
implicit fallback to the regular application heap. Each ML-DSA repetition
releases its key before the arena is reset.
The ML-DSA keygen window includes key derivation, signing window includes
signature generation, and verification window includes verification; setup,
report formatting and network transport are outside these windows.

The 96-record measurement store can retain 76 records per image: 70 successful
selected-operation samples and six explicit unavailable records. The existing
32 KiB result buffer is retained; failure to append any measurement or the
completion record is an explicit test failure, not an acceptable partial result.
Ten observations are a minimum run-level diagnostic, **not** a statistical
power guarantee or a substitute for independent experiment repetitions.
The standard impairment-exempt reporting path remains unchanged.

## Reproducibility and execution

`configs/campaigns/baremetal_benchmark.yaml` resolves three firmware identities,
one per ML-KEM parameter set. `configs/workloads/baremetal_benchmark.yaml`
sets `operations_per_run: 10`. The framework's existing build provenance includes
the parent revision, wolfSSL submodule identity and final ELF hash, while raw
benchmark provenance specifies HCLK, DWT, interrupt policy, allocator and seed
policy. Neither generated-state nor manifest captures are a scientific metric
database; measured values stay in the retained raw STM32 stream.

From the Linux repository root:

```bash
./scripts/dev.sh python scripts/resolve_campaign.py baremetal_benchmark.yaml
./scripts/dev.sh pytest tests/unit/test_baremetal_benchmark.py tests/unit/test_baremetal_benchmark_integration.py tests/unit/test_baremetal_benchmark_summary.py tests/unit/test_baremetal_benchmark_allocator.py
./scripts/dev.sh pytest tests/unit
./scripts/dev.sh pytest tests/integration -m integration
./scripts/dev.sh pytest-hardware tests/hardware/test_baremetal_benchmark_hw.py -m hardware --pqc-require-hardware
```

Hardware validation is **not established** until logs, final manifests and
retained per-parameter raw streams demonstrate that selected keygen,
encapsulation, decapsulation and SHA-256 returned successful, non-zero cycle
samples, the collector validated one complete logical stream, and the
benchmark-to-reporting transition did not overwrite the raw records.

The self-contained hardware test produces three independent completed experiment
streams. To validate stream hashes/counts and derive descriptive statistics
**after** that test, supply its printed evidence directory:

```bash
./scripts/dev.sh python scripts/benchmark_summary.py "<repository-relative hardware evidence directory>" --output results/benchmark-summary.json
```

The summary refuses missing samples, incorrect unavailable records, failed
cryptographic outcomes, zero/overflow cycle readings, missing iterations, or
incomplete/hash-mismatched result streams. Its min/mean/median/max/sample
standard deviation are descriptive statistics for ten deterministic-seed
repetitions, not confidence intervals or cross-implementation speed ratings.
The baseline TLS/MQTT hardware regression remains a separate strict gate:

```bash
./scripts/dev.sh pytest-hardware tests/hardware/test_tls_handshake_repeat_hw.py -m hardware --pqc-require-hardware -v -s
```
