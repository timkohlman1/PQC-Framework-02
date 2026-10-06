# Results and offline analysis

This reference owns capture schemas, measurement interpretation and offline
analysis entry points. It describes supported contracts, not fresh experimental
results. The [architecture](007_framework_architecture.md) explains producers;
[testing and deferred coverage](013_testing_and_deferred_coverage.md) records
validation gaps. Historical A1–A8 labels below identify existing tools, not phases
to implement again.

## Capture and provenance

Current firmware experiment captures use `pqc-run-evidence` schema v3. `manifest.json` owns execution
and capture provenance. `resolved-case.json` retains selected profiles,
hashes, choices and named environment references. `run-provenance.json` retains detailed
source, dependency, preparation, build and deployment records. Both snapshots are
hashed required evidence. Source identity includes recorded commit, dirty-state
fingerprint and submodule state; current checkout metadata cannot fill historical
gaps. `source.git_commit` and the supported legacy alias must not conflict.

| Decision | Meaning |
|---|---|
| `execution_outcome` | Recorded orchestration/SUT completion, failure or non-execution |
| `capture_acceptance` | Required raw artifacts retained and integrity-checked |
| Metric validity | A supported parser found consistent measurement evidence |
| Comparison eligibility | Selected observations meet the declared control/statistical policy |

A failed experiment can retain useful complete evidence; a completed experiment
can have incomplete capture. Success at one decision does not imply the others.

The capture contract classifies artifacts as required, optional or not applicable.
Each semantic artifact carries a role, source/producer, result-relative path,
size, SHA-256, acquisition state and reason. Finalization inventories additional
retained files, rechecks bytes and seals the compact index. Raw files become
read-only where supported. `manifest.json`, manual notes and `analysis/` are not
self-inventoried. Legacy v1 records are historical inputs, not silently upgraded
v3 captures. Transient metric blocks used by orchestration are removed on
finalization; new scientific fields belong in raw records and derived products.

Results retain explicitly selected experiment images and disposable cryptographic
material through `material-inventory.json`. Canonical material remains future-input
authority; archived copies are reproduction evidence. All experiment material
follows the [open-data policy](006_security_and_secrets.md). Current export
allowlists/redaction describe implemented output shape, not confidentiality.

## Device, packet and clock boundaries

The reporting collector stores `mqtt-reporting-raw.ndjson`. STM32 topics under
`pqc/result/stm32/<run-id>/` carry bounded chunks and completion metadata: identity,
sequence, counts, overflow/drop state and logical SHA-256. A completed epoch can
precede a reset or the next repeated handshake; an epoch alone is not proof of a
boot/reset. Iteration and handshake identities remain explicit. The current
ESP32 stream uses fixed instrument topics without an STM32-style run ID; its
[acquisition contract](010_esp32_ina228_energy_instrument.md) is validated separately.

UART is raw device output, with acquisition metadata in the capture record and
interpretation offline. Networked runtime completion normally uses reporting
integrity, not mandatory UART phrases. Baseline diagnostic and negative boot
workflows retain their own UART predicates. Gateway PCAP and broker observations
are independent evidence; packet identity does not establish firmware state.

Application time uses TIM2 at a recorded 1 MHz with wrap extension. HAL ticks are
scheduler/diagnostic time, not research timing. DWT records independent cycle
attribution. The LPTIM2 boot bridge supplies an operational wolfBoot-entry offset
only when valid; it is not physical power-on/reset timing. Packet epochs, broker
time and device clocks remain separate unless explicit alignment evidence exists.
Host duration, linker size and capture duration cannot supply runtime measurements.

## Timing dataset and typed loading (A1)

Select existing captures and a new output directory:

```bash
./scripts/dev.sh python scripts/export_timing_dataset.py \
  --results-root results/campaigns/SELECTED_CAMPAIGN \
  --output results/analysis/SELECTED_DATASET
```

Alternatively repeat `--run-dir` for explicit run directories; do not combine it
with `--results-root`. Discovery excludes generated analysis, preparation, build,
`secrets/` and dependency trees and stops at a run. Empty discovery fails. Missing or
unreadable explicitly selected runs remain inventory findings. Outputs cannot be
existing directories, symlinks, or overlap selected raw inputs.

Products are `runs.csv`, `timings.csv`, `issues.csv`, `dataset.json` and
`dataset.sha256`. Exit 0 means export completed, not that every input or metric
succeeded; invalid selection/checks exit 2. Verify the frozen tables and optionally
the exact original consumed inputs:

```bash
./scripts/dev.sh python scripts/export_timing_dataset.py \
  --check results/analysis/SELECTED_DATASET --verify-source-inputs
```

Omit `--verify-source-inputs` for output-only verification after relocation.
`capture_recheck=selected_inputs_only` is not a new audit of every raw artifact.
The exporter verifies the sealed index/acceptance and consumed snapshot/reporting
hashes before parsing, then rechecks inputs before publication. Unsupported schemas,
identity conflicts, missing completions and changed consumed bytes remain explicit.
Invalid optional energy content does not invalidate unrelated valid timing.

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve()))
from framework.timing_dataset_loader import load_dataset

dataset = load_dataset("results/analysis/SELECTED_DATASET")
view = dataset.timing_view()
```

The loader checks hashes, columns, types, units and joins. Join on `run_key`, which
binds recorded run ID and manifest hash, not a basename or run ID alone. Repeated
identical captures are deduplicated; ID collisions with different captures remain
visible. Retry links, campaign repetition and workload iteration are not invented.
CSV null is `\N`; leading literal backslashes are escaped. Identifiers remain
strings, timestamps exact integers (including above 2**53), and missing values
`None` with reasons. A measured zero stays zero. Avoid automatic CSV dtype inference.

### Timing definitions

All scalar values below are microseconds. Let T be TCP-connect initiation after
DNS, M the first MQTT CONNACK plaintext byte, Q the application request, F/L the
first/final requested payload byte, and O the valid reset-to-application offset.

| Metric | Formula | Evidence boundary |
|---|---|---|
| `tls_handshake` | end − start | Successful outer handshake and available application clock |
| `mqtt_readiness` | M − T | MQTT readiness, not payload TTFB |
| `rtfb` | O + F | Operational wolfBoot entry to first payload byte |
| `rtlb` | O + L | Operational wolfBoot entry to final payload byte |
| `ttfb` | F − T | TCP-connect attempt to first payload byte |
| `ttlb` | L − T | TCP-connect attempt to final payload byte |
| `req_tfb` | F − Q | Request to first payload byte |
| `req_tlb` | L − Q | Request to final payload byte |

Ready Metrics 2 schema 3 records checkpoints and scalars; the parser rederives them
and checks order, payload counts, completion and clock evidence. Invalid reset
handoff disables only reset-relative metrics. Failed TLS attempts retain outcomes
without a successful-latency value. Phase overflow does not automatically invalidate
an independent outer scalar. No configured repeat count manufactures observations.
A1 reports `comparison_inclusion=not_assessed`; it does not select a comparison.

## Comparisons and notebooks (A2)

A JSON analysis specification declares disjoint named `conditions`, an explicit
`baseline`, optional `filters`/`exclude_runs`, and intentional `treatment` paths.
Use `notebooks/timing_comparison.example.json` as an inspection-only starting point.
Unknown or conflicting controls refuse matched differences; absolute distributions
remain available. Hardware, source/dirty identity, workload, payload/chunk, QoS,
boot, diagnostics, authentication and network properties stay fixed unless the
selected scientific treatment explicitly changes them. `not_applicable` needs a
methodological reason and does not mean silently waiving an unknown value.

```bash
./scripts/dev.sh python scripts/summarise_timing_dataset.py \
  --dataset results/analysis/SELECTED_DATASET \
  --spec notebooks/SELECTED_SPEC.json \
  --output results/analysis/NEW_SUMMARY
```

Choose fresh destinations outside raw runs and datasets. Add `--execute-notebook`
for a clean kernel, or run `./scripts/dev.sh notebook` and edit the chosen notebook's
configuration cell before Run All. The notebook server retains authentication and
binds through `127.0.0.1:8888`; an occupied port fails. CLI/notebook scientific CSVs
use the same functions; rendering timestamps need not match. Cell failures propagate.

Failures, unknown outcomes and explicit exclusions remain visible. The binary
completion denominator is completed + failed framework runs; other states stay
unknown. Latencies are success-conditional and require valid selected inputs and
applicable timing policy. Timeout thresholds are not observations. There is no
automatic outlier removal or zero fill.

Differences are treatment median minus baseline median; percentage differences
are unavailable with `zero_baseline`. Quartiles/percentiles use linear interpolation.
Inference requires `independent_runs: true`, at least two eligible independent
runs and no linked retries. Default continuous intervals use a seeded 2,000-sample
percentile bootstrap at 95%; binary completion uses Wilson intervals. Repeated
intra-run values require the per-run TLS treatment below. These are not causal
claims or hypothesis tests; small-sample limitations remain explicit.

Evidence classes match exactly by default. Explicit `stm32_st67_tls` comparison
policy admits the known classical/hybrid/PQ STM32 TLS labels; `stm32_st67_transport`
also supports declared plaintext/TLS transitions. Original labels remain visible.
Neither policy admits host/fake/build-only evidence, waives other controls, or
merges positive experiments with deliberate negative validation.

## Analysis domains

The summary command and `summary.json` retain effective selections, parser/source
versions, direct input hashes, output hashes and unavailable reasons. Domain
extensions consume only their declared retained inputs and never mutate captures.
Use the same `/workspace` mount for paths recorded by Docker-generated datasets.

| Domain | CLI option | Notebook | Main outputs |
|---|---|---|---|
| Timing | default | `notebooks/timing_comparison.ipynb` | Inventory, observations, completeness, distributions, differences |
| Application resources (A3) | `--resources` | Timing notebook, `INCLUDE_RESOURCES` | `resource_builds.csv`, observations/distributions/differences |
| TLS attribution (A4) | `--tls` | `notebooks/tls_attribution.ipynb` | `tls_attribution.csv`, coverage/issues/iterations/handshakes, `tls_per_run.csv`, operation/run comparisons |
| Network (A5) | `--network-spec <selection.json>` | `notebooks/network_comparison.ipynb` | Flow observations, comparisons and diagnostic packet view |
| Energy (A6) | `--energy` or `--energy-spec <selection.json>` | `notebooks/energy_comparison.ipynb` | Interval/availability tables, distributions, selected trace |
| Secure boot (A7) | `--secure-boot` (includes resources) | `notebooks/secure_boot_comparison.ipynb` | Boot observations/outcomes/resources/distributions/differences |

### Resources

Static observations deduplicate by application ELF SHA-256. Signed-image identity
must be explicitly associated with its ELF through verified preparation provenance;
a build number alone is insufficient. The supported ELF32 ARM decoder counts
allocated file-backed load-address ranges for Flash, separately from image span
and retained binary length. Debug data and NOBITS reservations are not Flash.
Unknown layouts remain unavailable. 1 KiB = 1024 bytes.

Runtime FreeRTOS heap includes dynamically allocated task stacks. Heap backing
storage and RAM3 workspace/result-buffer reservations already occupy static RAM;
do not add their peaks again. `_sbrk` grows above the static base. MSP watermarking
excludes startup before `main()`; saturation is a lower bound and excluded from
exact-peak summaries. Independent regional peaks are not simultaneous demand:
`simultaneous_system_peak_bytes` remains unavailable. TLS before/after checkpoints
are not reset per-handshake peaks. Lifetime records have no invented iteration.

### TLS attribution

TIM2 elapsed spans and DWT cycles are independent observations under RTOS
scheduling. Ordered events retain sequence/parent/depth, boundary times, completion
and result. High-frequency hash operations can remain aggregate-only. Overflow,
truncation, unmatched ends and incomplete hierarchy remain findings; independently
valid aggregates may survive unavailable ordered evidence.

Nested phases, X.509 and primitive spans overlap: do not sum them into total crypto
cost. Handshake minus crypto is not measured network delay. Aggregate and invocation
representations stay separate; same-operation invocation totals require nonoverlap.
Absent stages in failed/unknown handshakes are unestablished; missing required
operations after success are reported. Server-only client signing is not applicable.

Repeated-handshake inference uses the across-run median of within-run successful
handshake medians, weighting each run equally. Run counts, observed handshakes,
failed TCP attempts and unknown outcomes remain separate. Operation comparisons
also use per-handshake totals and then per-run medians. KEX/certificate/auth-mode
comparisons must vary only their selected dimension.

### Packets and network

`scripts/analyse_packet_capture.py <manifest.json>` rechecks finalized PCAP,
optional TLS key log and device stream, then writes run-local
`analysis/packet_capture/` outputs and lineage. The built-in parser supports classic
PCAP Ethernet/cooked/raw-IP sources. Pinned `tshark` optionally enriches TLS/MQTT
using retained key logs; `--no-tshark` disables it. Missing/failed decryption stays
unavailable. Stale derived outputs cannot silently be reused.

A network selection maps exact A1 run keys to client/server IP, server port,
`evidence_reference` and `window`. A `retained_flow` window covers the selected
four-tuple lifetime. A `pcap_epoch` window uses explicit gateway start/end and
half-open bounds. These are operator assertions supported by evidence, not device
identification by broker port. `scripts/prepare_network_selection.py` can derive
conservative candidates from verified broker/PCAP intersections.

Wire bytes and TCP payload bytes include retransmissions. Sequence overlap is an
indicator, not causal loss diagnosis; out-of-order gap filling is not overlap.
Sequence wrap/tuple reuse can make overlap unavailable. Later IPv4 fragments cannot
be assigned safely by port; `any` captures may include duplicate observations.
No key log or packet payload is exported by the scalar comparison tools.

Configured rate/RTT/loss/MTU, verified gateway state and observed impairment are
separate. Qdisc state/counters do not measure achieved throughput, RTT or loss.
One-axis comparisons hold other conditions and window definitions fixed; disabled
zero-valued settings are not measured unlimited rate or MTU. Reporting traffic is
excluded. Whole-flow totals must not be labelled handshake-only bytes.

### Energy

ESP32 schema 1 samples are packed `<qfff`: microsecond timestamp, V, A and W.
Validate acquisition/chunks/hash/calibration before interpretation. Integrate W
once by trapezoids: `J[i+1] = J[i] + (P[i]+P[i+1])*(t[i+1]-t[i])/2000000`.
Gaps beyond the recorded limit start new segments. Interpolate cumulative J only
inside valid sample brackets; never extrapolate or bridge gaps. Average W is J
per instrument interval second, not a second integration of cumulative energy.

Scopes are instrument `recorded_interval`, `whole_workload`, `tls_handshake` and
first-to-final-payload `application_transfer`. Device phases use the explicit
STM32/ESP32 edge pairs: `e=e0+(s-s0)*(e1-e0)/(s1-s0)`. Offline alignment requires
one unambiguous duration-compatible pair; no clock fit or Cartesian pairing is
invented. Instrument-local totals may remain usable without a device pair.

Current STM32 capture records `workload_end_us` before a 20 ms tail guard; both
edges align clocks but workload integration stops at that endpoint. Legacy windows
retain their original GPIO meaning. `outside_sample_coverage` is unavailable even
when acquisition itself passed. Electrical boundary/evidence references in an
energy spec are researcher assertions; unknown boundaries exclude comparisons.
Calibration, instrument identity, scope and policy remain separate strata. No idle
subtraction, battery-life prediction or physical accuracy claim follows from math.

### Secure boot

Current interpretation supports mailbox v8/schema 1. Integrity-call, authenticity,
selected-image enclosing verification and `hal_init_entry_to_hal_prepare_boot`
are distinct boundaries; inclusive intervals cannot be summed. Convert cycles
only with recorded bootloader HCLK. Application-start timing and stale-SRAM
freshness are not proven by a structurally valid mailbox.

Selected-image records require matching verified partition/content digest/length.
Content digest differs from packaged-image SHA-256. Retained bootloader ELF and
signed WOLF header/TLV data determine static sizes, header capacity/use and actual
signature bytes; no size comes from today's profile constants. Integrity-only is
not signature authentication. Expected negative rejection is not normal boot success.

Stack-profiling timings are excluded from normal timing comparisons. Early boot
UART diagnostics exclude reset/handoff timing; normal boot analysis also excludes
negative and ambiguous multi-epoch observations. Boot stack is not concurrent
application RAM. Application energy cannot provide boot/OTA energy without matching
boundaries. A missing optional measurement does not invalidate unrelated evidence.

## Flat archives and frozen reports (A8)

`scripts/export_archive_table.py` produces nullable `runs.csv` plus schema and
lineage, using the existing decoders. Most experiments have one row per run;
repeated TLS has per-handshake rows without duplicating run-wide measurements.
Bare-metal columns contain within-run raw-cycle medians/counts and HCLK context,
not fabricated peak RAM. Sealed campaign indexes retain blocked/no-capture attempts
and attempt/acceptance history. Schema-1 archives remain loadable; schema 2 uses
functional-role columns with algorithm/parameter fields. The [flat archive procedure](#flat-experiment-archive) below owns typed loading;
the [queue guide](014_campaign_queue.md) owns selected-job export.

`scripts/build_research_report.py` consumes explicit datasets and analysis specs.
`configs/analysis/thesis_report.example.json` declares analysis IDs, relative dataset
paths, specs, domains, security domain and thesis sections. It reuses the summary
functions plus bounded bare-metal and OTA importers, without new experiments or
thesis prose generation.

```bash
./scripts/dev.sh python scripts/build_research_report.py --spec configs/analysis/thesis_report.example.json --output results/analysis/NEW_REPORT
./scripts/dev.sh python scripts/build_research_report.py --verify results/analysis/NEW_REPORT
./scripts/dev.sh python scripts/build_research_report.py --rebuild results/analysis/NEW_REPORT --output results/analysis/REBUILT_REPORT
```

The current `0700` snapshot separates `local/` source/selection/lock data from
allowlisted scalar `report/` products, executed notebook and HTML. CSV/PNG/LaTeX
use the same rows; LaTeX fragments require `longtable`. Raw keys, addresses,
packet/energy traces and nested provenance are not emitted by this report builder.
Those output restrictions do not change the open-data classification. Integrity
checking establishes hashes, not a digital signature.

Verification checks exact dependency/output inventories; rebuild requires matching
frozen code/environment and identical scientific CSV/LaTeX. Newly collected runs
cannot enter the selection. Rendering metadata need not be bit-identical. Optional
budgets compare one unambiguous statistic and otherwise remain `not_assessed`; a
median under budget is not a worst-case guarantee.

RQ1–RQ6 coverage distinguishes implemented analysis, available rows and supported
comparisons. RM2 throughput uses payload divided by first-to-final-byte duration
in the same valid run/epoch/iteration. Bare-metal aggregation uses one operation
median per boot. OTA import keeps delivery, authentication, bank selection,
confirmation and rollback separate; candidate transitions without immutable
identity remain unconfirmed. No cross-reset duration, software bank-copy time,
security ranking, aggregate migration score or completed RQ is invented.

## Flat experiment archive

Export a bounded collection/campaign, or explicitly select the full `results/`
archive. Supply annotations only when the electrical boundary and device attribution
apply to every selected capture:

```bash
./scripts/dev.sh python scripts/export_archive_table.py --results-root results/thesis/collection-01 --output results/analysis/flat-archive-01 --annotations configs/analysis/thesis_collection_annotations.json
./scripts/dev.sh python scripts/export_archive_table.py --check results/analysis/flat-archive-01 --verify-sources
```

`runs.csv` and `archive.json` retain typed columns, output hashes, source lineage,
attempt/acceptance history and unavailable data. A run usually has one row; repeated
TLS has one per observed handshake without copying whole-run energy, packet totals
or end-to-end timing into each row. Blocked attempts with no capture remain rows
with null measurements. No configured counts invent missing handshakes.

`run_key` identifies a retained capture and `row_id` a row. Identical copies are
deduplicated; never join by run ID alone. Schema 2 uses common metric columns and
separate treatment fields. Plaintext application values occupy the same timing
columns as TLS but have no handshake duration; absent is not zero cost.

| Domain | Representative columns / interpretation |
|---|---|
| Application | `timing__rtfb_us`, `timing__rtlb_us`, `timing__ttfb_us`, `timing__ttlb_us`, `timing__req_tfb_us`, `timing__req_tlb_us`, `application__payload_throughput_bytes_s` |
| TLS | `timing__tls_handshake_us`, `tls__aggregate__signature_verify__elapsed_us`; roles retain observed implementation identity |
| Resources | `resource__flash_section_bytes`, `resource__ram_static_base_bytes`, `resource__freertos_heap_peak_used_bytes`; reservations and peaks cannot be blindly added |
| Network | `packet__client_to_server__wire_bytes`, `packet__server_to_client__overlap_bytes`; retain layer, flow and window meaning |
| Energy | `energy__whole_workload__energy_j`, `energy__whole_workload__average_power_w`; require sample brackets and attribution |
| Boot/OTA | `boot__image_verification_ms`, `boot__image_signature_used_bytes`, `ota__*`; stage success is not final-image proof |
| Primitive reference | `primitive__signature_verify_median_cycles`, `primitive__kem_keygen_median_cycles`; within-run cycle summaries stay separate from RTOS elapsed time |

`transport_mode`, `tls_kex`, `tls_auth`, `auth_mode`, `secure_boot` and workload/network
fields describe treatments/controls. A role with multiple implementations is labelled
`mixed` and has no combined value. Nested/aggregate/invocation TLS views cannot be
summed into disjoint Total Crypto. Static build facts are repeated context, not
independent measurements.

Diagnostics include `run_success`, `capture_valid`, `selected_inputs_valid`,
`data_status`, `analysis_errors` and `timing_policy_exclusion`. A valid metric may
survive an unrelated channel failure; comparison restrictions remain explicit.
Regenerate specialist analysis for per-value reasons. Schema-1 exports remain
loadable; regenerate from raw inputs for schema 2 rather than editing sealed CSVs.

Use the maintained loader instead of pandas' default NA/type guessing:

```python
import sys
sys.path.insert(0, "scripts")
from framework.archive_table import load_archive

df = load_archive("results/analysis/flat-archive-01")
handshakes = df.loc[
    df["row_kind"].eq("handshake") & df["handshake_outcome"].eq("success"),
    ["run_key", "iteration_id", "tls_kex", "tls_auth", "timing__tls_handshake_us"],
]
```

The loader verifies hashes and returns nullable numeric/boolean/string columns.
CSV null is `\N`; literal identifiers such as `NA` and leading zeros survive.
Count unique run keys for run counts; intra-run handshake rows are not extra boots.
Before comparisons, select one compatible source/platform/workload/QoS/network/boot/
instrumentation stratum and declare the treatment. Summary statistics alone do not
establish matching, independence or causality.

## Notebook operation

The domain table above selects analysis notebooks. `notebooks/00_checkout.ipynb`
is different: it is a host-Docker checkout diagnostic, so run it in a Linux Jupyter
environment with Docker access. `notebooks/Memory_Analysis.ipynb` is an exploratory
notebook with local paths/saved analysis; it is not the maintained resource parser
or a validation gate. Use the resources option for canonical A3 interpretation.

For maintained analysis notebooks, use `./scripts/dev.sh notebook`, configure paths
under `/workspace`, and run all cells. Use fresh output directories. CLI clean-kernel
execution verifies the notebook path without relying on interactive saved outputs.

For PDF of saved outputs, use JupyterLab's Save and Export Notebook As → PDF, or:

```bash
./scripts/dev.sh run python -m jupyter nbconvert --to pdf notebooks/tls_matrix_energy.ipynb --output-dir results/analysis/tls_matrix_energy_pdf
```

The image contains pinned Pandoc/TeX tools. After an image update, save work, stop
the notebook server, rebuild with `./scripts/dev.sh build-image` and relaunch it.
Restarting only a kernel keeps the old container. PDF export does not rerun hardware
or establish any new measurement evidence.
