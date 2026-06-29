# Phase 10 — Start Boot-Security Experiments: Sub-Phase Plan

## Purpose

This document breaks the proposed **Phase 10 — Start Boot-Security Experiments** scope into smaller implementation phases suitable for separate AI-assisted development prompts.

The intent is to state the **requirement and expected outcome** for each sub-phase, not to prescribe the exact implementation approach. Each implementation prompt should inspect the current repository files and decide the specific code, configuration, test, and documentation changes needed.

The direct-flash STM32 HAL baseline should remain the known-good regression path while boot-security support is introduced incrementally. wolfBoot should not be treated as implemented or working until build, signing, flashing, UART evidence, and documentation are in place.

Private signing keys, private certificates, credentials, and other secrets must remain out of Git.

---

## Phase 10a — Add Direct-Flash Boot Config Model - COMPLETED 27/6

### Goal

Introduce boot mode as a first-class configuration concept without changing runtime behaviour.

### Requirements / Outcomes

- Add `configs/boot/direct_flash.yaml`.
- Refactor the baseline experiment config so it references the direct-flash boot config.
- Extend config loading and validation so experiment configs can resolve a boot config.
- Preserve the current known-good direct-flash baseline behaviour.
- Ensure the existing baseline commands continue to work:
  - `status`
  - `create-run`
  - `build`
  - `flash`
  - `build-flash`
  - `run`
- Record or preserve `boot_mode` in the manifest as `direct_flash`.
- Add unit tests for boot config resolution and validation.
- Update README, architecture documentation, and `AI_BUILD_GUIDE.md`.

### Pass Criteria

- Unit tests pass.
- Existing direct-flash baseline commands still resolve config correctly.
- No wolfBoot implementation is added.

---

## Phase 10b — Add Planned wolfBoot Boot Config Placeholder - COMPLETED 27/6

### Goal

Add a planned wolfBoot boot-profile config without enabling or implementing wolfBoot.

### Requirements / Outcomes

- Add `configs/boot/wolfboot_ecdsa_p256.yaml` as a planned or inactive boot profile.
- Mark it clearly as not yet runnable.
- Include intended metadata such as:
  - boot mode
  - intended signature algorithm
  - planned application slot concept
- Avoid claiming a final flash layout until it is confirmed.
- Ensure normal baseline workflows do not accidentally use this config.
- Add validation behaviour that can distinguish implemented/runnable boot configs from planned/non-runnable configs.
- Add tests proving the planned wolfBoot config is loadable for inspection but not accepted for execution unless explicitly supported.
- Update documentation and `AI_BUILD_GUIDE.md`.

### Pass Criteria

- Direct-flash baseline remains unchanged.
- wolfBoot config exists but cannot be mistaken for a working boot mode.
- No wolfBoot source, linker relocation, signing, or flashing is implemented.

---

## Phase 10c — wolfBoot STM32L4 Target Support Assessment - COMPLETED 29/6

### Goal

Produce a documented technical decision on whether wolfBoot already supports a suitable STM32L4 target or whether a target adaptation is required.

### Requirements / Outcomes

- Inspect wolfBoot upstream target support for STM32L4 / STM32L4R5 suitability.
- Identify the closest supported target, if any.
- Document compatibility concerns, including:
  - flash size
  - flash page/sector layout
  - vector table expectations
  - bootloader location
  - application offset
  - signing support
  - build/toolchain assumptions
- Decide whether the project will:
  - use an existing wolfBoot target,
  - adapt an existing target, or
  - create a project-local target configuration.
- Do not modify firmware linker scripts yet.
- Do not build wolfBoot yet.
- Do not generate signing keys yet.
- Update documentation and `AI_BUILD_GUIDE.md` with the decision.

### Pass Criteria

- A documented decision exists.
- The next implementation phase has enough information to define the flash layout safely.
- No runtime behaviour changes are made.

---

## Phase 10d — Define Secure-Boot Flash Layout - COMPLETED 29/6

### Goal

Define the initial wolfBoot flash memory layout as a documented project decision before relocating the application.

### Requirements / Outcomes

- Define the intended STM32L4R5 flash layout for:
  - wolfBoot
  - signed application slot
  - optional update/swap area, if required
  - any metadata/trailer area required by wolfBoot
- Evaluate whether the initial working assumption is valid:

  ```text
  0x08000000  wolfBoot
  0x08020000  signed application
  ```

- Document the rationale and constraints.
- Ensure the layout accounts for the board's 2 MB flash size.
- Add config/documentation fields needed to describe the planned layout.
- Do not relocate the application yet.
- Do not flash wolfBoot yet.

### Pass Criteria

- Flash layout decision is documented.
- The selected application offset is explicit.
- Any unresolved risks are documented.

---

## Phase 10e — Relocate HAL Application for Bootloader Launch  - COMPLETED 29/6

### Goal

Build the existing HAL application so it can run from the chosen signed-application address.

### Requirements / Outcomes

- Add a relocated application build profile or configuration.
- Relocate the HAL application linker script to the selected application start address.
- Set the vector table offset consistently with the chosen application address.
- Build the relocated app.
- Preserve the direct-flash baseline as a separate known-good path.
- Add unit tests for configuration selection where applicable.
- Add an opt-in integration test or documented manual command for relocated-app build verification.
- Update documentation and `AI_BUILD_GUIDE.md`.

### Pass Criteria

- Direct-flash baseline remains available.
- Relocated app builds successfully when the local toolchain is available.
- No claim is made that the relocated app boots unless user-provided UART logs confirm it.

---

## Phase 10f — Add wolfBoot Build Profile - COMPLETED 29/6

### Goal

Add framework support for invoking a wolfBoot build profile and capturing wolfBoot build evidence without enabling signing, flashing, UART capture, or secure-boot runtime claims.

### Requirements / Outcomes

- Add wolfBoot build configuration/profile support.
- Add a framework command that can invoke the configured wolfBoot build profile.
- Capture wolfBoot build logs, return codes, artifact paths, artifact existence, and hashes when an artifact is produced.
- Record controlled failures when wolfBoot source, build tooling, or target integration is missing.
- Keep wolfBoot build outputs out of Git.
- Keep direct-flash build behaviour unchanged.
- Add unit tests using mocked command runners.
- Ensure unit tests do not invoke wolfBoot build tooling.
- Add opt-in integration test coverage only if the required tooling and wolfBoot source are available.
- Update documentation and `AI_BUILD_GUIDE.md`.

### Observed Result / Follow-Up Need

- The Phase 10f framework command and evidence-capture path are implemented.
- Full pytest regression passed with the wolfBoot integration test skipped when local wolfBoot prerequisites were unavailable.
- After cloning wolfBoot locally and initialising submodules, the framework command invoked the upstream `TARGET=stm32l4` build and captured controlled failure evidence.
- The observed blocker is that upstream `TARGET=stm32l4` does not directly find or use the project CubeMX STM32L4R5 HAL/CMSIS layout.
- Manual diagnostics showed the build needs project-local HAL/CMSIS include paths and Cortex-M4/thumb target flags, but those flags must not be applied to host keytools.
- This creates a required follow-up phase for a project-local STM32L4R5 wolfBoot target/build adaptation before signing or flashing phases proceed.

### Pass Criteria

- wolfBoot build can be invoked through the framework when configured.
- Build evidence is captured for success and failure cases.
- Missing source, missing tooling, and failed build commands are recorded without Python tracebacks.
- Unit tests remain hardware-free.
- No signing, flashing, UART evidence, or secure-boot runtime success is claimed.

---

## Phase 10f.1 — Project-Local wolfBoot STM32L4R5 Target Adaptation - completed 29/6

### Goal

Adapt the upstream wolfBoot STM32L4 support so the framework can build wolfBoot for the project-local NUCLEO-L4R5ZI-P / STM32L4R5 layout.

### Requirements / Outcomes

- Decide whether wolfBoot is referenced as a local clone, Git submodule, or vendored source.
- Keep generated wolfBoot outputs and private keys out of Git.
- Add or document a project-local STM32L4R5 wolfBoot target/build adaptation.
- Ensure STM32L4R5 HAL/CMSIS include paths are available to target ARM objects.
- Ensure Cortex-M4/thumb compiler flags apply to target ARM objects but not host keytools.
- Preserve ECDSA-P256 build configuration.
- Preserve the Phase 10d flash layout assumptions unless a documented issue requires revision.
- Capture build logs, return codes, artifact paths, and hashes through the existing `build-wolfboot` framework command.
- Add mocked unit tests for command/config handling.
- Add opt-in integration coverage only when wolfBoot source and required tools are available.
- Do not generate or commit private signing keys as durable project assets.
- Do not sign application images yet.
- Do not flash wolfBoot yet.
- Do not claim runtime boot success.

### Pass Criteria

- `build-wolfboot` produces a retained `wolfboot.elf` and records its SHA-256 when the local wolfBoot source and required toolchain are available.
- Unit tests remain hardware-free.
- Direct-flash baseline remains available.
- No signing, flashing, UART evidence, or secure-boot success is claimed.

---

## Phase 10g — Signing Key and Image-Signing Workflow - competed 29/6

### Goal

Add a safe signing workflow for the relocated application image.

### Requirements / Outcomes

- Define where signing keys are expected to live locally.
- Generate or use an ECDSA-P256 signing keypair without committing the private key.
- Ensure `.gitignore` or documentation prevents accidental private-key commits.
- Sign the relocated application image.
- Capture signed-image path, signature algorithm, signature size, and image hash in logs/manifest data.
- Add tests for signing command construction and metadata handling using fixtures or mocked runners.
- Update documentation and `AI_BUILD_GUIDE.md`.

### Pass Criteria

- Private signing key is not committed or included in replacement artifacts.
- Signed app image is produced by an explicit workflow.
- Manifest can record signing metadata.

---

## Phase 10h — Flash wolfBoot and Signed Application - completed 29/6

### Goal

Add a controlled workflow to flash both wolfBoot and the signed application image.

### Requirements / Outcomes

- Add a wolfBoot experiment profile that uses the wolfBoot boot config.
- Flash wolfBoot to the bootloader address.
- Flash the signed application to the application slot address.
- Record both flashed artifacts, hashes, offsets, return codes, and logs.
- Preserve provenance checks where applicable.
- Capture UART after flashing.
- Confirm boot only from user-provided UART logs.
- Add mocked unit tests for the two-artifact flash workflow.
- Add hardware test coverage as opt-in only.
- Update documentation and `AI_BUILD_GUIDE.md`.

### Pass Criteria

- Framework can orchestrate flashing both required images.
- Unit tests do not require hardware.
- Hardware success is only claimed after logs confirm the boot marker.

---

## Phase 10i — wolfBoot Positive Boot Evidence

### Goal

Confirm and record that the signed application boots through wolfBoot.

### Requirements / Outcomes

- Add or update UART boot markers so the log can distinguish direct-flash boot from wolfBoot-mediated boot.
- Capture UART after wolfBoot flash.
- Record boot-mode evidence in the manifest.
- Record `boot_mode`, `boot_crypto`, and signature metadata.
- Add pass/fail evaluation for the wolfBoot boot marker.
- Update documentation with expected UART evidence.

### Pass Criteria

- UART evidence shows the signed app boots through the intended boot path.
- Manifest records the boot security mode and relevant crypto metadata.
- No manual interpretation is required to distinguish the boot path.

---

## Phase 10j — Negative Boot Test for Corrupted Application

### Goal

Prove that wolfBoot refuses a corrupted or invalid signed application image.

### Requirements / Outcomes

- Add a controlled negative-test workflow that corrupts or invalidates the application image after signing.
- Flash wolfBoot plus the corrupted/invalid app.
- Capture UART or other evidence that the application did not boot.
- Avoid destructive or ambiguous test behaviour.
- Record the negative-test result in the manifest.
- Add mocked unit tests for negative-test orchestration.
- Add opt-in hardware test coverage only.
- Update documentation.

### Pass Criteria

- Corrupted app does not produce the normal application boot marker.
- Manifest clearly records the negative-test verdict.
- The test does not overwrite or destroy private signing material.

---

## Phase 10k — Boot Timing Instrumentation

### Goal

Measure and record secure-boot timing evidence.

### Requirements / Outcomes

- Add timing instrumentation sufficient to estimate or measure verification time.
- Record `verification_time_ms` in the manifest.
- Record the measurement method and limitations.
- Preserve direct-flash baseline timing where useful for comparison.
- Add tests for manifest fields and timing parsing.
- Update documentation.

### Pass Criteria

- Manifest includes `verification_time_ms`.
- The measurement source is documented.
- Timing values are not invented; unavailable timing is recorded explicitly.

---

## Phase 10l — Secure-Boot Manifest and Documentation Consolidation

### Goal

Consolidate secure-boot experiment metadata and documentation after the working wolfBoot path exists.

### Requirements / Outcomes

- Ensure manifest records:
  - `boot_mode`
  - `boot_crypto`
  - `signature_size`
  - `verification_time_ms`
- Ensure build, signing, flash, UART, and result evidence are linked coherently.
- Update relevant documentation, including:
  - README
  - architecture documentation
  - security/secrets documentation
  - `AI_BUILD_GUIDE.md`
- Confirm generated outputs and private keys remain ignored.
- Run unit tests and relevant opt-in integration/hardware tests where available.

### Pass Criteria

- Documentation matches the implemented workflow.
- Manifest schema is internally consistent.
- Known-good direct-flash baseline remains available.

---

# Suggested Verification Commands

## Early Config and Documentation Phases

```powershell
python -m pytest tests/unit
python -m pytest
```

## Local Build-Related Phases

```powershell
python -m pytest tests/unit
python -m pytest tests/integration -m integration --pqc-require-local-build
```

## Gateway / Hardware Phases

Run these only when the gateway and board are intentionally available:

```powershell
python -m pytest tests/integration/test_gateway_flash_helper.py -m integration --pqc-require-gateway
python -m pytest tests/hardware/test_baseline_uart.py -m hardware --pqc-require-hardware
```

## Direct-Flash Regression

```powershell
python scripts/experiment.py run --experiment configs/experiments/baseline_direct_uart.yaml
```

## wolfBoot-Specific Commands

The Phase 10f framework build-profile command is:

```powershell
python scripts/experiment.py build-wolfboot --profile configs/builds/wolfboot_stm32l4_ecdsa_p256.yaml
```

Until Phase 10f.1 is complete, this command may produce a controlled failed wolfBoot build record when upstream `TARGET=stm32l4` cannot yet use the project-local STM32L4R5 HAL/CMSIS target adaptation.

Exact signing, flash, UART, and secure-boot runtime commands should be defined only after the relevant configs and CLI behaviour exist.

---

# General Pass/Fail Expectations

- Unit tests pass without requiring hardware, SSH, UART, STM32 flashing, MQTT, VPN, or network impairment.
- Integration and hardware tests skip cleanly unless strict capability flags are supplied.
- Direct-flash baseline remains available throughout Phase 10.
- wolfBoot is not treated as working until build, flash, signing, and UART evidence exist.
- Private signing keys remain outside Git.
- Hardware success is only claimed from user-provided logs.

---

# Assumptions, Risks, and Unresolved Questions

## Assumptions

- The current direct-flash baseline should remain the stable regression target while wolfBoot support is added incrementally.
- Each sub-phase should be implemented in a separate prompt or small group of closely related prompts.
- Each implementation phase should update tests and documentation at the same time as behaviour changes.

## Risks

- The tentative `0x08020000` application offset may be wrong or incomplete until wolfBoot target requirements, STM32L4 flash geometry, slot/trailer requirements, and image format constraints are confirmed.
- wolfBoot target support for STM32L4R5 requires project-local adaptation; Phase 10f diagnostics showed upstream `TARGET=stm32l4` does not directly build against the current CubeMX HAL/CMSIS project layout.
- Signing-key handling must be kept isolated and explicit to avoid accidental private-key commits.

## Unresolved Questions

- Which wolfBoot version or commit will be used long-term?
- Will wolfBoot be vendored, included as a submodule, or referenced externally?
- Should the local clone at `tools/wolfboot` remain developer-local only until the dependency strategy is decided?
- What exact project-local STM32L4R5 wolfBoot target/build adaptation will keep target ARM flags separate from host keytools flags?
- Does the final flash layout require one slot, two slots, a swap area, or a metadata/trailer area?
- What exact UART marker should distinguish wolfBoot-mediated boot from direct-flash boot?
- What measurement source should be used for `verification_time_ms`?

