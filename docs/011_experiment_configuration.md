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

### ML-DSA memory-option pilot

The optional case choice mldsa_memory_mode accepts default, verify_small,
sign_small and both_small. Nondefault options require ML-DSA TLS authentication;
signing options require mutual mode. The choice participates in firmware identity
and retained TLS controls. Omission keeps the previous configuration identity.
The two focused templates and decision criteria are described in
[memory-option experiment](mldsa_memory_experiment.md). Their fixed heap/scratch
reservations make utilisation changes comparable before any capacity reduction.
