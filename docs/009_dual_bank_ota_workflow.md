# Dual-bank OTA workflow

This guide owns STM32L4R5 candidate-bank delivery, activation and recovery.
[Configuration](011_experiment_configuration.md) owns profile composition;
[operation](005_remote_flash_workflow.md) owns ordinary build/sign/run commands.
Signing identity and all experiment material follow the
[open-data policy](006_security_and_secrets.md).

## Modes and layout

`single_bank` retains the primary/update/software-swap arrangement.
`dual_bank_no_ota` selects symmetric hardware banks but compiles out application
OTA handling. `dual_bank_ota` additionally enables reporting-plane reception,
staging, activation and confirmation. An OTA plan requires the latter mode.
All retain the logical application vector `0x08023000`.

Each physical 1 MiB dual bank contains:

| Bank-relative range | Purpose |
|---|---|
| `0x00000`–`0x1BFFF` | Candidate wolfBoot, at most 112 KiB |
| `0x1C000`–`0x1FFFF` | 16 KiB candidate-bank manifest reservation |
| `0x20000`–`0xFFFFF` | 896 KiB signed application slot, including 12 KiB header reserve |

BFB2 activation maps the selected physical bank into the lower logical boot window.
The inactive bank is accessed through `0x08100000`–`0x081FFFFF`. No software copy/swap
partition is used by these modes. The final 24 bytes of the manifest reservation
hold one-way staged/booted/confirmed markers outside the signed manifest image.

## Trust and state transitions

The current trusted wolfBoot verifies the candidate-bank manifest before activation.
Its payload binds candidate bootloader and signed-application sizes/SHA-256 values
and the migration flag. During bootloader migration, the old bootloader authenticates
that package; after remapping, the candidate bootloader verifies its application
using its own configured key/algorithm. Integrity-only checks must not be described
as signature-based authentication.

`tools/wolfboot/src/update_flash_hwswap.c` refuses missing/invalid manifest evidence,
invalidates a rejected inactive candidate and keeps the valid bank. The swap helper
uses live `SYSCFG->MEMRMP.FB_MODE` mapping and reloads option bytes/reset. Verify both
physical directions; a raw BFB2 bit alone is not the bank-transition proof.

After a verified candidate boot, the application completes its workload and deferred
reporting, writes confirmation and resets. A booted candidate that resets without
confirmation causes rollback to the previous physical bank and invalidation of the
failed candidate. Transport completion alone is not OTA success.

## Delivery and prepared plans

OTA control/data uses the impairment-exempt plaintext reporting broker on port 1886,
under `pqc/control/ota/stm32/<run-id>/...`. Publication is retained and chunked at
192 bytes. The reporting broker's 8,192-message queue covers the supported maximum
bootloader, manifest and application burst (5,464 messages including completion).
Do not route OTA through the measured experiment broker.

First produce the exact candidate artifacts through normal framework builds/signing.
The recovery algorithm must be trusted by the active bootloader:

```bash
./scripts/dev.sh experiment ota-prepare   --bootloader tools/wolfboot/wolfboot.bin   --signed-application build/Release/stm32_basic_hal1_v1_signed.bin   --recovery-boot-algorithm ecdsa_p256 --output-dir build/ota
```

Add `--migration` when replacing the bootloader. The result includes `ota-plan.json`,
the signed bank manifest and signing evidence. Select a resolved `dual_bank_ota`
case and attach the plan:

```bash
./scripts/dev.sh experiment-gateway run --experiment .pqc-generated-state/campaigns/<campaign>/cases/<case>.yaml --ota-plan build/ota/ota-plan.json
```

A campaign can instead set `execution.ota_plan`, including matrix overrides.
The integrated run owns reporting-broker lifecycle and keeps capture active beyond
ordinary workload completion until OTA terminal evidence appears. Positive completion
requires `confirmed`; no-confirm rollback requires `confirmation_withheld` followed
by restored-bank `boot_state`. Negative cases retain separate failure/recovery evidence.

For delivery-only diagnosis against a running reporting service:

```bash
./scripts/dev.sh experiment-gateway ota-deliver --experiment .pqc-generated-state/campaigns/<campaign>/cases/<case>.yaml --plan build/ota/ota-plan.json --run-id <run-id>
```

This stages delivery; it is not a substitute for integrated transition validation.

## Negative cases and signing choices

Fault plans mutate isolated copies, preserving canonical artifacts:

```bash
./scripts/dev.sh experiment ota-fault-plan --plan build/ota/ota-plan.json --fault invalid-manifest
./scripts/dev.sh experiment ota-fault-plan --plan build/ota/ota-plan.json --fault corrupt-application
./scripts/dev.sh experiment ota-fault-plan --plan build/ota/ota-plan.json --fault interrupted
```

`ota-prepare --test-no-confirm` signs a test-only bit that makes the candidate reset
without confirming after its workload/reporting. Verify rollback and the recovery
image, not just the command return code.

`standby_signing_keys` accepts 0, 1 or 2 for signed profiles, adding that many trusted
keys to the primary slot. It affects firmware/tuple identity. Native key-hint lookup
selects the matching keystore slot; zero standby keys specializes lookup to slot zero.
Changing the count cannot reuse an incompatible tuple. Tuple retention, including
standby files, is described in the open-data policy.

## Hardware validation and evidence

The self-contained suite prepares an ECDSA-P256 dual-bank case, builds/flashes its
baseline, creates candidate/fault plans and exercises transition scenarios:

```bash
./scripts/dev.sh pytest-hardware -s tests/hardware/test_ota_dualbank_hw.py -m hardware --pqc-require-hardware
```

No prior build/case, retained run or `PQC_OTA_HW*` environment input is required.
The wrapper isolates `build/` and `.pqc-generated-state/` in anonymous volumes;
fixtures create test-owned setup there and retain evidence through pytest's
result workflow. Volumes are removed at container exit. Capability gates still need
the actual board, gateway, helpers and network infrastructure.

Assertions distinguish observed physical-bank mapping, BFB2 state, candidate
verification/execution, confirmation programming and recovery. Representative
`PQC_OTA_APP` phases include `request_accepted`, `transfer_complete`, `hashes_verified`,
`activation_reset`, `boot_state`, `confirmed` and `confirmation_withheld`.
Raw UART and reporting remain retained. Unit tests cannot establish these physical
state changes; current missing qualification belongs to the
[test register](013_testing_and_deferred_coverage.md).

Multiple application boots may reuse one run ID. The collector validates each
completion-bounded reporting epoch independently, allowing sequence restart only
after prior completion. An unfinished trailing epoch fails collection. An epoch
alone does not prove a reset or immutable candidate-image execution; interpretation
and OTA importer limits belong to [results](012_results_and_analysis.md).

Optional `boot_uart_diagnostics` adds blocking early UART observations and excludes
normal boot timing comparisons. It supplements rather than replaces transition
records. Bootloader changes belong to the pinned project `tools/wolfboot` fork;
follow the [AI guide](../AI_BUILD_GUIDE.md) for authorized submodule publication.
