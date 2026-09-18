# STM32L4R5 dual-bank OTA workflow

## Scope

The dual-bank OTA design uses two symmetric 1 MiB physical banks instead of the legacy primary/update/software-swap interpretation. Each physical bank is a complete boot environment: 128 KiB is reserved from bank offset `0x00000` for wolfBoot and candidate metadata, and the 896 KiB signed application slot begins at bank offset `0x20000`. With the 12 KiB wolfBoot image-header reserve, the application remains linked at logical vector address `0x08023000` regardless of which physical bank is mapped active.

The inactive physical bank is always addressed through the logical upper-bank window (`0x08100000`..`0x081FFFFF`). BFB2 remaps the selected physical bank into the logical lower-bank boot window after reset. No dedicated software swap partition remains. The app confirms through the reserved manifest tail, so the previous bank remains recoverable until the new application has completed its workload and reporting path.

## Candidate-bank layout

- `bank + 0x00000` .. `bank + 0x1BFFF`: candidate wolfBoot bytes (maximum 112 KiB in this implementation).
- `bank + 0x1C000` .. `bank + 0x1FFFF`: 16 KiB signed candidate-bank manifest slot.
- `bank + 0x20000` .. `bank + 0xFFFFF`: signed application slot (896 KiB).
- Application vector: logical `0x08023000` after the 12 KiB image header.

The 16 KiB manifest is a wolfBoot-signed image authenticated by the currently trusted system before activation. Its payload records the candidate wolfBoot size/SHA-256, signed-application size/SHA-256 and whether the bank is a bootloader migration. For a migration, the currently active wolfBoot authenticates this manifest and the two artifact hashes; the replacement wolfBoot is then responsible for authenticating its colocated application after BFB2 remapping. This permits migration to a different application-signing algorithm without asking the old bootloader to trust the new application key directly.

## Activation and recovery

`tools/wolfboot/src/update_flash_hwswap.c` verifies the signed bank manifest before any `hal_flash_dualbank_swap()` call. A missing, corrupt or unauthenticated manifest causes the inactive application candidate to be invalidated and the current valid bank remains selected. `hal_flash_dualbank_swap()` toggles BFB2 based on the observed `SYSCFG->MEMRMP.FB_MODE` mapping and launches option-byte reload/reset. The update path must therefore be tested in both Bank1→Bank2 and Bank2→Bank1 directions.

Post-swap, wolfBoot verifies the application at the same logical primary address. The final 24 bytes of the manifest reservation carry one-way staged/booted/confirmed markers outside the signed manifest image. wolfBoot writes staged before activation and booted on the first candidate boot. After the application completes its normal workload and successfully publishes deferred reporting evidence, it writes confirmed and resets. On that reset wolfBoot keeps the bank. If a booted candidate resets without confirmed, wolfBoot swaps back to the previous physical bank and invalidates the failed candidate after the mapping returns. A candidate that cannot be authenticated must not be reported as an OTA success.

## Reporting-plane delivery

OTA control/data belongs to the mandatory plaintext reporting broker on port 1886 and is outside experiment TLS and network impairment. `scripts/framework/ota.py` defines deterministic candidate metadata and retained bounded-chunk publication under `pqc/control/ota/stm32/<run-id>/...`. Do not carry OTA control over the experiment broker.

The reporting broker is explicitly sized for the retained OTA burst rather than inheriting Mosquitto's default queued-message limit. `experiment/mqtt-broker/config/reporting/mosquitto.conf` sets `max_queued_messages 8192`. At the framework's 192-byte chunk size, the maximum supported 112 KiB bootloader, 16 KiB candidate manifest and 896 KiB signed application require 598 + 86 + 4779 data topics plus the retained completion marker (5,464 retained messages total). The 8,192-message bound therefore covers the complete supported candidate while remaining finite. This setting applies only to the impairment-exempt reporting broker; workload/experiment broker queue settings are not changed.

## Manual validation sequence

From the repository root, resolve and execute one known-good secure-boot case first. Retain its result directory as the pre-update baseline. Build the candidate wolfBoot and candidate application using the normal framework paths, sign the application with the candidate bootloader's application key, construct the candidate-bank manifest payload from the exact candidate artifact hashes, and sign that manifest using a key already trusted by the currently active wolfBoot. Stage the three artifacts through the reporting-plane OTA delivery mechanism, verify complete byte counts and SHA-256 values before activation, then reset/activate.

After reset, retain: active physical bank, inactive physical bank, BFB2 state, old/new wolfBoot hashes, candidate manifest authentication outcome, staged and installed application hashes, wolfBoot verification result, and final application identity. Repeat the workflow in the opposite bank direction.

Negative validation must cover interrupted delivery, incomplete bank, corrupted candidate application, invalid application signature, invalid signed bank manifest, and failed/unconfirmed migration. In all rejection cases, verify that the invalid inactive bank was not accepted and that the previously valid bank is recoverable.

## wolfBoot source ownership

The dual-bank OTA implementation includes framework-specific source changes inside `tools/wolfboot`; it is therefore not reproducible from the unmodified upstream wolfBoot repository alone. The parent repository configures `tools/wolfboot` from the project-controlled `https://github.com/timkohlman1/wolfBoot.git` fork and pins the exact required commit through the submodule gitlink.

When OTA or bootloader work changes files inside `tools/wolfboot`, commit and push those changes to the project wolfBoot fork first, then stage and commit the updated `tools/wolfboot` gitlink in `PQC-Framework-02`. Do not leave the parent repository pointing at a submodule commit that exists only in a local detached HEAD. The official `wolfSSL/wolfBoot` repository may remain configured as a local `upstream` remote for future synchronization, but `.gitmodules` must reference a remote that can serve the project-pinned commit.

## Hardware-test gates

The destructive OTA hardware test is self-bootstrapping and does not require `PQC_OTA_HW*` environment variables, pre-existing `.pqc-generated-state`, repository `build/ota` output, or previously built wolfBoot/application artifacts. `scripts/dev.sh pytest-hardware` overlays `/workspace/.pqc-generated-state` and `/workspace/build` with anonymous Docker volumes before pytest starts. Those volumes hide any host copies, begin empty for the hardware-test invocation, and are removed automatically with `docker run --rm`; the host repository is therefore not populated with hardware-test generated state or build output. On the first test in a pytest invocation, the fixture resolves an ECDSA-P256 `dual_bank_ota` case directly from source-controlled profiles into the isolated generated-state volume, performs a fresh baseline experiment run, uses only the wolfBoot binary and signed application retained by that run to create the positive, rollback, migration, and negative OTA plans, and then reuses that private setup for the eight hardware scenarios. Baseline and per-scenario result directories live under pytest temporary storage; OTA plans and their signing evidence live under the isolated `/workspace/build/hardware-tests/dualbank-ota/` volume so `ota-prepare` retains repository-relative path semantics without writing to the host repository. Any inherited `PQC_OTA_HW*` variables are stripped from subprocess environments so stale shell configuration cannot affect the suite. A passing static/unit suite is not hardware evidence; BFB2, physical-bank identity, flash contents, reset behavior and rollback require retained hardware logs/manifests.

The hardware suite also contains explicit state-transition proofs for the six low-level conditions that a host return code alone cannot establish: physical-bank change, BFB2 change, candidate wolfBoot execution, candidate application execution, confirmation-marker programming, and rollback to the original physical bank. The application emits structured `PQC_OTA_APP` serial markers, while the established wolfBoot verification mailbox emits `wolfBoot verification result` evidence through the application UART path. Run pytest with `-s` to display those OTA serial markers while each scenario is reported:

```bash
./scripts/dev.sh pytest-hardware -s \
    tests/hardware/test_ota_dualbank_hw.py \
    -m hardware \
    --pqc-require-hardware
```

Representative OTA markers are `PQC_OTA_APP phase=request_accepted`, `transfer_complete`, `hashes_verified`, `activation_reset`, `boot_state`, `confirmed` and `confirmation_withheld`. Successful wolfBoot execution/authentication is correlated with `wolfBoot verification result: 0` between reset/state transitions. The complete serial capture remains `uart.log`; pytest displays the OTA and wolfBoot-verification lines so the bank transition is readable.

## Manual framework commands

Prepare a candidate only after the normal framework has produced the exact wolfBoot and signed application artifacts. The recovery algorithm must be one already trusted by the currently active wolfBoot:

```bash
./scripts/dev.sh experiment ota-prepare \
    --bootloader tools/wolfboot/wolfboot.bin \
    --signed-application build/Release/stm32_basic_hal1_v1_signed.bin \
    --recovery-boot-algorithm ecdsa_p256 \
    --output-dir build/ota
```

For a bootloader/PQC migration, add `--migration`. The command creates `build/ota/ota-plan.json` plus the signed candidate-bank manifest and signing evidence. Do not activate a replacement bootloader without that authenticated manifest.

A prepared plan can be attached to a normal resolved experiment run:

```bash
./scripts/dev.sh experiment-gateway run \
    --experiment .pqc-generated-state/campaigns/secure_boot/cases/<case>.yaml \
    --ota-plan build/ota/ota-plan.json
```

Campaigns use the same path: set `execution.ota_plan` in the campaign so the campaign executor forwards the plan to each resolved run. Matrix overrides may vary `execution.ota_plan` independently of the secure-boot and TLS selections.

For a delivery-only diagnostic against an already running reporting service, use:

```bash
./scripts/dev.sh experiment ota-deliver \
    --experiment .pqc-generated-state/campaigns/secure_boot/cases/<case>.yaml \
    --plan build/ota/ota-plan.json \
    --run-id <run-id>
```

The integrated `experiment-gateway run --ota-plan ...` form is the normal end-to-end path because it owns reporting-broker lifecycle and evidence capture. For valid positive and no-confirm/rollback plans, the runner does not stop at the ordinary workload reporting-complete event: it keeps the reporting broker and UART capture active until the OTA terminal state is observed. A confirmed update terminates on `PQC_OTA_APP phase=confirmed`; an intentional no-confirm rollback terminates only after `confirmation_withheld` and a subsequent restored-bank `boot_state`. Negative fault plans retain the normal failure/recovery handling.

## Negative-test plan generation

Negative hardware tests use isolated copies and never alter the canonical signed artifacts. Starting from a valid `build/ota/ota-plan.json`, create deterministic faults with:

```bash
./scripts/dev.sh experiment ota-fault-plan --plan build/ota/ota-plan.json --fault invalid-manifest
./scripts/dev.sh experiment ota-fault-plan --plan build/ota/ota-plan.json --fault corrupt-application
./scripts/dev.sh experiment ota-fault-plan --plan build/ota/ota-plan.json --fault interrupted
```

For explicit rollback of a valid-but-unconfirmed candidate, create the signed candidate with `ota-prepare --test-no-confirm`. This test-only bit is covered by the signed candidate manifest. After the candidate application completes its workload and deferred reporting path, it intentionally resets without writing the confirmation marker; wolfBoot must restore the previous bank and invalidate the unconfirmed candidate.

## Experiment-selectable firmware mode

The firmware configuration exposes two independent resolved choices. They are build-affecting and
therefore participate in configuration and firmware identity:

```yaml
fixed:
  firmware_mode: single_bank        # or dual_bank_no_ota / dual_bank_ota
  standby_signing_keys: 0           # 0, 1, or 2
```

Both fields may instead be campaign matrix dimensions.

`single_bank` retains the legacy wolfBoot primary/update/software-swap
layout. `DUALBANK_SWAP` is disabled, so the STM32 BFB2 swap implementation is
not selected by wolfBoot, and the application is compiled with
`PQC_OTA_ENABLED=0`.

`dual_bank_no_ota` uses the symmetric 1 MiB hardware dual-bank layout and the
BFB2 bank-switch implementation, but the application reporting-plane OTA
receiver/staging/confirmation code is compiled out (`PQC_OTA_ENABLED=0`).

`dual_bank_ota` uses the same symmetric hardware layout and compiles the
reporting-plane OTA staging, confirmation and rollback path
(`PQC_OTA_ENABLED=1`). An `--ota-plan` is rejected unless this mode is selected.

The logical signed-application vector remains `0x08023000` in all wolfBoot
modes, so the application does not require a different vector address after a
hardware bank remap.

### Standby firmware-signing keys

`standby_signing_keys` accepts 0, 1, or 2, giving a total trusted firmware key
count of 1, 2, or 3. Multi-key builds use wolfBoot's native keystore: each
signed image carries the normal public-key hint and wolfBoot selects the
matching trusted slot.

The persistent tuple directory is keyed by standby count, so changing the count
cannot silently reuse an incompatible keystore. Standby private keys remain in
the ignored local `secrets/wolfboot/tuples/...` tuple and are never copied into
result evidence.

When `standby_signing_keys: 0`, `PQC_WOLFBOOT_STANDBY_KEYS=0` specializes
`keyslot_id_by_sha()` to slot zero and the multi-slot iteration loop is excluded
at preprocessing time. With one or two standby keys the native constant-time
hint comparison iterates the generated 2- or 3-key keystore.

Example campaign matrix:

```yaml
matrix:
  secure_boot: [ecdsa_p256]
  firmware_mode: [single_bank, dual_bank_no_ota, dual_bank_ota]
  standby_signing_keys: [0, 1, 2]
```

This produces distinct firmware identities for all nine combinations and
prevents campaign build/flash reuse across incompatible layouts or key sets.

### Hardware-test generated storage

`./scripts/dev.sh pytest-hardware` overlays `/workspace/.pqc-generated-state` and `/workspace/build` with anonymous Docker volumes. The self-contained dual-bank OTA hardware fixture creates its resolver-generated case under `/workspace/.pqc-generated-state/hardware-tests/dualbank-ota/` and creates OTA plans plus signing evidence under `/workspace/build/hardware-tests/dualbank-ota/`. Baseline and per-scenario result directories remain under pytest temporary storage. Because the container runs with `--rm`, the anonymous volumes are removed when the hardware-test invocation exits and no generated OTA setup is written back to the host repository.


### Reset-spanning result collection

A dual-bank OTA run can reboot the STM32 more than once while retaining the same framework `run_id`. Each application boot may publish a complete deferred STM32 result stream before OTA processing or confirmation. The gateway collector therefore treats every completion-bounded sequence as an independent **boot epoch** for that source: sequence numbers may restart at zero only after the preceding epoch has supplied its completion record. Every epoch is independently checked for duplicate or missing chunks, declared chunk/record/byte counts, and SHA-256 integrity. An unfinished trailing epoch remains a collection failure. This preserves transport-integrity checking while allowing activation, candidate confirmation, and rollback resets to remain inside one experiment run ID.
