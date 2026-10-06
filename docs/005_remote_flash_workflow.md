# Build, flash and experiment operation

Run commands from the repository root on Linux through `./scripts/dev.sh`.
[Host/gateway setup](002_host_gateway_setup.md) owns prerequisites and gateway
coordination; [configuration](011_experiment_configuration.md) owns case semantics.
For interactive jobs use the [queue guide](014_campaign_queue.md); for batches and
thesis reports use [campaign collection](015_campaign_collection.md).

## Resolve, inspect and run a case

```bash
./scripts/dev.sh python scripts/resolve_campaign.py baseline.yaml
case_file=$(compgen -G '.pqc-generated-state/campaigns/baseline/cases/0001_*.yaml' | sort | head -n 1)
./scripts/dev.sh experiment status --experiment "$case_file"
./scripts/dev.sh experiment build --experiment "$case_file"
```

`baseline` selects Ready Metrics, classical TLS server authentication and
`integrity_sha256` boot. Check the generated case before execution. Certificates
must already be provisioned using the [broker guide](../experiment/mqtt-broker/README.md);
Wi-Fi inputs come from the caller environment or ignored `.env`.

With the configured board, gateway and brokers available:

```bash
./scripts/dev.sh experiment-gateway run --experiment "$case_file"
```

The normal wolfBoot `run` path owns dependency validation, bootloader/application
builds, packaging/signing, flashing, broker lifecycle, reset, capture and cleanup.
Standalone build/sign/flash commands are not prerequisites for it. The case's
secure-boot selection controls boot cryptography independently of TLS. An explicit
conflicting boot-algorithm override fails before hardware actions.

Current CMake builds always use `STM32L4R5XX_FLASH_RELOCATED.ld`: signed slot
`0x08020000`, 12 KiB header reserve, application vector `0x08023000`. Release is
the default; `--debug` selects Debug settings with the same addresses. A legacy
`flash` helper does not create an unrelocated application build.

## Separate secure-boot stages

For diagnosis or controlled signing experiments, use a consistent algorithm and
firmware mode throughout. The following selects the baseline's integrity-only
profile; it packages the image with SHA-256 and provides no signature authentication.

```bash
./scripts/dev.sh experiment build-wolfboot --boot-algorithm integrity_sha256
./scripts/dev.sh experiment build --experiment "$case_file" --configure-preset Release --build-preset Release --artifact build/Release/stm32_basic_hal1.elf
./scripts/dev.sh experiment sign-application --boot-algorithm integrity_sha256
./scripts/dev.sh experiment-gateway flash-secure-boot --experiment "$case_file" --boot-algorithm integrity_sha256
```

For signed profiles, resolve the intended campaign first and select its algorithm
consistently. Algorithm definitions are in `configs/secure_boot/`; shared layout
and generated wolfBoot settings come from the target/profile resolver. The
[configuration reference](011_experiment_configuration.md) lists supported choices.
The [OTA guide](009_dual_bank_ota_workflow.md) owns dual-bank operations.

Framework build records and generated-state preflight bind signing/flashing to
exact successful artifacts. Direct CMake does not supply that provenance.
Persistent tuples and disposable wolfBoot-local materializations have different
lifecycles: the owning build can restore materializations from a validated tuple.
Partial/mismatched persistent tuples fail; do not delete members or run `keysclean`
as routine repair. See [signing-state policy](006_security_and_secrets.md#wolfboot-signing-state).

## Flash and UART diagnostics

`flash` consumes a recorded application build; `build-flash` builds first. Both
capture UART only with `--capture-uart`. These compatibility helpers do not replace
the complete wolfBoot/broker/reporting workflow:

```bash
./scripts/dev.sh experiment-gateway flash --experiment "$case_file" --build-run <run_id> --capture-uart
./scripts/dev.sh experiment-gateway build-flash --experiment "$case_file" --capture-uart
./scripts/dev.sh experiment-gateway monitor --experiment "$case_file" --duration-seconds 10
./scripts/dev.sh experiment-gateway monitor --experiment "$case_file" --duration-seconds 10 --restart
```

`flash` refuses untracked/mismatched artifacts unless the explicit manual-recovery
option `--allow-untracked-artifact` is supplied. A monitor-only capture has no
result manifest and cannot establish image identity by itself. UART mode belongs
to the case; diagnostic markers are not universal scientific success predicates.
[Baseline firmware](004_baseline_hal_app.md) describes their meaning.

`flash-secure-boot` captures UART unless `--skip-uart` is supplied. Its focused
positive check uses secure-boot, boot and configured tick-substring diagnostics;
it is distinct from networked reporting acceptance. Default single-capture startup
can pass without legacy aggregate timing. Explicit `--repeat-count` benchmarking
also requires valid timing for every sample. `--skip-uart` proves flashing only.

For rejection tests, `--negative-corrupt-application` mutates a result-local copy.
`--negative-corruption-method payload_byte_flip` tests integrity rejection;
`signature_byte_flip` requires a signed profile and targets authenticity.
Header-byte corruption is a separate malformed-image control. Preserve canonical
images and keys, retain flash/reset evidence, and verify known-good restoration.
Empty UART in a diagnostics-off rejected boot does not identify the rejection cause.

## Optional instrumentation

`boot_uart_diagnostics: true` enables blocking `PQC_WOLFBOOT_DIAG` output before
application handoff. It defaults off and perturbs boot elapsed time. Build-only
selection is also available:

```bash
./scripts/dev.sh experiment build-wolfboot --boot-algorithm integrity_sha256 --boot-uart-diagnostics
```

Use a matching application/case and rebuild after disabling diagnostics before
normal timing collection. Diagnostic messages supplement verification records;
they do not replace them.

The separate `secure_boot_stack` campaign selects boot stack watermarking:

```bash
./scripts/dev.sh python scripts/resolve_campaign.py secure_boot_stack.yaml
./scripts/dev.sh campaign-gateway secure_boot_stack
```

Normal timing comparisons exclude stack-profiled runs. Interpret measured versus
unavailable stack records using the [results reference](012_results_and_analysis.md#secure-boot).
The offline stack parser accepts retained manifests:

```bash
./scripts/dev.sh python scripts/analyse_secure_boot_stack.py results/<run-one>/manifest.json results/<run-two>/manifest.json --output-dir results/analysis/secure_boot_stack
```

## Capture, failures and verification

Networked runs normally retain `mqtt-reporting-raw.ndjson`, UART when enabled,
`gateway-network-capture.pcap`, broker logs and TLS key logs when applicable.
Required collection failure rejects capture even if application work completed.
The [results reference](012_results_and_analysis.md) owns artifact contracts,
packet decryption and offline analysis. Raw results remain generated/ignored; classification follows the
[open-data policy](006_security_and_secrets.md).

Progress rows report completed attempts, including failures/blocked slots, rather
than successful scientific samples. Inspect `console.log` in each run and
`campaign.log`/child logs for campaigns. Pytest retains diagnostic evidence under
`results/automated-tests/<test-run-id>/`, including setup and teardown failures.
Test-triggered builds are not normal reusable build records.

Hardware tests prepare their own cases and build/sign/flash prerequisites. With
laboratory capabilities available, focused gates include:

```bash
./scripts/dev.sh pytest-hardware tests/hardware/test_secure_boot_flash_workflow_hw.py --pqc-require-hardware
./scripts/dev.sh pytest-hardware tests/hardware/test_application_timebase_hw.py --pqc-require-hardware
```

Use [testing and deferred coverage](013_testing_and_deferred_coverage.md) to select
other gates. A build, flash, startup, accepted capture and valid metric establish
different boundaries. No pass is implied by the presence of these commands.
Host-native toolchain/SSH commands are bounded diagnostic fallbacks; they must not
bypass signing provenance, shared gateway coordination or the open-data policy.
