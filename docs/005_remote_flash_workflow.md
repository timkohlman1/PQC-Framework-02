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
