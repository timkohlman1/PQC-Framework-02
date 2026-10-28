# Campaigns and thesis evidence collection

This guide owns batch execution and collection recipes. Use the
[queue](014_campaign_queue.md) for interactive local profiles,
[configuration reference](011_experiment_configuration.md) for execution semantics,
and [results reference](012_results_and_analysis.md) for metric/analysis contracts.
All commands start at the repository root; replace bracketed result paths with
exact retained paths and use fresh analysis output directories.

## Run and resume a campaign

Resolve offline to inspect expanded cases before laboratory work:

```bash
./scripts/dev.sh python scripts/resolve_campaign.py baseline
./scripts/dev.sh campaign-gateway baseline
```

The gateway command owns preparation/build/sign/flash and runtime repetitions.
It may reuse compatible brokers and retain a condition across repetitions.
Runtime failures remain evidence while later slots continue. Preparation failures
block the affected firmware group's pending slots; cleanup permits later groups.
Uncertain cleanup/condition verification stops execution. A completed matrix with
failures exits 1; all-success exits 0. Planned counts are not successful-capture counts.

Resume the exact recorded campaign, with unchanged source/profiles:

```bash
./scripts/dev.sh campaign-gateway --resume results/campaigns/<campaign-run>/campaign-manifest.json
```

Ordinary resume retries failed/missing work and validates retained successes. Before
pending repetitions it prepares and flashes expected firmware again. Changed image
hashes can invalidate earlier successes in that group. Queue preservation instead
binds each old capture to its original preparation, as described in the queue guide.

`--stop-on-error` requests a pause on failure. Resume-only `--accept-failed` or
`--retry-failed` records explicit decisions; `--defer-failed` leaves older failures
unresolved while unfinished work proceeds. `--pause-file` requests cooperative
pause after the active operation and cleanup; exit 75 denotes pause, not completion.
Gateway lease contention waits normally. Do not update an active frozen collection
or run another workflow against its laboratory resources outside that coordination.

## Focused pilot recipes

Campaign YAML owns exact dimensions and counts; resolver output is the preflight
inventory. `configs/analysis/thesis_campaigns.json` lists the thesis families:
KEX, certificate/authentication, repeated TLS, payload/chunk, separate rate/RTT/loss/
MTU sweeps, energy and OTA-capability overhead. Plaintext application/network/energy
companions provide matched no-TLS controls. The `secure_boot`, `secure_boot_stack`
and `baremetal_benchmark` campaigns measure separate boot/primitive boundaries.

Pilot repetitions are grouped by firmware/condition, not randomized or balanced.
Hardware resets alone do not establish independence. Choose final counts using
pilot variability and retain all attempted/blocked outcomes. OTA-capability overhead
is a normal boot comparison; actual update/rollback/migration needs the
[OTA workflow](009_dual_bank_ota_workflow.md). Application energy is not boot energy.

### Five-family TLS authentication comparison

`thesis_authentication` specifies RSA-3072, ECDSA P-256, ECDSA P-384, ML-DSA-44
and ML-DSA-65, each in server-only and mutual mode: **10 conditions × 30 fixed
attempts = 300 planned slots**. This is a design, not completed evidence.
P-256 key establishment, a root/intermediate/leaf X.509 hierarchy, Ready Metrics 2
(204800-byte payload, 400-byte chunks, QoS 0), baseline network, integrity-only
single-bank boot, no standby keys and normal timing instrumentation remain fixed.
The canonical profile retains energy acquisition; freeze and record the same
acquisition policy for every condition rather than mixing earlier energy-off runs.

Before any queue creation or collection, review the responder audit, commit all
required changes with explicit authorization, check the parent and recursive
submodule working trees, pass unit/integration and applicable hardware qualification,
and freeze source/component revisions, build options, broker/responder identity,
container image, environment and final campaign counts. A dirty or unverified state
blocks the main collection. The current request leaves queue creation on hold.

Use the resolver to inspect the matrix offline. Once the gate and explicit execution
approval are satisfied, collect the five families in the declared campaign order,
server then mutual for each family, with 30 fixed slots per condition. Record actual
order/timestamps and environmental controls; this grouped order is not randomized.
Preparation captures remain separate. Record failed, blocked and unexecuted slots;
never retry merely to reach 30 successes. If preparation blocks a group, retain that
fact rather than silently treating it as 30 measured failures. Any later recovery
batch has its own identity and does not replace the fixed cohort.

Validate certificate family, negotiated signature scheme and P-256 group, payload
completion, capture integrity, metric eligibility, timing event coverage, firmware
and source identities, packet corroboration and gateway cleanup. Publish manifests,
raw captures, an all-slot outcome inventory, metric-specific eligible n and missing
reasons, and median/Q1/Q3/observed-p95 descriptive tables. Preserve the prior
eight-condition cohort separately; do not append ML-DSA-44 to that cohort.

Existing ML-DSA-44 firmware-authentication evidence belongs to the selected normal
boot and separate stack cohorts. Adding TLS authentication does not itself justify
recollecting firmware authentication, RQ4 migration, signing follow-ups or the
small-memory experiment. Additional conditions require a separate comparison
rationale and approved plan.

### Network trial

`network_trial` selects Ready Metrics 2, hybrid TLS/ECDSA-P256 server authentication,
integrity-only single-bank boot and no energy. Its five conditions vary rate, RTT,
loss or MTU individually against enabled `trial_reference`, with three attempts
each. Configured limits are not measured throughput, RTT or loss.

```bash
./scripts/dev.sh python scripts/resolve_campaign.py network_trial
./scripts/dev.sh campaign-gateway network_trial
./scripts/dev.sh python scripts/analyse_results.py import --source results/campaigns/<network-trial-run> --output results/analysis/exports/network-trial-01
./scripts/dev.sh python scripts/prepare_network_selection.py --dataset results/analysis/exports/network-trial-01/source-dataset --output results/analysis/network-trial-flow-selection
for axis in rate rtt loss mtu; do
  ./scripts/dev.sh python scripts/analyse_results.py select \
    --export results/analysis/exports/network-trial-01 --filter 'workload="ready_metrics_2"' \
    --recipe network --comparison "configs/analysis/comparisons/network_trial_${axis}.json" \
    --network-selection results/analysis/network-trial-flow-selection/network-selection.json \
    --output "results/analysis/network-trial-${axis}.json"
  ./scripts/dev.sh python scripts/analyse_results.py publish \
    --spec "results/analysis/network-trial-${axis}.json" --name "network-trial-${axis}"
done
```

Review `selection-status.json`. The helper intersects verified broker client identity
with retained workload flows; missing identity, ambiguous ports and NAT mismatches
remain unselected. Explicit alternate attribution needs retained evidence. Unknown
controls can refuse matched deltas while absolute observations remain usable. A
blocked condition may have no captured row: preserve the campaign failure and
make any reduced analysis selection explicit. No raw captures means no dataset.

### TLS matrix with energy

`tls_matrix_energy` selects three KEX choices (`secp256r1`, `SecP256r1MLKEM768`,
`ML_KEM_768`), two certificate families (`ecdsa-p256`, `mldsa65`) and server/mutual
authentication: twelve conditions, ten planned attempts each. Ready Metrics 2 uses
200 KiB payloads and 400-byte chunks. Baseline network, integrity-only single-bank
boot and minimal UART remain fixed; stack/early-UART diagnostics are disabled.

Every case requires the persistent provisioned [energy instrument](010_esp32_ina228_energy_instrument.md).
The campaign does not flash or command it. These selections establish neither
hardware interoperability nor valid metrics; qualification remains DTR-TLS-MATRIX-ENERGY.

```bash
./scripts/dev.sh python scripts/resolve_campaign.py tls_matrix_energy
./scripts/dev.sh campaign-gateway tls_matrix_energy
./scripts/dev.sh python scripts/analyse_results.py import --source results/campaigns/<tls-matrix-run> --output results/analysis/exports/tls-matrix-01
./scripts/dev.sh python scripts/analyse_results.py select \
  --export results/analysis/exports/tls-matrix-01 --filter 'workload="ready_metrics_2"' \
  --recipe timing --comparison configs/analysis/comparisons/tls_matrix_energy.example.json \
  --output results/analysis/tls-matrix-selection.json
./scripts/dev.sh python scripts/analyse_results.py publish --spec results/analysis/tls-matrix-selection.json --name tls-matrix
```

The preset uses P-256/ECDSA/server as baseline, keeps `independent_runs: false`,
and has no exclusions/unknown-control waivers. It retains the default exact-evidence-
class policy, so cross-family matched differences are refused. The analysis library
also supports explicit STM32 TLS/transport policies; selecting one still requires
all other matching controls and a justified question. Multi-factor deltas cannot
be called isolated KEX or certificate effects. Energy derivation uses the energy
recipe and explicit electrical-boundary annotations in the results reference;
this example selects timing.

For interactive use, launch `./scripts/dev.sh notebook`, open `notebooks/analysis.ipynb`
and select the export and recipe, or set `SPEC_FILE` to the saved selection.
Keep any chosen baseline within the filters. Notebook/PDF export procedures are in
[results](012_results_and_analysis.md#notebook-operation).

## Frozen thesis collections

The standard-library host coordinator invokes Docker for all framework work:

```bash
python3 scripts/collect_thesis_evidence.py plan --output results/thesis/collection-01
python3 scripts/collect_thesis_evidence.py status --output results/thesis/collection-01
```

Do not launch this coordinator inside `dev.sh python`. The default plan selects
`secure_boot`, `secure_boot_stack`, `thesis_kex`, `thesis_authentication` and
`thesis_application_plaintext`. Source definitions currently expand to 43 conditions
and 430 planned attempts at ten repetitions per condition. The plan's inventory is
authoritative. Use plan-only `--only`, `--repetitions N` and `--include-ota` for a
bounded alternative. OTA is omitted by default; `--skip-ota` is a compatibility alias
for that default. The OTA step checks eight selected lifecycle scenarios.

Planning freezes source/submodule identity, original/effective profiles and hashes.
Uncommitted source can be frozen, but cannot change during execution. Existing plans
do not acquire new templates or policies. The coordinator defaults energy monitoring to `off`.
Set `execution.energy_monitoring: auto` explicitly to enable the existing instrument
on supported deferred-reporting workloads; dedicated energy templates already opt in. The application interval in a boot
campaign cannot measure bootloader verification energy or multi-reset OTA energy.

Review the copied `annotations.json` before analysis. Its electrical-boundary and
client-IP values come from `configs/analysis/thesis_collection_annotations.json`
and are operator assertions, not independently measured facts. Confirm the actual
power rail, calibration reference and device-address evidence for every selected
capture. Use per-run network selections if attribution varies. Unknown attribution
leaves relevant comparisons unavailable; do not copy a historical lab address as
proof of current identity.

With the board, gateway, brokers, Wi-Fi and selected instrument provisioned:

```bash
python3 scripts/collect_thesis_evidence.py run --output results/thesis/collection-01
```

Execution is sequential. Repeat `run` to resume interrupted work; retained terminal
steps are validated and skipped. Failed/blocked attempts stay in denominators.
Use `run --retry-failed` only after reviewing their cause; prior attempts remain.
Cleanup failure stops the suite. No gateway lease is force-released.

Progress rows count finished attempts, including failed/blocked/skipped entries.
Preparation rows do not advance that counter. Detailed transcripts are retained
in each run's `console.log`, campaign explanations in `campaign.log`, and child
commands under `logs/`. `PQC_PROGRESS_TIMEZONE` controls timestamps; `NO_COLOR`
disables color. Source updates require a new acquisition plan.

## Reports and reanalysis

Collections automatically export bounded datasets, flat archives and numbered
frozen reports. To report a partial collection or corrected local attribution:

```bash
python3 scripts/collect_thesis_evidence.py report --output results/thesis/collection-01
```

After analysis-source changes, create a new report without rerunning hardware:

```bash
python3 scripts/collect_thesis_evidence.py report --reanalyze --output results/thesis/collection-01
```

This records original collection and current analysis identities in
`analysis-source.json`, preserving plan/profile integrity and previous reports.
It never authorizes hardware resume under changed source. `latest-report.json`
identifies the report/archive; numbered outputs retain selections, annotations,
datasets and `collection-gaps.json`. Use the report's verification command from
[results](012_results_and_analysis.md#flat-archives-and-frozen-reports-a8).

Exit 0 means scheduled workflow steps completed and a report verified, not that
all measurements/RQs are complete. Exit 1 retains workflow failures; 2 denotes
planning/source/report errors; 130 denotes interruption. Missing or skipped OTA
scenarios cannot produce a passing lifecycle verdict. Unsupported measurement
boundaries remain explicit gaps rather than inferred numbers.

For software validation and current laboratory qualification, use
[testing and deferred coverage](013_testing_and_deferred_coverage.md), especially
DTR-A5-TRIAL, DTR-TLS-MATRIX-ENERGY and DTR-THESIS-COLLECT.
