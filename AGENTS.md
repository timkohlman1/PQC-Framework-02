# PQC IoT Experiment Framework — Codex Instructions

This repository is an STM32 embedded-security experiment framework.

`AGENTS.md` is the entry point for direct-repository agents such as Codex.
Read `AI_BUILD_GUIDE.md` from the working tree before substantive work; it
remains the normative AI engineering guide for both supported workflows.

## Direct-repository workflow

Inspect and modify the working tree directly within the user's requested scope.
Do not ask the user to ZIP or upload repository context that is already available.
Do not return replacement ZIPs for files already modified in the working tree.
Report the actual diff, validation results, and remaining limitations instead.
For read-only requests, inspect and report without editing files.

If repository access is unavailable, use the upload-based ChatGPT fallback in
`docs/001_ai_feature_request_workflow.md` and `docs/008_chatgpt_project_prompt.md`.
That fallback retains selected-file context ZIPs and replacement artifacts.

## Repository guidance

For substantive implementation or review work, use `AI_BUILD_GUIDE.md` as
the normative AI engineering guide.

Use additional canonical documents only when relevant:

- `docs/README.md` — documentation ownership/index
- `docs/007_framework_architecture.md` — implemented components and capability boundaries
- `docs/011_experiment_configuration.md` — profile and orchestration semantics
- `docs/012_results_and_analysis.md` — capture contracts and measurement interpretation
- `docs/013_testing_and_deferred_coverage.md` — test architecture and deferred tests
- `README.md` — normal developer commands
- `docs/005_remote_flash_workflow.md` — build, signing, flashing, UART,
  secure-boot, and gateway operation
- `docs/006_security_and_secrets.md` — secrets and signing-state rules
- `experiment/mqtt-broker/README.md` — broker operation

Do not read every document before every task. Read the files needed to
understand the requested change.

## Development environment

Linux/bash is the supported development environment.

Prefer the repository wrappers for normal work:

    ./scripts/dev.sh pytest tests/unit
    ./scripts/dev.sh pytest
    ./scripts/dev.sh pytest-hardware
    ./scripts/dev.sh experiment ...
    ./scripts/dev.sh experiment-gateway ...
    ./scripts/dev.sh campaign-gateway ...

Do not substitute host-native build/test commands for the reproducible
wrapper path except for an explicitly justified diagnostic fallback.

## Implementation workflow

For implementation requests:

1. Inspect the relevant implementation, configuration, tests, and
   documentation before modifying behaviour.
2. Determine the smallest coherent change that satisfies the request.
3. Modify repository files directly.
4. Add or update tests appropriate to the affected boundary.
5. Update canonical documentation where behaviour, capability, architecture,
   or user-visible operation changes.
6. Run targeted validation while developing.
7. Run the appropriate broader validation before completion.
8. Inspect `git diff --check`, `git diff`, and `git status` before finishing.
9. Report exactly what was verified and what remains unverified.

Preserve unrelated user changes.

Do not reset, discard, overwrite, commit, amend, rebase, merge, push,
force-push, or create a pull request unless the user's current request
explicitly authorizes the relevant Git action.

## Testing

Follow the testing model in `AI_BUILD_GUIDE.md`.

Do not stop at unit tests when a change crosses a process, Docker, build,
gateway, broker, UART, firmware-runtime, network, or hardware boundary.

Where a relevant self-contained hardware test exists and gateway capability
is available, run it after appropriate lower-level validation succeeds.

A skipped capability-gated test is not evidence that the capability passed.

If required higher-layer validation cannot be performed, state the specific
reason and follow the repository's deferred-test rules.

## Gateway and physical hardware

Physical hardware access must remain gateway-mediated.

Prefer framework-owned operations such as:

- `pytest-hardware`
- `experiment-gateway`
- `campaign-gateway`

over ad-hoc SSH, flashing, UART, broker, or hardware command sequences.

Raw SSH may be used only for bounded diagnostics where the framework does
not provide the required diagnostic operation.

Let gateway wrappers wait for an occupied lock, report the wait, and retain
Ctrl-C cancellation. Contention alone is not a command failure; do not impose
a short timeout unless requested. A recorded owner description is not proof
that the named workload is still running. See `docs/002_host_gateway_setup.md`.

Do not:

- copy, display, request, modify, or commit SSH private keys;
- copy, display, request, modify, or commit VPN private material;
- change SSH/VPN authentication configuration unless explicitly requested;
- modify persistent gateway OS/network configuration unless explicitly
  requested;
- bypass an existing framework workflow merely because direct SSH is easier;
- force-release the gateway lock unless an abandoned owner has been verified
  and recovery has been explicitly authorized.

## Secrets

Do not inspect secret values merely because filesystem access permits it.

Do not display or copy the contents of:

- the real repository `.env`;
- SSH/VPN private keys;
- tokens or credential stores;
- externally managed private certificates;
- production credentials;
- unrelated host credentials.

Repository workflows may consume credentials through their established
interfaces without exposing their values.

Never put secrets into source files, prompts, logs, patches, commits, pull
requests, or generated documentation.

## Evidence

Claims must match explicit evidence.

Do not claim build, signing, flashing, secure-boot, gateway, UART, runtime,
timing, memory, networking, Wi-Fi, TLS, MQTT, broker, hardware, or
end-to-end success unless the applicable workflow produced evidence that
supports that claim.

Do not promote one evidence class into another.

If a value or capability was not measured or demonstrated, report it as
unverified or unavailable rather than estimating it.

## Dependency ownership

Application TLS/wolfCrypt work belongs under
`Middlewares/Third_Party/wolfSSL`.

Do not use wolfBoot's nested wolfSSL dependency as the application TLS
source.

When that submodule is modified, follow the documented submodule commit
ordering.

## Git and GitHub

Normal implementation work may inspect Git state and diffs.

Before completion, use:

    git status --short
    git diff --check
    git diff

Do not commit or push by default.

If explicitly asked to commit, first ensure requested validation has
succeeded.

If explicitly asked to push or create a pull request, verify the intended
branch and remote first.

Never force-push unless explicitly requested.

## Completion report

For an implementation task report:

- interpretation of the requested change;
- files changed;
- implementation performed;
- tests added or modified;
- documentation changed;
- commands actually executed;
- observed pass/fail/skip results;
- hardware/runtime evidence obtained, where applicable;
- anything not verified;
- remaining risks or issues;
- current Git worktree status.

Do not state that a command passed unless it was actually executed and its
output supports that conclusion.
