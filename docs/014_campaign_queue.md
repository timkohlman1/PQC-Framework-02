# Terminal campaign queue

The queue edits local profiles, freezes jobs, runs campaigns sequentially and
exports selected completed evidence. [Configuration](011_experiment_configuration.md)
owns execution semantics; [results](012_results_and_analysis.md) owns data meaning.

## Start and create a profile

Run on the Linux host, from the repository root:

```bash
python3 scripts/run_queue.py
```

The standard-library curses/SQLite interface requires at least 120 columns and
30 rows, plus one row per additional gateway. It invokes Docker through
`scripts/dev.sh`; launching it inside `dev.sh python` would require nested Docker.
`--directory results/<name>` selects another persistent queue. Profiles remain
shared under `results/profiles/` in this checkout, regardless of queue directory.

The Profiles tab starts empty. Tracked `configs/campaigns/` are templates, not
automatically enqueued or copied profiles. Press `n`, choose Blank or a template,
name the profile and edit its components, matrix, workload, execution and analysis.
Blank supplies a minimum one-case scaffold. Profile IDs accept letters, numbers,
underscores and hyphens and must be unique within the local collection.

The editor uses arrows/Enter to navigate and Space for choices. `P` previews YAML,
`V` validates every expanded case, `S` validates and saves, and Esc returns or
confirms discarding a draft. `e` switches a read-only view to editing. Integer
matrix values accept comma-separated values. The resolver enforces component
compatibility and limits of 10,000 cases and 1,000 repetitions. Invalid drafts
stay open with the error. Saves preserve unedited YAML sections; edited sections
may be reformatted. Files changed since opening cannot be silently overwritten.
Component profile files and tracked templates are never edited by this UI.

## Controls

| Context | Key | Action |
|---|---|---|
| All tabs | Tab or `1` / `2` / `3` | Switch Profiles / Queue / Completed; clear selections and highlights |
| Profiles | `n`, `v`, `e`, `D` | Create, view, edit or delete a local profile |
| Profiles | Space, `/`, `R` | Select multiple profiles, filter, reload |
| Profiles | `a` | Enqueue selection/highlight; optional repetitions override |
| Queue | `K` / `J` | Move a waiting entry up/down |
| Queue | `p` | Request cooperative pause |
| Queue | `r` | Resume unfinished work, deferring earlier failures |
| Queue | `t` | Retry failures and remaining work, preserving history |
| Queue | `f` | Accept recorded failures and continue unfinished work |
| Queue | Delete | Remove from scheduling while retaining the job folder |
| Queue / Completed | `N` | Create a new job from the frozen definition using current source/components |
| Completed | Space, `e` | Mark/unmark entries, export marked selection |
| Completed | `D` | Permanently purge the selected job after exact-ID confirmation |
| Main UI | `s`, `x` | Start worker; stop dispatch and request active-job pause |
| Main UI | `d` | Detach UI; worker continues |
| Main UI | `q` | Pause, wait for cleanup/worker exit and quit |

Tab switching does not cancel work. Select a row again before an item command.
A profile deletion requires its exact filename; it preserves queued copies and
results. A purge deletes job-local profiles, logs, captures and material, but
retains independent exports. Those exports can no longer verify deleted source
files. Active jobs, marked/in-progress exports and unresolved cleanup halts are
protected. Stop the worker before purging an unregistered retained folder.

## Frozen job identity and progress

Enqueueing retains original bytes as `profiles/input.yaml` and effective choices
as `profiles/campaign.yaml`, both hashed in the plan. Template identity/hash and
any repetition override remain recorded. Profile edits/deletion affect future
jobs only. `N` preserves the old frozen definition but resolves it under current
source/components, creates a new ID and starts its repetitions again. The original
plan hashes must still validate; pause active entries first.

Energy defaults to `off` for new queue plans. Set **Execution → Energy monitoring**
to `auto` to request the existing instrument for supported deferred-reporting
workloads. Dedicated energy templates opt in explicitly. Instrument selection alone
does not override an `off` policy. Provisioning, calibration and wiring remain
external prerequisites. Frozen jobs retain their recorded energy/failure choices,
including when legacy jobs are explicitly requeued; they are not rewritten by a
new default.

Rows distinguish REPS per case, CASES, TOTAL RUNS, OK/ERROR/TOTAL and REPEATS
(previous attempts). Errors include failed and blocked slots. Accepted failures
do not become successes. Counters come from campaign evidence; unreadable data
shows `?`. Export status applies to the current completed manifest version; retries
need a new export. Old exports remain retained.

The title shows current source SHA/date; rows show their frozen source identity.
`*` indicates dirty source, including submodules. Missing provenance is `unknown`.
Gateway status refreshes in the background: READY, IN USE, CONNECTION ERROR or
OFFLINE. It is advisory reachability/lease information, not physical power state;
dispatch still acquires the real gateway lease. The selected row shows recent
log lines and recorded failure reasons.

## Pause, failures and recovery

A cooperative pause finishes the current preparation or runtime operation, then
cleans up condition/broker state. It does not kill build/sign/flash to pause them.
`q` also waits for planning/export tasks and worker termination; an absent worker
with an active job is unverified cleanup, not a successful shutdown.

Each planned slot is attempted once. Runtime failures stay recorded while later
slots continue; preparation failures block the affected group's remaining slots,
then other groups can proceed after cleanup. At completion, unresolved failures
need retry or acceptance while the next eligible job can start. Acceptance records
an operator decision without changing failed captures or measurements.

**Execution → Valid workload failures** defaults to `pause`; `record` enables
qualified Ready Metrics 2 negative trials. Firmware-reported network timeout,
connection failure or measured failed handshake counts toward the fixed trial
count only with intact reporting, required capture/instruments/broker evidence,
verified conditions and cleanup. `trial-outcome.json` records classifier checks.
Missing reports/tools, unknown observer errors and unmeasured TLS setup failures
remain unaccepted. Policy acceptance is `policy_record_valid_failure`; the slot
remains failed. Export retains the outcome and unavailable timings as null.

Use the requested trial count as the denominator. Report failure fraction separately
from successful-transfer latency; at 100% failure the latter is unavailable. Do not
retry until a target number of successes. Explicit retries preserve prior attempts.
Older captures without the outcome marker are not automatically reclassified.

Resume restores expected firmware through normal preparation. Queue preservation
validates old successful captures against their original preparation/image hash,
so rebuilding does not repeat or relabel those measurements. Source/profile drift
prevents dispatch; restore the matching source or use `N` for a fresh job. Never
edit manifests or bypass source checks to manufacture completion.

If a source fix prevents resuming a frozen job, a targeted continuation can use
new local profiles containing only its unexecuted or acquisition-failed slots.
Retain the original job and captures, and record the old campaign hash, case and
repetition alongside each replacement slot and new job ID. Verify the selected
controls and fixed attempt counts before enqueueing. Keep measured workload
failures as outcomes; do not replace them merely to reach a success target.
Continuation captures retain their new source identity and require an explicit
analysis selection rather than silently pooling them with the old batch.

MQTT clients, remote capture groups, SSH and evidence/control operations have bounded
deadlines. Each campaign preparation/runtime subprocess also has a 1,800-second
watchdog and 90-second cleanup grace. `PQC_CAMPAIGN_OPERATION_TIMEOUT_SECONDS` can
select a positive finite override before starting the worker. This is per operation,
not a whole-campaign deadline; gateway contention retains its normal wait policy.
Timeouts are failed results, not automatically valid negative trials.

Unverified remote completion, unsafe cleanup or abrupt worker loss halts dispatch.
Inspect logs and [gateway ownership](002_host_gateway_setup.md#gateway-lock-and-recovery),
resolve the cause, explicitly resume/retry the entry, then restart dispatch.
The worker never force-releases a lease or changes authentication. A removed entry
is `removed`; an unregistered job folder is `retained`. Discovery does not schedule
or certify it. Incomplete removed/retained entries cannot be exported or auto-resumed.

## Export and inspect

Mark completed entries on Completed, then `e`. Export locks only that selection
and writes a fresh `results/queue/exports/<timestamp>-<id>/` containing `runs.csv`,
archive metadata and selection/provenance. The completion message points to the
shared analysis notebook. Changed completion
manifests, unresolved failures and incompatible annotations are refused.

Every job copies `configs/analysis/thesis_collection_annotations.json`; review
its electrical boundary and network attribution for the actual lab before export.
Local annotations may be corrected; select compatible annotations together.
For thesis tables and figures, launch `./scripts/dev.sh notebook` and open
`notebooks/analysis.ipynb`. Select the export and campaigns from its catalogue,
review counts and exclusions, preview, then save a named revision. The
[default analysis workflow](012_results_and_analysis.md#default-thesis-workflow)
records hashes and selection counts automatically.

Exports contain no generated notebooks. Existing exported notebooks and saved
outputs remain available as research artifacts. For custom exploration use
`load_archive()` in the shared notebook to retain nullable types and missingness;
see the [flat archive contract](012_results_and_analysis.md#flat-experiment-archive).

Local profiles, queue databases, captures and exports remain generated/ignored.
Their handling follows the [open-data policy](006_security_and_secrets.md).
Inspect `results/queue/jobs/<entry-id>/logs/dispatch-*.log` and
`results/queue/worker.log` (under the selected directory for non-default queues).

## Interactive MQTT migration comparison

Run on the Linux host:

```bash
python3 scripts/migration_compare.py
```

The wizard asks for the current **From** configuration and proposed **To**
configuration. Numbered options come from the maintained component profiles;
To offers **Unchanged** for applicable choices. It covers plaintext/TLS transport,
TLS key exchange, certificate family, server/mutual authentication, firmware
signing, firmware layout/OTA support, standby signing keys, network impairment,
and payload/chunk sizes. Plaintext skips TLS questions; integrity-only boot has
no standby signing keys. Firmware-layout choices compare compiled support, not
an executed OTA update. The existing STM32/ST67 gateway testbed is fixed: there
are no device-capacity questions, and the results are not predictions for another
MCU. Missing supported configurations need normal profile implementation and
qualification first.

For ML-DSA-65 TLS authentication, the wizard also offers `default` or `verify_small`.
Mutual authentication additionally offers `sign_small` and `both_small`. These
settings apply to the STM32's TLS signing/verification, with **Unchanged** available
when the From choice is still applicable. Other authentication families and plaintext
skip this question. Leaving the choice at `default` preserves the existing build
configuration; selecting a small-memory mode does not resize the reserved memory pools.
The campaign editor exposes the same optional factor under **Factors / matrix**.
The **TLS implementation options** menu also exposes compact-code and ML-KEM
memory controls, small-stack implementation, and explicit task/heap reservations.
See [the application TLS controls](011_experiment_configuration.md#optional-tls-implementation-controls)
for defaults and applicability. The same fields can be campaign matrix factors.

Both states use Ready Metrics 2, a fresh connection following a hardware reset,
normal boot without stack profiling, and energy monitoring off. Payload sizes
describe the measured gateway-to-device response after an MQTT request, rather
than a general simulation of the designer's traffic. The default is
**10 attempts per state**, adjustable before collection. This is a pilot count,
not a statistical-precision claim. The tool creates exactly two one-condition
profiles under `results/profiles/`, freezes both through the shared queue and
waits for preceding jobs, execution, export and analysis. Start confirmation
starts the shared dispatcher; it does not reprioritise or cancel other work.
Keep source files unchanged while frozen jobs remain queued/running.

Ctrl-C detaches the comparison app; submitted work continues. The printed session
path supports recovery without resubmitting the pair:

```bash
python3 scripts/migration_compare.py --resume results/migrations/<comparison>/session.json
```

`--directory results/<queue>` selects a different queue for a new comparison;
resume uses the recorded queue. Externally paused jobs or stopped dispatch require
explicit recovery. Unsafe cleanup/source-validation failures stop the comparison
with the queue diagnostic. There are no automatic replacement attempts. Qualified
workload failures remain recorded under the queue's `record` policy; other failed
attempts require inspection and explicit acceptance before export. Accepted
failures never become successes. An all-failed state reports unavailable timing.

The tool exports its two job IDs without changing the queue UI's marked selection.
The session and `report/` are below `results/migrations/<comparison>/`. Outputs:

- `comparison.txt`: the console table, also retained as text.
- `comparison.tex`: From, To, signed absolute change and percentage change.
- `selections.tex`: the selected functional/crypto settings for both states.
- `comparison.json`: full domain statistics, counts, quartiles, comparison controls
  and unavailable reasons; `provenance.json` hashes the frozen inputs and outputs.

The two `.tex` files use `booktabs` and `tabularx`, contain no document preamble
or floating table wrapper, and can be included with `\input{...}` inside a thesis
table. No thesis files are edited. The [analysis reference](012_results_and_analysis.md#interactive-migration-comparisons)
owns metric boundaries and delta interpretation.

## CLI and validation

The names passed to `add` must exist under `results/profiles/`; they are not
tracked template names. IDs come from `list`:

```bash
python3 scripts/run_queue.py profiles
python3 scripts/run_queue.py add my_baseline my_kex
python3 scripts/run_queue.py add my_authentication --repetitions 5
python3 scripts/run_queue.py list
python3 scripts/run_queue.py start
python3 scripts/run_queue.py pause <entry-id>
python3 scripts/run_queue.py move <entry-id> up
python3 scripts/run_queue.py resume <entry-id>
python3 scripts/run_queue.py retry <entry-id>
python3 scripts/run_queue.py requeue <entry-id> --repetitions 5
python3 scripts/run_queue.py accept <entry-id>
python3 scripts/run_queue.py mark <completed-entry-id>
python3 scripts/run_queue.py export
python3 scripts/run_queue.py stop
python3 scripts/run_queue.py quit
python3 scripts/run_queue.py remove <waiting-entry-id>
python3 scripts/run_queue.py purge <retained-entry-id> --confirm <retained-entry-id>
```

Software and separately gated physical checks:

```bash
./scripts/dev.sh pytest tests/unit/test_run_queue.py tests/unit/test_queue_workspace.py tests/unit/test_archive_table.py
./scripts/dev.sh pytest tests/integration/test_run_queue_in.py tests/integration/test_campaign_continue_in.py -m integration
./scripts/dev.sh pytest-hardware tests/hardware/test_run_queue_hw.py --pqc-require-hardware
```

Current qualification and remaining fault coverage belong to DTR-RUN-QUEUE and
DTR-CAPTURE-DEADLINE in the [test register](013_testing_and_deferred_coverage.md).
