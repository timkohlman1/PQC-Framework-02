# Documentation index

This is the complete project-owned topic and ownership map. The
[root README](../README.md) is the quick start; this index selects the detailed
reference. Each subject has one owner. A link to a plan or decision does not make
its historical claims current.

## Choose by task

| Task | Read |
|---|---|
| Change firmware/framework behavior | [AI guide](../AI_BUILD_GUIDE.md), then [architecture](007_framework_architecture.md) and the relevant source |
| Select workloads or alter orchestration | [Configuration and campaigns](011_experiment_configuration.md) |
| Build, sign, flash, queue or recover | [Operating guide](005_remote_flash_workflow.md) |
| Interpret captures or run analysis | [Results and analysis](012_results_and_analysis.md) |
| Choose validation or inspect missing coverage | [Testing and deferred coverage](013_testing_and_deferred_coverage.md) |
| Handle credentials or signing state | [Security policy](006_security_and_secrets.md) |
| Set up a bounded subsystem | The setup, broker, OTA, benchmark or instrument guide below |

AI agents enter through [AGENTS.md](../AGENTS.md) and the
[AI build guide](../AI_BUILD_GUIDE.md), then read only the relevant topic/source
files. Historical request labels do not authorize implementing those requests.

## Project-owned inventory

Paths in the first column are repository-relative labels with usable links.
Current references describe maintained behavior; operational guides own procedures;
AI workflows own process. Historical plans and decision records preserve context
and are not current capability or command authorities.

| Document | Owns | Status |
|---|---|---|
| [AGENTS.md](../AGENTS.md) | Direct-repository agent entry point and routing | AI workflow |
| [AI_BUILD_GUIDE.md](../AI_BUILD_GUIDE.md) | Normative AI engineering, evidence, safety and testing rules | Current reference |
| [README.md](../README.md) | Project entry point and common commands | Current reference |
| [analysis_implementation_requests.md](../analysis_implementation_requests.md) | Original A1–A8/S1–S2 request plan; current behavior belongs to the results reference | Historical plan |
| [docs/000_project_overview.md](000_project_overview.md) | Research purpose and scope; routes current detail to topic owners | Current reference |
| [docs/001_ai_feature_request_workflow.md](001_ai_feature_request_workflow.md) | Canonical direct-repository implementation/review workflow and selected-file upload fallback | AI workflow |
| [docs/002_host_gateway_setup.md](002_host_gateway_setup.md) | Development-host access, SSH configuration, and gateway identity | Operational guide |
| [docs/003_stm32_board_setup.md](003_stm32_board_setup.md) | Board, ST-LINK, UART, memory, and physical hardware setup | Operational guide |
| [docs/004_baseline_hal_app.md](004_baseline_hal_app.md) | Firmware startup, task ownership and diagnostic interpretation | Current reference |
| [docs/005_remote_flash_workflow.md](005_remote_flash_workflow.md) | Docker-wrapper build, signing, flash, secure-boot, and UART workflows | Operational guide |
| [docs/006_security_and_secrets.md](006_security_and_secrets.md) | Secret handling, private generated state, signing-tuple safety, and packaging exclusions | Current reference |
| [docs/007_framework_architecture.md](007_framework_architecture.md) | Implemented components, data flow, dependency and capability boundaries | Current reference |
| [docs/008_chatgpt_project_prompt.md](008_chatgpt_project_prompt.md) | Reusable prompt routing direct-repository sessions to AGENTS.md and retaining the upload-based ChatGPT fallback | AI workflow |
| [docs/009_dual_bank_ota_workflow.md](009_dual_bank_ota_workflow.md) | STM32L4R5 dual-bank firmware modes, authenticated OTA staging/activation, rollback/confirmation behavior, and OTA evidence/test workflow | Current reference |
| [docs/010_esp32_ina228_energy_instrument.md](010_esp32_ina228_energy_instrument.md) | Retained appliance, optional STM32/framework capture, raw acceptance and physical validation | Current reference |
| [docs/011_experiment_configuration.md](011_experiment_configuration.md) | Profile composition, firmware/configuration identity, campaign/queue/collection semantics | Current reference |
| [docs/012_results_and_analysis.md](012_results_and_analysis.md) | Capture/provenance schema, metric meanings, offline analysis and report commands | Current reference |
| [docs/013_testing_and_deferred_coverage.md](013_testing_and_deferred_coverage.md) | Test layers, documentation contracts and the sole deferred-test register | Current reference |
| [docs/README.md](README.md) | Complete project documentation inventory and topic ownership | Current reference |
| [docs/baremetal_benchmark_measurement_core.md](baremetal_benchmark_measurement_core.md) | Primitive measurement boundaries, operation support and benchmark commands | Operational guide |
| [docs/decisions/0001_keep_cubemx_project_at_repo_root.md](decisions/0001_keep_cubemx_project_at_repo_root.md) | Rationale for retaining the CubeMX project at repository root | Decision record |
| [docs/decisions/0002_wolfboot_stm32l4_target_support_assessment.md](decisions/0002_wolfboot_stm32l4_target_support_assessment.md) | wolfBoot STM32L4 target support assessment and accepted direction | Decision record |
| [docs/decisions/0003_secure_boot_flash_layout.md](decisions/0003_secure_boot_flash_layout.md) | STM32L4R5 secure-boot flash layout decision and rationale | Decision record |
| [experiment/mqtt-broker/README.md](../experiment/mqtt-broker/README.md) | Canonical MQTT broker Compose profiles, provisioning, deployment, validation, and broker evidence limits | Operational guide |
| [experiment/mqtt-broker/config/oqs-mtls/README.md](../experiment/mqtt-broker/config/oqs-mtls/README.md) | Mutual-TLS profile entry point and certificate/KEX separation | Operational guide |
| [experiment/mqtt-broker/config/oqs/README.md](../experiment/mqtt-broker/config/oqs/README.md) | OQS Mosquitto profile algorithms, generated certificate material, and runtime diagnostic limits | Operational guide |
| [instruments/esp32_ina228/README.md](../instruments/esp32_ina228/README.md) | Routes the extracted device source to its instrument guide; does not establish surrounding framework integration | Current reference |

## Inventory maintenance

Include tracked and non-ignored working-tree Markdown documents at the repository
root, Markdown/text under `docs/`, broker README files, and the instrument entry
README. Add, move, remove or reclassify their index row in the same change.
Vendor/submodule documentation, generated results/builds and dependency caches
are excluded; `.gitmodules` defines submodule roots. Do not duplicate upstream
manuals here.

Keep operational commands in their topic guide, current component boundaries in
the architecture, measurement definitions in the results reference, and outstanding
validation in the testing register. Retire superseded narratives instead of
appending another request history to a current reference. Git history preserves
replaced text. Documentation tests check coverage and navigation, not paragraph
wording; capability claims still require source and appropriate evidence review.
