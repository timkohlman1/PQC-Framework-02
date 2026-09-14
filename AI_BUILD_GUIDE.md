# AI Build Guide — PQC IoT Experiment Framework

## 1. Purpose and authority

This guide is the compact source of truth for AI-assisted implementation and review in this repository. Read it before proposing or applying changes.

It defines the mandatory development workflow, repository boundaries, evidence rules, testing expectations, safety constraints, and artifact-delivery requirements. Detailed architecture, commands, setup instructions, capability status, and roadmap history belong to the canonical documents linked below.

Do not rely on prior chats, prior uploads, memory, or inferred repository state. Use only this guide and repository files supplied for the current request.

Supported AI entry points are:

- `AI_BUILD_GUIDE.md`
- `docs/001_ai_feature_request_workflow.md`
- `docs/008_chatgpt_project_prompt.md`

Release-readiness assessments use the review-request path in the maintained workflow; there is no separate release-readiness prompt document.

## 2. Canonical documentation routing

Use `docs/README.md` as the project-owned documentation index and ownership map. It identifies each maintained document's role, lifecycle, canonical subject ownership, and audience. Vendor and submodule documentation is upstream-owned and excluded from project-maintained consistency checks.

Canonical owners:

- Current architecture, capability matrix, evidence boundaries, stable file map, generated-state model, test architecture, and consolidated deferred-test register: `docs/007_framework_architecture.md`
- Human-facing project orientation and common commands: `README.md`
- AI implementation and review process: `docs/001_ai_feature_request_workflow.md`
- Project prompt for fresh feature-development chats: `docs/008_chatgpt_project_prompt.md`
- Host and gateway setup: `docs/002_host_gateway_setup.md`
- STM32 board setup: `docs/003_stm32_board_setup.md`
- Baseline firmware and UART marker model: `docs/004_baseline_hal_app.md`
- Flashing, UART capture, secure-boot operation, and diagnostic fallback commands: `docs/005_remote_flash_workflow.md`
- Secrets, credentials, signing material, and generated-state safety: `docs/006_security_and_secrets.md`
- MQTT broker operation and host-side validation: `experiment/mqtt-broker/README.md`
- Master framework roadmap and lifecycle classification: `docs/pqc_iot_experiment_framework_plan.md`

Do not duplicate detailed topic instructions in this guide. Update the canonical owner and keep only the rule or boundary needed for safe AI work here.

## 3. Project and capability boundaries

This repository is an STM32 embedded-security experiment framework covering direct-flash HAL/FreeRTOS workflows, wolfBoot secure boot, signing and benchmark evidence, and bounded MQTT/TLS preparation.

The canonical current capability matrix is in `docs/007_framework_architecture.md`. Treat its evidence classes and limitations as authoritative. In particular:

- Build-only evidence proves compilation and linkage only.
- STM32 local-only evidence does not prove external networking.
- Fake/no-network evidence is simulation or initialization evidence only.
- An unavailable transport boundary performs no socket I/O and proves no handshake or protocol operation.
- Host-side and broker-side evidence does not prove STM32, Wi-Fi-module, or end-to-end wireless behavior.
- Real ST67W61M1-backed networking, external STM32 TCP, certificate-backed STM32 TLS handshakes, real STM32 MQTT connect/publish/reconnect, and end-to-end classical or PQC/hybrid MQTT-over-TLS remain unavailable unless the architecture matrix and explicit evidence show otherwise.

Do not promote evidence from one class into another. Do not implement a future or deferred capability early unless the current request explicitly requires it and the necessary repository context is available.

## 4. Repository navigation and ownership

The CubeMX-generated firmware project remains at the repository root. Do not move CubeMX-generated folders unless explicitly requested.

Use stable directory-level ownership rather than exhaustive file lists:

```text
Core/, Drivers/, Middlewares/     STM32 firmware and generated/vendor integration
configs/                          canonical target, gateway, service, workload, crypto, network-condition, campaign, and benchmark configuration
scripts/                          Docker wrappers, experiment CLI, and framework implementation
tests/                            unit, integration, gateway-capable, and hardware tests
docs/                             project documentation, decisions, and plans
experiment/mqtt-broker/           broker compose project and host-side MQTT/TLS tools
docker/, .github/workflows/       reproducible development image and CI
results/                          generated evidence; not source
```

Use `docs/007_framework_architecture.md` for the maintained detailed source/configuration map. Use `docs/README.md` to locate project-owned documentation.

### wolfSSL source ownership

Application TLS/wolfCrypt changes must target `Middlewares/Third_Party/wolfSSL`, the project-controlled wolfSSL submodule. Do not modify `tools/wolfboot/lib/wolfssl` for application TLS functionality; that path is wolfBoot's upstream-owned nested dependency.

When a change modifies files under `Middlewares/Third_Party/wolfSSL`, commit and push the wolfSSL change in that submodule repository first, then commit the resulting submodule SHA update in this parent repository. A parent-repository commit alone does not preserve dirty wolfSSL working-tree changes. The canonical dependency model and source-of-truth paths are documented in `docs/007_framework_architecture.md`.

## 5. Default workflow model

The project default is Docker-hosted Linux execution for framework commands, firmware builds, wolfBoot builds, application signing, pytest, gateway checks, and gateway-mediated hardware experiments.

Use the repository wrappers from the repository root:

```powershell
.\scripts\dev.ps1 pytest tests/unit
.\scripts\dev.ps1 python <repository-script.py> [args...]
.\scripts\dev.ps1 python-gateway <script> [arguments...]
.\scripts\dev.ps1 pytest
.\scripts\dev.ps1 python scripts/resolve_campaign.py baseline.yaml
$case = Get-ChildItem ".pqc-generated-state/campaigns/baseline/cases/0001_*.yaml" | Select-Object -First 1
$path = (Resolve-Path -Relative $case.FullName) -replace '\\','/'
.\scripts\dev.ps1 experiment status --experiment $path
.\scripts\dev.ps1 experiment build --experiment $path
.\scripts\dev.ps1 experiment-gateway run --experiment $path
.\scripts\dev.ps1 pytest-hardware
```

The POSIX wrapper is `./scripts/dev.sh` with corresponding subcommands.

For wrapper runs that require local Wi-Fi credentials, `.env.sample` is the committed template and `.env` is the Git-ignored local file. Both `scripts/dev.ps1` and `scripts/dev.sh` may load only `PQC_WIFI_SSID` and `PQC_WIFI_PSK` from `.env`, must not overwrite caller-supplied values, and must ensure wrapper-loaded values do not persist after the Docker invocation finishes. Never commit or package the real `.env`, and never resolve these secrets into generated campaign YAML.

Use the wrapper `python` subcommand for ad hoc repository Python scripts. Do not document or recommend `.\scripts\dev.ps1 python ...` unless both wrappers implement that subcommand.

Host-native Windows or development-machine builds remain available only as an explicit manual fallback for diagnosis or CubeMX/IDE-oriented work. They are not the reproducible validation gate. Detailed build, flash, signing, broker, gateway, and UART command sequences belong to `README.md`, `docs/005_remote_flash_workflow.md`, and `experiment/mqtt-broker/README.md`.

Gateway and hardware access remains gateway-mediated. Do not bake SSH material, VPN material, signing material, certificates, credentials, or generated runtime state into container images or repository artifacts.

## 6. Generated state, signing state, and provenance

Generated-state preflight is the primary mechanism for build/signing compatibility, stale-output handling, artifact provenance, and downstream artifact validation. Pytest startup cleanup is supplementary cross-platform hygiene only; it does not establish provenance and must not remove source files, canonical signing keys, or reusable signing-tuple members.

wolfBoot signing state is a reusable local tuple:

- A completely absent tuple may be created only by its owning workflow when allowed.
- A complete matching tuple must be preserved.
- A partially missing tuple must fail safely before build or signing.
- A mismatched tuple must fail safely before build or signing.
- Never silently reconstruct tuple members, silently replace a canonical private key, run destructive `keysclean` guidance, or delete tuple members as routine cleanup.

The normal secure-boot path must use a framework-recorded relocated application build before signing so provenance is available. Direct wrapped CMake or host-native commands are diagnostic fallback only. Exact commands and profile coverage are owned by `docs/005_remote_flash_workflow.md`.

## 7. Evidence and result rules

Claims must match explicit evidence. The manifest is the source of truth for what a recorded workflow ran; logs and UART output provide supporting evidence according to the architecture model.

Do not claim hardware, gateway, flashing, UART, runtime, timing, memory, benchmark, MQTT/TLS, network, broker, Wi-Fi, ST67W61M1, or end-to-end success without explicit logs, manifests, or equivalent evidence from the relevant workflow.

Specific rules:

- Runtime timing, cycle counts, result codes, stack high-water values, and heap values must come from explicit firmware/UART markers or recorded manifests. Do not infer them from host duration, reset delay, linker output, ELF output, build logs, or UART capture duration alone.
- Containerised build/signing evidence is portable software-build evidence only.
- Broker or native host wolfMQTT/wolfSSL validation is host-side or broker-side compatibility evidence only; it is not wolfMQTT-on-STM32 or end-to-end wireless evidence.
- Fake/no-network outcomes must remain labelled as such.
- Unavailable metrics must be recorded as unavailable with a reason rather than estimated.
- Negative-test and repeated-run claims require their recorded samples and outcomes.

Detailed result schemas, benchmark interpretation, evidence classes, and limitations are owned by `docs/007_framework_architecture.md`.

## 8. Testing requirements

Use the established test layers:

```powershell
.\scripts\dev.ps1 pytest tests/unit
.\scripts\dev.ps1 pytest tests/integration -m integration
.\scripts\dev.ps1 pytest-hardware
.\scripts\dev.ps1 pytest
```

Testing rules:

1. Add or update tests for framework, firmware-integration, configuration, documentation, or workflow changes.
2. Unit tests must not require hardware, SSH, UART devices, broker access, VPN access, network-impairment privileges, or private credentials.
3. Keep hardware-dependent tests separate, marked, bounded, and capability-gated.
4. Test-module filenames must identify their layer: integration tests under `tests/integration/` end in `_in.py`, and hardware tests under `tests/hardware/` end in `_hw.py`. Unit tests keep the normal `test_*.py` form. Do not reuse the same Python module basename across test directories.
5. Integration tests may use real local toolchains or gateway probes but must skip cleanly when capabilities are unavailable unless a strict `--pqc-require-*` control is intentionally supplied.
6. A plain full pytest run may skip unavailable gateway or hardware capabilities. A skip is not evidence that the capability succeeded.
7. Do not stop at unit tests when a feature crosses process, build, Docker, gateway, broker, UART, firmware-runtime, network, or hardware boundaries.
8. When an affected boundary cannot receive the required higher-layer test, state the specific reason in the implementation response and add or update the item in the consolidated deferred-test register in `docs/007_framework_architecture.md`. Each item must retain the feature, missing test layer, reason, required capability or phase, intended test file, eventual verification command, and status.
9. Future related changes must inspect the deferred-test register and implement, update, or explicitly retire applicable entries with justification.

For documentation-only changes, run the targeted documentation tests and the full unit suite. The normal minimum gate is:

```powershell
.\scripts\dev.ps1 pytest tests/unit/test_documentation_integrity.py
.\scripts\dev.ps1 pytest tests/unit/test_docker_default_workflow_docs.py
.\scripts\dev.ps1 pytest tests/unit
```

Run `./scripts/dev.ps1 pytest` when required by the phase plan or when broader verification is appropriate. Do not claim that a command passed until its output is provided.

## 9. Secrets and generated artifacts

Disposable experiment-only TLS, MQTT, wolfBoot, firmware-signing, CA, client, and broker material must be copied into the owning build or experiment result when it was used to produce, verify, flash, or orchestrate that result. Retain unsigned and signed application images, bootloader outputs, public/private keys, certificates, chains, keystores, tuple manifests, and explicitly selected infrastructure artifacts. Record every copied file in a SHA-256 material inventory.

Do not commit this generated material, bake it into images/static build contexts, or include it in AI replacement ZIPs. Result directories remain ignored and sensitive. Never copy SSH/VPN private keys, tokens, production credentials, externally managed/non-exportable material, unrelated `.env` files, or host control-plane credentials into results. Workflows must copy explicitly selected files and must never sweep broad credential directories.

Do not commit generated build output, result output, caches, local generated-state manifests, local signing tuples, broker runtime state, or tool-generated binaries. The canonical security and exclusion rules are in `docs/006_security_and_secrets.md` and repository ignore files.

Replacement ZIPs and context ZIPs must exclude secrets and generated evidence unless a specific non-secret artifact is explicitly required for the task.

## 10. AI-assisted implementation and review workflow

For every request:

1. Read this guide first.
2. Classify the request as implementation or review according to `docs/001_ai_feature_request_workflow.md`.
3. Inspect the supplied files before proposing code, replacement content, or candidate edits.
4. Ask only for files needed for the current change or review. Do not request the whole repository by default.
5. When multiple files are needed, provide a PowerShell `Compress-Archive` command with an exact repository-relative `$files = @(...)` list and an output path under `C:\Users\timko\Downloads\`.
6. Do not implement code until the required context is available.
7. Preserve unrelated content and existing capability boundaries.
8. Update relevant documentation in the same change.
9. Do not implement future phases early.
10. Do not ask for or suggest committing secrets.

Implementation responses must contain:

1. Brief interpretation.
2. Files inspected.
3. Files likely to change.
4. Proposed code changes.
5. Proposed test changes.
6. Proposed documentation updates.
7. Exact commands to run.
8. Expected output or pass/fail criteria.
9. Assumptions, risks, or unresolved questions.

Review responses must contain:

1. Brief interpretation.
2. Files inspected.
3. Compliance result.
4. Issues found.
5. Files likely needing changes.
6. Proposed updates.
7. Exact verification commands.
8. Expected output or pass/fail criteria.
9. Assumptions, risks, or unresolved questions.

## 11. Replacement artifact delivery

For every modified or created file:

- Provide complete replacement content in a downloadable artifact using the exact target filename.
- When multiple files change, provide one ZIP containing repository-relative paths.
- Provide the exact PowerShell extraction command, assuming the ZIP is in `C:\Users\timko\Downloads\` and extraction runs from the repository root:

```powershell
Expand-Archive -LiteralPath "C:\Users\timko\Downloads\<archive-name>.zip" -DestinationPath . -Force
```

Do not require the user to relocate the downloaded archive before extraction. State the files changed, verification commands, expected pass criteria, and any unverified assumptions. End an implementation response with the next verification command.

## 12. Documentation maintenance rules

- Keep this guide compact, current, and normative. Do not add detailed phase narratives, exhaustive unstable file lists, complete command manuals, hardware identity values, or duplicated topic documentation.
- Update `docs/README.md` whenever a project-owned document is added, removed, relocated, or reclassified.
- Keep current capability detail and the deferred-test register in `docs/007_framework_architecture.md`.
- Keep user-facing command orientation in `README.md`.
- Keep operational procedures in their topic documents.
- Keep roadmap status in active plans and historical narrative in historical plans or decisions.
- Preserve safety constraints and evidence boundaries when consolidating documentation.
- Add or update structural documentation tests when document ownership, required links, workflow rules, or prohibited guidance changes.
