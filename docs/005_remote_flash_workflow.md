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
Ready Metrics 2 (200 KiB, 400-byte chunks), `SecP256r1MLKEM768`, RSA-3072 server
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
| Certificate authentication | `rsa3072`, `mldsa65` |
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
using `secp256r1__rsa3072__server` as the reference. It retains failures, makes no
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
`SPEC["baseline"] = "ML_KEM_768__rsa3072__server"`. Conditions outside that filter
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
| `thesis_kex` | 10 | KEX; RSA-3072/server auth and baseline network fixed |
| `thesis_authentication` | 8 | Four certificate families × server/mutual; P-256 KEX fixed; analyse each factor within the other factor's fixed stratum |
| `thesis_repeated_tls` | 8 | Classical/hybrid × RSA/ML-DSA × auth mode; ten fresh full handshakes per boot, ten outer attempts |
| `thesis_application` | 8 | Classical/hybrid × 4 KiB/200 KiB payload × 128/400-byte chunks; analyse payload and chunk effects separately |
| `thesis_network_rate` | 6 | Classical/hybrid × 100000/1024/256 kbit/s; other network variables fixed |
| `thesis_network_rtt` | 6 | Classical/hybrid × 0/20/100 ms configured RTT; other network variables fixed |
| `thesis_network_loss` | 6 | Classical/hybrid × 0/1/3 percent configured loss; other variables fixed |
| `thesis_network_mtu` | 6 | Classical/hybrid × 1500/1280/1000-byte MTU; other variables fixed |
| `thesis_energy` | 4 | Representative classical/hybrid and RSA/ML-DSA server-auth configurations with the existing instrument |
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

The default plan resolves all thirteen campaign families: the ten thesis pilots,
normal secure boot, instrumented boot stack and bare-metal reference. It assigns
ten outer reset attempts to every condition, including stack and bare-metal
campaigns: 93 conditions and 930 campaign attempts. The existing bare-metal and
repeated-TLS inner repetitions remain unchanged. Eight normal-build OTA scenario
tests additionally cover application update, rollback, bootloader migration,
invalid candidates and recovery. Their setup/recovery boots are separate retained
records; these tests are not ten independent performance samples. The diagnostic
Request 17 OTA build is excluded from this collection.

Use `--repetitions N` when creating a plan to choose an outer attempt count. Ten
is a pilot default, not statistical sufficiency. `--only thesis_kex ...` limits
campaign families; OTA remains included unless `--skip-ota` is explicitly supplied.
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
