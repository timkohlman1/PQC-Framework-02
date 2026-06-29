# Decision 0002 — wolfBoot STM32L4 Target Support Assessment

## Status

Accepted for Phase 10c.

## Date

2026-06-29

## Context

The project target is the NUCLEO-L4R5ZI-P / STM32L4R5 direct-flash STM32 HAL baseline. The current wolfBoot profile is only a planned, non-runnable placeholder. Phase 10c requires a technical decision on whether upstream wolfBoot already provides a suitable STM32L4 target or whether this project needs target adaptation before defining a secure-boot flash layout.

Phase 10c does not relocate the application, build wolfBoot, generate signing keys, flash wolfBoot, or claim runtime secure-boot success.

## Upstream Evidence Reviewed

- The wolfBoot manual includes an STM32L4 target example with 4 KB sectors, a 40 KB wolfBoot region, a 488 KB application partition, `WOLFBOOT_PARTITION_BOOT_ADDRESS` at `0x0800A000`, `WOLFBOOT_PARTITION_UPDATE_ADDRESS` at `0x08084000`, and `WOLFBOOT_PARTITION_SWAP_ADDRESS` at `0x080FE000`.
- The wolfBoot manual states that the signed firmware entry point must be linked at `WOLFBOOT_PARTITION_BOOT_ADDRESS + 256` for ECC signature headers.
- The upstream wolfBoot repository includes an STM32L4 HAL implementation at `hal/stm32l4.c` that uses STM32L4 HAL flash erase/write mechanisms and STM32L4 page/bank concepts.
- wolfBoot supports ECDSA P-256 selection with `SIGN=ECC256`.
- wolfBoot partitioning is configured through target-specific values such as sector size, boot partition address, update partition address, swap address, and partition size.

## Target Compatibility Assessment

### Closest Supported Target

The closest supported target is wolfBoot's existing STM32L4 support.

This is close enough to use as the starting point for the project. It is not sufficient to treat wolfBoot as already working on the NUCLEO-L4R5ZI-P / STM32L4R5 board because the upstream STM32L4 example is documented as a 1 MB layout, while this project target has 2 MB of internal flash.

### Flash Size

The project board has 2 MB of internal flash. The upstream STM32L4 example layout only describes a 1 MB target layout. The project must therefore define its own STM32L4R5-specific flash layout before any linker relocation, wolfBoot build, signing, or flashing work.

### Flash Page and Sector Layout

The upstream STM32L4 example uses 4 KB sectors. The project should initially treat 4 KB page/sector alignment as the working assumption, but Phase 10d must confirm the exact STM32L4R5 flash geometry, bank mode, erase granularity, and address alignment against the board and STM32 reference material before layout values are finalized.

### Vector Table Expectations

A signed application image is not entered at the raw partition start. wolfBoot expects the application entry point after the image header. For ECC-signed images, this means the relocated application must be linked for `WOLFBOOT_PARTITION_BOOT_ADDRESS + 0x100`, not merely the partition start address.

The relocated HAL application will also need its vector table offset set consistently with the linked application address in a later phase.

### Bootloader Location

The normal STM32 internal flash base is `0x08000000`. The working assumption for this project is that wolfBoot will occupy the beginning of internal flash and the signed application slot will begin at a later aligned address. The exact wolfBoot size and first application slot address must be selected in Phase 10d.

### Application Offset

The earlier tentative `0x08020000` signed-application offset remains unconfirmed. If selected, the relocated application entry point would be expected at `0x08020100` for a standard ECC header. Phase 10d must confirm whether `0x08020000` leaves enough room for wolfBoot, public-key material, build/debug growth, required alignment, update slot, swap/trailer data, and the planned experiment firmware size.

### Signing Support

The intended ECDSA-P256 profile maps to wolfBoot's ECC256 signing support. This is suitable as a planned signing algorithm, but no signing workflow or key material is implemented in Phase 10c.

### Build and Toolchain Assumptions

wolfBoot uses its own build configuration and target values. The current project build system only covers the STM32 HAL application through CMake/Ninja and STM32 tooling. A later phase must add an explicit wolfBoot build profile rather than assuming the current HAL application build profile can build the bootloader.

## Decision

Use wolfBoot's existing STM32L4 support as the starting point, but create a project-local STM32L4R5 / NUCLEO-L4R5ZI-P target configuration or adaptation before attempting to build or flash wolfBoot.

The project will not claim that the upstream STM32L4 target is directly runnable on STM32L4R5. The next phase must define a project-specific secure-boot flash layout first.

## Consequences

- The direct-flash baseline remains the only runnable boot mode.
- `configs/boot/wolfboot_ecdsa_p256.yaml` remains non-runnable.
- Phase 10d should define the STM32L4R5 flash layout explicitly before linker relocation.
- Phase 10e should relocate the HAL application to the selected signed-image entry address.
- Phase 10f should add an explicit wolfBoot build profile using the selected project-local target values.
- Phase 10g should add signing workflow support without committing private signing keys.
- No hardware, UART, flash, signing, or secure-boot success is claimed by this decision.

## Risks and Open Questions

- I cannot confirm this target is directly runnable without a project-local wolfBoot build and hardware logs.
- The correct slot layout depends on final decisions about one-slot versus two-slot update flow, swap area, trailer placement, and whether update storage remains in internal flash.
- The STM32L4R5 flash bank mode and option-byte state may affect erase/write assumptions.
- The bootloader size must be measured once the selected wolfBoot crypto and debug options are built.
- The final relocated application entry address must account for wolfBoot's image header.
