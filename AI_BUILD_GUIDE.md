# AI build guide — PQC experiment framework

## Authority and scope

Read this guide before substantive implementation or review. It owns mandatory
engineering, testing, evidence and Git rules. Establish current state
from the accessible working tree or the files supplied for this request; prior
chats and historical plans are not current source or authorization for new work.
The user's requested action sets the scope.

[AGENTS.md](AGENTS.md) is the direct-repository entry point.
The [AI workflow](docs/001_ai_feature_request_workflow.md) owns classification,
context exchange and response format, including release-readiness reviews.
The [project prompt](docs/008_chatgpt_project_prompt.md) selects direct access or
the upload-only fallback. Do not ask for uploads of accessible files, propose
uninspected edits, or ask users to reapply working-tree changes already made.

## Navigation

[docs/README.md](docs/README.md) is the complete documentation ownership/index.
Read only the relevant topic and source files for a task.

| Subject | Canonical owner |
|---|---|
| Orientation and common commands | [Root README](README.md) |
| Implemented components and capability boundaries | [Architecture](docs/007_framework_architecture.md) |
| Profiles, campaign/queue/collection semantics | [Configuration](docs/011_experiment_configuration.md) |
| Capture contracts, metrics and analysis | [Results](docs/012_results_and_analysis.md) |
| Test layers and deferred coverage | [Testing](docs/013_testing_and_deferred_coverage.md) |
| Linux host and gateway prerequisites/locks | [Host setup](docs/002_host_gateway_setup.md) |
| Board wiring and diagnostics | [Board setup](docs/003_stm32_board_setup.md), [firmware startup](docs/004_baseline_hal_app.md) |
| Build, signing, flash and UART | [Operating guide](docs/005_remote_flash_workflow.md) |
| Queue and batch procedures | [Queue](docs/014_campaign_queue.md), [collection](docs/015_campaign_collection.md) |
| Open experiment data, signing identity and generated state | [Open-data policy](docs/006_security_and_secrets.md) |
| Broker and certificate operation | [Broker guide](experiment/mqtt-broker/README.md) |

Current code supports wolfBoot, live ST67/lwIP/wolfSSL/wolfMQTT, passive energy
capture and offline analysis. Support is not qualification of every combination.
Do not implement deferred capabilities unless the request requires them and the
necessary context is available. Preserve the evidence boundaries below.

## Repository boundaries

The CubeMX project remains at the repository root. Do not move generated folders
unless explicitly requested. Firmware lives in `Core/`, `Drivers/`, `Middlewares/`
and `LWIP/`; canonical profiles in `configs/`; orchestration in `scripts/`; tests
in `tests/`; project documents in `docs/`; broker/instrument sources under
`experiment/mqtt-broker/` and `instruments/esp32_ina228/`.
`results/`, `build/` and `.pqc-generated-state/` are generated state, not source.

Application TLS/wolfCrypt belongs in `Middlewares/Third_Party/wolfSSL`.
`tools/wolfboot/lib/wolfssl` is the bootloader's separate dependency. Inspect the
parent gitlinks and `.gitmodules` for pinned revisions and project fork ownership.
When Git publication is explicitly authorized, publish a modified submodule
commit before advancing the parent gitlink; a parent commit cannot preserve
uncommitted submodule contents. This ordering does not authorize publication.

## Development and hardware access

Linux/bash is the sole supported environment. Run normal builds, tests and
framework commands from the repository root using Docker wrappers:

```bash
./scripts/dev.sh pytest tests/unit
./scripts/dev.sh python scripts/experiment.py --help
./scripts/dev.sh experiment --help
```

Gateway work uses `pytest-gateway`, `pytest-hardware`, `experiment-gateway`,
`campaign-gateway` or `python-gateway`. Physical hardware access remains
gateway-mediated. Host-native builds are explicit diagnostic fallbacks, not the
reproducible validation gate. Host launchers that themselves own Docker, including
certificate provisioning, queue and collection, are documented exceptions.

Let gateway wrappers wait for an occupied lease with Ctrl-C cancellation; do not
impose a short timeout unless requested. Recorded owner metadata does not prove
that its workload is still running. Force-release requires verified abandonment
and explicit recovery authorization. Never delete the lock file. Raw SSH is for
bounded diagnostics only when no framework operation supplies the needed check.
Do not change gateway OS/network persistence or SSH/VPN authentication without
an explicit request. Framework-owned temporary impairment is scoped and restored
by its owning workflow.

## Generated state and open experiment data

Generated-state preflight owns build/signing compatibility, stale-output cleanup
and provenance. Pytest cleanup is supplementary hygiene; it must preserve source
and canonical keys. Signing requires a framework-recorded relocated application
build and matching artifact identity. Follow the
[open-data policy](docs/006_security_and_secrets.md) for persistent tuples:

- A completely absent tuple may be created only by its owning workflow when allowed.
- Preserve complete matching tuples; fail on partial or mismatched state.
- Never silently replace canonical keys, reconstruct partial tuples, or use
  `keysclean`/tuple-member deletion as routine repair.
- Disposable build materializations may be restored from a validated tuple.

All project material follows the [open experimental-data policy](docs/006_security_and_secrets.md).
It is the sole classification authority, including experiment private keys and
dedicated Wi-Fi settings. Do not infer confidentiality from filenames, old prompts
or existing redaction code. Use the policy's distinction between open handling and
current tool behavior; preserve task scope, state integrity and reproducibility.

## Evidence

Claims must match retained evidence from the affected boundary. Build/link/sign
results do not establish flashing or execution. Local-only and fake/no-network
checks do not prove external networking. Host/broker checks do not establish STM32,
Wi-Fi, TLS/MQTT or end-to-end wireless success. Never promote one evidence class
into another.

Runtime timings, cycles, result codes, heap/stack values and negative/repeated-run
outcomes require explicit firmware records and applicable acquisition/provenance.
Host durations, capture lengths, linker sizes and configured capacities cannot
supply missing measurements. Unavailable values need reasons, not estimates.

A finalized run manifest records execution and capture provenance. Scientific
values remain in indexed raw evidence and separately versioned analysis products;
do not insert metrics into or reseal an immutable capture. Execution outcome,
capture acceptance, metric validity and comparison eligibility are distinct.
See the [results reference](docs/012_results_and_analysis.md).

## Validation

Update tests appropriate to the changed boundary. Unit tests require no hardware,
SSH, UART, brokers, VPN, privileged impairment or credentials. Integration tests
exercise real local/process/tool boundaries and use explicit capability gates.
Hardware tests remain bounded, gateway-mediated and capability-gated.
Integration filenames end in `_in.py`, hardware filenames in `_hw.py`; test-module
basenames must be unique across directories.

```bash
./scripts/dev.sh pytest tests/unit
./scripts/dev.sh pytest tests/integration -m integration
./scripts/dev.sh pytest-hardware
./scripts/dev.sh pytest
```

A plain full run may skip unavailable capabilities. Strict `--pqc-require-*`
controls intentionally require a selected gate; a skip is never a pass.
Do not stop at units when a change crosses a process, Docker, build, gateway,
broker, UART, firmware, network or hardware boundary. Run relevant self-contained
hardware tests when the affected capability is available and within scope.

Hardware tests must prepare their own canonical cases/build/sign/flash state,
capture their own evidence and clean up owned state. Prior logs, manually generated
cases/builds and test-specific evidence variables are not default prerequisites.
Credentials, reachable laboratory equipment and provisioned instruments are
external capabilities; optional selectors may narrow an otherwise runnable matrix.

When required higher-layer validation is unavailable, explain why and update the
[deferred-test register](docs/013_testing_and_deferred_coverage.md). Preserve each
entry's feature, missing layer, reason, required capability, intended test, command
and status. Related changes must implement, update or explicitly retire applicable
entries with justification.

Documentation-only changes require targeted documentation checks and all units:

```bash
./scripts/dev.sh pytest tests/unit/test_documentation_integrity.py tests/unit/test_docker_default_workflow_docs.py
./scripts/dev.sh pytest tests/unit
```

## Delivery and maintenance

Preserve unrelated work. Do not reset, discard, overwrite unrelated changes, commit,
amend, rebase, merge, push, force-push or create a PR without explicit authorization
for that Git action. Complete required validation before an authorized commit;
verify branch and remote before an authorized push or PR.

Inspect `git diff --check`, `git diff` and `git status --short` before completion.
Report interpretation, inspected/changed files, implementation/test/doc changes,
executed commands and observed pass/fail/skip results, runtime evidence where
applicable, unverified work, risks and Git state. Do not claim unexecuted checks.
Follow the [workflow](docs/001_ai_feature_request_workflow.md) for review responses
and upload-only complete replacement files/ZIPs. Direct sessions deliver edits
and their completion report, without replacement ZIPs for already applied changes.

Keep each subject with its canonical owner. Update the index when documents move,
appear or change lifecycle. Preserve historical rationale in explicitly labelled
plans/decisions; do not append phase diaries to current references. Prefer links
to duplicate manuals. Tests should check inventory, links, command/schema contracts
and prohibited executable guidance rather than require particular prose.
