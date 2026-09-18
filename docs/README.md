# Project Documentation Index and Ownership Map

## Purpose

This file is the canonical index for project-maintained documentation. Use it to locate the authoritative owner for a subject, determine a document's lifecycle, and distinguish project documentation from upstream material.

A document being indexed does not make every statement in it current. Lifecycle classifications below determine how it should be used.

## Ownership rules

Project-owned documentation consists of the tracked root entry documents, tracked documents under `docs/`, and the tracked MQTT broker documentation listed below. Every project-owned document must appear in this index.

Documentation inside vendor or submodule trees is upstream-owned and is excluded from project-maintained documentation consistency checks. The current submodule roots are:

- `tools/wolfboot/`
- `Middlewares/Third_Party/wolfMQTT/`
- `Middlewares/Third_Party/wolfSSL/`

Other third-party material under `Drivers/`, `Middlewares/Third_Party/`, generated build trees, virtual environments, result directories, and dependency caches is also outside this index unless a project-owned document is explicitly listed below.

## Lifecycle definitions

- **Current reference:** maintained description of the current project, policy, architecture, or workflow.
- **Operational guide:** maintained instructions for a bounded setup or operational task.
- **AI workflow:** maintained instructions or prompt material for AI-assisted work.
- **Active plan:** maintained roadmap with current implementation status and remaining work.
- **Historical plan:** preserved goals and sequencing; not a current-state authority.
- **Decision record:** preserved architectural decision and rationale; later current references may supersede operational details.
- **Remediation plan:** bounded maintenance plan used to execute documentation corrections.

## Canonical ownership map

| Path | Classification | Lifecycle | Canonical subject ownership | Intended audience |
|---|---|---|---|---|
| `AI_BUILD_GUIDE.md` | AI context guide | Current reference | AI-assisted development rules, safety constraints, evidence rules, test expectations, and repository navigation | AI assistants and developers preparing AI requests |
| `README.md` | Project entry point | Current reference | Human-facing purpose, current summary, common commands, and routing to detailed documentation | Developers, reviewers, operators |
| `docs/000_project_overview.md` | Project overview | Current reference | Detailed project purpose, scope, implemented boundaries, and evidence model overview | New developers, reviewers, researchers |
| `docs/001_ai_feature_request_workflow.md` | AI workflow guide | AI workflow | Canonical feature-request and review workflow for AI-assisted changes | Developers and AI assistants |
| `docs/002_host_gateway_setup.md` | Setup guide | Operational guide | Development-host access, SSH configuration, and gateway identity | Operators and developers using the gateway |
| `docs/003_stm32_board_setup.md` | Hardware setup guide | Operational guide | Board, ST-LINK, UART, memory, and physical hardware setup | Firmware developers and hardware operators |
| `docs/004_baseline_hal_app.md` | Firmware behavior reference | Current reference | Baseline HAL/FreeRTOS application behavior, UART markers, and local-smoke limitations | Firmware developers and test authors |
| `docs/005_remote_flash_workflow.md` | Workflow guide | Operational guide | Docker-wrapper build, signing, flash, secure-boot, and UART workflows | Operators, firmware developers, test authors |
| `docs/006_security_and_secrets.md` | Security policy | Current reference | Secret handling, private generated state, signing-tuple safety, and packaging exclusions | All contributors and operators |
| `docs/007_framework_architecture.md` | Architecture reference | Current reference | Detailed current architecture, capability matrix, evidence boundaries, file map, and deferred-test register | Developers, reviewers, test authors, researchers |
| `docs/008_chatgpt_project_prompt.md` | AI prompt | AI workflow | Maintained reusable project prompt that routes work through the canonical AI workflow | Developers starting AI-assisted work |
| `docs/009_dual_bank_ota_workflow.md` | Dual-bank OTA workflow | Current reference | STM32L4R5 dual-bank firmware modes, authenticated OTA staging/activation, rollback/confirmation behavior, and OTA evidence/test workflow | Firmware, secure-boot, OTA, and test maintainers |
| `docs/README.md` | Documentation index | Current reference | Project documentation inventory, ownership, lifecycle, audience, and exclusion rules | All documentation users and maintainers |
| `docs/decisions/0001_keep_cubemx_project_at_repo_root.md` | Architecture decision record | Decision record | Rationale for retaining the CubeMX project at repository root | Firmware and build-system maintainers |
| `docs/decisions/0002_wolfboot_stm32l4_target_support_assessment.md` | Architecture decision record | Decision record | wolfBoot STM32L4 target support assessment and accepted direction | Secure-boot and platform maintainers |
| `docs/decisions/0003_secure_boot_flash_layout.md` | Architecture decision record | Decision record | STM32L4R5 secure-boot flash layout decision and rationale | Secure-boot, linker, and firmware maintainers |
| `docs/local build commands.txt` | Local-tooling troubleshooting guide | Operational guide | Host-native diagnostic fallback commands; never the normal reproducible workflow | Developers diagnosing CubeMX, IDE, or local toolchain issues |
| `docs/non_hardware_mqtt_tls_development_plan.md` | MQTT/TLS roadmap | Active plan | Current phase status, evidence boundaries, remaining limitations, and deferred work for non-hardware MQTT/TLS development | Firmware, network, security, and test developers |
| `docs/pqc_iot_experiment_framework_plan.md` | Framework roadmap | Historical plan | Original framework goals, sequencing, checklists, and pass criteria | Maintainers reviewing project history and original intent |
| `experiment/mqtt-broker/README.md` | Broker operations guide | Operational guide | Canonical MQTT broker Compose profiles, provisioning, deployment, validation, and broker evidence limits | Network/security developers and gateway operators |
| `experiment/mqtt-broker/config/oqs/README.md` | OQS broker profile reference | Operational guide | OQS Mosquitto profile algorithms, generated certificate material, and runtime diagnostic limits | PQC/TLS experimenters and broker maintainers |

## Subject routing

Use `README.md` for initial orientation and common commands. Use `AI_BUILD_GUIDE.md` and `docs/001_ai_feature_request_workflow.md` for AI-assisted changes. Use `docs/007_framework_architecture.md` for detailed current capability and evidence questions. Use the topic-specific operational guide for setup or execution details. Use the active MQTT/TLS plan for current roadmap status. Treat the historical framework plan and decision records as preserved context rather than current operational authority.

## Maintenance contract

When adding, relocating, reclassifying, or removing a project-owned document:

1. Update this index in the same change.
2. Keep the path tracked and valid.
3. Assign one classification, lifecycle, canonical subject owner, and intended audience.
4. Avoid creating a second canonical owner for an existing subject.
5. Do not add vendor or submodule documentation to project-maintained consistency checks.

`tests/unit/test_documentation_integrity.py` enforces index coverage and tracked-path validity without snapshotting complete document contents.
