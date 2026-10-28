# Experiment configuration and campaign execution

This reference owns profile composition, execution identities and orchestration
semantics. Use the [operating guide](005_remote_flash_workflow.md) for command
sequences and diagnostics, the [queue guide](014_campaign_queue.md) for controls,
and the [architecture](007_framework_architecture.md) for component boundaries.

## Configuration sources

`ConfigResolver` in `scripts/framework/config_resolver.py` resolves versioned
profiles. `scripts/resolve_campaign.py` materializes deterministic derivative
cases under `.pqc-generated-state/campaigns/<campaign>/cases/`.

| Directory under `configs/` | Owns |
|---|---|
| `targets/` | MCU, interface/build defaults and shared wolfBoot target/layout |
| `gateways/` | Gateway identity, SSH endpoint and hardware helpers |
| `instruments/` | Selected external acquisition capabilities |
| `services/` | Separate experiment and reporting services |
| `workloads/` | Registered application and workload parameters |
| `tls_kex/` | TLS named group and required algorithm capabilities |
| `tls_auth/` | Certificate hierarchy and authentication family |
| `secure_boot/` | Algorithm-specific wolfBoot, packaging and tuple selection |
| `network_conditions/` | Configured rate, RTT, loss and MTU |
| `campaigns/` | Case matrix and execution policy |
| `benchmarks/`, `analysis/` | Benchmark aggregation and offline report/collection declarations |

Source campaign YAML is declarative. Generated cases are the operational inputs
to `experiment.py`; they retain profile IDs/content hashes, resolved choices,
configuration identity and firmware identity. Consumption rechecks source profile
hashes and refuses stale resolution. Do not edit generated cases as a substitute
for changing their canonical inputs.

The current implementation retains named Wi-Fi environment references in cases
and resolves values from the caller environment or ignored `.env` at execution.
Logs/provenance redact these fields; this is current behavior, not a confidentiality
requirement under the [open-data policy](006_security_and_secrets.md).
The wrapper imports only
`PQC_WIFI_SSID` and `PQC_WIFI_PSK`, respects caller values and scopes imports to its
Docker invocation. TLS certificates are an explicit offline prerequisite under
`secrets/certificates/<profile-id>/`; experiments consume them without renewal.
See [broker operations](../experiment/mqtt-broker/README.md) and
[open-data policy](006_security_and_secrets.md).

## Independent selections

TLS key exchange, certificate family, server/mutual authentication, firmware
signing, firmware mode and workload are independent within resolver validation.
The catalog includes classical, hybrid ML-KEM and standalone ML-KEM TLS groups.
Standalone groups must not silently resolve to hybrids. Runtime evidence must
confirm the negotiated group; a selected compile option does not prove a handshake.

The secure-boot catalog includes `integrity_sha256`, ECDSA P-256/P-384/P-521,
Ed25519/Ed448, RSA-2048/3072/4096 and ML-DSA-44/65/87. Profile files own precise
sizes and algorithm flags. The target owns the common 12 KiB header reserve and
layout. `render_wolfboot_config()` produces the effective wolfBoot `.config`.
A generated case carries its secure-boot selection into execution; a conflicting
explicit selection fails before hardware side effects. Integrity-only verifies
a digest and requires no signing key.

| Workload profile | Firmware application | Measurement/execution boundary |
|---|---|---|
| `baseline` | `baseline` | Retained profile, not a registered CMake application; the `baseline` campaign selects `ready_metrics` |
| `mqtt_validation` | `mqtt_validation` | Bounded protocol/correlation exchange |
| `ready_metrics` | `mqtt_ready_metrics` | Shared connection/workload measurement and deferred reporting |
| `ready_metrics_2` | `mqtt_ready_metrics_2` | Request and first/final payload checkpoints; default 204800 bytes in 400-byte chunks |
| `tls_handshake_repeat` | `tls_handshake_repeat` | Fresh TCP/TLS context/session per iteration, no supplied resumption session |
| `baremetal_benchmark` | `baremetal_benchmark` | Pre-scheduler primitive cycles; [dedicated measurement contract](baremetal_benchmark_measurement_core.md) |

Plaintext is supported for validation and both Ready Metrics applications.
TLS selectors retained in plaintext schema compatibility fields are inert;
analysis reports TLS as not applicable. Repeated-handshake and bare-metal profiles
are not plaintext application comparisons. CMake selects one registered workload
source and refuses unknown identifiers.

Payload and chunk sizes can vary through dotted campaign matrix dimensions
`workload.transfer.payload_bytes` and `workload.transfer.chunk_bytes`.
`uart_output_mode`, `boot_uart_diagnostics` and `boot_stack_profiling` affect
firmware identity and interpretation. Instrument selection and
`energy_monitoring` determine acquisition requirements, not measured energy.
Queue/collection planning defaults to `off` and requires an explicit `auto` policy
for instrumented acquisition. Direct campaign execution uses its resolved instrument
selection; use the queue planner when applying its acquisition policy.

## Preparation and repetition

`scripts/run_campaign.py` orchestrates `scripts/experiment.py`. Policy validation
occurs before hardware actions. Cases group by build-affecting firmware identity,
then by network condition. Preparation runs with baseline network settings and
binds runtime reuse to a finalized preparation manifest and exact firmware hash.
The resolver identity is a grouping key, not artifact provenance by itself.

Each repetition owns a distinct finalized run, reporting acquisition, optional
UART, PCAP and broker evidence. Compatible brokers may remain running, but they
are health/readiness checked before reuse. The reporting broker is separate.
A condition may persist across its repetitions; both directional qdiscs, IFB
redirection and MTUs are verified before/after attempts. Network-condition cleanup
precedes broker shutdown, including interruption and failure paths.

Outer campaign repetitions are independent execution attempts, not the
`handshakes_per_run` iterations of one repeated-TLS workload. Hardware reset is
required when the workload declares it; no-reset execution is accepted only for
compatible workloads. The repeated-TLS workload publishes each completed epoch
between measurements and stops later iterations when state isolation or reporting
can no longer be trusted.

`campaign-manifest.json` records expansion, preparation references, attempts,
condition events and cleanup. A finalized run uses the capture/provenance contract
in [results and analysis](012_results_and_analysis.md), not a campaign-level
substitute for raw device evidence.

## Failure, resume and queue behavior

Runtime failures and rejected captures remain failed attempts while later slots
continue. Preparation/broker setup failure blocks unstarted slots in that firmware
group; later groups can proceed after successful cleanup. Condition verification,
cleanup uncertainty and interruption stop execution. `completed_with_failures`
retains counts and exits nonzero after the matrix and cleanup; a failed runtime
attempt and a blocked slot with no runtime capture are distinct.

Resume requires matching source/resolution and validated retained captures.
Groups with pending work restore firmware through the normal build/sign/flash
preparation path; an old preparation does not establish what is currently on the
board. This is restoration, not readback attestation. Ordinary campaign resume
revalidates against its current preparation identity. Queue preservation mode
validates completed slots against their original retained preparation/hash and
keeps new attempts tied to the new image. Broker and impairment state are always
re-established.

`scripts/run_queue.py` owns host SQLite queue state and the terminal UI;
`scripts/queue_workspace.py` performs Docker-side planning/export. Tracked campaigns
are read-only UI templates. Editable profiles live in ignored `results/profiles/`.
Enqueueing freezes original/effective YAML and hashes in the job plan; later profile
edits affect future jobs only. Source drift and plan tampering are refused.

Cooperative pause completes the current operation, cleans up shared resources and
records `paused` without a terminal final index. Capture timeouts cover MQTT
publishers/subscribers and the entire remote process group, with a local SSH
deadline. Evidence/control commands are bounded separately. Campaign streaming
has a 30-minute fallback watchdog and 90-second interrupt/kill grace; watchdog
activation or unverified remote cleanup is unsafe and halts dispatch.
`tests/integration/test_operation_timeout_in.py` exercises local disposable
processes, not every remote-disconnection or Docker-daemon failure. Remaining
remote-fault qualification is tracked by DTR-CAPTURE-DEADLINE in the testing register.

Operator acceptance of failed/blocked slots records a decision without relabelling
the outcome. Explicit retry preserves prior attempt history. `--defer-failed`
preserves unresolved slots without claiming success. The opt-in
`workload_failures: record` policy accepts only qualified Ready Metrics 2 negative
trials with firmware-reported failure, intact reporting, infrastructure capture and
verified conditions. Failed trials count toward the fixed count; no automatic
success-target retry replaces them. Cleanup ambiguity always halts dispatch.

The advisory gateway lease covers wrapper-owned operations across development
hosts. It does not intercept arbitrary SSH commands, prove detached remote helpers
have stopped, or authorize forced release. Recovery belongs to the
[host/gateway guide](002_host_gateway_setup.md).

## Collection and export

Use [campaign collection](015_campaign_collection.md) for commands and recovery.

`scripts/collect_thesis_evidence.py` checkpoints frozen multi-campaign plans,
source/profile identity, attempts and explicit retries. It advances only after a
finalized campaign and successful cleanup; skipped/missing OTA cases are incomplete.
Energy-enabled plans select acquisition before resolution. Application energy in
a boot-profile campaign is not bootloader energy.

Queue exports select explicit completed campaign roots and preserve decisions,
attempt history and capture identities. `runs.csv` and archive metadata
are offline products, not new measurements. The shared analysis notebook lists
these exports without generating another notebook per export. Flat archives, typed loading, analysis
controls and frozen report verification are owned by the
[result reference](012_results_and_analysis.md).

### TLS authentication parameter sets

`configs/tls_auth/mldsa44.yaml` and `mldsa65.yaml` select separate native
ML-DSA certificate hierarchies and TLS signature schemes. Both support server
and mutual authentication. The `tls_authentication` and `thesis_authentication`
grids contain five certificate families and both roles (ten conditions), with
P-256 key establishment fixed. Existing frozen queue plans are not expanded.

The firmware compiles only the selected ML-DSA parameter set, enables signing
only for mutual authentication, and records `mldsa44_sign`/`mldsa44_verify` or
`mldsa65_sign`/`mldsa65_verify` from the measured key's parameter level. The
candidate-count records join the matching signing event. ML-DSA-44 and
ML-DSA-65 results remain separate configurations; adding the profile is not
hardware qualification. A bounded queue capture must verify the certificate
scheme, complete workload, instrumentation and normal cleanup before collection.

### ML-DSA TLS memory options

The optional case choice `mldsa_memory_mode` accepts `default`, `verify_small`,
`sign_small` and `both_small`. Nondefault options require ML-DSA-44 or ML-DSA-65 TLS authentication;
signing options require mutual mode. These options affect the STM32 TLS implementation,
not the broker or firmware-signature verification. The choice participates in firmware identity
and retained TLS controls. Omission keeps the previous configuration identity.
In the campaign editor, select **Factors / matrix → ML-DSA TLS memory mode**:
one selection becomes a fixed choice; several become a matrix. **Use default / omit**
leaves the setting absent. Invalid combinations are rejected during validation;
use a separate ML-DSA campaign when other authentication families are in the grid.

For example, a mutual-authentication profile can contain:

```yaml
fixed:
  tls_auth: mldsa65
  auth_mode: mutual
  mldsa_memory_mode: both_small
```

Server authentication supports `default` and `verify_small`; mutual authentication
supports all four modes. Existing profiles and defaults are unchanged. These modes
do not automatically reduce the configured heap or scratch reservation. The default
ML-DSA-44 allocator routes its 29 KiB verification scratch and larger requests to
the existing RAM3 workspace; the default ML-DSA-65 threshold remains 32 KiB.
Small-memory modes retain the 8 KiB threshold. These thresholds select allocation
placement, not additional reserved capacity; ordinary non-ML-DSA allocations stay
on the FreeRTOS heap.
The two focused templates and decision criteria are described in
[memory-option experiment](mldsa_memory_experiment.md). Their fixed heap/scratch
reservations make utilisation changes comparable before any capacity reduction.


### Optional TLS implementation controls

Campaign `fixed` choices and `matrix` factors also accept the following application
wolfSSL controls. They appear under **Factors / matrix** in the campaign editor;
the migration wizard offers **TLS implementation options → Customise**.

| Parameter | Default | Meaning |
|---|---|---|
| `tls_small_stack` | `true` | Move selected temporary arrays from stack to allocator storage. |
| `tls_task_stack_bytes` | `8192` | Network task allocation; supported alternatives are 49152 and 65536 bytes. |
| `tls_heap_bytes` | `98304` | Shared FreeRTOS pool reservation; optional 131072 bytes supports the larger task stack. |
| `mlkem_small_code` | `false` | Select wolfSSL's compact ML-KEM implementation. |
| `mlkem_makekey_small_mem` | `true` | Reduce ML-KEM key-generation temporary storage. |
| `mlkem_encapsulate_small_mem` | `false` | Reduce encapsulation/re-encapsulation storage; this also affects decapsulation. |
| `mldsa_small_code` | `false` | Select wolfSSL's compact ML-DSA implementation. |
| `mldsa_memory_mode` | `default` | Independently select small signing and/or verification, as described above. |

Defaults are unchanged. An omitted choice preserves the existing case identity;
an explicitly selected campaign value is retained in case/build identity and TLS
analysis controls. A/B profiles omit default values for compatibility with saved
sessions. Invalid types and inapplicable algorithm/transport choices are rejected.
Use separate grids for ML-KEM and classical KEX when a factor only applies to ML-KEM.

Disabling `tls_small_stack` requires `tls_task_stack_bytes` of at least 49152.
Large task stacks also require the explicitly recorded 131072-byte FreeRTOS pool;
the 96 KiB default could not start the enlarged-stack hardware qualification.
That validation floor is not a guarantee of stack/heap sufficiency for every grid
point: retain allocation failures and inspect measured watermarks. To compare the
implementation flag alone, hold the larger task and heap allocations fixed on both sides.
The task allocation belongs to the FreeRTOS heap and must not be added twice in
RAM accounting. The wizard records the required heap choice when a larger stack is selected;
no option resizes the ML-DSA scratch pool.

For example, a focused ML-KEM experiment can use:

```yaml
fixed:
  tls_kex: ML_KEM_768
  tls_auth: ecdsa-p256
  auth_mode: server
matrix:
  mlkem_small_code: [false, true]
  mlkem_encapsulate_small_mem: [false, true]
```

These controls apply to the MQTT/TLS application and repeated-handshake workload,
not wolfBoot or the isolated primitive benchmark. ML-DSA TLS credentials are
provisioned before collection, so its key-generation small-memory flag has no
on-device TLS operation to benchmark and is not exposed as an inert grid factor.
The options follow [wolfSSL's memory trade-off study](https://www.wolfssl.com/optimizing-post-quantum-algorithm-memory-usage-on-embedded-systems/);
its Raspberry Pi measurements do not establish memory or latency on the STM32.

### Experiment broker TCP_NODELAY

`broker_tcp_nodelay` is an optional boolean in campaign `fixed` or `matrix`,
also exposed under **Factors / matrix** in the campaign editor. Omission executes
with `true`; explicit `true` and `false` are supported and other types rejected.
It applies to plaintext, server TLS and mutual TLS experiment profiles. The
reporting broker is unchanged. The Mosquitto process-wide setting also applies to
its workload-feeder connections; it is not a device-connection-only intervention.

Resolved values participate in configuration and frozen-case identity, and both
resolved values participate in broker compatibility. A changed value requires
reconfiguration before reuse. It is excluded from firmware identity: keep and
verify the same preparation image hash within each off/on pair. Newly resolved cases explicitly freeze ON, including its configuration identity.
Previously resolved cases and requeued historical jobs with an omitted setting
retain OFF execution semantics; their historical captures remain unknown rather
than invented observations of effective socket settings.

The default is ON for new experiments, following the bounded baseline intervention.
Explicit OFF remains available for deployment comparisons. A matched pilot must hold all other settings
constant, retain failed attempts, and report its instrumentation and attempt order.
A faster result alone does not justify changing the measurement configuration.
