# Incremental analysis implementation requests

> Historical record. Original phase instructions, capability limits, commands and
> handling rules below describe their original context. Use the
> [current reference](docs/012_results_and_analysis.md) and [open-data policy](docs/006_security_and_secrets.md)
> for present work; this record does not authorize implementing old requests.

## Purpose and status

Build an offline analysis component that becomes useful before every measurement channel is integrated. The first milestone is a reproducible timing dataset and a working comparison notebook. Later requests extend that same path rather than create separate analysis systems.

This is a standalone implementation-request plan, not a repository patch. No framework implementation has been inspected or changed as part of preparing this document. The source basis is the supplied `AI_BUILD_GUIDE.md` and thesis `main.pdf`, especially §§1.3, 3.4–3.8, 4.9–4.10, and Chapters 5–6. Current parser compatibility, measurement availability and delivery effort are not established: I cannot confirm this without inspecting the current implementation and representative evidence.

The request IDs A1–A8 and S1–S2 belong only to this analysis plan; they do not renumber the framework's existing requests. Scope and ordering below are proposed engineering decisions, not statements that the thesis prescribes these implementation steps.

## Delivery order and usable stopping points

| Request | Deliverable | Research use | Dependencies |
|---|---|---|---|
| A1 | Current-format run inventory and timing dataset | Foundation for all RQs; initial RQ1/RQ4 measurements | None |
| A2 | First comparison notebook and reusable summaries | Initial RQ1/RQ4 comparisons and dataset completeness | A1 |
| A3 | Application memory and firmware-footprint comparisons | Resource dimensions of RQ1/RQ2 | A1–A2 |
| A4 | TLS phase/operation attribution and repeated-handshake summaries | RQ2; interpretation of RQ1 | A1–A2 |
| A5 | Network/impairment analysis using retained packet evidence | RQ3; network contributions to RQ1/RQ2/RQ4 | A1–A2 |
| A6 | Workload and bounded-phase energy analysis | Energy dimension of RQ4; later RQ5/RQ6 inputs | A1–A2 |
| A7 | Normal secure-boot comparisons | Direct firmware-authentication comparison in RQ5 | A1–A3 |
| A8 | Frozen report exports and cross-domain evidence summary | Chapter 5 outputs and RQ6 support | A1–A2; consume completed domain extensions |
| S1 | Existing bare-metal benchmark results | Supporting RQ1/RQ2/RQ5 reference | A1–A3 and benchmark evidence |
| S2 | Existing OTA lifecycle results | OTA aspects of RQ5 and migration discussion | A1–A3, A7 and OTA evidence |

Implement A1 and A2 first and start using them on pilot runs immediately. Continue collecting experiments while adding the remaining domains. A3–A7 need not wait for one another except for their stated dependencies. S1 and S2 are evidence-gated: implement their analysis when the underlying experiment capability and records exist, not as a prerequisite to the first notebook. Run A8 whenever a research snapshot is needed; unsupported sections remain explicitly incomplete.

The thesis's Table 3.8, printed p.36, distinguishes primary experiment families, per-build observations, repeated handshakes and representative-only energy collection. It identifies RQ6 as synthesis rather than a separate execution family. These distinctions determine the priorities above. Deferring S1/S2 implementation does not remove the corresponding claims or sections from the thesis: unsupported content must remain outstanding unless the thesis scope is explicitly revised.

## Deliberate simplifications

Use a small Python analysis library, a batch command, CSV datasets with an explicit schema/metadata file, and Jupyter notebooks using pandas, NumPy and Matplotlib. Reuse current compatible dependencies and framework tooling. Do not upgrade unrelated packages to obtain the latest releases. Add only the dependencies required by the selected request and pin them using the repository's existing mechanism.

Use CSV for initial scalar tables. Do not make a Parquet migration a prerequisite. The shared loader must enforce column types, identifier handling, integer timestamps, units and null semantics. Retain large raw energy traces and PCAPs in their existing formats; read selected traces when required. Do not load all samples and packets into one campaign-wide table.

The initial proposed generated products are a run table, a timing-observation table, an issue table and a dataset metadata/index file. Their final filenames and repository locations must be selected after inspecting existing ownership and interfaces. Later requests add only the tables needed for their domain. Prefer a notebook-ready pivot/view over duplicating every representation on disk.

Do not build a dashboard, database server, generic plugin framework, workflow scheduler, automatic experiment rerunner, publication portal, universal statistical engine, automatic thesis writer, or universal migration score.

## Common instructions for every implementation request

Apply this section with one selected request below.

Read the current `AI_BUILD_GUIDE.md` first, then `docs/001_ai_feature_request_workflow.md` and the relevant current architecture/implementation. In direct-repository sessions inspect the working tree; in upload-based sessions request only the exact needed files and non-secret evidence artifacts. Inspect existing tests, dependency declarations, analysis commands and deferred-test entries. Do not assume that descriptions in the thesis or an earlier request are the current on-disk schema. Resolve discrepancies through source and recorded evidence; identify methodological conflicts rather than silently changing their meaning.

Implement only the selected request. These are offline analysis requests: do not change STM32/ESP32 firmware, instrumentation, bootloader behaviour, capture contracts, experimental profiles, network topology, or experiment execution. Do not trigger builds, signing, flashing, gateway access or new measurements. Where an existing offline analyser must run, use its local analysis path only. Missing evidence is an analysis limitation, not authorisation to implement the missing experiment capability.

Keep the sealed run-capture record unchanged. Use the recorded resolved case and provenance, not today's YAML, to interpret historical runs. Reuse existing integrity validation. Retain direct-input hashes, source record references, parser/metric/schema versions, selected inputs and parameters, and output hashes. Keep per-run derivatives under the established run-local analysis namespace; cross-run products must have their own generated output location and lineage. Never update or reseal a raw manifest to insert derived metrics. Unknown schemas, conflicting IDs or mismatched input identities must produce explicit diagnostics, not guessed compatibility.

Keep framework run, intra-run iteration, timing invocation, firmware build, energy interval and network flow identities distinct. Preserve all encountered attempts and explicit retry links. Do not infer unobserved attempts or completed iterations. Separate execution outcome, raw-capture acceptance, analytical validity, and inclusion in a particular comparison. Mark unavailable values with a reason, never numerical zero. A valid observed zero remains zero. Do not let an invalid optional channel automatically invalidate unrelated supported measurements.

Default analyses must retain pertinent failures and avoid automatic outlier removal. Record any explicit exclusion with its reason and affected metric/comparison. Report unknown outcomes separately; do not turn missing evidence into success or a known failure stage. Keep positive experiments and deliberate negative-validation cases separate. Use comparison rules that hold applicable controls fixed; absent controls cannot silently count as matched.

Every request must reuse the shared loader, identity, validity, summary and export conventions established by earlier requests. Preserve backward compatibility or version a deliberate schema change. Document metric meaning, unit, scope, evidence requirements, derivation and limitations alongside implementation.

Add deterministic unit fixtures with hand-checkable expected values. Synthetic data must be labelled as test data, not experimental evidence. Add local integration tests for affected command, container, notebook, external-tool and export boundaries; no hardware, SSH, brokers, credentials or live network access should be required by offline tests. Use a narrowly selected, sanitised real capture for a parser smoke check when available. A reconstructed/sanitised fixture must not pretend to retain the original run's sealed integrity identity. Unit tests alone do not establish compatibility with real recorded formats. Report missing real-evidence validation explicitly.

Use Linux/bash and the established Docker wrapper. Document the exact batch, interactive notebook, clean-kernel execution and verification commands actually supported after implementation. Update the existing canonical documentation owners; do not create a new document hierarchy for each request. Provide the required implementation completion report and replacement artifacts under the current AI workflow. Do not commit or push without explicit authorisation. Never package secrets, TLS key-log contents, private keys, real `.env` files or unrelated raw result trees into replacement artifacts or reports.

The thesis source for capture/analysis separation is §4.9.2, printed p.79. Evidence and testing constraints are also mandatory in the supplied build guide, §§7–10.

---

## IMPLEMENTATION REQUEST A1 — Export a minimal current-format timing dataset

**Objective:** Turn selected existing run records into a trustworthy dataset that can be inspected immediately, without implementing every measurement type.

**Inspect first:** Current manifest/provenance validation; resolved-case snapshots; STM32 result decoding and metric extraction; current Ready Metrics and Ready Metrics 2 records; repeated-handshake record structure if available; applicable tests and command ownership. The minimum useful real examples are one successful relevant run and one failed/incomplete run. Do not ask for whole result directories when selected artifacts suffice.

**Implement:** One offline batch entry point accepting explicit input run directories or an explicitly selected results root, and a separate generated output destination. Snapshot the discovered input list. Initially support only the current verified evidence format.

Produce a run inventory containing recorded configuration/build identities, applicable controls, workload, network condition, execution outcome, capture acceptance and available repetition/iteration identity. Produce timing observations for the outer TLS handshake, MQTT readiness, and the six Ready Metrics 2 timing measures when supported: RTFB, RTLB, TTFB, TTLB, ReqTFB and ReqTLB. Preserve their actual timestamp origins and clock provenance. Missing reset handoff must not silently become application-start time. Preserve iteration identity where it exists; do not manufacture per-iteration records from an aggregate.

Produce an issue table and metadata/index file recording supported schemas, definitions, dtypes, null rules, direct-input hashes, source record references, parser version and generated outputs. Provide a small typed Python loader and a notebook-ready timing view. Retain failed and unreadable inputs in the inventory/diagnostics rather than silently dropping them. Repeated input paths must not duplicate observations; distinct retry attempts remain distinct.

Use existing scalar extraction where valid. Do not redesign the parser stack to support hypothetical future formats. Verify consumed artifacts and reuse the established capture validation; distinguish an unavailable unrelated artifact from corruption of an input required for a metric.

**Acceptance:** An offline invocation produces loadable tables from selected evidence; each metric traces to source evidence; failed/incomplete runs remain visible; missing values remain null with reasons; duplicated inputs do not inflate counts; changing a consumed artifact is detected; all raw hashes remain unchanged. Known-answer timestamp fixtures establish each timing formula, including missing/invalid boundary cases. Repeated ingestion yields equivalent sorted data and declared provenance differences only.

**Out of scope:** Cryptographic phase attribution, memory accounting, energy integration, PCAP decoding, inferential statistics, new firmware measurements and legacy-format migration.

**Usable outcome:** Timing measurements from existing runs can be loaded and compared manually without copying numbers from logs.

**Thesis basis:** §3.4.1 and Table 3.6, printed pp.31–33; §§4.9.1–4.9.2, printed pp.77–79.

---

## IMPLEMENTATION REQUEST A2 — First comparison notebook and summary library

**Objective:** Produce useful plots, tables and failure accounting from A1 before integrating additional domains.

**Inspect first:** A1's delivered schemas, loader, issue model and commands; existing Python/container dependency handling; selected campaign controls and representative datasets. Do not select a historical baseline by filename alone.

**Implement:** Reusable summary/comparison functions and one starter notebook, with the dataset, filters, named baseline and matching controls in a clear configuration section. The notebook consumes A1 tables and calls tested functions; it must not independently parse raw files.

Provide inventory/completeness counts, separate execution and measurement-validity summaries, per-condition runtime distributions, counts of contributing runs/iterations, median, quartiles/IQR and configurable relevant percentiles. Compare explicitly matched configurations using absolute differences and percentage differences where the baseline is non-zero. Do not require identical ELF or credential hashes when those identities necessarily change with the declared treatment; retain them for provenance and check the applicable controlled properties instead. Refuse an unsupported matched interpretation when controls conflict or are unknown; absolute results remain available.

Initially make independent framework-run observations the supported inferential unit. Add one documented run-level bootstrap method for a selected continuous summary and one documented confidence-interval method for independent binary completion outcomes. Fix the resampling seed and retain parameters. Suppress inferential output with an explicit reason where the sample structure or count does not support the method. Repeated intra-run observations remain descriptive until A4 supplies explicit per-run summaries. No generic hypothesis-test selection engine is required.

Separate success-conditional latency from completion outcomes. Excluded infrastructure attempts and unknown outcomes remain visible with explicit denominator rules. Timed-out attempts are not successful latency samples at the timeout threshold.

Provide a timing-distribution figure, matched-difference figure and completion/completeness table, with units, counts and baseline labels. Export summary CSVs and figures. Support documented interactive use and clean-kernel execution through the established Linux/Docker workflow, preserving notebook authentication and binding an interactive server locally rather than exposing it publicly.

**Acceptance:** A clean-kernel execution reproduces fixture summaries/figures without manual cell ordering; arithmetic and denominators are known-answer tested; an invalid comparison is flagged; zero baselines do not produce infinite percentage changes; a deliberately failed notebook cell fails automated execution; missing optional measurements do not crash the notebook. A real-data smoke run is reported separately from synthetic tests.

**Out of scope:** Dashboard, report website, automatic experiment execution, new metric parsers, advanced statistical models and automatic scientific conclusions.

**Usable outcome:** Initial RQ1 timing comparisons, RQ4 application comparisons and dataset-quality inspection are practical at this point. This is the first usable release, not a claim that either RQ is fully answered.

**Thesis basis:** §§3.6.4 and 3.7, printed pp.41,43–44; Chapter 5 baseline and application sections.

---

## IMPLEMENTATION REQUEST A3 — Application memory and firmware-footprint comparisons

**Objective:** Add the resource measurements required by RQ1/RQ2 without changing the measurement implementation.

**Inspect first:** Current memory decoders and emitted records; maintained accounting definitions; target memory-region ownership; retained ELF/map/size outputs and build identity; task-stack and heap allocation relationships. Inspect relevant source only to establish the semantics of retained measurements.

**Implement:** Import existing application static/Flash/image evidence once per unique build and existing runtime heap, stack and workspace measurements at their recorded scope. Add a build/resource table and runtime observations that use A1 identities and lineage.

Keep region, lifetime, reservation, allocated amount and observed use distinct. Preserve run-lifetime high-water values as run-lifetime measurements; do not label them per-handshake peaks unless the measurement was reset/scoped accordingly. Avoid double counting a heap's static backing array, heap-allocated task stacks and workspace regions. Report regional measurements separately where a combined requirement is not justified. A sum of independently observed regional peaks must not be labelled an observed simultaneous whole-system peak.

Extend the existing comparison functions/notebook with measured RAM and Flash values and matched absolute/percentage changes. Display absent evidence rather than replacing it with configured capacity. Keep native byte counts; display KiB with an explicit conversion. Treat repeated references to one build as one static-footprint observation, not repeated static measurements.

**Acceptance:** Known-answer region fixtures detect double counting, reservation/use confusion and unit errors; build deduplication is tested; run-scope memory is not duplicated into independent iteration samples; a real supported profile comparison retains source/build references; unsupported combined totals remain unavailable with explanation. Earlier A1/A2 outputs and notebook behaviour remain compatible.

**Out of scope:** New memory instrumentation, allocator changes, linker-layout changes, memory optimisation, new wolfBoot profiling and a universal MCU memory estimator.

**Usable outcome:** RQ1/RQ2 comparisons now show measured resource cost beside timing, with explicit accounting limits.

**Thesis basis:** §3.6.2, printed p.39; §4.3.4 and Table 4.13, printed pp.64–65.

---

## IMPLEMENTATION REQUEST A4 — TLS attribution and repeated-handshake analysis

**Objective:** Explain the TLS timing results through the recorded protocol/security/primitive observations and preserve the experimental structure of repeated handshakes.

**Inspect first:** Existing timing-event/aggregate decoder, semantic event IDs, expected-coverage rules, overflow indicators, invocation hierarchy and repeated-handshake records. Verify current clock semantics from records and source rather than copying potentially older DWT descriptions from the draft.

**Implement:** Import recorded protocol-phase, security-function and cryptographic-operation timing with run, iteration, sequence, parent, operation identity, count, clock and validity. Keep aggregate-only evidence aggregate-only. Preserve incomplete spans, overflow and unexpected/missing required operations as explicit findings according to the selected configuration and reached execution stage.

Generate bounded comparison views for KEX, certificate-family and server-versus-mutual authentication, holding the other applicable dimensions fixed. Show applicable operation counts and elapsed measurements. Client signing must be not applicable in server-only mode, not measured zero.

Do not sum inclusive nested measurements into a disjoint 'Total Crypto' value. Do not interpret handshake time minus recorded crypto as measured network delay. Do not convert in-RTOS elapsed observations into isolated primitive benchmark measurements.

For repeated handshakes, retain every observed iteration and its outcome, report runs and handshakes separately, and add clearly defined per-run summaries. Feed per-run summaries into A2's run-level inference only with the estimand explicitly labelled, such as the across-run median of within-run handshake medians. Pooled handshake percentiles may be shown descriptively but must not be presented as independent-run inference. Missing iteration outcomes must remain unknown, not inferred from the configured repetition count.

**Acceptance:** Nested-event fixtures cannot be double-counted; unmatched spans and overflow are detected; aggregate-only records do not create invented invocations; two fixture runs with unequal numbers of handshakes are not silently weighted as independent individual experiments; profile-specific not-applicable/missing events are distinguished. Include one TLS-attribution notebook section or dedicated notebook using shared functions.

**Out of scope:** New firmware hooks, instrumentation repair, inferred exclusive CPU cost, benchmark execution and automatic causal diagnosis.

**Usable outcome:** RQ2 has operation/phase evidence and controlled comparisons rather than only total-handshake plots.

**Thesis basis:** §3.6.1, printed pp.37–39; §3.4.1 repeated workload, printed p.33; §4.10.2, printed pp.82–83.

---

## IMPLEMENTATION REQUEST A5 — Network and impairment comparison reports

**Objective:** Support RQ3 with condition-response plots and the retained transport evidence needed to interpret them.

**Inspect first:** Existing offline packet analyser, its raw inputs, derived schema, tool/version provenance, flow selection and interval definitions; requested/effective impairment records; a baseline capture and an impaired capture with attributable STM32 workload traffic.

**Implement:** Consume existing packet-derived outputs when their lineage matches the retained raw inputs. Where necessary, invoke the existing offline analysis path locally; add only the bounded missing extraction needed for this request, not a replacement packet-analysis framework.

Produce per-workload-flow/per-defined-window summaries of available traffic bytes, packet/TCP-segment counts, retransmission indicators/retransmitted bytes, segmentation or fragmentation observations, and negotiated TLS identities. Define byte layer, direction, inclusion of retransmissions, capture point and interval. Do not call whole-capture bytes 'TLS handshake bytes'. Keep missing decryption separate from missing PCAP, and preserve packet-level metrics that do not depend on decryption.

Retain configured, verified-applied and observed network properties separately. Add separate rate, RTT, loss and MTU comparisons for matched TLS/workload conditions, combining A2 timing/completion summaries with transport measurements. Mixed-impairment observations remain separate rather than being labelled one-factor comparisons.

Provide a selected-run packet diagnostic table or timeline to examine retransmission/segmentation evidence. Do not equate analyser flags with established cause. Do not merge gateway timestamps with STM32 timestamps without an evidenced alignment; flow association alone is not clock synchronisation. Keep raw and derived packet provenance available locally without exporting TLS secrets or payloads.

**Acceptance:** Multi-client fixtures exclude broker health-check/responder/reporting flows; unrelated packets do not change target metrics; stale derived analysis is detected; missing key logs leave non-decrypted TCP observations usable; impairment axes/units and control matching are tested. Include a local external-tool integration check when that boundary is changed.

**Out of scope:** Live capture, impairment changes, new network campaigns, TCP simulation, automatic root-cause verdicts and universal packet decoding.

**Usable outcome:** RQ3/RQ4 response curves can be examined alongside packet evidence without manually joining results.

**Thesis basis:** §§3.4.2 and 3.6.3, printed pp.33,40; §4.6, printed pp.68–70; Chapter 5 §5.4.

---

## IMPLEMENTATION REQUEST A6 — Energy totals and bounded phase correlation

**Objective:** Add usable workload energy comparisons and a small set of evidence-supported phases, not a complete energy attribution system.

**Inspect first:** Current acquisition decoder and validity rules, acquisition/sample formats, interval identity, cumulative-energy representation, paired GPIO timestamps, calibration/firmware metadata, and representative energy-enabled evidence. Verify the actual current record format before selecting a computation path.

**Implement:** Reuse existing validated decoding/integration. Export recorded-interval duration, energy and derived average power, with the electrical boundary, calibration, sample counts/gaps and acquisition validity. Use cumulative energy where that is the authoritative defined representation; do not apply a second integration over already-integrated energy.

Implement the thesis's per-interval affine mapping between paired STM32 and ESP32 boundaries. Initially derive only whole-workload, TLS-handshake and application-transfer energy where the trace and boundaries support them. Compute phase energy from cumulative-energy differences at the mapped boundaries, interpolating only within valid bracketing samples under a documented policy. Do not extrapolate outside acquired coverage or bridge rejected gaps. A valid instrument-local total may remain usable when missing clock pairs make device-phase attribution unavailable.

Add a selected-run trace with supported phase annotations and per-configuration energy/average-power comparisons to the existing report workflow. Keep reporting time and measurement time distinct according to recorded boundaries. Do not trim away time solely because it appears to be reporting. Preserve absent energy as not captured/not applicable rather than zero. Do not pool whole-interval energy with phase-specific energy or observations using incompatible electrical boundaries/calibration policies.

**Acceptance:** Synthetic constant-load, offset/drift, boundary interpolation, malformed-pair, gap and multi-interval fixtures have known answers; no clock-domain cross-join is possible; total and phase energy remain distinct; unit conversion and average-power calculations are tested; one real trace can be followed from source samples to the exported metric. Report acquisition qualification limitations separately from mathematical parser tests.

**Out of scope:** ESP32/STM32 changes, recalibration, new acquisition scheduling, sub-sample primitive energy claims, idle subtraction and battery-lifetime modelling.

**Usable outcome:** RQ4 gains representative workload energy comparisons without waiting for fine-grained attribution.

**Thesis basis:** §3.6.5, printed pp.41–43; §4.8, printed pp.73–76; Table 3.8's representative-only energy policy.

---

## IMPLEMENTATION REQUEST A7 — Normal secure-boot result analysis

**Objective:** Deliver the direct classical-versus-ML-DSA firmware-authentication analysis needed by RQ5 independently of OTA implementation.

**Inspect first:** Current secure-boot result/diagnostic decoder, mailbox validity and clock provenance, bootloader/application build identities, existing RAM measurements, relevant signed-image metadata and representative integrity-only and signed-boot evidence.

**Implement:** Export integrity verification, authenticity verification, application-start/boot timing where recorded, observed verification outcome and handoff identity. Preserve each actual boundary; integrity-only verification and signed authenticity verification are not interchangeable total-boot measures. Convert cycles only with supported recorded clock provenance and do not assume bootloader/application clock frequencies match.

Reuse A3's build/resource accounting for bootloader static/Flash/image measurements and recorded boot-time memory. Keep bootloader and application lifetimes separate. Distinguish actual image metadata/signature use from reserved header or bank capacity, using recorded layout rather than constants copied from the thesis.

Add profile comparison tables/plots for timing, memory, bootloader/image footprint and outcomes, with matched application/image properties and configuration controls. Integrity-only is an integrity reference, not a classical signature-authentication equivalent. Deliberate rejection-validation cases must be labelled separately: expected rejection may be a passed validation case, but is not a successful normal boot. Missing application MQTT evidence in a rejected boot must be interpreted according to its negative capture class, not silently converted into an ordinary workload failure.

Reuse A6 phase-energy outputs only where matching boot interval evidence exists; missing energy must not block non-energy comparisons.

**Acceptance:** Fixtures distinguish integrity/authenticity/boot boundaries, invalid mailbox/clock evidence, positive handoff and expected rejection; image/build identities remain traceable; bootloader/application RAM is not added as concurrent demand; matched controls are tested. Include a documented real-evidence comparison when suitable records exist.

**Out of scope:** Bootloader changes, new RAM profiling, new signed images, flashing, OTA execution, trust-policy changes and key recovery implementation.

**Usable outcome:** The main normal-boot portion of RQ5 can be analysed independently of the later lifecycle work.

**Thesis basis:** §3.3.4, printed pp.30–31; §4.7.3, printed p.72; Chapter 5 §§5.2.2 and 5.5.1.

---

## IMPLEMENTATION REQUEST A8 — Frozen research outputs and RQ6 evidence synthesis

**Objective:** Make the completed analyses repeatable and directly usable in Chapters 5 and 6, without building a report platform.

**Inspect first:** The implemented domain outputs, current summary methods/notebooks, thesis result-section requirements, explicit analysis choices and available campaign inventory. Do not assume every request or experiment family is complete.

**Implement:** One offline report-build entry point that takes an explicit dataset/analysis selection and produces a frozen input inventory, analysis specification, metric coverage report, shared summary tables, figures, LaTeX table fragments and a static HTML rendering of the selected notebooks. Use the same summary data for tables and figures. Do not edit the thesis or automatically write results/discussion prose.

Retain selected/excluded run identities and reasons, baseline mappings, contributing measurement counts, statistical method/estimand/seed where applicable, parser/metric versions, source/output hashes and software environment identity. Make data selection stable: adding unrelated runs under `results/` must not change an existing snapshot. Rebuilding a snapshot must verify its dependencies rather than silently pick up changed inputs. Scientific tables and selections should reproduce deterministically; any environment/render-time metadata differences must be documented rather than called bit-for-bit identical.

Add a cross-domain evidence summary for key establishment, endpoint authentication and firmware authentication containing actual measured costs, matched differences, outcome evidence and limitations. Optional operator-supplied budgets may produce bounded headroom/requirement checks; missing evidence is 'not assessed', not passed. Use observed combined configurations for combined-resource conclusions. Do not add isolated Flash/RAM deltas from different builds and present the sum as measured simultaneous feasibility. Do not derive cryptographic security strength or migration priority from runtime measurements.

Provide an RQ/Chapter 5 coverage view distinguishing implemented analysis, available evidence and supported comparisons. Incomplete sections must be visible. Keep secret-bearing inputs local; export only explicitly allowed scalar metadata, figures and tables. This is not a public raw-data release mechanism.

**Acceptance:** One clean offline command produces the available report bundle; table/figure numbers agree; missing domains are reported rather than invented; a modified input fails snapshot verification; an unrelated new run cannot change a frozen snapshot; private-key/key-log fixtures do not leak into exports; earlier notebook workflows continue to work.

**Out of scope:** Dashboard, public archive upload, full thesis compilation, automatic scientific conclusions, generic decision scoring, advanced new statistics and unsupported migration rankings.

**Usable outcome:** Chapter 5 results and Chapter 6 evidence summaries can be regenerated instead of manually transcribed. Completing this software request does not establish that every RQ has enough experimental evidence.

**Thesis basis:** §4.9.2, printed p.79; Chapter 5, printed pp.87–93; §§6.2.5–6.2.7, printed pp.96–97.

---

## IMPLEMENTATION REQUEST S1 — Import existing bare-metal benchmark results

**Activation gate:** Implement only when the maintained benchmark and actual retained outputs are available. It is not a prerequisite to A1–A7.

**Objective and scope:** Inspect the current benchmark schema/decoder and import operation, algorithm/parameter set, recorded cycles, result state, repetition structure, build identity and available memory/footprint. Produce a compact reference table and cycle-comparison figure using A1/A2/A3 functions. Preserve cycles as the primary result. Derived elapsed time requires the benchmark's own recorded frequency. Keep setup, reporting and actual measurement boundaries as the benchmark defines them.

Do not merge primitive samples with in-RTOS TLS invocation samples as though they measure identical quantities. External pqm4/published values are not required for this first importer; they require separately supplied, attributed records and comparable operation/parameter/implementation context, not guessed equivalence or automated scraping.

**Acceptance:** Known-answer cycle/unit fixtures, failure handling, identity and repetition tests, plus a supported real-record smoke check. No benchmark firmware change or execution is required. Exported reference tables integrate with A8 when present.

**Out of scope:** Implementing or running the benchmark harness, benchmarking new profiles, external reference collection and performance optimisation.

**Thesis basis:** §3.6.1, printed p.39; §4.10.5, printed p.85; Chapter 5 §5.2.3 and Table 5.4.

---

## IMPLEMENTATION REQUEST S2 — Import existing OTA lifecycle evidence

**Activation gate:** Implement only when current OTA capability and its retained records support the specific scenario. Do not implement missing OTA capability inside an analysis request.

**Objective and scope:** Inspect existing records and add two outputs: an OTA-enabled-versus-disabled resource comparison using A3/A7, and a stage/outcome table for evidenced application update, bootloader migration, or signing-key rotation/recovery scenarios. Keep scenario types separate.

Retain source/candidate/staged/final image identities, actual verification and bank-selection evidence, and available transport, staging, activation/reset, verification and application-start measurements. Preserve clock origins across resets. Keep application/gateway operations distinct from wolfBoot operations; mark stages not executed in wolfBoot as not applicable to bootloader runtime measurement. Do not invent a software-copy/swap stage for hardware bank activation.

A completed transport is not a completed update. Record final execution/verification evidence separately. A scenario lacking authenticated transition or final-image evidence must remain unconfirmed even if another stage succeeded. Reuse A6 energy only for applicable evidenced intervals; absent energy does not block other lifecycle results.

**Acceptance:** Fixtures distinguish delivery success from verified activation and final-image execution, positive and expected-negative scenarios, different clock domains and missing stages. Existing normal-boot reports remain unchanged. Integrate available scenario outputs and explicit gaps into A8.

**Out of scope:** OTA firmware, recovery-key provisioning, bootloader replacement mechanisms, bank-switching changes, new lifecycle experiments and inferred successful transitions.

**Thesis basis:** §3.4.3, printed p.34; §4.7.4, printed pp.72–73; Chapter 5 §§5.5.2–5.5.4 and Tables 5.15–5.17.

## Final prioritisation

Protect the first usable release: A1 and A2 must not expand into a complete framework redesign. Use that release on pilot measurements and fix demonstrated parsing/definition errors before building more visualisation features. Add A3–A7 against actual available evidence. Include S1/S2 when their records exist and their thesis sections remain in scope. Use A8 to freeze whatever is supported, with the remaining research gaps explicit.

Confidence is high that this sequence maps to the supplied RQs and evidence model. Delivery duration, existing code reuse and complete metric availability remain unverified; no day estimate or hardware-success claim is made.
