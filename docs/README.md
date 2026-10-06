# Documentation index

The [root README](../README.md) owns orientation and common commands. This index
selects one canonical owner per topic and inventories all project-owned documents
and notebooks. Historical records preserve context; their old instructions and
capability claims are not current authorities.

## Choose by task

| Task | Read |
|---|---|
| Develop or review with AI | [AGENTS.md](../AGENTS.md), [AI guide](../AI_BUILD_GUIDE.md), then relevant source/topic files |
| Understand implemented boundaries | [Architecture](007_framework_architecture.md) |
| Change profiles/orchestration | [Configuration](011_experiment_configuration.md) |
| Set up the lab | [Host/gateway](002_host_gateway_setup.md), [board](003_stm32_board_setup.md), [broker](../experiment/mqtt-broker/README.md) |
| Build/sign/flash or diagnose one case | [Operating guide](005_remote_flash_workflow.md) |
| Edit local profiles or manage jobs | [Terminal queue](014_campaign_queue.md) |
| Run/resume batches and thesis collections | [Campaign collection](015_campaign_collection.md) |
| Interpret evidence or export/analyse it | [Results and analysis](012_results_and_analysis.md) |
| Select validation or inspect gaps | [Testing and deferred coverage](013_testing_and_deferred_coverage.md) |
| Handle experiment keys, Wi-Fi settings or other material | [Open experimental-data policy](006_security_and_secrets.md) |

Read the shortest relevant owner first; do not load every document for each task.
The open policy is the single classification authority. Current code may still
redact or omit fields; those implementation behaviors do not reinstate old policy.

## Project-owned inventory

Paths in the first column are repository-relative. Operational guides own procedures;
references own contracts; AI workflows own process. Executable notebooks are entry
points into maintained code, not independent metric definitions. The exploratory
notebook is retained user analysis. Decision records and the analysis request plan
are historical and do not instruct agents to implement old phases again.

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
| [docs/005_remote_flash_workflow.md](005_remote_flash_workflow.md) | Single-case build, signing, flashing, UART and diagnostics | Operational guide |
| [docs/006_security_and_secrets.md](006_security_and_secrets.md) | Sole open experimental-data policy; signing identity and reproduction-material ownership | Current reference |
| [docs/007_framework_architecture.md](007_framework_architecture.md) | Implemented components, data flow, dependency and capability boundaries | Current reference |
| [docs/008_chatgpt_project_prompt.md](008_chatgpt_project_prompt.md) | Reusable prompt routing direct-repository sessions to AGENTS.md and retaining the upload-based ChatGPT fallback | AI workflow |
| [docs/009_dual_bank_ota_workflow.md](009_dual_bank_ota_workflow.md) | STM32L4R5 dual-bank firmware modes, authenticated OTA staging/activation, rollback/confirmation behavior, and OTA evidence/test workflow | Current reference |
| [docs/010_esp32_ina228_energy_instrument.md](010_esp32_ina228_energy_instrument.md) | Retained appliance, optional STM32/framework capture, raw acceptance and physical validation | Current reference |
| [docs/011_experiment_configuration.md](011_experiment_configuration.md) | Profile composition, firmware/configuration identity, campaign/queue/collection semantics | Current reference |
| [docs/012_results_and_analysis.md](012_results_and_analysis.md) | Capture/provenance schema, metric meanings, offline analysis and report commands | Current reference |
| [docs/013_testing_and_deferred_coverage.md](013_testing_and_deferred_coverage.md) | Test layers, documentation contracts and the sole deferred-test register | Current reference |
| [docs/014_campaign_queue.md](014_campaign_queue.md) | Terminal queue/profile controls, recovery and selected-job export | Operational guide |
| [docs/015_campaign_collection.md](015_campaign_collection.md) | Campaign execution/resume, pilot recipes and frozen thesis collections | Operational guide |
| [docs/016_reliability_trials.md](016_reliability_trials.md) | Explicit destructive reset and independent RM2 reliability trials | Operational guide |
| [docs/README.md](README.md) | Complete project documentation inventory and topic ownership | Current reference |
| [docs/baremetal_benchmark_measurement_core.md](baremetal_benchmark_measurement_core.md) | Primitive measurement boundaries, operation support and benchmark commands | Operational guide |
| [docs/decisions/0001_keep_cubemx_project_at_repo_root.md](decisions/0001_keep_cubemx_project_at_repo_root.md) | Rationale for retaining the CubeMX project at repository root | Decision record |
| [docs/decisions/0002_wolfboot_stm32l4_target_support_assessment.md](decisions/0002_wolfboot_stm32l4_target_support_assessment.md) | wolfBoot STM32L4 target support assessment and accepted direction | Decision record |
| [docs/decisions/0003_secure_boot_flash_layout.md](decisions/0003_secure_boot_flash_layout.md) | STM32L4R5 secure-boot flash layout decision and rationale | Decision record |
| [experiment/mqtt-broker/README.md](../experiment/mqtt-broker/README.md) | Canonical MQTT broker Compose profiles, provisioning, deployment, validation, and broker evidence limits | Operational guide |
| [experiment/mqtt-broker/config/oqs-mtls/README.md](../experiment/mqtt-broker/config/oqs-mtls/README.md) | Mutual-TLS profile entry point and certificate/KEX separation | Operational guide |
| [experiment/mqtt-broker/config/oqs/README.md](../experiment/mqtt-broker/config/oqs/README.md) | OQS Mosquitto profile algorithms, generated certificate material, and runtime diagnostic limits | Operational guide |
| [instruments/esp32_ina228/README.md](../instruments/esp32_ina228/README.md) | Routes the extracted device source to its instrument guide; does not establish surrounding framework integration | Current reference |
| [notebooks/00_checkout.ipynb](../notebooks/00_checkout.ipynb) | Host-Docker checkout and unit-test diagnostics | Executable notebook |
| [notebooks/Memory_Analysis.ipynb](../notebooks/Memory_Analysis.ipynb) | Exploratory saved analysis with local paths; not a maintained parser or validation gate | Exploratory notebook |
| [notebooks/energy_comparison.ipynb](../notebooks/energy_comparison.ipynb) | Energy comparison using maintained offline analysis | Executable notebook |
| [notebooks/network_comparison.ipynb](../notebooks/network_comparison.ipynb) | Network comparison using maintained offline analysis | Executable notebook |
| [notebooks/research_report.ipynb](../notebooks/research_report.ipynb) | Research report using maintained offline analysis | Executable notebook |
| [notebooks/secure_boot_comparison.ipynb](../notebooks/secure_boot_comparison.ipynb) | Secure boot comparison using maintained offline analysis | Executable notebook |
| [notebooks/timing_comparison.ipynb](../notebooks/timing_comparison.ipynb) | Timing comparison using maintained offline analysis | Executable notebook |
| [notebooks/tls_attribution.ipynb](../notebooks/tls_attribution.ipynb) | Tls attribution using maintained offline analysis | Executable notebook |
| [notebooks/tls_matrix_energy.ipynb](../notebooks/tls_matrix_energy.ipynb) | Timing notebook for the TLS/energy pilot using its explicit preset | Executable notebook |

## Maintenance boundary

Update this inventory when project documents/notebooks appear, move or change role.
Keep current behavior with its owner and link to it rather than copying procedures.
Use historical banners for decisions/plans whose original statements are retained.
Do not append implementation-request diaries to current guides.

Submodule/vendor documentation belongs to its upstream source and is excluded from
this inventory. Firmware/API comments and CLI help remain colocated with their code;
profile/spec JSON and YAML are executable configuration, linked by topic references.
Generated results and exported notebooks under ignored `results/` are evidence, not
maintained documentation. Structural tests check this inventory, links, command
interfaces and selected contracts; source inspection establishes semantic accuracy.
