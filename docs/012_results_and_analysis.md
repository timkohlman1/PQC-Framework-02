# Results and offline analysis

This reference owns capture schemas, measurement interpretation and offline
analysis entry points. It describes supported contracts, not fresh experimental
results. The [architecture](007_framework_architecture.md) explains producers;
[testing and deferred coverage](013_testing_and_deferred_coverage.md) records
validation gaps. Historical A1–A8 labels below identify existing tools, not phases
to implement again.

## Default thesis workflow

Run `./scripts/dev.sh notebook` and open
[notebooks/analysis.ipynb](../notebooks/analysis.ipynb). The maintained path is:
choose retained results → select the question/recipe → review evidence and counts
→ preview tables and figures → save a revision. The same backend is available
through `scripts/analyse_results.py`.

### Choose results once

The catalogue scans only `results/queue/exports/*/archive.json` and
`results/analysis/exports/*/archive.json`. It lists campaigns, captured source
commits, current attempts, historical rows and missing captures. Invalid archives
remain visible. Set the notebook's `CHOICE` to a catalogue row; no filenames or
hashes need copying. Alternatively reopen a saved `selection.json`, or use the
advanced `EXPORTS`/`REQUESTS` list for several disjoint selections.

Selection freezes exact archive identities and expected run counts. It never
silently selects the latest export or adds later captures. Overlapping exports
and overlapping campaign selections are refused. General domain recipes select
complete runs: a repeated handshake row cannot be filtered out to change its
run's weight. Queue replacements remain replacements in inference checks.
Standalone retained captures are included without inventing queue attempts.

For retained results outside the queue, import explicit capture/campaign folders
using the existing archive exporter:

```bash
./scripts/dev.sh python scripts/analyse_results.py import \
  --source results/campaigns/SELECTED_CAMPAIGN \
  --output results/analysis/exports/selected-campaign
./scripts/dev.sh python scripts/analyse_results.py catalog
./scripts/dev.sh python scripts/analyse_results.py inspect \
  --export results/analysis/exports/selected-campaign --campaign SELECTED_CAMPAIGN
```

`--source` may be repeated. Import creates a new derived archive; it neither
acquires data nor changes captures. An optional `--annotations` file uses the
existing energy/network annotation contract. `inspect` exposes recorded control
values, run keys and timing metrics, allowing selection without browsing raw
files. Use `--filter FIELD=JSON` for other explicit archive equality filters.
A non-default catalogue root uses `--exports-root`.

### Choose the question

| Recipe | Purpose and statistic |
|---|---|
| `secure_boot`, `secure_boot_stack` | Compact boot timing/size table and a separately linked stack selection |
| `tls_auth`, `tls_kex`, `tls_auth_followup` | Compact thesis matrices: timing means/sample SD, unique static sizes, observed regional maxima; follow-up remains a separate matched batch |
| `network_loss` | Configured loss grid: all-current-attempt outcomes and success-conditional timing medians/IQR |
| `timing` | Recorded checkpoints and same-iteration payload throughput; descriptive medians/IQR |
| `resources` | Memory/flash medians across unique builds or final run lifetimes, retaining regions/accounting |
| `tls` | Handshake and operation attribution; repeated handshakes reduce to a median per run before across-run summaries |
| `network` | Selected packet flows, directions, windows and matched rate/RTT/loss/MTU comparisons |
| `energy` | Recorded-window and aligned phase energy/power with explicit electrical attribution |
| `boot_evidence` | Detailed mailbox/clock/image/static evidence and boot timing exclusions |
| `baremetal` | Raw primitive cycles: within-run operation medians, then across-run summaries |
| `ota` | Delivery, stages and image evidence, with unconfirmed transitions and unsupported durations explicit |
| `comparison` | Several chosen domains sharing one selection and comparison specification |

`recipes` lists these purposes in the CLI. Compact recipes retain their existing
scientific policy and old pinned selections remain valid. General recipes reuse
the same A2–A8 engines used by detailed/frozen reports; there is no separate
notebook parser or statistical implementation.

For general recipes, `GROUP_BY` defines named conditions from recorded fields
(default `case_id`); the first sorted condition becomes the recorded baseline
unless explicitly changed. `TREATMENT` identifies deliberately changed controls.
Every other required control remains checked. No control waiver or independence
claim is inferred from grouping. An explicit `COMPARISON` dictionary can instead
provide the existing comparison contract, including exclusions with reasons,
not-applicable controls and the deliberately opt-in evidence equivalence policy.
The CLI accepts this as `--comparison FILE`; grouping uses repeatable
`--group-by`/`--treatment` and `--baseline`.

Example TLS selection:

```bash
./scripts/dev.sh python scripts/analyse_results.py select \
  --export SELECTED_EXPORT --campaign SELECTED_CAMPAIGN --recipe tls \
  --group-by tls_kex --treatment tls_kex \
  --output results/analysis/selections/tls.json
./scripts/dev.sh python scripts/analyse_results.py preview \
  --spec results/analysis/selections/tls.json
./scripts/dev.sh python scripts/analyse_results.py publish \
  --spec results/analysis/selections/tls.json --name tls
```

This example does not waive correlated TLS/profile controls; inspect the matched
comparison reasons before claiming an effect. `comparison` accepts repeatable
`--domain` selections. Energy and packet recipes reuse explicit archive
annotations, or accept `--energy-selection` and `--network-selection` JSON using
the existing per-run contracts. Missing boundaries/endpoints produce unavailable
results, never guessed physical attribution. The retained broker identity helper
`scripts/prepare_network_selection.py` remains available for conservative flow
selection from broker/PCAP evidence.

General reports distinguish descriptive summaries from matched differences.
Conflicting/unknown controls leave differences unavailable with reasons. Failed
and unknown runs remain in detailed completeness data; unsuccessful attempts are
not latency samples. Attempts without captures stay in `observations.csv` and
cannot supply an attributed domain measurement or controlled completion
denominator. Compact recipes refuse those attempts where their controls are
unestablished. Do not filter them away to suggest a complete campaign.

### Preview and shape the output

The notebook shows the selected attempt audit, frozen comparison, table index,
metric names and full-precision statistics. `DETAIL_FRAMES` displays any of the
computed domain frames for inspection. Preview writes only temporary rendering
files. Saved specifications retain their presentation settings unless
`APPLY_PRESENTATION` is enabled.

General recipes default to a small primary set of measurements. All detailed
frames remain available. Set `measurements` to a list of metric names or glob
patterns (for example `tls_handshake` or `*.energy_j.*`), or `["*"]` for every
metric. The notebook lists available measurement names.

Other presentation options are `figures` (metric names), `tables` (ordered table IDs),
`captions` (table ID to caption/figure heading), `labels` (original condition to display label),
`order` (original conditions) and `width_inches` (3–16). Empty `tables` means all;
empty `figures` means tables only. General recipe defaults plot available
summaries; `figures: ["*"]` expands these explicitly on publication. Unavailable
summaries and their reasons remain in the detailed domain exports. Selecting a
smaller presentation does not alter the domain calculation.

Tables and figures use the same computed values, with the statistic, units and
sample unit recorded. SD/IQR bars describe spread, not confidence intervals.
Missing values are not zero. Static-build observations, run lifetimes, per-run
medians and repeated samples remain distinct. Regional memory peaks cannot be
added to obtain system peak RAM. Network percentages are configured loss, not
observed loss. Unsupported boot/OTA energy and cross-reset durations remain
unavailable. LaTeX fragments require `booktabs` and `graphicx`.

### Save, verify and reproduce

Saving creates `results/analysis/reports/<name>/<revision>/` or an explicitly
selected fresh directory. Existing reports and source exports are preserved.
Every revision contains CSV/LaTeX tables, SVG/PDF/PNG figures plus
`figure-data.csv` when requested, full-precision `metrics.csv`, attempt audit,
pinned `selection.json`, HTML preview, provenance and checksums. General recipes
also emit `data-<selection>-<frame>.csv` for every detailed frame and `methods.json`
with normalized comparisons and domain provenance. Detailed CSV uses `\N` for
null, JSON for nested provenance and a doubled leading backslash for literal
backslash-prefixed strings. Empty domain frames still have their exported schema.

```bash
./scripts/dev.sh python scripts/analyse_results.py verify results/analysis/reports/tls/SELECTED_REVISION
./scripts/dev.sh python scripts/analyse_results.py verify results/analysis/reports/tls/SELECTED_REVISION --verify-sources
./scripts/dev.sh python scripts/analyse_results.py rebuild \
  results/analysis/reports/tls/SELECTED_REVISION --output results/analysis/rebuilt-tls
```

Output verification needs only the saved report. Source verification also checks
original retained inputs, additional evidence consumed by the domain engines,
and recorded absence of selected inputs.
`rebuild` requires unchanged recorded framework sources and analysis environment,
and compares every scientific CSV/LaTeX file before publishing the new directory.
Vector/raster metadata is not promised byte-identical. Reports created before the
complete source inventory was added require deliberate republication instead of
strict rebuild. Reopening a pinned selection and publishing it with changed code
or a different Python/library environment is deliberate reanalysis; it is a new revision.

Exit 0 means the requested software operation completed; exit 2 means invalid
inputs, integrity failure, unsupported selection or failed reproduction. None of
these checks establishes physical measurement accuracy, hardware qualification
or completion of a campaign's intended design.

### One interactive workflow

`notebooks/analysis.ipynb` and `scripts/analyse_results.py` are the maintained
interactive and batch interfaces to the same selection, comparison and publication
functions. Domain engines own evidence interpretation; notebooks contain no
independent parsers or statistics. Queue exports contain data and provenance and
appear in the notebook catalogue automatically.

The old domain notebooks, compact-table notebook/CLI, summary CLI and per-export
notebook generator have been retired. Existing pinned compact selections still
work through `analyse_results.py publish --spec` or the shared notebook's
`SPEC_FILE`. The old `PQC_A2_*` and `PQC_THESIS_TABLES_*` notebook overrides are
replaced by `PQC_ANALYSIS_SPEC`, `PQC_ANALYSIS_PUBLISH` and `PQC_ANALYSIS_OUTPUT`.
Retired notebook bytes, including saved outputs, are preserved in the local
`results/analysis/cleanup-backups/` archive; prior generated reports and export
notebooks remain research artifacts. They are not inputs to new analyses.

`build_research_report.py` retains its separate purpose: collection-driven chapter
coverage and frozen snapshots. Its internal renderer lives in
`scripts/framework/templates/research_report.ipynb`; it is not a notebook to
configure interactively. `00_checkout.ipynb` diagnoses the host Docker checkout.
Raw packet/stack diagnostics and the A1 dataset exporter retain their distinct
acquisition/inspection roles. The obsolete manifest-metric aggregation command
has been removed; current boot/primitive evidence uses the shared recipes.

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

## Comparison policy (A2)

A JSON analysis specification declares disjoint named `conditions`, an explicit
`baseline`, optional `filters`/`exclude_runs`, and intentional `treatment` paths.
The shared selection command creates this specification; `--comparison FILE`
accepts an explicit one. Maintained pilot presets live in
`configs/analysis/comparisons/`.
Unknown or conflicting controls refuse matched differences; absolute distributions
remain available. Hardware, source/dirty identity, workload, payload/chunk, QoS,
boot, diagnostics, authentication and network properties stay fixed unless the
selected scientific treatment explicitly changes them. `not_applicable` needs a
methodological reason and does not mean silently waiving an unknown value.

Select a recipe and publish through the [default workflow](#default-thesis-workflow).
Choose fresh destinations outside raw runs and datasets. CLI and notebook use the
same functions; rendering timestamps need not match. Cell failures propagate.

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

`report.json` and `methods.json` retain effective selections, parser/source
versions, direct input hashes and unavailable reasons. Domain engines consume only
their declared retained inputs and never mutate captures. Detailed tables are
exported as `data-<selection>-<frame>.csv`, alongside publication tables and figures.
Docker-recorded `/workspace/results/...` inputs also load from the matching
`results/...` location in the active checkout when that Docker path is absent.
Recorded paths and source hashes remain unchanged; existing paths, hash failures
and symlink refusals never trigger a search for substitute evidence.
All domains use the shared notebook or `analyse_results.py --recipe` selection.

| Recipe | Main detailed frames |
|---|---|
| `timing` | Inventory, observations, completeness, distributions, differences |
| `resources` | Resource builds, observations, distributions, differences |
| `tls` | Attribution, coverage/issues/iterations/handshakes, per-run comparisons |
| `network` | Flow observations, comparisons, availability and packet view |
| `energy` | Intervals, availability, distributions and explicitly selected trace data |
| `boot_evidence` | Boot observations, outcomes, resources, distributions, differences |
| `baremetal` | Primitive observations, availability and per-run summaries |
| `ota` | Observed update outcomes and explicit confirmation limitations |
| `comparison` | Multiple explicitly selected domains |

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

## Compact publication recipes

The shared workflow also supports compact grids for secure boot, TLS authentication,
TLS key exchange and packet loss. Select the corresponding recipe in the notebook
or CLI. `configs/analysis/thesis_tables.example.json` demonstrates linked
selections for advanced use; existing pinned specifications can be loaded as
`SPEC_FILE` or published with `analyse_results.py publish --spec FILE`.
These recipes use the same archive loader, publication writer and source verification
as domain comparisons. Their explicit statistical conventions are described below.

Load `booktabs` and `graphicx` in the thesis preamble, then insert copied fragments
with `\input{secure_boot.tex}`, `\input{tls_auth.tex}` or `\input{tls_kex.tex}`.
Each fragment has a caption and a `tab:pqc-...` label. Its marked draft-provenance
block is visible by default: change `\iftrue` to `\iffalse` to hide it. Scientific
measurement definitions remain with the table. Make thesis edits to copies;
editing the generated report invalidates its output checksums.

Table kinds are `secure_boot`, `secure_boot_stack`, `tls_auth`, `tls_kex`,
`tls_auth_followup`, and `network_loss`. A secure-boot selection can name its separate
`stack_selection`; a follow-up must name its original `baseline_selection` and
match the selected case's configuration, firmware and source identities. The
follow-up is displayed separately, preserving the main matrix's sample sizes.
Stack profiling never supplies normal boot timings. Baseline TLS selections
require impairment disabled; zero-loss impairment controls remain separate.

The tables select current successful captures with verified inputs and preserve
failed/historical attempts in the audit. Repeated-handshake rows are refused
rather than treated as extra independent boots. TLS timing cells show mean and sample
SD. Secure-boot timing cells show means, with integrity verification before authentication;
all secure-boot sizes use bytes. A note reports identical values across ten executions
only when every applicable displayed metric meets that condition in both campaigns.
Otherwise the note directs readers to counts and dispersion in `metrics.csv`.
Per-metric missingness is disclosed. Static sizes are build facts and
conflicting sizes are unavailable rather than averaged. TLS regional peak RAM values
overlap static reservations and are not additive. Bootloader static RAM excludes
stack; its stack watermark covers selected-image verification in a separate profiling
build, so their sum is not a measured whole-boot RAM maximum. These are descriptive tables:
no confidence intervals, independent-run claim or causal difference is inferred.

A `network_loss` selection generates three grids: `_success.tex` reports successful
runs / all current attempts; `_completion.tex` reports median TCP-connect-start to
application-last-byte time; `_handshake.tex` reports median device TLS handshake
time. Timing is in seconds and conditions on successful, valid captures only.
Capture failures remain in outcome denominators; missing timing is never zero-filled.
Read latency alongside success counts because high-loss survivors are a selected subset.
Full-precision counts, sample SD and quartiles remain in `metrics.csv`.

Loss columns use configured percentages, including an enabled-impairment 0% reference.
The exported configured controls do not establish realized packet loss or verified
application of impairment. Keep RTT, rate, MTU, payload, QoS and TLS authentication
mode fixed within a grid; do not merge later diagnostic follow-ups into the pilot.
Use an explicitly pinned selection with `kind: network_loss`, created through
`analyse_results.py select --recipe network_loss`, and review the current attempt
count before publication.

## Notebook operation

Launch `./scripts/dev.sh notebook`, open `notebooks/analysis.ipynb`, and Run All.
Your own Linux Jupyter installation can also open this notebook from the checkout
with the analysis dependencies installed (`requirements-dev.txt` records the
maintained environment). After framework changes, restart its kernel and Run All
to load the updated modules. Docker remains the reproducible validation environment.
The Docker launcher retains authentication and binds through `127.0.0.1:8888`; an occupied
port fails. Paths recorded in Docker use `/workspace`; result reads resolve that prefix
to this checkout when needed, retaining all integrity checks. Select results and a recipe,
preview, then save a fresh report revision. Notebook outputs are a view; published
CSV/LaTeX and PNG/SVG/PDF files are the thesis artifacts. The committed notebook
starts without a selection and with saving disabled. Keep reusable selections in
`results/analysis/selections/` or use a published report's `selection.json`; set
`SPEC_FILE` to that repository-relative path to reopen the selection.

`notebooks/00_checkout.ipynb` is a host Docker diagnostic and needs a Linux Jupyter
environment with Docker access. It does not analyse experiment results.
For PDF of saved notebook outputs, use JupyterLab's Save and Export Notebook As →
PDF, or:

```bash
./scripts/dev.sh run python -m jupyter nbconvert --to pdf notebooks/analysis.ipynb --output-dir results/analysis/notebook-pdf
```

The image contains pinned Pandoc/TeX tools. After an image update, save work, stop
the notebook server, rebuild with `./scripts/dev.sh build-image` and relaunch it.
Restarting only a kernel keeps the old container. PDF export does not rerun hardware
or establish any new measurement evidence.
