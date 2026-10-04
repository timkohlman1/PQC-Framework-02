# Remote Flash Workflow

## Purpose

This document owns the current Docker-wrapper direct-flash, secure-boot, and UART workflows. Run commands from the repository root. Host-native Python, CMake, Make, SCP, SSH, and toolchain commands are diagnostic fallback only; they are not the normal reproducible validation path.

Gateway identity is owned by `configs/gateways/pqc_gateway1.yaml` and explained in `docs/002_host_gateway_setup.md`. Board/ST-LINK/UART hardware identity is owned by `docs/003_stm32_board_setup.md`.

Direct-flash builds use the normal application layout. wolfBoot-secured builds use the relocated application vector at `0x08023000`, while the flash/update mechanism is selected by `firmware_mode`: `single_bank`, `dual_bank_no_ota`, or `dual_bank_ota`. Release is the default compiler configuration. Add `--debug` to select Debug compiler settings without changing the selected mode's flash addresses.

## Direct-flash workflow

Build through the Docker wrapper:

```bash
./scripts/dev.sh experiment build --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml
```

Flash an explicitly recorded build:

```bash
./scripts/dev.sh experiment-gateway flash --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml --build-run <run_id>
```

The untracked-artifact escape hatch is limited to manual recovery or investigation:

```bash
./scripts/dev.sh experiment-gateway flash --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml --allow-untracked-artifact
```

Build and flash, with optional UART capture:

```bash
./scripts/dev.sh experiment-gateway build-flash --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml
./scripts/dev.sh experiment-gateway build-flash --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml --capture-uart
```

Run the normal build/flash/UART baseline workflow:

```bash
./scripts/dev.sh experiment-gateway run --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml
```

The `flash` path refuses SCP/SSH unless the artifact matches recorded build provenance or the explicit recovery escape hatch is supplied.

## Secure-boot workflow

Secure boot consumes the configured wolfBoot artifact and signed relocated application. The secure-boot workflow selects one canonical target and algorithm. The normal command pattern is:

```bash
./scripts/dev.sh experiment build-wolfboot --boot-algorithm <algorithm>
./scripts/dev.sh experiment build --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml --configure-preset Release --build-preset Release --artifact build/Release/stm32_basic_hal1.elf
./scripts/dev.sh experiment sign-application --boot-algorithm <algorithm>
./scripts/dev.sh experiment-gateway flash-secure-boot --experiment .pqc-generated-state/campaigns/secure_boot/cases/<case>.yaml --boot-algorithm <algorithm>
```

Supported algorithm IDs are:

```text
Classical: integrity_sha256, ecdsa_p256, ecdsa_p384, ecdsa_p521, ed25519, ed448, rsa2048, rsa3072, rsa4096
ML-DSA:   mldsa44, mldsa65, mldsa87
```

`configs/targets/stm32l4r5_wolfboot.yaml` owns shared target configuration, `configs/secure_boot/*.yaml` owns the twelve supported secure-boot selections (including ML-DSA-87), `.pqc-generated-state/campaigns/secure_boot/cases/<case>.yaml` is the single secure-boot experiment entry point, and resolver-generated wolfBoot configuration provides the native build settings.

The relocated application build must run through the framework so generated-state provenance and the artifact hash are recorded before signing. `build-wolfboot`, `sign-application`, and `flash-secure-boot` use generated-state preflight as the primary compatibility, stale-output, and provenance mechanism.

The reusable signing tuple consists of the canonical private key, matching wolfBoot-local private key, generated public key, and generated `tools/wolfboot/src/keystore.c`:

- Completely absent tuple: the owning workflow may create it when the profile permits generation.
- Complete matching tuple: preserve and reuse it.
- Partially missing tuple: fail before build/signing; do not reconstruct members.
- Mismatched tuple: fail before build/signing; do not replace the canonical key or overwrite members.

Do not run wolfBoot `keysclean` or manually delete tuple members. Pytest startup cleanup is supplementary cross-platform hygiene only; it is not provenance validation and must not remove reusable signing state.

Negative corrupted-application test:

```bash
./scripts/dev.sh experiment-gateway flash-secure-boot --experiment .pqc-generated-state/campaigns/secure_boot/cases/<case>.yaml --boot-algorithm ecdsa_p256 --negative-corrupt-application
```

The workflow corrupts a result-local copy. It must not modify the canonical signed image or private key.

## UART capture

Direct-flash `flash` and `build-flash` capture UART only with `--capture-uart`; `run` captures UART after a successful flash. Secure-boot flashing captures UART unless `--skip-uart` is supplied. Repeated secure-boot samples are written as `uart_sample_001.log`, `uart_sample_002.log`, and so on.

Ad hoc bounded capture:

```bash
./scripts/dev.sh experiment-gateway monitor --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml --duration-seconds 10
./scripts/dev.sh experiment-gateway monitor --experiment .pqc-generated-state/campaigns/baseline/cases/<case>.yaml --duration-seconds 10 --restart
```

Monitor output is useful for diagnosis but has no result manifest and does not establish image provenance by itself.

## Automated hardware tests

Hardware tests under `tests/hardware/` are expected to be self-contained framework workflows. The normal user contract is a single `pytest-hardware` invocation; the test should resolve/materialise its own case, create its own ephemeral build/generated state, run the framework-owned build/sign/flash/runtime path, capture its own evidence, and assert the result. Do not document pre-generated campaigns, manual CMake/build/sign/flash steps, prior result directories, or test-specific evidence-path environment variables as prerequisites for a default hardware test.

For standalone application-timebase hardware validation, run:

```bash
./scripts/dev.sh pytest-hardware tests/hardware/test_application_timebase_hw.py -m hardware --pqc-require-hardware
```

The test retains its own resolved wolfBoot-enabled baseline case and setup/experiment logs under `results/automated-tests/`, enables `PQC_TIMEBASE_HARDWARE_SELF_TEST=ON` inside the isolated hardware-test build volume, executes the normal experiment runner so wolfBoot and the relocated application are built/signed/flashed together, reads the UART evidence created by that run, and verifies the requested delay, derived 1 MHz counter rate, unchanged HAL-tick behaviour, wolfBoot verification, and application startup. The flag is validation-only; because `pytest-hardware` overlays `/workspace/build` and `/workspace/.pqc-generated-state` with disposable Docker volumes, this self-test configuration does not become the normal host build configuration.

Capability prerequisites such as gateway SSH access, flash-helper access, the UART device, physical hardware, credentials, brokers, and instruments remain external laboratory capabilities and are enforced through pytest capability gates. They are not manual test preparation steps.


The secure-boot flash workflow hardware file independently resolves one canonical
baseline build case and one canonical secure-boot case for each selected algorithm.
Run it by itself with:

```bash
./scripts/dev.sh pytest-hardware tests/hardware/test_secure_boot_flash_workflow_hw.py -m hardware --pqc-require-hardware
```

The file's positive ECDSA P-256 case and its ECDSA P-256/SHA-256 integrity
negative-and-restoration cases run sequentially. Each retains command logs,
resolved non-secret configuration, run manifests, UART and flash evidence in its
own directory below `results/automated-tests/`. The test does not delete
reusable signing-tuple members or manually remove build outputs; the framework's
generated-state preflight controls compatibility. Negative-path validation and
restoration failures are retained separately, and a failed restoration must be
investigated before attempting another hardware experiment.

The default single-capture `flash-secure-boot` command requires successful
flashing, UART acquisition, and the secure-boot application, normal boot, and
tick markers. Missing markers fail with return code 9 at
`positive_uart_evidence`. Missing legacy aggregate timing alone does not fail
this flash/startup workflow; timing remains unavailable and the sample is not
valid for benchmark statistics. Typed integrity/authenticity diagnostics must
not be relabelled as legacy aggregate verification timing.

Explicit repeated benchmarking (`--repeat-count 5`, for example) additionally
requires valid timing samples on every capture. Missing timing still fails with
return code 9 at `benchmark_sample`; a successful startup does not make that
benchmark pass. `--skip-uart` proves flashing only.

The positive hardware test requires CLI exit 0, a successful finalized manifest,
and retained flash/capture evidence and UART markers independently demonstrating
both verified downloads, integrity/authenticity results of zero, and application
startup. Restoration tests also require CLI exit 0. These checks do not prove
benchmark sampling, MQTT reporting, or an end-to-end workload.


## Broker boundary

Broker deployment and host-side MQTT/TLS checks are separate from firmware flashing. Use `experiment/mqtt-broker/README.md`. Broker/client success is `host_side` or broker-side evidence only and cannot be promoted to STM32, UART, Wi-Fi, ST67W61M1, wolfSSL-on-STM32, wolfMQTT-on-STM32, or end-to-end wireless evidence.

## Diagnostic fallback

Host-native commands may be used only to isolate a development-machine, CubeMX, IDE, toolchain, SSH, or gateway problem. They must not replace wrapper verification, bypass generated-state preflight, or use destructive signing-state cleanup. Manual SCP/SSH flash and direct `picocom` capture are recovery diagnostics documented by the host/gateway and board setup guides.

## Evidence rules

- Container build output proves compilation/linkage only.
- Flash success requires workflow SCP/SSH/helper evidence.
- Direct-flash runtime success requires expected UART markers from a provenance-backed run.
- Positive secure-boot success requires explicit secure-boot/application markers and result status.
- Timing, cycle, stack, heap, and benchmark values must come from explicit UART fields or manifests.
- Gateway reachability, broker status, host-client validation, and hardware/UART evidence are separate boundaries.


## ST67 T02 and secure-boot runtime validation

Use a UART capture of at least 30 seconds when validating ST67 networking.
A successful normal or secure-boot application run must show module
initialization, the normal scan-skipped marker, Wi-Fi association, DHCP
success, a live `lwIP runtime network:` marker with a non-zero IPv4 address,
and continued heartbeat output.

For secure-boot profiles, these application markers are required in addition
to the profile-specific wolfBoot verification and handoff evidence. Run the
existing secure-boot flash workflow and algorithm benchmark tests for the
maintained profile matrix; do not treat build or signing success alone as
runtime networking evidence.

## Signing-state initialization and clean builds

Before the first secure-boot build for an algorithm, ensure the configured
persistent tuple directory is either completely absent or complete. The
matching `build-wolfboot` profile atomically creates a new tuple when absent.

Deleting `build/` or generated files inside `tools/wolfboot/` does not rotate
the signing identity. The next build rematerializes the required wolfBoot files
from `secrets/wolfboot/tuples/<tuple-id>/`. Do not manually delete individual
files inside a persistent tuple.

## Locating failed pytest hardware and gateway evidence

Hardware, gateway, and integration pytest failures retain their partial evidence
under `results/automated-tests/<test-run-id>/`. Inspect `manifest.json` for the
failure stage and `pytest.log` for the ordered collection, setup, call, and
teardown records. Test-triggered build evidence is below the same run's
`builds/` directory. These test-only builds are diagnostic evidence and are not
normal reusable firmware builds.


## End-to-end MQTT experiments through wolfBoot

For MQTT experiments, use the normal `run` command and select the secure-boot
domain separately:

```bash
./scripts/dev.sh experiment-gateway run \
    --experiment .pqc-generated-state/campaigns/<campaign>/cases/<case>.yaml \
    --boot-mode wolfboot \
    --boot-algorithm ecdsa_p256
```

This path owns all prerequisites. It provisions experiment dependencies and
signing state, builds wolfBoot, builds the MQTT application with the relocated
preset, signs that exact application, prepares the broker, flashes both images,
captures UART, validates MQTT command/response behaviour, collects broker logs,
and stops the broker. Standalone secure-boot commands remain diagnostic and
benchmark entry points; they are not prerequisites for `run`.

The `--boot-algorithm` option applies only to wolfBoot signing and verification.
TLS key exchange and certificate/signature selections remain in the MQTT
experiment profile.

## Network packet-capture artifacts

Every full firmware run whose experiment profile contains `network` enables gateway packet capture by default. The capture starts after the managed broker is ready and before the STM32 reset that begins UART and network execution. Cleanup stops only the `tcpdump` process created for the current run, copies the capture into the result directory, records its SHA-256 digest and byte count in `manifest.json`, and removes the temporary gateway files.

The retained files are:

- `gateway-network-capture.pcap` — packet data readable by Wireshark or `tcpdump -r`.
- `gateway-network-capture.log` — start, stop, copy, and `tcpdump` diagnostic evidence.

Example inspection:

```bash
wireshark "results/<run-id>/gateway-network-capture.pcap"
```

For repeatable offline analysis after the run is finalized, use:

```bash
./scripts/dev.sh python scripts/analyse_packet_capture.py results/<run-id>/manifest.json
```

This writes derived observations to `results/<run-id>/analysis/packet_capture/packet_analysis.json` and a separate hashed lineage record to `packet_analysis_lineage.json`. It does not modify the finalized manifest or raw capture. The maintained Docker image includes pinned `tshark`; when a TLS key log is retained, the normal analyser invocation uses it for TLS/MQTT decryption enrichment. Pass `--no-tshark` only when encrypted-protocol enrichment is intentionally disabled. If the key log is unavailable or decryption fails, the output records that state explicitly and preserves the encrypted packet observations. Structured STM32 MQTT reporting evidence is preferred for device-side correlation; UART remains diagnostic/secondary evidence. No cross-clock alignment is inferred unless an explicit mapping exists in retained evidence.

or inside the development container:

```bash
./scripts/dev.sh python -c "import subprocess; subprocess.run(['tcpdump', '-nn', '-r', 'results/<run-id>/gateway-network-capture.pcap'], check=True)"
```

Configure a known STM32/ST67 MAC address to avoid unrelated gateway traffic:

```yaml
network:
  packet_capture:
    enabled: true
    interface: any
    stm32_mac_address: "02:11:22:33:44:55"
```

Replace the example address with the actual device address. When the MAC is omitted, the framework captures all traffic visible on the selected interface so that DHCP and other pre-address traffic are not lost. The manifest records the effective interface and filter. A missing, empty, uncollectable, or unsuccessfully stopped capture fails an otherwise successful network experiment rather than creating unsupported evidence.


## Relocated secure-boot build defaults

wolfBoot-secured firmware keeps the signed application slot at offset `0x20000` and the application vector at logical `0x08023000`, after the 12 KiB image-header reserve. The selected update mechanism is build-affecting:

- `single_bank` retains the legacy primary/update/software-swap layout and compiles out hardware BFB2 swapping and application OTA handling.
- `dual_bank_no_ota` uses two symmetric 1 MiB physical banks, each with a 128 KiB wolfBoot/metadata reservation followed by an 896 KiB signed application slot; BFB2 bank switching is available, while application OTA handling is compiled out.
- `dual_bank_ota` uses the same symmetric dual-bank layout and enables reporting-plane OTA staging, activation, confirmation, and rollback.

Release is the default build mode and `--debug` selects Debug compiler configuration without changing the selected firmware mode's addresses. The default wolfBoot algorithm is `integrity_sha256`, which verifies the image SHA-256 digest but performs no signature or signing-key authentication. It therefore does not require or resolve a signing tuple. Signing profiles remain explicit non-default selections.


### MQTT TLS packet decryption

TLS-enabled MQTT runs collect `mqtt-broker-tls-keylog.log` before the managed broker is stopped. It is stored beside `gateway-network-capture.pcap` and described under `mqtt_broker.tls_keylog` in `manifest.json`. A TLS run does not pass broker evidence collection when the key log is missing or empty. Plaintext runs do not require this artifact.

### Optional bootloader verification stack profiling (Request 4)

Normal secure-boot campaigns leave `boot_stack_profiling: false` and retain
existing DWT, reset-origin and MQTT evidence without watermarking. The dedicated
`configs/campaigns/secure_boot_stack.yaml` enables profiling. To resolve it:

```bash
cd /home/timk/rmit/PQC-Framework-02
./scripts/dev.sh python scripts/resolve_campaign.py secure_boot_stack.yaml
```

Use the resulting case files with the normal `experiment build` /
`experiment-gateway run` workflow, or execute the campaign with the maintained
campaign command documented in `README.md`. The profile-appropriate bootloader
is built with stack instrumentation and paired with the matching relocated
application (mailbox v8). Read the `PQC_SECURE_BOOT_STACK` structured evidence
from the retained raw MQTT stream; `measurement_status=measured` plus a positive
high-water value and successful selected-image verification is required. If
unavailable, inspect `unavailable_reason` (`watermark_untouched`,
`region_exhausted`, `scan_interference`, or `initialization_unavailable`)
and retain that status rather than substituting the reserved RAM size.
Do not compare timings from these runs with normal boot or application timing
campaigns. The watermark can change reset-to-application delay; ordinary
secure-boot image validation, bank switching and OTA logic remain unchanged.
To analyse finalized profiling runs without changing their manifests, pass the
actual retained run-manifest paths to the offline parser:

```bash
./scripts/dev.sh python scripts/analyse_secure_boot_stack.py \
  results/<run-one>/manifest.json results/<run-two>/manifest.json \
  --output-dir results/analysis/secure_boot_stack
```

Replace the example run-directory names with the real paths. The parser rejects
incomplete streams, mismatched run IDs, unavailable evidence presented as a
numeric result, and profiling records without a matching mailbox version.
Its output records input SHA-256 hashes and remains separate from run capture.
Run the targeted boot/handoff and OTA smoke regressions before hardware claims.


## Optional wolfBoot early-boot UART diagnostics

Request 17 adds a diagnostic-only wolfBoot UART mode. It is **off by default**.
The standard secure-boot measurement configuration therefore continues to boot
without bootloader UART formatting or transmission. A diagnostic build is selected
with `boot_uart_diagnostics: true` in a resolved case, or for an isolated build with:

```bash
./scripts/dev.sh experiment build-wolfboot --boot-algorithm integrity_sha256 --boot-uart-diagnostics
```

The diagnostic target uses the board's existing gateway console route: LPUART1 at
115200 baud on PG7 (TX) and PG8 (RX), AF8, sourced from the wolfBoot 80 MHz PCLK1.
Bootloader lines use the stable `PQC_WOLFBOOT_DIAG` prefix so they are distinct from
application startup markers. Diagnostic records cover image selection, verification
start/completion and result codes, refusal/recovery decisions, representative dual-bank
selection/swap decisions, and final handoff. They contain no private key, credential,
secret material, or complete sensitive buffer contents.

Diagnostic UART is blocking and intentionally perturbs bootloader-entry-to-handoff and
reset-to-application elapsed time. **Diagnostic-enabled runs are not eligible for timing
comparisons.** The DWT integrity/authenticity wrappers remain unchanged: diagnostic
formatting/transmission occurs only before a verify call begins or after it returns.
Restore the standard measurement configuration by resolving/running with
`boot_uart_diagnostics: false` (the default) and rebuilding wolfBoot.

Verification-stage negative tests use deterministic result-local mutations. The legacy
`flip_first_byte`/`header_byte_flip` case remains available as a malformed-header control.
For Request 17 diagnostic evidence, prefer `payload_byte_flip` to preserve the wolfBoot
header and force a failed integrity check, and `signature_byte_flip` on signed profiles to
preserve payload integrity and force a failed authenticity check. Select the method with
`--negative-corruption-method` together with `--negative-corrupt-application`. The result
evidence records the mutation class, exact byte offset, original/modified byte values,
derived signed-image header size, payload size, and original/corrupted SHA-256 identities.

When boot timing instrumentation is present, diagnostic `verification_complete` records also
report the integrity/authenticity cycle count already captured by the Request 14 DWT wrapper.
The UART read occurs only after that wrapper has taken its end snapshot, so these diagnostic
prints do not alter the established measured interval. Failed-verification timings are
reported as failure-path diagnostic evidence and remain excluded from normal timing
comparisons because diagnostic builds are `timing_comparison_eligible=0`.

For a rejected application, `uart.log` may contain only `PQC_WOLFBOOT_DIAG` records; no
application MQTT result is expected because control is never handed to the application.
The file-owned hardware workflow retains the raw UART plus flash/reset evidence. In the
default diagnostics-off build, an empty UART capture remains negative-path evidence only
when paired with successful flash/reset evidence and a subsequent known-good restoration;
it does not identify wolfBoot's internal rejection reason.


## Ready Metrics 2 reliability trials

`scripts/ready_metrics_2_reliability_v2.py` is a standard-library host orchestrator.
Run it as your normal Linux user from the repository root; it needs normal-user
Docker access and uses `sudo` only for directory cleanup. It prints a plan by
default. Leave any older executing script in place; start version 2 with
`--execute` only after the current run has finished and its results have been saved. `--execute` explicitly authorizes the destructive setup:

```bash
python3 scripts/ready_metrics_2_reliability_v2.py --runs 10 --dry-run
python3 scripts/ready_metrics_2_reliability_v2.py --runs 100 --execute
```

Execution empties **all content, including hidden files and keys**, from
`.pqc-generated-state/`, `build/`, `results/`, and `secrets/`, retaining the four
directories. This is an intentional complete reset of disposable laboratory
state, not routine signing-tuple cleanup. Existing results and signing identities
will be lost. It then removes all containers (including running containers),
images, named and anonymous volumes, unused custom networks, and default-builder
cache on the selected local Docker daemon, including other projects. Built-in
networks, other Docker contexts/builders, remote gateway Docker, and host Docker
configuration are not erased. Symlink/mount cleanup roots and non-local Docker
endpoints are refused. Use a dedicated, idle lab checkout and Docker daemon.

The script calls `./scripts/dev.sh build-image`, then calls
`python3 scripts/provision_certificates.py` on the host because that provisioner
owns a pinned Docker runtime itself; the framework image does not expose a nested
Docker daemon. All configured certificate profiles are provisioned. SSH/VPN
credentials and local Wi-Fi inputs must already exist outside the deleted folders.
The current campaign selects `integrity_sha256`, which requires no signing key;
framework-owned signing workflows handle key prerequisites for other selections.
No private material is printed or included in the summary.

Version 2 restores the full setup sequence. It checks that
`configs/campaigns/ready_metrics_2.yaml` exists, but passes only the filename
`ready_metrics_2.yaml` to `./scripts/dev.sh python scripts/resolve_campaign.py`
because the resolver supplies the campaign directory. It then chooses the lexically first generated case. The current empty matrix resolves
to one case. For each requested trial it invokes a fresh
`./scripts/dev.sh experiment-gateway run --experiment <case> --results-dir <batch>/runs`.
It does not use the campaign executor, `execution.repetitions`, `--runtime-only`,
or preparation reuse. Each full invocation owns build/sign/flash, broker lifecycle,
reset and evidence collection; the framework may reuse compatible build artifacts.
The Docker image and provisioned keys persist between trials. No short gateway-lock
timeout is added. Setup failure stops the batch; trial failure is recorded and the
next independent invocation proceeds. Ctrl-C stops further trials.

Results are under `results/reliability/<UTC-time>-<unique-id>/runs/<run-id>/`.
A shared results parent lets the framework allocate distinct sequential run IDs;
only the new manifest from each invocation is inspected, never a previous result.
`summary.json` is updated after every trial, with the repository commit, selected
case, command, process exit, manifest path, UART paths and classification. Current
schema success requires exit code zero, manifest run return code zero, no failure
stage, explicit completed execution, accepted capture, and a finalized index.
Legacy manifests require run return code zero and an explicit supported run-pass
verdict. Unknown schemas fail closed. This measures framework execution/capture
reliability; it does not independently certify every scientific metric.

UART matching is case-sensitive, whole-word `ERROR`; `error`, `ERRORS` and
`NO_ERROR` do not match. Success and UART ERROR are separate statistics. Both
headline percentages divide by **attempted runs**, including failed launches.
Missing, empty or unreadable UART captures are unknown, never verified clean.
The summary also reports the ERROR percentage among trials with known UART status.
With unknown captures, the headline ERROR rate is only the observed lower bound.
Exit codes: 0 = all attempted runs succeeded; 1 = at least one failed trial;
2 = invalid arguments/setup failure; 130 = interrupted. No trials means no rate.

The script uses existing CLI entry points, but compatibility with earlier commits
is not guaranteed: provisioning, CLI and manifest contracts must still match.
Unit tests and subprocess tests with disposable command shims validate orchestration;
those simulated results do not establish Docker purge/rebuild or hardware success.

## Network impairment trial and A5 notebook

`configs/campaigns/network_trial.yaml` runs five fixed-TLS conditions with three
hardware-reset repetitions each: **15 planned runtime attempts**. It uses
Ready Metrics 2 (200 KiB, 400-byte chunks), `SecP256r1MLKEM768`, ECDSA-P256 server
authentication, integrity-only secure boot and single-bank firmware. Energy is
not selected. The existing reporting path remains impairment-exempt.

| Profile | Rate (kbit/s) | Configured RTT (ms) | Loss (% independently per direction) | MTU (bytes) |
|---|---:|---:|---:|---:|
| `trial_reference` | 100000 | 0 | 0 | 1500 |
| `validation_rate` | 256 | 0 | 0 | 1500 |
| `validation_rtt` | 100000 | 100 | 0 | 1500 |
| `validation_loss` | 100000 | 0 | 1 | 1500 |
| `validation_mtu` | 100000 | 0 | 0 | 1200 |

All five profiles enable netem; the reference is an enabled, configured reference,
not a claim of 100 Mbit/s achieved throughput or zero physical RTT. Each treatment
changes only one property. Existing validation profiles are reused unchanged.
The executor retains each condition across repetitions and cleans up through its
normal workflow. Runs are grouped, not randomised; three repetitions are a pilot,
not evidence of statistical independence. No gateway or hardware run is implied
by offline resolution/tests.

Resolve first; expect five cases, one firmware identity and three repetitions:

```bash
./scripts/dev.sh python scripts/resolve_campaign.py network_trial
```

When the gateway/STM32 and brokers are available, run the trial:

```bash
./scripts/dev.sh campaign-gateway network_trial
```

This performs the framework-owned preparation, flashing and runtime measurements.
Let an occupied gateway lock wait. Failed runs remain evidence; do not treat
15 planned attempts as 15 successful captures. The configured rate limit may
extend runtime, and loss/MTU conditions may fail. Resume an interrupted campaign
with its exact manifest via `campaign-gateway --resume`, as described below for
the TLS matrix. This trial has not yet been hardware validated; see DTR-A5-TRIAL.

Use the exact resulting campaign directory (replace `<timestamp>`), then export
and verify an A1 dataset. Use fresh output directories on subsequent trials:

```bash
./scripts/dev.sh python scripts/export_timing_dataset.py \
  --results-root "results/campaigns/network_trial_<timestamp>" \
  --output results/analysis/network_trial_dataset_01
./scripts/dev.sh python scripts/export_timing_dataset.py \
  --check results/analysis/network_trial_dataset_01 --verify-source-inputs
./scripts/dev.sh python scripts/prepare_network_selection.py \
  --dataset results/analysis/network_trial_dataset_01 \
  --output results/analysis/network_trial_selection_01
for axis in rate rtt loss mtu; do
  ./scripts/dev.sh python scripts/summarise_timing_dataset.py \
    --dataset results/analysis/network_trial_dataset_01 \
    --spec "notebooks/network_trial_${axis}.json" \
    --network-spec results/analysis/network_trial_selection_01/network-selection.json \
    --output "results/analysis/network_trial_${axis}_01" --execute-notebook
done
```

The helper verifies retained broker logs, PCAPs and resolved snapshots. It matches
the exact configured STM32 MQTT client ID to a broker-observed address/port and
intersects that with the retained workload-broker flow. It refuses ambiguous
addresses or extra client ports without identity evidence. It never reads key-log
contents or exports payloads. Review `selection-status.json`: missing broker
identity (including failed TLS handshakes), missing captures, and NAT mismatches
remain unselected. You may supply an explicit A5 selection using other retained
identity evidence; do not guess by broker port alone. A broker match is not clock
synchronisation or an independent-run declaration.

Each output contains `executed.ipynb`, condition/transport plots, packet diagnostics,
completeness and comparison tables. The presets compare one axis against the
reference and leave `independent_runs: false`, exclusions empty and unknown-control
waivers empty. A2 still refuses matched deltas when source revision, QoS or other
required controls are unknown; absolute flow/timing tables and completion coverage
remain useful for evaluating the notebook. Inspect refusal reasons instead of
waiving unknown controls. If a whole condition was blocked before capture, its
profile may be absent from the dataset: retain that campaign failure and create an
explicit reduced analysis selection rather than inventing runs. No usable raw
runs means there is no analysis dataset to export.

## TLS matrix with energy and notebook analysis

`configs/campaigns/tls_matrix_energy.yaml` is a 12-condition TLS 1.3 exercise:

| Dimension | Values |
|---|---|
| Key exchange | `secp256r1`, `SecP256r1MLKEM768`, `ML_KEM_768` |
| Certificate authentication | `ecdsa-p256`, `mldsa65` |
| Authentication mode | `server`, `mutual` |

Each condition requests ten framework runs with a hardware reset between runs:
120 planned runtime attempts, plus framework-owned preparation. The existing
executor groups by firmware and runs repetitions consecutively; this is not a
randomised/block-balanced design and reset separation alone does not prove
statistical independence. Account for temporal drift before inferential use.

All cases use `ready_metrics_2`, the profile's 200 KiB transfer with 400-byte
chunks, baseline network conditions, `integrity_sha256` secure boot, single-bank
firmware, minimal UART and disabled boot stack/UART diagnostics. These fixed
controls allow all eight A1 timing metrics to be collected when the required
boundaries and evidence are valid. No successful values are promised by a
configuration alone. The selection spans KEX and authentication families; a
classical KEX with ML-DSA certificates is not an all-classical TLS configuration.

The persistent `esp32_ina228` instrument is selected in every case. Energy stream
capture is required by the resolved runtime contract; the instrument must already
be powered, provisioned and connected as documented in the instrument guide.
This campaign does not reflash or command the ESP32. Every run keeps its own raw
capture and integrity record; A2 does not yet derive energy in joules (A6), TLS
primitive attribution (A4), or boot-verification summaries (A7).

Resolve and inspect the matrix without building firmware or accessing the gateway:

```bash
./scripts/dev.sh python scripts/resolve_campaign.py tls_matrix_energy
```

Expected: `.pqc-generated-state/campaigns/tls_matrix_energy/` contains
`campaign-resolved.yaml` with `case_count: 12`, and twelve case YAML files, each
with `repetitions: 10`, `reset_between_runs: hardware_reset`, and the energy
instrument selected. The configuration has offline test coverage; first full
hardware validation is tracked by DTR-TLS-MATRIX-ENERGY.

When ready to run the hardware experiment:

```bash
./scripts/dev.sh campaign-gateway tls_matrix_energy
```

This command performs preparation/build/signing/flash and the requested runtime
repetitions through the framework. Failed runtime repetitions are recorded and
execution continues with the remaining repetitions and conditions. After all
attempts, `completed_with_failures` and exit code 1 distinguish a finished matrix
with failures from all-success (`completed`, exit code 0). Preparation and broker
setup failures mark the affected firmware group's remaining repetitions `blocked`
(no runtime measurement), clean up, and continue to the next firmware group.
The summary separates completed, failed and blocked repetitions. Condition
verification and cleanup errors still stop execution; 120 is the planned count, not proof of 120
completed captures. The two selected certificate profiles and compatible brokers
are handled by the maintained preparation/orchestration path. Existing Wi-Fi,
gateway and instrument prerequisites apply. Do not run a second campaign against
the same laboratory resources. Let an occupied gateway lock wait; Ctrl-C cancels.
Use the exact resulting campaign directory in subsequent commands. Resume an
interrupted campaign using its recorded manifest, without changing the source.
Resume skips validated successes and retries failed or missing repetitions; prior
run evidence and retry logs remain available. Before any pending repetitions in
an existing firmware group, resume runs normal preparation/build/sign/flash again,
restoring both wolfBoot and the signed application. A preparation or flash failure
blocks that group's measurements; after successful cleanup the next group is tried. Fully validated completed groups perform no
hardware work. This restores firmware rather than reading back its identity;
preparation may rebuild/re-sign, and changed firmware hashes invalidate old
successes in that group so they are measured again:


```bash
./scripts/dev.sh campaign-gateway --resume "results/campaigns/tls_matrix_energy_<timestamp>/campaign-manifest.json"
```

Export the selected recorded campaign (replace `<timestamp>` with its actual
identifier; do not select a scientific baseline by directory name):

```bash
./scripts/dev.sh python scripts/export_timing_dataset.py \
    --results-root "results/campaigns/tls_matrix_energy_<timestamp>" \
    --output results/analysis/tls_matrix_energy_dataset_01
./scripts/dev.sh python scripts/export_timing_dataset.py \
    --check results/analysis/tls_matrix_energy_dataset_01 --verify-source-inputs
./scripts/dev.sh python scripts/summarise_timing_dataset.py \
    --dataset results/analysis/tls_matrix_energy_dataset_01 \
    --spec notebooks/tls_matrix_energy.example.json \
    --output results/analysis/tls_matrix_energy_summary_01 --execute-notebook \
    --notebook notebooks/tls_matrix_energy.ipynb
```

The companion analysis preset names each of the twelve combinations explicitly,
using `secp256r1__ecdsa-p256__server` as the reference. It retains failures, makes no
exclusions or unknown-control waivers, and leaves `independent_runs: false`.
The declared treatment includes only the selected TLS KEX, certificate and
authentication-mode properties and their profile identities. Absolute per-condition
distributions, percentiles and completeness are useful immediately. Differences
between combinations changing multiple factors are combined-configuration deltas,
not isolated KEX/authentication effects.

A2 deliberately requires the same recorded evidence class for matched differences;
it therefore refuses cross-classical/hybrid/pure-PQC matches. Unknown controls
(such as missing source revision or an unrecorded MQTT setting) also refuse
matching. This campaign does not repair old provenance or change the matching
rules. Inspect `differences.csv` reasons instead of relabelling classes, inferring
missing controls or setting `not_applicable` merely to obtain a number. A future
justified comparison policy or provenance correction may be needed for those
matches. This does not block absolute timing summaries or energy capture.

For interactive work, launch `./scripts/dev.sh notebook` and open
`notebooks/tls_matrix_energy.ipynb`. It has its own configuration and preserves any
existing secure-boot notebook customisation. In its configuration cell use
`ROOT = Path("/workspace")` inside the Docker server, and set:

```python
DATASET = ROOT / "results/analysis/tls_matrix_energy_dataset_01"
SPEC_FILE = ROOT / "notebooks/tls_matrix_energy.example.json"
OUTPUT = ROOT / "results/analysis/tls_matrix_energy_interactive_01"
SPEC = json.loads(SPEC_FILE.read_text())
```

For PDF export, save the executed notebook, then use JupyterLab's File → Save
and Export Notebook As → PDF. The development image includes snapshot-pinned
Pandoc and TeX Live/XeLaTeX dependencies; no Jupyter plugin is needed. After an
image update, save your notebook, stop the existing server with Ctrl-C, rebuild
with `./scripts/dev.sh build-image`, and start `./scripts/dev.sh notebook` again.
Restarting only the kernel keeps the old container and will not load new tools.
A terminal export of saved outputs (without re-executing cells) is also available:

```bash
./scripts/dev.sh run python -m jupyter nbconvert --to pdf \
    notebooks/tls_matrix_energy.ipynb \
    --output-dir results/analysis/tls_matrix_energy_pdf
```

The normal configuration cell imports `json` and `Path` and adds `ROOT / "scripts"`
to `sys.path`. Use a new output path on every run. For clearer plots or a bounded
within-family question, filter to one KEX (for example add
`"tls_kex": "ML_KEM_768"` to `SPEC["filters"]`) and set
`SPEC["baseline"] = "ML_KEM_768__ecdsa-p256__server"`. Conditions outside that filter
remain in inventory with exclusion reasons; their comparison rows are unsupported.
Keep the chosen baseline within the filter. The four retained conditions then
show certificate and mutual-auth differences within that KEX family, subject to
all the same control checks.

Offline verification:

```bash
./scripts/dev.sh pytest tests/unit/test_tls_matrix_energy_campaign.py
./scripts/dev.sh pytest tests/integration/test_tls_matrix_energy_campaign_in.py -m integration
```

The integration tests use real resolver/CLI processes, broker command dry-runs
and explicitly synthetic timing records through A1 and the clean-kernel notebook.
They do not establish hardware TLS compatibility or live energy acceptance.


## Thesis pilot campaigns and frozen reports

The A8 suite extends existing profiles without changing firmware measurement
boundaries. `configs/analysis/thesis_campaigns.json` is the machine-readable
inventory. All new campaigns use ten reset-separated pilot attempts per condition,
uninstrumented normal boot timing, and the established gateway/capture lifecycle.
Choose final repetition counts from pilot variability before final collection.
These profile definitions do not establish hardware success.

| Campaign | Conditions | Varied dimensions and controls |
|---|---:|---|
| `thesis_kex` | 10 | KEX; ECDSA-P256/server auth and baseline network fixed |
| `thesis_authentication` | 8 | Four certificate families × server/mutual; P-256 KEX fixed; analyse each factor within the other factor's fixed stratum |
| `thesis_repeated_tls` | 8 | Classical/hybrid × ECDSA/ML-DSA × auth mode; ten fresh full handshakes per boot, ten outer attempts |
| `thesis_application` | 8 | Classical/hybrid × 4 KiB/200 KiB payload × 128/400-byte chunks; analyse payload and chunk effects separately |
| `thesis_network_rate` | 6 | Classical/hybrid × 100000/1024/256 kbit/s; other network variables fixed |
| `thesis_network_rtt` | 6 | Classical/hybrid × 0/20/100 ms configured RTT; other network variables fixed |
| `thesis_network_loss` | 6 | Classical/hybrid × 0/1/3 percent configured loss; other variables fixed |
| `thesis_network_mtu` | 6 | Classical/hybrid × 1500/1280/1000-byte MTU; other variables fixed |
| `thesis_energy` | 4 | Representative classical/hybrid and ECDSA/ML-DSA server-auth configurations with the existing instrument |
| `thesis_ota_overhead` | 4 | ECDSA-P256/ML-DSA65 × dual-bank OTA disabled/enabled, holding bank layout fixed |

All network sweeps use `trial_reference`, which keeps impairment enabled at the
reference. Analyse each TLS profile separately for one-factor network responses;
then compare responses between the profiles. The configured values are pilot
choices, not measured applied conditions. A5 still requires observed impairment
and an explicitly attributed device TCP flow.

Use the existing `secure_boot` campaign for normal authentication timings,
`secure_boot_stack` for separate stack profiling, and `baremetal_benchmark` for
the supporting primitive reference. `thesis_ota_overhead` measures capability
cost during normal boot, not an OTA transition. Actual application update,
rollback and bootloader migration use the existing self-contained dual-bank OTA
hardware tests and their retained evidence. Multi-boot OTA energy remains
unsupported. An application-bracketed energy interval is not bootloader energy.

Resolve a pilot without hardware access:

```bash
./scripts/dev.sh python scripts/resolve_campaign.py thesis_kex
```

After selecting the required pilot and provisioning its laboratory prerequisites,
execute through the maintained gateway wrapper:

```bash
./scripts/dev.sh campaign-gateway thesis_kex
```

Substitute a campaign from the table for other families; do not launch the whole
suite as a generic smoke test. Retain failed attempts. Use recorded evidence to
choose sample counts and verify broker/target interoperability per configuration.

Export an explicitly selected completed campaign into a new A1 dataset, set the
A8 JSON's dataset path, named conditions, baseline and fixed controls, then build:

```bash
./scripts/dev.sh python scripts/export_timing_dataset.py --results-root results/campaigns/SELECTED_CAMPAIGN/runs --output results/analysis/SELECTED_DATASET
./scripts/dev.sh python scripts/build_research_report.py --spec configs/analysis/thesis_report.example.json --output results/analysis/NEW_THESIS_SNAPSHOT
./scripts/dev.sh python scripts/build_research_report.py --verify results/analysis/NEW_THESIS_SNAPSHOT
```

See [the A8 architecture contract](007_framework_architecture.md#frozen-research-reports-analysis-request-a8)
for the selection schema, offline rebuild command, metric boundaries, LaTeX
fragments, clean-kernel HTML and incomplete Chapter 5/RQ coverage. Opening
`report/notebook.html` does not run a measurement or edit the thesis.


## Terminal campaign queue

Run `python3 scripts/run_queue.py` from the Linux host at the repository root.
The full-screen interface uses the Python standard library (`curses` and SQLite);
its resolver, execution and analysis operations use the maintained Docker image
through `scripts/dev.sh`. It must not be launched inside `dev.sh python`.
A terminal of at least 120 columns by 28 rows is required (one additional row
per additional gateway). No new Python package
or image rebuild is needed when the existing development image is current.

The title shows the current framework's short Git SHA, commit date and today's
local date. `*` after a SHA means the checkout was dirty (including submodules).
Queue and Completed rows show the source identity frozen in that entry's plan;
the **VERSION / DATE** column adds that commit's date to the right of its SHA.
New plans retain the date; older plans look it up from local Git history, showing
`unknown` if unavailable. Rows do not change version when the checkout changes. Unknown
provenance is labelled `unknown`. These display labels do not replace full source
verification. The selected entry's last eight dispatch-log lines appear between
horizontal rules; short logs leave the remaining lines blank.

Below the queue summary, each configured gateway has an advisory status refreshed
in the background every five seconds: **READY** (lock free), **IN USE - hostname**
(lock held), **CONNECTION ERROR** (SSH/authentication/status query failed), or
**OFFLINE** (SSH transport unreachable and no ICMP reply). A firewall dropping both
SSH and ICMP can look offline; this is a reachability indication, not proof of
power state. Checks use `./scripts/dev.sh gateway-lock status-all` and never release
an occupied lease. The execution wrapper still checks/acquires the actual lock.

All tabs use **PROFILE NAME**, **TEMPLATE**, **REPS**, **CASES**, and **TOTAL RUNS**.
REPS is the configured repetition count **per case**, CASES is the expanded
matrix size, and TOTAL RUNS is their product. Queue and Completed entries occupy
two lines; the second shows the full job ID, VERSION / DATE,
**RUNS OK/ERROR/TOTAL**, **REPEATS**, local finish date/time and **EXPORTED** status.
For example, 8 cases with 10 reps have 80 total runs; `5/1/80` means 5 successful
runs and 1 error out of the 80 planned runs. Errors include failed and blocked
slots; accepting an error does not increment successes. REPEATS counts retained
previous attempts, not repetitions per case or worker restarts. Export status
applies to the current completed manifest version; retrying results requires a
new export. Existing exports remain recorded. Counts refresh once a second from
the campaign manifest; unreadable evidence shows `?` rather than zero progress.

The three tabs are **Profiles**, **Queue**, and **Completed**. `Tab` or `1`/`2`/`3`
switches tabs and clears all profile selections, export marks and row highlights.
Use arrow keys to choose a row again before issuing an item command. Switching
tabs does not cancel an already-started operation. Completed rows show the full
job ID, including removed/retained entries, for the permanent-deletion prompt.

**Tracked templates and local profiles:** `configs/campaigns/` remains the tracked
campaign-template collection, also available to existing resolver/collector CLI
workflows. The queue's Profiles tab reads only **`results/profiles/`**, shared by
queues in this checkout even when `--directory` selects a different queue. It
starts empty; templates are not automatically copied or migrated. Existing queued
jobs and retained evidence remain available independently of this list.

On Profiles, **`n` creates a profile**: choose **Blank** or **Use a template**. For
a template, select one from `configs/campaigns/`; then enter your own profile
name (letters, numbers, `_` or `-`). Blank starts with the minimum one-case
execution scaffold and component defaults, without inheriting a template's
matrix or analysis settings. The editor opens to customise the draft. `S` saves
after validation, defaulting to `<name>.yaml` under `results/profiles/`. Template
names and the SHA-256 of the selected template are retained in profile metadata;
Blank profiles show `Blank` in the TEMPLATE column. Saving never rewrites the
template. Older queued jobs without template metadata show `Legacy`.

**`v` views**, **`e` edits**, and **`D` deletes a profile**. The menu has Profile,
Components, Factors/matrix, Workload parameters, Execution and Analysis sections.
Arrow keys navigate, Enter opens a section/field, and Space toggles choices.
Select multiple factor values to build a matrix, one for a fixed value, or
default/omit to remove that override. Integer parameters accept comma-separated
values. Component choices come from existing validated profiles; the editor
never writes target, gateway, workload, crypto, broker, network-condition or
instrument component files. Profile names/IDs must be unique within the local
profile collection; they may match a template name.

Within the menu, `P` previews YAML, `V` validates all expanded cases and displays
case/run counts, and `S` validates then saves. `e` switches a read-only view to
editing. Esc returns or discards an unsaved draft after confirmation; main queue
`q`/`d` controls apply after returning from the editor. Execution policy and
component compatibility are enforced by the normal resolver. An invalid draft
stays open with the validation error. Up to 10000 expanded cases and 1000
repetitions are accepted. Unedited YAML sections are preserved verbatim; edited
sections are re-serialized, so their layout/inline comments may change. File
changes since opening the editor are rejected, preventing stale saves/deletions.
Deletion requires typing the profile filename and leaves frozen queue copies,
templates and results intact. Profile creation, editing and deletion are ignored
by Git and do not change the checkout's source identity or dirty marker.

Space selects multiple profiles, `/` filters names, `R` reloads the catalogue,
and **`a` enqueues** selected profiles (or the highlighted profile). Enter a
repetition override between 1 and 1000, or leave it blank to retain each profile's
`execution.repetitions`. Invalid profiles remain visible with their resolver
error and cannot be enqueued. Each entry retains the exact enqueued profile bytes
as `profiles/input.yaml` and its effective configuration as `profiles/campaign.yaml`.
Both SHA-256 hashes are sealed into the plan and checked before execution/resume;
changing either frozen copy is rejected. The effective copy includes any
repetition override and, as with the thesis collector, enables the existing
ESP32/INA228 instrument for supported deferred-reporting workloads. Its
provisioning, calibration and wiring remain external prerequisites.

Editing or deleting a local profile after enqueueing affects **future jobs only**;
existing jobs continue using their immutable copies. New jobs record the updated
profile hash, original path and template provenance. Source/submodule identity
is still verified separately; changing framework code or tracked templates still
participates in the normal source-verification rules.

`N` on Queue or Completed creates a fresh entry from the selected entry's retained
campaign definition, with its repetition count or a new override, using the
**current checkout and current component profiles**. This is the recovery path
when source verification prevents resume. The original frozen plan/profile hashes
must still match; its historical evidence is untouched. The fresh entry starts
all repetitions again, gets a new ID/version/date, records its parent entry, and
is appended normally (eligible immediately when dispatch is running). It also
works if the local profile has since been edited or deleted. Active entries must
pause first; unregistered retained folders are not re-queued by this control.

On Queue, `K`/`J` moves waiting entries up/down; `p` pauses the highlighted entry.
`r` resumes incomplete work with no unresolved failures, `t` retries recorded
failures plus remaining work, and `f` accepts existing failed/blocked outcomes
and continues remaining work. Acceptance never turns a failed measurement into
a success. Runtime failures pause at the first failed attempt; preparation errors
record a blocked slot, retaining the remaining slots as incomplete. Earlier
attempts stay in the campaign history, logs and archive, including attempts that
never produced a capture. Verified successful captures are reused on resume.
Previously accepted failures can be explicitly retried from Completed after
unmarking the entry.

For loss sweeps, the editor's **Execution → Energy monitoring** can be `off`
(`execution.energy_monitoring: 'off'` in YAML). The default `auto` retains the
collector's existing instrumentation policy; clearing the instrument selector
alone does not disable automatic instrumentation.

**Execution → Valid workload failures** selects `pause` (default) or `record`.
`execution.workload_failures: record` uses a fixed number of trials per case.
For Ready Metrics 2, a reported network timeout, network connection failure or
measured failed TLS handshake counts as a failed trial and continues, provided
its reporting stream, capture, enabled instruments, broker evidence and cleanup
are intact. Before the device requests a transfer, known host-observer network
errors on the impaired path are expected; after a request, successful host
operation is required. Missing tools and unknown observer errors still pause. TLS setup errors without a measured handshake, missing/corrupt
reports and infrastructure faults still pause. The firmware emits
`PQC_WORKLOAD_OUTCOME` through the independent plaintext reporting broker;
`trial-outcome.json` retains the classifier checks and is hashed in the capture.
Campaign slots remain `failed`, with `accepted_failure.decision` set to
`policy_record_valid_failure`; they are never relabelled successful. The CSV
retains failed rows, the acceptance decision and
`recorded__PQC_WORKLOAD_OUTCOME__return_code`. Unmeasured timings stay null.
A missing/null build reference leaves unverifiable static resource metrics
unavailable; it does not prevent exporting the recorded trial outcome.

Use the requested repetition count as the denominator, including valid failures.
Report the success/failure fraction separately from timings among successes;
at 100% failure, successful-transfer timing is unavailable. Do not retry until
N successes: that conditions the sample on success and can run indefinitely.
Use explicit retry only after investigating an invalid capture/infrastructure
fault; retain all previous attempts, and decide a retry limit before collection.

Profile edits affect newly enqueued entries only. Enqueue the edited profile
with `a` to use its new policy. `N` re-queues the old frozen definition, including
its original energy settings. Existing captures without the outcome marker are
not automatically reclassified; manual acceptance remains available.

**Delete** removes a waiting Queue entry from scheduling while preserving its job folder.
Pause an active entry and wait for cleanup before removing it. Removed entries
appear on Completed as `removed`; directories beneath this queue's `jobs/` with
no database record appear as `retained`, including partial folders. Discovery does
not schedule work or claim the evidence completed successfully. Removed/retained
incomplete entries cannot be marked for export or resumed automatically.

On Completed, `D` permanently deletes the highlighted entry's job folder and its
database record after you type its exact entry ID. This includes copied profiles,
logs, captures and job-local materials. Active runs, selected/in-progress exports
and unresolved cleanup halts are protected. Stop the queue worker before deleting
an unregistered retained folder. Combined CSV/notebook exports remain independent
and are retained; source-verification of such exports can no longer read a deleted
job's original files. Other jobs and shared framework state are preserved. Removal
and purge are recorded in the queue event history. Discovery is limited to the
selected queue directory, not arbitrary campaign result folders elsewhere.

`s` starts the queue worker. Only one entry runs at a time, in queue order;
paused/attention entries are skipped. Entries added while dispatch is running
are appended and are eligible automatically. `x` stops dispatch and requests a
cooperative pause of the active entry. `d` detaches the UI; it does not terminate
the worker. **`q` pauses and quits**: it requests a safe pause, keeps the waiting
status visible while the active operation and cleanup finish, then waits for the
worker to exit before closing the UI. Background planning/export operations also
finish before the UI process exits. No resident queue worker remains after a
successful `q`; queued work stays on disk for the next `s`. The CLI equivalent is
`python3 scripts/run_queue.py quit`. An active entry with a missing worker is
reported as unverified cleanup rather than silently treated as a clean shutdown.
Reopen the interface to reattach. Queues do not start at particular
wall-clock times. `--directory results/<name>` selects another persistent queue;
the normal gateway lease still serializes hardware across workers/checkouts.

A pause finishes the current framework operation and then performs condition and
broker cleanup. Breakpoints occur after preparation, broker setup and runtime
repetitions; no build/sign/flash/runtime command is killed to pause it. Preparation
may contain several related commands and completes as a unit. Resume restores
expected firmware through the existing validated preparation path because another
entry may have used the board. Queue mode validates each retained successful slot
against its original preparation and firmware SHA, so a rebuilt image does not
cause successful measurements to be repeated. New captures retain the new image
SHA; exports never relabel older images as byte-identical. Only after successful cleanup can the next eligible
entry start. Gateway-lock contention keeps its normal unbounded wait; a queued
pause is observed when that wrapper reaches campaign execution. Use the existing
gateway-lock controls for inspecting ownership, without force-releasing another
owner. Worker SIGINT/SIGTERM requests cooperative stop; abrupt process loss does
not establish cleanup and is recovered conservatively.

If cleanup, command completion or a worker restart cannot be verified, dispatch
halts and the entry needs attention. Inspect its logs and gateway ownership,
resolve the cause, explicitly resume/retry that entry, then press `s` again.
The worker never force-releases a gateway lease or changes authentication.
Source/profile drift pauses execution before hardware dispatch: restore the
matching source or enqueue a fresh entry from the new revision. Do not bypass
source checks or edit queue/campaign manifests to manufacture completion.

On Completed, Space marks/unmarks entries; `e` exports the marked selection.
Export locks the selected completed entries while remaining queue operations stay
available. Each new `results/queue/exports/<timestamp>-<id>/` contains `runs.csv`,
its typed/hash-checked archive metadata, a selection/provenance record and
`analysis.ipynb`. Only the explicitly selected campaign roots are discovered.
A changed completion manifest, unresolved failures, incomplete entries, or mixed
electrical/network annotations are refused. Every frozen entry initially copies
`configs/analysis/thesis_collection_annotations.json`; review its operator
assertions for the current lab. Local entry annotations can be corrected before
export, as in thesis collections. Select compatible annotations together.

The generated notebook adapts the general processing from the supplied Untitled
notebook: schema-driven nullable types, archive/hash validation, preserved raw
values and missingness, UTC timestamps, per-diagnostic indicators/counts,
preservation assertions and a column profile. `raw_df` retains the typed export;
`df` is the editable analysis view. Normalised timing metrics are provided by the
maintained archive exporter. Missing measurements stay missing; failed attempts
remain available for reliability work. The notebook includes a starting campaign/
outcome summary. Thesis-specific boot/TLS tables require their explicit control
and treatment selections and are not automatically applied to arbitrary campaigns.
Generated notebooks have no executed outputs; run their cells in the framework
Jupyter environment (`./scripts/dev.sh notebook`). Open the notebook beside its
CSV; a repository-root kernel is also supported. User notebook edits are local.

Local profiles, queue databases, copied profiles, logs, captures, CSVs and notebooks remain under
ignored `results/` paths. Creating or using them does not add Git changes; the
implementation and notebook generator are maintained source. Exported results
remain sensitive under the existing results policy.

Queue actions are also available without the full-screen UI. The `add` names
below must first exist as profiles under `results/profiles/` (create them with
`n` in the UI); they are not template names:

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

Entry IDs come from `list` or the UI. For logs, open
`results/queue/jobs/<entry-id>/logs/dispatch-*.log`; worker diagnostics are in
`results/queue/worker.log`. The underlying campaign CLI additionally accepts
`--pause-file`, `--stop-on-error`, `--preserve-completed`, and resume-only `--accept-failed` or
`--retry-failed`. Exit code 75 denotes a cooperative pause after cleanup; it is
not a completed campaign verdict. Existing campaign invocations retain their
continue-after-failure behavior unless `--stop-on-error` is selected.

Offline validation and the self-contained live breakpoint check:

```bash
./scripts/dev.sh pytest tests/unit/test_run_queue.py tests/unit/test_queue_workspace.py tests/unit/test_archive_table.py
./scripts/dev.sh pytest tests/integration/test_run_queue_in.py tests/integration/test_campaign_continue_in.py -m integration
./scripts/dev.sh pytest-hardware tests/hardware/test_run_queue_hw.py --pqc-require-hardware
```

The live baseline pause/intervening-campaign/resume test passed on 2026-10-03
(Australia/Melbourne): the first capture stayed unchanged, the remaining repetition
completed, and cleanup passed. Synthetic process/notebook tests separately cover
queue control and offline exports. Different-configuration interleaving and live
fault injection remain tracked by DTR-RUN-QUEUE in the architecture.

## Resumable thesis evidence collection

`scripts/collect_thesis_evidence.py` is a Linux host coordinator using only the
Python standard library. It invokes `scripts/dev.sh` for every resolver, campaign,
analysis and hardware-test operation. Do not run the host coordinator inside
`dev.sh python`: that would require nested Docker. No direct SSH or independent
flashing commands are used.

Create and inspect a plan without hardware access:

```bash
python3 scripts/collect_thesis_evidence.py plan --output results/thesis/collection-01
python3 scripts/collect_thesis_evidence.py status --output results/thesis/collection-01
```

The default plan contains five campaigns with ten reset attempts per condition:

| Campaign | Conditions | Attempts | Purpose |
| --- | ---: | ---: | --- |
| `secure_boot` | 12 | 120 | Normal boot timing |
| `secure_boot_stack` | 12 | 120 | Separate bootloader stack profiling |
| `thesis_kex` | 10 | 100 | Key exchange with ECDSA-P256 server authentication |
| `thesis_authentication` | 8 | 80 | Four certificate schemes, each with server and mutual authentication |
| `thesis_application_plaintext` | 1 | 10 | Matched application without TLS |

This is 43 conditions and 430 attempts. All three application comparison campaigns
use Ready Metrics 2 with a fixed 204800-byte payload and 400-byte chunks. The TLS
reference is TLS 1.3, ECDHE-secp256r1 and ECDSA-P256/SHA-256 server authentication.
The authentication study holds P-256 KEX fixed and compares certificate schemes
within each authentication mode, with separate server-versus-mutual contrasts.
All five source profiles explicitly select `instruments: {energy: esp32_ina228}`;
energy is captured alongside each run, without a separate energy campaign.
The existing PF12 trigger begins after bootloader handoff: secure-boot campaigns
retain the application energy trace, but bootloader verification energy remains
unavailable. Raw traces and supported derived values remain in the archive.
Normal boot timing and instrumented stack runs stay separate.

Network sweeps, repeated TLS, workload-size sweeps, energy-only, bare-metal and OTA
overhead campaigns remain available via explicit `--only` selections, but are not
default collection steps. Eight OTA lifecycle tests require `--include-ota`.
`--skip-ota` remains accepted for older commands and now matches the default.
Use `--repetitions N` at plan creation to override the ten-attempt pilot count;
ten attempts do not establish statistical sufficiency.
Plan choices are immutable after creation. Existing source edits need not be
committed, but the source, dirty submodule contents and copied profiles must stay
unchanged during collection. Resume refuses drift instead of mixing revisions.

The plan copies `configs/analysis/thesis_collection_annotations.json` to its local
`annotations.json`. The recorded electrical boundary is the operator-confirmed
E5V rail supplying STM32 plus Wi-Fi, excluding ST-Link's separate USB supply.
This wiring statement does not establish calibration accuracy. The supplied
device attribution is `10.1.7.126`, DHCP-reserved on the UniFi UDM-Pro for the
dedicated-AP PQC wireless network. If that reservation changes, set `network` in
the collection's annotations to
`{"client_ip": "<device IPv4>", "evidence_reference": "<reservation/lease evidence>"}`.
This assertion must apply to every selected capture; if addresses vary, use the
A8 per-run flow selections instead. The broker endpoint comes from each sealed
resolved snapshot. Without attribution, packets remain retained but packet
comparisons are unavailable. Missing energy attribution likewise stays unknown.

With the lab's existing board, gateway, brokers, Wi-Fi credentials, flash/UART
capabilities and calibrated persistent INA228 recorder provisioned, start:

```bash
python3 scripts/collect_thesis_evidence.py run --output results/thesis/collection-01
```

The driver executes sequentially; each hardware command obtains the existing
gateway lease with normal waiting and Ctrl-C cancellation. Campaigns own their
preparation, repeated captures and cleanup. OTA uses `pytest-hardware` and its
isolated build/generated-state volumes, strict capability checks, JUnit verdict
and suite-owned persistent result root. The script does not provision or flash
the energy recorder, alter gateway OS settings, or copy authentication material.

Experiment `run` and campaign commands show one compact row per preparation or
measurement run. On a terminal the current row changes in place from yellow
`[Running]` to green `[Success]`, red `[Failed]`, cyan `[Skipped]`, magenta
`[Blocked]`, or yellow `[Interrupted]`; only the final row advances to the next
line. For example:

```text
2026-09-30 11:20:00 2026-09-30_001_thesis_kex-0001-69594607494c [Success] 1/100
```

The counter is finished batch entries / planned entries for the current campaign,
including failures, blocked entries, and validated entries skipped on resume. It
is not a count of successful samples. Preparation rows carry `prep` and do not
advance this counter; standalone runs use `1/1`. Entries blocked before a run
folder exists show the case ID and repetition number. Long IDs are shortened in
the middle for display only. Rows use at most 119 visible columns on a 120-column
terminal. Redirected output contains one plain final row per entry; `NO_COLOR`
disables color while retaining terminal updates.

Detailed run stdout/stderr is flushed to `console.log` inside each run folder,
including preparation folders nested under the collection's campaign directory.
The transcript is closed before evidence sealing and retained in the hashed file
inventory. Existing build, flash, UART and prerequisite logs remain available.
Campaign-level explanations, including preparation errors, are in `campaign.log`
in the campaign folder; individual child logs remain under its `logs/` directory.
Errors before a run folder can be allocated, or during evidence sealing, remain
visible on stderr/stdout because there is no writable unsealed run transcript.
Gateway lease notices and collection/report summaries remain separate operational
messages. `PQC_PROGRESS_TIMEZONE` still controls timestamps (Melbourne by default).

This output change is source code: copy it to the collection PC between
collections and create a new plan there. An existing frozen plan will reject
changed source; do not bypass that check to adopt a display update mid-collection.

Repeat the same `run` command after interruption. Valid terminal steps are skipped.
Interrupted campaigns use their exact owned campaign manifest with `--resume`.
An interrupted OTA module runs again with a new attempt directory; previous
records remain. Failed/blocked attempts stay in campaign evidence and denominators;
the driver does not retry them merely to fill a successful-sample quota. Use
`run --retry-failed` explicitly to append retries of terminal failed steps after
reviewing their cause. Cleanup failure stops the suite. No lock is force-released.

At the end, datasets and an A8 report are generated automatically from only this
collection's bounded roots. One-factor analysis strata hold the other KEX,
certificate, authentication-mode, payload/chunk or network factors fixed.
Independent-run inference is off by default. Each report gets a new numbered
directory, preserving previous selections and all raw evidence. To report a
partial collection or revised local attribution without hardware:

```bash
python3 scripts/collect_thesis_evidence.py report --output results/thesis/collection-01
```

After upgrading analysis code, use `report --reanalyze --output <existing-collection>`
to produce a new numbered report from retained inputs. This records both the
original collection source identity and current analysis identity in
`analysis-source.json`. Plan integrity and frozen profile hashes are still
checked. This option never permits running or resuming hardware under changed
source: create a fresh collection plan for the next complete acquisition.

Reports hide excluded-only groups from comparisons, retain them in inventory,
and distinguish OTA signed-image identity from its unsigned build reference.
Notebook tables show explicitly labelled previews; full CSV files remain the
complete result tables.

`latest-report.json` names the verified A8 snapshot. The numbered report directory
also includes `collection-gaps.json`, the annotation snapshot, explicit analysis
selection and individual datasets. Use A8 `--verify` on that snapshot. Exit 0
means all scheduled workflow steps completed and a report verified; it does not
mean all measurements or RQs are complete. Exit 1 retains attempted/blocked
workflow failures, 2 indicates planning/source/report errors, and 130 interruption.
Skipped OTA tests or an unexpected test count cannot produce a successful verdict.

Collection cannot manufacture unsupported boot/OTA energy, cross-reset stage
timing, final candidate-to-image binding, simultaneous system RAM, disjoint
Total Crypto or handshake-only byte measurements. These remain explicit gaps
until their measurement contracts exist or the corresponding thesis columns
are revised as documented in the A8 architecture section.


### Matched no-TLS application baselines

`ready_metrics_plaintext` and `ready_metrics_2_plaintext` run the existing Ready
Metrics applications using plaintext MQTT on port 1883. Set `mqtt_transport:
plaintext` in a campaign's `fixed` choices to select this build mode. The resolver
allows TLS choices to be omitted; canonical plaintext campaigns omit them. Older
explicit `secp256r1`/`rsa3072`/`server` compatibility choices are still accepted
internally, but do not enable TLS, certificates or transport authentication.
Conflicting explicit TLS choices are rejected rather than silently ignored.
The application build excludes wolfSSL/wolfCrypt sources and linkage. wolfMQTT
remains for the MQTT protocol. Framework instrumentation and secure-boot verification
remain; this is a no-TLS application baseline, not a claim that the bootloader,
Wi-Fi link or entire device has no cryptography.

The same workload code, transfer sizes/chunks, QoS, reporting, boot settings and
network conditions are retained. Available plaintext families are listed below;
only `thesis_application_plaintext` belongs to the focused default collection:

| Campaign | Conditions | Attempts at 10 repetitions | Matched workload |
| --- | ---: | ---: | --- |
| `thesis_application_plaintext` | 1 | 10 | 200 KiB, 400-byte chunks |
| `thesis_network_rate_plaintext` | 3 | 30 | Reference and two rate limits |
| `thesis_network_rtt_plaintext` | 3 | 30 | Reference and two delays |
| `thesis_network_loss_plaintext` | 3 | 30 | Reference and two loss levels |
| `thesis_network_mtu_plaintext` | 3 | 30 | Reference and two MTUs |
| `thesis_energy_plaintext` | 1 | 10 | 200 KiB, 400-byte chunks, E5V energy |

Standalone Ready Metrics profiles each perform one attempt and are not extra
default collection steps. There is no plaintext TLS-handshake or primitive-crypto
benchmark: those operations do not exist without TLS.

Transport report strata compare the no-TLS baseline with classical, hybrid or
pure PQ TLS conditions where the collected TLS design includes them. The KEX and
authentication studies reuse the matching 200 KiB/400-byte plaintext application
condition; all selections stay within the current collection. These comparisons
measure the whole transition, including authentication, rather than isolating
only key exchange. New certificate comparisons use ECDSA-P256 as the baseline.
Archived collections
retain their frozen profiles; historical designs without `analysis_baselines`
retain their RSA reference, even when ECDSA was a comparison condition.
TLS handshake measurements absent on plaintext are unavailable, never zero-cost
handshakes. Original evidence labels remain in the exported inventory.

Create a fresh plan after transferring these source changes to the collection PC.
Do not update the checkout of an active frozen collection. An old plan will not
automatically acquire new profiles, and its source seal refuses revision mixing.
A selected subset needs both its TLS family and corresponding plaintext family
for transition comparisons. For example:

```bash
python3 scripts/collect_thesis_evidence.py plan --output results/thesis/transport-baselines-01 --only thesis_kex thesis_application thesis_application_plaintext --skip-ota
python3 scripts/collect_thesis_evidence.py run --output results/thesis/transport-baselines-01
python3 scripts/collect_thesis_evidence.py report --output results/thesis/transport-baselines-01
```

Before laboratory collection, qualify both application paths on the gateway:

```bash
./scripts/dev.sh pytest-hardware tests/hardware/test_plaintext_application_baselines_hw.py --pqc-require-hardware
```

### Flat experiment archive

Collection reports now also write `reports/<number>/archive/runs.csv`, with its
column dictionary and integrity metadata in `archive.json`. `latest-report.json`
names both the report snapshot and the archive directory. The flat archive is a
local analysis artifact, not the sanitized public report. It contains experiment
identifiers and evidence paths, but no payloads, key logs or credential material.

Every experiment run has one row, including bare-metal benchmarks. The only
exception is repeated TLS, with one row per recorded handshake attempt.
`run_key` identifies the retained capture; `row_id` identifies the particular row.
Run IDs can repeat in different result roots: never join on `run_id` alone.
Identical copied captures are deduplicated. Campaign attempts blocked before a
capture exists remain rows with null measurements. No missing handshakes are
invented from configured counts.

The table combines recorded numeric firmware fields with derived timings,
resources, TLS operation totals, packet observations, energy intervals and OTA
status. Repeated TLS handshakes are not replaced with medians. Bare-metal
repetitions within one run use explicitly named median-cycle columns; every raw
primitive record remains in the original evidence and specialist export. Static build facts
may repeat as context, but run-wide energy, packet totals and end-to-end timings
are not copied onto handshake rows. Unavailable, conflicting or unreliable values
are null. Row-level `run_success`, `capture_valid`, `selected_inputs_valid`,
`data_status`, `analysis_errors` and failure-stage columns keep diagnostics compact;
there are no validity/reason columns for every measurement. A reliable timing can
remain available in an otherwise failed run (for example, failed energy capture);
`timing_policy_exclusion` preserves the specialist comparison restriction. Detailed per-value
analysis can be regenerated from the original evidence.

Schema version 2 puts treatment choices in row fields and equivalent measurements
in shared columns. It does not make different measurement boundaries equivalent:

| Thesis comparison | Row fields / controls | Shared value columns (examples) |
| --- | --- | --- |
| Application performance: plaintext, classical, hybrid or PQ TLS (RQ1/RQ4) | `transport_mode`, `tls_kex`, `tls_auth`, `auth_mode`, payload/chunk, network and boot configuration | `timing__rtfb_us`, `timing__rtlb_us`, `timing__ttfb_us`, `timing__ttlb_us`, `timing__req_tfb_us`, `timing__req_tlb_us`, `timing__mqtt_readiness_us`, `application__payload_throughput_bytes_s` |
| Handshake / authentication (RQ2) | TLS profiles and authentication mode; repeated handshake ID | `timing__tls_handshake_us`, `tls__aggregate__signature_verify__elapsed_us`, `tls__aggregate__signature_sign__elapsed_us` |
| KEX components (RQ2) | `tls_kex` and recorded implementation fields | `tls__aggregate__kex_classical_keygen__elapsed_us`, `tls__aggregate__kex_kem_keygen__elapsed_us` |
| Memory / firmware (RQ1/RQ2) | Same workload/build controls and TLS choices | `resource__flash_section_bytes`, `resource__ram_static_base_bytes`, `resource__freertos_heap_peak_used_bytes` |
| Network (RQ3) | Network condition, transfer size, transport/TLS choices | `packet__client_to_server__wire_bytes`, `packet__server_to_client__overlap_bytes` |
| Application energy (RQ4) | Same workload, electrical boundary, capture/instrument configuration | `energy__whole_workload__energy_j`, `energy__whole_workload__average_power_w` |
| Secure boot / OTA (RQ5/RQ6) | `secure_boot`, `firmware_mode`, OTA state | `boot__image_verification_ms`, `boot__bootloader_flash_bytes`, `boot__image_signature_used_bytes`, `ota__*` outcomes |
| Bare-metal reference only | `primitive_signature_algorithm`, `primitive_signature_parameter`, `primitive_kem_algorithm`, `primitive_kem_parameter`, `primitive_repetitions`, `primitive__hclk_hz` | `primitive__signature_verify_median_cycles`, `primitive__kem_keygen_median_cycles`, other operation-specific median-cycle columns |

`transport_mode` distinguishes `plaintext` and `tls`; `kex_class` describes key
establishment only. Certificate authentication remains a separate axis in
`tls_auth`: a classical KEX may still use a PQ certificate. Plaintext has no TLS
handshake duration; that field is null, while its measured application timings
occupy the same columns as TLS. Inert resolver crypto selections do not label the
plaintext row as encrypted.

TLS primitive columns use functional roles, with observed implementations in
`tls_<role>_implementation`. Hybrid KEX retains separate classical and KEM
components in the same run row. A role containing multiple implementations is
labelled `mixed` and its value is null rather than combining unlike operations.
Aggregate and invocation representations remain separate and cannot be added to
protocol phases or each other to infer Total Crypto. Bare-metal cycle counts are
never mixed with application or TLS elapsed-time columns. Bare-metal parameters
are taken from measured records, not uncompiled alternatives; currently the
benchmark measures ML-DSA-65 and selected ML-KEM variants, not every algorithm
that can be used by TLS.

Schema-1 exports remain loadable in their original layout. Regenerate from the
retained evidence to obtain schema 2; do not edit sealed CSVs. Format changes or
new derivations from existing evidence do not require new experiments. Missing
measurements, incomplete captures or unsupported acquisition boundaries cannot
be recovered by changing the export.

Export a selected collection independently, or use `--results-root results` to
query the complete retained archive:

```bash
./scripts/dev.sh python scripts/export_archive_table.py \
  --results-root results/thesis/collection-01 \
  --output results/analysis/flat-archive-01 \
  --annotations configs/analysis/thesis_collection_annotations.json
./scripts/dev.sh python scripts/export_archive_table.py \
  --check results/analysis/flat-archive-01 --verify-sources
```

Use a new output directory for every export. Electrical-boundary and client-IP
annotations must apply to the selected captures; omit `--annotations` if that
attribution is unknown. Missing attribution leaves corresponding derived metrics
null instead of guessing a client or measurement rail. Unsupported historical
formats remain visible as unavailable captures. Existing specialized exports and
original logs remain the route to detailed diagnostics.

Load from a Python session started at the repository root:

```python
import sys
sys.path.insert(0, "scripts")
from framework.archive_table import load_archive

df = load_archive("results/analysis/flat-archive-01")
handshakes = df.loc[
    df["row_kind"].eq("handshake") & df["handshake_outcome"].eq("success"),
    ["source_commit", "campaign_execution_id", "run_key", "iteration_id",
     "tls_kex", "tls_auth", "timing__tls_handshake_us"],
]
energy = df.loc[df["energy__whole_workload__energy_j"].notna()]

# Select one matched application stratum, then compare all transport choices.
app = df.loc[
    df["row_kind"].eq("retained_capture")
    & df["application"].eq("mqtt_ready_metrics_2")
    & df["network_condition"].eq("baseline")
    & df["payload_bytes"].eq(4096) & df["chunk_bytes"].eq(400)
    & df["secure_boot"].eq("integrity_sha256")
    & df["run_success"] & df["selected_inputs_valid"] & df["capture_valid"]
    & df["timing_policy_exclusion"].isna()
]
# Choose a single source/build environment and energy mode before plotting.
# Preserve those strata here instead of silently pooling different revisions.
controls = ["target", "source_commit", "git_state_identity", "firmware_mode",
            "energy_enabled", "energy_profile"]
treatments = ["transport_mode", "tls_kex", "tls_auth", "auth_mode"]
summary = app.groupby(controls + treatments, dropna=False)[
    ["timing__ttlb_us", "timing__rtlb_us"]
].agg(["count", "median"])
# For a selected single control stratum:
# app.groupby(treatments)["timing__ttlb_us"].median().div(1000).plot.bar(ylabel="TTLB (ms)")
```

These are summaries of measured outcomes, not automatic causal estimates or
independence claims. Match QoS, actual network settings, platform/build environment,
boot and instrumentation controls before calculating deltas against a baseline.
Use the specialist matched-comparison reports for strict eligibility checks.
Count unique `run_key` values for independent experiment-run counts; repeated TLS
rows share a capture and must not be counted as additional boots.

The loader verifies output hashes and returns pandas nullable numeric, boolean and
string columns (`pd.NA` for missing values). It preserves identifier strings such
as leading-zero build numbers and literal `NA`. The CSV's explicit null token is
`\N`; use the loader instead of pandas' default NA/type guessing. The dictionary
records each measurement's origin, unit and any within-handshake operation total.

New collection plans enable the existing ESP32/INA228 instrument for every
supported deferred-reporting workload, including plaintext and the post-boot
application portions of secure-boot/OTA-overhead campaigns. This does not measure
bootloader or multi-reset OTA energy. The separate OTA lifecycle tests remain
outside that energy contract. Energy adds publication/storage cost and can reject
a capture with an acquisition fault; it does not change MQTT payloads, chunk sizes
or QoS. All matched new collection conditions use the same instrument selection.
The STM32's 20 ms tail guard is excluded from whole-workload energy using the
recorded workload-end timestamp. No ESP32 firmware update is required.
