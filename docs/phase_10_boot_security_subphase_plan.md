# Phase 10 — Start Boot-Security Experiments: Sub-Phase Plan

## Purpose

This document breaks the proposed **Phase 10 — Start Boot-Security Experiments** scope into smaller implementation phases suitable for separate AI-assisted development prompts.

The intent is to state the **requirement and expected outcome** for each sub-phase, not to prescribe the exact implementation approach. Each implementation prompt should inspect the current repository files and decide the specific code, configuration, test, and documentation changes needed.

The direct-flash STM32 HAL baseline should remain the known-good regression path while boot-security support is introduced incrementally. wolfBoot should not be treated as implemented or working until build, signing, flashing, UART evidence, and documentation are in place.

Private signing keys, private certificates, credentials, and other secrets must remain out of Git.

---

## Phase 10a — Add Direct-Flash Boot Config Model - COMPLETED 27/6

## Phase 10b — Add Planned wolfBoot Boot Config Placeholder - COMPLETED 27/6

## Phase 10c — wolfBoot STM32L4 Target Support Assessment - COMPLETED 29/6

## Phase 10d — Define Secure-Boot Flash Layout - COMPLETED 29/6

## Phase 10e — Relocate HAL Application for Bootloader Launch  - COMPLETED 29/6

## Phase 10f — Add wolfBoot Build Profile - COMPLETED 29/6

## Phase 10f.1 — Project-Local wolfBoot STM32L4R5 Target Adaptation - completed 29/6

## Phase 10g — Signing Key and Image-Signing Workflow - competed 29/6

## Phase 10h — Flash wolfBoot and Signed Application - completed 29/6

## Phase 10i — wolfBoot Positive Boot Evidence - completed 29/6

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

## Phase 10j — Negative Boot Test for Corrupted Application - completed 29/6

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

