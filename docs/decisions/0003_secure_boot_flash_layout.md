# Decision 0003 — STM32L4R5 Secure-Boot Flash Layout

## Status

Accepted for Phase 10d.

## Date

2026-06-29

## Context

The project target is the NUCLEO-L4R5ZI-P / STM32L4R5 direct-flash STM32 HAL baseline. The board has 2 MB of internal flash starting at `0x08000000`.

Phase 10c selected wolfBoot's existing STM32L4 support as the closest upstream starting point, but required a project-local STM32L4R5 / NUCLEO-L4R5ZI-P target configuration or adaptation before wolfBoot is built or treated as runnable.

Phase 10d defines the initial secure-boot flash layout before any HAL application relocation, wolfBoot build profile, signing workflow, or wolfBoot flashing workflow is implemented.

## Upstream Evidence Considered

The wolfBoot STM32L4 manual example uses:

```c
#define WOLFBOOT_SECTOR_SIZE                 0x1000   /* 4 KB */
#define WOLFBOOT_PARTITION_BOOT_ADDRESS      0x0800A000
#define WOLFBOOT_PARTITION_SIZE              0x7A000  /* 488 KB */
#define WOLFBOOT_PARTITION_UPDATE_ADDRESS    0x08084000
#define WOLFBOOT_PARTITION_SWAP_ADDRESS      0x080FE000
```

The manual also documents that runnable firmware entry is offset by the image header. For ECC-signed images, the application entry address is expected to be the signed application slot start plus `0x100`.

## Decision

Use an initial two-slot internal-flash layout for the planned `wolfboot_ecdsa_p256` profile.

The earlier working assumption is accepted as the initial signed application slot start:

```text
0x08000000  wolfBoot
0x08020000  signed application slot
```

The selected initial layout is:

```text
Internal flash base: 0x08000000
Internal flash size: 0x00200000  # 2 MB
Internal flash end:  0x081FFFFF

0x08000000..0x0801FFFF  wolfBoot region                 0x00020000  128 KB
0x08020000..0x080FFFFF  signed application primary slot  0x000E0000  896 KB
0x08100000..0x081DFFFF  signed application update slot   0x000E0000  896 KB
0x081E0000..0x081FFFFF  swap / metadata reserve          0x00020000  128 KB
```

The planned wolfBoot target values are therefore:

```c
#define WOLFBOOT_SECTOR_SIZE                 0x1000
#define WOLFBOOT_PARTITION_BOOT_ADDRESS      0x08020000
#define WOLFBOOT_PARTITION_SIZE              0x000E0000
#define WOLFBOOT_PARTITION_UPDATE_ADDRESS    0x08100000
#define WOLFBOOT_PARTITION_SWAP_ADDRESS      0x081E0000
```

For the planned ECDSA-P256 / ECC image header, the HAL application must later be linked and configured to start at:

```text
0x08020100
```

The application entry address is not the same as the primary slot base. The first `0x100` bytes of the slot are reserved for the wolfBoot image header.

## Rationale

The layout deliberately keeps the direct-flash baseline untouched and gives the planned wolfBoot profile a concrete, auditable memory map before linker relocation.

The `0x08020000` primary slot base provides a 128 KB reserved bootloader region at the start of flash. This is larger than the 40 KB STM32L4 example bootloader region and is intended to leave room for STM32L4R5 target adaptation, ECDSA-P256 verification code, public verification material, debug growth, and alignment.

The primary and update slots are equal size. This supports an internal-flash update path in a later phase without requiring external storage for the first working secure-boot experiment.

The update slot starts at `0x08100000`, which is the 1 MB boundary. This gives a simple split: the bootloader and primary application slot occupy the lower 1 MB, while the update slot and swap / metadata reserve occupy the upper 1 MB.

The `0x081E0000` reserve leaves 128 KB at the end of flash for wolfBoot swap and metadata needs while the exact STM32L4R5 update strategy is still being validated.

All selected addresses and sizes are aligned to the working 4 KB wolfBoot STM32L4 sector-size assumption.

## Consequences

- `configs/boot/wolfboot_ecdsa_p256.yaml` can now describe an explicit planned flash layout.
- The direct-flash baseline remains the only runnable boot mode.
- The planned wolfBoot profile remains `runnable: false`.
- Phase 10e should relocate the HAL application linker script and vector-table configuration to `0x08020100` when adding a relocated application build profile.
- Phase 10f should use the selected values when creating the project-local STM32L4R5 wolfBoot target configuration or adaptation.
- Phase 10g should keep private signing keys outside the repository.
- Phase 10h should flash wolfBoot and the signed application only after build, signing, and provenance handling exist.

## Not Implemented by This Decision

This decision does not:

- relocate `STM32L4R5XX_FLASH.ld`
- change vector-table configuration
- build wolfBoot
- vendor wolfBoot source
- generate or store signing keys
- sign an application image
- flash wolfBoot
- flash a signed application
- claim secure-boot runtime success

## Risks and Open Questions

- I cannot confirm this layout boots until wolfBoot is built for the project-local STM32L4R5 target and user-provided hardware logs show the expected UART evidence.
- The exact STM32L4R5 erase geometry, flash bank mode, and option-byte state still need to be confirmed against the physical board before relying on swap/update behaviour.
- The bootloader reserve may need adjustment after measuring the actual wolfBoot binary with the selected ECDSA-P256 configuration.
- The 128 KB swap / metadata reserve is an initial conservative allocation. It may be reduced or reshaped after wolfBoot update and trailer requirements are verified for the selected target configuration.
- The initial layout assumes internal-flash update storage. A later network or OTA phase may choose a different update-image storage model.
- The exact UART marker that distinguishes wolfBoot-mediated boot from direct-flash boot remains a later-phase decision.
