# Documentation Consistency and AI Discoverability Remediation Plan

## Purpose

This plan converts the documentation consistency review into a sequence of small AI-driven change requests.

The plan addresses three priorities:

- Priority 1: correctness and safety
- Priority 2: current-state consistency
- Priority 3: tightening, ownership, and automated maintenance

Each phase is intentionally scoped so one AI-assisted implementation request can inspect, modify, test, and document a bounded set of files without attempting to rewrite the entire documentation system at once.

The target documentation model remains:

- `AI_BUILD_GUIDE.md` is the compact source of truth for AI-assisted development rules, current capability boundaries, repository navigation, testing expectations, and safety constraints.
- `README.md` is the concise human-facing project entry point and common command reference.
- `docs/007_framework_architecture.md` is the canonical detailed current-state architecture, capability matrix, evidence-boundary reference, file map, and deferred-test register.
- `docs/README.md` is the project-owned documentation index and ownership map.
- Topic-specific setup and workflow documents own their detailed operational instructions.
- Active plans own roadmap status for their subject area.
- Historical plans and decision records preserve history without being treated as current-state references.
- Vendor and submodule documentation remains upstream-owned and is excluded from project-maintained documentation consistency checks.

No phase may claim that documentation matches runtime, hardware, gateway, UART, benchmark, timing, memory, MQTT/TLS, or end-to-end behavior unless explicit repository files, logs, manifests, or equivalent evidence support the claim.

## Scope Principles

- Correct unsafe or misleading instructions before restructuring documents.
- Keep each AI-driven phase small and reviewable.
- Do not rewrite unrelated documentation.
- Preserve valid historical information, but label it clearly.
- Prefer one canonical owner for each policy, workflow, capability statement, or command family.
- Replace duplicated detail with links to canonical documents.
- Distinguish current reference material from historical plans and decision records.
- Ensure every project-owned document is discoverable from an AI-facing index.
- Exclude third-party and submodule documentation from project-owned maintenance checks.
- Prefer Docker wrapper commands as the documented default path.
- Treat host-native commands as explicit troubleshooting or diagnostic fallback only.
- Preserve signing-state safety rules and never recommend destructive key or keystore cleanup.
- Do not request, expose, document, or commit secrets.
- Add structural tests so future documentation drift is detected automatically.
- Use the normal documentation verification commands after every phase.
- Do not combine priorities unless the inspected files show that a narrowly scoped correction cannot be made safely in isolation.

---

# Priority 1 — Correctness and Safety

## Goal

Remove unsafe, broken, misleading, or internally contradictory operational instructions before broader documentation consolidation begins.

Priority 1 is split into four phases so safety-sensitive changes remain small and independently verifiable.

---

## Phase D1.1 — Remove Unsafe Legacy wolfBoot Command Guidance

### Goal

Remove or replace active documentation that recommends destructive wolfBoot signing-state cleanup or obsolete local build sequences.

### Outcomes

- `docs/local build commands.txt` is removed or replaced with a clearly scoped troubleshooting document.
- Active documentation no longer recommends `make WOLFBOOT_ROOT=. keysclean`.
- Documentation does not instruct users to delete or silently regenerate reusable signing-tuple members.
- Current generated-state preflight and signing-state provenance rules are referenced instead.
- Docker wrapper commands are used for normal workflows.
- Any retained host-native commands are labelled diagnostic fallback only.
- Unrelated local-build and signing documentation is preserved.

### Files Likely to Change

- `docs/local build commands.txt`
- `AI_BUILD_GUIDE.md`, only if it references the legacy file
- `README.md`, only if it references the legacy file
- `docs/007_framework_architecture.md`, only if a canonical signing-state link is needed
- documentation tests

### Expected Evidence

- Documentation diff showing removal of unsafe commands.
- Unit test or structural documentation check rejecting `keysclean` in active project-owned documentation.
- Existing unit test suite passes.
- No build, signing, gateway, hardware, or runtime success claim is required.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D1.1 of the attached documentation remediation plan - Remove Unsafe Legacy wolfBoot Command Guidance. Inspect the current AI build guide, documentation index or file inventory, architecture documentation, signing-state documentation, `docs/local build commands.txt`, and existing documentation tests. Remove or replace active documentation that recommends wolfBoot `keysclean`, destructive signing-tuple cleanup, or obsolete normal host-native build sequences. Preserve valid troubleshooting information only where it can be rewritten around the current generated-state preflight and signing-state provenance model. Docker wrapper commands must remain the normal documented path, and host-native commands must be labelled diagnostic fallback. Add or update structural documentation tests so unsafe legacy commands cannot silently return. Do not modify firmware, framework behavior, signing implementation, or generated files in this phase.
```

### Verification Commands

```powershell
git grep -n "keysclean" -- "*.md" "*.txt"
.\scripts\dev.ps1 pytest tests/unit/test_docker_default_workflow_docs.py
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- No active project-owned document recommends `keysclean`.
- No active document recommends deleting canonical private keys, wolfBoot-local private keys, public keys, or generated keystore members as routine cleanup.
- Normal workflows use Docker wrappers and generated-state preflight.
- Any retained native workflow is explicitly diagnostic.
- Documentation tests and unit tests pass.

---

## Phase D1.2 — Repair Broken AI Workflow References

### Goal

Ensure every AI-facing documentation reference resolves to a tracked, maintained file.

### Outcomes

- The repository no longer references missing documentation paths.
- The release-readiness prompt reference is either restored as a tracked document or removed and redirected to an existing maintained workflow.
- Stale references such as missing Phase 11 plan/checklist paths are removed, restored, or explicitly marked historical.
- Misspelled paths are corrected.
- The AI build guide and README use the same valid AI workflow entry points.
- Structural tests validate explicitly referenced project documentation paths.

### Files Likely to Change

- `README.md`
- `AI_BUILD_GUIDE.md`
- `docs/001_ai_feature_request_workflow.md`
- `docs/008_chatgpt_project_prompt.md`
- any restored release-readiness prompt
- documentation tests

### Expected Evidence

- Every referenced project documentation path exists in `git ls-files`.
- Unit tests check the required AI workflow references.
- No implementation or runtime claims are introduced.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D1.2 of the attached documentation remediation plan - Repair Broken AI Workflow References. Inspect the current tracked-file inventory, AI build guide, root README, AI feature-request workflow, ChatGPT project prompt, and existing documentation tests. Resolve every missing, stale, or misspelled project documentation reference, including the release-readiness prompt and any obsolete Phase 11 paths. Restore a missing document only if its intended role can be confirmed from inspected files; otherwise remove or redirect the reference to an existing maintained document. Add or update structural tests so explicitly referenced project documentation paths must exist and be tracked. Do not modify firmware, framework code, CI behavior, or runtime workflows in this phase.
```

### Verification Commands

```powershell
git ls-files | Sort-Object
git grep -n "docs/009_chatgpt_project_prompt_release_readiness_review.md"
git grep -n "docs/phase11_plan.md"
git grep -n "docs/plase11_checklist.md"
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- Every AI workflow document path referenced by active documentation exists and is tracked.
- Misspelled and obsolete paths are removed.
- README and AI build guide identify the same supported AI entry points.
- Structural documentation tests pass.

---

## Phase D1.3 — Correct Signing-State and Generated-State Wording

### Goal

Make signing-state lifecycle and generated-state preflight descriptions precise and consistent across active documentation.

### Outcomes

- Documentation clearly distinguishes:
  - a completely absent signing tuple
  - a complete matching reusable tuple
  - a partially missing tuple
  - a mismatched tuple
- Documentation does not imply that an existing canonical private key may be replaced or that a keystore may be silently regenerated from partial state.
- Generated-state preflight is documented as the primary compatibility and provenance mechanism.
- Pytest startup cleanup is described only as supplementary cross-platform hygiene.
- Documentation states that cleanup does not remove canonical signing keys.
- Secure-boot signing commands consistently use the framework-recorded relocated build path where provenance is required.

### Files Likely to Change

- `README.md`
- `AI_BUILD_GUIDE.md`
- `docs/005_remote_flash_workflow.md`
- `docs/006_security_and_secrets.md`
- `docs/007_framework_architecture.md`
- documentation tests

### Expected Evidence

- Consistent signing-tuple wording across canonical documents.
- Consistent generated-state preflight wording.
- Structural test coverage for required wording or prohibited unsafe wording.
- No signing, build, or hardware run is required.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D1.3 of the attached documentation remediation plan - Correct Signing-State and Generated-State Wording. Inspect the current signing implementation documentation, generated-state implementation documentation, AI build guide, README, remote flash workflow, security document, architecture document, and relevant documentation tests. Reconcile all active wording so reusable wolfBoot signing tuples are preserved, partial or mismatched tuple state fails safely, canonical private keys are not silently replaced, and generated-state preflight is the primary build/signing compatibility and provenance mechanism. Describe pytest startup cleanup only as supplementary cross-platform hygiene. Make the framework-recorded relocated build the canonical normal path before signing, while retaining direct wrapped CMake only as a clearly labelled diagnostic fallback where appropriate. Do not change signing code, generated-state code, firmware, tests outside documentation integrity coverage, or runtime behavior in this phase.
```

### Verification Commands

```powershell
git grep -n "may locally generate missing profile keys" -- "*.md"
git grep -n "keysclean" -- "*.md" "*.txt"
git grep -n "PQC_SKIP_CONTAINER_GENERATED_BUILD_CLEANUP" -- "*.md"
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- Signing-tuple lifecycle is consistent across active documents.
- Generated-state preflight is clearly primary.
- Pytest cleanup is clearly supplementary.
- The normal relocated build-before-signing path records framework provenance.
- No unsafe signing-state implication remains.
- Unit tests pass.

---

## Phase D1.4 — Correct MQTT/Broker Command Examples

### Goal

Remove contradictory or misleading MQTT broker and host wolfMQTT invocation examples.

### Outcomes

- PowerShell host wolfMQTT arguments are documented after `--client-args`.
- Every dash-prefixed forwarded wolfMQTT token is shown individually quoted.
- Active PowerShell documentation does not recommend a standalone `--` forwarding boundary.
- Gateway certificate provisioning examples include `--host-config configs/hosts/gateway.yaml` where gateway IP SAN support is required.
- Localhost-only certificate examples are distinguished from gateway examples.
- Canonical broker Compose path remains `experiment/mqtt-broker/compose.yaml`.
- Host-side validation remains explicitly separate from STM32 and wireless evidence.

### Files Likely to Change

- `README.md`
- `AI_BUILD_GUIDE.md`
- `experiment/mqtt-broker/README.md`
- `docs/007_framework_architecture.md`, only if command examples are maintained there
- relevant unit tests

### Expected Evidence

- Documentation examples agree with the implemented PowerShell forwarding contract.
- Documentation examples distinguish local and gateway certificate provisioning.
- Unit tests validate canonical command fragments.
- No live broker, gateway, or network validation is required.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D1.4 of the attached documentation remediation plan - Correct MQTT/Broker Command Examples. Inspect the current README, AI build guide, broker README, host wolfMQTT wrapper behavior or tests, broker certificate provisioning behavior or tests, and relevant architecture documentation. Correct PowerShell examples so upstream wolfMQTT options are passed after `--client-args` with each dash-prefixed token individually quoted. Remove wording that recommends a standalone `--` PowerShell forwarding path. Make gateway certificate provisioning examples use the host config where gateway IP SAN support is required, while keeping localhost-only examples clearly separate. Preserve host-side evidence boundaries and the canonical broker Compose path. Add or update unit tests for the documented command contract. Do not run gateway, broker, network, or hardware workflows in this phase.
```

### Verification Commands

```powershell
git grep -n "after ``--``" -- "*.md"
git grep -n "\-\-client-args" -- "*.md"
git grep -n "provision-certs --server-name pqc-gateway1" -- "*.md"
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- PowerShell forwarding guidance consistently uses `--client-args`.
- Gateway certificate provisioning examples use the host config where required.
- Local and gateway examples are not conflated.
- Evidence-boundary language remains intact.
- Unit tests pass.

---

# Priority 2 — Current-State Consistency

## Goal

Reconcile contradictory implementation status, stale plans, incomplete operational documents, and fragmented deferred-test tracking.

Priority 2 is split into four phases so each change has one clear source-of-truth objective.

---

## Phase D2.1 — Establish the Canonical Current Capability Matrix

### Goal

Create one detailed current capability matrix in `docs/007_framework_architecture.md` and use it as the canonical implementation-status reference.

### Outcomes

- The architecture document contains a current capability matrix covering at least:
  - direct-flash build/runtime
  - FreeRTOS scheduler/task evidence
  - wolfBoot build/sign/flash
  - classical and ML-DSA secure-boot profiles
  - benchmark evidence
  - MQTT schema and fake transport
  - broker/host-side validation
  - STM32 lwIP preparation and loopback
  - STM32 wolfSSL context and unavailable transport boundary
  - STM32 wolfMQTT build-only and fake/no-network runtime
  - ST67W61M1 backend
  - real STM32 MQTT-over-TLS
  - PQC/hybrid TLS
- Each row distinguishes build support, local runtime support, host-side support, gateway/hardware support, evidence class, and limitations.
- Ambiguous statements such as “MQTT is not implemented” are replaced with precise capability-boundary language.
- The architecture opening summary agrees with later detailed sections.
- Phase history is not used as the primary matrix structure.

### Files Likely to Change

- `docs/007_framework_architecture.md`
- related documentation tests

### Expected Evidence

- One internally consistent architecture capability matrix.
- No contradiction between the architecture introduction and later sections.
- Unit tests or structural tests validate required capability headings or rows.
- No code or runtime workflow changes.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D2.1 of the attached documentation remediation plan - Establish the Canonical Current Capability Matrix. Inspect the AI build guide, root README, architecture document, current tracked configs, representative source files, relevant tests, and the MQTT development plan. Update `docs/007_framework_architecture.md` so it contains one canonical current capability matrix that distinguishes build-only, STM32-local runtime, host-side, broker-side, gateway/hardware, unavailable-boundary, and future hardware-backed capabilities. Reconcile contradictions within the architecture document, especially broad statements that MQTT, wolfSSL transport, or wolfMQTT are wholly unimplemented when preparation or host-side phases exist. Keep real ST67W61M1-backed networking and real STM32 MQTT-over-TLS explicitly unimplemented unless inspected evidence proves otherwise. Do not update the README, AI build guide, overview, or plans beyond minimal links in this phase.
```

### Verification Commands

```powershell
git grep -n "planned but not implemented" docs/007_framework_architecture.md
git grep -n "MQTT.*not implemented" docs/007_framework_architecture.md
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- Architecture has one detailed canonical capability matrix.
- Current implementation and unavailable/future boundaries are explicit.
- Architecture introduction and detailed sections agree.
- No unsupported runtime or hardware claim is added.
- Unit tests pass.

---

## Phase D2.2 — Reconcile Current-State Entry Documents

### Goal

Align the AI build guide, README, project overview, and baseline application document with the canonical architecture capability matrix.

### Outcomes

- `AI_BUILD_GUIDE.md` contains a concise current capability summary consistent with the matrix.
- `README.md` contains a high-level current implementation summary consistent with the matrix.
- `docs/000_project_overview.md` is updated to reflect Docker, FreeRTOS, ML-DSA, broker infrastructure, MQTT preparation, generated-state preflight, and CI at an appropriate overview level.
- `docs/004_baseline_hal_app.md` documents the current scheduler/task marker model and local smoke evidence without implying real networking.
- Broad contradictory statements are replaced with precise implementation-boundary language.
- Detailed phase history remains outside these entry documents.

### Files Likely to Change

- `AI_BUILD_GUIDE.md`
- `README.md`
- `docs/000_project_overview.md`
- `docs/004_baseline_hal_app.md`
- documentation tests

### Expected Evidence

- Entry documents agree with the architecture matrix.
- Marker descriptions distinguish pre-scheduler, scheduler-start, task-context, local loopback, and fake/no-network evidence.
- No unsupported hardware or network claim.
- Unit tests pass.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D2.2 of the attached documentation remediation plan - Reconcile Current-State Entry Documents. Inspect the canonical capability matrix in `docs/007_framework_architecture.md`, AI build guide, root README, project overview, baseline application document, current firmware marker sources, and relevant tests. Update the four entry documents so their current-state claims agree with the architecture matrix. Use precise language for build-only, local-only, fake/no-network, host-side, unavailable transport, and future ST67W61M1-backed capabilities. Update the baseline application document to describe the current FreeRTOS scheduler/task marker sequence and local smoke evidence without claiming real network, TLS handshake, MQTT, or wireless success. Keep detailed phase history out of these documents. Do not change firmware, framework code, configs, CI, or plans in this phase.
```

### Verification Commands

```powershell
git grep -n "Not implemented yet" README.md docs/000_project_overview.md docs/004_baseline_hal_app.md AI_BUILD_GUIDE.md
git grep -n "MQTT.*not implemented" README.md docs/000_project_overview.md docs/004_baseline_hal_app.md AI_BUILD_GUIDE.md
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- All four entry documents agree with the capability matrix.
- FreeRTOS and local smoke evidence are represented accurately.
- Real network, TLS, MQTT, ST67W61M1, and end-to-end boundaries remain explicit.
- No phase-history expansion is introduced.
- Unit tests pass.

---

## Phase D2.3 — Reconcile Operational Workflow Documentation

### Goal

Bring setup, flash, broker, and test workflow documents into alignment with the current Docker-default and generated-state model.

### Outcomes

- `docs/005_remote_flash_workflow.md` uses wrapper-based commands as the normal path.
- Host-native Python and CMake commands are moved to a clearly labelled diagnostic fallback section.
- Secure-boot profile coverage includes implemented classical and ML-DSA profiles or links to the canonical profile source.
- Generated-state provenance requirements are documented.
- Gateway, UART, broker, and hardware evidence rules agree with the guide and architecture.
- Duplicate gateway identity, UART path, and profile lists are reduced where practical through links.
- Setup and security documents link to canonical owners rather than copying full policy blocks.

### Files Likely to Change

- `docs/002_host_gateway_setup.md`
- `docs/003_stm32_board_setup.md`
- `docs/005_remote_flash_workflow.md`
- `docs/006_security_and_secrets.md`
- `experiment/mqtt-broker/README.md`
- relevant documentation tests

### Expected Evidence

- Operational commands use the supported wrapper model.
- Diagnostic fallbacks are clearly labelled.
- Profile and evidence rules are consistent.
- No gateway or hardware run required.
- Unit tests pass.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D2.3 of the attached documentation remediation plan - Reconcile Operational Workflow Documentation. Inspect the current AI build guide, README, architecture capability matrix, host/gateway setup, board setup, remote flash workflow, security document, broker README, current wrapper scripts or tests, supported profile configs, and documentation tests. Update operational documentation so Docker wrapper commands are the normal path, host-native commands are explicit diagnostic fallback, generated-state provenance is respected, supported classical and ML-DSA secure-boot profiles are represented consistently, and gateway/UART/broker/hardware evidence boundaries agree. Reduce duplicated policy and identity blocks by linking to canonical owners where practical. Do not change implementation code, configs, CI, hardware tests, or roadmap plans in this phase.
```

### Verification Commands

```powershell
git grep -n "python scripts/experiment.py" -- "docs/*.md" "experiment/mqtt-broker/README.md"
git grep -n "cmake --preset" -- "docs/*.md"
git grep -n "mldsa44\|mldsa65" docs/005_remote_flash_workflow.md
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- Wrapper commands are the operational default.
- Native commands are diagnostic fallback only.
- Generated-state provenance is documented.
- Secure-boot profile coverage is consistent.
- Evidence boundaries remain explicit.
- Unit tests pass.

---

## Phase D2.4 — Reconcile Plans and Consolidate Deferred Test Coverage

### Goal

Make active and historical plans communicate status consistently and consolidate deferred test obligations into one discoverable register.

### Outcomes

- `docs/non_hardware_mqtt_tls_development_plan.md` has a consistent status block for every phase.
- Each status block records:
  - status
  - implemented evidence boundary
  - verification
  - remaining limitations
  - deferred tests
  - last reconciled date
- `docs/pqc_iot_experiment_framework_plan.md` is clearly labelled as active or historical.
- Duplicate detailed MQTT phase tracking is removed from the master plan or replaced with a canonical link.
- Completed work is not left unchecked without explanation.
- `docs/007_framework_architecture.md` contains one consolidated deferred-test register.
- Each deferred item records:
  - feature
  - missing test layer
  - reason
  - required capability or phase
  - intended test file
  - eventual verification command
  - status
- Existing scattered deferred items are migrated without losing information.

### Files Likely to Change

- `docs/non_hardware_mqtt_tls_development_plan.md`
- `docs/pqc_iot_experiment_framework_plan.md`
- `docs/007_framework_architecture.md`
- documentation tests

### Expected Evidence

- Every MQTT phase has the same status structure.
- The master plan has an explicit role and reconciliation status.
- Deferred tests are discoverable in one location.
- Structural tests validate required plan and deferred-test fields.
- No runtime or hardware claim is added without evidence.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D2.4 of the attached documentation remediation plan - Reconcile Plans and Consolidate Deferred Test Coverage. Inspect the current MQTT development plan, master framework plan, architecture document, AI build guide deferred-test rules, tracked test inventory, and relevant implementation evidence. Add a standard status block to every MQTT phase, clearly classify the master framework plan as active or historical, remove duplicate live MQTT status tracking from the master plan in favor of the canonical MQTT plan, and reconcile completed versus outstanding work. Consolidate all deferred integration, gateway, UART, firmware-runtime, network, and hardware test obligations into one structured register in `docs/007_framework_architecture.md`. Preserve historical goals and pass criteria. Add structural tests for the required status and deferred-test fields. Do not implement any deferred feature or test in this documentation-only phase.
```

### Verification Commands

```powershell
git grep -n "Implementation Status\|Status:" docs/non_hardware_mqtt_tls_development_plan.md
git grep -n "Deferred test coverage" docs/007_framework_architecture.md
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- Every MQTT phase has a consistent status block.
- The master plan has one explicit role.
- MQTT phase status has one canonical owner.
- Deferred tests are consolidated and structured.
- No deferred test item is silently dropped.
- Unit tests pass.

---

# Priority 3 — Tightening, Ownership, and Automated Maintenance

## Goal

Reduce duplication, establish clear document ownership, improve discoverability, and add durable automated protection against future drift.

Priority 3 is split into four phases so document restructuring and test enforcement can be reviewed separately.

---

## Phase D3.1 — Add the Project Documentation Index and Ownership Map

### Goal

Create a project-owned documentation index that future users and AI requests can use to discover every maintained document and its canonical role.

### Outcomes

- New `docs/README.md` indexes all project-owned documentation.
- Each indexed document records:
  - path
  - classification
  - canonical role
  - intended audience
  - whether it is current, active plan, historical plan, decision record, or operational guide
- Root `README.md` and `AI_BUILD_GUIDE.md` link to `docs/README.md`.
- Third-party and submodule documentation is explicitly excluded from project-owned maintenance checks.
- Broker documentation under `experiment/mqtt-broker/` is included as project-owned topical documentation.
- Unknown or orphan project-owned documents are either indexed, reclassified, relocated, or removed.

### Files Likely to Change

- new `docs/README.md`
- `README.md`
- `AI_BUILD_GUIDE.md`
- any orphan-document headers requiring classification
- documentation tests

### Expected Evidence

- Every tracked project-owned documentation file appears in the index.
- Vendor and submodule docs are excluded by rule.
- Structural test checks index coverage.
- No code or runtime changes.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D3.1 of the attached documentation remediation plan - Add the Project Documentation Index and Ownership Map. Inspect the current tracked-file inventory, all project-owned documentation, AI build guide, root README, broker documentation, and documentation tests. Create `docs/README.md` as the canonical project documentation index. Classify every project-owned document by role and lifecycle, identify its canonical subject ownership and audience, and explicitly exclude vendor and submodule documentation from project-maintained consistency checks. Link the new index from the root README and AI build guide. Resolve any orphan project-owned documentation by indexing, reclassifying, relocating, or removing it while preserving unrelated content. Add structural tests that fail when a project-owned document is not indexed.
```

### Verification Commands

```powershell
git ls-files | Where-Object {
    $_ -eq "README.md" -or
    $_ -eq "AI_BUILD_GUIDE.md" -or
    $_ -like "docs/*.md" -or
    $_ -like "docs/*.txt" -or
    $_ -like "docs/decisions/*.md" -or
    $_ -eq "experiment/mqtt-broker/README.md" -or
    $_ -eq "experiment/mqtt-broker/config/oqs/README.md"
} | Sort-Object

.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- Every project-owned document is indexed.
- Each document has a clear role and lifecycle.
- Vendor/submodule docs are excluded.
- README and AI build guide link to the index.
- Unit tests pass.

---

## Phase D3.2 — Tighten `AI_BUILD_GUIDE.md`

### Goal

Reduce the AI build guide to a compact source of truth for AI-assisted development without retaining full phase history or duplicating detailed operational documentation.

### Outcomes

- The guide retains:
  - purpose and authority
  - concise current capability boundaries
  - repository navigation
  - default workflow model
  - testing rules
  - evidence rules
  - secrets and safety rules
  - AI implementation/review workflow
  - documentation routing
- Detailed phase narratives are moved to canonical architecture or plan documents.
- Exhaustive test-file and module-file lists are replaced with stable directory-level maps and critical exceptions.
- Long command references are reduced to representative entry points with links.
- The guide remains sufficient to start a fresh feature request safely.
- The guide links to the documentation index, architecture matrix, deferred-test register, active plans, and operational guides.

### Files Likely to Change

- `AI_BUILD_GUIDE.md`
- `docs/README.md`, only if ownership links need adjustment
- documentation tests

### Expected Evidence

- Significant reduction in duplicated phase-specific content.
- All mandatory AI workflow and safety rules remain.
- Structural tests validate required sections and canonical links.
- No implementation status is lost because detail remains in canonical documents.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D3.2 of the attached documentation remediation plan - Tighten `AI_BUILD_GUIDE.md`. Inspect the current guide, documentation index, architecture capability matrix, deferred-test register, README, operational documents, active plans, and AI workflow instructions. Rewrite the guide as a compact AI source of truth that preserves all mandatory safety, evidence, testing, workflow, repository-layout, and artifact-delivery rules while removing detailed phase history, duplicated command manuals, exhaustive unstable file lists, and topic detail owned by other documents. Replace removed detail with precise links to canonical documents. Do not weaken any safety constraint, secret rule, capability boundary, test requirement, or implementation/review response requirement. Update structural documentation tests accordingly.
```

### Verification Commands

```powershell
(Get-Content AI_BUILD_GUIDE.md).Count
git grep -n "Phase M" AI_BUILD_GUIDE.md
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- Guide remains complete for fresh AI feature requests.
- Mandatory rules are preserved.
- Detailed phase history is removed.
- Canonical documents own detailed architecture and roadmap content.
- Unit tests pass.

---

## Phase D3.3 — Tighten `README.md` and Reorganize Architecture by Capability

### Goal

Return the README to a concise human-facing entry point and organize the architecture document around stable capabilities rather than chronological phase history.

### Outcomes

- `README.md` contains:
  - project purpose
  - concise current implementation summary
  - common commands
  - short direct-flash and secure-boot examples
  - short test and MQTT/broker orientation
  - safety/evidence warning
  - links to canonical detailed documents
- Detailed CI, benchmark, broker, MQTT, generated-state, pin-map, and phase-history material is moved or linked rather than duplicated.
- `docs/007_framework_architecture.md` is organized by:
  - system layers
  - firmware boundaries
  - framework boundaries
  - evidence model
  - build/generated-state model
  - test architecture
  - capability matrix
  - deferred-test register
  - historical references
- Phase identifiers remain in plans or historical references, not as the main architecture structure.
- Valid information is preserved during redistribution.

### Files Likely to Change

- `README.md`
- `docs/007_framework_architecture.md`
- `docs/README.md`
- topic documents receiving moved detail, only where needed
- documentation tests

### Expected Evidence

- README is materially shorter and easier to navigate.
- Architecture is capability-oriented.
- No current implementation boundary, safety rule, or deferred test is lost.
- Unit tests pass.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D3.3 of the attached documentation remediation plan - Tighten `README.md` and Reorganize Architecture by Capability. Inspect the documentation index, current README, architecture document, canonical operational documents, active plans, AI build guide, and documentation tests. Reduce the README to a concise human-facing entry point with common commands and links. Reorganize `docs/007_framework_architecture.md` around stable system capabilities, evidence boundaries, build/generated-state architecture, test architecture, the capability matrix, and the deferred-test register rather than chronological phase history. Preserve valid technical detail by moving it to the correct canonical owner or linking to it. Do not remove safety constraints, evidence limitations, supported workflow guidance, or deferred-test obligations. Update documentation tests.
```

### Verification Commands

```powershell
(Get-Content README.md).Count
(Get-Content docs/007_framework_architecture.md).Count
git grep -n "^### Phase" README.md docs/007_framework_architecture.md
.\scripts\dev.ps1 pytest tests/unit
```

### Pass Criteria

- README is concise and task-oriented.
- Architecture is capability-oriented.
- Phase history remains discoverable through plans and references.
- No technical or safety obligation is lost.
- Unit tests pass.

---

## Phase D3.4 — Add Comprehensive Documentation Integrity Tests

### Goal

Add durable automated checks that detect structural documentation drift before it becomes established.

### Outcomes

- New `tests/unit/test_documentation_integrity.py` or equivalent provides focused documentation integrity coverage.
- Tests verify:
  - every project-owned document is indexed
  - every indexed path exists and is tracked
  - required canonical documents exist
  - active docs do not contain prohibited `keysclean` guidance
  - Docker wrappers are documented as the default
  - host-native command sections are labelled fallback where present
  - active plans contain required status metadata
  - historical plans contain lifecycle/status notices
  - the canonical MQTT plan path is correct
  - deferred-test register entries contain required fields
  - AI workflow references resolve
  - vendor/submodule docs are excluded from ownership checks
- Existing `test_docker_default_workflow_docs.py` is retained, merged, or narrowed to avoid duplicate test ownership.
- Test failures clearly identify the missing or inconsistent document.
- Tests avoid brittle full-document snapshots.

### Files Likely to Change

- new `tests/unit/test_documentation_integrity.py`
- `tests/unit/test_docker_default_workflow_docs.py`
- documentation files only if testable metadata is missing
- `docs/README.md`

### Expected Evidence

- Targeted documentation integrity tests pass.
- Full unit suite passes.
- Full capability-gated pytest selection passes or skips unavailable capabilities normally.
- No hardware, gateway, UART, or network success claim is required.

### Suggested AI Prompt

```text
Treat this as a fresh project request. Do not rely on prior chats, prior uploaded files, memory, or inferred repository state.

Requirement: Implement Phase D3.4 of the attached documentation remediation plan - Add Comprehensive Documentation Integrity Tests. Inspect the documentation index, AI build guide, README, architecture matrix and deferred-test register, active and historical plans, existing documentation tests, tracked-file inventory behavior, and repository test conventions. Add focused unit coverage that verifies project-owned documentation indexing, tracked path validity, canonical document presence, prohibited unsafe command absence, Docker-default wording, diagnostic fallback labelling, plan status metadata, historical lifecycle notices, canonical MQTT plan path, deferred-test entry structure, and valid AI workflow references. Exclude vendor and submodule docs from ownership checks. Refactor existing documentation tests where needed to avoid duplication, but preserve their current intent. Avoid brittle full-file snapshots. Do not change runtime implementation, firmware, CI behavior, gateway tests, or hardware tests.
```

### Verification Commands

```powershell
.\scripts\dev.ps1 pytest tests/unit/test_documentation_integrity.py
.\scripts\dev.ps1 pytest tests/unit/test_docker_default_workflow_docs.py
.\scripts\dev.ps1 pytest tests/unit
.\scripts\dev.ps1 pytest
```

### Pass Criteria

- Documentation integrity tests pass.
- Existing Docker workflow documentation tests remain covered.
- Full unit suite passes.
- Full pytest selection passes or skips unavailable capabilities according to the established capability model.
- Structural documentation drift produces clear test failures.

---

# Overall Completion Criteria

The documentation consistency and AI discoverability remediation is complete when:

- Unsafe legacy wolfBoot cleanup guidance is absent.
- Signing-state and generated-state wording is consistent and safe.
- All AI workflow references resolve to tracked files.
- MQTT broker and host wolfMQTT examples match the implemented command contracts.
- One canonical architecture capability matrix defines current implementation boundaries.
- AI build guide, README, overview, baseline app, workflow docs, and plans agree with that matrix.
- Docker wrappers are the documented normal path.
- Host-native commands are diagnostic fallback only.
- Active plans contain consistent status records.
- Historical plans and decision records are clearly classified.
- Deferred test obligations are consolidated into one discoverable register.
- Every project-owned document appears in `docs/README.md`.
- Vendor and submodule documentation is excluded from project-owned consistency checks.
- `AI_BUILD_GUIDE.md` is compact enough to function as a practical fresh-chat source of truth.
- `README.md` is a concise human entry point.
- `docs/007_framework_architecture.md` is capability-oriented rather than phase-history-oriented.
- Automated documentation integrity tests protect the document hierarchy, references, ownership, and safety rules.
- Documentation-only changes do not claim build, signing, gateway, hardware, UART, timing, memory, MQTT/TLS, benchmark, or end-to-end success without explicit evidence.

# Recommended Execution Order

Execute the phases in this order:

```text
D1.1
D1.2
D1.3
D1.4
D2.1
D2.2
D2.3
D2.4
D3.1
D3.2
D3.3
D3.4
```

Do not combine phases by default. A phase may be combined with the immediately adjacent phase only when inspection shows that the same small file set must be changed atomically and the combined request remains reviewable.

# Standard Verification After Each Documentation Phase

At minimum:

```powershell
.\scripts\dev.ps1 pytest tests/unit
```

After phases that add or modify documentation integrity tests:

```powershell
.\scripts\dev.ps1 pytest tests/unit/test_documentation_integrity.py
.\scripts\dev.ps1 pytest tests/unit/test_docker_default_workflow_docs.py
.\scripts\dev.ps1 pytest tests/unit
```

After Priority 1, Priority 2, and Priority 3 are each complete:

```powershell
.\scripts\dev.ps1 pytest
```

A plain full pytest run may skip unavailable gateway or hardware capabilities according to the established test model. Do not treat skipped unavailable capabilities as evidence that those capabilities succeeded.
