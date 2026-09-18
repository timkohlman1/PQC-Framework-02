# STM32L4R5 dual-bank OTA workflow

## Scope

Request 5 replaces the legacy primary/update/software-swap interpretation with two symmetric 1 MiB physical banks. Each physical bank is a complete boot environment: 128 KiB is reserved from bank offset `0x00000` for wolfBoot and candidate metadata, and the 896 KiB signed application slot begins at bank offset `0x20000`. With the 12 KiB wolfBoot image-header reserve, the application remains linked at logical vector address `0x08023000` regardless of which physical bank is mapped active.

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

## Manual validation sequence

From the repository root, resolve and execute one known-good secure-boot case first. Retain its result directory as the pre-update baseline. Build the candidate wolfBoot and candidate application using the normal framework paths, sign the application with the candidate bootloader's application key, construct the candidate-bank manifest payload from the exact candidate artifact hashes, and sign that manifest using a key already trusted by the currently active wolfBoot. Stage the three artifacts through the reporting-plane OTA delivery mechanism, verify complete byte counts and SHA-256 values before activation, then reset/activate.

After reset, retain: active physical bank, inactive physical bank, BFB2 state, old/new wolfBoot hashes, candidate manifest authentication outcome, staged and installed application hashes, wolfBoot verification result, and final application identity. Repeat the workflow in the opposite bank direction.

Negative validation must cover interrupted delivery, incomplete bank, corrupted candidate application, invalid application signature, invalid signed bank manifest, and failed/unconfirmed migration. In all rejection cases, verify that the invalid inactive bank was not accepted and that the previously valid bank is recoverable.

## Hardware-test gates

The destructive OTA test is opt-in. Set `PQC_OTA_HW=1` and `PQC_OTA_HW_CASE` to a resolved secure-boot case, then run `tests/hardware/test_ota_dualbank_hw.py`. A passing static/unit suite is not hardware evidence; BFB2, physical-bank identity, flash contents, reset behavior and rollback require retained hardware logs/manifests. The Linux `scripts/dev.sh` wrapper forwards the Request-5 OTA hardware variables into the container by name: `PQC_OTA_HW`, `PQC_OTA_HW_CASE`, `PQC_OTA_HW_APP_PLAN`, `PQC_OTA_HW_ROLLBACK_PLAN`, `PQC_OTA_HW_MIGRATION_PLAN`, `PQC_OTA_HW_INTERRUPTED_PLAN`, `PQC_OTA_HW_CORRUPT_APP_PLAN`, and `PQC_OTA_HW_INVALID_MANIFEST_PLAN`.

The hardware suite also contains explicit state-transition proofs for the six low-level conditions that a host return code alone cannot establish: physical-bank change, BFB2 change, candidate wolfBoot execution, candidate application execution, confirmation-marker programming, and rollback to the original physical bank. The firmware and wolfBoot emit structured serial markers prefixed `PQC_OTA_APP` and `PQC_OTA_BOOT`. Run pytest with `-s` to display those OTA serial markers while each scenario is reported:

```bash
./scripts/dev.sh pytest-hardware -s \
    tests/hardware/test_ota_dualbank_hw.py \
    -m hardware \
    --pqc-require-hardware
```

Representative markers are `PQC_OTA_APP phase=request_accepted`, `transfer_complete`, `hashes_verified`, `activation_reset`, `boot_state`, `confirmed` or `confirmation_withheld`, plus wolfBoot markers `PQC_OTA_BOOT phase=start`, `candidate_manifest_authenticated`, `candidate_application_authenticated`, `swap_requested`, `candidate_first_boot`, and `rollback_requested`. The complete serial capture remains `uart.log`; the pytest display filters to Request-5 OTA markers so the bank transition is readable.

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

The integrated `experiment-gateway run --ota-plan ...` form is the normal end-to-end path because it owns reporting-broker lifecycle and evidence capture.

## Negative-test plan generation

Negative hardware tests use isolated copies and never alter the canonical signed artifacts. Starting from a valid `build/ota/ota-plan.json`, create deterministic faults with:

```bash
./scripts/dev.sh experiment ota-fault-plan --plan build/ota/ota-plan.json --fault invalid-manifest
./scripts/dev.sh experiment ota-fault-plan --plan build/ota/ota-plan.json --fault corrupt-application
./scripts/dev.sh experiment ota-fault-plan --plan build/ota/ota-plan.json --fault interrupted
```

For explicit rollback of a valid-but-unconfirmed candidate, create the signed candidate with `ota-prepare --test-no-confirm`. This test-only bit is covered by the signed candidate manifest. After the candidate application completes its workload and deferred reporting path, it intentionally resets without writing the confirmation marker; wolfBoot must restore the previous bank and invalidate the unconfirmed candidate.

## Experiment-selectable firmware mode

Request 5 exposes two independent resolved choices. They are build-affecting and
therefore participate in configuration and firmware identity:

```yaml
fixed:
  firmware_mode: single_bank        # or dual_bank_no_ota / dual_bank_ota
  standby_signing_keys: 0           # 0, 1, or 2
```

Both fields may instead be campaign matrix dimensions.

`single_bank` retains the pre-Request-5 wolfBoot primary/update/software-swap
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
