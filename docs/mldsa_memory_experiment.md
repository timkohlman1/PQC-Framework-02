# ML-DSA memory-option side experiment

The default remains unchanged until this comparison is analysed. P-256 key
establishment, ML-DSA-65 credentials, baseline network, 200 KiB payload and
400-byte chunks are fixed. Server mode compares default and small verification
(10 fixed attempts each). Mutual mode compares default, small verification,
small signing and both (30 fixed attempts each, informed by existing signing
variability). These are pilots, not precision guarantees.

The mldsa_memory_mode choice enters configuration/firmware identity, compiler
definitions and retained TLS controls. Omitted settings preserve previous case
identities. Nondefault settings require ML-DSA; signing requires mutual mode.
The broker credentials, RNG, energy and allocation-tracing settings do not change.

Keep the 96 KiB heap and 96 KiB scratch reservation fixed initially. Normal modes
route ML-DSA requests of at least 32 KiB to the scratch arena.
Small-memory modes lower that routing threshold to 8 KiB, keeping their smaller
contiguous scratch blocks out of the shared heap. The arena size and single-user
exclusion remain unchanged; this adapter policy is part of the tested variant.
A zero workspace request does not mean RAM disappeared. Compare handshake
distributions, sign/verify phases, heap peak/minimum free, stack watermarks,
largest scratch request, configured Flash/RAM and failures. Retain every attempt.
Use fresh same-source defaults, not pooled historical captures.

After the pilot, inspect ordering/drift and failures. For a promising setting,
run separate allocation-provenance diagnostics and smaller-reservation validation.
Trace output can perturb latency and must not join normal timing samples.
Select a default against explicit RAM/latency budgets. No production-sized
reservation or automatic default change is part of this pilot.

Commit 5901d0f introduced the contiguous-allocation workaround. The existing
PQC_WOLFSSL_ALLOCATION_PROVENANCE option records size/type/call site and route.
Small-memory sign/verify branches reduce scratch storage. WOLFSSL_SMALL_STACK
alone shifts storage to heap; dynamic key allocation does not split scratch
across noncontiguous banks. Vendor benchmarks do not substitute for target data.

Validation commands (framework root):
    ./scripts/dev.sh pytest tests/unit/test_mldsa_memory_options.py
    ./scripts/dev.sh pytest-hardware tests/hardware/test_mldsa_memory_options_hw.py

Copy the two campaign templates into results/profiles and enqueue through the
normal host queue. Qualification attempts remain separate from the pilot.

Initial qualification with the unchanged 32 KiB routing passed both server
variants and default mutual mode, but failed all three small-memory mutual modes.
The separately retained full-UART verification diagnostic recorded FreeRTOS
allocation failure after association/DHCP and workload start. Do not pool those
attempts with the adjusted-routing pilot or treat them as TLS algorithm failures.
Fresh qualification with the 8 KiB threshold passed all six variants on
14 October 2026 (four mutual, two server), including accepted captures, completed
workloads and return code zero. Qualification is separate from the fixed-count
pilot and does not establish distribution precision or a reduced pool capacity.
