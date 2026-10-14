# PQC-Framework-02

STM32 embedded-security experiments on NUCLEO-L4R5ZI-P: wolfBoot secure boot,
MQTT/TLS, controlled network conditions and reproducible timing/resource/energy
evidence. The framework includes firmware, gateway orchestration, optional
ESP32/INA228 acquisition and offline analysis.

## Start here

The [documentation index](docs/README.md) is the complete topic/ownership map.
This README owns orientation and common entry commands.

- Understand the system: [architecture](docs/007_framework_architecture.md).
- Prepare the lab: [host/gateway setup](docs/002_host_gateway_setup.md) and
  [board setup](docs/003_stm32_board_setup.md).
- Run experiments: [operating guide](docs/005_remote_flash_workflow.md).
- Select profiles: [configuration and campaigns](docs/011_experiment_configuration.md).
- Inspect data: [results and analysis](docs/012_results_and_analysis.md).
- Develop with AI: start at [AGENTS.md](AGENTS.md), then
  [AI_BUILD_GUIDE.md](AI_BUILD_GUIDE.md). The maintained
  [AI workflow](docs/001_ai_feature_request_workflow.md) covers implementation and
  review; [the project prompt](docs/008_chatgpt_project_prompt.md) covers startup.

## Common commands

The default development path is Docker-hosted Linux execution through
`scripts/dev.sh`, from the repository root. Host-native builds are a diagnostic
fallback described in the operating guide. Gateway commands use runtime-mounted
SSH access and gateway-owned hardware helpers.

```bash
./scripts/dev.sh build-image
./scripts/dev.sh pytest tests/unit
./scripts/dev.sh python scripts/experiment.py --help
```

Resolve a source-controlled campaign, inspect one generated case, then build it:

```bash
./scripts/dev.sh python scripts/resolve_campaign.py baseline.yaml
case_file=$(compgen -G '.pqc-generated-state/campaigns/baseline/cases/0001_*.yaml' | sort | head -n 1)
./scripts/dev.sh experiment status --experiment "$case_file"
./scripts/dev.sh experiment build --experiment "$case_file"
```

With the configured laboratory prerequisites available, run that case or an
entire campaign:

```bash
./scripts/dev.sh experiment-gateway run --experiment "$case_file"
./scripts/dev.sh campaign-gateway baseline
```

For interactive profile editing, queuing and selected-data export, launch the
[terminal queue](docs/014_campaign_queue.md) on the
Linux host:

```bash
python3 scripts/run_queue.py
```

To compare an MQTT migration from current to future crypto/function choices,
run the [interactive migration tool](docs/014_campaign_queue.md#interactive-mqtt-migration-comparison):

```bash
python3 scripts/migration_compare.py
```

It queues both states, waits for completion and produces console and LaTeX
comparison/selection tables with signed absolute and percentage deltas.

For thesis tables and figures across all supported analysis domains, run `./scripts/dev.sh notebook`
and open [notebooks/analysis.ipynb](notebooks/analysis.ipynb). Choose a catalogue row and recipe,
preview the analysis, then save a reproducible revision; see the
[analysis workflow](docs/012_results_and_analysis.md#default-thesis-workflow).

Generated cases are the runner's operational inputs. Release is the default,
with a wolfBoot-relocated layout; the default `integrity_sha256` boot profile
checks the image digest without signature authentication. Detailed signing,
certificate, resume and hardware-test procedures belong in their topic guides.

## Evidence and safety

A supported implementation is not proof that a particular profile ran successfully.
Build-only, local/fake, host/broker and STM32 hardware evidence remain distinct.
Capture acceptance, scientific validity and comparison eligibility are separate.
Consult the [test reference](docs/013_testing_and_deferred_coverage.md) for coverage
and outstanding validation.

Use `.env.sample` as the template for ignored local Wi-Fi credentials and the
[broker guide](experiment/mqtt-broker/README.md) for certificate provisioning.
All framework experiment material, including private keys and dedicated Wi-Fi
settings, follows the [open-data policy](docs/006_security_and_secrets.md).
Generated-state integrity and recorded experiment identities still matter.
